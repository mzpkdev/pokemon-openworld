import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MAPJSON = ROOT / "tools" / "mapjson" / "mapjson"
GROUPS = ROOT / "data" / "maps" / "map_groups.json"
LAYOUTS = ROOT / "data" / "layouts" / "layouts.json"
CHECKPOINTS = ROOT / "src" / "data" / "heal_locations.json"
PUBLISHED = ROOT / "tools" / "persistence" / "published_allocations.json"
MAPS = sorted((ROOT / "data" / "maps").glob("*/map.json"))


class CheckpointRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["make", "-C", "tools/mapjson", "all"], cwd=ROOT, check=True)
        cls.registry = json.loads(CHECKPOINTS.read_text(encoding="utf-8"))

    def _validate(self, registry):
        with tempfile.TemporaryDirectory(prefix="checkpoint-registry-") as tempdir:
            path = Path(tempdir) / "checkpoints.json"
            path.write_text(json.dumps(registry), encoding="utf-8")
            return subprocess.run(
                [
                    str(MAPJSON),
                    "checkpoints",
                    "allregions",
                    str(GROUPS),
                    str(LAYOUTS),
                    str(path),
                    str(PUBLISHED),
                    *(str(path) for path in MAPS),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

    def _mutated(self, index=0, **changes):
        registry = copy.deepcopy(self.registry)
        registry["heal_locations"][index].update(changes)
        return registry

    def assertRejected(self, registry, message):
        result = self._validate(registry)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(message, result.stderr)

    def test_registry_and_published_ids_are_exactly_zero_through_42(self):
        result = self._validate(self.registry)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "checkpoints=valid\n")

        entries = json.loads(PUBLISHED.read_text(encoding="utf-8"))["entries"]
        bindings = {
            entry["symbol"]: entry["value"]
            for entry in entries
            if entry["domain"] == "checkpoints"
            and entry["source"] == "heal-locations"
        }
        ids = ["HEAL_LOCATION_NONE"] + [
            checkpoint["id"] for checkpoint in self.registry["heal_locations"]
        ]
        self.assertEqual(len(ids), 43)
        self.assertEqual([bindings[symbol] for symbol in ids], list(range(43)))

    def test_missing_checkpoint_is_rejected(self):
        registry = copy.deepcopy(self.registry)
        registry["heal_locations"].pop()
        self.assertRejected(registry, "missing a published checkpoint")

    def test_invalid_destination_is_rejected(self):
        self.assertRejected(
            self._mutated(respawn_map="MAP_NOT_A_REAL_DESTINATION"),
            "names invalid destination",
        )

    def test_invalid_healer_actor_is_rejected(self):
        self.assertRejected(
            self._mutated(respawn_npc="LOCALID_NOT_OWNED_BY_DESTINATION"),
            "is not owned exactly once by destination events",
        )

    def test_out_of_bounds_heal_and_destination_coordinates_are_rejected(self):
        self.assertRejected(self._mutated(x=65535), "heal location is outside map bounds")
        self.assertRejected(
            self._mutated(respawn_x=65535, respawn_y=7),
            "whiteout destination is outside map bounds",
        )

    def test_recovery_mode_contract_is_rejected_when_incoherent(self):
        self.assertRejected(
            self._mutated(recovery_mode="UNKNOWN"), "has invalid recovery mode"
        )
        self.assertRejected(
            self._mutated(recovery_mode="DIRECT"), "must not name a healer actor"
        )
        self.assertRejected(
            self._mutated(20, recovery_mode="HEALER"), "lacks a healer actor"
        )

    def test_partial_or_duplicate_coordinates_are_rejected(self):
        registry = self._mutated()
        del registry["heal_locations"][0]["respawn_y"]
        self.assertRejected(registry, "must author both respawn coordinates or neither")

        duplicate = copy.deepcopy(self.registry)
        duplicate["heal_locations"][1].update(
            {
                "map": duplicate["heal_locations"][0]["map"],
                "x": duplicate["heal_locations"][0]["x"],
                "y": duplicate["heal_locations"][0]["y"],
            }
        )
        self.assertRejected(duplicate, "duplicates a heal location")

    def test_unknown_fields_and_serialized_reordering_are_rejected(self):
        self.assertRejected(
            self._mutated(typo_respawn_mode="HEALER"), "has unknown field"
        )

        reordered = copy.deepcopy(self.registry)
        reordered["heal_locations"][:2] = reversed(reordered["heal_locations"][:2])
        self.assertRejected(reordered, "changed its serialized binding")

    def test_runtime_uses_one_record_without_changing_public_lookup_api(self):
        template = (ROOT / "src/data/heal_locations.json.txt").read_text()
        source = (ROOT / "src/heal_location.c").read_text()
        public = (ROOT / "include/heal_location.h").read_text()

        self.assertIn("static const struct Checkpoint sCheckpoints", template)
        self.assertNotIn("sWhiteoutRespawnHealCenterMapIdxs", template)
        self.assertNotIn("sWhiteoutRespawnHealerNpcIds", template)
        self.assertIn("checkpoint->recoveryMode", source)
        for signature in (
            "u32 GetHealLocationIndexByMap(u16 mapGroup, u16 mapNum);",
            "u32 GetHealLocationIndexByWarpData(struct WarpData *warp);",
            "const struct HealLocation *GetHealLocationByMap(u16 mapGroup, u16 mapNum);",
            "const struct HealLocation *GetHealLocation(u32 index);",
            "u32 GetHealNpcLocalId(u32 healLocationId);",
        ):
            self.assertIn(signature, public)


if __name__ == "__main__":
    unittest.main()
