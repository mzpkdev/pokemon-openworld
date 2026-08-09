from __future__ import annotations

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
        )
        manifest, payloads = render_units(context, [second, first])
        self.assertEqual(
            [unit.kind for unit in manifest.units], ["file", "registry-record"]
        )
        self.assertEqual(
            payloads[("file", "data/maps/Test/map.json")],
            b'{\n  "a": 2,\n  "z": 1\n}\n',
        )

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
