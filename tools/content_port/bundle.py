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
import shutil
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


def _read_project_config(path: Path) -> tuple[tuple[str, ...], ...]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ContentPortError(f"cannot load project config {path}: {error}") from error
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "validationCommands",
    }:
        raise ContentPortError(
            "project config requires only schemaVersion and validationCommands"
        )
    if value["schemaVersion"] != 1 or not isinstance(value["validationCommands"], list):
        raise ContentPortError("project config has an unsupported schema")
    commands: list[tuple[str, ...]] = []
    for index, command in enumerate(value["validationCommands"]):
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(part, str) or not part for part in command)
        ):
            raise ContentPortError(
                f"project config validationCommands[{index}] is invalid"
            )
        commands.append(tuple(command))
    return tuple(commands)


def project_validation_commands(repo: Path) -> tuple[tuple[str, ...], ...]:
    return _read_project_config(repo / "tools/content_port/project.json")


def validate_asset_ownership(
    manifest: OwnershipManifest, asset_document: Mapping[str, object]
) -> None:
    """Require every redistributable asset and only ledgered asset paths."""

    from .update import validate_assets

    assets = validate_assets(asset_document, require_redistributable=True)
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
    previous: OwnershipManifest | None = None,
    validation_commands: Sequence[Sequence[str]] | None = None,
    revision: str = "HEAD",
    checked_manifest_path: str | None = None,
    prepare: Callable[[Path], None] | None = None,
) -> BundleArtifacts:
    """Build all artifacts from a complete validated detached desired state."""

    repo = repo.resolve(strict=True)
    require_clean_worktree(repo)
    checked_manifest_path = checked_manifest_path or (
        f"tools/content_port/ports/{desired.port}/ownership.json"
    )
    asset_path = repo / f"tools/content_port/ports/{desired.port}/assets.json"
    if asset_path.is_file():
        try:
            asset_document = json.loads(asset_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise ContentPortError(
                f"cannot load asset policy {asset_path}: {error}"
            ) from error
        if not isinstance(asset_document, dict):
            raise ContentPortError(f"asset policy must be an object: {asset_path}")
        validate_asset_ownership(desired, asset_document)
    if output_dir.exists() and output_dir.is_symlink():
        raise ContentPortError(f"bundle output cannot be a symlink: {output_dir}")
    commands = (
        tuple(tuple(part for part in command) for command in validation_commands)
        if validation_commands is not None
        else project_validation_commands(repo)
    )
    with detached_worktree(repo, revision) as staging:
        manifest_path = staging / checked_manifest_path
        baseline = previous
        if baseline is None:
            baseline = (
                OwnershipManifest.load(manifest_path)
                if manifest_path.exists()
                else OwnershipManifest(desired.port, ())
            )
        if prepare is not None:
            prepare(staging)
        reconcile_owned(staging, baseline, desired, payloads)
        desired.write(manifest_path)
        desired_patch = deterministic_patch(staging)
        run_validation_commands(staging, commands)
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
        }
        conflict = sorted(reserved & set(report_value))
        if conflict:
            raise ContentPortError(f"report field is reserved: {conflict[0]}")
        report_value.update(
            {
                "schemaVersion": 1,
                "port": desired.port,
                "baseCommit": head.strip(),
                "patchSha256": hashlib.sha256(patch).hexdigest(),
                "ownedUnitCount": len(desired.units),
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
    if not required <= set(report) or report["schemaVersion"] != 1:
        raise ContentPortError("bundle report is incomplete")
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
