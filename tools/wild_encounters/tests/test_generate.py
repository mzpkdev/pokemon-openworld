import copy
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.wild_encounters import wild_encounters_to_header as generator


ROOT = Path(__file__).resolve().parents[3]
ENCOUNTERS = ROOT / "src/data/wild_encounters.json"
REGISTRY = ROOT / "src/data/wild_encounter_registry.json"
TIME_POLICIES = ROOT / "src/data/wild_encounter_time_policies.json"


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
        self.time_policies_path = self.root / "wild_encounter_time_policies.json"
        self.output_path = self.root / "wild_encounters.h"
        self.time_policies_path.write_text(
            json.dumps(self.route39_time_policies()), encoding="utf-8"
        )

    @staticmethod
    def route39_time_policies():
        return {
            "schema_version": 1,
            "methodFallbacks": [],
            "encounterProfiles": [
                {
                    "map": "Route39",
                    "label": "gRoute39",
                    "habitat": "land_mons",
                    "authority": "content",
                    "time": "TIME_DAY",
                },
                {
                    "map": "Route39",
                    "label": "gRoute39_Night",
                    "habitat": "land_mons",
                    "authority": "content",
                    "time": "TIME_NIGHT",
                },
            ],
            "encounterTimePolicy": [
                {
                    "map": "Route39",
                    "dayStart": "06:00",
                    "nightStart": "18:00",
                    "dayLabel": "gRoute39",
                    "nightLabel": "gRoute39_Night",
                    "fallbackLabel": "gRoute39",
                }
            ],
        }

    def test_ordinary_registry_arrays_are_not_public_runtime_authority(self):
        public_header = (ROOT / "include/wild_encounter.h").read_text(encoding="utf-8")
        self.assertNotIn(
            "extern const struct WildPokemonHeader gWildMonHeaders", public_header
        )
        self.assertNotIn(
            "extern const struct WildEncounterTimePolicy gWildMonHeaderTimePolicies",
            public_header,
        )

        direct_consumers = []
        source_root = ROOT / "src"
        for source in source_root.rglob("*.c"):
            if source.relative_to(ROOT).as_posix() == "src/wild_encounter.c":
                continue
            text = source.read_text(encoding="utf-8")
            if "gWildMonHeaders" in text or "gWildMonHeaderTimePolicies" in text:
                direct_consumers.append(source.relative_to(ROOT).as_posix())
        self.assertEqual(direct_consumers, [])

    def test_pokedex_resolves_display_bucket_through_map_policy(self):
        contents = (ROOT / "src/pokedex_area_screen.c").read_text(encoding="utf-8")
        self.assertIn("ResolveWildEncounterDisplayTime(i, gAreaTimeOfDay)", contents)
        self.assertNotIn("TryGetWildEncounterTypes(i, gAreaTimeOfDay", contents)

    def test_both_altering_cave_domains_use_independent_selectors(self):
        runtime = (ROOT / "src/wild_encounter.c").read_text(encoding="utf-8")
        area_screen = (ROOT / "src/pokedex_area_screen.c").read_text(encoding="utf-8")
        self.assertIn("MAP_SIX_ISLAND_ALTERING_CAVE", runtime)
        self.assertIn("VAR_ALTERING_CAVE_WILD_SET_FRLG", runtime)
        self.assertIn("MAPSEC_ALTERING_CAVE_FRLG", area_screen)
        self.assertIn("VAR_ALTERING_CAVE_WILD_SET_FRLG", area_screen)

    def generate(
        self,
        encounters=None,
        registry=None,
        config_path=None,
        rtc_constants_path=None,
        time_policies_path=None,
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
            time_policies_path=(
                self.time_policies_path
                if time_policies_path is None
                else time_policies_path
            ),
            enforce_reviewed_method_fallbacks=False,
        )
        return self.output_path.read_text(encoding="utf-8")

    def assert_rejected_without_replacement(
        self,
        encounters=None,
        registry=None,
        config_path=None,
        rtc_constants_path=None,
        time_policies_path=None,
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
                time_policies_path=(
                    self.time_policies_path
                    if time_policies_path is None
                    else time_policies_path
                ),
                enforce_reviewed_method_fallbacks=False,
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
        self.assertEqual(len(profiles), 547)
        self.assertEqual(
            {
                residency: sum(row[3] == residency for row in profiles)
                for residency in generator.RESIDENCIES
            },
            {"hoenn": 136, "kanto": 132, "sevii": 132, "johto": 147},
        )
        self.assertIsNone(generator.PRODUCT_GUARD.search(output))
        self.assertEqual(output.count("const struct WildPokemonHeader "), 3)
        self.assertIn("static const struct WildPokemonHeader gWildMonHeaders[]", output)
        self.assertIn(
            "static const struct WildEncounterRegistry sWildEncounterRegistry", output
        )
        self.assertIn(".count = ARRAY_COUNT(gWildMonHeaders),", output)
        self.assertIn("WildEncounterRegistryParallelArraysMustMatch", output)
        self.assertNotIn("WildEncounterAuthored", output)
        self.assertNotIn("WILD_ENCOUNTER_AUTHORED_PROFILE_COUNT", output)
        self.assertIn(
            "{ REGIONAL_FACT_HOENN_STONE_BADGE, FLAG_BADGE01_GET, 0, "
            "TRAINER_RATING_SOURCE_BADGE },",
            output,
        )
        self.assertIn(
            "{ REGIONAL_FACT_KANTO_CASCADE_BADGE, "
            "TRAINER_RATING_LEGACY_FLAG_NONE, 0, "
            "TRAINER_RATING_SOURCE_BADGE },",
            output,
        )
        self.assertIn(".maximumRating = 46,", output)
        ordinary_headers = output.split(
            "static const struct WildEncounterTimePolicy", 1
        )[0].split("static const struct WildPokemonHeader gWildMonHeaders[]", 1)[1]
        self.assertNotIn("MAP_GROUP(MAP_UNDEFINED)", ordinary_headers)
        self.assertEqual(output.count(".mapGroup = MAP_GROUP(MAP_UNDEFINED),"), 2)
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

    def test_vermilion_old_rod_uses_one_firered_canonical_profile(self):
        fire_red = self.find_encounter(self.encounters, "sVermilionCity_FireRed")
        leaf_green = self.find_encounter(self.encounters, "sVermilionCity_LeafGreen")
        fishing_field = next(
            field
            for field in self.encounters["wild_encounter_groups"][0]["fields"]
            if field["type"] == "fishing_mons"
        )
        old_rod_slots = fishing_field["groups"]["old_rod"]
        self.assertEqual(old_rod_slots, [0, 1])
        self.assertEqual(
            [fishing_field["encounter_rates"][slot] for slot in old_rod_slots],
            [70, 30],
        )

        def old_rod_projection(encounter):
            fishing = encounter["fishing_mons"]
            return {
                "encounter_rate": fishing["encounter_rate"],
                "mons": [fishing["mons"][slot] for slot in old_rod_slots],
            }

        fire_red_projection = old_rod_projection(fire_red)
        leaf_green_projection = old_rod_projection(leaf_green)
        self.assertEqual(
            json.dumps(
                fire_red_projection, sort_keys=True, separators=(",", ":")
            ).encode(),
            json.dumps(
                leaf_green_projection, sort_keys=True, separators=(",", ":")
            ).encode(),
        )
        self.assertEqual(
            fire_red_projection,
            {
                "encounter_rate": 10,
                "mons": [
                    {
                        "min_level": 5,
                        "max_level": 5,
                        "species": "SPECIES_MAGIKARP",
                    },
                    {
                        "min_level": 5,
                        "max_level": 5,
                        "species": "SPECIES_MAGIKARP",
                    },
                ],
            },
        )
        self.assertIsNone(self.find_profile(self.registry, "sVermilionCity_FireRed")[5])
        self.assertEqual(
            self.find_profile(self.registry, "sVermilionCity_LeafGreen")[5],
            "sVermilionCity_FireRed",
        )
        output = self.generate()
        self.assertIn("sVermilionCity_FireRed_FishingMons", output)
        self.assertNotIn("sVermilionCity_LeafGreen", output)

    def test_route39_profiles_use_target_time_and_fallback_roles(self):
        day = self.find_encounter(self.encounters, "gRoute39")
        night = self.find_encounter(self.encounters, "gRoute39_Night")
        self.assertEqual(
            (day["land_mons"]["encounter_rate"], night["land_mons"]["encounter_rate"]),
            (20, 20),
        )
        self.assertEqual(
            (len(day["land_mons"]["mons"]), len(night["land_mons"]["mons"])),
            (12, 12),
        )
        self.assertEqual(
            self.find_profile(self.registry, "gRoute39")[4],
            generator.FALLBACK_TIME_ROLE,
        )
        self.assertEqual(
            self.find_profile(self.registry, "gRoute39_Night")[2:5],
            ["gRoute39", "johto", "TIME_NIGHT"],
        )
        output = self.generate()
        self.assertIn("const struct WildPokemon gRoute39_LandMons[]", output)
        self.assertIn("const struct WildPokemon gRoute39_Night_LandMons[]", output)
        route_39_start = output.index(".mapGroup = MAP_GROUP(MAP_ROUTE39),")
        route_39_end = output.index(".mapGroup = ", route_39_start + 1)
        route_39 = output[route_39_start:route_39_end]
        self.assertRegex(
            route_39,
            re.compile(
                r"\[TIME_DAY\].*?&gRoute39_LandMonsInfo.*?"
                r"\[TIME_NIGHT\].*?&gRoute39_Night_LandMonsInfo",
                re.DOTALL,
            ),
        )
        self.assertIn(".dayStartMinutes = 360,", output)
        self.assertIn(".nightStartMinutes = 1080,", output)
        self.assertIn(".dayTime = TIME_DAY,", output)
        self.assertIn(".nightTime = TIME_NIGHT,", output)

    def test_runtime_time_policies_accept_multiple_canonical_maps(self):
        policy = self.route39_time_policies()
        policy["encounterProfiles"].extend(
            [
                {
                    "map": "Route29",
                    "label": "gRoute29",
                    "habitat": "land_mons",
                    "authority": "content",
                    "time": "TIME_DAY",
                },
                {
                    "map": "Route29",
                    "label": "gRoute29_Night",
                    "habitat": "land_mons",
                    "authority": "content",
                    "time": "TIME_NIGHT",
                },
            ]
        )
        policy["encounterTimePolicy"].append(
            {
                "map": "Route29",
                "dayStart": "06:00",
                "nightStart": "18:00",
                "dayLabel": "gRoute29",
                "nightLabel": "gRoute29_Night",
                "fallbackLabel": "gRoute29",
            }
        )
        policy_path = self.root / "multiple-time-policies.json"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")

        output = self.generate(time_policies_path=policy_path)

        route_29_start = output.index(".mapGroup = MAP_GROUP(MAP_ROUTE29),")
        route_29_end = output.index(".mapGroup = ", route_29_start + 1)
        route_29 = output[route_29_start:route_29_end]
        self.assertRegex(
            route_29,
            re.compile(
                r"\[TIME_DAY\].*?&gRoute29_LandMonsInfo.*?"
                r"\[TIME_NIGHT\].*?&gRoute29_Night_LandMonsInfo",
                re.DOTALL,
            ),
        )
        self.assertEqual(output.count(".dayStartMinutes = 360,"), 2)
        self.assertEqual(output.count(".nightStartMinutes = 1080,"), 2)

    def test_runtime_time_policy_map_names_resolve_through_map_json_authority(self):
        identities = (
            ("Route26North", "MAP_ROUTE26NORTH", "gRoute26North"),
            (
                "JohtoVictoryRoad_1F",
                "MAP_JOHTO_VICTORY_ROAD_1F",
                "gJohtoVictoryRoad_1F",
            ),
        )
        policy = {
            "schema_version": 1,
            "encounterProfiles": [],
            "encounterTimePolicy": [],
            "methodFallbacks": [],
        }
        profiles = []
        encounters = {
            "wild_encounter_groups": [{"encounters": []}],
        }
        for map_name, map_id, label in identities:
            night_label = f"{label}_Night"
            policy["encounterProfiles"].extend(
                [
                    {
                        "map": map_name,
                        "label": label,
                        "habitat": "land_mons",
                        "authority": "content",
                        "time": "TIME_DAY",
                    },
                    {
                        "map": map_name,
                        "label": night_label,
                        "habitat": "land_mons",
                        "authority": "content",
                        "time": "TIME_NIGHT",
                    },
                ]
            )
            policy["encounterTimePolicy"].append(
                {
                    "map": map_name,
                    "dayStart": "06:00",
                    "nightStart": "18:00",
                    "dayLabel": label,
                    "nightLabel": night_label,
                    "fallbackLabel": label,
                }
            )
            profiles.extend(
                [
                    {
                        "group": "gWildMonHeaders",
                        "label": label,
                        "header": label,
                        "time": generator.FALLBACK_TIME_ROLE,
                        "alternate_of": None,
                    },
                    {
                        "group": "gWildMonHeaders",
                        "label": night_label,
                        "header": label,
                        "time": "TIME_NIGHT",
                        "alternate_of": None,
                    },
                ]
            )
            encounters["wild_encounter_groups"][0]["encounters"].extend(
                [
                    {"base_label": label, "map": map_id, "land_mons": {}},
                    {
                        "base_label": night_label,
                        "map": map_id,
                        "land_mons": {},
                    },
                ]
            )

        policy_path = self.root / "canonical-map-time-policies.json"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        config = generator.Config(
            generator.DEFAULT_CONFIG,
            generator.DEFAULT_RTC_CONSTANTS,
            self.encounters,
        )
        maps = generator._load_map_authority(
            generator.DEFAULT_MAP_GROUPS,
            generator.DEFAULT_MAPS_ROOT,
            generator.DEFAULT_MAP_SECTIONS,
        )

        labels, headers = generator._load_time_policies(
            policy_path, profiles, encounters, config, maps
        )

        self.assertEqual(set(headers), {identity[2] for identity in identities})
        self.assertEqual(
            {label: value["time"] for label, value in labels.items()},
            {
                **{identity[2]: "TIME_DAY" for identity in identities},
                **{f"{identity[2]}_Night": "TIME_NIGHT" for identity in identities},
            },
        )

        for map_name, _, label in identities:
            wrong_map_id = (
                "MAP_ROUTE26_NORTH"
                if map_name == "Route26North"
                else "MAP_JOHTO_VICTORY_ROAD_1_F"
            )
            with self.subTest(map_name=map_name, wrong_map_id=wrong_map_id):
                invalid_encounters = copy.deepcopy(encounters)
                next(
                    encounter
                    for encounter in invalid_encounters["wild_encounter_groups"][0][
                        "encounters"
                    ]
                    if encounter["base_label"] == label
                )["map"] = wrong_map_id
                with self.assertRaises(generator.ValidationError):
                    generator._load_time_policies(
                        policy_path, profiles, invalid_encounters, config, maps
                    )

    def test_compiled_route39_policy_resolves_every_minute_and_boundaries(self):
        source = self.root / "route39_policy_test.c"
        executable = self.root / "route39_policy_test"
        source.write_text(
            """
#include "wild_encounter_time_policy.h"

int main(void)
{
    unsigned short minute;
    const unsigned char day = 1;
    const unsigned char night = 3;

    for (minute = 0; minute < 1440; minute++)
    {
        unsigned char expected = minute >= 360 && minute < 1080 ? day : night;
        if (ResolveWildEncounterPolicyTime(minute, 360, 1080, day, night) != expected)
            return 1;
    }
    if (ResolveWildEncounterPolicyTime(359, 360, 1080, day, night) != night)
        return 2;
    if (ResolveWildEncounterPolicyTime(360, 360, 1080, day, night) != day)
        return 3;
    if (ResolveWildEncounterPolicyTime(1079, 360, 1080, day, night) != day)
        return 4;
    if (ResolveWildEncounterPolicyTime(1080, 360, 1080, day, night) != night)
        return 5;
    if (ResolveWildEncounterPolicyTime(
            ResolveApparentTimeMinutes(5, 59, 18), 360, 1080, day, night) != night)
        return 6;
    if (ResolveWildEncounterPolicyTime(
            ResolveApparentTimeMinutes(5, 59, 6), 360, 1080, day, night) != day)
        return 7;
    if (ResolveApparentTimeMinutes(5, 59, 18) != 18 * 60)
        return 8;
    if (ResolveApparentTimeMinutes(5, 59, 6) != 6 * 60)
        return 9;
    if (ResolveApparentTimeMinutes(5, 59, 0) != 5 * 60 + 59)
        return 10;
    if (ResolveWildEncounterPolicyTime(
            ResolveApparentTimeMinutes(5, 59, 0), 360, 1080, day, night) != night)
        return 11;
    return 0;
}
""",
            encoding="utf-8",
        )
        subprocess.run(
            [
                "cc",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(ROOT / "include"),
                str(source),
                "-o",
                str(executable),
            ],
            check=True,
        )
        subprocess.run([str(executable)], check=True)

    def test_invalid_route39_runtime_policy_fails_before_output_replacement(self):
        policy = self.route39_time_policies()
        policy["encounterTimePolicy"][0]["nightStart"] = "24:00"
        policy_path = self.root / "invalid-time-policies.json"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        self.assert_rejected_without_replacement(time_policies_path=policy_path)

        policy["encounterTimePolicy"] = []
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        self.assert_rejected_without_replacement(time_policies_path=policy_path)

        for field, value in (
            ("dayStart", "05:59"),
            ("nightStart", "18:01"),
            ("fallbackLabel", "gRoute39_Night"),
        ):
            with self.subTest(field=field, value=value):
                policy = self.route39_time_policies()
                policy["encounterTimePolicy"][0][field] = value
                policy_path.write_text(json.dumps(policy), encoding="utf-8")
                self.assert_rejected_without_replacement(time_policies_path=policy_path)

        for schema_version in (True, 2):
            with self.subTest(schema_version=schema_version):
                policy = self.route39_time_policies()
                policy["schema_version"] = schema_version
                policy_path.write_text(json.dumps(policy), encoding="utf-8")
                self.assert_rejected_without_replacement(time_policies_path=policy_path)

        policy = self.route39_time_policies()
        policy["unexpected"] = []
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        self.assert_rejected_without_replacement(time_policies_path=policy_path)

        policy = self.route39_time_policies()
        extra = copy.deepcopy(policy["encounterProfiles"][0])
        extra["label"] = "gUnconsumedRoute39Evidence"
        policy["encounterProfiles"].append(extra)
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        self.assert_rejected_without_replacement(time_policies_path=policy_path)

        for label, wrong_time in (
            ("gRoute39", "TIME_MORNING"),
            ("gRoute39_Night", "TIME_EVENING"),
        ):
            with self.subTest(label=label, wrong_time=wrong_time):
                policy = self.route39_time_policies()
                next(
                    profile
                    for profile in policy["encounterProfiles"]
                    if profile["label"] == label
                )["time"] = wrong_time
                policy_path.write_text(json.dumps(policy), encoding="utf-8")
                self.assert_rejected_without_replacement(time_policies_path=policy_path)

    def test_production_requires_exact_reviewed_method_fallback_set(self):
        policy = json.loads(TIME_POLICIES.read_text(encoding="utf-8"))
        mutations = []

        missing = copy.deepcopy(policy)
        missing["methodFallbacks"] = missing["methodFallbacks"][1:]
        mutations.append(missing)

        extra = copy.deepcopy(policy)
        reversed_row = copy.deepcopy(extra["methodFallbacks"][0])
        reversed_row["missingCondition"], reversed_row["sourceCondition"] = (
            reversed_row["sourceCondition"],
            reversed_row["missingCondition"],
        )
        extra["methodFallbacks"].append(reversed_row)
        mutations.append(extra)

        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                policy_path = self.root / f"invalid-reviewed-fallbacks-{index}.json"
                policy_path.write_text(json.dumps(mutation), encoding="utf-8")
                self.output_path.write_bytes(b"reviewed output\n")
                with self.assertRaises(generator.ValidationError):
                    generator.generate(
                        output_path=self.output_path,
                        time_policies_path=policy_path,
                    )
                self.assertEqual(self.output_path.read_bytes(), b"reviewed output\n")

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
                route_39 = map_entry(output, "MAP_ROUTE39")
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
                    expected_route_39 = {
                        "TIME_DAY": "&gRoute39_LandMonsInfo",
                        "TIME_NIGHT": "&gRoute39_Night_LandMonsInfo",
                    }.get(time, "NULL")
                    self.assertEqual(land_binding(route_39, time), expected_route_39)
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
                route_39 = map_entry(output, "MAP_ROUTE39")
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
                self.assertEqual(
                    land_binding(route_39, "TIME_DAY"),
                    "&gRoute39_LandMonsInfo",
                )
                self.assertEqual(
                    land_binding(route_39, "TIME_NIGHT"),
                    "&gRoute39_Night_LandMonsInfo",
                )

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


class WildEncounterSpeciesMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.authority_path = self.root / "wild_encounter_species.json"
        self.species_info_path = self.root / "species_info.h"
        self.known_species = {
            "SPECIES_ALPHA",
            "SPECIES_BETA",
            "SPECIES_GAMMA",
            "SPECIES_DELTA",
        }
        self.ordinary_species = {"SPECIES_BETA"}

    def write_authority(self, minimum_levels=None, resolutions=None):
        self.authority_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "minimumOrdinaryWildLevels": (
                        [] if minimum_levels is None else minimum_levels
                    ),
                    "predecessorResolutions": []
                    if resolutions is None
                    else resolutions,
                }
            ),
            encoding="utf-8",
        )

    def write_species_info(
        self, alpha_evolutions, gamma_evolutions="", beta_evolutions=""
    ):
        self.species_info_path.write_text(
            "\n".join(
                (
                    "#define EVOLUTION(...) (const struct Evolution[]) { __VA_ARGS__, { EVOLUTIONS_END }, }",
                    "#define CONDITIONS(...) ((const struct EvolutionParam[]) { __VA_ARGS__, { CONDITIONS_END } })",
                    "[SPECIES_ALPHA] = { .evolutions = EVOLUTION(",
                    alpha_evolutions,
                    "), };",
                    "[SPECIES_GAMMA] = { .evolutions = EVOLUTION(",
                    gamma_evolutions,
                    "), };",
                    "[SPECIES_BETA] = { .evolutions = EVOLUTION(",
                    beta_evolutions,
                    "), };",
                    "[SPECIES_DELTA] = { };",
                )
            ),
            encoding="utf-8",
        )

    def load_metadata(self):
        return generator._load_wild_encounter_species_metadata(
            self.authority_path,
            self.species_info_path,
            self.known_species,
            self.ordinary_species,
        )

    def test_conditional_positive_level_edge_and_explicit_floor_are_generated(self):
        self.write_authority(
            minimum_levels=[{"species": "SPECIES_BETA", "minimumOrdinaryWildLevel": 12}]
        )
        self.write_species_info(
            "{EVO_LEVEL, 20, SPECIES_BETA, CONDITIONS({IF_TIME, TIME_DAY})}"
        )

        self.assertEqual(
            self.load_metadata(),
            [
                {
                    "species": "SPECIES_ALPHA",
                    "minimum_level": 1,
                    "predecessor": "SPECIES_NONE",
                    "predecessor_level": 0,
                    "has_alternate_non_level_route": False,
                },
                {
                    "species": "SPECIES_BETA",
                    "minimum_level": 12,
                    "predecessor": "SPECIES_ALPHA",
                    "predecessor_level": 20,
                    "has_alternate_non_level_route": False,
                },
            ],
        )

    def test_alternate_non_level_route_is_explicit(self):
        self.write_authority()
        self.write_species_info(
            "{EVO_LEVEL, 20, SPECIES_BETA},{EVO_ITEM, ITEM_TEST, SPECIES_BETA}"
        )

        self.assertTrue(self.load_metadata()[1]["has_alternate_non_level_route"])

    def test_numeric_predecessor_closure_emits_all_recursive_ancestors(self):
        self.write_authority(
            minimum_levels=[{"species": "SPECIES_GAMMA", "minimumOrdinaryWildLevel": 7}]
        )
        self.write_species_info(
            "{EVO_LEVEL, 20, SPECIES_BETA}",
            "{EVO_LEVEL, 10, SPECIES_ALPHA}",
        )

        metadata = {row["species"]: row for row in self.load_metadata()}
        self.assertEqual(
            set(metadata), {"SPECIES_ALPHA", "SPECIES_BETA", "SPECIES_GAMMA"}
        )
        self.assertEqual(metadata["SPECIES_BETA"]["predecessor"], "SPECIES_ALPHA")
        self.assertEqual(metadata["SPECIES_ALPHA"]["predecessor"], "SPECIES_GAMMA")
        self.assertEqual(metadata["SPECIES_GAMMA"]["minimum_level"], 7)

    def test_ambiguous_predecessor_requires_and_accepts_narrow_resolution(self):
        self.write_authority()
        self.write_species_info(
            "{EVO_LEVEL, 20, SPECIES_BETA}",
            "{EVO_LEVEL, 30, SPECIES_BETA}",
        )
        with self.assertRaisesRegex(generator.ValidationError, "ambiguous numeric"):
            self.load_metadata()

        self.write_authority(
            resolutions=[
                {
                    "species": "SPECIES_BETA",
                    "predecessorSpecies": "SPECIES_GAMMA",
                    "predecessorLevel": 30,
                }
            ]
        )
        metadata = next(
            metadata
            for metadata in self.load_metadata()
            if metadata["species"] == "SPECIES_BETA"
        )
        self.assertEqual(metadata["predecessor"], "SPECIES_GAMMA")
        self.assertEqual(metadata["predecessor_level"], 30)

    def test_invalid_metadata_and_evolution_graph_fail_closed(self):
        self.write_species_info("{EVO_LEVEL, 20, SPECIES_BETA}")
        cases = (
            (
                {
                    "schemaVersion": 1,
                    "minimumOrdinaryWildLevels": [
                        {
                            "species": "SPECIES_BETA",
                            "minimumOrdinaryWildLevel": 0,
                        }
                    ],
                    "predecessorResolutions": [],
                },
                "expected integer",
            ),
            (
                {
                    "schemaVersion": 1,
                    "minimumOrdinaryWildLevels": [
                        {
                            "species": "SPECIES_DELTA",
                            "minimumOrdinaryWildLevel": 1,
                        }
                    ],
                    "predecessorResolutions": [],
                },
                "not reachable",
            ),
            (
                {
                    "schemaVersion": 1,
                    "minimumOrdinaryWildLevels": [],
                    "predecessorResolutions": [
                        {
                            "species": "SPECIES_BETA",
                            "predecessorSpecies": "SPECIES_ALPHA",
                            "predecessorLevel": 20,
                        }
                    ],
                },
                "requires an ambiguous",
            ),
        )
        for authority, message in cases:
            with self.subTest(authority=authority):
                self.authority_path.write_text(json.dumps(authority), encoding="utf-8")
                with self.assertRaisesRegex(generator.ValidationError, message):
                    self.load_metadata()

        self.write_authority()
        self.write_species_info(
            "{EVO_LEVEL, 20, SPECIES_BETA}",
            beta_evolutions="{EVO_LEVEL, 30, SPECIES_ALPHA}",
        )
        with self.assertRaisesRegex(generator.ValidationError, "cycle"):
            self.load_metadata()


