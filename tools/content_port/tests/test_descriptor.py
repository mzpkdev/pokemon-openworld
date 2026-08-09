from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.content_port.descriptor import ADAPTATION_KEYS, load_port, read_json
from tools.content_port.errors import ContentPortError
from tools.content_port.update import (
    REQUIRED_REVIEW_COMMANDS,
    build_migration,
    canonical_bytes,
    identify_tree,
    migration_digest,
)

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
        adaptations["layoutBinaryAuthorities"] = [
            {
                "layout": "LAYOUT_TEST",
                "source": "TestMap",
                "sourceRole": "content",
            }
        ]
        adaptations["generatedSections"] = [
            {
                "key": key,
                "path": path,
                "sourceRole": "policy",
                "sourceSymbol": symbol,
            }
            for key, path, symbol in (
                ("map scripts", "data/event_scripts.s", "map-scripts"),
                (
                    "berry tree allocations",
                    "include/constants/berry.h",
                    "berry-bindings",
                ),
                ("flags", "include/constants/flags.h", "flag-bindings"),
                (
                    "rival opponents",
                    "include/constants/opponents.h",
                    "trainer-bindings",
                ),
                ("vars", "include/constants/vars.h", "var-bindings"),
                ("externs", "include/tilesets.h", "tileset-externs"),
                ("graphics", "src/data/tilesets/graphics.h", "tileset-graphics"),
                ("headers", "src/data/tilesets/headers.h", "tileset-headers"),
                ("metatiles", "src/data/tilesets/metatiles.h", "tileset-metatiles"),
                ("rival trainers", "src/data/trainers.party", "trainer-parties"),
            )
        ]
        adaptations["sectionMetadataAuthorities"] = [
            {
                "section": "MAPSEC_TEST",
                "sourceRole": "content",
                "sourceSymbol": "MAPSEC_TEST",
            }
        ]
        adaptations["targetBindings"] = {
            "layoutFormat": "test",
            "sectionKind": "geographic",
            "region": "REGION_TEST",
            "regionMapType": "REGION_MAP_TEST",
            "savedLocationInvalidBinding": {
                "domain": "savedLocations",
                "symbol": "MAPSEC_ICE_PATH",
            },
            "metLocationInvalidBinding": {
                "domain": "destinations",
                "symbol": "MAPSEC_BLACKTHORN_CITY",
            },
            "berryTreeBinding": {
                "domain": "berryTrees",
                "symbol": "BERRY_TREE_ROUTE_29_ORAN_1",
            },
            "tilesetFeatureMacro": "HAS_TEST_TILESETS",
            "timeEncounterLabel": "Test_EventScript_SetTimeEncounters",
            "deferredCallLabel": "Test_Text_DeferredCall",
            "deferredCallText": "Call again later.$",
            "sectionPersistenceCodecs": [
                {
                    "section": "MAPSEC_TEST",
                    "savedLocation": "MAPSEC_TEST",
                    "metLocationBinding": {
                        "domain": "destinations",
                        "symbol": "MAPSEC_TEST",
                    },
                    "metLocationDisplay": "MAPSEC_TEST",
                }
            ],
            "flagExports": [],
            "varExports": [],
        }
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
                    "excludePaths": [],
                    "genesis": {
                        "commit": "1" * 40,
                        "fileCount": 2,
                        "treeDigest": "2" * 64,
                    },
                    "root": "mechanical",
                    "migration": None,
                },
                "content": {
                    "name": "content",
                    "repository": "example/content",
                    "commit": "3" * 40,
                    "treeDigest": "4" * 64,
                    "fileCount": 3,
                    "excludePaths": [],
                    "genesis": {
                        "commit": "3" * 40,
                        "fileCount": 3,
                        "treeDigest": "4" * 64,
                    },
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
        self,
        root: Path,
        port: dict[str, object],
        mutation=None,
        *,
        from_after_genesis: bool = False,
    ) -> tuple[str, dict[str, object]]:
        pin = port["donors"]["mechanical"]  # type: ignore[index]
        donor = root / "donors/mechanical"
        donor.mkdir(parents=True)
        subprocess.run(("git", "init", "-q"), cwd=donor, check=True)
        subprocess.run(
            ("git", "config", "user.name", "Descriptor Test"),
            cwd=donor,
            check=True,
        )
        subprocess.run(
            ("git", "config", "user.email", "descriptor@example.invalid"),
            cwd=donor,
            check=True,
        )
        (donor / "evidence.txt").write_text("old\n")
        subprocess.run(("git", "add", "."), cwd=donor, check=True)
        subprocess.run(("git", "commit", "-q", "-m", "old"), cwd=donor, check=True)
        genesis = identify_tree(donor)
        if from_after_genesis:
            (donor / "evidence.txt").write_text("middle\n")
            subprocess.run(("git", "add", "."), cwd=donor, check=True)
            subprocess.run(
                ("git", "commit", "-q", "-m", "middle"), cwd=donor, check=True
            )
            source = identify_tree(donor)
        else:
            source = genesis
        (donor / "evidence.txt").write_text("new\n")
        subprocess.run(("git", "add", "."), cwd=donor, check=True)
        subprocess.run(("git", "commit", "-q", "-m", "new"), cwd=donor, check=True)
        target = identify_tree(donor)
        pin["genesis"] = {
            "commit": genesis.commit,
            "fileCount": genesis.file_count,
            "treeDigest": genesis.digest,
        }
        pin.update(
            commit=target.commit,
            treeDigest=target.digest,
            fileCount=target.file_count,
        )
        old_tree = root / "old-donor"
        subprocess.run(
            (
                "git",
                "-C",
                str(donor),
                "worktree",
                "add",
                "-q",
                "--detach",
                str(old_tree),
                source.commit,
            ),
            check=True,
        )
        report = build_migration(
            donor="mechanical",
            repository=str(pin["repository"]),
            old_tree=old_tree,
            new_tree=donor,
            tests=(
                {"command": list(command), "result": "passed"}
                for command in REQUIRED_REVIEW_COMMANDS
            ),
        )
        report["decision"] = "reviewed"
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
            self.assertIs(descriptor.donor("mechanical"), descriptor.donors[0])
            self.assertEqual(
                descriptor.allocation_index.map_allocation("TestMap").layout,
                "LAYOUT_TEST",
            )
            self.assertEqual(len(descriptor.generated_sections), 10)
            self.assertEqual(
                descriptor.target_bindings.berry_tree_binding.symbol,
                "BERRY_TREE_ROUTE_29_ORAN_1",
            )
            self.assertEqual(
                descriptor.target_bindings.section_persistence_codecs[
                    0
                ].met_location_binding.domain,
                "destinations",
            )
            with self.assertRaises(TypeError):
                descriptor.authority["new"] = ()  # type: ignore[index]
            with self.assertRaises(TypeError):
                descriptor.donors_by_role["other"] = descriptor.donors[0]  # type: ignore[index]

    def test_donor_roles_are_explicit_and_extensible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = self.make_port(root)
            extra = dict(port["donors"]["content"])  # type: ignore[index]
            extra.update(name="reference", root="reference")
            port["donors"]["reference"] = extra  # type: ignore[index]
            dump(root / "port.json", port)
            descriptor = load_port(root, root / "donors")
            self.assertEqual(
                set(descriptor.donors_by_role), {"mechanical", "content", "reference"}
            )
            self.assertEqual(descriptor.donor("reference").name, "reference")
            with self.assertRaisesRegex(ContentPortError, "no donor role 'missing'"):
                descriptor.donor("missing")

            del port["donors"]["content"]  # type: ignore[index]
            dump(root / "port.json", port)
            with self.assertRaisesRegex(
                ContentPortError, "missing authority donor role 'content'"
            ):
                load_port(root, root / "donors")

    def test_renderer_policy_is_exact_and_complete(self):
        cases = (
            (
                lambda document: document.update(layoutBinaryAuthorities=[]),
                "must cover every allocated layout",
            ),
            (
                lambda document: document["sectionMetadataAuthorities"][0].update(
                    sourceRole="missing"
                ),
                "unknown donor role 'missing'",
            ),
            (
                lambda document: document.update(
                    generatedSections=document["generatedSections"][:-1]
                ),
                "missing renderer source",
            ),
            (
                lambda document: document["targetBindings"].update(extra=True),
                "unknown field 'extra'",
            ),
            (
                lambda document: document["targetBindings"].update(berryTreeBase=90),
                "unknown field 'berryTreeBase'",
            ),
            (
                lambda document: document.pop("targetBindings"),
                "missing field 'targetBindings'",
            ),
        )
        for mutation, message in cases:
            with (
                self.subTest(message=message),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                self.make_port(root)
                path = root / "adaptations.json"
                document = read_json(path)
                mutation(document)
                dump(path, document)
                with self.assertRaisesRegex(ContentPortError, message):
                    load_port(root, root / "donors")

    def test_loads_exact_reviewed_content_addressed_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = self.make_port(root)
            digest, _report = self.attach_migration(root, port)
            descriptor = load_port(root, root / "donors")
            self.assertEqual(descriptor.donors[0].migration, digest)

    def test_hand_installed_record_cannot_skip_published_predecessor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = self.make_port(root)
            self.attach_migration(root, port, from_after_genesis=True)
            with self.assertRaisesRegex(
                ContentPortError, "does not start at genesis pin"
            ):
                load_port(root, root / "donors")

    def test_unlinked_pin_must_equal_authored_genesis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = self.make_port(root)
            port["donors"]["mechanical"]["commit"] = "9" * 40  # type: ignore[index]
            dump(root / "port.json", port)
            with self.assertRaisesRegex(
                ContentPortError, "unlinked pin differs from genesis"
            ):
                load_port(root, root / "donors")

    def test_donor_exclusions_require_sorted_safe_exact_paths(self):
        invalid = (
            (["../outside"], "unsafe donor excluded path"),
            (["nested//file"], "unsafe donor excluded path"),
            (["z.bin", "a.bin"], "expected sorted exact paths"),
            (["same", "same"], "must not contain duplicates"),
        )
        for exclusions, message in invalid:
            with (
                self.subTest(exclusions=exclusions),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                port = self.make_port(root)
                port["donors"]["mechanical"]["excludePaths"] = exclusions  # type: ignore[index]
                dump(root / "port.json", port)
                with self.assertRaisesRegex(ContentPortError, message):
                    load_port(root, root / "donors")

    def test_content_addressed_predecessor_chain_reaches_genesis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = self.make_port(root)
            first_digest, _ = self.attach_migration(root, port)
            donor = root / "donors/mechanical"
            first = identify_tree(donor)
            first_tree = root / "first-pin"
            subprocess.run(
                (
                    "git",
                    "-C",
                    str(donor),
                    "worktree",
                    "add",
                    "-q",
                    "--detach",
                    str(first_tree),
                    first.commit,
                ),
                check=True,
            )
            (donor / "evidence.txt").write_text("newer\n")
            subprocess.run(("git", "add", "."), cwd=donor, check=True)
            subprocess.run(
                ("git", "commit", "-q", "-m", "newer"), cwd=donor, check=True
            )
            second = identify_tree(donor)
            report = build_migration(
                donor="mechanical",
                repository="example/mechanical",
                old_tree=first_tree,
                new_tree=donor,
                tests=(
                    {"command": list(command), "result": "passed"}
                    for command in REQUIRED_REVIEW_COMMANDS
                ),
                predecessor=first_digest,
            )
            report["decision"] = "reviewed"
            second_digest = migration_digest(report)
            (root / "migrations" / f"{second_digest}.json").write_bytes(
                canonical_bytes(report)
            )
            pin = port["donors"]["mechanical"]  # type: ignore[index]
            pin.update(
                commit=second.commit,
                treeDigest=second.digest,
                fileCount=second.file_count,
                migration=second_digest,
            )
            dump(root / "port.json", port)
            descriptor = load_port(root, root / "donors")
            self.assertEqual(descriptor.donors[0].migration, second_digest)

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
                "migration target pin is stale",
            ),
            (
                lambda report, pin: report["from"].update(commit=pin["commit"]),
                "commit chain is a no-op",
            ),
            (
                lambda report, _pin: report.update(tests=[]),
                "required donor migration commands are missing",
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
