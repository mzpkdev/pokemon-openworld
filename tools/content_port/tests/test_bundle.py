from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.content_port.bundle import (
    build_bundle,
    bundle_digest,
    validate_asset_ownership,
    verify_bundle,
)
from tools.content_port.errors import ContentPortError
from tools.content_port.ownership import (
    OwnershipManifest,
    OwnershipUnit,
    content_sha256,
)


def run(root: Path, *command: str) -> None:
    subprocess.run(
        command, cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )


class BundleTests(unittest.TestCase):
    def test_asset_ledger_and_ownership_are_exact(self) -> None:
        digest = content_sha256(b"asset")
        unit = OwnershipUnit("file", "data/tilesets/test/asset.bin", digest)
        manifest = OwnershipManifest("test", (unit,))
        asset = {
            "key": unit.path,
            "source": "donor",
            "donor": "fixture",
            "sourcePath": "asset.bin",
            "semanticTarget": unit.path,
            "sourceSha256": digest,
            "targetSha256": digest,
            "conversionCommand": ["copy-bytes"],
            "permission": "redistributable",
            "license": "fixture permission",
            "permissionEvidence": "fixture",
            "capability": "environment-assets",
            "supportState": "enabled",
        }
        policy = {"schemaVersion": 1, "assets": [asset]}
        validate_asset_ownership(manifest, policy)
        with self.assertRaisesRegex(ContentPortError, "hash differs"):
            validate_asset_ownership(
                OwnershipManifest(
                    "test",
                    (OwnershipUnit("file", unit.path, content_sha256(b"different")),),
                ),
                policy,
            )
        extra = OwnershipUnit(
            "file", "data/tilesets/test/unledgered.bin", content_sha256(b"extra")
        )
        with self.assertRaisesRegex(ContentPortError, "unledgered"):
            validate_asset_ownership(OwnershipManifest("test", (unit, extra)), policy)

    def make_repo(self, root: Path) -> None:
        run(root, "git", "init", "-q")
        run(root, "git", "config", "user.name", "Content Port Test")
        run(root, "git", "config", "user.email", "content-port@example.invalid")
        (root / "base.txt").write_text("base\n")
        run(root, "git", "add", "base.txt")
        run(root, "git", "commit", "-q", "-m", "base")

    def test_binary_bundle_is_deterministic_and_does_not_touch_caller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            self.make_repo(repo)
            binary = b"\x00\xff\x10content\x00"
            unit = OwnershipUnit("file", "generated/data.bin", content_sha256(binary))
            desired = OwnershipManifest("test", (unit,))
            payloads = {unit.identity: binary}
            first = build_bundle(
                repo,
                base / "first",
                desired,
                payloads,
                {"closureDigest": "abc"},
                validation_commands=[],
            )
            second = build_bundle(
                repo,
                base / "second",
                desired,
                payloads,
                {"closureDigest": "abc"},
                validation_commands=[],
            )
            for name in ("desired.patch", "ownership.json", "report.json"):
                self.assertEqual(
                    (first.output_dir / name).read_bytes(),
                    (second.output_dir / name).read_bytes(),
                )
            self.assertIn(b"GIT binary patch", first.patch.read_bytes())
            self.assertEqual(first.sha256, bundle_digest(first.output_dir))
            self.assertEqual(first.sha256, verify_bundle(first.output_dir))
            status = subprocess.check_output(["git", "status", "--porcelain"], cwd=repo)
            self.assertEqual(status, b"")

    def test_corrupt_patch_and_unsafe_artifacts_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            self.make_repo(repo)
            unit = OwnershipUnit("file", "new", content_sha256(b"new"))
            artifact = build_bundle(
                repo,
                base / "bundle",
                OwnershipManifest("test", (unit,)),
                {unit.identity: b"new"},
                validation_commands=[],
            )
            artifact.patch.write_bytes(b"corrupt")
            with self.assertRaisesRegex(ContentPortError, "does not match"):
                verify_bundle(artifact.output_dir)
            artifact.patch.unlink()
            artifact.patch.symlink_to(repo / "base.txt")
            with self.assertRaisesRegex(ContentPortError, "unsafe"):
                bundle_digest(artifact.output_dir)

    def test_dirty_caller_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_repo(root)
            (root / "dirty").write_text("dirty")
            with self.assertRaisesRegex(ContentPortError, "clean worktree"):
                build_bundle(
                    root,
                    root.parent / "bundle",
                    OwnershipManifest("test", ()),
                    {},
                    validation_commands=[],
                )

    def test_validation_cannot_mutate_desired_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            self.make_repo(repo)
            with self.assertRaisesRegex(
                ContentPortError, "changed the staged desired tree"
            ):
                build_bundle(
                    repo,
                    base / "bundle",
                    OwnershipManifest("test", ()),
                    {},
                    validation_commands=[
                        (
                            "python3",
                            "-c",
                            "from pathlib import Path; Path('base.txt').write_text('mutated')",
                        )
                    ],
                )


if __name__ == "__main__":
    unittest.main()