class TrainerRatingScalingTests(unittest.TestCase):
    def load_scaling(self, document):
        with tempfile.TemporaryDirectory() as temporary:
            scaling_path = Path(temporary) / "wild_encounter_scaling.json"
            scaling_path.write_text(json.dumps(document), encoding="utf-8")
            return generator._load_scaling(
                scaling_path, generator.DEFAULT_REGIONAL_FACTS
            )

    def test_legacy_fallbacks_are_limited_to_authenticated_hoenn_badges(self):
        document = json.loads(generator.DEFAULT_SCALING.read_text(encoding="utf-8"))
        scaling = self.load_scaling(document)
        fallbacks = {
            source["id"]: source["legacy_fallback_flag"]
            for source in scaling["sources"]
            if source["legacy_fallback_flag"] != "TRAINER_RATING_LEGACY_FLAG_NONE"
        }
        self.assertEqual(
            fallbacks,
            {
                "REGIONAL_FACT_HOENN_STONE_BADGE": "FLAG_BADGE01_GET",
                "REGIONAL_FACT_HOENN_KNUCKLE_BADGE": "FLAG_BADGE02_GET",
                "REGIONAL_FACT_HOENN_DYNAMO_BADGE": "FLAG_BADGE03_GET",
                "REGIONAL_FACT_HOENN_HEAT_BADGE": "FLAG_BADGE04_GET",
                "REGIONAL_FACT_HOENN_BALANCE_BADGE": "FLAG_BADGE05_GET",
                "REGIONAL_FACT_HOENN_FEATHER_BADGE": "FLAG_BADGE06_GET",
                "REGIONAL_FACT_HOENN_MIND_BADGE": "FLAG_BADGE07_GET",
                "REGIONAL_FACT_HOENN_RAIN_BADGE": "FLAG_BADGE08_GET",
            },
        )

        document["trainerRating"]["sources"][1]["legacyFallbackFlag"] = (
            "FLAG_BADGE02_GET"
        )
        with self.assertRaisesRegex(
            generator.ValidationError, "only authenticated Hoenn"
        ):
            self.load_scaling(document)

    def test_configured_rating_total_may_exceed_the_projection_cap(self):
        document = json.loads(generator.DEFAULT_SCALING.read_text(encoding="utf-8"))
        document["trainerRating"]["sources"][-1]["value"] = 255

        scaling = self.load_scaling(document)

        self.assertEqual(scaling["projection_cap"], 80)
        self.assertEqual(scaling["maximum_rating"], 300)
        self.assertEqual(len(scaling["points"]), 81)


