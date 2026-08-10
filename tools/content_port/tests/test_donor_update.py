from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import MappingProxyType
import unittest
from unittest import mock

from tools.content_port import update as donor_update_module
from tools.content_port.descriptor import load_port
from tools.content_port.model import CapabilityState, ResourceKey
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
    _derive_authored_policy_snapshot,
    _remove_worktrees,
    _policy_references,
    _semantic_policy_references,
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


def empty_policy() -> dict[str, object]:
    return {
        "assets": {"schemaVersion": 1, "permissionRecords": {}, "assets": []},
        "excludedPaths": [],
        "references": [],
        "schemaVersion": 1,
    }


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

    def test_semantic_reconstruction_rejects_every_unsafe_donor_root_before_mutation(
        self,
    ) -> None:
        pin = {
            "commit": self.old_commit,
            "fileCount": 1,
            "treeDigest": "a" * 64,
        }
        for unsafe_kind in ("traversal", "absolute", "symlink"):
            with self.subTest(unsafe_kind=unsafe_kind):
                outside = self.root / f"semantic-outside-{unsafe_kind}"
                outside.mkdir()
                if unsafe_kind == "traversal":
                    unsafe_root = "../escape"
                elif unsafe_kind == "absolute":
                    unsafe_root = str(outside)
                else:
                    link = self.root / "semantic-linked-donor"
                    link.symlink_to(outside, target_is_directory=True)
                    unsafe_root = link.name
                port = {
                    "donors": {
                        "content": {"commit": self.old_commit, "root": "donor"},
                        # Keep the unsafe entry second: preflight must reject all
                        # roots before starting work for the first valid donor.
                        "mechanical": {
                            "commit": self.old_commit,
                            "root": unsafe_root,
                        },
                    }
                }
                with (
                    mock.patch(
                        "tools.content_port.update.tempfile.TemporaryDirectory"
                    ) as temporary_directory,
                    mock.patch("tools.content_port.update.shutil.copytree") as copytree,
                    mock.patch("tools.content_port.update._run_git") as run_git,
                    self.assertRaisesRegex(
                        DonorUpdateError,
                        "unsafe donor checkout path|symbolic link",
                    ),
                ):
                    donor_update_module._semantic_evidence_at_pin(
                        self.root,
                        self.root / "port",
                        self.root,
                        "content",
                        pin,
                        port_document=port,
                    )
                temporary_directory.assert_not_called()
                copytree.assert_not_called()
                run_git.assert_not_called()

    def test_update_rejects_every_unsafe_donor_root_before_mutation(self) -> None:
        for unsafe_kind in ("traversal", "absolute", "symlink"):
            with self.subTest(unsafe_kind=unsafe_kind):
                host = self.root / f"update-host-{unsafe_kind}"
                port_dir = host / "tools/content_port/ports/fixture"
                port_dir.mkdir(parents=True)
                outside = self.root / f"update-outside-{unsafe_kind}"
                outside.mkdir()
                if unsafe_kind == "traversal":
                    unsafe_root = "../escape"
                elif unsafe_kind == "absolute":
                    unsafe_root = str(outside)
                else:
                    link = self.root / "update-linked-donor"
                    link.symlink_to(outside, target_is_directory=True)
                    unsafe_root = link.name
                port = {
                    "donors": {
                        "content": {
                            "commit": self.old_commit,
                            "excludePaths": [],
                            "name": "fixture",
                            "repository": "owner/repo",
                            "root": "donor",
                        },
                        "mechanical": {
                            "commit": self.old_commit,
                            "root": unsafe_root,
                        },
                    }
                }
                (port_dir / "port.json").write_bytes(canonical_bytes(port))
                output = host / "candidate.json"
                with (
                    mock.patch(
                        "tools.content_port.update.tempfile.TemporaryDirectory"
                    ) as temporary_directory,
                    mock.patch(
                        "tools.content_port.update._derive_authored_policy_snapshot"
                    ) as derive_policy,
                    mock.patch("tools.content_port.update._run_git") as run_git,
                    self.assertRaisesRegex(
                        DonorUpdateError,
                        "unsafe donor checkout path|symbolic link",
                    ),
                ):
                    run_donor_update(
                        host,
                        "fixture",
                        self.root,
                        "content",
                        self.old_commit,
                        output,
                    )
                temporary_directory.assert_not_called()
                derive_policy.assert_not_called()
                run_git.assert_not_called()
                self.assertFalse(output.exists())

    def test_atomic_publication_ignores_predictable_temporary_symlink(self) -> None:
        publication = self.root / "publication"
        publication.mkdir()
        output = publication / "candidate.json"
        victim = self.root / "victim"
        victim.write_bytes(b"untouched")
        predictable = publication / ".candidate.json.tmp"
        predictable.symlink_to(victim)

        donor_update_module._atomic_write(
            output, b"published", "secure-temporary-symlink-test"
        )

        self.assertEqual(output.read_bytes(), b"published")
        self.assertEqual(victim.read_bytes(), b"untouched")
        self.assertTrue(predictable.is_symlink())
        self.assertEqual(
            list(publication.glob(".candidate.json.tmp-*")),
            [],
        )

    def test_publication_rollback_stays_on_held_parent_after_swap(self) -> None:
        publication = self.root / "publication"
        publication.mkdir()
        output = publication / "record.json"
        output.write_bytes(b"previous")
        displaced = self.root / "held-publication"
        calls = 0

        def swap_parent(*args: object, **kwargs: object) -> str:
            nonlocal calls
            calls += 1
            if calls == 2:
                publication.rename(displaced)
                publication.mkdir()
                (publication / output.name).write_bytes(b"decoy")
                return "b" * 64
            return "a" * 64

        with (
            mock.patch(
                "tools.content_port.update._publication_policy_digest",
                side_effect=swap_parent,
            ),
            self.assertRaisesRegex(DonorUpdateError, "policy drifted during write"),
        ):
            donor_update_module._write_policy_bound_artifact(
                output,
                b"published",
                "parent-swap-test",
                port_dir=self.root,
                donor="content",
                evidence_root=self.root,
                policy_digest="a" * 64,
            )

        self.assertEqual((displaced / output.name).read_bytes(), b"previous")
        self.assertEqual((publication / output.name).read_bytes(), b"decoy")

    def test_publication_rejects_parent_swap_with_identical_policy(self) -> None:
        publication = self.root / "publication"
        publication.mkdir()
        output = publication / "record.json"
        output.write_bytes(b"previous")
        displaced = self.root / "held-publication"
        calls = 0

        def swap_parent(*args: object, **kwargs: object) -> str:
            nonlocal calls
            calls += 1
            if calls == 2:
                publication.rename(displaced)
                publication.mkdir()
                (publication / output.name).write_bytes(b"decoy")
            return "a" * 64

        with (
            mock.patch(
                "tools.content_port.update._publication_policy_digest",
                side_effect=swap_parent,
            ),
            self.assertRaisesRegex(DonorUpdateError, "publication parent changed"),
        ):
            donor_update_module._write_policy_bound_artifact(
                output,
                b"published",
                "identical-policy-parent-swap-test",
                port_dir=self.root,
                donor="content",
                evidence_root=self.root,
                policy_digest="a" * 64,
            )

        self.assertEqual((displaced / output.name).read_bytes(), b"previous")
        self.assertEqual((publication / output.name).read_bytes(), b"decoy")

    def test_selected_pin_reconstruction_unlinks_every_frozen_donor(self) -> None:
        port_dir = self.root / "port"
        port_dir.mkdir()
        current = {
            "commit": "1" * 40,
            "fileCount": 1,
            "treeDigest": "2" * 64,
        }
        unrelated = {
            "commit": "3" * 40,
            "fileCount": 2,
            "treeDigest": "4" * 64,
        }
        selected = {
            "commit": "5" * 40,
            "fileCount": 3,
            "treeDigest": "6" * 64,
        }
        port = {
            "donors": {
                "content": {
                    **current,
                    "genesis": dict(current),
                    "migration": "a" * 64,
                    "root": "content",
                },
                "mechanical": {
                    **unrelated,
                    "genesis": {
                        "commit": "7" * 40,
                        "fileCount": 7,
                        "treeDigest": "8" * 64,
                    },
                    "migration": "b" * 64,
                    "root": "mechanical",
                },
            }
        }
        (port_dir / "port.json").write_bytes(canonical_bytes(port))
        captured: dict[str, object] = {}

        def inspect_descriptor(snapshot_port: Path, donor_root: Path) -> None:
            del donor_root
            captured.update(json.loads((snapshot_port / "port.json").read_text()))
            raise DonorUpdateError("inspection complete")

        with (
            mock.patch("tools.content_port.update._run_git", return_value=""),
            mock.patch("tools.content_port.update._remove_worktrees"),
            mock.patch(
                "tools.content_port.descriptor.load_port",
                side_effect=inspect_descriptor,
            ),
            self.assertRaisesRegex(DonorUpdateError, "inspection complete"),
        ):
            donor_update_module._semantic_evidence_at_pin(
                self.root,
                port_dir,
                self.root,
                "content",
                selected,
                port_document=port,
            )

        donors = captured["donors"]
        self.assertEqual(donors["content"]["genesis"], selected)  # type: ignore[index]
        self.assertIsNone(donors["content"]["migration"])  # type: ignore[index]
        self.assertEqual(donors["mechanical"]["genesis"], unrelated)  # type: ignore[index]
        self.assertIsNone(donors["mechanical"]["migration"])  # type: ignore[index]

    def asset_policy(self, permission: str = "redistributable") -> dict[str, object]:
        evidence = self.root / "permission.txt"
        evidence.write_text("reviewed fixture permission\n")
        permission_record = {
            "decision": "reviewed",
            "path": "permission.txt",
            "permission": permission,
            "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        }
        permission_digest = hashlib.sha256(
            canonical_bytes(permission_record)
        ).hexdigest()
        return {
            "schemaVersion": 1,
            "permissionRecords": {permission_digest: permission_record},
            "assets": [
                {
                    "key": "route-art",
                    "donor": "fixture",
                    "sourcePath": "asset.bin",
                    "semanticTarget": "graphics/route/tiles.4bpp",
                    "sourceSha256": hashlib.sha256(b"old asset").hexdigest(),
                    "targetSha256": hashlib.sha256(b"old asset").hexdigest(),
                    "conversionCommand": ["python3", "convert.py", "asset.bin"],
                    "permission": permission,
                    "permissionEvidence": permission_digest,
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

    def test_canonical_bytes_thaws_frozen_descriptor_values(self) -> None:
        frozen = MappingProxyType(
            {"record": MappingProxyType({"argv": ("copy-bytes",)})}
        )
        self.assertEqual(
            json.loads(canonical_bytes(frozen)),
            {"record": {"argv": ["copy-bytes"]}},
        )

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
            evidence_root=self.root,
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
            [
                reference["semanticIdentity"]
                for reference in references
                if reference.get("recordType") is None
            ],
            ["layout:LAYOUT_TEST.border_width"],
        )
        base_references = _policy_references(policy, "content")
        self.assertEqual(
            [
                reference["semanticIdentity"]
                for reference in base_references
                if reference.get("recordType") is None
            ],
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
            [
                change["semanticIdentity"]
                for change in report["authorityChanges"]
                if change["semanticIdentity"] == "layout:LAYOUT_TEST.border_width"
            ],
            ["layout:LAYOUT_TEST.border_width"],
        )
        field_change = next(
            change
            for change in report["authorityChanges"]
            if change["semanticIdentity"] == "layout:LAYOUT_TEST.border_width"
        )
        self.assertNotEqual(field_change["oldHash"], field_change["newHash"])
        self.assertIsNone(field_change["oldHash"])

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

    def test_complete_selected_records_emit_field_level_migration_evidence(
        self,
    ) -> None:
        map_path = self.repo / "data/maps/TestMap/map.json"
        layout_path = self.repo / "data/layouts/layouts.json"
        section_path = self.repo / "src/data/region_map/test.json"
        for path in (map_path, layout_path, section_path):
            path.parent.mkdir(parents=True, exist_ok=True)
        map_path.write_text(
            json.dumps(
                {
                    "id": "MAP_TEST",
                    "layout": "LAYOUT_TEST",
                    "weather": "WEATHER_NONE",
                }
            )
        )
        layout_path.write_text(
            json.dumps(
                {
                    "layouts": [
                        {
                            "id": "LAYOUT_TEST",
                            "width": 10,
                            "blockdata_filepath": "data/layouts/old.bin",
                        }
                    ]
                }
            )
        )
        section_path.write_text(
            json.dumps(
                {
                    "map_sections": [
                        {
                            "id": "MAPSEC_TEST",
                            "name": "Old Name",
                            "x": 1,
                            "y": 2,
                            "width": 3,
                            "height": 4,
                        }
                    ]
                }
            )
        )
        old_commit = make_commit(self.repo, "selected records old")
        map_document = json.loads(map_path.read_text())
        map_document["weather"] = "WEATHER_RAIN"
        map_path.write_text(json.dumps(map_document))
        layout_document = json.loads(layout_path.read_text())
        layout_document["layouts"][0]["width"] = 11
        layout_document["layouts"][0]["blockdata_filepath"] = "data/layouts/new.bin"
        layout_path.write_text(json.dumps(layout_document))
        section_document = json.loads(section_path.read_text())
        section_document["map_sections"][0]["name"] = "New Name"
        section_document["map_sections"][0]["x"] = 5
        section_path.write_text(json.dumps(section_document))
        new_commit = make_commit(self.repo, "selected records new")
        policy = {
            "donorFieldRoles": {"content": "hns", "mechanical": "mechanical"},
            "contentFallback": {"maps": []},
            "layoutBinaryAuthorities": [
                {
                    "layout": "LAYOUT_TEST",
                    "source": "TestMap",
                    "sourceRole": "content",
                }
            ],
            "layoutFieldAuthorities": [],
            "sectionMetadataAuthorities": [
                {
                    "section": "MAPSEC_TEST",
                    "sourceRole": "content",
                    "sourceSymbol": "MAPSEC_TEST",
                }
            ],
        }
        allocations = {"maps": [{"name": "TestMap"}]}
        report = build_migration(
            donor="content",
            repository="owner/repo",
            old_tree=self.worktree("selected-old", old_commit),
            new_tree=self.worktree("selected-new", new_commit),
            references=_policy_references(policy, "content", allocations),
        )
        changes = {
            change["semanticIdentity"]: change for change in report["authorityChanges"]
        }
        for identity in (
            "map:TestMap.weather",
            "layout:LAYOUT_TEST.width",
            "layout:LAYOUT_TEST.blockdata_filepath",
            "section:MAPSEC_TEST.name",
            "section:MAPSEC_TEST.x",
        ):
            with self.subTest(identity=identity):
                self.assertIn(identity, changes)
                self.assertEqual(changes[identity]["authority"], "content")
                self.assertEqual(changes[identity]["reviewerDisposition"], "pending")

    def test_complete_layout_and_section_additions_and_removals_are_reported(
        self,
    ) -> None:
        layout_path = self.repo / "data/layouts/layouts.json"
        section_path = self.repo / "src/data/region_map/test.json"
        layout_path.parent.mkdir(parents=True)
        section_path.parent.mkdir(parents=True)
        layout_path.write_text(json.dumps({"layouts": []}))
        section_path.write_text(json.dumps({"map_sections": []}))
        absent_commit = make_commit(self.repo, "selected records absent")
        layout_path.write_text(
            json.dumps({"layouts": [{"id": "LAYOUT_TEST", "width": 10}]})
        )
        section_path.write_text(
            json.dumps({"map_sections": [{"id": "MAPSEC_TEST", "name": "Test"}]})
        )
        present_commit = make_commit(self.repo, "selected records present")
        references = _policy_references(
            {
                "layoutBinaryAuthorities": [
                    {
                        "layout": "LAYOUT_TEST",
                        "source": "TestMap",
                        "sourceRole": "content",
                    }
                ],
                "sectionMetadataAuthorities": [
                    {
                        "section": "MAPSEC_TEST",
                        "sourceRole": "content",
                        "sourceSymbol": "MAPSEC_TEST",
                    }
                ],
            },
            "content",
        )
        absent = self.worktree("records-absent", absent_commit)
        present = self.worktree("records-present", present_commit)
        added = build_migration(
            donor="content",
            repository="owner/repo",
            old_tree=absent,
            new_tree=present,
            references=references,
        )
        removed = build_migration(
            donor="content",
            repository="owner/repo",
            old_tree=present,
            new_tree=absent,
            references=references,
        )
        for report, missing_side in ((added, "oldHash"), (removed, "newHash")):
            changes = {
                change["semanticIdentity"]: change
                for change in report["authorityChanges"]
            }
            for identity in (
                "layout:LAYOUT_TEST.id",
                "layout:LAYOUT_TEST.width",
                "section:MAPSEC_TEST.id",
                "section:MAPSEC_TEST.name",
            ):
                with self.subTest(identity=identity, missing_side=missing_side):
                    self.assertIn(identity, changes)
                    self.assertIsNone(changes[identity][missing_side])

    def test_complete_layout_and_section_records_reject_non_mappings(self) -> None:
        layout_path = self.repo / "data/layouts/layouts.json"
        section_path = self.repo / "src/data/region_map/test.json"
        layout_path.parent.mkdir(parents=True)
        section_path.parent.mkdir(parents=True)
        layout_path.write_text(json.dumps({"layouts": ["invalid"]}))
        section_path.write_text(json.dumps({"map_sections": ["invalid"]}))
        malformed_commit = make_commit(self.repo, "malformed selected records")
        malformed = self.worktree("records-malformed", malformed_commit)
        for reference, message in (
            (
                {
                    "authority": "content",
                    "jsonPointer": "/layouts/@LAYOUT_TEST",
                    "layoutId": "LAYOUT_TEST",
                    "recordType": "layout",
                    "semanticIdentity": "layout:LAYOUT_TEST",
                    "sourcePath": "data/layouts/layouts.json",
                },
                "layout registry is malformed",
            ),
            (
                {
                    "authority": "content",
                    "jsonPointer": "",
                    "recordType": "section",
                    "sectionSymbol": "MAPSEC_TEST",
                    "semanticIdentity": "section:MAPSEC_TEST",
                    "sourcePath": "src/data/region_map",
                },
                "section metadata is malformed",
            ),
        ):
            with (
                self.subTest(record=reference["recordType"]),
                self.assertRaisesRegex(DonorUpdateError, message),
            ):
                build_migration(
                    donor="content",
                    repository="owner/repo",
                    old_tree=malformed,
                    new_tree=malformed,
                    references=(reference,),
                )

    def test_asset_policy_fails_closed_on_permission_and_metadata(self) -> None:
        for permission in ("blocked", "unknown"):
            with self.subTest(permission=permission):
                with self.assertRaisesRegex(
                    DonorUpdateError, f"asset route-art: permission is {permission}"
                ):
                    validate_assets(
                        self.asset_policy(permission), evidence_root=self.root
                    )
        malformed = self.asset_policy()
        del malformed["assets"][0]["conversionCommand"]
        with self.assertRaisesRegex(DonorUpdateError, "missing fields"):
            validate_assets(malformed, evidence_root=self.root)

        for compatibility_field in ("source", "license"):
            with self.subTest(compatibility_field=compatibility_field):
                policy = self.asset_policy()
                policy["assets"][0][compatibility_field] = "reviewed fixture metadata"
                self.assertEqual(
                    validate_assets(policy, evidence_root=self.root),
                    tuple(policy["assets"]),
                )

                policy["assets"][0][compatibility_field] = {"arbitrary": True}
                with self.assertRaisesRegex(
                    DonorUpdateError,
                    rf"\.{compatibility_field}: expected a non-empty string",
                ):
                    validate_assets(policy, evidence_root=self.root)

        for mutation, message in (
            (
                lambda policy: policy["assets"][0].__setitem__(
                    "permissionEvidence", "0" * 64
                ),
                "unknown permission record",
            ),
            (
                lambda policy: next(
                    iter(policy["permissionRecords"].values())
                ).__setitem__("sha256", "0" * 64),
                "permission record digest is stale",
            ),
            (
                lambda policy: policy["permissionRecords"].__setitem__(
                    hashlib.sha256(
                        canonical_bytes(
                            {
                                **next(iter(policy["permissionRecords"].values())),
                                "path": "missing.txt",
                            }
                        )
                    ).hexdigest(),
                    {
                        **policy["permissionRecords"].pop(
                            next(iter(policy["permissionRecords"]))
                        ),
                        "path": "missing.txt",
                    },
                ),
                "permission evidence is missing",
            ),
        ):
            policy = self.asset_policy()
            mutation(policy)
            with self.assertRaisesRegex(DonorUpdateError, message):
                validate_assets(policy, evidence_root=self.root)

    def test_historical_migration_uses_immutable_embedded_policy(self) -> None:
        map_path = self.repo / "data/maps/TestMap/map.json"
        map_path.parent.mkdir(parents=True)
        map_path.write_text(json.dumps({"weather": "SUN"}))
        old_commit = make_commit(self.repo, "weather old")
        map_path.write_text(json.dumps({"weather": "RAIN"}))
        new_commit = make_commit(self.repo, "weather new")
        report = build_migration(
            donor="content",
            repository="owner/repo",
            old_tree=self.worktree("weather-old", old_commit),
            new_tree=self.worktree("weather-new", new_commit),
            references=(
                {
                    "authority": "content",
                    "jsonPointer": "/weather",
                    "semanticIdentity": "map:TestMap.weather",
                    "sourcePath": "data/maps/TestMap/map.json",
                },
            ),
        )
        report["decision"] = "reviewed"
        report["authorityChanges"][0]["reviewerDisposition"] = "accepted"
        port_dir = self.root / "historical-port"
        port_dir.mkdir()
        # Current policy deliberately no longer contains the weather decision.
        (port_dir / "adaptations.json").write_text(
            json.dumps({"schemaVersion": 1, "mapFieldDecisions": []})
        )
        verify_migration_evidence(
            report,
            port_dir,
            self.repo,
            evidence_root=self.root,
        )

        tampered = copy.deepcopy(report)
        tampered["policy"]["references"] = []
        with self.assertRaisesRegex(DonorUpdateError, "fabricated or stale"):
            verify_migration_evidence(
                tampered,
                port_dir,
                self.repo,
                evidence_root=self.root,
            )
        missing = copy.deepcopy(report)
        del missing["policy"]
        with self.assertRaisesRegex(DonorUpdateError, "policy snapshot"):
            verify_migration_evidence(
                missing,
                port_dir,
                self.repo,
                evidence_root=self.root,
            )

    def test_production_semantic_evidence_covers_every_enabled_native_domain(
        self,
    ) -> None:
        domains = ("trainer", "party", "encounter", "service", "binding")
        current = {f"content:{domain}:Fixture": "a" * 64 for domain in domains}
        current.update(
            {
                "content:binding:Removed": "c" * 64,
                "content:service:Unchanged": "d" * 64,
                "mechanical:trainer:Ignored": "e" * 64,
            }
        )
        target = {f"content:{domain}:Fixture": "b" * 64 for domain in domains}
        target.update(
            {
                "content:encounter:Added": "f" * 64,
                "content:service:Unchanged": "d" * 64,
                "mechanical:trainer:Ignored": "0" * 64,
            }
        )
        references = _semantic_policy_references(current, target, "content")
        reversed_references = _semantic_policy_references(
            dict(reversed(tuple(current.items()))),
            dict(reversed(tuple(target.items()))),
            "content",
        )
        self.assertEqual(references, reversed_references)
        self.assertEqual(
            {reference["authority"] for reference in references}, {"content"}
        )
        self.assertEqual(
            [reference["semanticIdentity"] for reference in references],
            sorted(
                [
                    *(f"{domain}:Fixture" for domain in domains),
                    "binding:Removed",
                    "encounter:Added",
                    "service:Unchanged",
                ]
            ),
        )
        report = build_migration(
            donor="content",
            repository="owner/repo",
            old_tree=self.worktree("semantic-old", self.old_commit),
            new_tree=self.worktree("semantic-new", self.old_commit),
            references=references,
        )
        self.assertEqual(
            {change["semanticIdentity"] for change in report["authorityChanges"]},
            {
                *(f"{domain}:Fixture" for domain in domains),
                "binding:Removed",
                "encounter:Added",
            },
        )
        changes = {
            change["semanticIdentity"]: change for change in report["authorityChanges"]
        }
        self.assertIsNone(changes["binding:Removed"]["newHash"])
        self.assertIsNone(changes["encounter:Added"]["oldHash"])
        self.assertNotIn("service:Unchanged", changes)

    def test_semantic_evidence_rejects_malformed_identities_and_hashes(self) -> None:
        with self.assertRaisesRegex(DonorUpdateError, "no resource identity"):
            _semantic_policy_references({"content:": "a" * 64}, {}, "content")
        for malformed in ("a" * 63, "A" * 64, 7):
            with (
                self.subTest(hash=malformed),
                self.assertRaisesRegex(DonorUpdateError, "lowercase hex hash"),
            ):
                _semantic_policy_references(
                    {"content:trainer:Fixture": malformed},  # type: ignore[dict-item]
                    {},
                    "content",
                )
        with self.assertRaisesRegex(DonorUpdateError, "identities must be strings"):
            _semantic_policy_references(
                {1: "a" * 64},  # type: ignore[dict-item]
                {},
                "content",
            )

        malformed_reference = {
            "authority": "content",
            "newHash": "not-a-hash",
            "oldHash": "a" * 64,
            "recordType": "semantic-evidence",
            "semanticIdentity": "trainer:Fixture",
            "sourcePath": "semantic-evidence/trainer/Fixture",
        }
        with self.assertRaisesRegex(DonorUpdateError, "newHash.*lowercase hex"):
            build_migration(
                donor="content",
                repository="owner/repo",
                old_tree=self.worktree("malformed-old", self.old_commit),
                new_tree=self.worktree("malformed-new", self.old_commit),
                references=(malformed_reference,),
            )

    def test_semantic_verification_recomputes_hashes_from_exact_pins(self) -> None:
        (self.repo / "data.json").write_text(json.dumps({"changed": True}))
        new_commit = make_commit(self.repo, "semantic verification target")
        actual_old = {"content:trainer:Fixture": "a" * 64}
        actual_new = {"content:trainer:Fixture": "b" * 64}
        report = build_migration(
            donor="content",
            repository="owner/repo",
            old_tree=self.worktree("semantic-verify-old", self.old_commit),
            new_tree=self.worktree("semantic-verify-new", new_commit),
            references=_semantic_policy_references(actual_old, actual_new, "content"),
        )
        port_dir = self.root / "semantic-port"
        port_dir.mkdir()
        (port_dir / "port.json").write_bytes(
            canonical_bytes(
                {
                    "donors": {
                        "content": {
                            "name": "fixture",
                            "root": "donor",
                        }
                    }
                }
            )
        )
        fabricated = copy.deepcopy(report)
        fabricated_reference = next(
            reference
            for reference in fabricated["policy"]["references"]
            if reference.get("recordType") == "semantic-evidence"
        )
        fabricated_reference["newHash"] = "c" * 64
        fabricated["authorityChanges"][0]["newHash"] = "c" * 64
        with (
            mock.patch(
                "tools.content_port.update._semantic_evidence_at_pin",
                side_effect=(actual_old, actual_new),
            ) as derive,
            self.assertRaisesRegex(DonorUpdateError, "fabricated or stale"),
        ):
            verify_migration_evidence(
                fabricated,
                port_dir,
                self.repo,
                evidence_root=self.root,
                donor_root=self.root,
                repo=self.root,
            )
        self.assertEqual(derive.call_count, 2)

    def test_public_update_and_finalize_derive_live_semantic_policy(self) -> None:
        repo = Path(__file__).resolve().parents[3]
        configured = os.environ.get("CONTENT_PORT_DONOR_ROOT")
        candidates = tuple(
            path
            for path in (
                Path(configured) if configured else None,
                repo / ".references",
                Path("/tmp/content-port-donors.ATzdJy"),
                repo.parents[2] / ".references",
            )
            if path is not None
        )
        source_donor_root = next(
            (
                path
                for path in candidates
                if all((path / name).is_dir() for name in ("pokemonHnS", "PKMN-World"))
            ),
            None,
        )
        if source_donor_root is None:
            self.skipTest("pinned donor checkouts are not present")

        donor_root = self.root / "live-donors"
        donor_root.mkdir()
        for name in ("pokemonHnS", "PKMN-World"):
            subprocess.run(
                (
                    "git",
                    "clone",
                    "-q",
                    "--shared",
                    str(source_donor_root / name),
                    str(donor_root / name),
                ),
                check=True,
            )

        ports_root = repo / "tools/content_port/ports"
        with tempfile.TemporaryDirectory(dir=ports_root) as directory:
            port_dir = Path(directory)
            shutil.copytree(ports_root / "johto", port_dir, dirs_exist_ok=True)
            port = json.loads((port_dir / "port.json").read_text())
            content = donor_root / "pokemonHnS"
            git(content, "config", "user.name", "Contract Test")
            git(content, "config", "user.email", "contract@example.invalid")
            git(content, "checkout", "-q", port["donors"]["content"]["commit"])
            parties = content / "src/data/trainer_parties.h"
            parties.write_text(
                parties.read_text().replace(
                    "    .species = SPECIES_GEODUDE,",
                    "    .species = SPECIES_ONIX,",
                    1,
                )
            )
            revision = make_commit(content, "semantic target")
            git(content, "checkout", "-q", port["donors"]["content"]["commit"])
            parties.write_text(
                parties.read_text().replace(
                    "    .species = SPECIES_GEODUDE,",
                    "    .species = SPECIES_ZUBAT,",
                    1,
                )
            )
            self.assertTrue(git(content, "status", "--porcelain"))
            output = self.root / "live-donor-migration.json"

            def descriptor_with_native_trainer(port_path: Path, donors: Path):
                descriptor = load_port(port_path, donors)
                capabilities = tuple(
                    replace(
                        decision,
                        state=CapabilityState.ENABLED,
                        dependencies=(ResourceKey("trainer", "TRAINER_SAWYER_1"),),
                    )
                    if decision.map_name == "Route29"
                    and decision.capability == "trainers"
                    else decision
                    for decision in descriptor.capabilities
                )
                return replace(
                    descriptor,
                    capabilities=capabilities,
                    legacy_report=None,
                )

            with (
                mock.patch(
                    "tools.content_port.update.run_review_commands",
                    return_value=tuple(passed_evidence()),
                ),
                mock.patch(
                    "tools.content_port.descriptor.load_port",
                    side_effect=descriptor_with_native_trainer,
                ),
                mock.patch("tools.content_port.materialize.derive_desired_state"),
            ):
                run_donor_update(
                    repo,
                    port_dir.name,
                    donor_root,
                    "content",
                    revision,
                    output,
                )
                report = json.loads(output.read_text())
                semantic_references = [
                    reference
                    for reference in report["policy"]["references"]
                    if reference.get("recordType") == "semantic-evidence"
                ]
                self.assertTrue(semantic_references)
                self.assertEqual(
                    {reference["authority"] for reference in semantic_references},
                    {"content"},
                )
                self.assertTrue(
                    any(
                        reference["oldHash"] != reference["newHash"]
                        for reference in semantic_references
                    )
                )
                report["decision"] = "reviewed"
                for change in (*report["authorityChanges"], *report["assets"]):
                    change["reviewerDisposition"] = "accepted"
                output.write_bytes(canonical_bytes(report))
                record, proposal = finalize_migration(
                    output,
                    port_dir,
                    donor_root=donor_root,
                    repo=repo,
                    evidence_root=repo,
                )
            finalized = json.loads(record.read_text())
            self.assertEqual(finalized["schemaVersion"], 2)
            self.assertRegex(finalized["publicationPolicyDigest"], r"^[0-9a-f]{64}$")
            self.assertEqual(
                json.loads(proposal.read_text())["proposedDonorRecord"]["commit"],
                revision,
            )

    def test_authored_snapshot_tracks_exact_live_reference_and_asset_removals(
        self,
    ) -> None:
        port_dir = self.root / "snapshot-port"
        port_dir.mkdir()
        adaptations = {
            "schemaVersion": 1,
            "donorFieldRoles": {"content": "content", "mechanical": "mechanical"},
            "adaptations": [
                {"source": "TestMap", "path": "weather"},
            ],
        }
        assets = self.asset_policy()
        assets["assets"][0]["donor"] = "content"
        (port_dir / "adaptations.json").write_bytes(canonical_bytes(adaptations))
        (port_dir / "assets.json").write_bytes(canonical_bytes(assets))
        port = {
            "adaptations": "adaptations.json",
            "assetPolicy": "assets.json",
            "donors": {
                "content": {
                    "name": "fixture",
                    "excludePaths": ["ignored"],
                }
            },
        }
        snapshot = _derive_authored_policy_snapshot(
            port_dir, port, "content", evidence_root=self.root
        )
        self.assertEqual(len(snapshot["references"]), 1)
        self.assertEqual(len(snapshot["assets"]["assets"]), 1)
        adaptations["adaptations"] = []
        assets["assets"] = []
        assets["permissionRecords"] = {}
        (port_dir / "adaptations.json").write_bytes(canonical_bytes(adaptations))
        (port_dir / "assets.json").write_bytes(canonical_bytes(assets))
        reduced = _derive_authored_policy_snapshot(
            port_dir, port, "content", evidence_root=self.root
        )
        self.assertEqual(reduced["references"], [])
        self.assertEqual(reduced["assets"]["assets"], [])
        self.assertNotEqual(snapshot, reduced)

    def test_worktree_cleanup_attempts_all_and_preserves_primary_error(self) -> None:
        first = self.root / "cleanup-first"
        second = self.root / "cleanup-second"
        first.mkdir()
        second.mkdir()
        primary = DonorUpdateError("primary donor failure")
        failed = subprocess.CompletedProcess(
            args=(), returncode=1, stdout="", stderr="remove refused"
        )
        with mock.patch(
            "tools.content_port.update.subprocess.run",
            side_effect=(OSError("git unavailable"), failed),
        ) as run:
            _remove_worktrees(
                ((self.repo, first), (self.repo, second)),
                primary_error=primary,
            )
        self.assertEqual(run.call_count, 2)
        self.assertEqual(str(primary), "primary donor failure")
        self.assertEqual(len(primary.__notes__), 1)
        self.assertIn("cleanup failed", primary.__notes__[0])
        self.assertIn(str(first), primary.__notes__[0])
        self.assertIn(str(second), primary.__notes__[0])

        with (
            mock.patch(
                "tools.content_port.update.subprocess.run",
                return_value=failed,
            ) as run,
            self.assertRaisesRegex(DonorUpdateError, "cleanup failed"),
        ):
            _remove_worktrees(
                ((self.repo, first), (self.repo, second)),
                primary_error=None,
            )
        self.assertEqual(run.call_count, 2)

    def test_update_and_finalize_reject_unsafe_authored_policy_paths(self) -> None:
        (self.repo / "data.json").write_text(json.dumps({"changed": True}))
        new_commit = make_commit(self.repo, "unsafe policy target")
        report = build_migration(
            donor="content",
            repository="owner/repo",
            old_tree=self.worktree("unsafe-policy-old", self.old_commit),
            new_tree=self.worktree("unsafe-policy-new", new_commit),
            tests=passed_evidence(),
        )
        report["decision"] = "reviewed"

        for operation in ("update", "finalize"):
            for field in ("adaptations", "assetPolicy"):
                for unsafe_kind, message in (
                    ("traversal", "expected one local policy filename"),
                    ("symlink", "must not be a symbolic link"),
                ):
                    with self.subTest(
                        operation=operation, field=field, unsafe_kind=unsafe_kind
                    ):
                        host = self.root / f"unsafe-{operation}-{field}-{unsafe_kind}"
                        port_dir = host / "tools/content_port/ports/fixture"
                        port_dir.mkdir(parents=True)
                        adaptations = port_dir / "adaptations.json"
                        assets = port_dir / "assets.json"
                        adaptations.write_bytes(canonical_bytes({"schemaVersion": 1}))
                        assets.write_bytes(
                            canonical_bytes(
                                {
                                    "schemaVersion": 1,
                                    "permissionRecords": {},
                                    "assets": [],
                                }
                            )
                        )
                        selected = {
                            "adaptations": adaptations.name,
                            "assetPolicy": assets.name,
                        }
                        outside = port_dir.parent / f"outside-{field}.json"
                        outside.write_bytes(
                            adaptations.read_bytes()
                            if field == "adaptations"
                            else assets.read_bytes()
                        )
                        if unsafe_kind == "traversal":
                            selected[field] = f"../{outside.name}"
                        else:
                            link = port_dir / f"{field}-link.json"
                            link.symlink_to(outside)
                            selected[field] = link.name
                        port = {
                            **selected,
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
                            },
                        }
                        (port_dir / "port.json").write_bytes(canonical_bytes(port))
                        output = host / "candidate.json"
                        if operation == "update":

                            def invoke() -> object:
                                return run_donor_update(
                                    host,
                                    "fixture",
                                    self.root,
                                    "content",
                                    new_commit,
                                    output,
                                )

                        else:
                            output.write_bytes(canonical_bytes(report))

                            def invoke() -> object:
                                return finalize_migration(
                                    output,
                                    port_dir,
                                    donor_root=self.root,
                                    repo=host,
                                    evidence_root=host,
                                )

                        with (
                            mock.patch(
                                "tools.content_port.update.run_review_commands",
                                return_value=tuple(passed_evidence()),
                            ),
                            self.assertRaisesRegex(DonorUpdateError, message),
                        ):
                            invoke()
                        if operation == "update":
                            self.assertFalse(output.exists())
                        self.assertFalse((port_dir / "migrations").exists())
                        self.assertFalse(
                            output.with_name("donor-port-update.json").exists()
                        )

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

        finalized_without_binding = build_migration(
            donor="fixture",
            repository="owner/repo",
            old_tree=self.worktree("missing-binding", self.old_commit),
            new_tree=self.worktree("missing-binding-target", self.old_commit),
        )
        finalized_without_binding["schemaVersion"] = 2
        missing_digest = migration_digest(finalized_without_binding)
        (migrations / f"{missing_digest}.json").write_bytes(
            canonical_bytes(finalized_without_binding)
        )
        with self.assertRaisesRegex(
            DonorUpdateError, "requires publicationPolicyDigest"
        ):
            load_reviewed_migration(migrations, missing_digest)

    def test_cli_wrapper_writes_candidate_without_editing_port_policy(self) -> None:
        host = self.root / "host"
        port = host / "tools/content_port/ports/fixture"
        port.mkdir(parents=True)
        assets = {"schemaVersion": 1, "permissionRecords": {}, "assets": []}
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
            "adaptations": "adaptations.json",
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
        with (
            mock.patch(
                "tools.content_port.update.run_review_commands",
                return_value=tuple(passed_evidence()),
            ),
            mock.patch(
                "tools.content_port.update._derive_live_policy_snapshot",
                return_value=empty_policy(),
            ),
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
            references=(
                {
                    "authority": "content",
                    "jsonPointer": "/maps/Route/section",
                    "semanticIdentity": "map:Route.section",
                    "sourcePath": "data.json",
                },
            ),
            tests=passed_evidence(),
            evidence_root=self.root,
        )
        candidate_digest = migration_digest(report)
        report["decision"] = "reviewed"
        report["assets"][0]["reviewerDisposition"] = "accepted"
        report["authorityChanges"][0]["reviewerDisposition"] = "accepted"
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
            "allocationLock": "allocations.json",
            "adaptations": "adaptations.json",
            "assetPolicy": "assets.json",
            "capabilityPolicy": "capabilities.json",
            "eventPolicy": "events.json",
            "legacyReport": "legacy.json",
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
            },
        }
        port_path = port_dir / "port.json"
        # Publication may begin from an authored, semantically valid descriptor
        # whose JSON bytes are not canonical. Applying the proposal normally
        # rewrites the descriptor canonically and must preserve the binding.
        port_path.write_text(json.dumps(port, separators=(",", ":")))
        self.assertNotEqual(port_path.read_bytes(), canonical_bytes(port))
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
        for filename in (
            "allocations.json",
            "capabilities.json",
            "events.json",
            "legacy.json",
        ):
            (port_dir / filename).write_bytes(canonical_bytes({}))
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
            evidence_root=self.root,
        )
        before = port_path.read_bytes()
        candidate = self.root / "donor-migration.json"
        candidate.write_bytes(canonical_bytes(report))
        policy_paths = {
            field: port_dir / str(port[field])
            for field in (
                "capabilityPolicy",
                "eventPolicy",
                "legacyReport",
                "adaptations",
                "assetPolicy",
                "allocationLock",
            )
        }
        original = policy_paths["adaptations"].read_bytes()

        def drift_during_live_policy(*args: object, **kwargs: object) -> object:
            policy_paths["adaptations"].write_bytes(original + b" \n")
            return report["policy"]

        with (
            mock.patch(
                "tools.content_port.update._derive_live_policy_snapshot",
                side_effect=drift_during_live_policy,
            ),
            mock.patch("tools.content_port.update.verify_migration_evidence") as verify,
            self.assertRaisesRegex(DonorUpdateError, "policy drifted"),
        ):
            finalize_migration(
                candidate,
                port_dir,
                donor_root=self.root,
                repo=Path.cwd(),
                evidence_root=self.root,
            )
        verify.assert_called_once()
        self.assertFalse((port_dir / "migrations").exists())
        self.assertFalse(candidate.with_name("donor-port-update.json").exists())
        policy_paths["adaptations"].write_bytes(original)

        for field, policy_path in policy_paths.items():
            original = policy_path.read_bytes()

            def drift_policy_after_verification(
                *args: object,
                drifted_path: Path = policy_path,
                **kwargs: object,
            ) -> None:
                verify_migration_evidence(*args, **kwargs)  # type: ignore[arg-type]
                drifted_path.write_bytes(original + b" \n")

            with (
                self.subTest(field=field),
                mock.patch(
                    "tools.content_port.update._derive_live_policy_snapshot",
                    return_value=report["policy"],
                ),
                mock.patch(
                    "tools.content_port.update.verify_migration_evidence",
                    side_effect=drift_policy_after_verification,
                ),
                self.assertRaisesRegex(DonorUpdateError, "policy drifted"),
            ):
                finalize_migration(
                    candidate,
                    port_dir,
                    donor_root=self.root,
                    repo=Path.cwd(),
                    evidence_root=self.root,
                )
            self.assertFalse((port_dir / "migrations").exists())
            self.assertFalse(candidate.with_name("donor-port-update.json").exists())
            policy_path.write_bytes(original)

        original_port = port_path.read_bytes()
        drifted_port = dict(port)
        drifted_port["schemaVersion"] = 2

        def drift_port_before_initial_digest(*args: object, **kwargs: object):
            port_path.write_bytes(canonical_bytes(drifted_port))
            return tuple(passed_evidence())

        with (
            mock.patch(
                "tools.content_port.update.run_review_commands",
                side_effect=drift_port_before_initial_digest,
            ),
            mock.patch(
                "tools.content_port.update._derive_live_policy_snapshot",
                return_value=report["policy"],
            ),
            mock.patch("tools.content_port.update.verify_migration_evidence"),
            self.assertRaisesRegex(DonorUpdateError, "policy drifted"),
        ):
            finalize_migration(
                candidate,
                port_dir,
                donor_root=self.root,
                repo=Path.cwd(),
                evidence_root=self.root,
            )
        self.assertFalse((port_dir / "migrations").exists())
        self.assertFalse(candidate.with_name("donor-port-update.json").exists())
        port_path.write_bytes(original_port)

        for digest_call, artifact in ((2, "record"), (4, "proposal")):
            original = policy_paths["adaptations"].read_bytes()
            calls = 0
            real_digest = donor_update_module._publication_policy_digest

            def drift_after_final_digest(*args: object, **kwargs: object) -> str:
                nonlocal calls
                calls += 1
                digest = real_digest(*args, **kwargs)  # type: ignore[arg-type]
                if calls == digest_call:
                    policy_paths["adaptations"].write_bytes(original + b" \n")
                return digest

            with (
                self.subTest(artifact=artifact),
                mock.patch(
                    "tools.content_port.update._derive_live_policy_snapshot",
                    return_value=report["policy"],
                ),
                mock.patch("tools.content_port.update.verify_migration_evidence"),
                mock.patch(
                    "tools.content_port.update._publication_policy_digest",
                    side_effect=drift_after_final_digest,
                ),
                self.assertRaisesRegex(DonorUpdateError, "policy drifted"),
            ):
                finalize_migration(
                    candidate,
                    port_dir,
                    donor_root=self.root,
                    repo=Path.cwd(),
                    evidence_root=self.root,
                )
            self.assertFalse((port_dir / "migrations").exists())
            self.assertFalse(candidate.with_name("donor-port-update.json").exists())
            policy_paths["adaptations"].write_bytes(original)

        outside_migrations = self.root / "outside-migrations"
        outside_migrations.mkdir()
        migrations_link = port_dir / "migrations"
        migrations_link.symlink_to(outside_migrations, target_is_directory=True)
        with self.assertRaisesRegex(DonorUpdateError, "must be a real directory"):
            load_reviewed_migration(migrations_link, "0" * 64)
        with (
            mock.patch(
                "tools.content_port.update.run_review_commands",
                return_value=tuple(passed_evidence()),
            ),
            mock.patch(
                "tools.content_port.update._derive_live_policy_snapshot",
                return_value=report["policy"],
            ),
            mock.patch("tools.content_port.update.verify_migration_evidence"),
            self.assertRaisesRegex(DonorUpdateError, "must be a real directory"),
        ):
            finalize_migration(
                candidate,
                port_dir,
                donor_root=self.root,
                repo=Path.cwd(),
                evidence_root=self.root,
            )
        self.assertEqual(list(outside_migrations.iterdir()), [])
        migrations_link.unlink()

        with mock.patch(
            "tools.content_port.update._derive_live_policy_snapshot",
            return_value=report["policy"],
        ):
            record, proposal = finalize_migration(
                candidate,
                port_dir,
                donor_root=self.root,
                repo=Path.cwd(),
                evidence_root=self.root,
            )
        finalized = json.loads(record.read_text())
        self.assertEqual(record.name, migration_filename(finalized))
        self.assertEqual(finalized["schemaVersion"], 2)
        self.assertRegex(finalized["publicationPolicyDigest"], r"^[0-9a-f]{64}$")
        captured_documents = finalized["publicationPolicySnapshot"]["policyDocuments"]
        self.assertEqual(set(captured_documents), set(policy_paths))
        for entry in captured_documents.values():
            self.assertEqual(
                entry["sha256"],
                hashlib.sha256(canonical_bytes(entry["document"])).hexdigest(),
            )
        self.assertEqual(port_path.read_bytes(), before)
        update = json.loads(proposal.read_text())
        self.assertEqual(update["migration"], migration_digest(finalized))
        self.assertEqual(
            update["publicationPolicyDigest"],
            finalized["publicationPolicyDigest"],
        )
        self.assertEqual(
            update["proposedDonorRecord"]["commit"], report["to"]["commit"]
        )
        self.assertEqual(update["proposedDonorRecord"]["genesis"], report["from"])

        applied_port = copy.deepcopy(port)
        applied_port["donors"]["content"] = update["proposedDonorRecord"]
        port_path.write_bytes(canonical_bytes(applied_port))
        loaded = load_reviewed_migration(
            record.parent,
            record.stem,
            evidence_root=self.root,
        )
        self.assertEqual(loaded, finalized)
        capability_bytes = policy_paths["capabilityPolicy"].read_bytes()
        policy_paths["capabilityPolicy"].write_bytes(capability_bytes + b" \n")
        # Raw formatting drift is not semantic drift after publication.
        self.assertEqual(
            load_reviewed_migration(
                record.parent,
                record.stem,
                evidence_root=self.root,
            ),
            finalized,
        )
        policy_paths["capabilityPolicy"].write_bytes(capability_bytes)
        policy_paths["capabilityPolicy"].write_bytes(
            canonical_bytes({"semanticChange": True})
        )
        with self.assertRaisesRegex(DonorUpdateError, "publication policy is stale"):
            load_reviewed_migration(
                record.parent,
                record.stem,
                evidence_root=self.root,
            )
        policy_paths["capabilityPolicy"].write_bytes(capability_bytes)
        applied_port["donors"]["content"]["excludePaths"] = ["new-exclusion"]
        port_path.write_bytes(canonical_bytes(applied_port))
        with self.assertRaisesRegex(DonorUpdateError, "publication policy is stale"):
            load_reviewed_migration(
                record.parent,
                record.stem,
                evidence_root=self.root,
            )
        port_path.write_bytes(before)

        shrunk = copy.deepcopy(report)
        shrunk["policy"]["references"] = []
        shrunk["authorityChanges"] = []
        candidate.write_bytes(canonical_bytes(shrunk))
        with (
            mock.patch(
                "tools.content_port.update._derive_live_policy_snapshot",
                return_value=report["policy"],
            ),
            self.assertRaisesRegex(DonorUpdateError, "differs from live policy"),
        ):
            finalize_migration(
                candidate,
                port_dir,
                donor_root=self.root,
                repo=Path.cwd(),
                evidence_root=self.root,
            )

        stale_predecessor = copy.deepcopy(report)
        stale_predecessor["predecessor"] = "f" * 64
        candidate.write_bytes(canonical_bytes(stale_predecessor))
        with self.assertRaisesRegex(
            DonorUpdateError, "predecessor is not the published pin"
        ):
            with mock.patch("tools.content_port.update._validate_target_pin"):
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
            "policy": empty_policy(),
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

        report["authorityChanges"] = []
        for permission in ("blocked", "unknown"):
            report["assets"] = [
                {
                    "key": "unpublishable-art",
                    "permission": permission,
                    "reviewerDisposition": "accepted",
                }
            ]
            candidate.write_bytes(canonical_bytes(report))
            with (
                self.subTest(permission=permission),
                self.assertRaisesRegex(DonorUpdateError, f"permission is {permission}"),
            ):
                finalize_migration(candidate, port_dir)

    def test_finalize_fails_before_publication_when_target_pin_is_invalid(self) -> None:
        (self.repo / "data.json").write_text(json.dumps({"changed": True}))
        new_commit = make_commit(self.repo, "target")
        report = build_migration(
            donor="content",
            repository="owner/repo",
            old_tree=self.worktree("target-check-old", self.old_commit),
            new_tree=self.worktree("target-check-new", new_commit),
            tests=passed_evidence(),
        )
        report["decision"] = "reviewed"
        candidate = self.root / "target-check.json"
        candidate.write_bytes(canonical_bytes(report))
        port_dir = self.root / "target-port"
        port_dir.mkdir()
        port = {
            "adaptations": "adaptations.json",
            "assetPolicy": "assets.json",
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
            },
        }
        (port_dir / "port.json").write_bytes(canonical_bytes(port))
        (port_dir / "assets.json").write_bytes(
            canonical_bytes({"schemaVersion": 1, "permissionRecords": {}, "assets": []})
        )
        (port_dir / "adaptations.json").write_bytes(
            canonical_bytes({"schemaVersion": 1})
        )

        with (
            mock.patch(
                "tools.content_port.update._derive_live_policy_snapshot",
                side_effect=DonorUpdateError("target pin production check failed"),
            ),
            self.assertRaisesRegex(
                DonorUpdateError, "target pin production check failed"
            ),
        ):
            finalize_migration(
                candidate, port_dir, donor_root=self.root, repo=Path.cwd()
            )
        self.assertFalse((port_dir / "migrations").exists())
        self.assertFalse(candidate.with_name("donor-port-update.json").exists())

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
            "policy": empty_policy(),
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
        assets = validate_assets(policy, evidence_root=Path.cwd())
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
                self.assertEqual(
                    asset["permissionEvidence"],
                    "0efc89c74162ec6967f3a7b0acf9a8e639f6ec2289ec316bb284673ec45bce05",
                )


if __name__ == "__main__":
    unittest.main()
