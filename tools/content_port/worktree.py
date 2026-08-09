"""Disposable detached Git worktrees used for desired-state construction."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Iterator, Mapping, Sequence

from .errors import ContentPortError
from .faults import checkpoint
from .ownership import safe_repo_path


DETERMINISTIC_ENV: Mapping[str, str] = {
    "LC_ALL": "C",
    "LANG": "C",
    "TZ": "UTC",
    "GIT_CONFIG_NOSYSTEM": "1",
}


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


def assert_output_path(root: Path, relative: str) -> Path:
    """Public safe-path helper for bundle and transaction callers."""

    return safe_repo_path(root, relative)
