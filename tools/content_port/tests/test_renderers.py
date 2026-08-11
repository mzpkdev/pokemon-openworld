from __future__ import annotations

import copy
import unittest

from tools.content_port.errors import ContentPortError
from tools.content_port.renderers import (
    RenderContext,
    RenderUnit,
    render_unit,
    render_units,
)


class RendererTests(unittest.TestCase):
    def test_json_and_registry_rendering_are_stable(self) -> None:
        context = RenderContext("fixture")
        first = RenderUnit(
            "map", "map-json", "data/maps/Test/map.json", {"z": 1, "a": 2}
        )
        second = RenderUnit(
            "LAYOUT_TEST",
            "layout-registry",
            "data/layouts/layouts.json",
            {"id": "LAYOUT_TEST", "width": 4},
            slot=12,
        )
        manifest, payloads = render_units(context, [second, first])
        self.assertEqual(
            [unit.kind for unit in manifest.units], ["file", "registry-record"]
        )
        self.assertEqual(
            payloads[("file", "data/maps/Test/map.json")],
            b'{\n  "a": 2,\n  "z": 1\n}\n',
        )
        self.assertEqual(manifest.units[1].slot, 12)

    def test_binary_tileset_assets_are_byte_exact(self) -> None:
        output = render_unit(
            RenderContext("fixture"),
            RenderUnit(
                "assets",
                "tileset-assets",
                "unused.bin",
                {"data/tilesets/test/map.bin": b"\x00\xff\x01"},
            ),
        )[0]
        self.assertEqual(output.payload_bytes(), b"\x00\xff\x01")

    def test_generated_section_has_exact_markers(self) -> None:
        output = render_unit(
            RenderContext("fixture"),
            RenderUnit(
                "headers",
                "generated-section",
                "include/test.h",
                "int x;",
                name="headers",
            ),
        )[0]
        self.assertEqual(
            output.payload_bytes(),
            b"// CONTENT PORT BEGIN fixture:headers\nint x;\n// CONTENT PORT END fixture:headers\n",
        )

    def test_selected_trainer_script_repairs_separator_and_preserves_text(self) -> None:
        output = render_unit(
            RenderContext("johto"),
            RenderUnit(
                "script",
                "trainer-script",
                "data/maps/Route34/scripts.inc",
                {
                    "map": "Route34",
                    "events": [
                        {
                            "script": "Samuel",
                            "instructions": [
                                {
                                    "command": "trainerbattle_single",
                                    "operands": ["TRAINER_TARGET", "Seen", "Beaten"],
                                },
                                {"command": "end", "operands": []},
                            ],
                            "texts": [{"label": "Seen", "fragments": ['"Hello$"']}],
                        }
                    ],
                },
            ),
        )[0]
        self.assertEqual(
            output.payload_bytes(),
            b"Route34_MapScripts::\n\t.byte 0\n\nSamuel::\n"
            b"\ttrainerbattle_single TRAINER_TARGET, Seen, Beaten\n\tend\n\n"
            b'Seen:\n\t.string "Hello$"\n',
        )

    def test_selected_trainer_party_has_dedicated_preprocessor_section(self) -> None:
        record = {
            "target": "TRAINER_TARGET",
            "name": "SAMUEL",
            "class": "Youngster",
            "pic": "Youngster",
            "gender": "Male",
            "music": "Male",
            "double": False,
            "ai": ["Check Bad Move"],
            "party": [{"species": "SPECIES_TEDDIURSA", "level": 12, "iv": 0}],
        }
        output = render_unit(
            RenderContext("johto"),
            RenderUnit(
                "party",
                "trainer-party",
                "src/data/trainers.party",
                [record],
                name="selected trainer parties",
            ),
        )[0]
        self.assertIn(b"=== TRAINER_TARGET ===\nName: SAMUEL", output.payload_bytes())
        self.assertIn(b"Level: 12\nIVs: 0 HP / 0 Atk", output.payload_bytes())
        self.assertTrue(
            output.payload_bytes().startswith(b"#if 1 /* CONTENT PORT BEGIN")
        )
        for field, injected in (
            ("target", "TRAINER_TARGET\n=== TRAINER_UNSELECTED ==="),
            ("name", "SAMUEL\n=== TRAINER_UNSELECTED ==="),
        ):
            with self.subTest(injected_field=field):
                malicious = copy.deepcopy(record)
                malicious[field] = injected
                with self.assertRaisesRegex(
                    ContentPortError, "invalid trainer render token"
                ):
                    render_unit(
                        RenderContext("johto"),
                        RenderUnit(
                            "party",
                            "trainer-party",
                            "src/data/trainers.party",
                            [malicious],
                            name="selected trainer parties",
                        ),
                    )

    def test_unknown_renderer_and_hand_ownership_fail(self) -> None:
        with self.assertRaisesRegex(ContentPortError, "unknown expansion renderer"):
            render_unit(RenderContext("fixture"), RenderUnit("x", "made-up", "x", b"x"))
        with self.assertRaisesRegex(ContentPortError, "hand-owned path"):
            render_unit(
                RenderContext("fixture", hand_owned_paths=frozenset({"x"})),
                RenderUnit("x", "map-json", "x", {}),
            )
        with self.assertRaisesRegex(ContentPortError, "hand-owned section"):
            render_unit(
                RenderContext(
                    "fixture", hand_owned_sections=frozenset({("x", "unit")})
                ),
                RenderUnit("unit", "generated-section", "x", "value"),
            )


if __name__ == "__main__":
    unittest.main()
