"""Changed-path discovery, classification, impact inference, and check routing."""

import json
import subprocess
from pathlib import PurePosixPath

from .output import envelope
from .registry import load_registry

SEMANTIC_IMPACTS = {
    "shared-behavior",
    "rom-purpose-variance",
    "emulator-evidence",
    "regional-integrity",
}

BUILD_SOURCES = {
    "Makefile",
    "audio_rules.mk",
    "config.mk",
    "graphics_file_rules.mk",
    "json_data_rules.mk",
    "make_tools.mk",
    "map_data_rules.mk",
    "persistent_id_rules.mk",
    "spritesheet_rules.mk",
    "trainer_rematch_rules.mk",
    "trainer_rules.mk",
}


def changed_paths(root, *, base=None, explicit=()):
    if explicit:
        return sorted({_safe_path(path) for path in explicit}), "explicit"
    reference = base or "HEAD"
    result = subprocess.run(
        ["git", "diff", "--name-status", "-z", "--find-renames", reference],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    )
    paths = _parse_name_status(result.stdout)
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    paths.update(
        part.decode("utf-8", "surrogateescape")
        for part in untracked.split(b"\0")
        if part
    )
    return sorted(paths), ("base" if base else "working-tree")


def _parse_name_status(data):
    fields = data.split(b"\0")
    paths = set()
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index].decode("ascii", "replace")
        index += 1
        count = 2 if status[:1] in {"R", "C"} else 1
        for _ in range(count):
            if index < len(fields) and fields[index]:
                paths.add(fields[index].decode("utf-8", "surrogateescape"))
            index += 1
    return paths


def _safe_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not value:
        raise ValueError(f"path must stay within the repository: {value}")
    return path.as_posix()


