from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.content_port.descriptor import ADAPTATION_KEYS, load_port, read_json
from tools.content_port.errors import ContentPortError
from tools.content_port.update import canonical_bytes, migration_digest

from tools.content_port.tests.test_allocations import allocation_document


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class DescriptorTests(unittest.TestCase):
    def test_checked_port_declares_every_map_and_capability(self):
        port_dir = Path(__file__).parents[1] / "ports" / "johto"
        descriptor = load_port(port_dir, port_dir / "unused-donor-root")
        self.assertEqual(len(descriptor.allocation_index.maps), 254)
        self.assertEqual(len(descriptor.map_ownership), 254)
        self.assertEqual(len(descriptor.capabilities), 254 * 12)
        self.assertEqual(list(descriptor.map_ownership.values()).count("preserve"), 16)
        state_counts: dict[str, int] = {}
        for decision in descriptor.capabilities:
            state_counts[decision.state.value] = (
                state_counts.get(decision.state.value, 0) + 1
            )
        self.assertEqual(
            state_counts,
            {"enabled": 508, "deferred": 2380, "story-owned": 160},
        )
        self.assertEqual(
            {
                domain: item["count"]
                for domain, item in descriptor.expected_inventory.items()
            },
            {"maps": 254, "layouts": 255, "groups": 25, "sections": 58, "tilesets": 71},
        )

    def make_port(self, root: Path) -> dict[str, object]:
        dump(root / "allocation_lock.json", allocation_document())
        capabilities = {
            "schemaVersion": 1,
            "capabilities": ["spatial", "events"],
            "maps": [
                {
                    "map": "TestMap",
                    "ownership": "rendered",
                    "capabilities": {
                        "spatial": "enabled",
                        "events": {
                            "state": "deferred",
                            "dependencies": [{"domain": "asset", "name": "tiles"}],
                        },
                    },
                }
            ],
        }
        dump(root / "capabilities.json", capabilities)
        adaptations = {key: [] for key in ADAPTATION_KEYS}
        adaptations["schemaVersion"] = 1
        dump(root / "adaptations.json", adaptations)
        dump(root / "events.json", {"schemaVersion": 1, "entries": []})
        dump(root / "assets.json", {"schemaVersion": 1, "assets": []})
        dump(root / "legacy_report.json", {"schemaVersion": 1, "inventory": {}})
        port = {
            "schemaVersion": 1,
            "allocationLock": "allocation_lock.json",
            "capabilityPolicy": "capabilities.json",
            "eventPolicy": "events.json",
            "adaptations": "adaptations.json",
            "assetPolicy": "assets.json",
            "legacyReport": "legacy_report.json",
            "donors": {
                "mechanical": {
                    "name": "mechanical",
                    "repository": "example/mechanical",
                    "commit": "1" * 40,
                    "treeDigest": "2" * 64,
                    "fileCount": 2,
                    "root": "mechanical",
                    "migration": None,
                },
                "content": {
                    "name": "content",
                    "repository": "example/content",
                    "commit": "3" * 40,
                    "treeDigest": "4" * 64,
                    "fileCount": 3,
                    "root": "content",
                    "migration": None,
                },
            },
            "expectedInventory": {
                domain: {"count": 1, "digest": "5" * 64}
                for domain in ("maps", "layouts", "groups", "sections", "tilesets")
            },
            "authority": {
                "content": ["map-fields"],
                "mechanical": ["layout-format"],
                "unclassifiedDivergence": "error",
            },
        }
        dump(root / "port.json", port)
        return port

    def attach_migration(
        self, root: Path, port: dict[str, object], mutation=None
    ) -> tuple[str, dict[str, object]]:
        pin = port["donors"]["mechanical"]  # type: ignore[index]
        report: dict[str, object] = {
            "addedPaths": [],
            "assets": [],
            "authorityChanges": [],
            "changedPaths": ["data/maps/TestMap/map.json"],
            "decision": "reviewed",
            "donor": "mechanical",
            "from": {
                "commit": "6" * 40,
                "fileCount": 1,
                "treeDigest": "7" * 64,
            },
            "removedPaths": [],
            "repository": pin["repository"],
            "schemaVersion": 1,
            "tests": ["python3 -m unittest fixture"],
            "to": {
                "commit": pin["commit"],
                "fileCount": pin["fileCount"],
                "treeDigest": pin["treeDigest"],
            },
        }
        if mutation is not None:
            mutation(report, pin)
        digest = migration_digest(report)
        migrations = root / "migrations"
        migrations.mkdir(exist_ok=True)
        (migrations / f"{digest}.json").write_bytes(canonical_bytes(report))
        pin["migration"] = digest
        dump(root / "port.json", port)
        return digest, report

    def test_loads_complete_port_and_freezes_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_port(root)
            descriptor = load_port(root, root / "donors")
            self.assertEqual(descriptor.allocation_index.layout_slot("LAYOUT_TEST"), 12)
            self.assertEqual(len(descriptor.capabilities), 2)
            self.assertEqual(descriptor.donors[0].root, root / "donors/mechanical")
            with self.assertRaises(TypeError):
                descriptor.authority["new"] = ()  # type: ignore[index]

    def test_loads_exact_reviewed_content_addressed_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = self.make_port(root)
            digest, _report = self.attach_migration(root, port)
            descriptor = load_port(root, root / "donors")
            self.assertEqual(descriptor.donors[0].migration, digest)

    def test_missing_stale_and_unreviewed_migrations_fail_closed(self):
        cases = (
            (
                lambda report, _pin: report.update(decision="candidate"),
                "migration record is not reviewed",
            ),
            (
                lambda report, _pin: report.update(decision="rejected"),
                "migration record is not reviewed",
            ),
            (
                lambda report, _pin: report.update(donor="content"),
                "migration record names another donor",
            ),
            (
                lambda report, _pin: report.update(repository="other/repository"),
                "migration repository is stale",
            ),
            (
                lambda report, _pin: report["to"].update(treeDigest="8" * 64),
                "migration target treeDigest is stale",
            ),
            (
                lambda report, pin: report["from"].update(commit=pin["commit"]),
                "commit chain is a no-op",
            ),
            (
                lambda report, _pin: report.update(tests=[]),
                "reviewed migration needs recorded tests",
            ),
            (
                lambda report, _pin: report.update(
                    authorityChanges=[{"authority": "content"}]
                ),
                "review is incomplete",
            ),
        )
        for mutation, message in cases:
            with (
                self.subTest(message=message),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                port = self.make_port(root)
                self.attach_migration(root, port, mutation)
                with self.assertRaisesRegex(ContentPortError, message):
                    load_port(root, root / "donors")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = self.make_port(root)
            port["donors"]["mechanical"]["migration"] = "0" * 64  # type: ignore[index]
            dump(root / "port.json", port)
            with self.assertRaisesRegex(ContentPortError, "cannot read JSON"):
                load_port(root, root / "donors")

    def test_migration_content_address_and_pin_type_are_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = self.make_port(root)
            digest, report = self.attach_migration(root, port)
            stale = "0" * 64
            (root / "migrations" / f"{stale}.json").write_bytes(canonical_bytes(report))
            port["donors"]["mechanical"]["migration"] = stale  # type: ignore[index]
            dump(root / "port.json", port)
            self.assertNotEqual(digest, stale)
            with self.assertRaisesRegex(ContentPortError, "filename is stale"):
                load_port(root, root / "donors")

            port = self.make_port(root)
            port["donors"]["mechanical"]["migration"] = 7  # type: ignore[index]
            dump(root / "port.json", port)
            with self.assertRaisesRegex(
                ContentPortError, "expected null or 64 lowercase hex"
            ):
                load_port(root, root / "donors")

    def test_unknown_and_duplicate_json_fields_fail_with_location(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = self.make_port(root)
            port["unexpected"] = True
            dump(root / "port.json", port)
            with self.assertRaisesRegex(
                ContentPortError, r"\$: unknown field 'unexpected'"
            ):
                load_port(root, root)
            (root / "port.json").write_text('{"schemaVersion":1,"schemaVersion":1}\n')
            with self.assertRaisesRegex(
                ContentPortError, "duplicate JSON field 'schemaVersion'"
            ):
                read_json(root / "port.json")

    def test_numeric_policy_field_fails_before_donor_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_port(root)
            events = {"schemaVersion": 1, "entries": [{"targetId": 7}]}
            dump(root / "events.json", events)
            with self.assertRaisesRegex(
                ContentPortError, "numeric placement belongs in allocation_lock.json"
            ):
                load_port(root, root / "missing-donors")

    def test_unknown_capability_state_and_map_drift_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_port(root)
            path = root / "capabilities.json"
            document = read_json(path)
            document["maps"][0]["capabilities"]["events"] = "implicit"  # type: ignore[index]
            dump(path, document)
            with self.assertRaisesRegex(ContentPortError, "unknown capability state"):
                load_port(root, root)
            self.make_port(root)
            document = read_json(path)
            document["maps"][0]["map"] = "OtherMap"  # type: ignore[index]
            dump(path, document)
            with self.assertRaisesRegex(
                ContentPortError, "does not match allocation maps"
            ):
                load_port(root, root)

    def test_unsafe_donor_and_policy_paths_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = self.make_port(root)
            port["allocationLock"] = "../allocation_lock.json"
            dump(root / "port.json", port)
            with self.assertRaisesRegex(ContentPortError, "one local policy filename"):
                load_port(root, root)
            port = self.make_port(root)
            port["donors"]["content"]["root"] = "../escape"  # type: ignore[index]
            dump(root / "port.json", port)
            with self.assertRaisesRegex(ContentPortError, "unsafe donor checkout path"):
                load_port(root, root)


if __name__ == "__main__":
    unittest.main()
