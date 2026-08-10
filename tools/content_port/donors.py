"""Authenticate public donor checkouts against authored immutable pins."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path, PurePosixPath
import tempfile
from typing import Iterator

from .errors import ContentPortError
from .model import DonorEvidence, DonorPin


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
VCS_METADATA_DIRECTORIES = frozenset({".git"})


def validate_excluded_paths(paths: Iterable[str]) -> frozenset[str]:
    """Validate exact, authored donor-relative file exclusions."""

    values = tuple(paths)
    if len(values) != len(set(values)):
        raise ContentPortError("donor excluded paths must not contain duplicates")
    for value in values:
        if not isinstance(value, str) or not value or "\\" in value:
            raise ContentPortError(f"unsafe donor excluded path: {value!r}")
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or value != path.as_posix()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ContentPortError(f"unsafe donor excluded path: {value!r}")
    return frozenset(values)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ContentPortError(f"cannot hash donor input {path}: {error}") from error
    return digest.hexdigest()


def source_tree_records(
    root: Path, *, excluded_paths: Iterable[str] = ()
) -> tuple[Mapping[str, object], ...]:
    """Return normalized source records in stable path order."""
    if not root.is_dir():
        raise ContentPortError(f"donor directory does not exist: {root}")
    exclusions = validate_excluded_paths(excluded_paths)
    records: list[Mapping[str, object]] = []
    try:
        paths = sorted(root.rglob("*"))
    except OSError as error:
        raise ContentPortError(
            f"cannot enumerate donor directory {root}: {error}"
        ) from error
    for path in paths:
        relative = path.relative_to(root)
        if any(part in VCS_METADATA_DIRECTORIES for part in relative.parts):
            continue
        if path.is_symlink():
            raise ContentPortError(
                f"donor source tree contains a symbolic link: {relative.as_posix()}"
            )
        if not path.is_file() or relative.as_posix() in exclusions:
            continue
        try:
            size = path.stat().st_size
        except OSError as error:
            raise ContentPortError(
                f"cannot stat donor input {path}: {error}"
            ) from error
        records.append(
            {"path": relative.as_posix(), "bytes": size, "sha256": _sha256(path)}
        )
    if not records:
        raise ContentPortError(f"donor source tree contains no evidence files: {root}")
    return tuple(records)


def records_digest(records: Iterable[Mapping[str, object]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        try:
            line = f"{record['path']}\0{record['bytes']}\0{record['sha256']}\n"
        except KeyError as error:
            raise ContentPortError(
                f"malformed donor source record: missing {error.args[0]}"
            ) from error
        digest.update(line.encode("utf-8"))
    return digest.hexdigest()


def _checkout_head(root: Path, name: str) -> tuple[str | None, str | None]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD^{commit}"],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        return None, str(error)
    head = result.stdout.strip()
    if result.returncode or not COMMIT_RE.fullmatch(head):
        detail = result.stderr.strip() or "checkout has no verifiable HEAD commit"
        return None, detail
    return head, None


def authenticate_donor(
    pin: DonorPin, *, require_git: bool | None = None
) -> DonorEvidence:
    if not COMMIT_RE.fullmatch(pin.commit):
        raise ContentPortError(f"{pin.name}: malformed pin; expected a 40-hex commit")
    if not DIGEST_RE.fullmatch(pin.tree_digest):
        raise ContentPortError(
            f"{pin.name}: malformed tree digest; expected 64 lowercase hex"
        )
    if (
        isinstance(pin.file_count, bool)
        or not isinstance(pin.file_count, int)
        or pin.file_count <= 0
    ):
        raise ContentPortError(f"{pin.name}: file count must be a positive integer")
    if require_git is None:
        require_git = os.environ.get("CONTENT_PORT_REQUIRE_DONORS") == "1"
    actual_commit, git_error = _checkout_head(pin.root, pin.name)
    if actual_commit is None and require_git:
        raise ContentPortError(
            f"cannot authenticate {pin.name} checkout at {pin.root}: {git_error}"
        )
    if actual_commit is not None and actual_commit != pin.commit:
        raise ContentPortError(
            f"{pin.name} checkout commit {actual_commit} does not match pin {pin.commit}"
        )
    records = source_tree_records(pin.root, excluded_paths=pin.excluded_paths)
    actual_digest = records_digest(records)
    if actual_digest != pin.tree_digest:
        raise ContentPortError(
            f"{pin.name} source-tree digest mismatch: expected {pin.tree_digest}, got {actual_digest}"
        )
    if len(records) != pin.file_count:
        raise ContentPortError(
            f"{pin.name} source-tree file count drift: expected {pin.file_count}, got {len(records)}"
        )
    return DonorEvidence(
        pin.name, actual_commit or pin.commit, actual_digest, len(records)
    )


def authenticate_donors(
    pins: Iterable[DonorPin], *, require_git: bool | None = None
) -> tuple[DonorEvidence, ...]:
    values = tuple(pins)
    names = [pin.name for pin in values]
    roots = [pin.root.resolve() for pin in values]
    if len(names) != len(set(names)):
        raise ContentPortError("duplicate donor name")
    if len(roots) != len(set(roots)):
        raise ContentPortError("multiple donor pins resolve to the same checkout")
    from .faults import checkpoint

    evidence: list[DonorEvidence] = []
    for pin in values:
        record = authenticate_donor(pin, require_git=require_git)
        evidence.append(record)
        checkpoint(f"after-donor-auth:{record.name}")
    return tuple(evidence)


def _copy_authenticated_tree(pin: DonorPin, destination: Path) -> DonorPin:
    records = source_tree_records(pin.root, excluded_paths=pin.excluded_paths)
    for record in records:
        relative = str(record["path"])
        source = pin.root / PurePosixPath(relative)
        target = destination / PurePosixPath(relative)
        try:
            payload = source.read_bytes()
        except OSError as error:
            raise ContentPortError(
                f"cannot snapshot donor input {source}: {error}"
            ) from error
        digest = hashlib.sha256(payload).hexdigest()
        if len(payload) != record["bytes"] or digest != record["sha256"]:
            raise ContentPortError(
                f"{pin.name}: donor input changed while creating authenticated snapshot: "
                f"{relative}"
            )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(payload)
        except OSError as error:
            raise ContentPortError(
                f"cannot create authenticated donor snapshot {target}: {error}"
            ) from error
    return replace(pin, root=destination, excluded_paths=())


@contextmanager
def authenticated_donor_snapshot(
    pins: Iterable[DonorPin],
) -> Iterator[tuple[DonorPin, ...]]:
    """Yield private byte copies whose complete contents match authenticated pins."""

    values = tuple(pins)
    authenticated = authenticate_donors(values)
    with tempfile.TemporaryDirectory(
        prefix="content-port-donor-snapshot-"
    ) as directory:
        snapshot_root = Path(directory)
        snapshots = tuple(
            _copy_authenticated_tree(pin, snapshot_root / str(index))
            for index, pin in enumerate(values)
        )
        copied = authenticate_donors(snapshots, require_git=False)
        if copied != authenticated:
            raise ContentPortError(
                "donor evidence changed while creating authenticated snapshot"
            )
        try:
            yield snapshots
        finally:
            try:
                rendered = authenticate_donors(snapshots, require_git=False)
            except ContentPortError as error:
                raise ContentPortError(
                    "authenticated donor snapshot changed during desired-state rendering"
                ) from error
            if rendered != authenticated:
                raise ContentPortError(
                    "authenticated donor snapshot changed during desired-state rendering"
                )
