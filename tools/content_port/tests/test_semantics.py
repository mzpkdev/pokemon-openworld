from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.content_port.errors import ContentPortError
from tools.content_port.semantics import (
    EventEntry,
    analyze_entry,
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

    def test_opcode_schema_is_exact_required_versioned_and_typed(self) -> None:
        valid = {
            "schemaVersion": 1,
            "opcodes": {"end": {"effects": [], "calls": [], "terminal": False}},
        }
        mutations = {
            "version": lambda value: value.update(schemaVersion=999),
            "missing effects": lambda value: value["opcodes"]["end"].pop("effects"),
            "missing calls": lambda value: value["opcodes"]["end"].pop("calls"),
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