class WildEncounterBalanceAuditTests(unittest.TestCase):
    def test_audit_reports_a_profile_that_loses_every_eligible_slot(self):
        scaling = generator._load_scaling(
            generator.DEFAULT_SCALING, generator.DEFAULT_REGIONAL_FACTS
        )
        _, _, failures = generator._audit_profile_slots(
            "gTest",
            "land_mons",
            "NONE",
            {
                "land_mons": {
                    "mons": [
                        {
                            "species": "SPECIES_TEST",
                            "min_level": 2,
                            "max_level": 2,
                        }
                    ]
                }
            },
            [100],
            scaling,
            0,
            {
                "SPECIES_TEST": {
                    "minimum_level": 100,
                    "predecessor": "SPECIES_NONE",
                    "predecessor_level": 0,
                    "has_alternate_non_level_route": False,
                }
            },
        )

        self.assertIn(
            "gTest/land_mons/NONE: all slots are locked at rating 0", failures
        )

    def test_audit_covers_required_ratings_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_path = Path(temporary) / "wild-encounter-balance-audit.json"
            first = generator.generate_wild_encounter_balance_audit(output_path)
            rendered = output_path.read_bytes()
            second = generator.generate_wild_encounter_balance_audit(output_path)

        self.assertEqual(first, second)
        self.assertEqual(
            rendered,
            json.dumps(second, ensure_ascii=True, indent=2, sort_keys=True).encode()
            + b"\n",
        )
        self.assertEqual(first["ratings"], list(generator.REQUIRED_AUDIT_RATINGS))
        self.assertTrue(first["invariants"]["passed"])
        self.assertEqual(first["invariants"]["failures"], [])
        self.assertGreater(len(first["profiles"]), 0)

        route101 = next(
            profile
            for profile in first["profiles"]
            if profile["label"] == "gRoute101"
            and profile["method"] == "land_mons"
            and profile["fishingRod"] == "NONE"
        )
        matrix = route101["matrix"]
        self.assertEqual(matrix[0]["totalWeight"], 100)
        self.assertEqual(matrix[0]["eligibleWeight"], 100)
        self.assertEqual(
            set(matrix[0]),
            {
                "rating",
                "original",
                "effective",
                "stageChanges",
                "lockedSlots",
                "eligibleSlotCount",
                "lockedSlotCount",
                "unlockRatings",
                "totalWeight",
                "eligibleWeight",
                "lockedWeight",
                "renormalizedProbabilities",
                "slotOutcomes",
            },
        )
        self.assertEqual(
            sum(
                probability["numerator"]
                for probability in matrix[0]["renormalizedProbabilities"]
            ),
            matrix[0]["eligibleWeight"],
        )
        self.assertTrue(
            all(
                probability["denominator"] == matrix[0]["eligibleWeight"]
                for probability in matrix[0]["renormalizedProbabilities"]
            )
        )
        self.assertIn("weightedAverage", matrix[0]["original"])
        self.assertIn("weightedAverage", matrix[0]["effective"])
        self.assertTrue(
            all(
                "startsLocked" in slot and "unlockRating" in slot
                for slot in route101["slots"]
            )
        )

    def test_audit_fails_when_strict_profile_ordering_inverts(self):
        def matrix(minimum, maximum):
            return [
                {
                    "rating": rating,
                    "original": {
                        "minimumLevel": minimum,
                        "maximumLevel": maximum,
                    },
                    "effective": {
                        "minimumLevel": minimum,
                        "maximumLevel": maximum,
                    },
                }
                for rating in generator.REQUIRED_AUDIT_RATINGS
            ]

        weaker = {
            "label": "gWeaker",
            "headerId": 1,
            "method": "land_mons",
            "fishingRod": "NONE",
            "matrix": matrix(2, 4),
        }
        stronger = {
            "label": "gStronger",
            "headerId": 2,
            "method": "land_mons",
            "fishingRod": "NONE",
            "matrix": matrix(5, 7),
        }
        stronger["matrix"][0]["effective"]["minimumLevel"] = 3

        failures = generator._cross_profile_ordering_failures([weaker, stronger])

        self.assertEqual(len(failures), 1)
        self.assertIn(
            "gWeaker above the strictly stronger vanilla profile gStronger", failures[0]
        )


if __name__ == "__main__":
    unittest.main()
