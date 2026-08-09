#!/usr/bin/env python3
"""Rebuild and capture the populated historical compatibility fixture."""

import argparse
from dataclasses import asdict
import difflib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

from tools.e2e.save_journey import (
    SaveScenarioRequest,
    representative_saved_semantics,
    run_save_scenario,
    save_from_start_menu,
)
from tools.e2e.save_file import SaveImage
from tools.e2e.skyemu import SkyEmuSession, Symbols


SOURCE_COMMIT = "135b32ca92"
INSTRUMENTED_ROM_SHA256 = (
    "b68fc2d33a3a6446da2af055be27e04b3ab7ef1ccba540395a9c44d9937ab07f"
)
# Updated only when the reviewed, canonical source overlay intentionally changes.
INSTRUMENTATION_PATCH_SHA256 = (
    "9ccc7ce7aca9bd1e1d3c30bc0571b80d42b176902b7f70bf10a8d6483f2333cd"
)
POPULATED_SAVE_SHA256 = (
    "6ea2d26f4b431543c31c50015678b5c8fc4c3b60d41aba6c7311fd064234448c"
)
ORACLE_PATH = Path("tools/e2e/fixtures/hoenn_populated_oracle.json")
OVERLAY_FILES = (
    "include/battle_tower.h",
    "include/daycare.h",
    "include/lilycove_lady.h",
    "include/trade.h",
    "src/battle_tower.c",
    "src/daycare.c",
    "src/load_save.c",
    "src/lilycove_lady.c",
    "src/trade.c",
    "include/debug_save_scenario.h",
    "src/debug_save_scenario.c",
)

REQUEST = SaveScenarioRequest(
    request_id=0x48495354,
    party_species=25,
    box_species=263,
    daycare_species_1=263,
    daycare_species_2=132,
    trade_species=273,
    reward_item=102,
    checkpoint_id=14,
    level=10,
    facility_id=0,
    facility_level_mode=0,
    trainer_id=64,
)


def _git_file(source_tree: Path, commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(source_tree), "show", f"{commit}:{path}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout


def instrumentation_overlay(
    source_tree: Path,
) -> tuple[dict[str, bytes], dict[str, bytes]]:
    """Return historical bases and the exact tracked-source overlay to apply."""
    bases: dict[str, bytes] = {}
    overlay: dict[str, bytes] = {}
    for path in OVERLAY_FILES:
        current = (source_tree / path).read_bytes()
        overlay[path] = current
        try:
            bases[path] = _git_file(source_tree, SOURCE_COMMIT, path)
        except subprocess.CalledProcessError:
            bases[path] = b""

    main_path = "src/main.c"
    main = _git_file(source_tree, SOURCE_COMMIT, main_path)
    text = main.decode()
    include_anchor = '#include "integrity_map_load.h"\n'
    update_anchor = "        IntegrityMapLoad_Update();\n"
    if text.count(include_anchor) != 1 or text.count(update_anchor) != 1:
        raise ValueError("historical main.c no longer has the reviewed DEBUG anchors")
    text = text.replace(
        include_anchor,
        include_anchor + '#include "debug_save_scenario.h"\n',
    ).replace(
        update_anchor,
        update_anchor + "        DebugSaveScenario_Update();\n",
    )
    bases[main_path] = main
    overlay[main_path] = text.encode()
    return bases, overlay


def canonical_patch(bases: dict[str, bytes], overlay: dict[str, bytes]) -> bytes:
    """Produce path-stable unified-diff bytes for provenance hashing."""
    chunks: list[str] = []
    for path in sorted(overlay):
        old = bases[path].decode().splitlines()
        new = overlay[path].decode().splitlines()
        chunks.extend(
            line + "\n"
            for line in difflib.unified_diff(
                old,
                new,
                fromfile=f"a/{path}" if old else "/dev/null",
                tofile=f"b/{path}",
                lineterm="",
            )
        )
    return "".join(chunks).encode()


def overlay_sha256(bases: dict[str, bytes], overlay: dict[str, bytes]) -> str:
    return hashlib.sha256(canonical_patch(bases, overlay)).hexdigest()


def _export_source(source_tree: Path, destination: Path) -> None:
    process = subprocess.Popen(
        ["git", "-C", str(source_tree), "archive", SOURCE_COMMIT],
        stdout=subprocess.PIPE,
    )
    assert process.stdout is not None
    with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
        archive.extractall(destination, filter="data")
    if process.wait() != 0:
        raise subprocess.CalledProcessError(process.returncode, process.args)


def build_instrumented_source(
    source_tree: Path, destination: Path
) -> tuple[Path, Path]:
    bases, overlay = instrumentation_overlay(source_tree)
    digest = overlay_sha256(bases, overlay)
    if digest != INSTRUMENTATION_PATCH_SHA256:
        raise ValueError(
            "historical instrumentation overlay digest mismatch: "
            f"expected={INSTRUMENTATION_PATCH_SHA256}, actual={digest}"
        )
    _export_source(source_tree, destination)
    for path, data in overlay.items():
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    # An archive intentionally has no .git directory; this is the upstream
    # build system's explicit acknowledgement for source archives.
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
        stdout=subprocess.DEVNULL,
    )
    rom = destination / "pokemon-openworld-debug.gba"
    symbols = destination / "pokemon-openworld-debug.sym"
    actual_rom_digest = hashlib.sha256(rom.read_bytes()).hexdigest()
    if actual_rom_digest != INSTRUMENTED_ROM_SHA256:
        raise ValueError(
            "instrumented historical ROM digest mismatch: "
            f"expected={INSTRUMENTED_ROM_SHA256}, actual={actual_rom_digest}"
        )
    return rom, symbols


