"""Deterministic binary patch bundle construction in disposable staging."""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Callable, Mapping, Sequence

from .errors import ContentPortError
from .faults import checkpoint
from .ownership import (
    OwnershipManifest,
    canonical_json,
    reconcile_owned,
)
from .worktree import (
    detached_worktree,
    git,
    require_clean_worktree,
    run_named_validation_commands,
    run_validation_commands,
)


BUNDLE_FILES = ("desired.patch", "ownership.json", "report.json")


@dataclass(frozen=True)
class BundleArtifacts:
    output_dir: Path
    patch: Path
    ownership: Path
    report: Path
    sha256: str


@dataclass(frozen=True)
class NamedCommand:
    command_id: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class ProjectValidationPlan:
    preflight: tuple[NamedCommand, ...]
    preparation: tuple[NamedCommand, ...]
    validators: tuple[NamedCommand, ...]
    artifacts: tuple[str, ...]
    sha256: str
    schema_version: int


def _named_commands(value: object, field: str) -> tuple[NamedCommand, ...]:
    if not isinstance(value, list):
        raise ContentPortError(f"project config {field} must be a list")
    commands: list[NamedCommand] = []
    seen: set[str] = set()
    for index, entry in enumerate(value):
        if not isinstance(entry, dict) or set(entry) != {"id", "command"}:
            raise ContentPortError(f"project config {field}[{index}] is invalid")
        command_id = entry["id"]
        command = entry["command"]
        if (
            not isinstance(command_id, str)
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", command_id)
            or command_id in seen
            or not isinstance(command, list)
            or not command
            or any(not isinstance(part, str) or not part for part in command)
        ):
            raise ContentPortError(f"project config {field}[{index}] is invalid")
        seen.add(command_id)
        commands.append(NamedCommand(command_id, tuple(command)))
    return tuple(commands)


def _read_project_config(path: Path) -> ProjectValidationPlan:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ContentPortError(f"cannot load project config {path}: {error}") from error
    if not isinstance(value, dict):
        raise ContentPortError("project config must be an object")
    canonical = canonical_json(value)
    if value.get("schemaVersion") == 1 and set(value) == {
        "schemaVersion",
        "validationCommands",
    }:
        raw_commands = value["validationCommands"]
        if not isinstance(raw_commands, list):
            raise ContentPortError("project config validationCommands must be a list")
        validators = _named_commands(
            [
                {"id": f"validation-{index}", "command": command}
                for index, command in enumerate(raw_commands)
            ],
            "validationCommands",
        )
        return ProjectValidationPlan(
            (), (), validators, (), hashlib.sha256(canonical).hexdigest(), 1
        )
    required = {
        "schemaVersion",
        "preflightCommands",
        "preparationCommands",
        "validators",
        "artifacts",
    }
    if value.get("schemaVersion") != 2 or set(value) != required:
        raise ContentPortError("project config has an unsupported schema")
    artifacts = value["artifacts"]
    if (
        not isinstance(artifacts, list)
        or any(not isinstance(item, str) or not item for item in artifacts)
        or len(set(artifacts)) != len(artifacts)
    ):
        raise ContentPortError("project config artifacts is invalid")
    for artifact in artifacts:
        parts = PurePosixPath(artifact).parts
        if PurePosixPath(artifact).is_absolute() or not parts or ".." in parts:
            raise ContentPortError("project config artifacts is invalid")
    preflight = _named_commands(value["preflightCommands"], "preflightCommands")
    preparation = _named_commands(value["preparationCommands"], "preparationCommands")
    validators = _named_commands(value["validators"], "validators")
    command_ids = [item.command_id for item in (*preflight, *preparation, *validators)]
    if len(set(command_ids)) != len(command_ids):
        raise ContentPortError("project config command ids must be unique")
    return ProjectValidationPlan(
        preflight,
        preparation,
        validators,
        tuple(artifacts),
        hashlib.sha256(canonical).hexdigest(),
        2,
    )


def project_validation_commands(repo: Path) -> tuple[tuple[str, ...], ...]:
    plan = _read_project_config(repo / "tools/content_port/project.json")
    return tuple(item.command for item in (*plan.preflight, *plan.validators))


