import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from tools.wild_encounters import wild_encounters_to_header as generator


ROOT = Path(__file__).resolve().parents[3]
ENCOUNTERS = ROOT / "src/data/wild_encounters.json"
REGISTRY = ROOT / "src/data/wild_encounter_registry.json"


class WildEncounterGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encounters = json.loads(ENCOUNTERS.read_text(encoding="utf-8"))
        cls.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.encounters_path = self.root / "wild_encounters.json"
        self.registry_path = self.root / "wild_encounter_registry.json"
        self.output_path = self.root / "wild_encounters.h"

    def generate(
        self, encounters=None, registry=None, config_path=None, rtc_constants_path=None
    ):
        encounters = self.encounters if encounters is None else encounters
        registry = self.registry if registry is None else registry
        self.encounters_path.write_text(json.dumps(encounters), encoding="utf-8")
        self.registry_path.write_text(json.dumps(registry), encoding="utf-8")
        generator.generate(
            encounters_path=self.encounters_path,
            registry_path=self.registry_path,
            output_path=self.output_path,
            config_path=(
                generator.DEFAULT_CONFIG if config_path is None else config_path
            ),
            rtc_constants_path=(
                generator.DEFAULT_RTC_CONSTANTS
                if rtc_constants_path is None
                else rtc_constants_path
            ),
        )
        return self.output_path.read_text(encoding="utf-8")

    def assert_rejected_without_replacement(
        self,
        encounters=None,
        registry=None,
        config_path=None,
        rtc_constants_path=None,
    ):
        self.output_path.write_bytes(b"reviewed output\n")
        encounters = self.encounters if encounters is None else encounters
        registry = self.registry if registry is None else registry
        self.encounters_path.write_text(json.dumps(encounters), encoding="utf-8")
        self.registry_path.write_text(json.dumps(registry), encoding="utf-8")
        with self.assertRaises(generator.ValidationError):
            generator.generate(
                encounters_path=self.encounters_path,
                registry_path=self.registry_path,
                output_path=self.output_path,
                config_path=(
                    generator.DEFAULT_CONFIG if config_path is None else config_path
                ),
                rtc_constants_path=(
                    generator.DEFAULT_RTC_CONSTANTS
                    if rtc_constants_path is None
                    else rtc_constants_path
                ),
            )
        self.assertEqual(self.output_path.read_bytes(), b"reviewed output\n")

    @staticmethod
    def find_profile(registry, label):
        return next(row for row in registry["profiles"] if row[1] == label)

    @staticmethod
    def find_encounter(encounters, label):
        return next(
            encounter
            for group in encounters["wild_encounter_groups"]
            for encounter in group["encounters"]
            if encounter["base_label"] == label
        )

    def test_complete_resident_inventory_generates_without_product_guards(self):
        output = self.generate()
        profiles = self.registry["profiles"]
        self.assertEqual(len(profiles), 407)
        self.assertEqual(
            {
                residency: sum(row[3] == residency for row in profiles)
                for residency in generator.RESIDENCIES
            },
            {"hoenn": 135, "kanto": 132, "sevii": 132, "johto": 8},
        )
        self.assertIsNone(generator.PRODUCT_GUARD.search(output))
        self.assertEqual(output.count("const struct WildPokemonHeader "), 3)
        mon_types = generator.Config(
            generator.DEFAULT_CONFIG,
            generator.DEFAULT_RTC_CONSTANTS,
            self.encounters,
        ).mon_types
        profiles_by_label = {
            row[1]: dict(zip(generator.PROFILE_FIELDS, row, strict=True))
            for row in profiles
        }

        for group in self.encounters["wild_encounter_groups"]:
            for encounter in group["encounters"]:
                profile = profiles_by_label[encounter["base_label"]]
                if profile["alternate_of"] is not None:
                    self.assertNotIn(encounter["base_label"], output)
                    continue
                for mon_type in mon_types:
                    if mon_type not in encounter:
                        continue
                    array_name = (
                        encounter["base_label"]
                        + "_"
                        + mon_type.title().replace("_", "")
                    )
                    self.assertIn(f"const struct WildPokemon {array_name}[] =", output)
                    for mon in encounter[mon_type]["mons"]:
                        member = (
                            f"{{ {mon.get('min_level', 2)}, {mon.get('max_level', 100)}, "
                            f"{mon['species']} }},"
                        )
                        self.assertIn(member, output)

    def test_runtime_headers_have_one_canonical_map_entry_and_ordered_variants(self):
        output = self.generate()
        profiles = [
            dict(zip(generator.PROFILE_FIELDS, row, strict=True))
            for row in self.registry["profiles"]
        ]
        encounter_by_label = {
            encounter["base_label"]: encounter
            for group in self.encounters["wild_encounter_groups"]
            for encounter in group["encounters"]
        }
        profiles_by_map = {}
        for profile in profiles:
            map_id = encounter_by_label[profile["label"]].get("map")
            if map_id is not None and profile["alternate_of"] is None:
                profiles_by_map.setdefault(map_id, []).append(profile)

        for map_id, map_profiles in profiles_by_map.items():
            variant_indices = {
                profile["variant_index"]
                for profile in map_profiles
                if profile["variant_set"] is not None
            }
            expected_entries = len(variant_indices) if variant_indices else 1
            self.assertEqual(
                output.count(f".mapGroup = MAP_GROUP({map_id}),"), expected_entries
            )

        for profile in profiles:
            if profile["alternate_of"] is not None:
                self.assertNotIn(profile["label"], output)

        runtime_species = set()
        evidence_species = set()
        mon_types = generator.Config(
            generator.DEFAULT_CONFIG,
            generator.DEFAULT_RTC_CONSTANTS,
            self.encounters,
        ).mon_types
        for profile in profiles:
            target = (
                evidence_species
                if profile["alternate_of"] is not None
                else runtime_species
            )
            encounter = encounter_by_label[profile["label"]]
            for mon_type in mon_types:
                if mon_type in encounter:
                    target.update(mon["species"] for mon in encounter[mon_type]["mons"])
        evidence_only_species = evidence_species - runtime_species
        self.assertTrue(evidence_only_species)
        for species in evidence_only_species:
            self.assertNotIn(species, output)

        for name in (
            "hoenn_altering_cave",
            "sevii_altering_cave_firered",
        ):
            labels = generator.ALTERING_CAVE_VARIANTS[name]["labels"]
            references = [output.index(f"&{label}_LandMonsInfo") for label in labels]
            self.assertEqual(references, sorted(references))

    def test_runtime_time_resolution_for_enabled_and_disabled_configs(self):
        config_source = generator.DEFAULT_CONFIG.read_text(encoding="utf-8")
        rtc_source = generator.DEFAULT_RTC_CONSTANTS.read_text(encoding="utf-8")
        times = list(
            generator.Config(
                generator.DEFAULT_CONFIG,
                generator.DEFAULT_RTC_CONSTANTS,
                self.encounters,
            ).times_of_day
        )

        def map_entry(output, map_id):
            start = output.index(f".mapGroup = MAP_GROUP({map_id}),")
            end = output.index(".mapGroup = ", start + 1)
            return output[start:end]

        def land_binding(entry, time):
            match = re.search(
                rf"\[{time}\]\s*=\s*\{{.*?\.landMonsInfo = ([^,]+),",
                entry,
                re.DOTALL,
            )
            return None if match is None else match.group(1)

        for fallback_time in times:
            with self.subTest(enabled=True, fallback=fallback_time):
                config_path = self.root / f"overworld-enabled-{fallback_time}.h"
                config_path.write_text(
                    re.sub(
                        r"(#define\s+OW_TIME_OF_DAY_FALLBACK\s+)TIME_MORNING",
                        rf"\g<1>{fallback_time}",
                        config_source,
                    ),
                    encoding="utf-8",
                )
                output = self.generate(config_path=config_path)
                route_101 = map_entry(output, "MAP_ROUTE101")
                route_29 = map_entry(output, "MAP_ROUTE29")
                for time in times:
                    self.assertEqual(
                        land_binding(route_101, time),
                        "&gRoute101_LandMonsInfo" if time == fallback_time else "NULL",
                    )
                    expected_route_29 = "NULL"
                    if time == "TIME_NIGHT":
                        expected_route_29 = "&gRoute29_Night_LandMonsInfo"
                    elif time == fallback_time:
                        expected_route_29 = "&gRoute29_LandMonsInfo"
                    self.assertEqual(land_binding(route_29, time), expected_route_29)
                if fallback_time == "TIME_NIGHT":
                    self.assertNotIn(
                        "const struct WildPokemon gRoute29_LandMons[]", output
                    )

        disabled_config = self.root / "overworld-disabled.h"
        disabled_config.write_text(
            re.sub(
                r"(#define\s+OW_TIME_OF_DAY_ENCOUNTERS\s+)TRUE",
                r"\1FALSE",
                re.sub(
                    r"(#define\s+OW_TIME_OF_DAY_FALLBACK\s+)TIME_MORNING",
                    r"\1TIME_DAY",
                    config_source,
                ),
            ),
            encoding="utf-8",
        )
        for default_index, default_time in enumerate(times):
            with self.subTest(enabled=False, default=default_time):
                rtc_path = self.root / f"rtc-disabled-{default_index}.h"
                rtc_path.write_text(
                    re.sub(
                        r"(#define\s+TIME_OF_DAY_DEFAULT\s+)0",
                        rf"\g<1>{default_index}",
                        rtc_source,
                    ),
                    encoding="utf-8",
                )
                output = self.generate(
                    config_path=disabled_config, rtc_constants_path=rtc_path
                )
                route_101 = map_entry(output, "MAP_ROUTE101")
                route_29 = map_entry(output, "MAP_ROUTE29")
                self.assertEqual(
                    land_binding(route_101, default_time),
                    "&gRoute101_LandMonsInfo",
                )
                self.assertEqual(
                    land_binding(route_29, default_time), "&gRoute29_LandMonsInfo"
                )
                for time in set(times) - {default_time}:
                    self.assertIsNone(land_binding(route_101, time))
                    self.assertIsNone(land_binding(route_29, time))
                self.assertNotIn("gRoute29_Night", output)

        invalid_config = self.root / "overworld-invalid.h"
        invalid_config.write_text(
            re.sub(
                r"(#define\s+OW_TIME_OF_DAY_FALLBACK\s+)TIME_MORNING",
                r"\1TIME_UNKNOWN",
                config_source,
            ),
            encoding="utf-8",
        )
        self.assert_rejected_without_replacement(config_path=invalid_config)

        invalid_rtc = self.root / "rtc-invalid.h"
        invalid_rtc.write_text(
            re.sub(
                r"(#define\s+TIME_OF_DAY_DEFAULT\s+)0",
                r"\g<1>99",
                rtc_source,
            ),
            encoding="utf-8",
        )
        self.assert_rejected_without_replacement(rtc_constants_path=invalid_rtc)

    def test_time_and_altering_cave_identities_are_explicit_and_ordered(self):
        rows = [
            dict(zip(generator.PROFILE_FIELDS, row, strict=True))
            for row in self.registry["profiles"]
        ]
        by_label = {row["label"]: row for row in rows}
        self.assertEqual(by_label["gRoute29"]["time"], generator.FALLBACK_TIME_ROLE)
        self.assertEqual(by_label["gRoute29_Night"]["header"], "gRoute29")
        self.assertEqual(by_label["gRoute29_Night"]["time"], "TIME_NIGHT")
        self.assertEqual(
            [
                row["variant_index"]
                for row in rows
                if row["variant_set"] == "hoenn_altering_cave"
            ],
            list(range(9)),
        )
        self.assertEqual(
            [
                row["variant_index"]
                for row in rows
                if row["variant_set"] == "sevii_altering_cave_firered"
            ],
            list(range(9)),
        )
        self.assertEqual(
            by_label["sSixIslandAlteringCave_9_LeafGreen"]["alternate_of"],
            "sSixIslandAlteringCave_9_FireRed",
        )
        positions = {row["label"]: index for index, row in enumerate(rows)}
        for row in rows:
            if not row["label"].endswith("_LeafGreen"):
                continue
            primary = row["label"].removesuffix("_LeafGreen") + "_FireRed"
            self.assertEqual(row["alternate_of"], primary)
            self.assertLess(positions[primary], positions[row["label"]])

        encounter_by_label = {
            encounter["base_label"]: encounter
            for group in self.encounters["wild_encounter_groups"]
            for encounter in group["encounters"]
        }
        for name, authority in generator.ALTERING_CAVE_VARIANTS.items():
            variants = [row for row in rows if row["variant_set"] == name]
            self.assertEqual(
                tuple(row["label"] for row in variants), authority["labels"]
            )
            self.assertEqual([row["variant_index"] for row in variants], list(range(9)))
            self.assertTrue(
                all(
                    encounter_by_label[row["label"]]["map"] == authority["map"]
                    for row in variants
                )
            )

    def test_invalid_missing_unexpected_duplicate_and_unresolved_inputs_fail_closed(
        self,
    ):
        cases = {}

        missing = copy.deepcopy(self.registry)
        missing["profiles"].pop()
        cases["missing profile"] = (None, missing)

        coordinated_deletion_encounters = copy.deepcopy(self.encounters)
        coordinated_deletion_registry = copy.deepcopy(self.registry)
        coordinated_deletion_encounters["wild_encounter_groups"][0]["encounters"].pop(0)
        coordinated_deletion_registry["profiles"].pop(0)
        cases["coordinated inventory deletion"] = (
            coordinated_deletion_encounters,
            coordinated_deletion_registry,
        )

        swapped_maps = copy.deepcopy(self.encounters)
        route_101 = self.find_encounter(swapped_maps, "gRoute101")
        route_102 = self.find_encounter(swapped_maps, "gRoute102")
        route_101["map"], route_102["map"] = route_102["map"], route_101["map"]
        cases["swapped authored maps"] = (swapped_maps, None)

        swapped_altering_payloads = copy.deepcopy(self.encounters)
        altering_1 = self.find_encounter(swapped_altering_payloads, "gAlteringCave1")
        altering_2 = self.find_encounter(swapped_altering_payloads, "gAlteringCave2")
        altering_1["land_mons"], altering_2["land_mons"] = (
            altering_2["land_mons"],
            altering_1["land_mons"],
        )
        cases["swapped Altering Cave payloads"] = (swapped_altering_payloads, None)

        substituted_header = copy.deepcopy(self.registry)
        self.find_profile(substituted_header, "gRoute29_Night")[2] = (
            "gRoute29Unreachable"
        )
        cases["substituted header"] = (None, substituted_header)

        substituted_time = copy.deepcopy(self.registry)
        self.find_profile(substituted_time, "gRoute101")[4] = "TIME_NIGHT"
        cases["substituted time"] = (None, substituted_time)

        unexpected = copy.deepcopy(self.encounters)
        unexpected["wild_encounter_groups"][0]["encounters"][0]["product"] = "EMERALD"
        cases["product-gated field"] = (unexpected, None)

        duplicate = copy.deepcopy(self.registry)
        duplicate["profiles"][1] = copy.deepcopy(duplicate["profiles"][0])
        cases["duplicate profile"] = (None, duplicate)

        unresolved_map = copy.deepcopy(self.encounters)
        unresolved_map["wild_encounter_groups"][0]["encounters"][0]["map"] = (
            "MAP_NOT_RESIDENT"
        )
        cases["unresolved map"] = (unresolved_map, None)

        unresolved_species = copy.deepcopy(self.encounters)
        unresolved_species["wild_encounter_groups"][0]["encounters"][0]["land_mons"][
            "mons"
        ][0]["species"] = "SPECIES_NOT_RESIDENT"
        cases["unresolved species"] = (unresolved_species, None)

        invalid_variant = copy.deepcopy(self.registry)
        altering = next(
            row for row in invalid_variant["profiles"] if row[1] == "gAlteringCave5"
        )
        altering[7] = 8
        cases["invalid ordered variant"] = (None, invalid_variant)

        missing_variant_metadata = copy.deepcopy(self.registry)
        altering = self.find_profile(missing_variant_metadata, "gAlteringCave1")
        altering[6:] = [None, None]
        cases["missing Altering Cave metadata"] = (None, missing_variant_metadata)

        renamed_variant_set = copy.deepcopy(self.registry)
        self.find_profile(renamed_variant_set, "gAlteringCave1")[6] = (
            "renamed_altering_cave"
        )
        cases["renamed Altering Cave set"] = (None, renamed_variant_set)

        reassigned_variant = copy.deepcopy(self.registry)
        self.find_profile(reassigned_variant, "gAlteringCave1")[6] = (
            "sevii_altering_cave_firered"
        )
        cases["reassigned Altering Cave profile"] = (None, reassigned_variant)

        unresolved_alternate = copy.deepcopy(self.registry)
        leafgreen = next(
            row
            for row in unresolved_alternate["profiles"]
            if row[1].endswith("_LeafGreen")
        )
        leafgreen[5] = "missing_primary"
        cases["unresolved alternate"] = (None, unresolved_alternate)

        missing_leafgreen_alternate = copy.deepcopy(self.registry)
        self.find_profile(missing_leafgreen_alternate, "sViridianForest_LeafGreen")[
            5
        ] = None
        cases["missing LeafGreen alternate"] = (None, missing_leafgreen_alternate)

        reversed_encounters = copy.deepcopy(self.encounters)
        reversed_registry = copy.deepcopy(self.registry)
        group = reversed_encounters["wild_encounter_groups"][0]["encounters"]
        fire_index = next(
            index
            for index, row in enumerate(group)
            if row["base_label"] == "sViridianForest_FireRed"
        )
        leaf_index = next(
            index
            for index, row in enumerate(group)
            if row["base_label"] == "sViridianForest_LeafGreen"
        )
        group[fire_index], group[leaf_index] = group[leaf_index], group[fire_index]
        profiles = reversed_registry["profiles"]
        profiles[fire_index], profiles[leaf_index] = (
            profiles[leaf_index],
            profiles[fire_index],
        )
        cases["LeafGreen before FireRed"] = (reversed_encounters, reversed_registry)

        wrong_facility_residency = copy.deepcopy(self.registry)
        self.find_profile(wrong_facility_residency, "gBattlePyramid_1")[3] = "kanto"
        cases["wrong facility residency"] = (None, wrong_facility_residency)

        empty_profile = copy.deepcopy(self.encounters)
        encounter = self.find_encounter(empty_profile, "gRoute101")
        for mon_type in generator.Config(
            generator.DEFAULT_CONFIG,
            generator.DEFAULT_RTC_CONSTANTS,
            empty_profile,
        ).mon_types:
            encounter.pop(mon_type, None)
        cases["profile without encounter types"] = (empty_profile, None)

        invalid_level = copy.deepcopy(self.encounters)
        invalid_level["wild_encounter_groups"][0]["encounters"][0]["land_mons"]["mons"][
            0
        ]["min_level"] = 101
        cases["invalid level"] = (invalid_level, None)

        for name, (encounters, registry) in cases.items():
            with self.subTest(name=name):
                self.assert_rejected_without_replacement(encounters, registry)

    def test_missing_registry_file_leaves_output_unchanged(self):
        self.output_path.write_bytes(b"reviewed output\n")
        self.encounters_path.write_text(json.dumps(self.encounters), encoding="utf-8")
        with self.assertRaises(generator.ValidationError):
            generator.generate(
                encounters_path=self.encounters_path,
                registry_path=self.root / "missing.json",
                output_path=self.output_path,
            )
        self.assertEqual(self.output_path.read_bytes(), b"reviewed output\n")

    def test_second_primary_header_for_same_map_is_unreachable(self):
        profiles = [
            dict(zip(generator.PROFILE_FIELDS, row, strict=True))
            for row in self.registry["profiles"]
        ]
        encounter_by_label = {
            encounter["base_label"]: encounter
            for group in self.encounters["wild_encounter_groups"]
            for encounter in group["encounters"]
        }
        next(profile for profile in profiles if profile["label"] == "gRoute29_Night")[
            "header"
        ] = "gRoute29Unreachable"
        with self.assertRaises(generator.ValidationError):
            generator._validate_map_header_semantics(profiles, encounter_by_label)

    def test_valid_generation_atomically_replaces_existing_output(self):
        self.output_path.write_bytes(b"old output\n")
        self.output_path.chmod(0o640)
        old_inode = self.output_path.stat().st_ino
        output = self.generate()
        self.assertNotEqual(self.output_path.stat().st_ino, old_inode)
        self.assertEqual(self.output_path.stat().st_mode & 0o777, 0o640)
        self.assertRegex(
            output,
            re.compile(
                r"^const struct WildPokemon gRoute101_LandMons\[\] =", re.MULTILINE
            ),
        )

    def test_new_output_uses_portable_mode(self):
        self.generate()
        self.assertEqual(
            self.output_path.stat().st_mode & 0o777, generator.DEFAULT_OUTPUT_MODE
        )


if __name__ == "__main__":
    unittest.main()
