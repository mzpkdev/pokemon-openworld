"""Recoverable application of a checked content-port bundle.

The transaction state lives in the participant Git directory, not the common
repository directory, so simultaneous uberepo worktrees cannot guard or recover
one another.  HEAD and refs are read-only throughout this module.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import json
import os
import shutil
import stat
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, Mapping

from .errors import ContentPortError
from .faults import checkpoint


STATE_DIRECTORY = "content-port-transaction"
GUARD_FILENAME = "guard.json"
JOURNAL_FILENAME = "journal.json"
LOCK_FILENAME = "creation.lock"
IDENTITY_FILENAME = "identity.json"
LIFETIME_LOCK_FILENAME = "lifetime.lock"
SCHEMA_VERSION = 1


def _git(repo: Path, *args: str, env: Mapping[str, str] | None = None) -> bytes:
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    process = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=command_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode:
        detail = process.stderr.decode("utf-8", "replace").strip()
        raise ContentPortError(f"git {' '.join(args)} failed: {detail}")
    return process.stdout


def _git_path(repo: Path, name: str) -> Path:
    raw = _git(repo, "rev-parse", "--path-format=absolute", "--git-path", name)
    return Path(raw.decode().strip())


def transaction_paths(repo: Path) -> tuple[Path, Path, Path]:
    state = _git_path(repo, STATE_DIRECTORY)
    return state, state / GUARD_FILENAME, state / JOURNAL_FILENAME


@contextmanager
def transaction_lifetime_lock(repo: Path, *, exclusive: bool) -> Iterator[None]:
    state, _, _ = transaction_paths(repo.resolve())
    state.mkdir(parents=True, exist_ok=True)
    path = state / LIFETIME_LOCK_FILENAME
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        fcntl.flock(
            descriptor,
            (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH),
        )
        yield
    finally:
        os.close(descriptor)


def guard_active(repo: Path) -> bool:
    state, guard, journal = transaction_paths(repo)
    lock = state / LOCK_FILENAME
    identity = state / IDENTITY_FILENAME
    return any(_path_present(path) for path in (guard, journal, lock, identity))


def _path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def require_no_active_transaction(repo: Path) -> None:
    if guard_active(repo):
        raise ContentPortError(
            "active content-port apply transaction; wait for any running apply, then run "
            "`python3 -m tools.content_port resume --repo .` or "
            "`python3 -m tools.content_port recover --repo .`"
        )


def _acquire_creation_lock(state: Path, transaction_id: str) -> tuple[Path, int]:
    lock = state / LOCK_FILENAME
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "transactionId": transaction_id,
        "lockProtocol": "flock-v1",
    }
    temporary = state / f".{LOCK_FILENAME}.{transaction_id}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(
        temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o644
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(
            descriptor,
            (
                json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode(),
        )
        os.fsync(descriptor)
        try:
            os.link(temporary, lock)
        except FileExistsError as error:
            raise ContentPortError(
                "another content-port transaction is being created"
            ) from error
        _fsync_directory(state)
        return lock, descriptor
    except BaseException:
        os.close(descriptor)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def _claim_orphaned_creation_lock(lock: Path) -> int:
    flags = os.O_RDWR | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock, flags)
    except OSError as error:
        raise ContentPortError(
            "transaction creation lock is not a safe regular file"
        ) from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ContentPortError("transaction creation lock is not a regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ContentPortError(
                "content-port apply transaction is still being created; wait for it to finish"
            ) from error
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            payload = json.loads(os.read(descriptor, 65536).decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ContentPortError(
                "transaction creation lock liveness cannot be established"
            ) from error
        if not isinstance(payload, dict) or payload.get("lockProtocol") != "flock-v1":
            raise ContentPortError(
                "transaction creation lock liveness cannot be established"
            )
        opened = os.fstat(descriptor)
        current = lock.stat(follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise ContentPortError("transaction creation lock changed while opening it")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _release_creation_lock(lock: Path, descriptor: int, *, remove: bool) -> None:
    try:
        if remove:
            opened = os.fstat(descriptor)
            current = lock.stat(follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise ContentPortError(
                    "transaction creation lock changed while it was held"
                )
            lock.unlink()
            _fsync_directory(lock.parent)
    finally:
        os.close(descriptor)


def require_clean_task_worktree(repo: Path) -> None:
    repo = repo.resolve()
    require_no_active_transaction(repo)
    branch = _git(repo, "branch", "--show-current").decode().strip()
    if not branch.startswith("task/"):
        raise ContentPortError(
            f"apply requires a non-detached task/* branch; found {branch or 'detached HEAD'}"
        )
    if _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
        raise ContentPortError("apply requires a clean index and working tree")


def canonical_bundle_digest(bundle: Path) -> str:
    digest = hashlib.sha256()
    for name in ("desired.patch", "ownership.json", "report.json"):
        path = bundle / name
        if not path.is_file():
            raise ContentPortError(f"bundle is missing {name}")
        data = path.read_bytes()
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def require_bundle_digest(bundle: Path, expected: str) -> str:
    actual = canonical_bundle_digest(bundle)
    normalized = expected.lower()
    if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
        raise ContentPortError(
            "bundle SHA-256 must be 64 lowercase hexadecimal characters"
        )
    if not hmac.compare_digest(actual, normalized):
        raise ContentPortError(
            f"bundle digest mismatch: expected {normalized}, found {actual}"
        )
    return actual


def _encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _decode(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"), validate=True)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _safe_path(repo: Path, raw: str) -> Path:
    pure = PurePosixPath(raw)
    if not raw or pure.is_absolute() or ".." in pure.parts or "." in pure.parts:
        raise ContentPortError(f"unsafe bundle path: {raw!r}")
    candidate = repo.joinpath(*pure.parts)
    current = repo
    for part in pure.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise ContentPortError(f"bundle path traverses symlink: {raw}")
    if candidate.is_symlink():
        raise ContentPortError(f"bundle path is a symlink: {raw}")
    return candidate


def _mode_for_path(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _index_entry(
    repo: Path, path: str, index: Path | None = None
) -> dict[str, Any] | None:
    env = {"GIT_INDEX_FILE": str(index)} if index else None
    raw = _git(repo, "ls-files", "--stage", "-z", "--", path, env=env)
    if not raw:
        return None
    first = raw.split(b"\0", 1)[0]
    metadata, actual_path = first.split(b"\t", 1)
    mode, oid, stage = metadata.decode().split()
    if stage != "0" or actual_path.decode("utf-8", "surrogateescape") != path:
        raise ContentPortError(f"unsupported non-stage-zero index entry for {path}")
    return {"mode": mode, "oid": oid}


def _materialize_expected(
    repo: Path,
    patch: Path,
    state: Path,
    path_order: tuple[str, ...],
    allowed_paths: frozenset[str],
) -> list[dict[str, Any]]:
    if not patch.read_bytes():
        return []
    actual_index = _git_path(repo, "index")
    temporary_index = state / f"index.expected.{uuid.uuid4().hex}"
    shutil.copyfile(actual_index, temporary_index)
    try:
        env = {"GIT_INDEX_FILE": str(temporary_index)}
        _git(
            repo,
            "apply",
            "--cached",
            "--binary",
            "--whitespace=nowarn",
            str(patch),
            env=env,
        )
        changed = _git(
            repo,
            "diff",
            "--cached",
            "--name-only",
            "-z",
            "--no-renames",
            "HEAD",
            env=env,
        )
        changed_paths = {
            item.decode("utf-8", "surrogateescape")
            for item in changed.split(b"\0")
            if item
        }
        unexpected = sorted(changed_paths - allowed_paths)
        if unexpected:
            raise ContentPortError(
                f"bundle patch modifies unowned path: {unexpected[0]}"
            )
        paths = [path for path in path_order if path in changed_paths]
        paths.extend(sorted(changed_paths - set(paths)))
        result: list[dict[str, Any]] = []
        for raw in paths:
            _safe_path(repo, raw)
            entry = _index_entry(repo, raw, temporary_index)
            if entry is None:
                result.append({"path": raw, "exists": False})
                continue
            if entry["mode"] not in ("100644", "100755"):
                raise ContentPortError(
                    f"bundle path has unsupported Git mode {entry['mode']}: {raw}"
                )
            content = _git(repo, "cat-file", "blob", entry["oid"])
            result.append(
                {
                    "path": raw,
                    "exists": True,
                    "mode": entry["mode"],
                    "oid": entry["oid"],
                    "sha256": _sha256(content),
                    "content": _encode(content),
                }
            )
        return result
    finally:
        temporary_index.unlink(missing_ok=True)


def _capture_preimages(
    repo: Path, expected: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in expected:
        raw = str(item["path"])
        path = _safe_path(repo, raw)
        index_entry = _index_entry(repo, raw)
        if path.exists():
            if not path.is_file():
                raise ContentPortError(f"owned path is not a regular file: {raw}")
            content = path.read_bytes()
            result.append(
                {
                    "path": raw,
                    "exists": True,
                    "mode": f"{_mode_for_path(path):06o}",
                    "sha256": _sha256(content),
                    "content": _encode(content),
                    "index": index_entry,
                }
            )
        else:
            result.append({"path": raw, "exists": False, "index": index_entry})
    return result


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_write(
        path, (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )


def _seal_journal(journal: dict[str, Any]) -> None:
    unsigned = dict(journal)
    unsigned.pop("journalSha256", None)
    journal["journalSha256"] = _sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    )


def _verify_journal(journal: Mapping[str, Any]) -> None:
    unsigned = dict(journal)
    claimed = unsigned.pop("journalSha256", None)
    actual = _sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    )
    if not isinstance(claimed, str) or not hmac.compare_digest(claimed, actual):
        raise ContentPortError("transaction journal checksum mismatch")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContentPortError(
            f"cannot read transaction state {path}: {error}"
        ) from error
    if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA_VERSION:
        raise ContentPortError(f"unsupported or corrupt transaction state: {path}")
    return value


def _read_bundle_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContentPortError(f"cannot read bundle report {path}: {error}") from error
    if not isinstance(value, dict):
        raise ContentPortError("bundle report must be a JSON object")
    return value


def _snapshot_bundle(bundle: Path, state: Path, transaction_id: str) -> Path:
    snapshot = state / f"bundle.{transaction_id}"
    snapshot.mkdir(mode=0o700)
    try:
        for name in ("desired.patch", "ownership.json", "report.json"):
            source = bundle / name
            if source.is_symlink() or not source.is_file():
                raise ContentPortError(
                    f"bundle artifact is missing or unsafe: {source}"
                )
            _atomic_write(snapshot / name, source.read_bytes())
    except BaseException:
        shutil.rmtree(snapshot, ignore_errors=True)
        raise
    return snapshot


def _publish_guard(path: Path, journal: Mapping[str, Any]) -> None:
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "transactionId": journal["transactionId"],
        "head": journal["head"],
    }
    temporary = (
        path.parent / f".{path.name}.{journal['transactionId']}.{uuid.uuid4().hex}.tmp"
    )
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(
                (
                    json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
                ).encode()
            )
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise ContentPortError(
                "another content-port apply transaction is active"
            ) from error
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _locked_marker_payload(transaction_id: str, kind: str) -> bytes:
    return (
        json.dumps(
            {
                "schemaVersion": SCHEMA_VERSION,
                "transactionId": transaction_id,
                "lockProtocol": "flock-v1",
                "kind": kind,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _create_locked_marker(path: Path, transaction_id: str, kind: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{transaction_id}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(
        temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o644
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(descriptor, _locked_marker_payload(transaction_id, kind))
        os.fsync(descriptor)
        os.link(temporary, path)
        _fsync_directory(path.parent)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def _claim_locked_marker(path: Path, transaction_id: str, kind: str) -> int:
    flags = os.O_RDWR | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ContentPortError(f"cannot open guarded Git {kind} lock") from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ContentPortError(f"guarded Git {kind} lock is not a regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ContentPortError(
                "another process is operating on the active content-port transaction"
            ) from error
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            payload = json.loads(os.read(descriptor, 65536).decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ContentPortError(
                f"existing Git {kind} lock is not owned by this transaction"
            ) from error
        if (
            not isinstance(payload, dict)
            or payload.get("lockProtocol") != "flock-v1"
            or payload.get("transactionId") != transaction_id
            or payload.get("kind") != kind
        ):
            raise ContentPortError(
                f"existing Git {kind} lock is not owned by this transaction"
            )
        opened = os.fstat(descriptor)
        current = path.stat(follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise ContentPortError(f"guarded Git {kind} lock changed while opening")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _publish_identity_marker(path: Path, journal: Mapping[str, Any]) -> bool:
    if _path_present(path):
        value = _read_json(path)
        if value.get("transactionId") != journal.get("transactionId"):
            raise ContentPortError("Git identity lock marker does not match journal")
        return False
    _write_json(
        path,
        {
            "schemaVersion": SCHEMA_VERSION,
            "transactionId": journal["transactionId"],
            "head": journal["head"],
            "branchRef": journal.get(
                "branchRef", f"refs/heads/{journal.get('branch')}"
            ),
        },
    )
    return True


@dataclass
class _GitIdentityLease:
    transaction_id: str
    marker: Path
    locks: list[tuple[Path, int, bool]]

    def release(self, *, remove: bool) -> None:
        error: BaseException | None = None
        for path, descriptor, _ in reversed(self.locks):
            try:
                _release_creation_lock(path, descriptor, remove=remove)
            except BaseException as caught:
                error = error or caught
        self.locks.clear()
        if remove and error is None and _path_present(self.marker):
            value = _read_json(self.marker)
            if value.get("transactionId") != self.transaction_id:
                raise ContentPortError(
                    "Git identity lock marker changed while it was held"
                )
            self.marker.unlink()
            _fsync_directory(self.marker.parent)
        if error is not None:
            raise error


def _acquire_git_identity(transaction: "ApplyTransaction") -> _GitIdentityLease:
    transaction_id = str(transaction.journal["transactionId"])
    marker = transaction.state / IDENTITY_FILENAME
    marker_created = _publish_identity_marker(marker, transaction.journal)
    branch_ref = transaction.journal.get(
        "branchRef", f"refs/heads/{transaction.journal.get('branch')}"
    )
    paths = (
        (_git_path(transaction.repo, "HEAD.lock"), "HEAD"),
        (_git_path(transaction.repo, f"{branch_ref}.lock"), "task branch"),
    )
    acquired: list[tuple[Path, int, bool]] = []
    try:
        for path, kind in paths:
            existed = _path_present(path)
            if existed:
                descriptor = _claim_locked_marker(path, transaction_id, kind)
            else:
                try:
                    descriptor = _create_locked_marker(path, transaction_id, kind)
                except FileExistsError:
                    existed = True
                    descriptor = _claim_locked_marker(path, transaction_id, kind)
            acquired.append((path, descriptor, existed))
        return _GitIdentityLease(transaction_id, marker, acquired)
    except BaseException:
        for path, descriptor, existed in reversed(acquired):
            _release_creation_lock(path, descriptor, remove=not existed)
        if marker_created and not any(existed for _, _, existed in acquired):
            marker.unlink(missing_ok=True)
            _fsync_directory(marker.parent)
        raise


@contextmanager
def _hold_git_identity(transaction: "ApplyTransaction") -> Iterator[None]:
    lease = _acquire_git_identity(transaction)
    try:
        yield
    except BaseException as error:
        identity_changed = isinstance(error, ContentPortError) and str(
            error
        ).startswith("HEAD or task branch changed")
        if identity_changed:
            preserve = False
        else:
            try:
                preserve = transaction._publication_state_changed()
            except BaseException:
                preserve = True
        lease.release(remove=not preserve)
        raise
    else:
        completed = not _path_present(transaction.guard) and not _path_present(
            transaction.journal_path
        )
        lease.release(remove=True)
        if completed:
            checkpoint("after-guard-remove")


@dataclass
class ApplyTransaction:
    repo: Path
    state: Path
    guard: Path
    journal_path: Path
    journal: dict[str, Any]
    creation_lock_descriptor: int | None = None

    def __del__(self) -> None:
        descriptor = self.creation_lock_descriptor
        if descriptor is not None:
            self.creation_lock_descriptor = None
            os.close(descriptor)

    @classmethod
    def create(
        cls, repo: Path, bundle: Path, expected_sha256: str
    ) -> "ApplyTransaction":
        repo = repo.resolve()
        bundle = bundle.resolve()
        require_clean_task_worktree(repo)
        from .bundle import verify_bundle
        from .ownership import OwnershipManifest, verify_owned_baseline

        state, guard, journal_path = transaction_paths(repo)
        state.mkdir(parents=True, exist_ok=True)
        transaction_id = uuid.uuid4().hex
        lock, lock_descriptor = _acquire_creation_lock(state, transaction_id)
        snapshot: Path | None = None
        try:
            if _path_present(guard) or _path_present(journal_path):
                raise ContentPortError("another content-port transaction is active")
            if _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
                raise ContentPortError("apply requires a clean index and working tree")
            head = _git(repo, "rev-parse", "HEAD").decode().strip()
            branch = _git(repo, "branch", "--show-current").decode().strip()
            branch_ref = _git(repo, "symbolic-ref", "HEAD").decode().strip()
            snapshot = _snapshot_bundle(bundle, state, transaction_id)
            digest = require_bundle_digest(snapshot, expected_sha256)
            verified = verify_bundle(snapshot)
            if not hmac.compare_digest(verified, digest):
                raise ContentPortError("bundle verification digest mismatch")
            desired_manifest = OwnershipManifest.load(snapshot / "ownership.json")
            baseline_path = (
                repo
                / "tools/content_port/ports"
                / desired_manifest.port
                / "ownership.json"
            )
            baseline_manifest = None
            if baseline_path.is_file():
                baseline_manifest = OwnershipManifest.load(baseline_path)
            if baseline_manifest is not None:
                verify_owned_baseline(repo, baseline_manifest)
            report = _read_bundle_report(snapshot / "report.json")
            if report.get("baseCommit") != head:
                raise ContentPortError(
                    f"bundle base commit {report.get('baseCommit')} does not match HEAD {head}"
                )
            ordered_paths = tuple(
                dict.fromkeys(unit.path for unit in desired_manifest.units)
            )
            allowed_paths = {unit.path for unit in desired_manifest.units}
            if baseline_manifest is not None:
                allowed_paths.update(unit.path for unit in baseline_manifest.units)
            manifest_relative = baseline_path.relative_to(repo).as_posix()
            allowed_paths.add(manifest_relative)
            expected = _materialize_expected(
                repo,
                snapshot / "desired.patch",
                state,
                ordered_paths,
                frozenset(allowed_paths),
            )
            installed_manifest = (
                baseline_path.read_bytes() if baseline_path.is_file() else None
            )
            desired_manifest_bytes = (snapshot / "ownership.json").read_bytes()
            expected_paths = {str(item["path"]) for item in expected}
            if (
                installed_manifest != desired_manifest_bytes
                and manifest_relative not in expected_paths
            ):
                raise ContentPortError(
                    "bundle patch does not install its ownership.json manifest"
                )
            expected_manifest_entry = next(
                (item for item in expected if item["path"] == manifest_relative), None
            )
            if expected_manifest_entry is not None and (
                not expected_manifest_entry["exists"]
                or _decode(str(expected_manifest_entry["content"]))
                != desired_manifest_bytes
            ):
                raise ContentPortError(
                    "bundle patch installs ownership.json content that differs from the bundle"
                )
            actual_index = _git_path(repo, "index")
            index = actual_index.read_bytes()
            journal: dict[str, Any] = {
                "schemaVersion": SCHEMA_VERSION,
                "transactionId": transaction_id,
                "repo": str(repo),
                "head": head,
                "branch": branch,
                "branchRef": branch_ref,
                "bundleDigest": digest,
                "indexSha256": _sha256(index),
                "index": _encode(index),
                "preimages": _capture_preimages(repo, expected),
                "expected": expected,
                "expectedManifest": desired_manifest.to_json(),
                "expectedManifestPath": manifest_relative,
                "expectedManifestSha256": _sha256(desired_manifest_bytes),
                "completed": [],
            }
            if (
                _git(repo, "rev-parse", "HEAD").decode().strip() != head
                or _git(repo, "branch", "--show-current").decode().strip() != branch
                or _git(repo, "symbolic-ref", "HEAD").decode().strip() != branch_ref
            ):
                raise ContentPortError("HEAD or task branch changed during apply setup")
            _seal_journal(journal)
            return cls(
                repo,
                state,
                guard,
                journal_path,
                journal,
                lock_descriptor,
            )
        except BaseException:
            _release_creation_lock(lock, lock_descriptor, remove=True)
            raise
        finally:
            if snapshot is not None:
                shutil.rmtree(snapshot, ignore_errors=True)

    @classmethod
    def open(cls, repo: Path) -> "ApplyTransaction":
        repo = repo.resolve()
        state, guard, journal_path = transaction_paths(repo)
        lock = state / LOCK_FILENAME
        lock_descriptor: int | None = None
        if not _path_present(guard) and not _path_present(journal_path):
            raise ContentPortError("no recoverable content-port apply transaction")
        if _path_present(lock):
            lock_descriptor = _claim_orphaned_creation_lock(lock)
        if not journal_path.is_file():
            if lock_descriptor is not None:
                _release_creation_lock(lock, lock_descriptor, remove=False)
            raise ContentPortError(
                "transaction creation was interrupted before the journal; run recover"
            )
        try:
            journal = _read_json(journal_path)
            _verify_journal(journal)
            if lock_descriptor is not None:
                lock_value = _read_json(lock)
                if lock_value.get("transactionId") != journal.get("transactionId"):
                    raise ContentPortError(
                        "transaction creation lock does not match its journal"
                    )
            if not _path_present(guard):
                _publish_guard(guard, journal)
            if not guard.is_file() or guard.is_symlink():
                raise ContentPortError("transaction guard is not a regular file")
            try:
                guard_value = _read_json(guard)
            except ContentPortError:
                if lock_descriptor is None:
                    raise
                guard.unlink()
                _fsync_directory(state)
                _publish_guard(guard, journal)
                guard_value = _read_json(guard)
            if guard_value.get("transactionId") != journal.get("transactionId"):
                raise ContentPortError("transaction guard does not match its journal")
            if lock_descriptor is not None:
                _release_creation_lock(lock, lock_descriptor, remove=True)
                lock_descriptor = None
            return cls(repo, state, guard, journal_path, journal)
        finally:
            if lock_descriptor is not None:
                _release_creation_lock(lock, lock_descriptor, remove=False)

    @property
    def units(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.journal["expected"])

    def write_and_fsync_preimage(self) -> None:
        _write_json(self.journal_path, self.journal)

    def acquire_guard(self) -> None:
        lock = self.state / LOCK_FILENAME
        descriptor = self.creation_lock_descriptor
        if descriptor is None:
            raise ContentPortError("transaction creation lock is not held")
        lock_value = _read_json(lock)
        if lock_value.get("transactionId") != self.journal["transactionId"]:
            raise ContentPortError(
                "transaction creation lock does not match its journal"
            )
        _publish_guard(self.guard, self.journal)
        self.creation_lock_descriptor = None
        _release_creation_lock(lock, descriptor, remove=True)

    def verify_identity(self) -> None:
        head = _git(self.repo, "rev-parse", "HEAD").decode().strip()
        branch = _git(self.repo, "branch", "--show-current").decode().strip()
        branch_ref = _git(self.repo, "symbolic-ref", "HEAD").decode().strip()
        expected_branch_ref = self.journal.get(
            "branchRef", f"refs/heads/{self.journal.get('branch')}"
        )
        if (
            head != self.journal.get("head")
            or branch != self.journal.get("branch")
            or branch_ref != expected_branch_ref
        ):
            raise ContentPortError(
                "HEAD or task branch changed during the active transaction"
            )

    def _preimages_by_path(self) -> dict[str, Mapping[str, Any]]:
        return {str(item["path"]): item for item in self.journal["preimages"]}

    def _unit_states(
        self, unit: Mapping[str, Any]
    ) -> tuple[
        tuple[bool, str | None, str | None],
        dict[str, Any] | None,
        tuple[bool, str | None, str | None],
        dict[str, Any] | None,
    ]:
        raw = str(unit["path"])
        preimage = self._preimages_by_path()[raw]
        preimage_index = preimage.get("index")
        if preimage_index is not None and not isinstance(preimage_index, dict):
            raise ContentPortError(f"invalid journaled index preimage: {raw}")
        expected_index = (
            {"mode": str(unit["mode"]), "oid": str(unit["oid"])}
            if unit["exists"]
            else None
        )
        return (
            _snapshot_expected(preimage),
            preimage_index,
            _snapshot_expected(unit),
            expected_index,
        )

    def _require_known_unit_state(
        self, unit: Mapping[str, Any], *, operation: str
    ) -> None:
        raw = str(unit["path"])
        preimage, preimage_index, expected, expected_index = self._unit_states(unit)
        actual = _snapshot_path(self.repo, raw)
        actual_index = _index_entry(self.repo, raw)
        if actual not in (preimage, expected) or actual_index not in (
            preimage_index,
            expected_index,
        ):
            raise ContentPortError(
                f"refusing to {operation} over changed transaction state: {raw}; "
                "preserve the edit elsewhere and restore the interrupted state before retrying"
            )

    def _require_known_transaction_state(self, *, operation: str) -> None:
        try:
            self._verify_no_unowned_changes()
        except ContentPortError as error:
            raise ContentPortError(
                f"refusing to {operation} over changed transaction state; "
                "preserve the edit elsewhere and restore the interrupted state before retrying: "
                f"{error}"
            ) from error
        for unit in self.units:
            self._require_known_unit_state(unit, operation=operation)

    def _publication_state_changed(self) -> bool:
        if self.journal["completed"]:
            return True
        for unit in self.units:
            raw = str(unit["path"])
            preimage, preimage_index, _, _ = self._unit_states(unit)
            if (
                _snapshot_path(self.repo, raw) != preimage
                or _index_entry(self.repo, raw) != preimage_index
            ):
                return True
        return False

    def apply_unit(self, unit: Mapping[str, Any]) -> None:
        raw = str(unit["path"])
        self._require_known_unit_state(unit, operation="apply")
        path = _safe_path(self.repo, raw)
        if unit["exists"]:
            content = _decode(str(unit["content"]))
            mode = int(str(unit["mode"]), 8) & 0o777
            _atomic_write(path, content, mode)
        elif path.exists():
            if not path.is_file():
                raise ContentPortError(f"refusing to remove non-file owned path: {raw}")
            path.unlink()
            _fsync_directory(path.parent)
        checkpoint(f"after-apply:{raw}")

        if _snapshot_path(self.repo, raw) != _snapshot_expected(unit):
            raise ContentPortError(
                f"owned path changed before index publication: {raw}"
            )
        self._require_known_unit_state(unit, operation="apply")

        if unit["exists"]:
            _git(
                self.repo,
                "update-index",
                "--add",
                "--cacheinfo",
                f"{unit['mode']},{unit['oid']},{raw}",
            )
        else:
            _git(self.repo, "update-index", "--force-remove", "--", raw)
        index = _git_path(self.repo, "index")
        with index.open("rb") as stream:
            os.fsync(stream.fileno())
        checkpoint(f"after-index:{raw}")

    def record_completed(self, unit: Mapping[str, Any]) -> None:
        raw = str(unit["path"])
        completed = self.journal["completed"]
        if raw not in completed:
            completed.append(raw)
        _seal_journal(self.journal)
        _write_json(self.journal_path, self.journal)

    def verify_expected_tree(self) -> None:
        for unit in self.units:
            raw = str(unit["path"])
            path = _safe_path(self.repo, raw)
            entry = _index_entry(self.repo, raw)
            if unit["exists"]:
                if not path.is_file() or _sha256(path.read_bytes()) != unit["sha256"]:
                    raise ContentPortError(
                        f"expected result mismatch in working tree: {raw}"
                    )
                if (
                    entry is None
                    or entry["oid"] != unit["oid"]
                    or entry["mode"] != unit["mode"]
                ):
                    raise ContentPortError(f"expected result mismatch in index: {raw}")
            elif path.exists() or entry is not None:
                raise ContentPortError(f"expected deleted path remains: {raw}")
        from .ownership import OwnershipManifest

        OwnershipManifest.from_json(self.journal["expectedManifest"]).verify(self.repo)
        manifest_path = _safe_path(self.repo, self.journal["expectedManifestPath"])
        if (
            not manifest_path.is_file()
            or _sha256(manifest_path.read_bytes())
            != self.journal["expectedManifestSha256"]
        ):
            raise ContentPortError(
                "applied tree does not install the bundle ownership manifest"
            )
        self._verify_no_unowned_changes()

    def _verify_no_unowned_changes(self) -> None:
        allowed = {str(unit["path"]) for unit in self.units}
        changed: set[str] = set()
        for arguments in (
            ("diff", "--name-only", "-z", "HEAD"),
            ("ls-files", "--others", "--exclude-standard", "-z"),
        ):
            raw = _git(self.repo, *arguments)
            changed.update(
                item.decode("utf-8", "surrogateescape")
                for item in raw.split(b"\0")
                if item
            )
        unexpected = sorted(changed - allowed)
        if unexpected:
            raise ContentPortError(
                f"path outside the transaction changed while guarded: {unexpected[0]}"
            )

    def release_guard(self) -> None:
        self.guard.unlink()
        _fsync_directory(self.state)
        self.journal_path.unlink(missing_ok=True)
        _fsync_directory(self.state)

    def _run_locked(self) -> None:
        self.verify_identity()
        self._require_known_transaction_state(operation="apply")
        completed = set(self.journal["completed"])
        for unit in self.units:
            if unit["path"] in completed:
                continue
            self.apply_unit(unit)
            self.record_completed(unit)
        self.verify_expected_tree()
        self.release_guard()

    def run(self) -> None:
        with _hold_git_identity(self):
            self._run_locked()

    def resume(self) -> None:
        with _hold_git_identity(self):
            self.verify_identity()
            self._verify_no_unowned_changes()
            completed = set(self.journal["completed"])
            preimages = {item["path"]: item for item in self.journal["preimages"]}
            for unit in self.units:
                raw = unit["path"]
                actual = _snapshot_path(self.repo, raw)
                expected = _snapshot_expected(unit)
                preimage = _snapshot_expected(preimages[raw])
                if raw in completed and actual != expected:
                    raise ContentPortError(
                        f"completed owned path changed during interruption: {raw}"
                    )
                if raw not in completed and actual not in (preimage, expected):
                    raise ContentPortError(
                        f"incomplete owned path changed during interruption: {raw}"
                    )
            self._run_locked()

    def recover(self) -> None:
        with _hold_git_identity(self):
            self.verify_identity()
            self._require_known_transaction_state(operation="recover")
            index = _decode(str(self.journal["index"]))
            if _sha256(index) != self.journal["indexSha256"]:
                raise ContentPortError("journaled index preimage checksum mismatch")
            for unit in reversed(self.journal["preimages"]):
                raw = str(unit["path"])
                path = _safe_path(self.repo, raw)
                if unit["exists"]:
                    _atomic_write(
                        path,
                        _decode(str(unit["content"])),
                        int(str(unit["mode"]), 8),
                    )
                elif path.exists():
                    if not path.is_file():
                        raise ContentPortError(
                            f"refusing to recover over non-file path: {raw}"
                        )
                    path.unlink()
                    _fsync_directory(path.parent)
                checkpoint(f"after-recover:{raw}")
            index_path = _git_path(self.repo, "index")
            _atomic_write(index_path, index)
            if _git(
                self.repo, "status", "--porcelain=v1", "-z", "--untracked-files=all"
            ):
                raise ContentPortError("recovery did not reproduce the clean preimage")
            self.release_guard()


def _snapshot_path(repo: Path, raw: str) -> tuple[bool, str | None, str | None]:
    path = _safe_path(repo, raw)
    if not path.exists():
        return False, None, None
    if not path.is_file():
        raise ContentPortError(f"owned path is not a regular file: {raw}")
    return True, f"{_mode_for_path(path):06o}", _sha256(path.read_bytes())


def _snapshot_expected(unit: Mapping[str, Any]) -> tuple[bool, str | None, str | None]:
    if not unit["exists"]:
        return False, None, None
    mode = str(unit["mode"])
    if len(mode) == 6 and mode.startswith("100"):
        mode = f"{int(mode, 8) & 0o777:06o}"
    return True, mode, str(unit["sha256"])


def apply_bundle(repo: Path, bundle: Path, expected_sha256: str) -> None:
    with transaction_lifetime_lock(repo, exclusive=True):
        transaction = ApplyTransaction.create(repo, bundle, expected_sha256)
        transaction.write_and_fsync_preimage()
        checkpoint("after-journal-fsync")
        transaction.acquire_guard()
        checkpoint("after-guard-create")
        transaction.run()


def resume_transaction(repo: Path) -> None:
    with transaction_lifetime_lock(repo, exclusive=True):
        ApplyTransaction.open(repo).resume()


def _release_completed_identity(repo: Path, state: Path, marker: Path) -> None:
    value = _read_json(marker)
    transaction_id = value.get("transactionId")
    branch_ref = value.get("branchRef")
    if not isinstance(transaction_id, str) or not isinstance(branch_ref, str):
        raise ContentPortError("completed Git identity lock marker is corrupt")
    acquired: list[tuple[Path, int]] = []
    try:
        for path, kind in (
            (_git_path(repo, "HEAD.lock"), "HEAD"),
            (_git_path(repo, f"{branch_ref}.lock"), "task branch"),
        ):
            if _path_present(path):
                acquired.append(
                    (path, _claim_locked_marker(path, transaction_id, kind))
                )
        while acquired:
            path, descriptor = acquired.pop()
            _release_creation_lock(path, descriptor, remove=True)
        marker.unlink()
        _fsync_directory(state)
    finally:
        for _, descriptor in acquired:
            os.close(descriptor)


def _recover_transaction_locked(repo: Path) -> None:
    repo = repo.resolve()
    state, guard, journal = transaction_paths(repo)
    lock = state / LOCK_FILENAME
    identity = state / IDENTITY_FILENAME
    if (
        _path_present(identity)
        and not _path_present(lock)
        and not _path_present(guard)
        and not _path_present(journal)
    ):
        _release_completed_identity(repo, state, identity)
        return
    if _path_present(lock) and not _path_present(guard) and not _path_present(journal):
        descriptor = _claim_orphaned_creation_lock(lock)
        _release_creation_lock(lock, descriptor, remove=True)
        return
    ApplyTransaction.open(repo).recover()


def recover_transaction(repo: Path) -> None:
    with transaction_lifetime_lock(repo, exclusive=True):
        _recover_transaction_locked(repo)
