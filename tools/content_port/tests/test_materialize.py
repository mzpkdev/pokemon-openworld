from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest.mock import patch

from tools.content_port.descriptor import load_port
from tools.content_port.allocations import AllocationIndex
from tools.content_port.donors import records_digest, source_tree_records
from tools.content_port.errors import ContentPortError
from tools.content_port.materialize import (
    _asset_units,
    _encounter_units,
    _group_units,
    _generated_body,
    _layout_units,
    _map_units,
    _section_units,
    _trainer_units,
    derive_desired_state,
    derive_released_map_files,
)
from tools.content_port.model import DonorPin, PersistentBindingRef
from tools.content_port.ownership import (
    OwnershipManifest,
    OwnershipUnit,
    extract_owned_content,
    reconcile_owned,
)
from tools.content_port.renderers import RenderContext, render_units
from tools.content_port.sources import resolve_port_sources


ROOT = Path(__file__).resolve().parents[3]
PORT = ROOT / "tools/content_port/ports/johto"

LATE_JOHTO_LOCATION_COMPATIBILITY = {
    "MAPSEC_BLACKTHORN_CITY": (
        "MAPSEC_BLACKTHORN_CITY",
        249,
        "MAPSEC_ROUTE_44",
    ),
    "MAPSEC_ROUTE_45": ("MAPSEC_ROUTE_45", 249, "MAPSEC_ROUTE_44"),
    "MAPSEC_ROUTE_46": ("MAPSEC_ROUTE_46", 210, "MAPSEC_ROUTE_29"),
    "MAPSEC_ICE_PATH": ("MAPSEC_ROUTE_44", 249, "MAPSEC_ROUTE_44"),
    "MAPSEC_DRAGONS_DEN": ("MAPSEC_ROUTE_44", 249, "MAPSEC_ROUTE_44"),
    "MAPSEC_DARK_CAVE": ("MAPSEC_ROUTE_31", 215, "MAPSEC_ROUTE_31"),
    "MAPSEC_ROUTE_26": ("MAPSEC_ROUTE_28", 212, "MAPSEC_ROUTE_28"),
    "MAPSEC_ROUTE_27": ("MAPSEC_NEW_BARK_TOWN", 209, "MAPSEC_NEW_BARK_TOWN"),
    "MAPSEC_TOHJO_FALLS": (
        "MAPSEC_NEW_BARK_TOWN",
        209,
        "MAPSEC_NEW_BARK_TOWN",
    ),
}

LATE_JOHTO_LOCATION_OWNERSHIP_HASHES = {
    "MAPSEC_BLACKTHORN_CITY": (
        "b22dfb624554d0ae0f20a6c474cb8a74af75919d148512e5f2509c5f3dded0f8",
        "16ab70106cd693b054172c6b1a7eae0590b5493fc863dc79002de6c1db9d1be8",
    ),
    "MAPSEC_DARK_CAVE": (
        "d607fceab94c6f58ee9e3657c3f878f28ccb55b1a698c0f86bf91d26b930494d",
        "388f9481d1af877f27200810b9b62edc32437d6abb40f85fe7e64fcf53042fb0",
    ),
    "MAPSEC_DRAGONS_DEN": (
        "c9083f38be148125a2ea8b1163bde456392702c0a7fb25560b3fdd266adea8bc",
        "7c37ad4d521f00c6329fc547334095aa6016b3a22f943eb77f1bdba89d21d645",
    ),
    "MAPSEC_ICE_PATH": (
        "6828dd19c3592ffee1028c1ad5023b1b4ddb92e9e55cb4926e06e4ebe5b5292b",
        "7d8c726b29ac892a873a3d9f97fbfa9affc9d8e2b1c7c5a21bdc0a221c7d3151",
    ),
    "MAPSEC_ROUTE_26": (
        "ce284cb09db820f736f9436b351d1e3bb3cf078f6982eb406fda5af50925885f",
        "aa1260d784fca27f3de4a70f358c4f127cf6bc0b3e51e1277123f3f5b15b2d6d",
    ),
    "MAPSEC_ROUTE_27": (
        "cfe39fcd79bbe29ca983a1eab56febc03cbb6873ce24e9922e12edbc388f603f",
        "c11b0c74ff080df15e6da131cc1947cee066c5feea3016838fe8c62cc4c4efc1",
    ),
    "MAPSEC_ROUTE_45": (
        "8c158d66d17120fcc07428fc2d8da5ba778b0d2eb7db4543f75d7c563d17144f",
        "88beaaf4f9ba8eb46deb43e6da57fec45311054576572f356c673f13743105c7",
    ),
    "MAPSEC_ROUTE_46": (
        "707f1e8b32fa62b9381c340bb10b68a90a135b59bd8961541a3617b257fb9eaa",
        "f0f1aa1f66c93a2ed011c3ddb035e3c4aa8dd40359250362b1602d8c86bc8ced",
    ),
    "MAPSEC_TOHJO_FALLS": (
        "6bacac6beba838982a9deeec051d047fade005356a0f1d6294e6b049557019dc",
        "872dbea038bd926624a46d9855fa5232c3528e94d64338469295b4564e1130a6",
    ),
}

PRE_CODEC_SAVED_LOCATIONS = {
    "MAPSEC_BLACKTHORN_CITY": "MAPSEC_BLACKTHORN_CITY",
    "MAPSEC_ROUTE_45": "MAPSEC_ROUTE_45",
    "MAPSEC_ROUTE_46": "MAPSEC_ROUTE_46",
    "MAPSEC_ICE_PATH": None,
    "MAPSEC_DRAGONS_DEN": None,
    "MAPSEC_DARK_CAVE": None,
    "MAPSEC_ROUTE_26": None,
    "MAPSEC_ROUTE_27": None,
    "MAPSEC_TOHJO_FALLS": None,
}


def _with_pre_location_refresh_hashes(
    manifest: OwnershipManifest,
) -> OwnershipManifest:
    return OwnershipManifest(
        port=manifest.port,
        units=tuple(
            replace(
                unit,
                sha256=LATE_JOHTO_LOCATION_OWNERSHIP_HASHES[unit.key][0],
            )
            if (
                unit.path == "src/data/region_map/region_map_sections.json"
                and unit.registry == "map_sections"
                and unit.key in LATE_JOHTO_LOCATION_OWNERSHIP_HASHES
            )
            else unit
            for unit in manifest.units
        ),
        schema_version=manifest.schema_version,
    )


def _restore_pre_codec_location_records(root: Path) -> None:
    path = root / "src/data/region_map/region_map_sections.json"
    document = json.loads(path.read_text())
    restored = set()
    for record in document["map_sections"]:
        section = record["id"]
        if section not in PRE_CODEC_SAVED_LOCATIONS:
            continue
        record["saved_location"] = PRE_CODEC_SAVED_LOCATIONS[section]
        record["met_location"] = None
        record["met_location_display"] = None
        restored.add(section)
    if restored != set(PRE_CODEC_SAVED_LOCATIONS):
        raise AssertionError("pre-codec fixture did not find every reviewed section")
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