def _artifact_digest(root: Path, relative: str) -> str:
    path = root / relative
    if not path.exists() and not path.is_symlink():
        raise ContentPortError(f"prepared artifact is missing: {relative}")
    digest = hashlib.sha256()
    entries = (
        (path,)
        if path.is_symlink() or not path.is_dir()
        else (path, *sorted(path.rglob("*")))
    )
    for entry in entries:
        name = "." if entry == path else entry.relative_to(path).as_posix()
        encoded = name.encode()
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        metadata = entry.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            kind = b"L"
            mode = b"120000"
            content = os.readlink(entry).encode()
        elif stat.S_ISDIR(metadata.st_mode):
            kind = b"D"
            mode = b"040000"
            content = b""
        elif stat.S_ISREG(metadata.st_mode):
            kind = b"F"
            mode = b"100755" if metadata.st_mode & 0o111 else b"100644"
            content = entry.read_bytes()
        else:
            raise ContentPortError(f"prepared artifact is unsafe: {relative}")
        digest.update(kind)
        digest.update(mode)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def verify_validation_policy(
    validation: Mapping[str, object], policy: ProjectValidationPlan
) -> None:
    """Bind schema-v2 validation evidence to the exact checked-out policy."""

    for group, expected_commands in (
        ("preflight", policy.preflight),
        ("validators", policy.validators),
    ):
        actual = validation.get(group)
        if not isinstance(actual, list) or len(actual) != len(expected_commands):
            raise ContentPortError(
                f"bundle validation {group} does not match the base commit policy"
            )
        for result, item in zip(actual, expected_commands, strict=True):
            if not isinstance(result, dict) or result.get("id") != item.command_id:
                raise ContentPortError(
                    f"bundle validation {group} does not match the base commit policy"
                )
            command = result.get("command")
            if command != list(item.command) and result.get("commandTemplate") != list(
                item.command
            ):
                raise ContentPortError(
                    f"bundle validation {group} does not match the base commit policy"
                )
            if result.get("status") != "passed":
                raise ContentPortError(
                    f"bundle validation {group} does not match the base commit policy"
                )

    artifacts = validation.get("artifacts")
    if not isinstance(artifacts, list) or [
        artifact.get("path") if isinstance(artifact, dict) else None
        for artifact in artifacts
    ] != list(policy.artifacts):
        raise ContentPortError(
            "bundle validation artifacts do not match the base commit policy"
        )


def _artifact_manifest(root: Path, artifacts: Sequence[str]) -> list[dict[str, str]]:
    return [
        {"path": relative, "sha256": _artifact_digest(root, relative)}
        for relative in artifacts
    ]


def write_artifact_manifest(repo: Path, output: Path) -> None:
    """Write the canonical identity of every artifact required by base policy."""

    plan = _read_project_config(repo / "tools/content_port/project.json")
    if plan.schema_version != 2:
        raise ContentPortError("artifact manifests require project policy schema v2")
    value = {"schemaVersion": 1, "artifacts": _artifact_manifest(repo, plan.artifacts)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json(value))


def verify_artifact_manifest(repo: Path, manifest_path: Path) -> list[dict[str, str]]:
    """Verify a canonical artifact manifest against files below repo."""

    try:
        value = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ContentPortError(
            f"cannot load artifact manifest {manifest_path}: {error}"
        ) from error
    if (
        not isinstance(value, dict)
        or set(value) != {"schemaVersion", "artifacts"}
        or value.get("schemaVersion") != 1
        or manifest_path.read_bytes() != canonical_json(value)
    ):
        raise ContentPortError("prepared artifact manifest is invalid or noncanonical")
    plan = _read_project_config(repo / "tools/content_port/project.json")
    expected = _artifact_manifest(repo, plan.artifacts)
    if value.get("artifacts") != expected:
        raise ContentPortError(
            "prepared artifacts do not match their canonical manifest"
        )
    return expected


