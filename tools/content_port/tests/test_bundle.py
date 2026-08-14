from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.content_port.bundle import (
    _validate_asset_ownership,
    build_bundle,
    bundle_digest,
    validate_asset_ownership,
    verify_bundle,
)
from tools.content_port.errors import ContentPortError
from tools.content_port.ownership import (
    OwnershipManifest,
    OwnershipUnit,
    canonical_json,
    content_sha256,
)
from tools.content_port.update import canonical_bytes


def run(root: Path, *command: str) -> None:
    subprocess.run(
        command, cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )


class BundleTests(unittest.TestCase):
    def test_asset_ledger_and_ownership_are_exact(self) -> None:
        evidence_root = Path.cwd()
        evidence_digest = content_sha256((evidence_root / "CREDITS.md").read_bytes())
        permission_record = {
            "decision": "reviewed",
            "path": "CREDITS.md",
            "permission": "redistributable",
            "sha256": evidence_digest,
        }
        permission_digest = content_sha256(canonical_bytes(permission_record))
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
            "permissionEvidence": permission_digest,
            "capability": "environment-assets",
            "supportState": "enabled",
        }
        policy = {
            "schemaVersion": 1,
            "permissionRecords": {permission_digest: permission_record},
            "assets": [asset],
        }
        validate_asset_ownership(manifest, policy, evidence_root=evidence_root)
        reviewed_path = "data/tilesets/test/animation/frame.png"
        reviewed_digest = content_sha256(b"reviewed")
        reviewed_unit = OwnershipUnit("file", reviewed_path, reviewed_digest)
        reviewed_manifest = OwnershipManifest("test", (unit, reviewed_unit))
        _validate_asset_ownership(
            reviewed_manifest,
            policy,
            evidence_root=evidence_root,
            reviewed_targets={reviewed_path: reviewed_digest},
        )
        with self.assertRaisesRegex(ContentPortError, "missing reviewed file unit"):
            _validate_asset_ownership(
                manifest,
                policy,
                evidence_root=evidence_root,
                reviewed_targets={reviewed_path: reviewed_digest},
            )
        with self.assertRaisesRegex(ContentPortError, "reviewed.*hash differs"):
            _validate_asset_ownership(
                OwnershipManifest(
                    "test",
                    (
                        unit,
                        OwnershipUnit(
                            "file", reviewed_path, content_sha256(b"tampered")
                        ),
                    ),
                ),
                policy,
                evidence_root=evidence_root,
                reviewed_targets={reviewed_path: reviewed_digest},
            )
        reviewed_extra = OwnershipUnit(
            "file",
            "data/tilesets/test/animation/unreviewed.png",
            content_sha256(b"extra"),
        )
        with self.assertRaisesRegex(ContentPortError, "unledgered"):
            _validate_asset_ownership(
                OwnershipManifest("test", (unit, reviewed_unit, reviewed_extra)),
                policy,
                evidence_root=evidence_root,
                reviewed_targets={reviewed_path: reviewed_digest},
            )
        with self.assertRaisesRegex(ContentPortError, "hash differs"):
            validate_asset_ownership(
                OwnershipManifest(
                    "test",
                    (OwnershipUnit("file", unit.path, content_sha256(b"different")),),
                ),
                policy,
                evidence_root=evidence_root,
            )
        extra = OwnershipUnit(
            "file", "data/tilesets/test/unledgered.bin", content_sha256(b"extra")
        )
        with self.assertRaisesRegex(ContentPortError, "unledgered"):
            validate_asset_ownership(
                OwnershipManifest("test", (unit, extra)),
                policy,
                evidence_root=evidence_root,
            )

    def test_animation_targets_come_from_fixed_staging_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            self.make_repo(repo)
            port = repo / "tools/content_port/ports/test"
            port.mkdir(parents=True)
            permission_path = repo / "PERMISSION.txt"
            permission_path.write_text("reviewed fixture permission\n")
            permission_record = {
                "decision": "reviewed",
                "path": "PERMISSION.txt",
                "permission": "redistributable",
                "sha256": content_sha256(permission_path.read_bytes()),
            }
            permission_digest = content_sha256(canonical_bytes(permission_record))
            asset_path = "data/tilesets/test/asset.bin"
            asset_payload = b"asset\n"
            asset_unit = OwnershipUnit(
                "file", asset_path, content_sha256(asset_payload)
            )
            (port / "assets.json").write_bytes(
                canonical_json(
                    {
                        "schemaVersion": 1,
                        "permissionRecords": {
                            permission_digest: permission_record,
                        },
                        "assets": [
                            {
                                "key": asset_path,
                                "source": "donor",
                                "donor": "fixture",
                                "sourcePath": "asset.bin",
                                "semanticTarget": asset_path,
                                "sourceSha256": asset_unit.sha256,
                                "targetSha256": asset_unit.sha256,
                                "conversionCommand": ["copy-bytes"],
                                "permission": "redistributable",
                                "license": "fixture permission",
                                "permissionEvidence": permission_digest,
                                "capability": "environment-assets",
                                "supportState": "enabled",
                            }
                        ],
                    }
                )
            )
            (port / "port.json").write_bytes(
                canonical_json({"animationPolicy": "animation_policy.json"})
            )
            animation_policy = port / "animation_policy.json"
            old_target = "data/tilesets/test/animation/old.png"
            animation_policy.write_bytes(
                canonical_json({"source": "frames/old.png", "target": old_target})
            )
            donor_root = base / "donors"
            content_root = donor_root / "content"
            (content_root / "frames").mkdir(parents=True)
            animation_payload = b"old animation\n"
            (content_root / "frames/old.png").write_bytes(animation_payload)
            animation_unit = OwnershipUnit(
                "file", old_target, content_sha256(animation_payload)
            )
            self.install_manifest(repo, OwnershipManifest("test", ()))
            revision = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            animation_policy.write_bytes(
                canonical_json(
                    {
                        "source": "frames/new.png",
                        "target": "data/tilesets/test/animation/new.png",
                    }
                )
            )
            run(repo, "git", "add", animation_policy.relative_to(repo).as_posix())
            run(repo, "git", "commit", "-q", "-m", "advance animation policy")

            def load_staged_descriptor(port_dir: Path, _donors: Path):
                document = json.loads((port_dir / "animation_policy.json").read_text())
                return SimpleNamespace(
                    animations=((document["source"], document["target"]),),
                    donor=lambda role: SimpleNamespace(root=content_root),
                )

            desired = OwnershipManifest("test", (asset_unit, animation_unit))
            with self.assertRaisesRegex(
                ContentPortError, "requires an authenticated donor root"
            ):
                build_bundle(
                    repo,
                    base / "missing-donor-bundle",
                    desired,
                    {
                        asset_unit.identity: asset_payload,
                        animation_unit.identity: animation_payload,
                    },
                    validation_commands=[],
                    revision=revision,
                )
            with (
                patch(
                    "tools.content_port.descriptor.load_port",
                    side_effect=load_staged_descriptor,
                ),
                patch(
                    "tools.content_port.animations.required_frame_payloads",
                    side_effect=lambda animations: animations,
                ),
            ):
                artifacts = build_bundle(
                    repo,
                    base / "bundle",
                    desired,
                    {
                        asset_unit.identity: asset_payload,
                        animation_unit.identity: animation_payload,
                    },
                    validation_commands=[],
                    revision=revision,
                    donor_root=donor_root,
                )

            self.assertEqual(
                json.loads(artifacts.report.read_text())["baseCommit"], revision
            )

    def make_repo(self, root: Path) -> None:
        run(root, "git", "init", "-q")
        run(root, "git", "config", "user.name", "Content Port Test")
        run(root, "git", "config", "user.email", "content-port@example.invalid")
        (root / "base.txt").write_text("base\n")
        run(root, "git", "add", "base.txt")
        run(root, "git", "commit", "-q", "-m", "base")

    def install_manifest(self, root: Path, manifest: OwnershipManifest) -> None:
        path = root / f"tools/content_port/ports/{manifest.port}/ownership.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json(manifest.to_json()))
        run(root, "git", "add", "--all", ".")
        run(root, "git", "commit", "-q", "-m", "installed ownership")

    def apply_bundle_patch(self, root: Path, patch: Path, destination: Path) -> Path:
        run(root.parent, "git", "clone", "-q", str(root), str(destination))
        run(destination, "git", "apply", "--binary", str(patch))
        return destination

    def test_bundle_removes_stale_installed_units_of_every_kind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            self.make_repo(repo)
            stale_section = (
                b"// CONTENT PORT BEGIN test:stale\n"
                b"generated\n"
                b"// CONTENT PORT END test:stale\n"
            )
            stale_record = {"id": "stale", "value": 1}
            (repo / "stale.bin").write_bytes(b"stale\n")
            (repo / "shared.h").write_bytes(stale_section + b"hand\n")
            (repo / "registry.json").write_bytes(
                canonical_json(
                    {"records": {"hand": {"value": 2}, "stale": stale_record}}
                )
            )
            installed = OwnershipManifest(
                "test",
                (
                    OwnershipUnit("file", "stale.bin", content_sha256(b"stale\n")),
                    OwnershipUnit(
                        "section",
                        "shared.h",
                        content_sha256(stale_section),
                        name="stale",
                    ),
                    OwnershipUnit(
                        "registry-record",
                        "registry.json",
                        content_sha256(canonical_json(stale_record)),
                        registry="records",
                        key="stale",
                    ),
                ),
            )
            self.install_manifest(repo, installed)

            artifacts = build_bundle(
                repo,
                base / "bundle",
                OwnershipManifest("test", ()),
                {},
                validation_commands=[],
            )
            applied = self.apply_bundle_patch(repo, artifacts.patch, base / "applied")

            self.assertFalse((applied / "stale.bin").exists())
            self.assertEqual((applied / "shared.h").read_bytes(), b"hand\n")
            self.assertEqual(
                json.loads((applied / "registry.json").read_text()),
                {"records": {"hand": {"value": 2}}},
            )
            self.assertEqual(
                OwnershipManifest.load(
                    applied / "tools/content_port/ports/test/ownership.json"
                ),
                OwnershipManifest("test", ()),
            )

    def test_bundle_releases_verified_file_without_deleting_its_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            self.make_repo(repo)
            original = b"target-owned after release\x00\xff"
            (repo / "released.bin").write_bytes(original)
            installed = OwnershipManifest(
                "test",
                (OwnershipUnit("file", "released.bin", content_sha256(original)),),
            )
            self.install_manifest(repo, installed)

            artifacts = build_bundle(
                repo,
                base / "bundle",
                OwnershipManifest("test", ()),
                {},
                validation_commands=[],
                released_files=("released.bin",),
            )
            applied = self.apply_bundle_patch(repo, artifacts.patch, base / "applied")

            self.assertEqual((applied / "released.bin").read_bytes(), original)
            self.assertEqual(
                OwnershipManifest.load(
                    applied / "tools/content_port/ports/test/ownership.json"
                ),
                OwnershipManifest("test", ()),
            )

    def test_bundle_adds_desired_units_absent_from_installed_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            self.make_repo(repo)
            self.install_manifest(repo, OwnershipManifest("test", ()))
            section = (
                b"// CONTENT PORT BEGIN test:new\n"
                b"generated\n"
                b"// CONTENT PORT END test:new\n"
            )
            record = {"id": "new", "value": 3}
            desired = OwnershipManifest(
                "test",
                (
                    OwnershipUnit("file", "new.bin", content_sha256(b"new\n")),
                    OwnershipUnit(
                        "section",
                        "new.h",
                        content_sha256(section),
                        name="new",
                    ),
                    OwnershipUnit(
                        "registry-record",
                        "new.json",
                        content_sha256(canonical_json(record)),
                        registry="records",
                        key="new",
                    ),
                ),
            )
            payloads = {
                ("file", "new.bin"): b"new\n",
                ("section", "new.h", "new"): section,
                ("registry-record", "new.json", "records", "new"): record,
            }

            artifacts = build_bundle(
                repo,
                base / "bundle",
                desired,
                payloads,
                validation_commands=[],
            )
            applied = self.apply_bundle_patch(repo, artifacts.patch, base / "applied")

            self.assertEqual((applied / "new.bin").read_bytes(), b"new\n")
            self.assertEqual((applied / "new.h").read_bytes(), section)
            self.assertEqual(
                json.loads((applied / "new.json").read_text()),
                {"records": {"new": record}},
            )
            self.assertEqual(
                OwnershipManifest.load(
                    applied / "tools/content_port/ports/test/ownership.json"
                ),
                desired,
            )

    def test_bundle_refuses_to_claim_existing_unowned_units(self) -> None:
        section = (
            b"// CONTENT PORT BEGIN test:new\nhand\n// CONTENT PORT END test:new\n"
        )
        replacement_section = section.replace(b"hand", b"generated")
        cases = (
            (
                "file",
                "hand.txt",
                b"hand\n",
                OwnershipUnit("file", "hand.txt", content_sha256(b"generated\n")),
                b"generated\n",
            ),
            (
                "section",
                "hand.h",
                section,
                OwnershipUnit(
                    "section",
                    "hand.h",
                    content_sha256(replacement_section),
                    name="new",
                ),
                replacement_section,
            ),
            (
                "registry-record",
                "hand.json",
                canonical_json({"records": {"new": {"id": "new", "value": "hand"}}}),
                OwnershipUnit(
                    "registry-record",
                    "hand.json",
                    content_sha256(canonical_json({"id": "new", "value": "generated"})),
                    registry="records",
                    key="new",
                ),
                {"id": "new", "value": "generated"},
            ),
        )
        for kind, relative, preimage, unit, payload in cases:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                repo = base / "repo"
                repo.mkdir()
                self.make_repo(repo)
                (repo / relative).write_bytes(preimage)
                self.install_manifest(repo, OwnershipManifest("test", ()))

                with self.assertRaisesRegex(
                    ContentPortError, "refuses to claim unowned existing"
                ):
                    build_bundle(
                        repo,
                        base / "bundle",
                        OwnershipManifest("test", (unit,)),
                        {unit.identity: payload},
                        validation_commands=[],
                    )

                self.assertEqual((repo / relative).read_bytes(), preimage)
                self.assertFalse((base / "bundle").exists())
                self.assertEqual(
                    subprocess.check_output(["git", "status", "--porcelain"], cwd=repo),
                    b"",
                )

    def test_bundle_reads_validation_policy_from_its_fixed_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            self.make_repo(repo)
            payload = b"asset\n"
            permission_path = repo / "PERMISSION.txt"
            permission_path.write_text("reviewed fixture permission\n")
            permission_record = {
                "decision": "reviewed",
                "path": "PERMISSION.txt",
                "permission": "redistributable",
                "sha256": content_sha256(permission_path.read_bytes()),
            }
            permission_digest = content_sha256(canonical_bytes(permission_record))
            target = "data/tilesets/test/asset.bin"
            unit = OwnershipUnit("file", target, content_sha256(payload))
            policy = {
                "schemaVersion": 1,
                "permissionRecords": {permission_digest: permission_record},
                "assets": [
                    {
                        "key": target,
                        "source": "donor",
                        "donor": "fixture",
                        "sourcePath": "asset.bin",
                        "semanticTarget": target,
                        "sourceSha256": unit.sha256,
                        "targetSha256": unit.sha256,
                        "conversionCommand": ["copy-bytes"],
                        "permission": "redistributable",
                        "license": "fixture permission",
                        "permissionEvidence": permission_digest,
                        "capability": "environment-assets",
                        "supportState": "enabled",
                    }
                ],
            }
            asset_path = repo / "tools/content_port/ports/test/assets.json"
            asset_path.parent.mkdir(parents=True)
            asset_path.write_bytes(canonical_json(policy))
            self.install_manifest(repo, OwnershipManifest("test", ()))
            revision = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            policy["assets"][0]["targetSha256"] = content_sha256(b"other\n")
            asset_path.write_bytes(canonical_json(policy))
            run(repo, "git", "add", asset_path.relative_to(repo).as_posix())
            run(repo, "git", "commit", "-q", "-m", "advance policy")

            artifacts = build_bundle(
                repo,
                base / "bundle",
                OwnershipManifest("test", (unit,)),
                {unit.identity: payload},
                validation_commands=[],
                revision=revision,
            )

            report = json.loads(artifacts.report.read_text())
            self.assertEqual(report["baseCommit"], revision)

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