class MaterializeTests(unittest.TestCase):
    def descriptor(self):
        donor_root = Path(os.environ.get("CONTENT_PORT_DONOR_ROOT", ".references"))
        if not all(
            (donor_root / name).is_dir() for name in ("PKMN-World", "pokemonHnS")
        ):
            message = "authenticated donor checkouts are required for materialization"
            if os.environ.get("CONTENT_PORT_REQUIRE_DONORS") == "1":
                self.fail(message)
            self.skipTest(message)
        return load_port(PORT, donor_root)

    def test_map_preserve_policy_derives_only_ledgered_full_map_releases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = root / "tools/content_port/ports/test"
            port.mkdir(parents=True)
            owned = (
                "data/maps/Preserved/map.json",
                "data/maps/Preserved/scripts.inc",
                "data/maps/Rendered/map.json",
                "data/layouts/Preserved/map.bin",
            )
            manifest = OwnershipManifest(
                "test",
                tuple(OwnershipUnit("file", path, "0" * 64) for path in owned),
            )
            manifest.write(port / "ownership.json")
            descriptor = SimpleNamespace(
                path=port / "port.json",
                map_ownership={"Preserved": "preserve", "Rendered": "rendered"},
            )

            desired_section = OwnershipUnit(
                "section",
                "data/maps/Preserved/scripts.inc",
                "0" * 64,
                name="retained",
            )
            with self.assertRaisesRegex(
                ContentPortError, "preserved map file still has desired ownership"
            ):
                derive_released_map_files(
                    descriptor,  # type: ignore[arg-type]
                    root,
                    OwnershipManifest("test", (desired_section,)),
                )

            self.assertEqual(
                derive_released_map_files(
                    descriptor,  # type: ignore[arg-type]
                    root,
                    OwnershipManifest("test", ()),
                ),
                frozenset(
                    {
                        "data/maps/Preserved/map.json",
                        "data/maps/Preserved/scripts.inc",
                    }
                ),
            )

    def test_selected_trainers_materialize_without_activating_bystanders(
        self,
    ) -> None:
        descriptor = self.descriptor()
        self.assertNotIn("trainerProjections", descriptor.adaptations)
        _, state = resolve_port_sources(descriptor, ROOT)
        map_units = {unit.key: unit for unit in _map_units(descriptor, state)}
        route_map = map_units["map:Route34"].value
        self.assertEqual(
            [event["script"] for event in route_map["object_events"]],
            [
                "Route34_EventScript_YoungsterSamuel",
                "Route34_EventScript_PokefanMBrandon",
                "Route34_EventScript_CamperTodd",
                "Route34_EventScript_YoungsterIan",
                "Route34_EventScript_Jenn",
                "Route34_EventScript_Irene",
                "Route34_EventScript_Kate",
                "Route34_EventScript_PicnickerGina",
            ],
        )

        script = map_units["map-script:Route34"].value
        self.assertEqual(
            [event["instructions"][0]["operands"][0] for event in script["events"]],
            [
                "TRAINER_YOUNGSTER_SAMUEL_JOHTO",
                "TRAINER_POKEFAN_BRANDON_JOHTO",
                "TRAINER_CAMPER_TODD_JOHTO",
                "TRAINER_YOUNGSTER_IAN_JOHTO",
                "TRAINER_COOLTRAINER_JENN_JOHTO",
                "TRAINER_COOLTRAINER_IRENE_JOHTO",
                "TRAINER_COOLTRAINER_KATE_JOHTO",
                "TRAINER_PICNICKER_GINA_JOHTO",
            ],
        )
        route31 = map_units["map:Route31"].value
        self.assertEqual(
            route31["object_events"],
            [
                {
                    "graphics_id": "OBJ_EVENT_GFX_BUG_CATCHER",
                    "x": 27,
                    "y": 10,
                    "elevation": 0,
                    "movement_type": "MOVEMENT_TYPE_LOOK_AROUND",
                    "movement_range_x": 0,
                    "movement_range_y": 3,
                    "trainer_type": "TRAINER_TYPE_NORMAL",
                    "trainer_sight_or_berry_tree_id": "3",
                    "script": "Route31_EventScript_Bugcatcher_Wade",
                    "flag": "0",
                }
            ],
        )
        route31_script = map_units["map-script:Route31"].value
        self.assertEqual(len(route31_script["events"]), 1)
        self.assertEqual(
            route31_script["events"][0]["instructions"][0]["operands"][0],
            "TRAINER_BUG_CATCHER_WADE_JOHTO",
        )
        route30 = map_units["map:Route30"].value
        self.assertEqual(
            [event["script"] for event in route30["object_events"]],
            [
                "Route30_EventScript_Bugcatcher_Don",
                "Route30_EventScript_Youngster_Mikey",
            ],
        )
        route30_script = map_units["map-script:Route30"].value
        self.assertEqual(
            [
                event["instructions"][0]["operands"][0]
                for event in route30_script["events"]
            ],
            [
                "TRAINER_BUG_CATCHER_DON_JOHTO",
                "TRAINER_YOUNGSTER_MIKEY_JOHTO",
            ],
        )
        route33 = map_units["map:Route33"].value
        self.assertEqual(
            route33["object_events"][0]["script"],
            "Route33_EventScript_HikerAnthony",
        )
        route33_script = map_units["map-script:Route33"].value
        self.assertEqual(
            route33_script["events"][0]["instructions"][0]["operands"][0],
            "TRAINER_HIKER_ANTHONY_JOHTO",
        )
        route39 = map_units["map:Route39"].value
        self.assertEqual(
            [event["script"] for event in route39["object_events"]],
            [
                "Route39_EventScript_Norman",
                "Route39_EventScript_Ruth",
                "Route39_EventScript_Derek",
                "Route39_EventScript_Eugene",
            ],
        )
        route39_script = map_units["map-script:Route39"].value
        self.assertEqual(
            [
                event["instructions"][0]["operands"][0]
                for event in route39_script["events"]
            ],
            [
                "TRAINER_PSYCHIC_M_NORMAN_JOHTO",
                "TRAINER_PARASOL_LADY_RUTH_JOHTO",
                "TRAINER_POKEFAN_DEREK_JOHTO",
                "TRAINER_SAILOR_EUGENE_JOHTO",
            ],
        )
        trainer_units = _trainer_units(descriptor, state, ROOT)
        self.assertEqual(len(trainer_units), 1)
        parties = {
            trainer["target"]: trainer["party"] for trainer in trainer_units[0].value
        }
        eugene = next(
            trainer
            for trainer in trainer_units[0].value
            if trainer["target"] == "TRAINER_SAILOR_EUGENE_JOHTO"
        )
        samuel = next(
            trainer
            for trainer in trainer_units[0].value
            if trainer["target"] == "TRAINER_YOUNGSTER_SAMUEL_JOHTO"
        )
        wade = next(
            trainer
            for trainer in trainer_units[0].value
            if trainer["target"] == "TRAINER_BUG_CATCHER_WADE_JOHTO"
        )
        self.assertEqual(
            (samuel["class"], samuel["pic"], samuel["music"]),
            ("Youngster", "Youngster", "Male"),
        )
        self.assertEqual(
            {
                key: eugene[key]
                for key in (
                    "target",
                    "name",
                    "class",
                    "pic",
                    "gender",
                    "music",
                    "double",
                    "ai",
                )
            },
            {
                "target": "TRAINER_SAILOR_EUGENE_JOHTO",
                "name": "EUGENE",
                "class": "Sailor",
                "pic": "Sailor",
                "gender": "Male",
                "music": "Male",
                "double": False,
                "ai": ["Check Bad Move"],
            },
        )
        self.assertEqual(
            [member["species"] for member in parties["TRAINER_SAILOR_EUGENE_JOHTO"]],
            ["SPECIES_POLIWHIRL", "SPECIES_TAUROS"],
        )
        self.assertEqual(
            [member["species"] for member in parties["TRAINER_YOUNGSTER_SAMUEL_JOHTO"]],
            ["SPECIES_TEDDIURSA", "SPECIES_SANDSHREW", "SPECIES_SPEAROW"],
        )
        self.assertEqual(
            {key: wade[key] for key in ("name", "class", "pic", "gender", "music")},
            {
                "name": "WADE",
                "class": "Bug Catcher",
                "pic": "Bug Catcher",
                "gender": "Male",
                "music": "Male",
            },
        )
        self.assertEqual(
            [member["species"] for member in parties["TRAINER_BUG_CATCHER_WADE_JOHTO"]],
            ["SPECIES_WEEDLE", "SPECIES_PINECO"],
        )
        missing_route39 = MappingProxyType(
            {
                name: rows
                for name, rows in state.trainer_event_projections.items()
                if name != "Route39"
            }
        )
        with self.assertRaisesRegex(
            ContentPortError, "emitted trainer objects.*missing=.*TRAINER_"
        ):
            _map_units(
                descriptor,
                replace(state, trainer_event_projections=missing_route39),
            )
        missing_eugene_party = MappingProxyType(
            {
                name: row
                for name, row in state.trainer_party_projections.items()
                if name != "TRAINER_EUGENE"
            }
        )
        with self.assertRaisesRegex(
            ContentPortError, "typed materialized party projection is missing"
        ):
            _trainer_units(
                descriptor,
                replace(state, trainer_party_projections=missing_eugene_party),
                ROOT,
            )
        self.assertEqual(
            hashlib.sha256(
                _generated_body("trainer-bindings", descriptor, state, ROOT).encode()
            ).hexdigest(),
            "e73b027b1743a157afcef41189ea2c80c7172504dd547cb7059f824db05d0f79",
        )
        self.assertEqual(
            hashlib.sha256(
                _generated_body("trainer-parties", descriptor, state, ROOT).encode()
            ).hexdigest(),
            "f2163b8059ef83d28fc87e422705125e8e7517e92cc90b2baf8e27ab5bdaf393",
        )

    def test_surf_edge_exit_materializes_only_on_its_rendered_source(self) -> None:
        descriptor = self.descriptor()
        _, state = resolve_port_sources(descriptor, ROOT)
        map_units = {unit.key: unit for unit in _map_units(descriptor, state)}
        self.assertEqual(
            map_units["map:Route40"].value["edge_exits"],
            [
                {
                    "exit_edge": "west",
                    "target_map": "MAP_ROUTE19",
                    "target_x": 20,
                    "target_y": 59,
                    "target_facing": "north",
                    "route_profile": "generated_ocean",
                }
            ],
        )
        self.assertNotIn("edge_exits", map_units["map:Route41"].value)

    def test_installed_baseline_and_location_refresh_have_exact_desired_delta(
        self,
    ) -> None:
        descriptor = self.descriptor()
        installed = OwnershipManifest.load(PORT / "ownership.json")
        desired, _ = derive_desired_state(descriptor, ROOT)
        pre_location_refresh = _with_pre_location_refresh_hashes(installed)
        desired_by_identity = desired.by_identity
        location_delta = {
            (
                "registry-record",
                "src/data/region_map/region_map_sections.json",
                "map_sections",
                section,
            )
            for section in LATE_JOHTO_LOCATION_OWNERSHIP_HASHES
        }

        def manifest_delta(baseline: OwnershipManifest) -> set[tuple[str, ...]]:
            baseline_by_identity = baseline.by_identity
            self.assertEqual(
                set(desired_by_identity),
                set(baseline_by_identity),
            )
            return {
                identity
                for identity in baseline_by_identity
                if baseline_by_identity[identity].sha256
                != desired_by_identity[identity].sha256
            }

        self.assertEqual(manifest_delta(installed), set())
        self.assertEqual(manifest_delta(pre_location_refresh), location_delta)
        for identity in location_delta:
            key = identity[-1]
            self.assertEqual(
                (
                    pre_location_refresh.by_identity[identity].sha256,
                    desired_by_identity[identity].sha256,
                ),
                LATE_JOHTO_LOCATION_OWNERSHIP_HASHES[key],
            )

    def test_route39_encounters_are_authenticated_land_only_profiles(self) -> None:
        descriptor = self.descriptor()
        installed = OwnershipManifest.load(PORT / "ownership.json")
        desired, payloads = derive_desired_state(descriptor, ROOT)
        pre_location_refresh = _with_pre_location_refresh_hashes(installed)
        installed_by_identity = installed.by_identity
        _, state = resolve_port_sources(descriptor, ROOT)
        units = _encounter_units(descriptor, state)
        self.assertEqual(
            [unit.record_key for unit in units], ["gRoute39", "gRoute39_Night"]
        )
        self.assertTrue(
            all(unit.registry == "wild_encounter_groups.0.encounters" for unit in units)
        )
        self.assertTrue(
            all(set(unit.value) == {"map", "base_label", "land_mons"} for unit in units)
        )
        profiles = {unit.record_key: unit.value["land_mons"] for unit in units}
        self.assertEqual(
            {
                label: (profile["encounter_rate"], len(profile["mons"]))
                for label, profile in profiles.items()
            },
            {"gRoute39": (20, 12), "gRoute39_Night": (20, 12)},
        )
        self.assertEqual(
            [
                (mon["min_level"], mon["max_level"], mon["species"])
                for mon in profiles["gRoute39"]["mons"]
            ],
            [
                (21, 21, "SPECIES_PONYTA"),
                (21, 21, "SPECIES_RATICATE"),
                (21, 21, "SPECIES_MAGNEMITE"),
                (21, 21, "SPECIES_DODUO"),
                (21, 21, "SPECIES_PONYTA"),
                (21, 21, "SPECIES_RATICATE"),
                (21, 21, "SPECIES_MAGNEMITE"),
                (21, 21, "SPECIES_DODUO"),
                (21, 21, "SPECIES_MILTANK"),
                (21, 21, "SPECIES_TAUROS"),
                (21, 21, "SPECIES_MILTANK"),
                (21, 21, "SPECIES_TAUROS"),
            ],
        )
        self.assertEqual(
            [
                (mon["min_level"], mon["max_level"], mon["species"])
                for mon in profiles["gRoute39_Night"]["mons"]
            ],
            [
                (18, 21, "SPECIES_MEOWTH"),
                (21, 21, "SPECIES_RATICATE"),
                (20, 20, "SPECIES_MAGNEMITE"),
                (20, 20, "SPECIES_NOCTOWL"),
                (18, 21, "SPECIES_MEOWTH"),
                (21, 21, "SPECIES_RATICATE"),
                (20, 20, "SPECIES_MAGNEMITE"),
                (18, 21, "SPECIES_MEOWTH"),
                (20, 20, "SPECIES_NOCTOWL"),
                (20, 20, "SPECIES_NOCTOWL"),
                (20, 20, "SPECIES_NOCTOWL"),
                (20, 20, "SPECIES_NOCTOWL"),
            ],
        )
        policy = descriptor.adaptations["encounterTimePolicy"][0]
        self.assertEqual(
            (policy["dayStart"], policy["nightStart"], policy["fallbackLabel"]),
            ("06:00", "18:00", "gRoute39"),
        )
        self.assertEqual(
            {
                key: state.semantic_evidence[key]
                for key in (
                    "content:encounter:gRoute39",
                    "content:encounter:gRoute39_Night",
                )
            },
            {
                "content:encounter:gRoute39": "2186b683bde5b5afd4d94c962f544613b77012c95f9967768d61b6a7f49c6699",
                "content:encounter:gRoute39_Night": "35d319bec735b29dad3a78a39ef6cf1625c9b6a323e98ac24a4346a607e130f2",
            },
        )

        rival_identity = (
            "section",
            "src/data/trainers.party",
            "rival trainers",
        )
        rival = installed_by_identity[rival_identity]
        rival_bytes = extract_owned_content(ROOT, installed.port, rival)
        self.assertEqual(payloads[rival_identity], rival_bytes)
        self.assertTrue(
            rival_bytes.startswith(
                b"#if 1 /* // JOHTO IMPORT BEGIN: rival trainers */\n"
            )
        )
        self.assertTrue(
            rival_bytes.endswith(
                b"\n#endif /* // JOHTO IMPORT END: rival trainers */\n"
            )
        )
        rival_opponents_identity = (
            "section",
            "include/constants/opponents.h",
            "rival opponents",
        )
        rival_opponents = extract_owned_content(
            ROOT,
            installed.port,
            installed_by_identity[rival_opponents_identity],
        )
        self.assertEqual(payloads[rival_opponents_identity], rival_opponents)
        self.assertTrue(
            rival_opponents.startswith(b"// JOHTO IMPORT BEGIN: rival opponents\n")
        )
        self.assertTrue(
            rival_opponents.endswith(b"// JOHTO IMPORT END: rival opponents\n")
        )

        for floor in range(1, 7):
            path = f"data/maps/GoldenrodCity_DepartmentStore_{floor}F/map.json"
            warps = json.loads(payloads[("file", path)])["warp_events"]
            self.assertIn(
                {
                    "x": 9,
                    "y": 3,
                    "elevation": 0,
                    "dest_map": "MAP_GOLDENROD_CITY_DEPARTMENT_STORE_ELEVATOR",
                    "dest_warp_id": "0",
                },
                warps,
            )
        for name in (
            "GoldenrodCity_DepartmentStore_7F",
            "GoldenrodCity_DepartmentStore_7FNight",
        ):
            warps = json.loads(payloads[("file", f"data/maps/{name}/map.json")])[
                "warp_events"
            ]
            self.assertEqual(warps[0]["dest_warp_id"], "2")

        for section in (
            "MAPSEC_CHERRYGROVE_CITY",
            "MAPSEC_NEW_BARK_TOWN",
            "MAPSEC_ROUTE_28",
            "MAPSEC_ROUTE_29",
        ):
            identity = (
                "registry-record",
                "src/data/region_map/region_map_sections.json",
                "map_sections",
                section,
            )
            self.assertEqual(
                payloads[identity],
                json.loads(
                    extract_owned_content(
                        ROOT, installed.port, installed_by_identity[identity]
                    )
                ),
            )

        for section, compatibility in LATE_JOHTO_LOCATION_COMPATIBILITY.items():
            identity = (
                "registry-record",
                "src/data/region_map/region_map_sections.json",
                "map_sections",
                section,
            )
            record = payloads[identity]
            self.assertEqual(
                (
                    record["saved_location"],
                    record["met_location"],
                    record["met_location_display"],
                ),
                compatibility,
            )
            self.assertEqual(
                installed_by_identity[identity].sha256,
                LATE_JOHTO_LOCATION_OWNERSHIP_HASHES[section][1],
            )

        for layout in (
            "LAYOUT_AZALEA_TOWN",
            "LAYOUT_NEW_BARK_TOWN",
            "LAYOUT_TIN_TOWER_ROOF_NIGHT",
        ):
            identity = (
                "registry-record",
                "data/layouts/layouts.json",
                "layouts",
                layout,
            )
            self.assertEqual(
                payloads[identity],
                json.loads(
                    extract_owned_content(
                        ROOT, installed.port, installed_by_identity[identity]
                    )
                ),
            )

        ownership_path = "tools/content_port/ports/johto/ownership.json"
        owned_paths = {
            unit.path for unit in (*pre_location_refresh.units, *desired.units)
        }
        with tempfile.TemporaryDirectory() as directory:
            staged = Path(directory)
            for relative in sorted(owned_paths | {ownership_path}):
                source = ROOT / relative
                target = staged / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            _restore_pre_codec_location_records(staged)
            pre_location_refresh.write(staged / ownership_path)
            before = {
                relative: (staged / relative).read_bytes()
                for relative in sorted(owned_paths | {ownership_path})
            }
            reconcile_owned(staged, pre_location_refresh, desired, payloads)
            desired.write(staged / ownership_path)
            changed_paths = {
                relative
                for relative, content in before.items()
                if (staged / relative).read_bytes() != content
            }
            expected_changed_paths = {
                "src/data/region_map/region_map_sections.json",
                ownership_path,
            }
            self.assertEqual(changed_paths, expected_changed_paths)
            self.assertEqual(
                (staged / "src/data/wild_encounters.json").read_bytes(),
                before["src/data/wild_encounters.json"],
            )
            self.assertEqual(
                (staged / "include/constants/opponents.h").read_bytes(),
                before["include/constants/opponents.h"],
            )
            self.assertEqual(
                (staged / "data/maps/AzaleaTown/map.json").read_bytes(),
                before["data/maps/AzaleaTown/map.json"],
            )
            unrelated_asset = descriptor.assets["assets"][0]["semanticTarget"]
            self.assertEqual(
                (staged / unrelated_asset).read_bytes(), before[unrelated_asset]
            )

    def test_asset_policy_capability_and_support_state_are_render_authority(
        self,
    ) -> None:
        descriptor = self.descriptor()
        donor_root = descriptor.donors[0].root.parent
        cases = (
            ("capability", "spatail", "unknown capability 'spatail'"),
            (
                "supportState",
                "disabled",
                "asset emission requires 'enabled'",
            ),
            ("source", "", r"\.source: expected a non-empty string"),
            (
                "license",
                {"arbitrary": True},
                r"\.license: expected a non-empty string",
            ),
        )
        for field, value, message in cases:
            with (
                self.subTest(field=field),
                tempfile.TemporaryDirectory(dir=ROOT) as directory,
            ):
                port = Path(directory) / "johto"
                shutil.copytree(PORT, port)
                path = port / "assets.json"
                document = json.loads(path.read_text(encoding="utf-8"))
                document["assets"][0][field] = value
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(ContentPortError, message):
                    load_port(port, donor_root)

    def test_enabled_non_spatial_capability_cannot_be_stripped_by_rendering(
        self,
    ) -> None:
        descriptor = self.descriptor()
        donor_root = descriptor.donors[0].root.parent
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            port = Path(directory) / "johto"
            shutil.copytree(PORT, port)
            path = port / "capabilities.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            blackthorn = next(
                item
                for item in document["maps"]
                if item["map"] == "BlackthornCity_House1"
            )
            blackthorn["capabilities"]["interactions"] = "enabled"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(
                ContentPortError,
                "enabled capability is not materialized by the current render profile",
            ):
                load_port(port, donor_root)

    def test_owned_output_corruption_cannot_change_desired_state(self) -> None:
        descriptor = self.descriptor()
        evidence, state = resolve_port_sources(descriptor, ROOT)
        recipe = OwnershipManifest.load(PORT / "ownership.json")
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            ledger = ROOT / "src/data/persistence/persistent_ids.json"
            destination = repo / ledger.relative_to(ROOT)
            destination.parent.mkdir(parents=True)
            shutil.copyfile(ledger, destination)
            installed = repo / "tools/content_port/ports/johto/ownership.json"
            installed.parent.mkdir(parents=True)
            shutil.copyfile(PORT / "ownership.json", installed)
            for path in {
                unit.path for unit in recipe.units if unit.kind == "registry-record"
            }:
                source = ROOT / path
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            for name, mode in descriptor.map_ownership.items():
                if mode != "preserve":
                    continue
                for leaf in ("map.json", "scripts.inc"):
                    source = ROOT / "data/maps" / name / leaf
                    target = repo / source.relative_to(ROOT)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)

            with (
                patch(
                    "tools.content_port.materialize.resolve_port_sources",
                    return_value=(evidence, state),
                ),
                patch(
                    "tools.content_port.materialize.authenticated_donor_snapshot",
                    return_value=nullcontext(descriptor.donors),
                ),
            ):
                first_manifest, first_payloads = derive_desired_state(descriptor, repo)
                for path in sorted(
                    {
                        unit.path
                        for unit in recipe.units
                        if unit.kind != "registry-record"
                    }
                ):
                    target = repo / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"corrupt installed output\n")
                for path in {
                    unit.path for unit in recipe.units if unit.kind == "registry-record"
                }:
                    target = repo / path
                    document = json.loads(target.read_bytes())
                    for unit in (
                        candidate
                        for candidate in recipe.units
                        if candidate.kind == "registry-record"
                        and candidate.path == path
                    ):
                        records = document
                        if unit.registry not in {"$", "root"}:
                            for part in (unit.registry or "").split("."):
                                records = (
                                    records[int(part)]
                                    if isinstance(records, list) and part.isdecimal()
                                    else records[part]
                                )
                        if isinstance(records, dict):
                            value = records[unit.key]
                        elif unit.slot is not None:
                            value = records[unit.slot]
                        else:
                            value = next(
                                record
                                for record in records
                                if isinstance(record, dict)
                                and unit.key
                                in (
                                    record.get("key"),
                                    record.get("id"),
                                    record.get("name"),
                                    record.get("base_label"),
                                )
                            )
                        if isinstance(value, dict):
                            value["_corrupt"] = True
                        elif isinstance(value, list):
                            value.append("CORRUPT_OUTPUT")
                    target.write_text(json.dumps(document), encoding="utf-8")
                second_manifest, second_payloads = derive_desired_state(
                    descriptor, repo
                )

            self.assertEqual(first_manifest.to_json(), second_manifest.to_json())
            self.assertEqual(dict(first_payloads), dict(second_payloads))
            policy_target_by_source = {
                f"{record['donor']}:{record['sourcePath']}": record["semanticTarget"]
                for record in descriptor.assets["assets"]
            }
            self.assertEqual(
                set(policy_target_by_source),
                set(state.inventory["asset-policy"]),
            )
            self.assertEqual(
                set(policy_target_by_source),
                set(state.inventory["asset-required"]),
            )
            self.assertEqual(
                {unit.key for unit in _asset_units(descriptor, state)},
                {f"asset:{target}" for target in state.asset_targets.values()},
            )
            self.assertEqual(policy_target_by_source, dict(state.asset_targets))
            actual_identities = tuple(unit.identity for unit in first_manifest.units)
            expected_identities = {unit.identity for unit in recipe.units} | {
                (
                    "section",
                    "src/data/trainers.party",
                    "selected trainer parties",
                )
            }
            self.assertEqual(len(actual_identities), len(set(actual_identities)))
            self.assertEqual(set(actual_identities), expected_identities)
            self.assertEqual(len(actual_identities), len(expected_identities))
            route30 = json.loads(first_payloads[("file", "data/maps/Route30/map.json")])
            route30_allocation = descriptor.allocation_index.map_allocation("Route30")
            self.assertEqual(route30["id"], route30_allocation.map_id)
            self.assertEqual(route30["layout"], route30_allocation.layout)
            self.assertEqual(route30["region_map_section"], route30_allocation.section)
            authenticated_route30 = next(
                unit.value
                for unit in _map_units(descriptor, state)
                if unit.key == "map:Route30"
            )
            self.assertEqual(
                route30["object_events"], authenticated_route30["object_events"]
            )
            self.assertEqual(
                [event["script"] for event in route30["object_events"]],
                [
                    "Route30_EventScript_Bugcatcher_Don",
                    "Route30_EventScript_Youngster_Mikey",
                ],
            )
            for field in descriptor.adaptations["materializationProfile"][
                "stripEventKinds"
            ]:
                if field == "object_events":
                    continue
                self.assertEqual(route30[field], [])
            self.assertTrue(route30["warp_events"])
            incomplete_adaptations = dict(descriptor.adaptations)
            incomplete_profile = dict(descriptor.adaptations["materializationProfile"])
            incomplete_profile["stripEventKinds"] = (
                "bg_events",
                "coord_events",
            )
            incomplete_adaptations["materializationProfile"] = MappingProxyType(
                incomplete_profile
            )
            incomplete_descriptor = replace(
                descriptor,
                adaptations=MappingProxyType(incomplete_adaptations),
            )
            with self.assertRaisesRegex(
                ContentPortError,
                "must strip every non-warp event collection",
            ):
                _map_units(incomplete_descriptor, state)
            interaction_decisions = tuple(
                replace(decision, state=type(decision.state).ENABLED)
                if decision.map_name == "BlackthornCity_House1"
                and decision.capability == "interactions"
                else decision
                for decision in descriptor.capabilities
            )
            with self.assertRaisesRegex(
                ContentPortError,
                "enabled capability 'interactions' is not materialized",
            ):
                _map_units(
                    replace(descriptor, capabilities=interaction_decisions),
                    state,
                )
            disabled_assets = dict(descriptor.assets)
            disabled_records = list(descriptor.assets["assets"])
            disabled_record = dict(disabled_records[0])
            disabled_record["supportState"] = "disabled"
            disabled_records[0] = MappingProxyType(disabled_record)
            disabled_assets["assets"] = tuple(disabled_records)
            disabled_descriptor = replace(
                descriptor,
                assets=MappingProxyType(disabled_assets),
            )
            with self.assertRaisesRegex(
                ContentPortError,
                "asset emission requires enabled support",
            ):
                _asset_units(disabled_descriptor, state)
            missing_asset_descriptor = replace(
                descriptor,
                assets=MappingProxyType(
                    {
                        **descriptor.assets,
                        "assets": descriptor.assets["assets"][1:],
                    }
                ),
            )
            with self.assertRaisesRegex(
                ContentPortError,
                "asset render inventory does not match authenticated closure",
            ):
                _asset_units(missing_asset_descriptor, state)
            removed_target = descriptor.assets["assets"][0]["semanticTarget"]
            self.assertIn(
                ("file", removed_target),
                {unit.identity for unit in recipe.units},
            )
            with (
                patch(
                    "tools.content_port.materialize.resolve_port_sources",
                    return_value=(evidence, state),
                ),
                patch(
                    "tools.content_port.materialize.authenticated_donor_snapshot",
                    return_value=nullcontext(descriptor.donors),
                ),
                self.assertRaisesRegex(
                    ContentPortError,
                    "asset render inventory does not match authenticated closure",
                ),
            ):
                derive_desired_state(missing_asset_descriptor, repo)
            mistargeted_assets = dict(descriptor.assets)
            mistargeted_records = list(descriptor.assets["assets"])
            mistargeted_record = dict(mistargeted_records[0])
            mistargeted_record["semanticTarget"] = (
                "data/layouts/AzaleaTown/unreferenced.bin"
            )
            mistargeted_records[0] = MappingProxyType(mistargeted_record)
            mistargeted_assets["assets"] = tuple(mistargeted_records)
            mistargeted_descriptor = replace(
                descriptor,
                assets=MappingProxyType(mistargeted_assets),
            )
            with self.assertRaisesRegex(
                ContentPortError,
                "asset render targets do not match authenticated closure",
            ):
                _asset_units(mistargeted_descriptor, state)
            victory_road = first_payloads[
                (
                    "registry-record",
                    "src/data/region_map/region_map_sections.json",
                    "map_sections",
                    "MAPSEC_JOHTO_VICTORY_ROAD",
                )
            ]
            self.assertEqual(victory_road["met_location"], 70)
            new_bark = first_payloads[
                (
                    "registry-record",
                    "data/layouts/layouts.json",
                    "layouts",
                    "LAYOUT_NEW_BARK_TOWN",
                )
            ]
            self.assertEqual(new_bark["width"], 30)
            self.assertEqual(new_bark["border_width"], 0)
            self.assertEqual(new_bark["border_height"], 0)
            self.assertRegex(
                first_payloads[
                    ("section", "include/constants/berry.h", "berry tree allocations")
                ].decode(),
                r"(?m)^#define BERRY_TREE_ROUTE_29_ORAN_1 +90$",
            )

    def test_new_group_and_layout_use_exact_authored_slots(self) -> None:
        descriptor = self.descriptor()
        _, state = resolve_port_sources(descriptor, ROOT)
        layout_id = "LAYOUT_TEST_ALLOCATION"
        group_id = "gMapGroup_TestAllocation"
        allocation_index = replace(
            descriptor.allocation_index,
            layouts=MappingProxyType(
                {**descriptor.allocation_index.layouts, layout_id: 1040}
            ),
            groups=MappingProxyType(
                {**descriptor.allocation_index.groups, group_id: 100}
            ),
        )
        layout = dict(state.layouts["LAYOUT_NEW_BARK_TOWN"])
        layout["id"] = layout_id
        expanded_state = replace(
            state,
            layouts=MappingProxyType({**state.layouts, layout_id: layout}),
            layout_authorities=MappingProxyType(
                {
                    **state.layout_authorities,
                    layout_id: state.layout_authorities["LAYOUT_NEW_BARK_TOWN"],
                }
            ),
            layout_field_authorities=MappingProxyType(
                {
                    **state.layout_field_authorities,
                    layout_id: state.layout_field_authorities["LAYOUT_NEW_BARK_TOWN"],
                }
            ),
        )
        expanded = replace(descriptor, allocation_index=allocation_index)

        layout_unit = next(
            unit
            for unit in _layout_units(expanded, expanded_state)
            if unit.key == layout_id
        )
        group_order = next(
            unit
            for unit in _group_units(expanded)
            if unit.key == f"group-order:{group_id}"
        )
        self.assertEqual(layout_unit.slot, 1040)
        self.assertEqual(group_order.registry, "group_order")
        self.assertEqual(group_order.record_key, group_id)
        self.assertEqual(group_order.slot, 100)

    def test_map_identity_layout_and_section_come_from_allocation(self) -> None:
        descriptor = self.descriptor()
        _, state = resolve_port_sources(descriptor, ROOT)
        route30 = dict(state.maps["Route30"])
        route30.update(
            {
                "id": "MAP_DONOR_DRIFT",
                "layout": "LAYOUT_DONOR_DRIFT",
                "region_map_section": "MAPSEC_DONOR_DRIFT",
            }
        )
        drifted = replace(
            state,
            maps=MappingProxyType({**state.maps, "Route30": route30}),
        )
        unit = next(
            unit
            for unit in _map_units(descriptor, drifted)
            if unit.key == "map:Route30"
        )
        allocation = descriptor.allocation_index.map_allocation("Route30")
        section_remaps = {
            item["source"]: item["target"]
            for item in descriptor.adaptations["sectionSymbolRemaps"]
        }
        self.assertEqual(unit.value["id"], allocation.map_id)
        self.assertEqual(unit.value["layout"], allocation.layout)
        self.assertEqual(
            unit.value["region_map_section"],
            section_remaps.get(allocation.section, allocation.section),
        )

        route30_map = next(
            item for item in _map_units(descriptor, state) if item.key == "map:Route30"
        )
        sections_by_slot = {
            item.slot: item for item in _section_units(descriptor, state, ROOT)
        }
        route30_section = sections_by_slot[allocation.target_section]
        self.assertEqual(
            route30_map.value["region_map_section"], route30_section.record_key
        )
        self.assertEqual(route30_map.value["region"], "REGION_JOHTO")
        self.assertEqual(route30_section.value["region"], "REGION_JOHTO")
        self.assertEqual(route30_section.slot, 214)
        resident_allocation = replace(allocation, section_ownership="reference")
        resident_descriptor = replace(
            descriptor,
            allocation_index=AllocationIndex(
                MappingProxyType(
                    {
                        **descriptor.allocation_index.maps,
                        "Route30": resident_allocation,
                    }
                ),
                descriptor.allocation_index.layouts,
                descriptor.allocation_index.groups,
                MappingProxyType(
                    {
                        name: slot
                        for name, slot in descriptor.allocation_index.sections.items()
                        if name != allocation.section
                    }
                ),
            ),
            section_metadata_authorities=tuple(
                authority
                for authority in descriptor.section_metadata_authorities
                if authority.section != allocation.section
            ),
        )
        self.assertNotIn(
            allocation.section,
            {
                unit.record_key
                for unit in _section_units(resident_descriptor, state, ROOT)
            },
        )
        manifest, _ = render_units(
            RenderContext("johto"), (route30_map, route30_section)
        )
        self.assertIn(
            ("file", "data/maps/Route30/map.json"),
            manifest.by_identity,
        )
        section_identity = (
            "registry-record",
            "src/data/region_map/region_map_sections.json",
            "map_sections",
            "MAPSEC_ROUTE_30",
        )
        self.assertEqual(manifest.by_identity[section_identity].slot, 214)
        self.assertNotIn(
            "map:VermilionCity_PortInside",
            {item.key for item in _map_units(descriptor, state)},
        )

    def test_transient_route30_mutation_cannot_enter_snapshot_render(
        self,
    ) -> None:
        descriptor = self.descriptor()
        _, state = resolve_port_sources(descriptor, ROOT)
        source = (
            descriptor.donors_by_role["content"].root / "data/maps/Route30/map.json"
        )
        source_document = json.loads(source.read_bytes())
        original_weather = source_document["weather"]
        transient_weather = "WEATHER_SUNNY_CLOUDS"
        self.assertNotEqual(original_weather, transient_weather)

        with tempfile.TemporaryDirectory() as directory:
            donor = Path(directory) / "donor"
            ledger = ROOT / "src/data/persistence/persistent_ids.json"
            installed_ledger = Path(directory) / ledger.relative_to(ROOT)
            installed_ledger.parent.mkdir(parents=True)
            shutil.copyfile(ledger, installed_ledger)
            route30 = donor / "data/maps/Route30/map.json"
            route30.parent.mkdir(parents=True)
            route30.write_bytes(source.read_bytes())
            records = source_tree_records(donor)
            pin = DonorPin(
                "isolated",
                "example/isolated",
                "0" * 40,
                records_digest(records),
                len(records),
                donor,
            )
            isolated_descriptor = replace(
                descriptor,
                donors=(pin,),
                donors_by_role=MappingProxyType({"content": pin, "mechanical": pin}),
                map_ownership=MappingProxyType({"Route30": "rendered"}),
            )
            original = route30.read_bytes()

            def resolve_during_transient_mutation(snapshot_descriptor, _repo):
                document = json.loads(original)
                document["weather"] = transient_weather
                route30.write_text(json.dumps(document), encoding="utf-8")
                try:
                    snapshot_route30 = (
                        snapshot_descriptor.donors_by_role["content"].root
                        / "data/maps/Route30/map.json"
                    )
                    self.assertFalse(os.path.samefile(route30, snapshot_route30))
                    rendered_map = json.loads(snapshot_route30.read_bytes())
                    isolated_state = replace(
                        state,
                        maps=MappingProxyType({"Route30": rendered_map}),
                        donor_roots=MappingProxyType(
                            {
                                role: pin.root
                                for role, pin in snapshot_descriptor.donors_by_role.items()
                            }
                        ),
                    )
                    return (), isolated_state
                finally:
                    route30.write_bytes(original)

            with (
                patch.dict(os.environ, {"CONTENT_PORT_REQUIRE_DONORS": "0"}),
                patch(
                    "tools.content_port.materialize.resolve_port_sources",
                    side_effect=resolve_during_transient_mutation,
                ),
                patch("tools.content_port.materialize._layout_units", return_value=[]),
                patch("tools.content_port.materialize._group_units", return_value=[]),
                patch("tools.content_port.materialize._section_units", return_value=[]),
                patch("tools.content_port.materialize._asset_units", return_value=[]),
                patch(
                    "tools.content_port.materialize._animation_units", return_value=[]
                ),
                patch(
                    "tools.content_port.materialize._generated_units", return_value=[]
                ),
            ):
                _, payloads = derive_desired_state(isolated_descriptor, Path(directory))

            rendered = json.loads(payloads[("file", "data/maps/Route30/map.json")])
            self.assertEqual(rendered["weather"], original_weather)
            self.assertEqual(route30.read_bytes(), original)

    def test_mechanical_layout_border_drift_fails_authentication(self) -> None:
        descriptor = self.descriptor()
        source = (
            descriptor.donors_by_role["mechanical"].root / "data/layouts/layouts.json"
        )
        with tempfile.TemporaryDirectory() as directory:
            donor = Path(directory) / "donor"
            layouts = donor / "data/layouts/layouts.json"
            layouts.parent.mkdir(parents=True)
            layouts.write_bytes(source.read_bytes())
            records = source_tree_records(donor)
            pin = DonorPin(
                "isolated",
                "example/isolated",
                "0" * 40,
                records_digest(records),
                len(records),
                donor,
            )
            document = json.loads(layouts.read_bytes())
            new_bark = next(
                item
                for item in document["layouts"]
                if item["id"] == "LAYOUT_NEW_BARK_TOWN"
            )
            self.assertEqual(new_bark["border_width"], 0)
            new_bark["border_width"] = 1
            layouts.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            isolated_descriptor = replace(
                descriptor,
                donors=(pin,),
                donors_by_role=MappingProxyType({"content": pin, "mechanical": pin}),
            )
            with (
                patch.dict(os.environ, {"CONTENT_PORT_REQUIRE_DONORS": "0"}),
                self.assertRaisesRegex(ContentPortError, "source-tree digest mismatch"),
            ):
                derive_desired_state(isolated_descriptor, ROOT)

    def test_victory_road_codec_requires_a_ledger_binding(self) -> None:
        descriptor = self.descriptor()
        evidence, state = resolve_port_sources(descriptor, ROOT)
        bindings = descriptor.target_bindings
        assert bindings is not None
        codec = bindings.section_persistence_codecs[0]
        broken = replace(
            descriptor,
            target_bindings=replace(
                bindings,
                section_persistence_codecs=(
                    replace(
                        codec,
                        met_location_binding=PersistentBindingRef(
                            "destinations", "MAPSEC_BLACKTHORN_CITY"
                        ),
                    ),
                ),
            ),
        )
        with (
            patch(
                "tools.content_port.materialize.resolve_port_sources",
                return_value=(evidence, state),
            ),
            patch(
                "tools.content_port.materialize.authenticated_donor_snapshot",
                return_value=nullcontext(descriptor.donors),
            ),
            self.assertRaisesRegex(ContentPortError, "must match its display identity"),
        ):
            derive_desired_state(broken, ROOT)

    def test_ordinary_section_codes_must_agree_with_the_persistent_ledger(
        self,
    ) -> None:
        descriptor = self.descriptor()
        evidence, state = resolve_port_sources(descriptor, ROOT)
        source = ROOT / "src/data/persistence/persistent_ids.json"
        original = json.loads(source.read_text(encoding="utf-8"))
        for domain, label in (
            ("destinations", "persistent destination binding"),
            ("savedLocations", "persistent saved location binding"),
        ):
            with (
                self.subTest(domain=domain),
                tempfile.TemporaryDirectory() as directory,
            ):
                repo = Path(directory)
                document = json.loads(json.dumps(original))
                binding = next(
                    item
                    for item in document["entries"]
                    if item["domain"] == domain
                    and item["symbol"] == "MAPSEC_NEW_BARK_TOWN"
                )
                self.assertEqual(binding["value"], 209)
                binding["value"] = 10000
                target = repo / source.relative_to(ROOT)
                target.parent.mkdir(parents=True)
                target.write_text(json.dumps(document), encoding="utf-8")
                with (
                    patch(
                        "tools.content_port.materialize.resolve_port_sources",
                        return_value=(evidence, state),
                    ),
                    patch(
                        "tools.content_port.materialize.authenticated_donor_snapshot",
                        return_value=nullcontext(descriptor.donors),
                    ),
                    self.assertRaisesRegex(ContentPortError, label),
                ):
                    derive_desired_state(descriptor, repo)

    def test_berry_tree_binding_requires_an_allocated_ledger_identity(self) -> None:
        descriptor = self.descriptor()
        evidence, state = resolve_port_sources(descriptor, ROOT)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            source = ROOT / "src/data/persistence/persistent_ids.json"
            document = json.loads(source.read_text(encoding="utf-8"))
            document["entries"] = [
                item
                for item in document["entries"]
                if item["symbol"] != "BERRY_TREE_ROUTE_29_ORAN_1"
            ]
            target = repo / source.relative_to(ROOT)
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(document), encoding="utf-8")
            with (
                patch(
                    "tools.content_port.materialize.resolve_port_sources",
                    return_value=(evidence, state),
                ),
                patch(
                    "tools.content_port.materialize.authenticated_donor_snapshot",
                    return_value=nullcontext(descriptor.donors),
                ),
                self.assertRaisesRegex(ContentPortError, "has no ledger binding"),
            ):
                derive_desired_state(descriptor, repo)

    def test_generated_section_authority_contract_is_enforced_in_production(
        self,
    ) -> None:
        descriptor = self.descriptor()
        evidence, state = resolve_port_sources(descriptor, ROOT)
        policies = tuple(
            replace(policy, authorities=("mechanical",))
            if policy.source_symbol == "flag-bindings"
            else policy
            for policy in descriptor.generated_sections
        )
        with (
            patch(
                "tools.content_port.materialize.resolve_port_sources",
                return_value=(evidence, state),
            ),
            patch(
                "tools.content_port.materialize.authenticated_donor_snapshot",
                return_value=nullcontext(descriptor.donors),
            ),
            self.assertRaisesRegex(ContentPortError, "authority contract drift"),
        ):
            derive_desired_state(replace(descriptor, generated_sections=policies), ROOT)

    def test_donor_asset_mutation_fails_closed(self) -> None:
        descriptor = self.descriptor()
        _, state = resolve_port_sources(descriptor, ROOT)
        asset = descriptor.assets["assets"][0]
        role = asset["donor"]
        source_path = asset["sourcePath"]
        with tempfile.TemporaryDirectory() as directory:
            donor = Path(directory)
            target = donor / source_path
            target.parent.mkdir(parents=True)
            shutil.copyfile(state.donor_roots[role] / source_path, target)
            isolated = replace(
                state,
                donor_roots=MappingProxyType({**state.donor_roots, role: donor}),
                asset_targets=MappingProxyType(
                    {f"{role}:{source_path}": asset["semanticTarget"]}
                ),
                inventory=MappingProxyType(
                    {
                        **state.inventory,
                        "asset-policy": (f"{role}:{source_path}",),
                        "asset-required": (f"{role}:{source_path}",),
                    }
                ),
            )
            focused = replace(
                descriptor,
                assets=MappingProxyType({"schemaVersion": 1, "assets": (asset,)}),
            )
            self.assertEqual(len(_asset_units(focused, isolated)), 1)
            target.write_bytes(target.read_bytes() + b"mutation")
            with self.assertRaisesRegex(ContentPortError, "hash drift"):
                _asset_units(focused, isolated)


if __name__ == "__main__":
    unittest.main()
