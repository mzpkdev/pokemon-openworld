"""Explicit installer for the checksum-pinned Probe standalone CLI."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

from .artifact import (
    ARCHIVE_NAME,
    ARCHIVE_ROOT,
    ARCHIVE_SHA256,
    ARCHIVE_URL,
    BINARY_SHA256,
    LICENSE_SHA256,
    TARGET,
    VERSION,
    ArtifactError,
    binary_path,
    repository_root,
    sha256,
)

DOWNLOAD_BYTES = 16 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 30
EXPECTED_FILES = {
    PurePosixPath(ARCHIVE_ROOT) / "probe": ("probe", 0o755),
    PurePosixPath(ARCHIVE_ROOT) / "LICENSE": ("LICENSE", 0o644),
    PurePosixPath(ARCHIVE_ROOT) / "README.md": ("README.md", 0o644),
}


def _require_platform() -> None:
    machine = platform.machine().lower()
    if platform.system() != "Linux" or machine not in {"x86_64", "amd64"}:
        raise ArtifactError(
            f"unsupported platform: {platform.system()} {platform.machine()}; "
            "only Linux x86_64 is reviewed"
        )


def _download(destination: Path) -> None:
    request = urllib.request.Request(
        ARCHIVE_URL, headers={"User-Agent": "pokemon-openworld-probe-bootstrap/1"}
    )
    try:
        with (
            urllib.request.urlopen(
                request, timeout=DOWNLOAD_TIMEOUT_SECONDS
            ) as response,
            destination.open("wb") as output,
        ):
            remaining = DOWNLOAD_BYTES
            while remaining:
                chunk = response.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                output.write(chunk)
                remaining -= len(chunk)
            if response.read(1):
                raise ArtifactError("Probe archive exceeds the bootstrap download cap")
    except OSError as exc:
        raise ArtifactError(f"Probe download failed: {exc}") from exc


def _extract(archive: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = {
                PurePosixPath(member.name): member for member in bundle.getmembers()
            }
            archive_directory = PurePosixPath(ARCHIVE_ROOT)
            allowed = set(EXPECTED_FILES) | {archive_directory}
            if not set(EXPECTED_FILES).issubset(members) or not set(members).issubset(
                allowed
            ):
                raise ArtifactError("Probe archive has an unexpected file inventory")
            if archive_directory in members and not members[archive_directory].isdir():
                raise ArtifactError("Probe archive root is not a directory")
            for archive_path, (name, mode) in EXPECTED_FILES.items():
                member = members[archive_path]
                if not member.isfile() or member.issym() or member.islnk():
                    raise ArtifactError("Probe archive contains a non-regular file")
                source = bundle.extractfile(member)
                if source is None:
                    raise ArtifactError(f"Probe archive cannot read {archive_path}")
                target = destination / name
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(mode)
    except (tarfile.TarError, OSError) as exc:
        if isinstance(exc, ArtifactError):
            raise
        raise ArtifactError(f"invalid Probe archive: {exc}") from exc


def install(root: Path, archive: Path | None = None) -> Path:
    _require_platform()
    root = root.resolve()
    destination = binary_path(root).parent
    try:
        destination.resolve(strict=False).relative_to(root)
    except (RuntimeError, ValueError) as exc:
        raise ArtifactError("Probe cache path escapes the active worktree") from exc
    if destination.is_symlink():
        raise ArtifactError("Probe cache version path must not be a symlink")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".probe-bootstrap-", dir=destination.parent
    ) as temporary:
        temporary_path = Path(temporary)
        archive_path = archive.resolve() if archive else temporary_path / ARCHIVE_NAME
        if archive is None:
            _download(archive_path)
        if not archive_path.is_file():
            raise ArtifactError("Probe archive does not exist")
        if sha256(archive_path) != ARCHIVE_SHA256:
            raise ArtifactError("Probe archive checksum mismatch")
        extracted = temporary_path / "extracted"
        extracted.mkdir()
        _extract(archive_path, extracted)
        if sha256(extracted / "probe") != BINARY_SHA256:
            raise ArtifactError("Probe executable checksum mismatch")
        if sha256(extracted / "LICENSE") != LICENSE_SHA256:
            raise ArtifactError("Probe license checksum mismatch")
        manifest = {
            "archive": ARCHIVE_NAME,
            "archive_sha256": ARCHIVE_SHA256,
            "binary_sha256": BINARY_SHA256,
            "license": "Apache-2.0",
            "license_sha256": LICENSE_SHA256,
            "target": TARGET,
            "version": VERSION,
        }
        (extracted / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(extracted, destination)
    return destination / "probe"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        help="install from this already-downloaded pinned archive",
    )
    args = parser.parse_args(argv)
    try:
        installed = install(repository_root(), args.archive)
    except ArtifactError as exc:
        print(f"probe bootstrap failed: {exc}", file=sys.stderr)
        return 1
    print(installed.relative_to(repository_root()).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
