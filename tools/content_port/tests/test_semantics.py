from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.content_port.errors import ContentPortError
from tools.content_port.semantics import (
    EventEntry,
    analyze_entry,
    load_event_policy,
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


if __name__ == "__main__":
    unittest.main()
