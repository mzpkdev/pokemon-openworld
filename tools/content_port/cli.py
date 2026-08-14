"""Command-line entry points for the region-neutral content-port engine."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from types import MappingProxyType
from typing import Mapping, Sequence

from .errors import ContentPortError
from .transaction import (
    apply_bundle,
    recover_transaction,
    require_no_active_transaction,
    resume_transaction,
)


def _repo(value: str) -> Path:
    path = Path(value).resolve()
    if not (path / ".git").exists():
        raise argparse.ArgumentTypeError(f"not a Git worktree: {value}")
    return path


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_report(path: Path, report: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical_json(report))
    temporary.replace(path)


def _port_dir(repo: Path, port: str) -> Path:
    return repo / "tools" / "content_port" / "ports" / port


def verify_ownership(repo: Path, port: str) -> None:
    """Verify installed content and local permission evidence without donors."""

    require_no_active_transaction(repo)
    from .descriptor import read_json
    from .ownership import OwnershipManifest
    from .update import validate_assets

    port_dir = _port_dir(repo, port)
    OwnershipManifest.load(port_dir / "ownership.json").verify(repo)
    descriptor = read_json(port_dir / "port.json")
    if not isinstance(descriptor, Mapping):
        raise ContentPortError("port.json: expected an object")
    asset_policy = descriptor.get("assetPolicy")
    if (
        not isinstance(asset_policy, str)
        or not asset_policy
        or Path(asset_policy).name != asset_policy
    ):
        raise ContentPortError("port.json: invalid assetPolicy path")
    assets = read_json(port_dir / asset_policy)
    if not isinstance(assets, Mapping):
        raise ContentPortError(f"{asset_policy}: expected an object")
    validate_assets(assets, evidence_root=repo, require_redistributable=True)


def check_port(
    repo: Path,
    port: str,
    donor_root: Path,
    *,
    compare_report: Path | None = None,
    write_report: Path | None = None,
) -> dict[str, object]:
    """Load every authored policy and authenticate every donor pin."""

    require_no_active_transaction(repo)
    from .descriptor import load_port
    from .donors import authenticated_donor_snapshot
    from .sources import validate_port_sources
    from .update import validate_assets

    descriptor = load_port(_port_dir(repo, port), donor_root.resolve())
    validate_assets(
        descriptor.assets,
        evidence_root=repo,
        require_redistributable=True,
    )
    with authenticated_donor_snapshot(descriptor.donors) as snapshots:
        snapshot_by_name = {pin.name: pin for pin in snapshots}
        expected_names = {pin.name for pin in descriptor.donors}
        if set(snapshot_by_name) != expected_names:
            raise ContentPortError(
                "authenticated donor snapshot does not match descriptor"
            )
        snapshot_descriptor = replace(
            descriptor,
            donors=tuple(snapshot_by_name[pin.name] for pin in descriptor.donors),
            donors_by_role=MappingProxyType(
                {
                    role: snapshot_by_name[pin.name]
                    for role, pin in descriptor.donors_by_role.items()
                }
            ),
        )
        contract = validate_port_sources(snapshot_descriptor, repo)
        body = dict(contract.to_report())
        contract_evidence = dict(body["evidence"])
        contract_evidence["donors"] = {
            role: {
                "commit": pin.commit,
                "sourceTreeDigest": pin.tree_digest,
                "fileCount": pin.file_count,
            }
            for role, pin in snapshot_descriptor.donors_by_role.items()
        }
        body["evidence"] = contract_evidence
    report: dict[str, object] = {
        "schemaVersion": 1,
        "producer": "tools.content_port",
        **body,
    }
    if compare_report is not None:
        try:
            expected = json.loads(compare_report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ContentPortError(
                f"cannot load comparison report {compare_report}: {error}"
            ) from error
        if not isinstance(expected, dict):
            raise ContentPortError("comparison report must be a JSON object")
        _compare_equivalence(report, expected, compare_report)
    if write_report is not None:
        _write_report(write_report, report)
    return report


def _compare_equivalence(
    actual: Mapping[str, object], expected: Mapping[str, object], source: Path
) -> None:
    """Compare the closure fields shared by legacy and graph-native reports."""

    def equivalent(left: object, right: object) -> bool:
        return _canonical_json(left) == _canonical_json(right)

    if not equivalent(actual.get("inventory"), expected.get("inventory")):
        raise ContentPortError(f"content-port inventory differs from {source}")
    actual_closure = actual.get("closure")
    expected_closure = expected.get("closure")
    if not isinstance(actual_closure, dict) or not isinstance(expected_closure, dict):
        raise ContentPortError("comparison reports require closure objects")
    shared_closure = (
        "maps",
        "layouts",
        "groups",
        "sections",
        "tilesets",
        "symbols",
        "deferred_edges",
    )
    for field in shared_closure:
        if not equivalent(actual_closure.get(field), expected_closure.get(field)):
            raise ContentPortError(
                f"content-port closure field {field} differs from {source}"
            )
    actual_evidence = actual.get("evidence")
    expected_evidence = expected.get("evidence")
    if not isinstance(actual_evidence, dict) or not isinstance(expected_evidence, dict):
        raise ContentPortError("comparison reports require evidence objects")
    for field in ("attributeFormats", "inputs", "donors"):
        if not equivalent(actual_evidence.get(field), expected_evidence.get(field)):
            raise ContentPortError(
                f"content-port evidence field {field} differs from {source}"
            )


def _bundle_current_state(repo: Path, port: str, donor_root: Path, output: Path) -> str:
    """Compile authenticated donor inputs into a checked desired-state bundle."""

    require_no_active_transaction(repo)
    from .bundle import build_bundle
    from .descriptor import load_port
    from .materialize import derive_desired_state, derive_released_map_files
    from .worktree import detached_worktree, git, require_clean_worktree

    require_clean_worktree(repo)
    raw_revision = git(repo, ["rev-parse", "--verify", "HEAD^{commit}"], text=True)
    assert isinstance(raw_revision, str)
    revision = raw_revision.strip()
    with detached_worktree(repo, revision) as source:
        report = check_port(source, port, donor_root)
        port_dir = _port_dir(source, port)
        descriptor = load_port(port_dir, donor_root.resolve())
        desired, payloads = derive_desired_state(descriptor, source)
        released_files = derive_released_map_files(descriptor, source, desired)
    artifacts = build_bundle(
        repo,
        output,
        desired,
        payloads,
        {
            "contract": report,
        },
        revision=revision,
        released_files=released_files,
    )
    return artifacts.sha256


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="python3 -m tools.content_port")
    commands = result.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="validate policy and authenticate donors")
    _common_port_arguments(check)
    check.add_argument("--compare-report", type=Path)
    check.add_argument("--write-report", type=Path)

    bundle = commands.add_parser(
        "bundle", help="build a deterministic desired-state bundle"
    )
    _common_port_arguments(bundle)
    bundle.add_argument("--output", type=Path, required=True)

    apply = commands.add_parser("apply", help="apply a verified bundle recoverably")
    apply.add_argument("--repo", type=_repo, default=Path.cwd())
    apply.add_argument("--bundle", type=Path, required=True)
    apply.add_argument("--sha256", required=True)

    resume = commands.add_parser("resume", help="finish an interrupted apply")
    resume.add_argument("--repo", type=_repo, default=Path.cwd())

    recover = commands.add_parser(
        "recover", help="restore an interrupted apply preimage"
    )
    recover.add_argument("--repo", type=_repo, default=Path.cwd())

    donor_update = commands.add_parser(
        "donor-update", help="write a donor pin proposal"
    )
    _common_port_arguments(donor_update)
    donor_update.add_argument("--donor", required=True)
    donor_update.add_argument("--revision", required=True)
    donor_update.add_argument("--output", type=Path, required=True)

    migration_finalize = commands.add_parser(
        "migration-finalize", help="install a reviewed donor migration record"
    )
    migration_finalize.add_argument("--repo", type=_repo, default=Path.cwd())
    migration_finalize.add_argument("--candidate", type=Path, required=True)
    migration_finalize.add_argument("--port-dir", type=Path, required=True)
    migration_finalize.add_argument(
        "--donor-root",
        type=Path,
        default=Path(os.environ["CONTENT_PORT_DONOR_ROOT"])
        if "CONTENT_PORT_DONOR_ROOT" in os.environ
        else None,
    )

    guard = commands.add_parser(
        "transaction-check", help="refuse while an apply transaction is active"
    )
    guard.add_argument("--repo", type=_repo, default=Path.cwd())
    ownership = commands.add_parser(
        "ownership-check", help="verify installed owned content without donors"
    )
    ownership.add_argument("--repo", type=_repo, default=Path.cwd())
    ownership.add_argument("--port", required=True)
    return result


def _common_port_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--repo", type=_repo, default=Path.cwd())
    command.add_argument("--port", required=True)
    command.add_argument("--donor-root", type=Path, required=True)


def run(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "check":
        check_port(
            args.repo,
            args.port,
            args.donor_root,
            compare_report=args.compare_report,
            write_report=args.write_report,
        )
    elif args.command == "bundle":
        digest = _bundle_current_state(
            args.repo, args.port, args.donor_root, args.output.resolve()
        )
        print(digest)
    elif args.command == "apply":
        from .bundle import verify_bundle

        actual = verify_bundle(args.bundle.resolve())
        if actual != args.sha256:
            raise ContentPortError(
                f"bundle digest mismatch: expected {args.sha256}, found {actual}"
            )
        apply_bundle(args.repo, args.bundle.resolve(), args.sha256)
    elif args.command == "resume":
        resume_transaction(args.repo)
    elif args.command == "recover":
        recover_transaction(args.repo)
    elif args.command == "donor-update":
        require_no_active_transaction(args.repo)
        from .update import run_donor_update

        run_donor_update(
            args.repo,
            args.port,
            args.donor_root.resolve(),
            args.donor,
            args.revision,
            args.output.resolve(),
        )
    elif args.command == "migration-finalize":
        require_no_active_transaction(args.repo)
        from .update import finalize_migration

        finalize_migration(
            args.candidate.resolve(),
            args.port_dir.resolve(),
            donor_root=args.donor_root.resolve() if args.donor_root else None,
            repo=args.repo,
        )
    elif args.command == "transaction-check":
        require_no_active_transaction(args.repo)
    elif args.command == "ownership-check":
        verify_ownership(args.repo, args.port)
    else:  # pragma: no cover - argparse makes this unreachable
        raise AssertionError(args.command)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(argv)
    except ContentPortError as error:
        print(f"content-port: {error}", file=sys.stderr)
        return 2
