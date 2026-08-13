"""Disposable detached Git worktrees used for desired-state construction."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from typing import BinaryIO, Iterator, Mapping, Sequence

from .errors import ContentPortError
from .faults import checkpoint
from .ownership import safe_repo_path


DETERMINISTIC_ENV: Mapping[str, str] = {
    "LC_ALL": "C",
    "LANG": "C",
    "TZ": "UTC",
    "GIT_CONFIG_NOSYSTEM": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
}


@dataclass(frozen=True)
class ValidationResult:
    validator_id: str
    command: tuple[str, ...]
    output_sha256: str


def git(
    repo: Path,
    arguments: Sequence[str],
    *,
    check: bool = True,
    text: bool = False,
) -> bytes | str:
    environment = os.environ.copy()
    environment.update(DETERMINISTIC_ENV)
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
    )
    if check and result.returncode:
        stderr = result.stderr.strip()
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        raise ContentPortError(f"git {' '.join(arguments)} failed: {stderr}")
    return result.stdout


def repository_root(repo: Path) -> Path:
    output = git(repo, ["rev-parse", "--show-toplevel"], text=True)
    assert isinstance(output, str)
    root = Path(output.strip()).resolve()
    if repo.resolve() != root:
        raise ContentPortError(
            f"content-port repository must be its worktree root: {repo}"
        )
    return root


def require_clean_worktree(repo: Path) -> None:
    output = git(repo, ["status", "--porcelain=v1", "--untracked-files=all"], text=True)
    assert isinstance(output, str)
    if output:
        raise ContentPortError("bundle construction requires a clean worktree")


@contextmanager
def detached_worktree(repo: Path, revision: str = "HEAD") -> Iterator[Path]:
    """Yield a clean detached worktree and remove only that created worktree."""

    repo = repository_root(repo)
    if not revision or revision.startswith("-"):
        raise ContentPortError(f"invalid staging revision {revision!r}")
    resolved = git(repo, ["rev-parse", "--verify", f"{revision}^{{commit}}"], text=True)
    assert isinstance(resolved, str)
    commit = resolved.strip()
    temporary_root = Path(tempfile.mkdtemp(prefix="content-port-worktree-"))
    staging = temporary_root / "repo"
    added = False
    try:
        git(
            repo, ["worktree", "add", "--detach", "--no-checkout", str(staging), commit]
        )
        added = True
        git(staging, ["checkout", "--detach", "--force", commit])
        yield staging
    finally:
        if added:
            result = subprocess.run(
                ["git", "worktree", "remove", "--force", str(staging)],
                cwd=repo,
                env={**os.environ, **DETERMINISTIC_ENV},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if result.returncode:
                raise ContentPortError(
                    "failed to remove disposable worktree: "
                    + result.stderr.decode(errors="replace").strip()
                )
        try:
            temporary_root.rmdir()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise ContentPortError(
                f"disposable worktree directory was not empty: {error}"
            ) from error


def run_validation_commands(root: Path, commands: Sequence[Sequence[str]]) -> None:
    for index, command in enumerate(commands):
        if not command or any(
            not isinstance(part, str) or not part for part in command
        ):
            raise ContentPortError(f"validation command {index} is invalid")
        result = subprocess.run(
            list(command),
            cwd=root,
            env={**os.environ, **DETERMINISTIC_ENV},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode:
            raise ContentPortError(
                f"validation command {index} ({' '.join(command)}) failed:\n{result.stdout}"
            )
        checkpoint(f"after-validation:{index}")


def run_named_validation_commands(
    root: Path,
    commands: Sequence[tuple[str, Sequence[str]]],
    output_root: Path,
    *,
    jobs: int,
) -> tuple[ValidationResult, ...]:
    """Run named validators with isolated outputs and fail-fast cancellation."""

    if jobs < 1:
        raise ContentPortError("validation jobs must be at least 1")
    validated: list[tuple[str, tuple[str, ...]]] = []
    seen: set[str] = set()
    for validator_id, raw_command in commands:
        command = tuple(raw_command)
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", validator_id):
            raise ContentPortError(f"invalid validator id {validator_id!r}")
        if validator_id in seen:
            raise ContentPortError(f"duplicate validator id {validator_id}")
        if not command or any(
            not isinstance(part, str) or not part for part in command
        ):
            raise ContentPortError(f"validation command {validator_id} is invalid")
        seen.add(validator_id)
        validated.append((validator_id, command))

    output_root.mkdir(parents=True, exist_ok=True)
    prepared_state = _validation_tree_digest(root, output_root)
    active: dict[
        subprocess.Popen[bytes],
        tuple[str, tuple[str, ...], BinaryIO, Path, Path | None, str],
    ] = {}
    completed: dict[str, ValidationResult] = {}
    next_index = 0

    def terminate_active() -> None:
        for process in active:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 5
        for process in active:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    pass
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()

    try:
        while next_index < len(validated) or active:
            finished_processes = [
                process for process in active if process.poll() is not None
            ]
            if finished_processes:
                finished = next(
                    (process for process in finished_processes if process.returncode),
                    finished_processes[0],
                )
                validator_id, command, stream, log, private_root, initial_state = (
                    active.pop(finished)
                )
                stream.close()
                output = log.read_bytes()
                if finished.returncode:
                    terminate_active()
                    if private_root is not None:
                        shutil.rmtree(private_root.parent, ignore_errors=True)
                    rendered = output.decode(errors="replace")
                    raise ContentPortError(
                        f"validator {validator_id} ({' '.join(command)}) failed:\n{rendered}"
                    )
                checked_root = private_root if private_root is not None else root
                state_exclusion = output_root if private_root is None else None
                if (
                    _validation_tree_digest(checked_root, state_exclusion)
                    != initial_state
                ):
                    terminate_active()
                    if private_root is not None:
                        shutil.rmtree(private_root.parent, ignore_errors=True)
                    raise ContentPortError(
                        f"validator {validator_id} changed prepared artifacts or input tree; "
                        "changed the staged desired tree"
                    )
                completed[validator_id] = ValidationResult(
                    validator_id,
                    command,
                    hashlib.sha256(output).hexdigest(),
                )
                if private_root is not None:
                    shutil.rmtree(private_root.parent, ignore_errors=True)
                checkpoint(f"after-validation:{validator_id}")
                continue

            while next_index < len(validated) and len(active) < jobs:
                validator_id, command = validated[next_index]
                next_index += 1
                result_dir = output_root / validator_id
                result_dir.mkdir()
                log = result_dir / "output.log"
                expanded = tuple(
                    part.replace("{results}", str(result_dir)) for part in command
                )
                environment = {
                    **os.environ,
                    **DETERMINISTIC_ENV,
                    "CONTENT_PORT_VALIDATOR_ID": validator_id,
                    "CONTENT_PORT_VALIDATOR_RESULTS": str(result_dir),
                }
                private_root: Path | None = None
                command_root = root
                if jobs > 1:
                    private_root = _private_validation_root(
                        root, validator_id, output_root
                    )
                    command_root = private_root
                initial_state = _validation_tree_digest(
                    command_root, output_root if private_root is None else None
                )
                if initial_state != prepared_state:
                    if private_root is not None:
                        shutil.rmtree(private_root.parent, ignore_errors=True)
                    raise ContentPortError(
                        f"validator {validator_id} private snapshot differs from prepared input"
                    )
                stream = log.open("wb")
                try:
                    process = subprocess.Popen(
                        expanded,
                        cwd=command_root,
                        env=environment,
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                except OSError as error:
                    stream.close()
                    if private_root is not None:
                        shutil.rmtree(private_root.parent, ignore_errors=True)
                    raise ContentPortError(
                        f"cannot start validator {validator_id}: {error}"
                    ) from error
                active[process] = (
                    validator_id,
                    command,
                    stream,
                    log,
                    private_root,
                    initial_state,
                )

            if active:
                time.sleep(0.02)
    finally:
        terminate_active()
        for _, _, stream, _, private_root, _ in active.values():
            stream.close()
            if private_root is not None:
                shutil.rmtree(private_root.parent, ignore_errors=True)

    return tuple(completed[validator_id] for validator_id, _ in validated)


def _private_validation_root(root: Path, validator_id: str, output_root: Path) -> Path:
    """Reflink the once-prepared candidate into a validator-private Git clone."""

    temporary = Path(tempfile.mkdtemp(prefix=f"content-port-{validator_id}-"))
    private = temporary / "repo"
    try:
        is_git = (
            subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=root,
                env={**os.environ, **DETERMINISTIC_ENV},
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            == 0
        )
        private.mkdir() if not is_git else None
        clone = (
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--quiet",
                    "--shared",
                    "--no-checkout",
                    str(root),
                    str(private),
                ],
                env={**os.environ, **DETERMINISTIC_ENV},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if is_git
            else None
        )
        if clone is not None and clone.returncode:
            raise ContentPortError(
                "cannot create private validator repository: "
                + clone.stderr.decode(errors="replace").strip()
            )
        for child in root.iterdir():
            if child.name == ".git":
                continue
            if child.resolve() == output_root.resolve():
                continue
            copied = subprocess.run(
                [
                    "cp",
                    "--archive",
                    "--reflink=auto",
                    "--",
                    str(child),
                    str(private / child.name),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if copied.returncode:
                raise ContentPortError(
                    "cannot copy prepared validator input: "
                    + copied.stderr.decode(errors="replace").strip()
                )
        return private
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _validation_tree_digest(root: Path, excluded: Path | None = None) -> str:
    """Hash validator-visible input without following links or Git internals."""

    digest = hashlib.sha256()
    excluded = excluded.resolve() if excluded is not None else None

    def add(value: bytes) -> None:
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)

    def visit(path: Path) -> None:
        if excluded is not None and (
            path.resolve() == excluded or excluded in path.resolve().parents
        ):
            return
        relative = path.relative_to(root).as_posix().encode()
        metadata = path.lstat()
        add(relative)
        add(stat.S_IFMT(metadata.st_mode).to_bytes(4, "big"))
        mode = 0 if path == root else stat.S_IMODE(metadata.st_mode)
        add(mode.to_bytes(4, "big"))
        if stat.S_ISLNK(metadata.st_mode):
            add(os.readlink(path).encode())
        elif stat.S_ISREG(metadata.st_mode):
            content = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    content.update(chunk)
            add(content.digest())
        elif stat.S_ISDIR(metadata.st_mode):
            names = sorted(
                entry.name
                for entry in os.scandir(path)
                if not (path == root and entry.name == ".git")
            )
            for name in names:
                visit(path / name)
        else:
            raise ContentPortError(
                f"validator input contains unsupported file type: {path.relative_to(root)}"
            )

    visit(root)
    return digest.hexdigest()


def assert_output_path(root: Path, relative: str) -> Path:
    """Public safe-path helper for bundle and transaction callers."""

    return safe_repo_path(root, relative)