def _owned_paths(root):
    owned = {}
    ports = root / "tools/content_port/ports"
    for manifest in sorted(ports.glob("*/ownership.json")):
        try:
            document = json.loads(manifest.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        port = document.get("port", manifest.parent.name)
        for unit in document.get("units", []):
            path = unit.get("path")
            if path:
                owned[path] = {
                    "kind": "content-port",
                    "port": port,
                    "unitKind": unit.get("kind"),
                }
    return owned


def classify(root, path, owned):
    parts = PurePosixPath(path).parts
    authority = "unknown"
    materialization = "authored"
    generator = None
    editable = True
    if (
        path.startswith("data/maps/")
        or path.startswith("data/layouts/")
        or path in {"data/maps/map_groups.json", "data/layouts/layouts.json"}
    ):
        authority = "map-source"
    elif path in {
        "src/data/trainers.party",
        "src/data/trainers_frlg.party",
        "src/data/debug_trainers.party",
    }:
        authority = "trainer-source"
        generator = {"tool": "tools/trainerproc", "outputs": ["src/data/trainers.h"]}
    elif (
        path.startswith("tools/persistence/")
        or path == "tools/integrity/save_contract.json"
        or path == "src/data/persistence/persistent_ids.json"
    ):
        authority = "persistence-source"
    elif path.startswith("tools/content_port/"):
        authority = "content-port-policy"
    elif path.startswith(".github/workflows/"):
        authority = "workflow-source"
    elif path in BUILD_SOURCES:
        authority = "build-source"
    elif path.startswith("test/") or "/tests/" in path:
        authority = "test-source"
    elif path.startswith(("src/", "include/", "data/", "asm/", "graphics/", "sound/")):
        authority = "engine-source"
    elif path.startswith("tools/"):
        authority = "tool-source"
    elif path.startswith("docs/") or path in {"README.md", "AGENTS.md"}:
        authority = "documentation-source"
    generated = {
        "src/data/trainers.h": "src/data/trainers.party",
        "src/data/trainers_frlg.h": "src/data/trainers_frlg.party",
        "src/data/debug_trainers.h": "src/data/debug_trainers.party",
        "src/data/map_group_count.h": "data/maps/map_groups.json",
        "include/constants/heal_locations.h": "data/heal_locations.json",
        "include/constants/script_commands.h": "data/script_cmd_table.inc",
    }
    if path in generated:
        materialization = "generated"
        editable = False
        generator = {"source": generated[path], "tool": "Make dependency graph"}
    elif parts[:1] == ("build",):
        materialization = "build-output"
        editable = False
    ownership = owned.get(path, {"kind": "repository"})
    if ownership["kind"] == "content-port":
        materialization = "imported"
        editable = False
        generator = {
            "tool": "tools.content_port",
            "policy": f"tools/content_port/ports/{ownership['port']}/ownership.json",
        }
    inferred_impacts = {
        "map-source": ["map-data", "rom-data"],
        "trainer-source": ["trainer-data", "rom-data"],
        "persistence-source": ["persistence", "rom-data"],
        "content-port-policy": ["content-port"],
        "workflow-source": ["workflow"],
        "build-source": ["build-orchestration"],
        "test-source": ["tests"],
        "engine-source": ["product-mechanics"],
        "tool-source": ["tooling"],
        "documentation-source": ["documentation"],
        "unknown": ["shared-behavior", "unknown"],
    }[authority]
    return {
        "path": path,
        "authority": authority,
        "materialization": materialization,
        "ownership": ownership,
        "generator": generator,
        "editable": editable,
        "impacts": inferred_impacts,
    }


def infer(paths, explicit_impacts):
    impacts = set(explicit_impacts)
    checks = {}
    definitions = load_registry()["checks"]

    def add(check_id, tier, reason):
        registered_tier = definitions[check_id]["tier"]
        if tier != registered_tier:
            raise ValueError(
                f"check tier drift for {check_id}: {tier} != {registered_tier}"
            )
        checks.setdefault(check_id, {"id": check_id, "tier": tier, "reason": reason})

    unknown = False
    python = False
    for item in paths:
        path = item["path"]
        authority = item["authority"]
        impacts.update(item["impacts"])
        if authority == "unknown":
            unknown = True
        if path.endswith(".py"):
            python = True
        if authority == "workflow-source":
            add("actionlint", "required", "workflow changed")
            parameters = checks["actionlint"].setdefault(
                "parameters", {"workflows": []}
            )
            parameters["workflows"].append(path)
            if path == ".github/workflows/release.yml":
                add("release-self-test", "required", "release workflow changed")
        if authority == "build-source":
            add("make-isolation-test", "iteration", "Make orchestration changed")
            add(
                "debug-check",
                "required",
                "build orchestration can affect ROM artifacts",
            )
        if (
            authority == "content-port-policy"
            or item["ownership"]["kind"] == "content-port"
        ):
            add(
                "content-port-test",
                "required",
                "content-port policy or owned unit changed",
            )
            add(
                "content-port-ownership-check",
                "required",
                "content-port ownership must remain valid",
            )
        if "wild_encounter" in path or "wild_encounters" in path:
            add("wild-encounter-test", "required", "wild encounter source changed")
        if path.startswith("tools/agent/"):
            add("agent-test", "required", "bounded agent interface changed")
        if authority in {"map-source", "trainer-source", "persistence-source"}:
            add(
                "debug-check",
                "required",
                f"{authority} affects generated or linked ROM data",
            )
        if authority == "engine-source":
            add("product-check", "required", "Pokemon OpenWorld C behavior changed")
        if authority == "persistence-source":
            impacts.add("rom-purpose-variance")
    if python:
        add("format-check", "required", "Python changed")
        add("lint-check", "required", "Python changed")
    if unknown:
        impacts.add("shared-behavior")
        add(
            "check",
            "conditional",
            "unknown path is conservatively treated as shared behavior",
        )
        add("debug-check", "required", "unknown path requires ROM-purpose coverage")
    if "shared-behavior" in impacts:
        add("check", "conditional", "shared or inherited behavior may be affected")
    if "rom-purpose-variance" in impacts:
        add(
            "integrity-check-rom-purposes",
            "conditional",
            "behavior can differ by ROM purpose",
        )
    if "emulator-evidence" in impacts:
        add("e2e-core", "conditional", "runtime behavior needs emulator evidence")
    if "regional-integrity" in impacts:
        add(
            "e2e-integrity",
            "conditional",
            "regional traversal or integrity coverage is needed",
        )
    order = {"iteration": 0, "required": 1, "conditional": 2}
    return sorted(impacts), sorted(
        checks.values(), key=lambda check: (order[check["tier"]], check["id"])
    )


def build_context(root, *, base=None, explicit=(), explicit_impacts=()):
    explicit = tuple(explicit)
    invalid = sorted(set(explicit_impacts) - SEMANTIC_IMPACTS)
    if invalid:
        raise ValueError(f"unknown impact: {', '.join(invalid)}")
    paths, mode = changed_paths(root, base=base, explicit=explicit)
    owned = _owned_paths(root)
    items = [classify(root, path, owned) for path in paths]
    impacts, checks = infer(items, explicit_impacts)
    result = envelope(
        summary=f"classified {len(items)} changed path(s)",
        inputs={
            "mode": mode,
            "base": base,
            "paths": paths if explicit else [],
            "explicitImpacts": sorted(explicit_impacts),
        },
    )
    result["items"] = items
    result["impacts"] = impacts
    result["checks"] = checks
    return result
