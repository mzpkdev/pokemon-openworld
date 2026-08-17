import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.wild_encounters import johto_population as projection


ROOT = Path(__file__).resolve().parents[3]


class JohtoPopulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.classification = cls.load(projection.DEFAULT_CLASSIFICATION)
        cls.ecology = cls.load(projection.DEFAULT_ECOLOGY)
        cls.fallbacks = cls.load(projection.DEFAULT_FALLBACKS)
        cls.encounters = cls.load(projection.DEFAULT_ENCOUNTERS)
        cls.registry = cls.load(projection.DEFAULT_REGISTRY)
        cls.bands = cls.load(projection.DEFAULT_BANDS)
        cls.map_ids = projection._map_ids(
            cls.classification, projection.DEFAULT_MAPS_ROOT
        )
        cls.ecology_source = cls.source_document()
        cls.outputs = projection.project_documents(
            cls.classification,
            cls.ecology,
            cls.fallbacks,
            cls.encounters,
            cls.registry,
            cls.bands,
            cls.map_ids,
            cls.ecology_source,
        )

    @staticmethod
    def load(path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    @classmethod
    def source_document(cls):
        if projection.DEFAULT_ECOLOGY_SOURCE.is_file():
            return cls.load(projection.DEFAULT_ECOLOGY_SOURCE)
        return projection._verified_checked_in_ecology_source(
            cls.encounters, cls.fallbacks
        )

    @property
    def projected_encounters(self):
        return self.outputs[0]["wild_encounter_groups"][0]["encounters"]

    def encounter(self, label):
        return next(
            row for row in self.projected_encounters if row["base_label"] == label
        )

    def test_anomaly_rules_preserve_normalized_standard_rows(self):
        new_bark = self.encounter("gNewBarkTown")
        self.assertNotIn("land_mons", new_bark)
        self.assertEqual(len(new_bark["water_mons"]["mons"]), 5)
        self.assertNotIn("water_mons", self.encounter("gMtSilver_1F_ItemRoom"))
        self.assertNotIn("water_mons", self.encounter("gMtSilver_MountainSide"))

        labels = {row["base_label"] for row in self.projected_encounters}
        self.assertIn("gMtSilver_Snow", labels)
        self.assertIn("gMtSilver_Snow_Night", labels)
        self.assertNotIn("gMtSilver_SnowUnused", labels)
        self.assertNotIn("gMtSilver_SnowNight", labels)

    def test_only_null_overflow_can_be_truncated(self):
        method = copy.deepcopy(self.ecology["records"][0]["profiles"][0]["methods"][1])
        self.assertEqual(len(method["slots"]), 12)
        self.assertEqual(len(projection._trim_method(method, "test")["slots"]), 5)
        method["slots"][5]["weight"] = 1
        with self.assertRaisesRegex(projection.ProjectionError, "non-null overflow"):
            projection._trim_method(method, "test")

    def test_fallbacks_use_target_not_source_identities(self):
        targets = {row["targetName"]: row for row in self.fallbacks["records"]}
        aliases = {
            row["map"] for row in self.classification["maps"] if row["kind"] == "alias"
        }
        self.assertEqual(set(targets), aliases)
        alias_ids = {self.map_ids[name] for name in aliases}
        direct_labels = {
            profile["label"]
            for record in self.ecology["records"]
            for profile in record["profiles"]
        }
        target_labels = [
            binding["targetLabel"]
            for fallback in targets.values()
            for binding in fallback["profiles"]
        ]
        self.assertEqual(len(target_labels), len(set(target_labels)))
        self.assertTrue(direct_labels.isdisjoint(target_labels))
        for name, fallback in targets.items():
            self.assertNotIn(fallback["sourceMap"], alias_ids)
            for binding in fallback["profiles"]:
                encounter = self.encounter(binding["targetLabel"])
                self.assertEqual(encounter["map"], fallback["targetMap"])
                self.assertEqual(encounter["map"], self.map_ids[name])
                if binding["sourceLabel"] != binding["targetLabel"]:
                    target_rows = [
                        row
                        for row in self.projected_encounters
                        if row["map"] == fallback["targetMap"]
                    ]
                    self.assertNotIn(
                        binding["sourceLabel"],
                        {row["base_label"] for row in target_rows},
                    )

    def test_projection_requires_the_exact_approved_fallback_evidence(self):
        changed = copy.deepcopy(self.fallbacks)
        changed["records"][0]["rationale"] += " Unreviewed change."
        with self.assertRaisesRegex(
            projection.ProjectionError, "pinned fallback evidence"
        ):
            projection.project_documents(
                self.classification,
                self.ecology,
                changed,
                self.encounters,
                self.registry,
                self.bands,
                self.map_ids,
                self.ecology_source,
            )

    def test_projection_rejects_classification_alias_set_drift(self):
        changed = copy.deepcopy(self.classification)
        by_name = {row["map"]: row for row in changed["maps"]}
        by_name["LakeOfRageLowTide"]["kind"] = "encounter-free"
        by_name["MahoganyTown_Gym"]["kind"] = "alias"
        with self.assertRaisesRegex(projection.ProjectionError, "fallback target"):
            projection.project_documents(
                changed,
                self.ecology,
                self.fallbacks,
                self.encounters,
                self.registry,
                self.bands,
                self.map_ids,
                self.ecology_source,
            )

    def test_all_ordinary_maps_are_eligible_and_exclusions_have_no_johto_rows(self):
        kinds = {row["map"]: row["kind"] for row in self.classification["maps"]}
        johto_rows = [row for row in self.outputs[1]["profiles"] if row[3] == "johto"]
        labels = {row[1] for row in johto_rows}
        encounter_rows = [
            row for row in self.projected_encounters if row["base_label"] in labels
        ]
        maps = {row["map"] for row in encounter_rows}
        direct_ids = {
            self.map_ids[name] for name, kind in kinds.items() if kind == "ordinary"
        }
        alias_ids = {
            self.map_ids[name] for name, kind in kinds.items() if kind == "alias"
        }
        self.assertEqual(maps, direct_ids | alias_ids)
        self.assertEqual(len(direct_ids), 84)
        self.assertEqual(len(alias_ids), 5)
        self.assertEqual(len(johto_rows), 147)
        self.assertTrue(
            all(set(row) & set(projection.METHOD_ORDER) for row in encounter_rows)
        )

        excluded_names = {
            name for name, kind in kinds.items() if kind not in {"ordinary", "alias"}
        }
        excluded_ids = {
            self.load(ROOT / "data/maps" / name / "map.json")["id"]
            for name in excluded_names
        }
        self.assertTrue(maps.isdisjoint(excluded_ids))
        self.assertEqual(sum(kind == "special" for kind in kinds.values()), 18)
        self.assertEqual(sum(kind == "encounter-free" for kind in kinds.values()), 147)

    def test_route39_and_non_johto_values_are_preserved(self):
        original_group = self.encounters["wild_encounter_groups"][0]["encounters"]
        for label in projection.ROUTE39_LABELS:
            self.assertEqual(
                next(row for row in original_group if row["base_label"] == label),
                self.encounter(label),
            )
        for label in projection.ROUTE39_LABELS:
            self.assertEqual(
                next(row for row in self.registry["profiles"] if row[1] == label),
                next(row for row in self.outputs[1]["profiles"] if row[1] == label),
            )
        self.assertTrue(
            projection.ROUTE39_LABELS.isdisjoint(
                {row["label"] for row in self.outputs[2]["profiles"]}
            )
        )
        original_non_johto = [
            row for row in self.registry["profiles"] if row[3] != "johto"
        ]
        projected_non_johto = [
            row for row in self.outputs[1]["profiles"] if row[3] != "johto"
        ]
        self.assertEqual(original_non_johto, projected_non_johto)
        registry_by_label = {row[1]: row for row in self.registry["profiles"]}
        expected_bands = [
            row
            for row in self.bands["profiles"]
            if registry_by_label[row["label"]][3] != "johto"
        ]
        self.assertEqual(self.outputs[2]["profiles"], expected_bands)
        self.assertEqual(len(expected_bands), projection.NON_JOHTO_BAND_COUNT)

    def test_time_policies_cover_every_selected_pair(self):
        time_document = self.outputs[3]
        self.assertEqual(
            set(time_document),
            {
                "schema_version",
                "encounterProfiles",
                "encounterTimePolicy",
                "methodFallbacks",
            },
        )
        self.assertEqual(
            {
                (
                    row["map"],
                    row["method"],
                    row["missingCondition"],
                    row["sourceCondition"],
                )
                for row in time_document["methodFallbacks"]
            },
            {
                (map_name, method, "TIME_NIGHT", "TIME_DAY")
                for map_name, method, _, _ in projection.REVIEWED_METHOD_TIME_FALLBACKS
            },
        )
        for row in time_document["encounterTimePolicy"]:
            self.assertEqual((row["dayStart"], row["nightStart"]), ("06:00", "18:00"))
            self.assertEqual(row["fallbackLabel"], row["dayLabel"])
        policy_labels = {
            label
            for row in time_document["encounterTimePolicy"]
            for label in (row["dayLabel"], row["nightLabel"])
        }
        typed_labels = {row["label"] for row in time_document["encounterProfiles"]}
        self.assertEqual(policy_labels, typed_labels)

        for policy in time_document["encounterTimePolicy"]:
            day = self.encounter(policy["dayLabel"])
            night = self.encounter(policy["nightLabel"])
            self.assertEqual(
                set(day) & set(projection.METHOD_ORDER),
                set(night) & set(projection.METHOD_ORDER),
                policy["map"],
            )

        cianwood_day = self.encounter("gCianwoodCity")
        cianwood_night = self.encounter("gCianwoodCity_Night")
        self.assertEqual(
            cianwood_night["rock_smash_mons"], cianwood_day["rock_smash_mons"]
        )

    def test_check_and_write_mismatch_behavior(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outputs = {
                root / "encounters.json": self.outputs[0],
                root / "registry.json": self.outputs[1],
            }
            self.assertEqual(set(projection.check_or_write(outputs)), set(outputs))
            self.assertEqual(
                set(projection.check_or_write(outputs, write=True)), set(outputs)
            )
            self.assertEqual(projection.check_or_write(outputs), [])
            first = next(iter(outputs))
            first.write_text("{}\n", encoding="utf-8")
            self.assertEqual(projection.check_or_write(outputs), [first])

    def test_production_outputs_are_current(self):
        paths = (
            projection.DEFAULT_ENCOUNTERS,
            projection.DEFAULT_REGISTRY,
            projection.DEFAULT_BANDS,
            projection.DEFAULT_TIME_POLICIES,
        )
        self.assertEqual(
            projection.check_or_write(dict(zip(paths, self.outputs, strict=True))),
            [],
        )

    def test_projection_is_pure_and_deterministic(self):
        inputs = [
            self.classification,
            self.ecology,
            self.fallbacks,
            self.encounters,
            self.registry,
            self.bands,
        ]
        before = copy.deepcopy(inputs)
        again = projection.project_documents(
            *inputs,
            self.map_ids,
            self.ecology_source,
        )
        self.assertEqual(inputs, before)
        self.assertEqual(again, self.outputs)

    def test_checked_in_fallback_source_is_pinned_to_authenticated_profiles(self):
        recovered = projection._verified_checked_in_ecology_source(
            self.encounters, self.fallbacks
        )
        recovered_profiles = projection._source_profiles(
            recovered, projection.CHECKED_IN_FALLBACK_SOURCE_LABELS
        )
        self.assertEqual(
            set(recovered_profiles), projection.CHECKED_IN_FALLBACK_SOURCE_LABELS
        )
        if projection.DEFAULT_ECOLOGY_SOURCE.is_file():
            self.assertEqual(
                recovered_profiles,
                projection._source_profiles(
                    self.ecology_source,
                    projection.CHECKED_IN_FALLBACK_SOURCE_LABELS,
                ),
            )

        changed = copy.deepcopy(self.encounters)
        target = next(
            row
            for row in changed["wild_encounter_groups"][0]["encounters"]
            if row["base_label"] == "gJohtoVictoryRoad_1F"
        )
        target["land_mons"]["mons"][0]["species"] = "SPECIES_RATTATA"
        with self.assertRaisesRegex(
            projection.ProjectionError, "authenticated donor evidence"
        ):
            projection._verified_checked_in_ecology_source(changed, self.fallbacks)


if __name__ == "__main__":
    unittest.main()
