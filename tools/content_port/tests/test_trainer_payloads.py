from __future__ import annotations

import unittest
from dataclasses import replace
from types import MappingProxyType

from tools.content_port.errors import ContentPortError
from tools.content_port.model import (
    TrainerEventRecord,
    TrainerScriptInstruction,
    TrainerText,
)
from tools.content_port.trainer_payloads import (
    DefaultPartyMember,
    project_standard_single_event,
    project_standard_single_party,
)


class StandardSingleEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.event = TrainerEventRecord(
            map_name="Route34",
            object_index=2,
            object_event={"script": "Route34_EventScript_Samuel", "x": 10},
            script_name="Route34_EventScript_Samuel",
            trainers=("TRAINER_SAMUEL",),
            instructions=(
                TrainerScriptInstruction(
                    "trainerbattle_single",
                    ("TRAINER_SAMUEL", "Samuel_Seen", "Samuel_Beaten"),
                ),
                TrainerScriptInstruction(
                    "msgbox", ("Samuel_After", "MSGBOX_AUTOCLOSE")
                ),
                TrainerScriptInstruction("end", ()),
            ),
            texts=(
                TrainerText("Samuel_Seen", ('_"I saw you!\\n"',)),
                TrainerText("Samuel_Beaten", ('_"I lost!$"',)),
                TrainerText("Samuel_After", ('_"Again?$"',)),
            ),
        )

    def test_projects_only_trainer_operand_and_freezes_result(self) -> None:
        result = project_standard_single_event(
            self.event,
            source_trainer="TRAINER_SAMUEL",
            target_trainer="TRAINER_YOUNGSTER_SAMUEL_JOHTO",
        )

        self.assertEqual(result.source_trainer, "TRAINER_SAMUEL")
        self.assertEqual(result.event.trainers, ("TRAINER_YOUNGSTER_SAMUEL_JOHTO",))
        self.assertEqual(
            result.event.instructions[0].operands,
            (
                "TRAINER_YOUNGSTER_SAMUEL_JOHTO",
                "Samuel_Seen",
                "Samuel_Beaten",
            ),
        )
        self.assertEqual(result.event.instructions[1:], self.event.instructions[1:])
        self.assertEqual(result.event.texts, self.event.texts)
        self.assertEqual(dict(result.event.object_event), self.event.object_event)
        self.assertIsInstance(result.event.object_event, MappingProxyType)
        with self.assertRaises(TypeError):
            result.event.object_event["x"] = 11

    def test_rejects_nonstandard_commands_and_arities(self) -> None:
        for event in (
            replace(
                self.event,
                instructions=(
                    replace(self.event.instructions[0], command="trainerbattle_double"),
                    *self.event.instructions[1:],
                ),
            ),
            replace(
                self.event,
                instructions=(
                    replace(
                        self.event.instructions[0],
                        operands=self.event.instructions[0].operands + ("EXTRA",),
                    ),
                    *self.event.instructions[1:],
                ),
            ),
        ):
            with self.subTest(event=event.instructions[0]):
                with self.assertRaisesRegex(ContentPortError, "script shape"):
                    project_standard_single_event(
                        event,
                        source_trainer="TRAINER_SAMUEL",
                        target_trainer="TRAINER_YOUNGSTER_SAMUEL_JOHTO",
                    )

    def test_rejects_source_identity_drift(self) -> None:
        with self.assertRaisesRegex(ContentPortError, "source trainer closure"):
            project_standard_single_event(
                replace(self.event, trainers=("TRAINER_EUGENE",)),
                source_trainer="TRAINER_SAMUEL",
                target_trainer="TRAINER_YOUNGSTER_SAMUEL_JOHTO",
            )
        drifted_battle = replace(
            self.event.instructions[0],
            operands=("TRAINER_EUGENE", *self.event.instructions[0].operands[1:]),
        )
        with self.assertRaisesRegex(ContentPortError, "trainerbattle source"):
            project_standard_single_event(
                replace(
                    self.event,
                    instructions=(drifted_battle, *self.event.instructions[1:]),
                ),
                source_trainer="TRAINER_SAMUEL",
                target_trainer="TRAINER_YOUNGSTER_SAMUEL_JOHTO",
            )

    def test_rejects_msgbox_and_exact_local_text_closure_drift(self) -> None:
        bad_msgbox = replace(
            self.event.instructions[1],
            operands=("Samuel_After", "MSGBOX_DEFAULT"),
        )
        with self.assertRaisesRegex(ContentPortError, "MSGBOX_AUTOCLOSE"):
            project_standard_single_event(
                replace(
                    self.event,
                    instructions=(
                        self.event.instructions[0],
                        bad_msgbox,
                        self.event.instructions[2],
                    ),
                ),
                source_trainer="TRAINER_SAMUEL",
                target_trainer="TRAINER_YOUNGSTER_SAMUEL_JOHTO",
            )
        for texts, message in (
            (self.event.texts[:-1], "exactly contain"),
            (
                (self.event.texts[1], self.event.texts[0], self.event.texts[2]),
                "exactly contain",
            ),
            (
                (replace(self.event.texts[0], fragments=()), *self.event.texts[1:]),
                "must not be empty",
            ),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ContentPortError, message):
                    project_standard_single_event(
                        replace(self.event, texts=texts),
                        source_trainer="TRAINER_SAMUEL",
                        target_trainer="TRAINER_YOUNGSTER_SAMUEL_JOHTO",
                    )


class StandardSinglePartyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.party = {
            "members": [
                {
                    "species": "SPECIES_TEDDIURSA",
                    "held_item": None,
                    "moves": [],
                    "level": 12,
                    "iv": 0,
                },
                {
                    "species": "SPECIES_SPEAROW",
                    "held_item": None,
                    "moves": (),
                    "level": 100,
                    "iv": 31,
                },
            ]
        }
        self.species = {"SPECIES_TEDDIURSA", "SPECIES_SPEAROW"}

    def project(self, party=None):
        return project_standard_single_party(
            self.party if party is None else party,
            source_trainer="TRAINER_SAMUEL",
            party_name="sParty_Samuel",
            known_species=self.species,
        )

    def test_projects_validated_members_to_immutable_records(self) -> None:
        result = self.project()

        self.assertEqual(result.source_trainer, "TRAINER_SAMUEL")
        self.assertEqual(result.party_name, "sParty_Samuel")
        self.assertEqual(
            result.members,
            (
                DefaultPartyMember("SPECIES_TEDDIURSA", 12, 0),
                DefaultPartyMember("SPECIES_SPEAROW", 100, 31),
            ),
        )

    def test_rejects_empty_and_oversized_parties(self) -> None:
        for members in ([], self.party["members"] * 4):
            with self.subTest(size=len(members)):
                with self.assertRaisesRegex(ContentPortError, "one and six"):
                    self.project({"members": members})

    def test_rejects_missing_and_unknown_species(self) -> None:
        for species, message in (
            (None, "missing species"),
            ("SPECIES_MEW", "unknown species"),
        ):
            member = dict(self.party["members"][0], species=species)
            with self.subTest(species=species):
                with self.assertRaisesRegex(ContentPortError, message):
                    self.project({"members": [member]})

    def test_rejects_out_of_range_or_noninteger_levels_and_ivs(self) -> None:
        for field, values in (("level", (0, 101, True)), ("iv", (-1, 32, False))):
            for value in values:
                with self.subTest(field=field, value=value):
                    member = dict(self.party["members"][0], **{field: value})
                    with self.assertRaisesRegex(ContentPortError, field):
                        self.project({"members": [member]})

    def test_rejects_nondefault_item_and_move_payloads(self) -> None:
        for field, value, message in (
            ("held_item", "ITEM_ORAN_BERRY", "use no items"),
            ("moves", ["MOVE_GROWL"], "use default moves"),
            ("moves", "MOVE_GROWL", "use default moves"),
        ):
            with self.subTest(field=field, value=value):
                member = dict(self.party["members"][0], **{field: value})
                with self.assertRaisesRegex(ContentPortError, message):
                    self.project({"members": [member]})

    def test_rejects_missing_or_unknown_member_fields(self) -> None:
        missing = dict(self.party["members"][0])
        del missing["moves"]
        unknown = dict(self.party["members"][0], nature="HARDY")
        for member, message in ((missing, "missing field"), (unknown, "unknown field")):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ContentPortError, message):
                    self.project({"members": [member]})


if __name__ == "__main__":
    unittest.main()
