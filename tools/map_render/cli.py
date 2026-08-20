"""Command-line interface for exterior-map renders and metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Sequence

from .catalog import (
    MapRenderError,
    build_catalog,
    default_config_path,
    default_schema_path,
    discover,
    load_config,
)
from .renderer import render


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="python3 -m tools.map_render")
    commands = result.add_subparsers(dest="command", required=True)

    regions = commands.add_parser("regions", help="list configured regions and maps")
    _common_arguments(regions)

    render_command = commands.add_parser(
        "render", help="render exterior maps and write catalog.json"
    )
    _common_arguments(render_command)
    render_command.add_argument(
        "--output", type=Path, default=Path("build/map-catalog")
    )
    render_command.add_argument(
        "--region",
        action="append",
        default=[],
        help="render only this region; repeat to select more than one",
    )
    render_command.add_argument(
        "--source-revision",
        help="revision recorded in catalog.json; defaults to the repository HEAD",
    )
    return result


def _common_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--repo", type=Path, default=Path.cwd())
    command.add_argument("--config", type=Path, default=default_config_path())


def _git_output(repo: Path, arguments: list[str]) -> str | None:
    process = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return process.stdout.strip() if process.returncode == 0 else None


def _source_state(repo: Path, revision: str | None) -> tuple[str, bool]:
    resolved_revision = revision or _git_output(repo, ["rev-parse", "HEAD"])
    if resolved_revision is None:
        resolved_revision = "unknown"
    status = _git_output(repo, ["status", "--porcelain=v1", "--untracked-files=normal"])
    return resolved_revision, bool(status) if status is not None else False


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def _select_targets(discovery, selected_regions: Sequence[str]):
    known_regions = {region["id"] for region in discovery.config["regions"]}
    unknown = sorted(set(selected_regions) - known_regions)
    if unknown:
        raise MapRenderError(f"unknown region: {', '.join(unknown)}")
    selected = set(selected_regions) or known_regions
    return tuple(target for target in discovery.targets if target.region_id in selected)


def _render(arguments: argparse.Namespace) -> int:
    repo = arguments.repo.resolve()
    output = arguments.output.resolve()
    revision, dirty = _source_state(repo, arguments.source_revision)
    discovery = discover(repo, load_config(arguments.config))
    targets = _select_targets(discovery, arguments.region)
    image_hashes = {}
    for target in targets:
        image_path = output / target.image_path
        render(repo, target.name, image_path, announce=False)
        image_hashes[target.name] = hashlib.sha256(image_path.read_bytes()).hexdigest()
    catalog = build_catalog(
        discovery,
        targets,
        image_hashes,
        source_revision=revision,
        working_tree_dirty=dirty,
    )
    _write_json(output / "catalog.json", catalog)
    _write_json(
        output / "catalog.schema.json", json.loads(default_schema_path().read_text())
    )
    counts = {region["id"]: region["mapCount"] for region in catalog["regions"]}
    summary = ", ".join(f"{region}: {count}" for region, count in counts.items())
    print(f"rendered {len(targets)} exterior maps ({summary}) -> {output}")
    return 0


def _regions(arguments: argparse.Namespace) -> int:
    discovery = discover(arguments.repo.resolve(), load_config(arguments.config))
    for region in discovery.config["regions"]:
        count = sum(target.region_id == region["id"] for target in discovery.targets)
        print(f"{region['id']}\t{count}\t{region['label']}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "regions":
            return _regions(arguments)
        if arguments.command == "render":
            return _render(arguments)
    except (ValueError, OSError) as error:
        parser().error(str(error))
    raise AssertionError(f"unhandled command: {arguments.command}")
