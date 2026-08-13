#!/usr/bin/env python3
"""Reproduce the historical field-capability oracle for legacy-save variants."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Callable, Sequence

from tools.e2e.generate_populated_fixture import (
    SOURCE_COMMIT,
    _export_source,
    _git_file,
    canonical_patch,
)
from tools.e2e.save_file import SaveImage, with_saved_flags
from tools.e2e.save_journey import probe_field_move
from tools.e2e.skyemu import SkyEmuSession, Symbols


ORACLE_PATH = Path("tools/e2e/fixtures/regional_cut_oracle.json")
BASE_FIXTURE_PATH = Path("tools/e2e/fixtures/hoenn_continue.sav")
CAPABILITIES = (
    ("CUT", 0, 0x867),
    ("FLASH", 1, 0x868),
    ("ROCK_SMASH", 2, 0x869),
    ("STRENGTH", 3, 0x86A),
    ("SURF", 4, 0x86B),
    ("FLY", 5, 0x86C),
    ("DIVE", 6, 0x86D),
    ("WATERFALL", 7, 0x86E),
)
LEGACY_FLAGS = tuple(flag for _, _, flag in CAPABILITIES)
MATRIX = (("none", None),) + tuple(
    (f"slot{index}", index - 1) for index in range(1, len(CAPABILITIES) + 1)
)
OVERLAY_FILES = (
    "include/debug_field_move_probe.h",
    "src/debug_field_move_probe.c",
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def load_reviewed_oracle(path: Path) -> dict:
    """Load only the exact, reviewed historical capability oracle contract."""
    oracle = json.loads(path.read_text())
    if not isinstance(oracle, dict) or set(oracle) != {
        "schemaVersion",
        "source",
        "matrix",
    }:
        raise ValueError("reviewed capability oracle has malformed top-level keys")
    if type(oracle["schemaVersion"]) is not int or oracle["schemaVersion"] != 2:
        raise ValueError("reviewed capability oracle has unsupported schemaVersion")

    source = oracle["source"]
    source_keys = {
        "commit",
        "baseFixture",
        "baseFixtureSha256",
        "instrumentationPatchSha256",
        "instrumentedRomSha256",
    }
    if not isinstance(source, dict) or set(source) != source_keys:
        raise ValueError("reviewed capability oracle has malformed source keys")
    if source["commit"] != SOURCE_COMMIT:
        raise ValueError("reviewed capability oracle has unexpected source commit")
    if source["baseFixture"] != BASE_FIXTURE_PATH.name:
        raise ValueError("reviewed capability oracle has unexpected base fixture")
    for key in (
        "baseFixtureSha256",
        "instrumentationPatchSha256",
        "instrumentedRomSha256",
    ):
        if not isinstance(source[key], str) or not SHA256_PATTERN.fullmatch(
            source[key]
        ):
            raise ValueError(f"reviewed capability oracle has malformed {key}")

    matrix = oracle["matrix"]
    if not isinstance(matrix, list) or len(matrix) != len(MATRIX):
        raise ValueError("reviewed capability oracle has malformed matrix")
    for item, (name, granted_index) in zip(matrix, MATRIX, strict=True):
        if not isinstance(item, dict) or set(item) != {
            "name",
            "legacySlots",
            "unlockedCapabilities",
        }:
            raise ValueError("reviewed capability oracle has malformed matrix keys")
        expected_slots = [index == granted_index for index in range(len(CAPABILITIES))]
        expected_unlocked = (
            [] if granted_index is None else [CAPABILITIES[granted_index][0]]
        )
        if (
            item["name"] != name
            or item["legacySlots"] != expected_slots
            or any(type(value) is not bool for value in item["legacySlots"])
            or item["unlockedCapabilities"] != expected_unlocked
        ):
            raise ValueError("reviewed capability oracle has malformed matrix entry")
    return oracle


def instrumentation_overlay(
    source_tree: Path,
) -> tuple[dict[str, bytes], dict[str, bytes]]:
    bases: dict[str, bytes] = {}
    overlay: dict[str, bytes] = {}
    for path in OVERLAY_FILES:
        try:
            bases[path] = _git_file(source_tree, SOURCE_COMMIT, path)
        except subprocess.CalledProcessError:
            bases[path] = b""
        overlay[path] = (source_tree / path).read_bytes()

    main_path = "src/main.c"
    main = _git_file(source_tree, SOURCE_COMMIT, main_path)
    text = main.decode()
    include_anchor = '#include "integrity_map_load.h"\n'
    update_anchor = "        IntegrityMapLoad_Update();\n"
    if text.count(include_anchor) != 1 or text.count(update_anchor) != 1:
        raise ValueError("historical main.c no longer has the reviewed DEBUG anchors")
    text = text.replace(
        include_anchor,
        include_anchor + '#include "debug_field_move_probe.h"\n',
    ).replace(
        update_anchor,
        update_anchor + "        DebugFieldMoveProbe_Update();\n",
    )
    bases[main_path] = main
    overlay[main_path] = text.encode()
    return bases, overlay


def build_instrumented_source(
    source_tree: Path, destination: Path
) -> tuple[Path, Path, str]:
    bases, overlay = instrumentation_overlay(source_tree)
    patch_digest = hashlib.sha256(canonical_patch(bases, overlay)).hexdigest()
    _export_source(source_tree, destination)
    for path, data in overlay.items():
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (destination / ".histignore").touch()

    subprocess.run(
        [
            "make",
            "-j2",
            "DEBUG=1",
            "pokemon-openworld-debug.gba",
            "pokemon-openworld-debug.sym",
        ],
        cwd=destination,
        check=True,
    )
    return (
        destination / "pokemon-openworld-debug.gba",
        destination / "pokemon-openworld-debug.sym",
        patch_digest,
    )


def _continue_to_overworld(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(1_500):
        game.press("A")
        if game.callback_is("CB2_Overworld"):
            break
    else:
        raise AssertionError("historical capability fixture did not Continue")
    game.wait_for_controls_unlocked(max_frames=1_200)


def capture_oracle(source_tree: Path, skyemu: Path) -> dict:
    base = SaveImage.from_path(source_tree / BASE_FIXTURE_PATH)
    with tempfile.TemporaryDirectory(prefix="historical-cut-oracle-") as temporary:
        root = Path(temporary)
        historical_tree = root / "source"
        historical_tree.mkdir()
        rom, symbols, patch_digest = build_instrumented_source(
            source_tree, historical_tree
        )
        results = []
        for index, (name, granted_index) in enumerate(MATRIX):
            legacy_slots = [
                slot_index == granted_index for slot_index in range(len(CAPABILITIES))
            ]
            variant = with_saved_flags(
                base,
                dict(zip(LEGACY_FLAGS, legacy_slots, strict=True)),
            )
            save = root / f"{name}.sav"
            save.write_bytes(variant.data)
            game = SkyEmuSession(
                binary=skyemu,
                rom=rom,
                symbols=Symbols(symbols),
                workdir=root / f"emulator-{name}",
                battery_save=save,
            )
            try:
                _continue_to_overworld(game)
                unlocked = [
                    capability
                    for move_index, (capability, field_move, _) in enumerate(
                        CAPABILITIES
                    )
                    if probe_field_move(
                        game,
                        field_move,
                        0x43415000 + index * len(CAPABILITIES) + move_index,
                    )
                ]
            finally:
                game.close()
            results.append(
                {
                    "name": name,
                    "legacySlots": legacy_slots,
                    "unlockedCapabilities": unlocked,
                }
            )

        return {
            "schemaVersion": 2,
            "source": {
                "commit": SOURCE_COMMIT,
                "baseFixture": BASE_FIXTURE_PATH.name,
                "baseFixtureSha256": base.sha256,
                "instrumentationPatchSha256": patch_digest,
                "instrumentedRomSha256": hashlib.sha256(rom.read_bytes()).hexdigest(),
            },
            "matrix": results,
        }


def run(
    argv: Sequence[str] | None = None,
    *,
    capture: Callable[[Path, Path], dict] = capture_oracle,
) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-tree", type=Path, default=Path.cwd())
    parser.add_argument("--skyemu", type=Path, required=True)
    parser.add_argument("--candidate-output", type=Path)
    args = parser.parse_args(argv)
    source_tree = args.source_tree.resolve()
    reviewed_path = (source_tree / ORACLE_PATH).resolve()
    candidate_output = (
        None if args.candidate_output is None else args.candidate_output.resolve()
    )
    if candidate_output == reviewed_path:
        raise ValueError(
            "candidate output cannot overwrite the reviewed capability oracle"
        )

    actual = capture(source_tree, args.skyemu.resolve())
    if args.candidate_output is not None:
        candidate_output.write_text(
            json.dumps(
                {
                    "reviewStatus": "UNREVIEWED_CANDIDATE_DO_NOT_USE_AS_ORACLE",
                    **actual,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        return

    reviewed = load_reviewed_oracle(reviewed_path)
    if actual != reviewed:
        raise ValueError(
            "historical capability oracle reproduction disagrees with review"
        )


def main() -> None:
    run()


if __name__ == "__main__":
    main()
