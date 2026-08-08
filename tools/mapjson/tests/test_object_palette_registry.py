import json
import re
import subprocess
import unittest
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MAPS = sorted((ROOT / "data" / "maps").glob("*/map.json"))
POINTERS = ROOT / "src/data/object_events/object_event_graphics_info_pointers.h"
GRAPHICS_INFO = ROOT / "src/data/object_events/object_event_graphics_info.h"
PALETTE_REGISTRY = ROOT / "src/event_object_movement.c"


def _map_graphics_usages() -> dict[str, set[str]]:
    usages: dict[str, set[str]] = defaultdict(set)
    for path in MAPS:
        data = json.loads(path.read_text())
        for obj in data.get("object_events", []):
            graphics_id = obj["graphics_id"]
            if (
                graphics_id == "0"
                or graphics_id.startswith("OBJ_EVENT_GFX_VAR_")
                or graphics_id.startswith("OBJ_EVENT_GFX_SPECIES(")
            ):
                continue
            usages[graphics_id].add(data["name"])
    return usages


def _graphics_info_by_id() -> dict[str, str]:
    return dict(
        re.findall(
            r"\[(OBJ_EVENT_GFX_[A-Z0-9_]+)\]\s*=\s*"
            r"&(gObjectEventGraphicsInfo_[A-Za-z0-9_]+)",
            POINTERS.read_text(),
        )
    )


def _palette_tag_by_graphics_info() -> dict[str, str]:
    result: dict[str, str] = {}
    source = GRAPHICS_INFO.read_text()
    for name, body in re.findall(
        r"const struct ObjectEventGraphicsInfo "
        r"(gObjectEventGraphicsInfo_[A-Za-z0-9_]+)\s*=\s*\{(.*?)^\};",
        source,
        re.MULTILINE | re.DOTALL,
    ):
        match = re.search(r"\.paletteTag\s*=\s*([A-Z0-9_]+)", body)
        if match:
            result[name] = match.group(1)
    return result


def _product_palette_tags() -> set[str]:
    source = PALETTE_REGISTRY.read_text()
    match = re.search(
        r"static const struct SpritePalette sObjectEventSpritePalettes\[\] = "
        r"\{(.*?)^\};",
        source,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError("object-event palette registry not found")

    product_registry = subprocess.run(
        ["cpp", "-P"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
        input=(
            "#define IS_FRLG 0\n"
            "#define ALL_REGIONS 1\n"
            "#define HAS_FRLG_TILESETS (IS_FRLG || ALL_REGIONS)\n"
            "#define BUGFIX\n" + match.group(0)
        ),
    ).stdout
    return set(re.findall(r"OBJ_EVENT_PAL_TAG_[A-Z0-9_]+", product_registry))


class ObjectPaletteRegistryTests(unittest.TestCase):
    def test_every_map_object_graphic_has_a_registered_product_palette(self) -> None:
        usages = _map_graphics_usages()
        graphics_info_by_id = _graphics_info_by_id()
        palette_tag_by_info = _palette_tag_by_graphics_info()
        registered_tags = _product_palette_tags()

        unresolved_graphics = sorted(set(usages) - set(graphics_info_by_id))
        if unresolved_graphics:
            self.fail("unresolved object graphics:\n" + "\n".join(unresolved_graphics))

        missing: list[str] = []
        for graphics_id, maps in sorted(usages.items()):
            info = graphics_info_by_id[graphics_id]
            palette_tag = palette_tag_by_info.get(info)
            if palette_tag is None:
                missing.append(
                    f"{graphics_id}: no palette tag ({', '.join(sorted(maps))})"
                )
            elif palette_tag not in registered_tags:
                missing.append(
                    f"{graphics_id}: {palette_tag} ({', '.join(sorted(maps))})"
                )

        if missing:
            self.fail("unregistered object palettes:\n" + "\n".join(missing))


if __name__ == "__main__":
    unittest.main()
