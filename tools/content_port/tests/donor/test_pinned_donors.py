from __future__ import annotations

import hashlib
import json
import os
import re
import unittest
from pathlib import Path

from tools.content_port.cli import check_port
from tools.content_port.descriptor import load_port
from tools.content_port.donors import authenticate_donors
from tools.content_port.ecology import (
    SUPPORTED_SOURCE_METHODS,
    build_authenticated_profile_lookup,
    normalize_donor_profile,
    validate_ecology_document,
)
from tools.content_port.ecology_fallbacks import validate_fallback_document
from tools.wild_encounters.johto_population import project_documents


ROUTE39_SOURCE_DIGEST = (
    "0bc050ec9aeb066e2b5fe3b8c178e0064aeeb636b51649c600c0dbfa4718f033"
)
BLOCKED_MAPS = {
    "LakeOfRageLowTide",
    "Route26North",
    "JohtoVictoryRoad_1F",
    "JohtoVictoryRoad_B1F",
    "JohtoVictoryRoad_B2F",
}
EXCLUDED_DONOR_MAPS = {
    "MAP_NATIONAL_PARK_BUG_CONTEST",
    "MAP_SAFARI_ZONE_GATE",
    "MAP_SAFARI_ZONE_LOW_LEFT",
    "MAP_SAFARI_ZONE_LOW_MID",
    "MAP_SAFARI_ZONE_LOW_RIGHT",
    "MAP_SAFARI_ZONE_TOP_MID",
    "MAP_SAFARI_ZONE_TOP_RIGHT",
}
VICTORY_ROAD_FALLBACKS = {
    "JohtoVictoryRoad_1F",
    "JohtoVictoryRoad_B1F",
    "JohtoVictoryRoad_B2F",
}


