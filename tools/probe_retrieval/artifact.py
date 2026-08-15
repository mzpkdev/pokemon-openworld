"""Immutable metadata for the reviewed Probe standalone artifact."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

VERSION = "v0.6.0-rc331"
TARGET = "x86_64-unknown-linux-musl"
ARCHIVE_NAME = f"probe-{VERSION}-{TARGET}.tar.gz"
ARCHIVE_URL = (
    f"https://github.com/probelabs/probe/releases/download/{VERSION}/{ARCHIVE_NAME}"
)
ARCHIVE_SHA256 = "404a10ca8f1e28cdae13855883d632b79be1d85a692eb35db33627268629fee4"
BINARY_SHA256 = "0f5e76b3a12abcdfe578b62ab87f04f454bbda2c84cde21bf65f9db38f635048"
LICENSE_SHA256 = "793b7448f5beb1535d9197bd3d2fd2f167c22322e3457465eec50159d96d7858"
ARCHIVE_ROOT = f"probe-{VERSION}-{TARGET}"
CACHE_RELATIVE = Path(".cache") / "probe" / VERSION / TARGET


class ArtifactError(RuntimeError):
    """The pinned artifact or repository context is invalid."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_root(cwd: Path | None = None) -> Path:
    location = (cwd or Path.cwd()).resolve()
    try:
        result = subprocess.run(
            ("git", "-C", str(location), "rev-parse", "--show-toplevel"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArtifactError(f"could not locate the Git worktree: {exc}") from exc
    if result.returncode != 0:
        raise ArtifactError("run this command inside a Git worktree")
    try:
        root = Path(result.stdout.decode("utf-8", errors="strict").strip()).resolve()
    except UnicodeDecodeError as exc:
        raise ArtifactError("Git returned a non-UTF-8 worktree path") from exc
    if not root.is_dir():
        raise ArtifactError("Git reported a missing worktree root")
    return root


def binary_path(root: Path) -> Path:
    return root / CACHE_RELATIVE / "probe"


def verified_binary(root: Path) -> Path:
    binary = binary_path(root)
    if not binary.is_file():
        raise ArtifactError(
            "Probe is not installed; run python3 -m tools.probe_retrieval.bootstrap"
        )
    try:
        binary.resolve(strict=True).relative_to(root.resolve())
    except (RuntimeError, ValueError) as exc:
        raise ArtifactError(
            "cached Probe executable escapes the active worktree"
        ) from exc
    if sha256(binary) != BINARY_SHA256:
        raise ArtifactError(
            "cached Probe executable checksum mismatch; bootstrap again"
        )
    return binary
