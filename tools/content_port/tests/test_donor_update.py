from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools.content_port.update import (
    DonorUpdateError,
    REQUIRED_REVIEW_COMMANDS,
    build_migration,
    canonical_bytes,
    finalize_migration,
    load_reviewed_migration,
    migration_digest,
    migration_filename,
    run_donor_update,
    validate_assets,
    validate_reviewed_migration,
    verify_migration_evidence,
    _policy_references,
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repo), *args),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def make_commit(repo: Path, message: str) -> str:
    git(repo, "add", ".")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def passed_evidence() -> list[dict[str, object]]:
    return [
        {"command": list(command), "result": "passed"}
        for command in REQUIRED_REVIEW_COMMANDS
    ]


class DonorUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "donor"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.name", "Contract Test")
        git(self.repo, "config", "user.email", "contract@example.invalid")
        (self.repo / "data.json").write_text(
            json.dumps({"maps": {"Route": {"section": "OLD"}}})
        )
        (self.repo / "asset.bin").write_bytes(b"old asset")
        self.old_commit = make_commit(self.repo, "old")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def worktree(self, name: str, revision: str) -> Path:
        path = self.root / name
        git(self.repo, "worktree", "add", "--detach", str(path), revision)
        return path

    def asset_policy(self, permission: str = "redistributable") -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "assets": [
                {
                    "key": "route-art",
                    "source": "content",
                    "donor": "fixture",
                    "sourcePath": "asset.bin",
                    "semanticTarget": "graphics/route/tiles.4bpp",
                    "sourceSha256": hashlib.sha256(b"old asset").hexdigest(),
                    "targetSha256": hashlib.sha256(b"old asset").hexdigest(),
                    "conversionCommand": ["python3", "convert.py", "asset.bin"],
                    "permission": permission,
                    "license": "author permission",
                    "permissionEvidence": "CREDITS.md#johto-import",
                    "capability": "environment-assets",
                    "supportState": "enabled",
                }
            ],
        }

    def test_noop_update_is_byte_identical(self) -> None:
        old = self.worktree("old", self.old_commit)
        new = self.worktree("new", self.old_commit)
        first = build_migration(
            donor="fixture",
            repository="owner/repo",
            old_tree=old,
            new_tree=new,
        )
        second = build_migration(
            donor="fixture",
            repository="owner/repo",
            old_tree=old,
            new_tree=new,
        )
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        self.assertEqual(first["addedPaths"], [])
        self.assertEqual(first["removedPaths"], [])
        self.assertEqual(first["changedPaths"], [])

    def test_reports_added_removed_changed_and_field_level_conflict(self) -> None:
        (self.repo / "data.json").write_text(
            json.dumps({"maps": {"Route": {"section": "NEW"}}})
        )
        (self.repo / "asset.bin").unlink()
        (self.repo / "added.txt").write_text("new")
        new_commit = make_commit(self.repo, "new")
        old = self.worktree("old", self.old_commit)
        new = self.worktree("new", new_commit)
        report = build_migration(
            donor="fixture",
            repository="owner/repo",
            old_tree=old,
            new_tree=new,
            references=(
                {
                    "sourcePath": "data.json",
                    "jsonPointer": "/maps/Route/section",
                    "semanticIdentity": "map:Route.section",
                    "authority": "content",
                },
            ),
            assets=self.asset_policy(),
        )
        self.assertEqual(report["addedPaths"][0]["path"], "added.txt")
        self.assertEqual(report["removedPaths"][0]["path"], "asset.bin")
        self.assertEqual(report["changedPaths"][0]["path"], "data.json")
        self.assertEqual(len(report["changedPaths"][0]["oldSha256"]), 64)
        self.assertEqual(len(report["changedPaths"][0]["newSha256"]), 64)
        self.assertEqual(
            report["authorityChanges"][0]["semanticIdentity"],
            "map:Route.section",
        )
        self.assertIsNone(report["assets"][0]["newHash"])

    def test_layout_field_authority_is_included_for_supplier_and_base(self) -> None:
        registry = self.repo / "data/layouts/layouts.json"
        registry.parent.mkdir(parents=True)
        registry.write_text(
            json.dumps(
                {
                    "layouts": [
                        {"id": "LAYOUT_TEST"},
                        {"id": "LAYOUT_MECHANICAL", "border_width": 3},
                    ]
                }
            )
        )
        old_commit = make_commit(self.repo, "layout old")
        registry.write_text(
            json.dumps(
                {
                    "layouts": [
                        {"id": "LAYOUT_TEST", "border_width": 2},
                        {"id": "LAYOUT_MECHANICAL", "border_width": 4},
                    ]
                }
            )
        )
        new_commit = make_commit(self.repo, "layout new")
        policy = {
            "layoutFieldAuthorities": [
                {
                    "field": "border_width",
                    "layoutRole": "content",
                    "sourceRole": "mechanical",
                }
            ],
            "layoutBinaryAuthorities": [
                {
                    "layout": "LAYOUT_TEST",
                    "source": "Test",
                    "sourceRole": "content",
                },
                {
                    "layout": "LAYOUT_MECHANICAL",
                    "source": "Mechanical",
                    "sourceRole": "mechanical",
                },
            ],
        }
        references = _policy_references(policy, "mechanical")
        self.assertEqual(
            [reference["semanticIdentity"] for reference in references],
            ["layout:LAYOUT_TEST.border_width"],
        )
        base_references = _policy_references(policy, "content")
        self.assertEqual(
            [reference["semanticIdentity"] for reference in base_references],
            ["layout:LAYOUT_TEST.border_width"],
        )
        self.assertEqual(base_references[0]["authority"], "content")
        report = build_migration(
            donor="mechanical",
            repository="owner/repo",
            old_tree=self.worktree("layout-old", old_commit),
            new_tree=self.worktree("layout-new", new_commit),
            references=references,
        )
        self.assertEqual(
            [change["semanticIdentity"] for change in report["authorityChanges"]],
            ["layout:LAYOUT_TEST.border_width"],
        )
        self.assertNotEqual(
            report["authorityChanges"][0]["oldHash"],
            report["authorityChanges"][0]["newHash"],
        )
        self.assertIsNone(report["authorityChanges"][0]["oldHash"])

    def test_explicit_map_adaptations_report_nested_removal_and_null_drift(
        self,
    ) -> None:
        source = self.repo / "data/maps/NewBarkTown/map.json"
        source.parent.mkdir(parents=True)
        source.write_text(
            json.dumps(
                {
                    "warp_events": [
                        {},
                        {},
                        {},
                        {},
                        {"dest_map": "MAP_OLD"},
                    ],
                    "metadata": {"removed": "present"},
                }
            )
        )
        old_commit = make_commit(self.repo, "adaptation old")
        source.write_text(
            json.dumps(
                {
                    "warp_events": [
                        {},
                        {},
                        {},
                        {},
                        {"dest_map": "MAP_NEW"},
                    ],
                    "metadata": {"nullable": None},
                }
            )
        )
        new_commit = make_commit(self.repo, "adaptation new")
        policy = {
            "donorFieldRoles": {"content": "hns", "mechanical": "mechanical"},
            "adaptations": [
                {
                    "source": "NewBarkTown",
                    "path": "warp_events/4/dest_map",
                },
                {"source": "NewBarkTown", "path": "metadata/removed"},
                {"source": "NewBarkTown", "path": "metadata/nullable"},
            ],
        }
        references = _policy_references(policy, "content")
        report = build_migration(
            donor="content",
            repository="owner/repo",
            old_tree=self.worktree("adaptation-old", old_commit),
            new_tree=self.worktree("adaptation-new", new_commit),
            references=references,
        )
        changes = {
            change["semanticIdentity"]: change for change in report["authorityChanges"]
        }
        nested = changes["map:NewBarkTown.warp_events/4/dest_map"]
        self.assertIsNotNone(nested["oldHash"])
        self.assertIsNotNone(nested["newHash"])
        removed = changes["map:NewBarkTown.metadata/removed"]
        self.assertIsNotNone(removed["oldHash"])
        self.assertIsNone(removed["newHash"])
        nullable = changes["map:NewBarkTown.metadata/nullable"]
        self.assertIsNone(nullable["oldHash"])
        self.assertEqual(
            nullable["newHash"], hashlib.sha256(canonical_bytes(None)).hexdigest()
        )
        self.assertTrue(
            all(
                change["reviewerDisposition"] == "pending"
                for change in changes.values()
            )
        )

    def test_real_policy_inventories_every_explicit_map_transform(self) -> None:
        policy = json.loads(
            Path("tools/content_port/ports/johto/adaptations.json").read_text()
        )
        expected_adaptations = {
            f"map:{item['source']}.{item['path']}" for item in policy["adaptations"]
        }
        self.assertEqual(len(expected_adaptations), 10)
        for donor in ("content", "mechanical"):
            identities = {
                reference["semanticIdentity"]
                for reference in _policy_references(policy, donor)
            }
            self.assertTrue(expected_adaptations.issubset(identities))

        transformed_content_paths = {
            f"map:{item['source']}.{item['path']}"
            for key in (
                "warpReindexes",
                "warpRemovals",
                "berryTreeAllocations",
                "deferredEdges",
            )
            for item in policy[key]
            if item["source"] not in set(policy["contentFallback"]["maps"])
        }
        content_identities = {
            reference["semanticIdentity"]
            for reference in _policy_references(policy, "content")
        }
        self.assertTrue(transformed_content_paths.issubset(content_identities))

    def test_asset_policy_fails_closed_on_permission_and_metadata(self) -> None:
        for permission in ("blocked", "unknown"):
            with self.subTest(permission=permission):
                with self.assertRaisesRegex(
                    DonorUpdateError, f"asset route-art: permission is {permission}"
                ):
                    validate_assets(self.asset_policy(permission))
        malformed = self.asset_policy()
        del malformed["assets"][0]["conversionCommand"]
        with self.assertRaisesRegex(DonorUpdateError, "missing fields"):
            validate_assets(malformed)

    def test_reviewed_record_rejects_stale_pin_and_conversion_drift(self) -> None:
        old = self.worktree("old", self.old_commit)
        report = build_migration(
            donor="fixture",
            repository="owner/repo",
            old_tree=old,
            new_tree=old,
        )
        report["decision"] = "reviewed"
        with self.assertRaisesRegex(DonorUpdateError, "target pin is stale"):
            validate_reviewed_migration(
                report,
                donor="fixture",
                from_commit=self.old_commit,
                to_commit="f" * 40,
            )

        changed = copy.deepcopy(report)
        changed["from"]["commit"] = "e" * 40
        changed["tests"] = passed_evidence()
        changed["assets"] = [
            {
                "key": "route-art",
                "conversionCommand": ["wrong"],
                "permission": "redistributable",
                "reviewerDisposition": "accepted",
            }
        ]
        with self.assertRaisesRegex(DonorUpdateError, "conversion command drift"):
            validate_reviewed_migration(
                changed,
                donor="fixture",
                from_commit="e" * 40,
                to_commit=self.old_commit,
                expected_assets={"route-art": self.asset_policy()["assets"][0]},
            )

    def test_missing_and_misnamed_reviewed_record_fail(self) -> None:
        migrations = self.root / "migrations"
        migrations.mkdir()
        with self.assertRaisesRegex(DonorUpdateError, "missing reviewed"):
            load_reviewed_migration(migrations, "0" * 64)
        report = {"schemaVersion": 1, "decision": "reviewed"}
        stale_digest = "1" * 64
        (migrations / f"{stale_digest}.json").write_bytes(canonical_bytes(report))
        self.assertNotEqual(migration_digest(report), stale_digest)
        with self.assertRaisesRegex(DonorUpdateError, "filename is stale"):
            load_reviewed_migration(migrations, stale_digest)

    def test_cli_wrapper_writes_candidate_without_editing_port_policy(self) -> None:
        host = self.root / "host"
        port = host / "tools/content_port/ports/fixture"
        port.mkdir(parents=True)
        assets = {"schemaVersion": 1, "assets": []}
        (port / "assets.json").write_bytes(canonical_bytes(assets))
        (port / "adaptations.json").write_bytes(
            canonical_bytes(
                {
                    "schemaVersion": 1,
                    "mapFieldDecisions": [],
                    "layoutHeaderDecisions": [],
                    "layoutTilesetRemaps": [],
                }
            )
        )
        port_document = {
            "schemaVersion": 1,
            "assetPolicy": "assets.json",
            "authority": {},
            "donors": {
                "content": {
                    "name": "fixture",
                    "repository": "owner/repo",
                    "commit": self.old_commit,
                    "treeDigest": "0" * 64,
                    "fileCount": 2,
                    "excludePaths": [],
                    "genesis": {
                        "commit": self.old_commit,
                        "treeDigest": "0" * 64,
                        "fileCount": 2,
                    },
                    "root": "donor",
                }
            },
        }
        policy_path = port / "port.json"
        policy_path.write_bytes(canonical_bytes(port_document))
        before = policy_path.read_bytes()
        donor_root = self.root / "donors"
        donor_root.mkdir()
        git(self.repo, "worktree", "add", str(donor_root / "donor"), self.old_commit)
        output = host / "build/content-port/fixture/donor-migration.json"
        with mock.patch(
            "tools.content_port.update.run_review_commands",
            return_value=tuple(passed_evidence()),
        ):
            result = run_donor_update(
                host,
                "fixture",
                donor_root,
                "content",
                self.old_commit,
                output,
            )
        self.assertEqual(result, output)
        self.assertEqual(policy_path.read_bytes(), before)
        candidate = json.loads(output.read_text())
        self.assertEqual(candidate["decision"], "candidate")
        self.assertEqual(candidate["donor"], "content")

    def test_finalize_links_reviewed_content_address_without_editing_port(self) -> None:
        (self.repo / "data.json").write_text(
            json.dumps({"maps": {"Route": {"section": "NEW"}}})
        )
        (self.repo / "asset.bin").write_bytes(b"new asset")
        new_commit = make_commit(self.repo, "new")
        old = self.worktree("old", self.old_commit)
        new = self.worktree("new", new_commit)
        asset_policy = self.asset_policy()
        asset_policy["assets"][0]["donor"] = "content"
        report = build_migration(
            donor="content",
            repository="owner/repo",
            old_tree=old,
            new_tree=new,
            assets=asset_policy,
            tests=passed_evidence(),
        )
        candidate_digest = migration_digest(report)
        report["decision"] = "reviewed"
        report["assets"][0]["reviewerDisposition"] = "accepted"
        self.assertNotEqual(candidate_digest, migration_digest(report))
        fabricated_tests = copy.deepcopy(report)
        fabricated_tests["tests"] = [{"command": ["true"], "result": "passed"}]
        with self.assertRaisesRegex(DonorUpdateError, "required.*commands"):
            validate_reviewed_migration(
                fabricated_tests,
                donor="content",
                from_commit=self.old_commit,
                to_commit=new_commit,
            )

        port_dir = self.root / "port"
        port_dir.mkdir()
        port = {
            "donors": {
                "content": {
                    "name": "fixture",
                    "repository": "owner/repo",
                    **report["from"],
                    "excludePaths": [],
                    "genesis": dict(report["from"]),
                    "root": "donor",
                    "migration": None,
                }
            }
        }
        port_path = port_dir / "port.json"
        port_path.write_bytes(canonical_bytes(port))
        (port_dir / "assets.json").write_bytes(canonical_bytes(asset_policy))
        (port_dir / "adaptations.json").write_bytes(
            canonical_bytes(
                {
                    "schemaVersion": 1,
                    "mapFieldDecisions": [],
                    "layoutHeaderDecisions": [],
                    "layoutTilesetRemaps": [],
                }
            )
        )
        validate_reviewed_migration(
            report,
            donor="content",
            repository="owner/repo",
            from_commit=str(report["from"]["commit"]),
            from_tree_digest=str(report["from"]["treeDigest"]),
            from_file_count=int(report["from"]["fileCount"]),
            to_commit=str(report["to"]["commit"]),
            to_tree_digest=str(report["to"]["treeDigest"]),
            to_file_count=int(report["to"]["fileCount"]),
            port_dir=port_dir,
            donor_checkout=self.repo,
        )
        before = port_path.read_bytes()
        candidate = self.root / "donor-migration.json"
        candidate.write_bytes(canonical_bytes(report))
        record, proposal = finalize_migration(
            candidate, port_dir, donor_root=self.root, repo=Path.cwd()
        )
        self.assertEqual(record.name, migration_filename(report))
        self.assertEqual(record.read_bytes(), canonical_bytes(report))
        self.assertEqual(port_path.read_bytes(), before)
        update = json.loads(proposal.read_text())
        self.assertEqual(update["migration"], migration_digest(report))
        self.assertEqual(
            update["proposedDonorRecord"]["commit"], report["to"]["commit"]
        )
        self.assertEqual(update["proposedDonorRecord"]["genesis"], report["from"])

        stale_predecessor = copy.deepcopy(report)
        stale_predecessor["predecessor"] = "f" * 64
        candidate.write_bytes(canonical_bytes(stale_predecessor))
        with self.assertRaisesRegex(
            DonorUpdateError, "predecessor is not the published pin"
        ):
            finalize_migration(
                candidate, port_dir, donor_root=self.root, repo=Path.cwd()
            )

        for field in ("changedPaths", "assets"):
            fabricated = copy.deepcopy(report)
            fabricated[field] = []
            with (
                self.subTest(fabricated=field),
                self.assertRaisesRegex(DonorUpdateError, "fabricated or stale"),
            ):
                verify_migration_evidence(fabricated, port_dir, self.repo)

        shallow = self.root / "target-only"
        subprocess.run(
            (
                "git",
                "clone",
                "-q",
                "--depth=1",
                f"file://{self.repo}",
                str(shallow),
            ),
            check=True,
        )
        with self.assertRaisesRegex(DonorUpdateError, "cannot inspect donor checkout"):
            verify_migration_evidence(report, port_dir, shallow)

    def test_finalize_rejects_pending_disposition(self) -> None:
        report = {
            "addedPaths": [],
            "assets": [],
            "authorityChanges": [{"reviewerDisposition": "pending"}],
            "changedPaths": ["data.json"],
            "decision": "reviewed",
            "donor": "content",
            "from": {
                "commit": "a" * 40,
                "fileCount": 1,
                "treeDigest": "b" * 64,
            },
            "predecessor": None,
            "removedPaths": [],
            "repository": "owner/repo",
            "schemaVersion": 1,
            "tests": passed_evidence(),
            "to": {
                "commit": "c" * 40,
                "fileCount": 1,
                "treeDigest": "d" * 64,
            },
        }
        candidate = self.root / "candidate.json"
        candidate.write_bytes(canonical_bytes(report))
        port_dir = self.root / "port"
        port_dir.mkdir()
        (port_dir / "port.json").write_text('{"donors":{}}')
        with self.assertRaisesRegex(DonorUpdateError, "review is incomplete"):
            finalize_migration(candidate, port_dir)

    def test_fabricated_empty_review_requires_authenticated_trees(self) -> None:
        report = {
            "addedPaths": [],
            "assets": [],
            "authorityChanges": [],
            "changedPaths": [],
            "decision": "reviewed",
            "donor": "content",
            "from": {
                "commit": "a" * 40,
                "fileCount": 1,
                "treeDigest": "b" * 64,
            },
            "predecessor": None,
            "removedPaths": [],
            "repository": "owner/repo",
            "schemaVersion": 1,
            "tests": passed_evidence(),
            "to": {
                "commit": "c" * 40,
                "fileCount": 1,
                "treeDigest": "d" * 64,
            },
        }
        with self.assertRaisesRegex(DonorUpdateError, "authenticated from/to trees"):
            validate_reviewed_migration(
                report,
                donor="content",
                from_commit="a" * 40,
                to_commit="c" * 40,
            )


class CheckedAssetLedgerTests(unittest.TestCase):
    def test_ledger_is_exact_for_every_owned_asset_tree(self) -> None:
        policy = json.loads(
            Path("tools/content_port/ports/johto/assets.json").read_text()
        )
        assets = validate_assets(policy)
        declared = {str(asset["semanticTarget"]) for asset in assets}
        roots = {
            Path(target).parent.parent
            if Path(target).parent.name == "palettes"
            else Path(target).parent
            for target in declared
        }
        actual = {
            path.as_posix()
            for root in roots
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix != ".inc"
            and "anim" not in path.relative_to(root).parts
        }
        self.assertEqual(declared, actual)
        for asset in assets:
            with self.subTest(asset=asset["key"]):
                target = Path(str(asset["semanticTarget"]))
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                self.assertEqual(asset["targetSha256"], digest)
                self.assertEqual(asset["sourceSha256"], digest)
                self.assertEqual(asset["conversionCommand"], ["copy-bytes"])
                self.assertEqual(asset["permissionEvidence"], "CREDITS.md#johto-import")


if __name__ == "__main__":
    unittest.main()