class PinnedDonorTests(unittest.TestCase):
    def test_real_pinned_donors_authenticate_without_skips(self) -> None:
        donor_root = Path(
            os.environ.get("CONTENT_PORT_DONOR_ROOT", ".references")
        ).resolve()
        missing = [
            str(donor_root / name)
            for name in ("pokemonHnS", "PKMN-World")
            if not (donor_root / name).is_dir()
        ]
        if missing:
            message = f"missing required donor checkouts: {', '.join(missing)}"
            if os.environ.get("CONTENT_PORT_REQUIRE_DONORS") == "1":
                self.fail(message)
            self.skipTest(message)
        descriptor = load_port(Path("tools/content_port/ports/johto"), donor_root)
        evidence = authenticate_donors(descriptor.donors)
        self.assertEqual(len(evidence), 2)
        report = check_port(
            Path.cwd(),
            "johto",
            donor_root,
            compare_report=Path("tools/content_port/ports/johto/legacy_report.json"),
        )
        self.assertEqual(report["schemaVersion"], 1)

        roots = {
            "content": donor_root / "pokemonHnS",
            "mechanical": donor_root / "PKMN-World",
        }
        policy = json.loads(
            Path("tools/content_port/ports/johto/assets.json").read_text()
        )
        for asset in policy["assets"]:
            with self.subTest(asset=asset["key"]):
                source = roots[asset["donor"]] / asset["sourcePath"]
                self.assertTrue(source.is_file(), f"missing donor asset: {source}")
                self.assertEqual(
                    hashlib.sha256(source.read_bytes()).hexdigest(),
                    asset["sourceSha256"],
                )

        johto = Path("tools/content_port/ports/johto")
        classification = json.loads(
            (johto / "encounter_classification.json").read_text()
        )
        ecology = json.loads((johto / "encounter_ecology.json").read_text())
        port = json.loads((johto / "port.json").read_text())
        ordinary_maps = [
            row["map"] for row in classification["maps"] if row["kind"] == "ordinary"
        ]
        source_map_by_target = {
            record["map"]: json.loads(
                (Path("data/maps") / record["map"] / "map.json").read_text()
            )["id"]
            for record in ecology["records"]
            if record["status"] == "inventoried"
        }
        source_ids = set(source_map_by_target.values())
        self.assertEqual(len(source_ids), 84)
        donor_document = json.loads(
            (roots["content"] / "src/data/wild_encounters.json").read_text()
        )
        donor_group = next(
            group
            for group in donor_document["wild_encounter_groups"]
            if group["for_maps"]
        )
        donor_map_ids = {encounter["map"] for encounter in donor_group["encounters"]}
        special_map_ids = {
            json.loads((Path("data/maps") / row["map"] / "map.json").read_text())["id"]
            for row in classification["maps"]
            if row["kind"] == "special"
        }
        self.assertEqual(donor_map_ids & special_map_ids, EXCLUDED_DONOR_MAPS)
        self.assertTrue(source_ids.isdisjoint(EXCLUDED_DONOR_MAPS))
        normalized_profiles = [
            normalize_donor_profile(
                encounter,
                donor_group["fields"],
                source_index=index,
            )
            for index, encounter in enumerate(donor_group["encounters"])
            if encounter["map"] in source_ids
        ]
        self.assertEqual(len(normalized_profiles), 140)
        donor = port["donors"]["content"]
        source_identity = {
            "role": "content",
            "name": donor["name"],
            "repository": donor["repository"],
            "commit": donor["commit"],
            "treeDigest": donor["treeDigest"],
            "path": "src/data/wild_encounters.json",
        }
        species = set(
            re.findall(
                r"\bSPECIES_[A-Z0-9_]+\b",
                Path("include/constants/species.h").read_text(),
            )
        )
        validate_ecology_document(
            ecology,
            ordinary_maps,
            build_authenticated_profile_lookup(normalized_profiles),
            source_identity=source_identity,
            supported_methods=SUPPORTED_SOURCE_METHODS,
            supported_species=species,
            source_map_by_target=source_map_by_target,
            expected_blocked_maps=BLOCKED_MAPS,
            protected_route39_profile=ROUTE39_SOURCE_DIGEST,
        )

        fallbacks = json.loads((johto / "encounter_fallbacks.json").read_text())
        validate_fallback_document(fallbacks)
        selected_profiles = {
            (record["sourceMap"], profile["sourceLabel"], profile["condition"])
            for record in fallbacks["records"]
            for profile in record["profiles"]
        }
        authenticated_fallback_profiles = {}
        for encounter in donor_group["encounters"]:
            key = (
                encounter["map"],
                encounter["base_label"],
                "night" if encounter["base_label"].endswith("_Night") else "day",
            )
            if key not in selected_profiles:
                continue
            # Fallback selectors may point outside the reconciled Johto inventory
            # slices. The slice does not affect normalized encounter values, so use
            # a valid reviewed index and discard that inventory-only annotation.
            normalized = normalize_donor_profile(
                encounter,
                donor_group["fields"],
                source_index=339,
            )
            normalized.pop("provenanceSlice")
            self.assertNotIn(key, authenticated_fallback_profiles)
            authenticated_fallback_profiles[key] = normalized
        self.assertEqual(set(authenticated_fallback_profiles), selected_profiles)
        for record in fallbacks["records"]:
            for profile in record["profiles"]:
                key = (
                    record["sourceMap"],
                    profile["sourceLabel"],
                    profile["condition"],
                )
                with self.subTest(fallback_profile=profile["targetLabel"]):
                    normalized = authenticated_fallback_profiles[key]
                    self.assertEqual(normalized["sourceMap"], record["sourceMap"])
                    self.assertEqual(normalized["label"], profile["sourceLabel"])
                    self.assertEqual(normalized["condition"], profile["condition"])
                    self.assertTrue(normalized["methods"])

        spatial_root = roots["mechanical"]
        map_groups = json.loads(
            (spatial_root / fallbacks["spatialSource"]["mapIndexPath"]).read_text()
        )
        authenticated_map_paths = {
            f"data/maps/{map_name}/map.json"
            for group_name in map_groups["group_order"]
            for map_name in map_groups[group_name]
        }
        layouts = json.loads(
            (spatial_root / fallbacks["spatialSource"]["layoutIndexPath"]).read_text()
        )
        layouts_by_id = {layout["id"]: layout for layout in layouts["layouts"]}

        for record in fallbacks["records"]:
            spatial = record["spatialEvidence"]
            actual = {}
            for side in ("target", "source"):
                evidence = spatial[side]
                map_path = spatial[f"{side}MapPath"]
                with self.subTest(fallback=record["targetName"], side=side):
                    self.assertIn(map_path, authenticated_map_paths)
                    map_document = json.loads(
                        (spatial_root / map_path).read_text(encoding="utf-8")
                    )
                    self.assertEqual(map_document["id"], evidence["mapId"])
                    self.assertEqual(map_document["layout"], evidence["layoutId"])
                    self.assertEqual(
                        map_document["region_map_section"],
                        evidence["regionMapSection"],
                    )
                    layout = layouts_by_id[evidence["layoutId"]]
                    self.assertEqual(layout["width"], evidence["width"])
                    self.assertEqual(layout["height"], evidence["height"])
                    self.assertEqual(
                        layout["primary_tileset"], evidence["primaryTileset"]
                    )
                    self.assertEqual(
                        layout["secondary_tileset"], evidence["secondaryTileset"]
                    )
                    self.assertEqual(
                        layout["blockdata_filepath"], evidence["mapBinPath"]
                    )
                    map_bin = (spatial_root / evidence["mapBinPath"]).read_bytes()
                    self.assertEqual(
                        hashlib.sha256(map_bin).hexdigest(),
                        evidence["mapBinSha256"],
                    )
                    actual[side] = (map_document, layout, map_bin)

            target_map, target_layout, target_bin = actual["target"]
            source_map, source_layout, source_bin = actual["source"]
            with self.subTest(fallback_relationship=record["targetName"]):
                self.assertEqual(target_map["id"], record["targetMap"])
                self.assertEqual(source_map["id"], record["sourceMap"])
                self.assertNotEqual(target_map["id"], source_map["id"])
                self.assertNotEqual(target_layout["id"], source_layout["id"])
                if record["targetName"] in VICTORY_ROAD_FALLBACKS:
                    self.assertEqual(spatial["relationship"], "byte-identical-layout")
                    self.assertEqual(target_bin, source_bin)
                elif record["targetName"] == "LakeOfRageLowTide":
                    self.assertEqual(spatial["relationship"], "alternate-tide")
                    self.assertEqual(
                        target_map["region_map_section"],
                        source_map["region_map_section"],
                    )
                    self.assertEqual(
                        (target_layout["width"], target_layout["height"]),
                        (source_layout["width"], source_layout["height"]),
                    )
                    self.assertEqual(
                        (
                            target_layout["primary_tileset"],
                            target_layout["secondary_tileset"],
                        ),
                        (
                            source_layout["primary_tileset"],
                            source_layout["secondary_tileset"],
                        ),
                    )
                    self.assertNotEqual(target_bin, source_bin)
                else:
                    self.assertEqual(record["targetName"], "Route26North")
                    self.assertEqual(
                        spatial["relationship"], "directly-connected-segment"
                    )
                    self.assertEqual(
                        target_map["region_map_section"],
                        source_map["region_map_section"],
                    )
                    self.assertNotEqual(target_bin, source_bin)
                    self.assertIn(
                        {
                            "map": record["targetMap"],
                            "offset": 0,
                            "direction": "up",
                        },
                        source_map["connections"],
                    )

        production_paths = {
            "encounters": Path("src/data/wild_encounters.json"),
            "registry": Path("src/data/wild_encounter_registry.json"),
            "bands": Path("src/data/wild_encounter_bands.json"),
            "timePolicies": Path("src/data/wild_encounter_time_policies.json"),
        }
        production = {
            name: json.loads(path.read_text(encoding="utf-8"))
            for name, path in production_paths.items()
        }
        map_ids = {
            row["map"]: json.loads(
                (Path("data/maps") / row["map"] / "map.json").read_text(
                    encoding="utf-8"
                )
            )["id"]
            for row in classification["maps"]
            if row["kind"] == "ordinary"
        }
        projected = project_documents(
            classification,
            ecology,
            fallbacks,
            production["encounters"],
            production["registry"],
            production["bands"],
            map_ids,
            donor_document,
        )
        for name, actual in zip(production_paths, projected, strict=True):
            with self.subTest(projected_document=name):
                self.assertEqual(actual, production[name])


if __name__ == "__main__":
    unittest.main()