def _canonical_file(path: Path, description: str) -> tuple[dict[str, object], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ContentPortError(f"cannot load {description} {path}: {error}") from error
    if not isinstance(value, dict) or raw != canonical_json(value):
        raise ContentPortError(f"{description} is invalid or noncanonical")
    return value, raw


def _candidate_identity(candidate: Path) -> dict[str, str]:
    verify_bundle(candidate)
    ownership = (candidate / "ownership.json").read_bytes()
    patch = (candidate / "desired.patch").read_bytes()
    return {
        "bundleSha256": bundle_digest(candidate),
        "ownershipSha256": hashlib.sha256(ownership).hexdigest(),
        "patchSha256": hashlib.sha256(patch).hexdigest(),
    }


def write_preflight_receipt(repo: Path, donor_contract: Path, output: Path) -> None:
    """Record the successful prerequisite jobs without claiming to rerun them."""

    plan = _read_project_config(repo / "tools/content_port/project.json")
    if plan.schema_version != 2:
        raise ContentPortError("preflight receipts require project policy schema v2")
    _, donor_raw = _canonical_file(donor_contract, "donor contract")
    head = git(repo, ["rev-parse", "HEAD"], text=True).strip()
    value = {
        "schemaVersion": 1,
        "kind": "preflight",
        "baseCommit": head,
        "policySha256": plan.sha256,
        "donorContractSha256": hashlib.sha256(donor_raw).hexdigest(),
        "commands": [
            {"id": item.command_id, "command": list(item.command), "status": "passed"}
            for item in plan.preflight
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json(value))


def verify_preflight_receipt(
    repo: Path, candidate: Path, donor_contract: Path, receipt: Path
) -> tuple[dict[str, object], str]:
    plan = _read_project_config(repo / "tools/content_port/project.json")
    value, raw = _canonical_file(receipt, "preflight receipt")
    _, donor_raw = _canonical_file(donor_contract, "donor contract")
    candidate_report, _ = _canonical_file(candidate / "report.json", "candidate report")
    head = git(repo, ["rev-parse", "HEAD"], text=True).strip()
    expected_commands = [
        {"id": item.command_id, "command": list(item.command), "status": "passed"}
        for item in plan.preflight
    ]
    if value != {
        "schemaVersion": 1,
        "kind": "preflight",
        "baseCommit": head,
        "policySha256": plan.sha256,
        "donorContractSha256": hashlib.sha256(donor_raw).hexdigest(),
        "commands": expected_commands,
    }:
        raise ContentPortError("preflight receipt does not match policy and evidence")
    contract = candidate_report.get("contract")
    if not isinstance(contract, dict) or canonical_json(contract) != donor_raw:
        raise ContentPortError(
            "donor contract does not match candidate-derived evidence"
        )
    return value, hashlib.sha256(raw).hexdigest()


def run_ci_validator(
    repo: Path,
    command_id: str,
    candidate: Path,
    artifact_manifest: Path,
    preflight_receipt: Path,
    donor_contract: Path,
    results: Path,
    output: Path,
) -> None:
    """Execute one canonical validator and emit a receipt only after success."""

    plan = _read_project_config(repo / "tools/content_port/project.json")
    command = next(
        (item for item in plan.validators if item.command_id == command_id), None
    )
    if command is None:
        raise ContentPortError(f"unknown validator id {command_id}")
    repo = repo.resolve(strict=True)
    artifacts = verify_artifact_manifest(repo, artifact_manifest)
    artifact_raw = artifact_manifest.read_bytes()
    candidate_identity = _candidate_identity(candidate)
    _, preflight_digest = verify_preflight_receipt(
        repo, candidate, donor_contract, preflight_receipt
    )
    relative_results = results.as_posix()
    if results.is_absolute():
        try:
            relative_results = results.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError as error:
            raise ContentPortError(
                "validator results must be below the repository"
            ) from error
    result_parts = PurePosixPath(relative_results).parts
    if not result_parts or ".." in result_parts:
        raise ContentPortError("validator results must be below the repository")
    results_path = repo / relative_results
    evidence_paths = (
        candidate,
        artifact_manifest,
        preflight_receipt,
        donor_contract,
    )
    resolved_results = results_path.resolve(strict=False)
    if resolved_results == repo or repo not in resolved_results.parents:
        raise ContentPortError("validator results must be below the repository")
    for evidence in evidence_paths:
        resolved_evidence = evidence.resolve(strict=False)
        if (
            resolved_evidence == resolved_results
            or resolved_results in resolved_evidence.parents
            or resolved_evidence in resolved_results.parents
        ):
            raise ContentPortError("validator results overlap validator evidence")
    results_path.mkdir(parents=True, exist_ok=True)
    if results_path.resolve() != results_path.absolute():
        raise ContentPortError("validator results path must not contain symlinks")
    candidate_allowances = (
        *evidence_paths,
        results_path,
        *(repo / item["path"] for item in artifacts),
    )
    _verify_candidate_checkout(repo, candidate, candidate_allowances)
    repository_state = _repository_state(repo, results_path)
    argv = tuple(
        part.replace("{results}", relative_results) for part in command.command
    )
    environment = {
        **os.environ,
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(argv, cwd=repo, env=environment, check=False)
    if completed.returncode:
        raise ContentPortError(
            f"validator {command_id} failed with status {completed.returncode}"
        )
    if _repository_state(repo, results_path) != repository_state:
        raise ContentPortError(f"validator {command_id} changed repository state")
    _verify_candidate_checkout(repo, candidate, candidate_allowances)
    if verify_artifact_manifest(repo, artifact_manifest) != artifacts:
        raise ContentPortError(f"validator {command_id} changed prepared artifacts")
    if _candidate_identity(candidate) != candidate_identity:
        raise ContentPortError(f"validator {command_id} changed the bundle candidate")
    value = {
        "schemaVersion": 1,
        "kind": "validator",
        "id": command_id,
        "commandTemplate": list(command.command),
        "argv": list(argv),
        "results": relative_results,
        "status": "passed",
        "baseCommit": git(repo, ["rev-parse", "HEAD"], text=True).strip(),
        "policySha256": plan.sha256,
        "candidate": candidate_identity,
        "artifactManifestSha256": hashlib.sha256(artifact_raw).hexdigest(),
        "artifacts": artifacts,
        "preflightReceiptSha256": preflight_digest,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json(value))


def _verify_candidate_checkout(
    repo: Path, candidate: Path, allowed_paths: Sequence[Path]
) -> None:
    """Require the worktree's complete non-ignored tree to equal desired.patch."""

    expected = (candidate / "desired.patch").read_bytes()
    temporary_index = Path(tempfile.mkstemp(prefix="content-port-index-")[1])
    temporary_index.unlink()
    environment = {
        **os.environ,
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_INDEX_FILE": str(temporary_index),
    }
    try:
        exclusions: list[str] = []
        for path in allowed_paths:
            try:
                relative = path.resolve(strict=False).relative_to(repo).as_posix()
            except ValueError:
                continue
            tracked = (
                subprocess.run(
                    ["git", "cat-file", "-e", f"HEAD:{relative}"],
                    cwd=repo,
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode
                == 0
            )
            ignored = (
                subprocess.run(
                    ["git", "check-ignore", "--quiet", "--", relative],
                    cwd=repo,
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode
                == 0
            )
            if not tracked and not ignored:
                exclusions.append(f":(exclude){relative}")
        for arguments in (
            ("read-tree", "HEAD"),
            ("add", "--all", "--", ".", *exclusions),
        ):
            completed = subprocess.run(
                ["git", *arguments],
                cwd=repo,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if completed.returncode:
                raise ContentPortError(
                    "cannot inspect validator candidate tree: "
                    + completed.stderr.decode(errors="replace").strip()
                )
        actual = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--binary",
                "--full-index",
                "--no-ext-diff",
                "--no-color",
                "--src-prefix=a/",
                "--dst-prefix=b/",
                "HEAD",
                "--",
                ".",
            ],
            cwd=repo,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if actual.returncode:
            raise ContentPortError(
                "cannot inspect validator candidate tree: "
                + actual.stderr.decode(errors="replace").strip()
            )
        if actual.stdout != expected:
            raise ContentPortError(
                "validator worktree does not exactly match candidate desired.patch"
            )
    finally:
        temporary_index.unlink(missing_ok=True)


def _repository_state(repo: Path, excluded: Path) -> str:
    """Hash all worktree state, including ignored files and the real Git index."""

    digest = hashlib.sha256()
    excluded = excluded.resolve()

    def add(value: bytes) -> None:
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)

    def visit(path: Path) -> None:
        if path == excluded or excluded in path.parents:
            return
        relative = path.relative_to(repo).as_posix().encode()
        metadata = path.lstat()
        add(relative)
        add(stat.S_IFMT(metadata.st_mode).to_bytes(4, "big"))
        add(stat.S_IMODE(metadata.st_mode).to_bytes(4, "big"))
        if stat.S_ISLNK(metadata.st_mode):
            add(os.readlink(path).encode())
        elif stat.S_ISREG(metadata.st_mode):
            file_digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    file_digest.update(chunk)
            add(file_digest.digest())
        elif stat.S_ISDIR(metadata.st_mode):
            if path == repo:
                names = sorted(
                    item.name for item in os.scandir(path) if item.name != ".git"
                )
            else:
                names = sorted(item.name for item in os.scandir(path))
            for name in names:
                visit(path / name)
        else:
            raise ContentPortError(
                f"repository contains unsupported file type: {path.relative_to(repo)}"
            )

    visit(repo)
    index_path = Path(
        git(repo, ["rev-parse", "--git-path", "index"], text=True).strip()
    )
    if not index_path.is_absolute():
        index_path = repo / index_path
    add(index_path.read_bytes() if index_path.exists() else b"")
    add(git(repo, ["rev-parse", "HEAD"]))
    return digest.hexdigest()


def _verify_validator_receipts(
    repo: Path,
    plan: ProjectValidationPlan,
    candidate: Path,
    artifact_manifest: Path,
    preflight_digest: str,
    receipts: Path,
) -> list[dict[str, object]]:
    candidate_identity = _candidate_identity(candidate)
    artifact_raw = artifact_manifest.read_bytes()
    artifacts = verify_artifact_manifest(repo, artifact_manifest)
    expected_names = {f"{item.command_id}.json" for item in plan.validators}
    actual_names = (
        {path.name for path in receipts.iterdir()} if receipts.is_dir() else set()
    )
    if actual_names != expected_names:
        raise ContentPortError("validator receipt set is incomplete or unexpected")
    head = git(repo, ["rev-parse", "HEAD"], text=True).strip()
    verified: list[dict[str, object]] = []
    for item in plan.validators:
        value, raw = _canonical_file(
            receipts / f"{item.command_id}.json", "validator receipt"
        )
        results = value.get("results")
        expected_argv = (
            [part.replace("{results}", results) for part in item.command]
            if isinstance(results, str)
            and results
            and not Path(results).is_absolute()
            and ".." not in PurePosixPath(results).parts
            else None
        )
        expected = {
            "schemaVersion": 1,
            "kind": "validator",
            "id": item.command_id,
            "commandTemplate": list(item.command),
            "argv": expected_argv,
            "results": results,
            "status": "passed",
            "baseCommit": head,
            "policySha256": plan.sha256,
            "candidate": candidate_identity,
            "artifactManifestSha256": hashlib.sha256(artifact_raw).hexdigest(),
            "artifacts": artifacts,
            "preflightReceiptSha256": preflight_digest,
        }
        if expected_argv is None or value != expected:
            raise ContentPortError(f"validator receipt {item.command_id} is invalid")
        verified.append({**value, "receiptSha256": hashlib.sha256(raw).hexdigest()})
    return verified


def finalize_ci_bundle(
    repo: Path,
    candidate: Path,
    artifact_manifest: Path,
    preflight_receipt: Path,
    donor_contract: Path,
    receipts: Path,
    output_dir: Path,
) -> BundleArtifacts:
    """Bind CI's passed policy commands to one exact candidate and artifact set."""

    plan = _read_project_config(repo / "tools/content_port/project.json")
    if plan.schema_version != 2:
        raise ContentPortError(
            "CI bundle finalization requires project policy schema v2"
        )
    artifacts = verify_artifact_manifest(repo, artifact_manifest)
    preflight, preflight_digest = verify_preflight_receipt(
        repo, candidate, donor_contract, preflight_receipt
    )
    validator_receipts = _verify_validator_receipts(
        repo, plan, candidate, artifact_manifest, preflight_digest, receipts
    )
    ownership_path = candidate / "ownership.json"
    manifest = OwnershipManifest.load(ownership_path)
    if ownership_path.read_bytes() != canonical_json(manifest.to_json()):
        raise ContentPortError("candidate ownership.json is not canonical")
    patch = (candidate / "desired.patch").read_bytes()
    try:
        candidate_report = json.loads((candidate / "report.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ContentPortError(f"cannot load candidate report: {error}") from error
    head = git(repo, ["rev-parse", "HEAD"], text=True)
    assert isinstance(head, str)
    if candidate_report.get("baseCommit") != head.strip():
        raise ContentPortError("candidate base commit does not match checked-out HEAD")
    report: dict[str, object] = {
        "schemaVersion": 2,
        "port": manifest.port,
        "baseCommit": head.strip(),
        "patchSha256": hashlib.sha256(patch).hexdigest(),
        "ownedUnitCount": len(manifest.units),
        "validation": {
            "schemaVersion": 1,
            "policySha256": plan.sha256,
            "artifacts": artifacts,
            "preflight": [
                {
                    "id": item.command_id,
                    "command": list(item.command),
                    "status": "passed",
                }
                for item in plan.preflight
            ],
            "validators": [
                {
                    "id": receipt["id"],
                    "commandTemplate": receipt["commandTemplate"],
                    "argv": receipt["argv"],
                    "results": receipt["results"],
                    "status": receipt["status"],
                    "receiptSha256": receipt["receiptSha256"],
                }
                for receipt in validator_receipts
            ],
            "preflightReceiptSha256": preflight_digest,
            "donorContractSha256": preflight["donorContractSha256"],
            "artifactManifestSha256": hashlib.sha256(
                artifact_manifest.read_bytes()
            ).hexdigest(),
        },
    }
    if "contract" in candidate_report:
        report["contract"] = candidate_report["contract"]
    _publish_artifacts(
        output_dir,
        {
            "desired.patch": patch,
            "ownership.json": ownership_path.read_bytes(),
            "report.json": canonical_json(report),
        },
    )
    return _artifact_result(output_dir)


def validate_asset_ownership(
    manifest: OwnershipManifest,
    asset_document: Mapping[str, object],
    *,
    evidence_root: Path,
) -> None:
    """Require every redistributable asset and only ledgered asset paths."""

    from .update import validate_assets

    assets = validate_assets(
        asset_document,
        evidence_root=evidence_root,
        require_redistributable=True,
    )
    expected: dict[str, str] = {}
    for asset in assets:
        path = asset["semanticTarget"]
        digest = asset["targetSha256"]
        assert isinstance(path, str) and isinstance(digest, str)
        expected[path] = digest
    owned = {unit.path: unit.sha256 for unit in manifest.units if unit.kind == "file"}
    for path, digest in sorted(expected.items()):
        if path not in owned:
            raise ContentPortError(f"asset ownership is missing file unit {path}")
        if owned[path] != digest:
            raise ContentPortError(f"asset ownership hash differs for {path}")
    roots = {
        PurePosixPath(*PurePosixPath(path).parts[:2]).as_posix() for path in expected
    }
    owned_in_asset_roots = {
        path
        for path in owned
        if any(path == root or path.startswith(f"{root}/") for root in roots)
    }
    unexpected = sorted(owned_in_asset_roots - set(expected))
    if unexpected:
        raise ContentPortError(
            f"asset ownership has unledgered file unit {unexpected[0]}"
        )


def deterministic_patch(staging: Path, revision: str = "HEAD") -> bytes:
    """Return a binary-safe patch including new, changed, and deleted files."""

    git(staging, ["add", "--intent-to-add", "--all", "--", "."])
    patch = git(
        staging,
        [
            "diff",
            "--binary",
            "--full-index",
            "--no-ext-diff",
            "--no-color",
            "--src-prefix=a/",
            "--dst-prefix=b/",
            revision,
            "--",
            ".",
        ],
    )
    assert isinstance(patch, bytes)
    return patch


def build_bundle(
    repo: Path,
    output_dir: Path,
    desired: OwnershipManifest,
    payloads: Mapping[tuple[str, ...], object],
    report: Mapping[str, object] | None = None,
    *,
    validation_commands: Sequence[Sequence[str]] | None = None,
    revision: str = "HEAD",
    checked_manifest_path: str | None = None,
    prepare: Callable[[Path], None] | None = None,
    validation_jobs: int = 1,
) -> BundleArtifacts:
    """Build desired artifacts against installed ownership in the base revision."""

    repo = repo.resolve(strict=True)
    require_clean_worktree(repo)
    checked_manifest_path = checked_manifest_path or (
        f"tools/content_port/ports/{desired.port}/ownership.json"
    )
    if output_dir.exists() and output_dir.is_symlink():
        raise ContentPortError(f"bundle output cannot be a symlink: {output_dir}")
    with detached_worktree(repo, revision) as staging:
        asset_path = staging / f"tools/content_port/ports/{desired.port}/assets.json"
        if asset_path.is_file():
            try:
                asset_document = json.loads(asset_path.read_text())
            except (OSError, json.JSONDecodeError) as error:
                raise ContentPortError(
                    f"cannot load asset policy {asset_path}: {error}"
                ) from error
            if not isinstance(asset_document, dict):
                raise ContentPortError(f"asset policy must be an object: {asset_path}")
            validate_asset_ownership(
                desired,
                asset_document,
                evidence_root=staging,
            )
        if validation_commands is not None:
            plan = ProjectValidationPlan(
                (),
                (),
                tuple(
                    NamedCommand(f"validation-{index}", tuple(command))
                    for index, command in enumerate(validation_commands)
                ),
                (),
                hashlib.sha256(
                    canonical_json({"validationCommands": validation_commands})
                ).hexdigest(),
                2,
            )
        else:
            plan = _read_project_config(staging / "tools/content_port/project.json")
        manifest_path = staging / checked_manifest_path
        installed = (
            OwnershipManifest.load(manifest_path)
            if manifest_path.exists()
            else OwnershipManifest(desired.port, ())
        )
        if prepare is not None:
            prepare(staging)
        reconcile_owned(staging, installed, desired, payloads)
        desired.write(manifest_path)
        desired_patch = deterministic_patch(staging)
        validation_root = Path(tempfile.mkdtemp(prefix="content-port-validation-"))
        try:
            preflight_results = run_named_validation_commands(
                staging,
                tuple((item.command_id, item.command) for item in plan.preflight),
                validation_root / "preflight",
                jobs=1,
            )
            run_validation_commands(
                staging, tuple(item.command for item in plan.preparation)
            )
            prepared_artifacts = _artifact_manifest(staging, plan.artifacts)
            validator_results = run_named_validation_commands(
                staging,
                tuple((item.command_id, item.command) for item in plan.validators),
                validation_root / "validators",
                jobs=validation_jobs,
            )
            if _artifact_manifest(staging, plan.artifacts) != prepared_artifacts:
                raise ContentPortError("validation commands changed prepared artifacts")
        finally:
            shutil.rmtree(validation_root, ignore_errors=True)
        patch = deterministic_patch(staging)
        if patch != desired_patch:
            raise ContentPortError(
                "validation commands changed the staged desired tree"
            )
        head = git(staging, ["rev-parse", "HEAD"], text=True)
        assert isinstance(head, str)
        report_value: dict[str, object] = dict(report or {})
        reserved = {
            "schemaVersion",
            "port",
            "baseCommit",
            "patchSha256",
            "ownedUnitCount",
            "validation",
        }
        conflict = sorted(reserved & set(report_value))
        if conflict:
            raise ContentPortError(f"report field is reserved: {conflict[0]}")
        common = {
            "port": desired.port,
            "baseCommit": head.strip(),
            "patchSha256": hashlib.sha256(patch).hexdigest(),
            "ownedUnitCount": len(desired.units),
        }
        if plan.schema_version == 1:
            report_value.update({"schemaVersion": 1, **common})
        else:
            report_value.update(
                {
                    "schemaVersion": 2,
                    **common,
                    "validation": {
                        "schemaVersion": 1,
                        "policySha256": plan.sha256,
                        "artifacts": prepared_artifacts,
                        "preflight": [
                            {
                                "id": item.validator_id,
                                "command": list(item.command),
                                "status": "passed",
                            }
                            for item in preflight_results
                        ],
                        "validators": [
                            {
                                "id": item.validator_id,
                                "command": list(item.command),
                                "status": "passed",
                            }
                            for item in validator_results
                        ],
                    },
                }
            )
        artifacts = {
            "desired.patch": patch,
            "ownership.json": canonical_json(desired.to_json()),
            "report.json": canonical_json(report_value),
        }
    _publish_artifacts(output_dir, artifacts)
    return _artifact_result(output_dir)


def _publish_artifacts(output_dir: Path, artifacts: Mapping[str, bytes]) -> None:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent)
    )
    try:
        for name in BUNDLE_FILES:
            path = temporary / name
            path.write_bytes(artifacts[name])
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
            checkpoint(f"after-bundle-fsync:{name}")
        _fsync_directory(temporary)
        if output_dir.exists() or output_dir.is_symlink():
            if output_dir.is_symlink() or not output_dir.is_dir():
                raise ContentPortError(
                    f"bundle output must be a real directory: {output_dir}"
                )
            _exchange_directories(temporary, output_dir)
        else:
            os.rename(temporary, output_dir)
        _fsync_directory(output_dir.parent)
        for name in BUNDLE_FILES:
            checkpoint(f"after-bundle-rename:{name}")
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _exchange_directories(left: Path, right: Path) -> None:
    """Atomically exchange two same-filesystem directories on Linux."""

    renameat2 = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if renameat2 is None:
        raise ContentPortError(
            "atomic bundle replacement requires renameat2(RENAME_EXCHANGE)"
        )
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(left),
        -100,
        os.fsencode(right),
        2,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
        raise ContentPortError(
            "filesystem does not support atomic bundle directory exchange"
        )
    raise ContentPortError(
        f"cannot atomically publish bundle: {os.strerror(error_number)}"
    )


def bundle_digest(output_dir: Path) -> str:
    """Hash a bundle using filename and byte-length framing."""

    digest = hashlib.sha256()
    for name in BUNDLE_FILES:
        path = output_dir / name
        if path.is_symlink() or not path.is_file():
            raise ContentPortError(f"bundle artifact is missing or unsafe: {path}")
        content = path.read_bytes()
        encoded_name = name.encode()
        digest.update(len(encoded_name).to_bytes(4, "big"))
        digest.update(encoded_name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def verify_bundle(output_dir: Path) -> str:
    """Validate canonical metadata and return the aggregate bundle digest."""

    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ContentPortError(f"bundle directory is missing or unsafe: {output_dir}")
    manifest_path = output_dir / "ownership.json"
    manifest = OwnershipManifest.load(manifest_path)
    if manifest_path.read_bytes() != canonical_json(manifest.to_json()):
        raise ContentPortError("ownership.json is not canonical")
    report_path = output_dir / "report.json"
    try:
        report = json.loads(report_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ContentPortError(f"invalid bundle report: {error}") from error
    if not isinstance(report, dict) or report_path.read_bytes() != canonical_json(
        report
    ):
        raise ContentPortError("report.json is not canonical")
    required = {"schemaVersion", "port", "baseCommit", "patchSha256", "ownedUnitCount"}
    if not required <= set(report) or report["schemaVersion"] not in (1, 2):
        raise ContentPortError("bundle report is incomplete")
    if report["schemaVersion"] == 2:
        validation = report.get("validation")
        if (
            not isinstance(validation, dict)
            or not {
                "schemaVersion",
                "policySha256",
                "artifacts",
                "preflight",
                "validators",
            }
            <= set(validation)
            or set(validation)
            - {
                "schemaVersion",
                "policySha256",
                "artifacts",
                "preflight",
                "validators",
                "preflightReceiptSha256",
                "donorContractSha256",
                "artifactManifestSha256",
            }
        ):
            raise ContentPortError("bundle validation report is incomplete")
        if (
            validation["schemaVersion"] != 1
            or not isinstance(validation["policySha256"], str)
            or len(validation["policySha256"]) != 64
            or any(
                character not in "0123456789abcdef"
                for character in validation["policySha256"]
            )
            or not isinstance(validation["artifacts"], list)
            or not isinstance(validation["preflight"], list)
            or not isinstance(validation["validators"], list)
        ):
            raise ContentPortError("bundle validation report is invalid")
        for group in ("preflight", "validators"):
            identifiers: set[str] = set()
            for result in validation[group]:
                simple = isinstance(result, dict) and set(result) == {
                    "id",
                    "command",
                    "status",
                }
                receipt = isinstance(result, dict) and set(result) == {
                    "id",
                    "commandTemplate",
                    "argv",
                    "results",
                    "status",
                    "receiptSha256",
                }
                if (
                    not isinstance(result, dict)
                    or not (simple or (group == "validators" and receipt))
                    or not isinstance(result["id"], str)
                    or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", result["id"])
                    or result["id"] in identifiers
                    or not isinstance(
                        result.get("command", result.get("commandTemplate")), list
                    )
                    or not result.get("command", result.get("commandTemplate"))
                    or any(
                        not isinstance(part, str) or not part
                        for part in result.get("command", result.get("commandTemplate"))
                    )
                    or result["status"] != "passed"
                ):
                    raise ContentPortError("bundle validation report is invalid")
                if receipt and (
                    not isinstance(result["argv"], list)
                    or not result["argv"]
                    or any(
                        not isinstance(part, str) or not part for part in result["argv"]
                    )
                    or not isinstance(result["results"], str)
                    or not result["results"]
                    or Path(result["results"]).is_absolute()
                    or ".." in PurePosixPath(result["results"]).parts
                    or not isinstance(result["receiptSha256"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", result["receiptSha256"])
                ):
                    raise ContentPortError("bundle validation report is invalid")
                identifiers.add(result["id"])
        for field in (
            "preflightReceiptSha256",
            "donorContractSha256",
            "artifactManifestSha256",
        ):
            if field in validation and (
                not isinstance(validation[field], str)
                or not re.fullmatch(r"[0-9a-f]{64}", validation[field])
            ):
                raise ContentPortError("bundle validation report is invalid")
        for artifact in validation["artifacts"]:
            if (
                not isinstance(artifact, dict)
                or set(artifact) != {"path", "sha256"}
                or not isinstance(artifact["path"], str)
                or not artifact["path"]
                or not isinstance(artifact["sha256"], str)
                or len(artifact["sha256"]) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in artifact["sha256"]
                )
            ):
                raise ContentPortError("bundle validation report is invalid")
    if report["port"] != manifest.port or report["ownedUnitCount"] != len(
        manifest.units
    ):
        raise ContentPortError("bundle report does not match ownership manifest")
    patch = (output_dir / "desired.patch").read_bytes()
    if hashlib.sha256(patch).hexdigest() != report["patchSha256"]:
        raise ContentPortError("desired.patch does not match report digest")
    return bundle_digest(output_dir)


def _artifact_result(output_dir: Path) -> BundleArtifacts:
    output_dir = output_dir.resolve()
    digest = verify_bundle(output_dir)
    return BundleArtifacts(
        output_dir=output_dir,
        patch=output_dir / "desired.patch",
        ownership=output_dir / "ownership.json",
        report=output_dir / "report.json",
        sha256=digest,
    )
