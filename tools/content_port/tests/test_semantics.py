from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.content_port.errors import ContentPortError
from tools.content_port.semantics import (
    EventEntry,
    analyze_entry,
    extract_script_warps,
    load_event_policy,
    load_opcodes,
    parse_scripts,
    validate_effects,
)


class SemanticsTests(unittest.TestCase):
    def _program(self, main: str, include: str = ""):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        if include:
            (root / "shared.inc").write_text(include, encoding="utf-8")
            main = '.include "shared.inc"\n' + main
        (root / "main.inc").write_text(main, encoding="utf-8")
        return parse_scripts(["main.inc"], root=root)

    def test_follows_nested_calls_conditionals_and_includes(self) -> None:
        program = self._program(
            "Entry::\n call Shared\n goto_if_eq VAR_ROUTE_STATE, 1, .Done\n.Done::\n warp MAP_ROUTE, 0, 0, 0\n end\n",
            "Shared::\n setflag FLAG_VISITED\n applymovement 1, WalkAway\n return\n",
        )
        effects = analyze_entry(program, "Entry")
        keys = {(effect.kind, effect.operand) for effect in effects}
        self.assertIn(("state-write", "FLAG_VISITED"), keys)
        self.assertIn(("state-read", "VAR_ROUTE_STATE"), keys)
        self.assertIn(("movement", "WalkAway"), keys)
        self.assertIn(("warp", "MAP_ROUTE"), keys)

    def test_unknown_opcode_has_source_line(self) -> None:
        program = self._program("Entry::\n mystery FLAG_STORY\n end\n")
        with self.assertRaisesRegex(
            ContentPortError, r"main.inc:2: unknown script opcode mystery"
        ):
            analyze_entry(program, "Entry")

    def test_script_warp_evidence_binds_reached_command_and_literal_destination(
        self,
    ) -> None:
        program = self._program(
            "Entry::\n msgbox TravelText, MSGBOX_YESNO\n call .Travel\n end\n"
            ".Travel::\n warp MAP_OTHER_REGION, 6, 7\n end\n"
        )
        evidence = extract_script_warps(program, "Entry")
        self.assertEqual(len(evidence), 1)
        self.assertEqual(
            (
                evidence[0].entry,
                evidence[0].label,
                evidence[0].index,
                evidence[0].command,
                evidence[0].destination,
                evidence[0].x,
                evidence[0].y,
            ),
            ("Entry", "Entry.Travel", 0, "warp", "OTHER_REGION", 6, 7),
        )

    def test_script_warp_identity_is_label_local_and_ignores_harmless_edits(
        self,
    ) -> None:
        before = self._program(
            "Entry::\n msgbox TravelText, MSGBOX_YESNO\n warp MAP_OTHER, 1, 2\n end\n"
        )
        after = self._program(
            "Entry::\n lock\n msgbox TravelText, MSGBOX_YESNO\n"
            " waitbuttonpress\n warp MAP_OTHER, 1, 2\n end\n"
        )
        before_warp = extract_script_warps(before, "Entry")[0]
        after_warp = extract_script_warps(after, "Entry")[0]
        self.assertEqual(
            (
                before_warp.entry,
                before_warp.label,
                before_warp.index,
                before_warp.command,
                before_warp.destination,
                before_warp.x,
                before_warp.y,
            ),
            (
                after_warp.entry,
                after_warp.label,
                after_warp.index,
                after_warp.command,
                after_warp.destination,
                after_warp.x,
                after_warp.y,
            ),
        )

    def test_script_warp_closure_accepts_transient_departure_presentation(
        self,
    ) -> None:
        program = self._program(
            "Entry::\n applymovement LOCALID_SAILOR, SailorMovement\n"
            " waitmovement 0\n playse SE_EXIT\n special SpawnCameraObject\n"
            " removeobject OBJ_EVENT_ID_PLAYER\n delay 60\n"
            " warp MAP_OTHER, 1, 2\n end\n"
            "SailorMovement:\n walk_down\n step_end\n"
        )
        evidence = extract_script_warps(program, "Entry")
        self.assertEqual(
            (evidence[0].destination, evidence[0].x, evidence[0].y),
            ("OTHER", 1, 2),
        )

    def test_script_warp_closure_rejects_unapproved_special(self) -> None:
        program = self._program(
            "Entry::\n special DoStoryMutation\n warp MAP_OTHER, 1, 2\n end\n"
        )
        with self.assertRaisesRegex(
            ContentPortError,
            "unsupported special DoStoryMutation",
        ):
            extract_script_warps(program, "Entry")

    def test_script_warp_control_reaches_case_and_supports_warpsilent(self) -> None:
        program = self._program(
            "Entry::\n switch VAR_RESULT\n case 1, .Travel\n end\n"
            ".Travel::\n warpsilent MAP_OTHER, 6, 7\n waitstate\n end\n"
        )
        evidence = extract_script_warps(program, "Entry")
        self.assertEqual(
            (evidence[0].label, evidence[0].index, evidence[0].command),
            ("Entry.Travel", 0, "warpsilent"),
        )

    def test_script_warp_closure_rejects_unresolved_called_target(self) -> None:
        program = self._program(
            "Entry::\n call GlobalMutatingService\n warp MAP_OTHER, 6, 7\n end\n"
        )
        with self.assertRaisesRegex(
            ContentPortError,
            "unresolved control target GlobalMutatingService",
        ):
            extract_script_warps(program, "Entry")

    def test_external_call_without_local_warp_yields_no_evidence(self) -> None:
        program = self._program("Entry::\n call GlobalService\n end\n")
        self.assertEqual(extract_script_warps(program, "Entry"), ())

    def test_script_warp_control_accepts_legacy_case_separator(self) -> None:
        program = self._program(
            "Entry::\n switch VAR_RESULT\n case 7 .Travel\n end\n"
            ".Travel::\n warp MAP_OTHER, 6, 7\n end\n"
        )
        evidence = extract_script_warps(program, "Entry")
        self.assertEqual(evidence[0].label, "Entry.Travel")

    def test_legacy_case_separator_does_not_accept_ambiguous_operands(self) -> None:
        program = self._program(
            "Entry::\n case 7 .Travel extra\n end\n"
            ".Travel::\n warp MAP_OTHER, 6, 7\n end\n"
        )
        with self.assertRaisesRegex(ContentPortError, "lacks label operand 1"):
            extract_script_warps(program, "Entry")

    def test_script_warp_closure_rejects_state_mutation(self) -> None:
        program = self._program(
            "Entry::\n setflag FLAG_BADGE01_GET\n warp MAP_OTHER, 6, 7\n end\n"
        )
        with self.assertRaisesRegex(ContentPortError, "unsupported command setflag"):
            extract_script_warps(program, "Entry")

    def test_script_warp_closure_rejects_story_flag_condition(self) -> None:
        program = self._program(
            "Entry::\n goto_if_set FLAG_BADGE01_GET, .Travel\n end\n"
            ".Travel::\n warp MAP_OTHER, 6, 7\n end\n"
        )
        with self.assertRaisesRegex(
            ContentPortError, "unsupported command goto_if_set"
        ):
            extract_script_warps(program, "Entry")

    def test_script_warp_choice_switch_must_use_result(self) -> None:
        program = self._program(
            "Entry::\n switch VAR_STORY\n case 1, .Travel\n end\n"
            ".Travel::\n warp MAP_OTHER, 6, 7\n end\n"
        )
        with self.assertRaisesRegex(ContentPortError, "must inspect VAR_RESULT"):
            extract_script_warps(program, "Entry")

    def test_persistent_script_warp_effect_is_not_world_graph_evidence(self) -> None:
        program = self._program("Entry::\n setwarp MAP_OTHER_REGION, 6, 7\n end\n")
        with self.assertRaisesRegex(ContentPortError, "unsupported persistent"):
            extract_script_warps(program, "Entry")

    def test_dynamic_warp_arming_precedes_immediate_travel_edge(self) -> None:
        program = self._program(
            "Entry::\n setdynamicwarp MAP_RETURN_BERTH, 8, 9\n"
            " warp MAP_SHIP, 29, 3\n end\n"
        )
        evidence = extract_script_warps(program, "Entry")
        self.assertEqual(len(evidence), 1)
        self.assertEqual(
            (
                evidence[0].command,
                evidence[0].destination,
                evidence[0].x,
                evidence[0].y,
            ),
            ("warp", "SHIP", 29, 3),
        )
        arm = evidence[0].dynamic_arm
        self.assertIsNotNone(arm)
        self.assertEqual(
            (arm.entry, arm.label, arm.index, arm.destination, arm.x, arm.y),
            ("Entry", "Entry", 0, "RETURN_BERTH", 8, 9),
        )

    def test_dynamic_warp_arming_supports_immediate_silent_travel(self) -> None:
        program = self._program(
            "Entry::\n setdynamicwarp MAP_RETURN_BERTH, 8, 9\n"
            " warpsilent MAP_SHIP, 29, 3\n end\n"
        )
        evidence = extract_script_warps(program, "Entry")
        self.assertEqual(
            (evidence[0].command, evidence[0].destination),
            ("warpsilent", "SHIP"),
        )

    def test_dynamic_warp_arming_must_be_literal_and_immediately_paired(self) -> None:
        cases = {
            "unpaired": (
                "setdynamicwarp MAP_RETURN, 1, 2\n msgbox Text, MSGBOX_DEFAULT",
                "must be immediately followed",
            ),
            "malformed": (
                "setdynamicwarp MAP_RETURN, 1\n warp MAP_SHIP, 2, 3",
                "requires literal destination",
            ),
            "nonliteral map": (
                "setdynamicwarp VAR_RETURN_MAP, 1, 2\n warp MAP_SHIP, 2, 3",
                "literal MAP_\\* identity",
            ),
            "nonliteral coordinate": (
                "setdynamicwarp MAP_RETURN, VAR_X, 2\n warp MAP_SHIP, 2, 3",
                "coordinates must be integer literals",
            ),
            "negative coordinate": (
                "setdynamicwarp MAP_RETURN, -1, 2\n warp MAP_SHIP, 2, 3",
                "coordinates must be non-negative",
            ),
        }
        for label, (body, message) in cases.items():
            with self.subTest(label=label):
                program = self._program(f"Entry::\n {body}\n end\n")
                with self.assertRaisesRegex(ContentPortError, message):
                    extract_script_warps(program, "Entry")

    def test_dynamic_warp_arming_cannot_pair_across_labels(self) -> None:
        program = self._program(
            "Entry::\n setdynamicwarp MAP_RETURN, 1, 2\n"
            " goto .Travel\n.Travel::\n warp MAP_SHIP, 2, 3\n end\n"
        )
        with self.assertRaisesRegex(ContentPortError, "same label"):
            extract_script_warps(program, "Entry")

    def test_hns_single_battle_separator_and_text_are_typed(self) -> None:
        program = self._program(
            "Entry::\n trainerbattle_single TRAINER_SAMUEL Seen, Beaten\n"
            " msgbox After, MSGBOX_AUTOCLOSE\n end\n"
            'Seen:\n .string "Seen$"\nBeaten:\n .string "Beaten$"\n'
            'After:\n .string "First\\p"\n .string "Second$"\n'
        )
        self.assertEqual(
            program.labels["Entry"][0].operands,
            ("TRAINER_SAMUEL", "Seen", "Beaten"),
        )
        self.assertEqual(program.texts["After"], ('"First\\p"', '"Second$"'))

    def test_separator_adaptation_is_not_applied_to_other_shapes(self) -> None:
        program = self._program(
            "Entry::\n trainerbattle_single TRAINER_SAMUEL Seen Beaten, After\n end\n"
        )
        self.assertEqual(
            program.labels["Entry"][0].operands,
            ("TRAINER_SAMUEL Seen Beaten", "After"),
        )

    def test_includes_cannot_escape_authenticated_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "donor"
            root.mkdir()
            external = parent / "external.inc"
            external.write_text("External::\n end\n", encoding="utf-8")
            main = root / "main.inc"
            cases = {
                "parent": "../external.inc",
                "absolute": external.as_posix(),
                "symlink": "external-link.inc",
            }
            (root / "external-link.inc").symlink_to(external)
            for label, include in cases.items():
                with self.subTest(label=label):
                    main.write_text(
                        f'.include "{include}"\nEntry::\n end\n', encoding="utf-8"
                    )
                    with self.assertRaisesRegex(
                        ContentPortError,
                        "unsafe script include|authenticated root|symlink",
                    ):
                        parse_scripts([main], root=root)

    def test_effect_ownership_is_exact_and_story_rejected(self) -> None:
        program = self._program("Entry::\n setflag FLAG_STORY\n end\n")
        effect = analyze_entry(program, "Entry")
        entry = EventEntry("Entry", "ambient", "enabled")
        with self.assertRaisesRegex(ContentPortError, "owner=story-owned"):
            validate_effects(
                entry, effect, {("state-write", "setflag", "FLAG_STORY"): "story-owned"}
            )
        with self.assertRaisesRegex(ContentPortError, "owner=services"):
            validate_effects(
                entry, effect, {("state-write", "setflag", "FLAG_STORY"): "services"}
            )

    def test_story_classification_never_enters_closure(self) -> None:
        with self.assertRaisesRegex(ContentPortError, "story-owned"):
            validate_effects(EventEntry("Story", "ambient", "story-owned"), (), {})

    def test_johto_policy_names_reviewed_story_entries(self) -> None:
        entries, policy = load_event_policy(
            "tools/content_port/ports/johto/events.json"
        )
        entry = entries["NewBarkTown_OnTransition"]
        self.assertEqual(entry.classification, "story-owned")
        self.assertEqual(
            policy[("state-read", "goto_if_eq", "VAR_NEWBARK_TOWN_STATE")],
            "story-owned",
        )
        self.assertNotIn("Route34_EventScript_YoungsterSamuel", entries)
        self.assertNotIn("Route39_EventScript_Eugene", entries)
        self.assertFalse(any(owner == "trainers" for owner in policy.values()))

    def test_opcode_schema_is_exact_required_versioned_and_typed(self) -> None:
        valid = {
            "schemaVersion": 1,
            "opcodes": {
                "end": {
                    "effects": [],
                    "calls": [],
                    "dependencies": [],
                    "terminal": False,
                }
            },
        }
        mutations = {
            "version": lambda value: value.update(schemaVersion=999),
            "missing effects": lambda value: value["opcodes"]["end"].pop("effects"),
            "missing calls": lambda value: value["opcodes"]["end"].pop("calls"),
            "missing dependencies": lambda value: value["opcodes"]["end"].pop(
                "dependencies"
            ),
            "coerced boolean": lambda value: value["opcodes"]["end"].update(
                terminal="false"
            ),
            "unknown nested": lambda value: value["opcodes"]["end"].update(effectz=[]),
            "unknown top": lambda value: value.update(entries=[]),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                document = json.loads(json.dumps(valid))
                mutate(document)
                path = Path(directory) / "opcodes.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(ContentPortError):
                    load_opcodes(path)

    def test_event_policy_schema_rejects_misspellings_unknowns_and_coercion(
        self,
    ) -> None:
        valid = {
            "schemaVersion": 1,
            "entries": [
                {
                    "name": "Entry",
                    "capability": "ambient",
                    "classification": "enabled",
                }
            ],
            "effects": [
                {
                    "kind": "state-read",
                    "command": "checkflag",
                    "operand": "FLAG_TEST",
                    "owner": "ambient",
                }
            ],
        }
        mutations = {
            "version": lambda value: value.update(schemaVersion=999),
            "misspelled entries": lambda value: value.update(
                entires=value.pop("entries")
            ),
            "unknown entry": lambda value: value["entries"][0].update(extra=False),
            "missing entry field": lambda value: value["entries"][0].pop("capability"),
            "unknown effect": lambda value: value["effects"][0].update(extra=False),
            "coerced string": lambda value: value["entries"][0].update(name=False),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                document = json.loads(json.dumps(valid))
                mutate(document)
                path = Path(directory) / "events.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(ContentPortError):
                    load_event_policy(path)


if __name__ == "__main__":
    unittest.main()
