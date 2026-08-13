from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from tools.content_port.animations import load_animation_policy, required_frame_payloads
from tools.content_port.descriptor import load_port
from tools.content_port.errors import ContentPortError
from tools.content_port.materialize import _animation_units


PORT = Path("tools/content_port/ports/johto")
DONOR_ROOT = Path(os.environ.get("CONTENT_PORT_DONOR_ROOT", ".references"))
if not DONOR_ROOT.exists():
    DONOR_ROOT = Path.cwd().parents[2] / ".references"
DONOR = DONOR_ROOT / "pokemonHnS"


class AnimationPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads((PORT / "animation_policy.json").read_text())
        adaptations = json.loads((PORT / "adaptations.json").read_text())
        cls.residents = {item["symbol"] for item in adaptations["tilesetAdaptations"]}

    def _load(
        self, document: dict[str, object], *, target_root: Path | None = None
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "animation_policy.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            load_animation_policy(
                path,
                donor_root=DONOR,
                target_root=target_root or Path.cwd(),
                resident_tilesets=self.residents,
            )

    def test_reviewed_policy_authenticates_complete_inventory(self) -> None:
        policy = load_animation_policy(
            PORT / "animation_policy.json",
            donor_root=DONOR,
            target_root=Path.cwd(),
            resident_tilesets=self.residents,
        )
        payloads = required_frame_payloads(policy)
        self.assertEqual(len(payloads), 111)
        self.assertEqual(len(payloads), len({target for _, target in payloads}))

    def test_missing_resident_classification_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["residentTilesets"].pop()
        with self.assertRaisesRegex(ContentPortError, "resident inventory differs"):
            self._load(mutated)

    def test_unclassified_donor_frame_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["frameSets"][0]["requiredFrames"].pop()
        with self.assertRaisesRegex(ContentPortError, "unclassified donor frame"):
            self._load(mutated)

    def test_unresolved_blocked_item_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["residentTilesets"][0]["disposition"] = "blocked"
        with self.assertRaisesRegex(ContentPortError, "unresolved blocked disposition"):
            self._load(mutated)

    def test_unauthenticated_required_code_and_assets_are_rejected(self) -> None:
        for family, field in (
            ("codePayloads", "sha256"),
            ("frameSets", "inventorySha256"),
        ):
            with self.subTest(family=family):
                mutated = copy.deepcopy(self.document)
                mutated[family][0][field] = "0" * 64
                with self.assertRaisesRegex(
                    ContentPortError, "digest mismatch|inventory mismatch"
                ):
                    self._load(mutated)

    def test_runtime_code_authority_path_and_disposition_are_pinned(self) -> None:
        mutations = (
            ("path", "src/fieldmap.c", "runtime authority"),
            ("targetPath", "src/fieldmap.c", "runtime authority"),
            ("disposition", "intentionally-unused", "must be required"),
        )
        for field, value, message in mutations:
            with self.subTest(field=field):
                mutated = copy.deepcopy(self.document)
                mutated["codePayloads"][0][field] = value
                with self.assertRaisesRegex(ContentPortError, message):
                    self._load(mutated)

    def test_regeneration_owns_exactly_policy_required_frames(self) -> None:
        descriptor = load_port(PORT, DONOR_ROOT)
        expected = {
            target for _, target in required_frame_payloads(descriptor.animations)
        }
        units = _animation_units(descriptor)
        self.assertEqual({unit.path for unit in units}, expected)
        self.assertEqual(len(units), 111)

    def test_schedule_drift_cannot_drop_a_mandatory_binding(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["schedules"].pop()
        with self.assertRaisesRegex(ContentPortError, "cover every mandatory binding"):
            self._load(mutated)

    def test_reviewed_inventory_rejects_whole_set_or_inactive_transfer_omission(
        self,
    ) -> None:
        for family in ("frameSets", "inactiveTransfers"):
            with self.subTest(family=family):
                mutated = copy.deepcopy(self.document)
                mutated[family].pop()
                with self.assertRaisesRegex(
                    ContentPortError, "inventory differs from reviewed authority"
                ):
                    self._load(mutated)

    def test_individual_required_transfer_removal_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["schedules"][0]["transfers"].pop()
        with self.assertRaisesRegex(ContentPortError, "donor schedule differs"):
            self._load(mutated)

    def test_callback_and_frame_disposition_mismatch_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["callbacks"][0]["disposition"] = "intentionally-unused"
        with self.assertRaisesRegex(ContentPortError, "callback is not required"):
            self._load(mutated)

        mutated = copy.deepcopy(self.document)
        mutated["frameSets"][0]["disposition"] = "intentionally-unused"
        with self.assertRaisesRegex(ContentPortError, "disposition disagrees"):
            self._load(mutated)

    def test_variant_candidates_cannot_be_claimed_as_donor_executable(self) -> None:
        mutated = copy.deepcopy(self.document)
        variant = next(
            frame_set
            for frame_set in mutated["frameSets"]
            if frame_set["id"].startswith("johto_north_east.")
        )
        variant["evidenceKind"] = "donor-executable"
        with self.assertRaisesRegex(ContentPortError, "frame evidence"):
            self._load(mutated)

        mutated = copy.deepcopy(self.document)
        mutated["schedules"][1]["transfers"][0]["frameSet"] = (
            "johto_general.sandwatersedge"
        )
        with self.assertRaisesRegex(ContentPortError, "donor schedule differs"):
            self._load(mutated)

    def test_schedule_numeric_contract_rejects_zero_wrong_types_and_bad_phase(
        self,
    ) -> None:
        mutations = (
            ("counterMax", 0, "positive integer"),
            ("counterMax", "256", "positive integer"),
            ("period", 0, "positive integer"),
            ("period", "8", "positive integer"),
            ("tileCount", 0, "positive integer"),
            ("tileCount", True, "positive integer"),
            ("sourceTileOffset", -1, "non-negative integer"),
            ("phase", 8, "within period"),
        )
        for field, value, message in mutations:
            with self.subTest(field=field, value=value):
                mutated = copy.deepcopy(self.document)
                if field == "counterMax":
                    mutated["schedules"][0][field] = value
                else:
                    mutated["schedules"][0]["transfers"][0][field] = value
                with self.assertRaisesRegex(ContentPortError, message):
                    self._load(mutated)

    def test_phase2_runtime_traces_cover_every_reviewed_transfer(self) -> None:
        frame_orders = {
            "national_park.red_flower": (0, 1, 2, 1),
            "national_park.yellow_flower": (2, 1, 0, 1),
            "azalea_town_gym.yellow_flower": (0, 1, 2, 1),
        }
        observed = []
        for schedule in self.document["schedules"]:
            counter_max = schedule["counterMax"]
            self.assertEqual((counter_max - 1 + 1) % counter_max, 0)
            for transfer in schedule["transfers"]:
                period, phase = transfer["period"], transfer["phase"]
                first = period if phase == 0 else phase
                order = frame_orders.get(
                    transfer["frameSet"],
                    tuple(
                        next(
                            item["requiredFrames"]
                            for item in self.document["frameSets"]
                            if item["id"] == transfer["frameSet"]
                        )
                    ),
                )
                observed.append(
                    (
                        schedule["tileset"],
                        transfer["frameSet"],
                        first,
                        order[(first // period) % len(order)],
                        transfer["sourceTileOffset"],
                        transfer["destinationTile"],
                        transfer["tileCount"] * 32,
                    )
                )
        self.assertEqual(
            observed,
            [
                ("Johto_General", "johto_general.sandwatersedge", 8, 1, 0, 416, 576),
                ("Johto_General", "johto_general.flower", 2, 0, 0, 508, 128),
                (
                    "Johto_General",
                    "johto_general.water_current_landwatersedge",
                    3,
                    0,
                    34,
                    450,
                    384,
                ),
                (
                    "Johto_NorthEast",
                    "johto_north_east.sandwatersedge",
                    8,
                    1,
                    0,
                    416,
                    576,
                ),
                ("Johto_NorthEast", "johto_north_east.flower", 2, 0, 0, 508, 128),
                (
                    "Johto_NorthEast",
                    "johto_north_east.water_current_landwatersedge",
                    3,
                    0,
                    34,
                    450,
                    384,
                ),
                ("Johto_South", "johto_south.sandwatersedge", 8, 1, 0, 416, 576),
                ("Johto_South", "johto_south.flower", 2, 0, 0, 508, 128),
                (
                    "Johto_South",
                    "johto_south.water_current_landwatersedge",
                    3,
                    0,
                    34,
                    450,
                    384,
                ),
                (
                    "Johto_NorthWest",
                    "johto_north_west.sandwatersedge",
                    8,
                    1,
                    0,
                    416,
                    576,
                ),
                ("Johto_NorthWest", "johto_north_west.flower", 2, 0, 0, 508, 128),
                (
                    "Johto_NorthWest",
                    "johto_north_west.water_current_landwatersedge",
                    3,
                    0,
                    34,
                    450,
                    384,
                ),
                ("NationalPark", "national_park.large_fountain", 10, 1, 0, 728, 256),
                ("NationalPark", "national_park.small_fountain", 1, 0, 0, 744, 256),
                ("NationalPark", "national_park.red_flower", 2, 0, 0, 736, 128),
                ("NationalPark", "national_park.yellow_flower", 12, 2, 0, 740, 128),
                ("EcruteakTheater", "ecruteak_theater.flower", 10, 1, 0, 744, 128),
                ("AzaleaTown_Gym", "azalea_town_gym.yellow_flower", 10, 1, 0, 739, 128),
                ("BlackthornGym", "blackthorn_gym.cave_lava", 1, 0, 0, 961, 128),
            ],
        )

    def test_phase2_generated_header_binds_every_mandatory_tileset(self) -> None:
        header = Path("src/data/tilesets/headers.h").read_text(encoding="utf-8")
        callbacks = {
            item["tileset"]: item["callback"] for item in self.document["schedules"]
        }
        for tileset, callback in callbacks.items():
            start = header.index(f"const struct Tileset gTileset_{tileset} =")
            block = header[start : header.index("};", start)]
            self.assertIn(f".callback = {callback},", block)

    def test_transfer_source_slice_is_authenticated_and_bounded(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["schedules"][0]["transfers"][2]["sourceTileOffset"] = 0
        with self.assertRaisesRegex(ContentPortError, "donor schedule differs"):
            self._load(mutated)

        mutated = copy.deepcopy(self.document)
        mutated["schedules"][0]["transfers"][2]["sourceTileOffset"] = 40
        with self.assertRaisesRegex(ContentPortError, "source tile slice exceeds"):
            self._load(mutated)

    def test_inactive_items_require_non_empty_reasons(self) -> None:
        mutations = (
            ("residentTilesets", 8),
            ("frameSets", 18),
            ("inactiveTransfers", 0),
        )
        for family, index in mutations:
            with self.subTest(family=family):
                mutated = copy.deepcopy(self.document)
                mutated[family][index]["reason"] = ""
                with self.assertRaisesRegex(ContentPortError, "non-empty"):
                    self._load(mutated)

        mutated = copy.deepcopy(self.document)
        mutated["codePayloads"][0]["reason"] = ""
        with self.assertRaisesRegex(ContentPortError, "non-empty"):
            self._load(mutated)

        mutated = copy.deepcopy(self.document)
        mutated["callbacks"][0]["reason"] = ""
        with self.assertRaisesRegex(ContentPortError, "non-empty"):
            self._load(mutated)

    def test_duplicate_frame_index_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.document)
        mutated["frameSets"][0]["requiredFrames"].append(0)
        with self.assertRaisesRegex(ContentPortError, "duplicate frame index"):
            self._load(mutated)

    def test_preserved_runtime_code_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target_root = Path(directory)
            target = target_root / "src/tileset_anims.c"
            target.parent.mkdir(parents=True)
            target.write_text("drifted\n", encoding="utf-8")
            with self.assertRaisesRegex(
                ContentPortError, "runtime code digest mismatch"
            ):
                self._load(copy.deepcopy(self.document), target_root=target_root)
            target.unlink()
            with self.assertRaisesRegex(ContentPortError, "owned path does not exist"):
                self._load(copy.deepcopy(self.document), target_root=target_root)

    def test_johto_animation_policy_reference_is_mandatory(self) -> None:
        original_read = __import__(
            "tools.content_port.descriptor", fromlist=["read_json"]
        ).read_json

        def without_animation_policy(path: Path) -> object:
            value = original_read(path)
            if path.name == "port.json":
                value = copy.deepcopy(value)
                value.pop("animationPolicy")
            return value

        with (
            mock.patch(
                "tools.content_port.descriptor.read_json",
                side_effect=without_animation_policy,
            ),
            self.assertRaisesRegex(ContentPortError, "required for the Johto port"),
        ):
            load_port(PORT, DONOR_ROOT)


if __name__ == "__main__":
    unittest.main()
