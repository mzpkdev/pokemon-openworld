from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.trainer_rematches.generate import (
    BEN,
    CALVIN,
    CHAIN_COUNT,
    CHAIN_WIDTH,
    MANIFEST_PATH,
    NONE_BINDINGS,
    PROVENANCE,
    RematchDataError,
    _trainer_values,
    main,
    render,
    validate_manifest,
)


ROOT = Path(__file__).parents[3]


class TrainerRematchDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / MANIFEST_PATH).read_text(encoding="utf-8"))
        cls.values = _trainer_values(ROOT)

    def mutated(self):
        return copy.deepcopy(self.manifest)

    def resolve(self, row):
        return [
            0 if stage == "NONE" else 0xFFFF if stage == "SKIP" else self.values[stage]
            for stage in row
        ]

    def test_reviewed_provenance_and_shape_are_exact(self):
        self.assertEqual(self.manifest["schemaVersion"], 1)
        self.assertEqual(self.manifest["provenance"], PROVENANCE)
        self.assertEqual(self.manifest["noneBindings"], list(NONE_BINDINGS))
        self.assertEqual(len(self.manifest["rows"]), CHAIN_COUNT)
        self.assertTrue(all(len(row) == CHAIN_WIDTH for row in self.manifest["rows"]))

    def test_reviewed_examples_and_none_bindings_are_exact(self):
        rows = {row[0]: self.resolve(row) for row in self.manifest["rows"]}
        self.assertEqual(rows["TRAINER_FRLG_YOUNGSTER_BEN"], BEN)
        self.assertEqual(rows["TRAINER_FRLG_YOUNGSTER_CALVIN"], CALVIN)
        self.assertEqual(
            {symbol: self.values[symbol] for symbol in self.manifest["noneBindings"]},
            NONE_BINDINGS,
        )

    def test_all_concrete_members_are_live_unique_and_have_valid_tails(self):
        member_family = {}
        numeric_member = {}
        for row in self.manifest["rows"]:
            family = row[0]
            seen_none = False
            for stage in row:
                if stage == "NONE":
                    seen_none = True
                    continue
                self.assertFalse(seen_none, f"{family}: nonzero stage after NONE")
                if stage == "SKIP":
                    continue
                self.assertTrue(stage.startswith("TRAINER_FRLG_"))
                value = self.values[stage]
                self.assertIn(value, range(858, 1481))
                self.assertIn(member_family.setdefault(stage, family), {family})
                self.assertIn(numeric_member.setdefault(value, stage), {stage})

    def test_render_is_deterministic_and_preserves_symbolic_order(self):
        first = render(self.manifest, self.values)
        second = render(self.mutated(), self.values)
        self.assertEqual(first, second)
        self.assertIn("#define FRLG_TRAINER_REMATCH_CHAIN_COUNT 221", first)
        self.assertIn(
            "[0] = { .trainerIds = { TRAINER_FRLG_YOUNGSTER_BEN, "
            "TRAINER_FRLG_YOUNGSTER_BEN_2, 0xFFFF, "
            "TRAINER_FRLG_YOUNGSTER_BEN_3, TRAINER_FRLG_YOUNGSTER_BEN_4, 0 } },",
            first,
        )
        self.assertIn(
            "[TRAINER_FRLG_RUIN_MANIAC_LAWSON] = { .kind = "
            "TRAINER_REMATCH_BINDING_NONE, .index = 0 },",
            first,
        )
        self.assertIn(
            "[TRAINER_YOUNGSTER_SAMUEL_JOHTO] = { .kind = "
            "TRAINER_REMATCH_BINDING_NONE, .index = 0 },",
            first,
        )

    def test_make_rule_regenerates_identical_output(self):
        expected = render(self.manifest, self.values).encode()
        with tempfile.TemporaryDirectory() as tmp:
            generated_root = Path(tmp) / "generated"
            output = generated_root / "src/data/trainer_rematches/frlg.inc.c"
            command = [
                "make",
                "-f",
                "trainer_rematch_rules.mk",
                f"GENERATED_ROOT={generated_root}",
                str(output),
            ]
            subprocess.run(command, cwd=ROOT, check=True, capture_output=True)
            self.assertEqual(output.read_bytes(), expected)
            output.unlink()
            subprocess.run(command, cwd=ROOT, check=True, capture_output=True)
            self.assertEqual(output.read_bytes(), expected)

    def test_wrong_provenance_fails(self):
        manifest = self.mutated()
        manifest["provenance"]["commit"] = "0" * 40
        with self.assertRaisesRegex(RematchDataError, "upstream identity drifted"):
            validate_manifest(manifest, self.values)

    def test_wrong_row_count_or_width_fails(self):
        missing = self.mutated()
        missing["rows"].pop()
        with self.assertRaisesRegex(RematchDataError, "exactly 221 rows"):
            validate_manifest(missing, self.values)
        narrow = self.mutated()
        narrow["rows"][0].pop()
        with self.assertRaisesRegex(RematchDataError, "exactly 6 stage"):
            validate_manifest(narrow, self.values)

    def test_nonzero_after_none_and_legacy_identity_fail(self):
        bad_tail = self.mutated()
        bad_tail["rows"][1][2] = "NONE"
        bad_tail["rows"][1][3] = "TRAINER_FRLG_YOUNGSTER_CALVIN"
        with self.assertRaisesRegex(RematchDataError, "after NONE tail"):
            validate_manifest(bad_tail, self.values)
        legacy = self.mutated()
        legacy["rows"][0][0] = "TRAINER_YOUNGSTER_BEN"
        with self.assertRaisesRegex(RematchDataError, "not a live FRLG identity"):
            validate_manifest(legacy, self.values)

    def test_duplicate_family_and_cross_family_member_fail(self):
        duplicate = self.mutated()
        duplicate["rows"][1][0] = duplicate["rows"][0][0]
        with self.assertRaisesRegex(RematchDataError, "duplicate family"):
            validate_manifest(duplicate, self.values)
        shared = self.mutated()
        shared["rows"][1][1] = "TRAINER_FRLG_YOUNGSTER_BEN_2"
        with self.assertRaisesRegex(RematchDataError, "also belongs"):
            validate_manifest(shared, self.values)

    def test_valid_looking_row_reorder_fails_exact_order_binding(self):
        reordered = self.mutated()
        reordered["rows"][2], reordered["rows"][3] = (
            reordered["rows"][3],
            reordered["rows"][2],
        )
        with self.assertRaisesRegex(RematchDataError, "row order or content drifted"):
            validate_manifest(reordered, self.values)

    def test_exact_examples_and_none_bindings_cannot_drift(self):
        ben = self.mutated()
        ben["rows"][0][2] = "NONE"
        ben["rows"][0][3:] = ["NONE"] * 3
        with self.assertRaisesRegex(RematchDataError, "must resolve exactly"):
            validate_manifest(ben, self.values)
        none = self.mutated()
        none["noneBindings"].reverse()
        with self.assertRaisesRegex(RematchDataError, "exact Lawson and Samuel"):
            validate_manifest(none, self.values)

    def test_malformed_manifest_fails_before_output_changes(self):
        manifest = self.mutated()
        manifest["rows"][0][0] = "TRAINER_YOUNGSTER_BEN"
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "bad.json"
            output = Path(tmp) / "generated.inc.c"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output.write_text("keep me\n", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                result = main(
                    [
                        "generate",
                        "--manifest",
                        str(manifest_path),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(result, 1)
            self.assertEqual(output.read_text(encoding="utf-8"), "keep me\n")


if __name__ == "__main__":
    unittest.main()
