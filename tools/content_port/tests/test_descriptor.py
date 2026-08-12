from __future__ import annotations

import copy
import json
import re
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from tools.content_port.descriptor import (
    ADAPTATION_KEYS,
    GENERATED_AUTHORITY_CONTRACT,
    load_port,
    read_json,
)
from tools.content_port.errors import ContentPortError
from tools.content_port.update import (
    REQUIRED_REVIEW_COMMANDS,
    _derive_authored_policy_snapshot,
    _publication_policy_snapshot,
    _validate_publication_policy_binding,
    build_migration,
    canonical_bytes,
    identify_tree,
    migration_digest,
)

from tools.content_port.tests.test_allocations import allocation_document


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class DescriptorTests(unittest.TestCase):
    @staticmethod
    def adaptation_policy_cases():
        digest = "a" * 64
        return (
            (
                "donorFieldRoles",
                {"content": "content", "mechanical": "mechanical"},
                "content",
                "mechanical",
                7,
                "$.donorFieldRoles",
                "mechanical",
            ),
            (
                "adaptations",
                {
                    "source": "TestMap",
                    "path": "warp_events/0/dest_map",
                    "content": "MAP_OLD",
                    "mechanical": "MAP_NEW",
                    "reason": "reviewed correction",
                },
                "reason",
                "source",
                7,
                "$.adaptations[0]",
                "source",
            ),
            (
                "layoutHeaderDecisions",
                {
                    "layout": "LAYOUT_TEST",
                    "field": "secondary_tileset",
                    "content": "gTileset_Old",
                    "mechanical": "gTileset_New",
                    "authority": "mechanical",
                },
                "field",
                "layout",
                [],
                "$.layoutHeaderDecisions[0]",
                "layout",
            ),
            (
                "mapFieldDecisions",
                {
                    "map": "TestMap",
                    "field": "region_map_section",
                    "content": "MAPSEC_OLD",
                    "mechanical": "MAPSEC_NEW",
                    "authority": "mechanical",
                },
                "field",
                "map",
                None,
                "$.mapFieldDecisions[0]",
                "map",
            ),
            (
                "sectionSymbolRemaps",
                {
                    "source": "MAPSEC_OLD",
                    "target": "MAPSEC_NEW",
                    "reason": "avoid collision",
                },
                "reason",
                "target",
                False,
                "$.sectionSymbolRemaps[0]",
                "target",
            ),
            (
                "layoutTilesetRemaps",
                {
                    "layout": "LAYOUT_TEST",
                    "field": "secondary_tileset",
                    "source": "gTileset_Old",
                    "target": "gTileset_New",
                },
                "target",
                "field",
                3,
                "$.layoutTilesetRemaps[0]",
                "field",
            ),
            (
                "attributeFixtures",
                {
                    "representative": "test-primary",
                    "layout": "LAYOUT_TEST",
                    "role": "primary",
                    "tileset": "gTileset_Test",
                    "metatiles": "data/tilesets/test/metatiles.bin",
                    "attributes": "data/tilesets/test/attributes.bin",
                    "metatilesSha256": digest,
                    "attributesSha256": digest,
                    "format": "METATILE_ATTRIBUTES_EMERALD_U16",
                    "authority": "content",
                },
                "format",
                "metatilesSha256",
                "not-a-digest",
                "$.attributeFixtures[0]",
                "metatilesSha256",
            ),
            (
                "contentFallback",
                {
                    "authority": "mechanical",
                    "reason": "content donor is missing the map",
                    "maps": [],
                },
                "reason",
                "maps",
                [7],
                "$.contentFallback",
                "maps[0]",
            ),
            (
                "retainedEdges",
                {
                    "source": "TestMap",
                    "path": "warp_events/0",
                    "kind": "warp",
                    "destination": "MAP_OTHER",
                },
                "destination",
                "kind",
                7,
                "$.retainedEdges[0]",
                "kind",
            ),
            (
                "deferredEdges",
                {
                    "source": "TestMap",
                    "path": "connections/0",
                    "kind": "connection",
                    "destination": "MAP_OTHER",
                },
                "destination",
                "path",
                [],
                "$.deferredEdges[0]",
                "path",
            ),
            (
                "graphicsAdaptations",
                {"content": "OBJ_EVENT_GFX_OLD", "target": "OBJ_EVENT_GFX_NEW"},
                "target",
                "content",
                7,
                "$.graphicsAdaptations[0]",
                "content",
            ),
            (
                "musicAdaptations",
                {"content": "MUS_OLD", "target": "MUS_NEW"},
                "target",
                "content",
                None,
                "$.musicAdaptations[0]",
                "content",
            ),
            (
                "tilesetAdaptations",
                {
                    "role": "primary",
                    "directory": "test",
                    "symbol": "Test",
                    "secondary": False,
                    "paletteCount": 16,
                    "authority": "content",
                },
                "directory",
                "secondary",
                "false",
                "$.tilesetAdaptations[0]",
                "secondary",
            ),
            (
                "trainerPresentation",
                {
                    "id": "TRAINER_TEST",
                    "name": "Test",
                    "class": "Rival",
                    "pic": "Wally",
                    "gender": "Male",
                    "music": "Male",
                    "battleType": "Singles",
                    "species": "Chikorita",
                    "level": 5,
                    "ivs": "0 HP",
                },
                "ivs",
                "level",
                0,
                "$.trainerPresentation[0]",
                "level",
            ),
            (
                "trainerProjections",
                {
                    "source": "TRAINER_TEST",
                    "target": "TRAINER_TARGET",
                    "class": {"source": "TRAINER_CLASS_TEST", "target": "Ace"},
                    "pic": {"source": "TRAINER_PIC_TEST", "target": "Ace"},
                    "gender": "Male",
                    "music": {
                        "source": "TRAINER_ENCOUNTER_MUSIC_TEST",
                        "target": "Male",
                    },
                    "ai": [{"source": "AI_TEST", "target": "Basic Trainer"}],
                },
                "gender",
                "ai",
                [],
                "$.trainerProjections[0]",
                "ai",
            ),
            (
                "warpReindexes",
                {
                    "source": "TestMap",
                    "path": "warp_events/0/dest_warp_id",
                    "to": 1,
                },
                "to",
                "to",
                [],
                "$.warpReindexes[0]",
                "to",
            ),
            (
                "warpRemovals",
                {
                    "source": "TestMap",
                    "path": "warp_events/0",
                    "destination": "MAP_OTHER",
                    "destWarpId": "0",
                    "reason": "deferred exit",
                },
                "reason",
                "destWarpId",
                0,
                "$.warpRemovals[0]",
                "destWarpId",
            ),
            (
                "berryTreeAllocations",
                {
                    "source": "TestMap",
                    "path": "object_events/0/trainer_sight_or_berry_tree_id",
                    "content": "BERRY_TREE_OLD",
                    "target": "BERRY_TREE_TEST",
                },
                "target",
                "content",
                {},
                "$.berryTreeAllocations[0]",
                "content",
            ),
            (
                "materializationProfile",
                {
                    "mapScripts": "empty",
                    "stripEventKinds": [
                        "bg_events",
                        "coord_events",
                        "object_events",
                    ],
                },
                "mapScripts",
                "stripEventKinds",
                False,
                "$.materializationProfile",
                "stripEventKinds",
            ),
            (
                "worldPolicy",
                {
                    "roots": ["TestMap"],
                    "unreachableShells": [],
                    "gateways": [],
                    "dynamicWarps": [],
                },
                "roots",
                "roots",
                [7],
                "$.worldPolicy",
                "roots[0]",
            ),
            (
                "worldGateway",
                {
                    "source": "TestMap",
                    "destination": "OtherMap",
                    "kind": "warp",
                    "index": 0,
                    "sourceRegion": "REGION_TEST",
                    "targetRegion": "REGION_OTHER",
                },
                "targetRegion",
                "index",
                True,
                "$.worldPolicy.gateways[0]",
                "index",
            ),
            (
                "worldDynamicWarp",
                {"source": "TestMap", "index": 0, "token": "WARP_ID_DYNAMIC"},
                "token",
                "index",
                True,
                "$.worldPolicy.dynamicWarps[0]",
                "index",
            ),
        )

    @staticmethod
    def install_adaptation_family(
        document: dict[str, object], family: str, sample: object
    ) -> object:
        if family == "worldGateway":
            document["worldPolicy"]["gateways"] = [sample]  # type: ignore[index]
            return document["worldPolicy"]["gateways"][0]  # type: ignore[index]
        if family == "worldDynamicWarp":
            document["worldPolicy"]["dynamicWarps"] = [sample]  # type: ignore[index]
            return document["worldPolicy"]["dynamicWarps"][0]  # type: ignore[index]
        if isinstance(document[family], list):
            document[family] = [sample]
            return document[family][0]  # type: ignore[index]
        document[family] = sample
        return document[family]

    def test_checked_port_declares_every_map_and_capability(self):
        port_dir = Path(__file__).parents[1] / "ports" / "johto"
        descriptor = load_port(port_dir, port_dir / "unused-donor-root")
        self.assertEqual(len(descriptor.allocation_index.maps), 254)
        self.assertEqual(len(descriptor.map_ownership), 254)
        self.assertEqual(len(descriptor.capabilities), 254 * 12)
        self.assertEqual(list(descriptor.map_ownership.values()).count("preserve"), 17)
        state_counts: dict[str, int] = {}
        for decision in descriptor.capabilities:
            state_counts[decision.state.value] = (
                state_counts.get(decision.state.value, 0) + 1
            )
        self.assertEqual(
            state_counts,
            {"enabled": 510, "deferred": 2368, "story-owned": 170},
        )
        self.assertEqual(
            {
                domain: item["count"]
                for domain, item in descriptor.expected_inventory.items()
            },
            {"maps": 254, "layouts": 255, "groups": 25, "sections": 58, "tilesets": 71},
        )

    def test_encounter_materialization_and_time_policy_fail_closed(self):
        profile = {
            "map": "TestMap",
            "label": "gTestMap",
            "habitat": "land_mons",
            "authority": "content",
            "time": "TIME_DAY",
        }
        night = {**profile, "label": "gTestMap_Night", "time": "TIME_NIGHT"}
        time_policy = {
            "map": "TestMap",
            "dayStart": "06:00",
            "nightStart": "18:00",
            "dayLabel": "gTestMap",
            "nightLabel": "gTestMap_Night",
            "fallbackLabel": "gTestMap",
        }
        cases = (
            (
                lambda profiles, policy: profiles[0].update(habitat="water_mons"),
                "only land_mons",
            ),
            (
                lambda profiles, policy: profiles[0].update(authority="missing"),
                "unknown donor role",
            ),
            (
                lambda profiles, policy: profiles[0].update(time="TIME_MORNING"),
                "expected TIME_DAY or TIME_NIGHT",
            ),
            (
                lambda profiles, policy: policy.update(dayStart="07:00"),
                "06:00 through 17:59",
            ),
            (
                lambda profiles, policy: policy.update(fallbackLabel="gTestMap_Night"),
                "do not match profiles",
            ),
            (
                lambda profiles, policy: profiles.append(copy.deepcopy(profiles[0])),
                "duplicate encounter profile",
            ),
            (
                lambda profiles, policy: profiles.append(
                    {
                        **copy.deepcopy(profiles[0]),
                        "map": "OtherMap",
                        "label": "gUnconsumedEncounter",
                    }
                ),
                "exactly match enabled encounter dependencies",
            ),
        )
        for mutation, message in cases:
            with (
                self.subTest(message=message),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                self.make_port(root)
                capability_path = root / "capabilities.json"
                capability_document = read_json(capability_path)
                capability_document["capabilities"].append("encounters")
                capability_document["maps"][0]["capabilities"]["encounters"] = {
                    "state": "enabled",
                    "dependencies": [
                        {"domain": "encounter", "name": "gTestMap"},
                        {"domain": "encounter", "name": "gTestMap_Night"},
                    ],
                }
                dump(capability_path, capability_document)
                path = root / "adaptations.json"
                document = read_json(path)
                profiles = [copy.deepcopy(profile), copy.deepcopy(night)]
                policy = copy.deepcopy(time_policy)
                mutation(profiles, policy)
                document["encounterProfiles"] = profiles
                document["encounterTimePolicy"] = [policy]
                dump(path, document)
                with self.assertRaisesRegex(ContentPortError, message):
                    load_port(root, root / "donors")

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
        adaptations.update(
            {
                "schemaVersion": 1,
                "donorFieldRoles": {
                    "content": "content",
                    "mechanical": "mechanical",
                },
                "contentFallback": {
                    "authority": "mechanical",
                    "reason": "content donor has no fallback maps",
                    "maps": [],
                },
                "materializationProfile": {
                    "mapScripts": "empty",
                    "stripEventKinds": [
                        "bg_events",
                        "coord_events",
                        "object_events",
                    ],
                },
                "worldPolicy": {
                    "roots": ["TestMap"],
                    "unreachableShells": [],
                    "gateways": [],
                    "dynamicWarps": [],
                },
            }
        )
        adaptations["layoutBinaryAuthorities"] = [
            {
                "layout": "LAYOUT_TEST",
                "source": "TestMap",
                "sourceRole": "content",
            }
        ]
        adaptations["layoutFieldAuthorities"] = [
            {
                "field": field,
                "layoutRole": "content",
                "sourceRole": "mechanical",
            }
            for field in ("border_height", "border_width")
        ]
        adaptations["generatedSections"] = [
            {
                "authorities": list(GENERATED_AUTHORITY_CONTRACT[symbol]),
                "key": key,
                "path": path,
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
        dump(
            root / "events.json",
            {"schemaVersion": 1, "entries": [], "effects": []},
        )
        dump(
            root / "assets.json",
            {"schemaVersion": 1, "permissionRecords": {}, "assets": []},
        )
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

    def test_non_legacy_port_does_not_require_migration_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = self.make_port(root)
            port.pop("legacyReport")
            dump(root / "port.json", port)

            descriptor = load_port(root, root / "donors")

            self.assertIsNone(descriptor.legacy_report)
            self.assertEqual(descriptor.target_bindings.region, "REGION_TEST")

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
            self.assertEqual(len(descriptor.layout_field_authorities), 2)
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
                    layoutFieldAuthorities=document["layoutFieldAuthorities"][:-1]
                ),
                "missing field 'border_width'",
            ),
            (
                lambda document: document["generatedSections"][2].update(
                    authorities=["mechanical"]
                ),
                "must exactly match generated source contract",
            ),
            (
                lambda document: document["generatedSections"][2].update(
                    sourceRole="mechanical"
                ),
                "unknown field 'sourceRole'",
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
                lambda document: document["materializationProfile"].update(
                    retainEventKinds=["warp_events"]
                ),
                "unknown field 'retainEventKinds'",
            ),
            (
                lambda document: document["materializationProfile"].update(
                    encounters=False
                ),
                "unknown field 'encounters'",
            ),
            (
                lambda document: document["materializationProfile"].update(
                    gameplayGlobals=False
                ),
                "unknown field 'gameplayGlobals'",
            ),
            (
                lambda document: document["materializationProfile"].update(
                    mapScripts="copy"
                ),
                "unsupported map script profile",
            ),
            (
                lambda document: document["materializationProfile"].update(
                    stripEventKinds=["bogus_events"]
                ),
                "unsupported event kind 'bogus_events'",
            ),
            (
                lambda document: document["materializationProfile"].update(
                    stripEventKinds=["object_events", "bg_events"]
                ),
                "must exactly strip",
            ),
            (
                lambda document: document["materializationProfile"].update(
                    stripEventKinds=["object_events", "object_events"]
                ),
                "must exactly strip",
            ),
            (
                lambda document: document["materializationProfile"].update(
                    stripEventKinds=["bg_events", "coord_events"]
                ),
                "must exactly strip",
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

    def test_trainer_projection_render_tokens_reject_header_injection(self):
        sample = next(
            item
            for family, item, *_ in self.adaptation_policy_cases()
            if family == "trainerProjections"
        )
        cases = (
            (
                "identity",
                lambda item: item.update(
                    target="TRAINER_TARGET\n=== TRAINER_UNSELECTED ==="
                ),
            ),
            (
                "class",
                lambda item: item["class"].update(target="Youngster\nName: Injected"),
            ),
            (
                "ai",
                lambda item: item["ai"][0].update(
                    target="Check Bad Move\n=== TRAINER_UNSELECTED ==="
                ),
            ),
        )
        for label, mutate in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_port(root)
                path = root / "adaptations.json"
                document = read_json(path)
                document["trainerProjections"] = [copy.deepcopy(sample)]
                mutate(document["trainerProjections"][0])
                dump(path, document)
                with self.assertRaisesRegex(
                    ContentPortError, "invalid trainer projection value"
                ):
                    load_port(root, root / "donors")

    def test_every_adaptation_family_rejects_unknown_fields(self):
        typo = "reviewedButTypoedField"
        for (
            family,
            sample,
            _missing,
            _field,
            _bad,
            pointer,
            _type_path,
        ) in self.adaptation_policy_cases():
            with (
                self.subTest(family=family),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                self.make_port(root)
                path = root / "adaptations.json"
                document = read_json(path)
                target = self.install_adaptation_family(
                    document,
                    family,
                    copy.deepcopy(sample),  # type: ignore[arg-type]
                )
                target[typo] = True  # type: ignore[index]
                dump(path, document)

                message = re.escape(f"{pointer}: unknown field {typo!r}")
                with self.assertRaisesRegex(ContentPortError, message):
                    load_port(root, root / "donors")

    def test_every_adaptation_family_rejects_missing_fields(self):
        for (
            family,
            sample,
            missing,
            _field,
            _bad,
            pointer,
            _type_path,
        ) in self.adaptation_policy_cases():
            with (
                self.subTest(family=family),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                self.make_port(root)
                path = root / "adaptations.json"
                document = read_json(path)
                target = self.install_adaptation_family(
                    document,
                    family,
                    copy.deepcopy(sample),  # type: ignore[arg-type]
                )
                target.pop(missing)  # type: ignore[union-attr]
                dump(path, document)

                message = re.escape(f"{pointer}: missing field {missing!r}")
                with self.assertRaisesRegex(ContentPortError, message):
                    load_port(root, root / "donors")

    def test_every_adaptation_family_rejects_ill_typed_fields(self):
        for (
            family,
            sample,
            _missing,
            field,
            bad,
            pointer,
            type_path,
        ) in self.adaptation_policy_cases():
            with (
                self.subTest(family=family),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                self.make_port(root)
                path = root / "adaptations.json"
                document = read_json(path)
                target = self.install_adaptation_family(
                    document,
                    family,
                    copy.deepcopy(sample),  # type: ignore[arg-type]
                )
                target[field] = bad  # type: ignore[index]
                dump(path, document)

                message = re.escape(f"{pointer}.{type_path}:")
                with self.assertRaisesRegex(ContentPortError, message):
                    load_port(root, root / "donors")

    def test_tileset_target_aliases_are_an_exact_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_port(root)
            path = root / "adaptations.json"
            document = read_json(path)
            document["tilesetAdaptations"] = [  # type: ignore[index]
                {
                    "role": "secondary",
                    "directory": "test",
                    "symbol": "Test",
                    "targetSymbol": "PortTest",
                    "secondary": True,
                    "paletteCount": 16,
                    "authority": "content",
                }
            ]
            dump(path, document)

            with self.assertRaisesRegex(
                ContentPortError,
                re.escape("$.tilesetAdaptations[0]: missing field 'targetDirectory'"),
            ):
                load_port(root, root / "donors")

    def test_transform_and_identity_records_reject_duplicates(self):
        samples = {
            family: sample for family, sample, *_rest in self.adaptation_policy_cases()
        }
        cases = (
            ("adaptations", "path"),
            ("layoutHeaderDecisions", "field"),
            ("mapFieldDecisions", "field"),
            ("sectionSymbolRemaps", "source"),
            ("layoutTilesetRemaps", "field"),
            ("attributeFixtures", "representative"),
            ("retainedEdges", "path"),
            ("deferredEdges", "path"),
            ("graphicsAdaptations", "content"),
            ("musicAdaptations", "content"),
            ("tilesetAdaptations", "symbol"),
            ("trainerPresentation", "id"),
            ("trainerProjections", "source"),
            ("warpReindexes", "path"),
            ("warpRemovals", "path"),
            ("berryTreeAllocations", "path"),
            ("worldGateway", "index"),
            ("worldDynamicWarp", "index"),
        )
        for family, identity_field in cases:
            with (
                self.subTest(family=family),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                self.make_port(root)
                path = root / "adaptations.json"
                document = read_json(path)
                sample = copy.deepcopy(samples[family])
                self.install_adaptation_family(document, family, sample)
                if family == "worldGateway":
                    records = document["worldPolicy"]["gateways"]  # type: ignore[index]
                    pointer = "$.worldPolicy.gateways[1]"
                elif family == "worldDynamicWarp":
                    records = document["worldPolicy"]["dynamicWarps"]  # type: ignore[index]
                    pointer = "$.worldPolicy.dynamicWarps[1]"
                else:
                    records = document[family]
                    pointer = f"$.{family}[1]"
                records.append(copy.deepcopy(sample))  # type: ignore[union-attr]
                dump(path, document)

                with self.assertRaisesRegex(
                    ContentPortError,
                    re.escape(f"{pointer}.{identity_field}:"),
                ):
                    load_port(root, root / "donors")

    def test_edge_classifications_and_transform_paths_are_exclusive(self):
        cases = (
            (
                "retainedEdges",
                {
                    "source": "TestMap",
                    "path": "warp_events/0",
                    "kind": "warp",
                    "destination": "MAP_OTHER",
                },
                "deferredEdges",
                {
                    "source": "TestMap",
                    "path": "warp_events/0",
                    "kind": "warp",
                    "destination": "MAP_OTHER",
                },
                "$.deferredEdges[0].path: edge is already classified",
            ),
            (
                "adaptations",
                {
                    "source": "TestMap",
                    "path": "warp_events/0/dest_warp_id",
                    "content": "0",
                    "mechanical": "1",
                    "reason": "reviewed correction",
                },
                "warpReindexes",
                {
                    "source": "TestMap",
                    "path": "warp_events/0/dest_warp_id",
                    "to": 1,
                },
                "$.warpReindexes[0].path: transform path is already declared",
            ),
        )
        for first_family, first, second_family, second, message in cases:
            with (
                self.subTest(first=first_family, second=second_family),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                self.make_port(root)
                path = root / "adaptations.json"
                document = read_json(path)
                self.install_adaptation_family(document, first_family, first)
                self.install_adaptation_family(document, second_family, second)
                dump(path, document)

                with self.assertRaisesRegex(ContentPortError, re.escape(message)):
                    load_port(root, root / "donors")

    def test_loads_exact_reviewed_content_addressed_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = self.make_port(root)
            digest, _report = self.attach_migration(root, port)
            descriptor = load_port(root, root / "donors")
            self.assertEqual(descriptor.donors[0].migration, digest)

    def test_legacy_migration_preflights_every_donor_root_before_git(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = self.make_port(root)
            _digest, report = self.attach_migration(root, port)
            self.assertEqual(report["schemaVersion"], 1)

            outside = root / "outside-content"
            outside.mkdir()
            marker = outside / "marker"
            marker.write_text("unchanged\n", encoding="utf-8")
            (root / "donors/content").symlink_to(outside, target_is_directory=True)

            with (
                mock.patch("tools.content_port.update._run_git") as run_git,
                mock.patch(
                    "tools.content_port.update.tempfile.TemporaryDirectory"
                ) as temporary_directory,
                self.assertRaisesRegex(ContentPortError, "symbolic link"),
            ):
                load_port(root, root / "donors")

            run_git.assert_not_called()
            temporary_directory.assert_not_called()
            self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged\n")

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
            first_digest, first_report = self.attach_migration(root, port)
            first_path = root / "migrations" / f"{first_digest}.json"
            first_path.unlink()
            semantic_reference = {
                "authority": "mechanical",
                "newHash": "b" * 64,
                "oldHash": "a" * 64,
                "recordType": "semantic-evidence",
                "semanticIdentity": "binding:Fixture",
                "sourcePath": "semantic-evidence/binding/Fixture",
            }
            first_report["policy"]["references"] = [semantic_reference]
            first_report["authorityChanges"] = [
                {
                    "authority": "mechanical",
                    "jsonPointer": None,
                    "newHash": "b" * 64,
                    "oldHash": "a" * 64,
                    "reviewerDisposition": "accepted",
                    "semanticIdentity": "binding:Fixture",
                    "sourcePath": "semantic-evidence/binding/Fixture",
                }
            ]
            first_descriptor = copy.deepcopy(port)
            first_source_record = first_descriptor["donors"]["mechanical"]  # type: ignore[index]
            first_source_record.update(first_report["from"])
            first_source_record["migration"] = None
            first_snapshot = _publication_policy_snapshot(
                root,
                first_descriptor,
                "mechanical",
                authored_policy=_derive_authored_policy_snapshot(
                    root, first_descriptor, "mechanical", evidence_root=root
                ),
            )
            first_report["schemaVersion"] = 2
            first_report["publicationPolicySnapshot"] = first_snapshot
            first_report["publicationPolicyDigest"] = migration_digest(first_snapshot)
            first_digest = migration_digest(first_report)
            (root / "migrations" / f"{first_digest}.json").write_bytes(
                canonical_bytes(first_report)
            )
            port["donors"]["mechanical"]["migration"] = first_digest  # type: ignore[index]
            dump(root / "port.json", port)
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
            pin = port["donors"]["mechanical"]  # type: ignore[index]
            # The new head captures unrelated donor and policy evolution. The
            # predecessor must remain verifiable from its embedded context.
            port["donors"]["content"]["commit"] = "9" * 40  # type: ignore[index]
            port["donors"]["content"]["genesis"]["commit"] = "9" * 40  # type: ignore[index]
            adaptations = json.loads((root / "adaptations.json").read_text())
            adaptations["contentFallback"]["reason"] = "evolved unrelated policy"
            dump(root / "adaptations.json", adaptations)
            second_descriptor = copy.deepcopy(port)
            second_source_record = second_descriptor["donors"]["mechanical"]  # type: ignore[index]
            second_source_record.update(report["from"])
            second_source_record["migration"] = first_digest
            second_snapshot = _publication_policy_snapshot(
                root,
                second_descriptor,
                "mechanical",
                authored_policy=_derive_authored_policy_snapshot(
                    root, second_descriptor, "mechanical", evidence_root=root
                ),
            )
            report["schemaVersion"] = 2
            report["publicationPolicySnapshot"] = second_snapshot
            report["publicationPolicyDigest"] = migration_digest(second_snapshot)
            second_digest = migration_digest(report)
            (root / "migrations" / f"{second_digest}.json").write_bytes(
                canonical_bytes(report)
            )
            pin.update(
                commit=second.commit,
                treeDigest=second.digest,
                fileCount=second.file_count,
                migration=second_digest,
            )
            dump(root / "port.json", port)
            historical_contexts: list[tuple[str, str]] = []

            def semantic_evidence(
                repo: Path,
                snapshot_port: Path,
                donor_root: Path,
                donor_role: str,
                selected_pin: dict[str, object],
                *,
                port_document: dict[str, object],
            ) -> dict[str, str]:
                policy = json.loads((snapshot_port / "adaptations.json").read_text())
                auxiliary = port_document["donors"]["content"]["commit"]  # type: ignore[index]
                historical_contexts.append(
                    (policy["contentFallback"]["reason"], auxiliary)
                )
                value = (
                    "a" * 64
                    if selected_pin["commit"] == first_report["from"]["commit"]
                    else "b" * 64
                )
                return {"mechanical:binding:Fixture": value}

            with mock.patch(
                "tools.content_port.update._semantic_evidence_at_pin",
                side_effect=semantic_evidence,
            ):
                descriptor = load_port(root, root / "donors")
            self.assertEqual(descriptor.donors[0].migration, second_digest)
            self.assertEqual(
                historical_contexts,
                [
                    ("content donor has no fallback maps", "3" * 40),
                    ("content donor has no fallback maps", "3" * 40),
                ],
            )

    def test_live_heads_ignore_cross_donor_update_order(self):
        for ordering in (("mechanical", "content"), ("content", "mechanical")):
            with (
                self.subTest(ordering=ordering),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                port = self.make_port(root)
                reports: dict[str, dict[str, object]] = {}
                for index, role in enumerate(ordering, start=6):
                    record = port["donors"][role]  # type: ignore[index]
                    source = {
                        field: record[field]
                        for field in ("commit", "fileCount", "treeDigest")
                    }
                    target = {
                        "commit": str(index) * 40,
                        "fileCount": index,
                        "treeDigest": str(index + 1) * 64,
                    }
                    snapshot = _publication_policy_snapshot(
                        root,
                        port,
                        role,
                        authored_policy=_derive_authored_policy_snapshot(
                            root, port, role, evidence_root=root
                        ),
                    )
                    report: dict[str, object] = {
                        "donor": role,
                        "from": source,
                        "predecessor": record["migration"],
                        "publicationPolicyDigest": migration_digest(snapshot),
                        "publicationPolicySnapshot": snapshot,
                        "schemaVersion": 2,
                        "to": target,
                    }
                    record.update(target)
                    record["migration"] = migration_digest(report)
                    reports[role] = report
                dump(root / "port.json", port)

                for role in ordering:
                    _validate_publication_policy_binding(
                        reports[role], root, evidence_root=root
                    )

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
            events = {
                "schemaVersion": 1,
                "entries": [{"targetId": 7}],
                "effects": [],
            }
            dump(root / "events.json", events)
            with self.assertRaisesRegex(
                ContentPortError, "numeric placement belongs in allocation_lock.json"
            ):
                load_port(root, root / "missing-donors")

    def test_event_policy_cross_references_capability_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = (
                (
                    {
                        "schemaVersion": 1,
                        "entries": [
                            {
                                "name": "Entry",
                                "capability": "spatail",
                                "classification": "enabled",
                            }
                        ],
                        "effects": [],
                    },
                    "unknown capability 'spatail'",
                ),
                (
                    {
                        "schemaVersion": 1,
                        "entries": [
                            {
                                "name": "Entry",
                                "capability": "spatial",
                                "classification": "story-owned",
                            }
                        ],
                        "effects": [],
                    },
                    "classification 'story-owned' is stale",
                ),
                (
                    {
                        "schemaVersion": 1,
                        "entries": [],
                        "effects": [
                            {
                                "kind": "state-read",
                                "command": "checkflag",
                                "operand": "FLAG_TEST",
                                "owner": "spatail",
                            }
                        ],
                    },
                    "unknown owner 'spatail'",
                ),
            )
            for document, message in cases:
                with self.subTest(message=message):
                    self.make_port(root)
                    dump(root / "events.json", document)
                    with self.assertRaisesRegex(ContentPortError, message):
                        load_port(root, root)

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
