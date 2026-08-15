from __future__ import annotations

import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.probe_retrieval import bootstrap
from tools.probe_retrieval.artifact import ArtifactError


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _archive(path: Path, *, extra: bool = False) -> tuple[bytes, bytes]:
    binary = b"#!/bin/sh\nexit 0\n"
    license_text = b"Apache License\nVersion 2.0\n"
    files = {
        f"{bootstrap.ARCHIVE_ROOT}/probe": binary,
        f"{bootstrap.ARCHIVE_ROOT}/LICENSE": license_text,
        f"{bootstrap.ARCHIVE_ROOT}/README.md": b"Probe\n",
    }
    if extra:
        files[f"{bootstrap.ARCHIVE_ROOT}/unexpected"] = b"no\n"
    with tarfile.open(path, "w:gz") as bundle:
        directory = tarfile.TarInfo(bootstrap.ARCHIVE_ROOT)
        directory.type = tarfile.DIRTYPE
        bundle.addfile(directory)
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            bundle.addfile(member, io.BytesIO(content))
    return binary, license_text


class BootstrapTests(unittest.TestCase):
    def test_checksum_failure_leaves_no_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "probe.tar.gz"
            archive.write_bytes(b"wrong")
            with self.assertRaisesRegex(ArtifactError, "checksum mismatch"):
                bootstrap.install(root, archive)
            self.assertFalse(
                (root / ".cache/probe" / bootstrap.VERSION / bootstrap.TARGET).exists()
            )

    def test_installs_reviewed_inventory_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "probe.tar.gz"
            binary, license_text = _archive(archive)
            with (
                mock.patch.object(
                    bootstrap, "ARCHIVE_SHA256", bootstrap.sha256(archive)
                ),
                mock.patch.object(bootstrap, "BINARY_SHA256", _digest(binary)),
                mock.patch.object(bootstrap, "LICENSE_SHA256", _digest(license_text)),
            ):
                installed = bootstrap.install(root, archive)
            self.assertTrue(installed.is_file())
            self.assertEqual(installed.stat().st_mode & 0o777, 0o755)
            self.assertIn(
                '"license": "Apache-2.0"',
                (installed.parent / "manifest.json").read_text(),
            )

    def test_unexpected_archive_inventory_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "probe.tar.gz"
            binary, license_text = _archive(archive, extra=True)
            with (
                mock.patch.object(
                    bootstrap, "ARCHIVE_SHA256", bootstrap.sha256(archive)
                ),
                mock.patch.object(bootstrap, "BINARY_SHA256", _digest(binary)),
                mock.patch.object(bootstrap, "LICENSE_SHA256", _digest(license_text)),
                self.assertRaisesRegex(ArtifactError, "unexpected file inventory"),
            ):
                bootstrap.install(root, archive)

    def test_unsupported_platform_fails_before_download(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.object(bootstrap.platform, "system", return_value="Darwin"),
            mock.patch.object(bootstrap.platform, "machine", return_value="arm64"),
            mock.patch.object(bootstrap, "_download") as download,
            self.assertRaisesRegex(ArtifactError, "unsupported platform"),
        ):
            bootstrap.install(Path(temporary))
        download.assert_not_called()

    def test_cache_symlink_escape_fails_closed(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            tempfile.TemporaryDirectory() as outside,
        ):
            root = Path(temporary)
            (root / ".cache").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ArtifactError, "cache path escapes"):
                bootstrap.install(root)


if __name__ == "__main__":
    unittest.main()