def verify_reviewed_oracle(
    image, result, oracle: dict, *, semantic_decoder=representative_saved_semantics
) -> dict:
    """Reject capture/parser drift; never derive or update the reviewed oracle."""
    blocks = {
        "saveBlock1": image.active_slot.save_block1,
        "saveBlock2": image.active_slot.save_block2,
        "pokemonStorage": image.active_slot.pokemon_storage,
    }
    for expectation in oracle["rawSerializedExpectations"]:
        offset = expectation["offset"]
        length = expectation["length"]
        actual = blocks[expectation["block"]][offset : offset + length].hex()
        if actual != expectation["hex"]:
            raise ValueError(
                "historical fixture raw oracle mismatch for "
                f"{expectation['meaning']}: expected={expectation['hex']}, actual={actual}"
            )
    reviewed = oracle["reviewedSemanticExpectations"]
    actual_semantics = semantic_decoder(image, result)
    if actual_semantics != reviewed:
        raise ValueError(
            "historical fixture semantic decoder disagrees with immutable reviewed oracle"
        )
    return reviewed


def publish_fixture(output: Path, image, result, oracle: dict) -> dict:
    """Validate completely, then publish a coherent save/manifest pair."""
    reviewed_semantics = verify_reviewed_oracle(image, result, oracle)
    if image.sha256 != POPULATED_SAVE_SHA256:
        raise ValueError(
            "historical fixture full-image digest mismatch: "
            f"expected={POPULATED_SAVE_SHA256}, actual={image.sha256}"
        )
    document = {
        "fixture": {
            "file": output.with_suffix(".sav").name,
            "sha256": image.sha256,
            "sourceCommit": SOURCE_COMMIT,
            "sourceRomSha256": INSTRUMENTED_ROM_SHA256,
            "instrumentationPatchSha256": INSTRUMENTATION_PATCH_SHA256,
        },
        "generation": {
            "method": "source-build DEBUG hook using genuine game services, then two field Start-menu Saves to replace both flash slots",
            "request": asdict(REQUEST),
            "result": asdict(result),
        },
        "semanticExpectations": reviewed_semantics,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    save_path = output.with_suffix(".sav")
    with tempfile.TemporaryDirectory(
        prefix=f".{output.stem}-publish-", dir=output.parent
    ) as staging_directory:
        staging = Path(staging_directory)
        staged_save = staging / save_path.name
        staged_manifest = staging / output.name
        staged_save.write_bytes(image.data)
        staged_manifest.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n"
        )

        # Reparse the staged flash and manifest before either tracked
        # destination is touched. This catches truncation/serialization drift.
        staged_image = SaveImage.from_path(staged_save)
        if staged_image.sha256 != document["fixture"]["sha256"]:
            raise ValueError("staged historical fixture digest mismatch")
        if json.loads(staged_manifest.read_text()) != document:
            raise ValueError("staged historical manifest serialization mismatch")
        verify_reviewed_oracle(staged_image, result, oracle)

        os.replace(staged_save, save_path)
        os.replace(staged_manifest, output)
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-tree", type=Path, default=Path.cwd())
    parser.add_argument("--skyemu", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--candidate-output",
        type=Path,
        help="optional unreviewed capture path for intentional oracle updates",
    )
    args = parser.parse_args()
    source_tree = args.source_tree.resolve()
    skyemu = args.skyemu.resolve()
    output = args.output.resolve()
    oracle = json.loads((source_tree / ORACLE_PATH).read_text())

    with tempfile.TemporaryDirectory(prefix="historical-save-fixture-") as temporary:
        temporary_path = Path(temporary)
        historical_tree = temporary_path / "source"
        historical_tree.mkdir()
        rom, symbols = build_instrumented_source(source_tree, historical_tree)
        game = SkyEmuSession(
            binary=skyemu,
            rom=rom,
            symbols=Symbols(symbols),
            workdir=temporary_path / "emulator",
        )
        try:
            game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
            for _ in range(3_000):
                game.press("Select")
                if game.callback_is("CB2_Overworld"):
                    break
            else:
                raise AssertionError("historical Quickstart did not reach overworld")
            game.wait_for_controls_unlocked(max_frames=1_200)
            result = run_save_scenario(game, REQUEST)
            save_from_start_menu(game)
            game.wait_for_controls_unlocked(max_frames=1_200)
            # Replace both rotating flash slots so the fixture contains no
            # stale pre-scenario Quickstart slot with unreviewed entropy.
            image = save_from_start_menu(game)
        finally:
            game.close()

    if args.candidate_output is not None:
        candidate_output = args.candidate_output.resolve()
        candidate_output.parent.mkdir(parents=True, exist_ok=True)
        candidate_output.with_suffix(".sav").write_bytes(image.data)
        candidate_output.write_text(
            json.dumps(
                {
                    "reviewStatus": "UNREVIEWED_CANDIDATE_DO_NOT_USE_AS_ORACLE",
                    "result": asdict(result),
                    "decodedSemantics": representative_saved_semantics(image, result),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    publish_fixture(output, image, result, oracle)


if __name__ == "__main__":
    main()
