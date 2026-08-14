from __future__ import annotations

import os
from pathlib import Path
import hashlib
import json
import re
import unittest

from tools.content_port.cli import check_port
from tools.content_port.descriptor import load_port
from tools.content_port.donors import authenticate_donors
from tools.content_port.ecology import (
    SUPPORTED_SOURCE_METHODS,
    build_authenticated_profile_lookup,
    normalize_donor_profile,
    validate_ecology_document,
)


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


if __name__ == "__main__":
    unittest.main()
