"""Render a static pokeemerald-family map layout without engine dependencies."""

import argparse
import json
import re
import struct
import zlib
from pathlib import Path


def read_define(path: Path, name: str) -> int:
    match = re.search(
        rf"^\s*#define\s+{re.escape(name)}\s+(\d+)\s*$",
        path.read_text(),
        re.MULTILINE,
    )
    if not match:
        raise ValueError(f"cannot resolve {name} from {path}")
    return int(match.group(1))


def read_indexed_png(path: Path) -> tuple[int, int, list[bytearray]]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")

    position = 8
    chunks: dict[bytes, bytes] = {}
    image_data: list[bytes] = []
    while position < len(data):
        size = struct.unpack(">I", data[position : position + 4])[0]
        kind = data[position + 4 : position + 8]
        payload = data[position + 8 : position + 8 + size]
        position += 12 + size
        if kind == b"IDAT":
            image_data.append(payload)
        else:
            chunks[kind] = payload
        if kind == b"IEND":
            break

    width, height, depth, color, _, _, interlace = struct.unpack(
        ">IIBBBBB", chunks[b"IHDR"]
    )
    if color != 3 or depth not in (4, 8) or interlace != 0:
        raise ValueError(
            f"unsupported PNG format in {path}: "
            f"depth={depth}, color={color}, interlace={interlace}"
        )

    raw = zlib.decompress(b"".join(image_data))
    packed_width = (width * depth + 7) // 8
    previous = bytearray(packed_width)
    rows: list[bytearray] = []
    offset = 0
    for _ in range(height):
        mode = raw[offset]
        scan = bytearray(raw[offset + 1 : offset + 1 + packed_width])
        offset += packed_width + 1
        for x in range(packed_width):
            left = scan[x - 1] if x else 0
            above = previous[x]
            upper_left = previous[x - 1] if x else 0
            if mode == 1:
                scan[x] = (scan[x] + left) & 255
            elif mode == 2:
                scan[x] = (scan[x] + above) & 255
            elif mode == 3:
                scan[x] = (scan[x] + ((left + above) // 2)) & 255
            elif mode == 4:
                estimate = left + above - upper_left
                left_distance = abs(estimate - left)
                above_distance = abs(estimate - above)
                corner_distance = abs(estimate - upper_left)
                if left_distance <= above_distance and left_distance <= corner_distance:
                    predictor = left
                elif above_distance <= corner_distance:
                    predictor = above
                else:
                    predictor = upper_left
                scan[x] = (scan[x] + predictor) & 255
            elif mode != 0:
                raise ValueError(f"unsupported PNG filter {mode}")
        if depth == 4:
            rows.append(
                bytearray(value for byte in scan for value in (byte >> 4, byte & 0xF))[
                    :width
                ]
            )
        else:
            rows.append(scan)
        previous = scan
    return width, height, rows


def read_palette(path: Path) -> list[tuple[int, int, int]]:
    lines = path.read_text().splitlines()
    colors = [tuple(map(int, line.split())) for line in lines[3:19]]
    return colors + [(0, 0, 0)] * (16 - len(colors))


def write_rgb_png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw.extend(pixels[y * stride : (y + 1) * stride])

    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", checksum)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def resolve_tileset_dir(root: Path, symbol: str) -> Path:
    graphics = (root / "src/data/tilesets/graphics.h").read_text()
    stem = symbol.removeprefix("gTileset_")
    match = re.search(
        rf"gTilesetTiles_{re.escape(stem)}\[\].*?"
        r'"([^"]+)/tiles(?:\.png|\.4bpp(?:\.lz)?)"',
        graphics,
    )
    if match:
        return root / match.group(1)

    snake_name = re.sub(r"(?<!^)(?=[A-Z])", "_", stem).lower()
    for kind in ("primary", "secondary"):
        candidate = root / "data/tilesets" / kind / snake_name
        if candidate.joinpath("tiles.png").exists():
            return candidate
    raise ValueError(f"cannot resolve {symbol}")


def resolve_tileset_assets(root: Path, symbol: str) -> tuple[Path, Path, Path]:
    headers = (root / "src/data/tilesets/headers.h").read_text()
    graphics = (root / "src/data/tilesets/graphics.h").read_text()
    metatiles = (root / "src/data/tilesets/metatiles.h").read_text()
    header_match = re.search(
        rf"const struct Tileset {re.escape(symbol)}\s*=\s*\{{(.*?)\}};",
        headers,
        re.DOTALL,
    )
    if header_match:
        fields = dict(
            re.findall(r"\.(tiles|palettes|metatiles)\s*=\s*(\w+)", header_match[1])
        )
        patterns = {
            "tiles": (
                graphics,
                r'\[\].*?"([^"]+/tiles(?:\.png|\.4bpp(?:\.lz)?))"',
            ),
            "palettes": (graphics, r'.*?\{.*?"([^"]+/palettes/\d+\.pal)"'),
            "metatiles": (metatiles, r'\[\].*?"([^"]+/metatiles\.bin)"'),
        }
        paths = {}
        for field, (source, pattern) in patterns.items():
            resource = fields.get(field)
            match = (
                re.search(rf"{re.escape(resource)}{pattern}", source, re.DOTALL)
                if resource
                else None
            )
            if match:
                paths[field] = root / match[1]
        if len(paths) == 3:
            return paths["tiles"], paths["palettes"].parent, paths["metatiles"]

    directory = resolve_tileset_dir(root, symbol)
    return directory / "tiles.png", directory / "palettes", directory / "metatiles.bin"


def read_layout_format_counts(root: Path, layout_format: str) -> tuple[int, int, int]:
    fieldmap = root / "include/fieldmap.h"
    if layout_format == "emerald":
        return (
            read_define(fieldmap, "NUM_TILES_IN_PRIMARY"),
            read_define(fieldmap, "NUM_METATILES_IN_PRIMARY"),
            read_define(fieldmap, "NUM_PALS_IN_PRIMARY"),
        )
    if layout_format == "frlg":
        return (
            read_define(fieldmap, "NUM_TILES_IN_PRIMARY_FRLG"),
            read_define(fieldmap, "NUM_METATILES_IN_PRIMARY_FRLG"),
            read_define(fieldmap, "NUM_PALS_IN_PRIMARY_FRLG"),
        )
    if layout_format == "johto":
        fieldmap_source = (root / "src/fieldmap.c").read_text()
        match = re.search(
            r"\[MAP_LAYOUT_FORMAT_JOHTO\]\s*=\s*\{\s*"
            r"(\d+),\s*(\d+),\s*(\d+),",
            fieldmap_source,
        )
        if match:
            return tuple(map(int, match.groups()))
    raise ValueError(f"unsupported map layout format: {layout_format}")


def split_tiles(
    image_width: int, image_height: int, rows: list[bytearray]
) -> list[bytes]:
    return [
        b"".join(bytes(rows[tile_y + y][tile_x : tile_x + 8]) for y in range(8))
        for tile_y in range(0, image_height, 8)
        for tile_x in range(0, image_width, 8)
    ]


def render(root: Path, map_name: str, output: Path, *, announce: bool = True) -> None:
    layouts = json.loads((root / "data/layouts/layouts.json").read_text())["layouts"]
    map_data = json.loads((root / f"data/maps/{map_name}/map.json").read_text())
    layout = next(item for item in layouts if item["id"] == map_data["layout"])
    primary_tile_count, primary_metatile_count, primary_palette_count = (
        read_layout_format_counts(root, layout.get("format", "emerald"))
    )
    palette_count = read_define(root / "include/fieldmap.h", "NUM_PALS_TOTAL")
    primary_tiles_path, primary_palettes, primary_metatiles_path = (
        resolve_tileset_assets(root, layout["primary_tileset"])
    )
    secondary_tiles_path, secondary_palettes, secondary_metatiles_path = (
        resolve_tileset_assets(root, layout["secondary_tileset"])
    )

    primary_width, primary_height, primary_pixels = read_indexed_png(primary_tiles_path)
    secondary_width, secondary_height, secondary_pixels = read_indexed_png(
        secondary_tiles_path
    )
    primary_tiles = split_tiles(primary_width, primary_height, primary_pixels)
    secondary_tiles = split_tiles(secondary_width, secondary_height, secondary_pixels)
    primary_metatiles = primary_metatiles_path.read_bytes()
    secondary_metatiles = secondary_metatiles_path.read_bytes()

    palettes = []
    for index in range(palette_count):
        palette_root = (
            primary_palettes if index < primary_palette_count else secondary_palettes
        )
        palette_path = palette_root / f"{index:02}.pal"
        if not palette_path.exists():
            fallback_root = (
                secondary_palettes
                if palette_root == primary_palettes
                else primary_palettes
            )
            palette_path = fallback_root / f"{index:02}.pal"
        palettes.append(read_palette(palette_path))

    width, height = layout["width"], layout["height"]
    blockdata = (root / layout["blockdata_filepath"]).read_bytes()
    map_words = struct.unpack(f"<{width * height}H", blockdata)
    output_width, output_height = width * 16, height * 16
    output_pixels = bytearray(output_width * output_height * 3)

    def draw_tile(
        tile_word: int,
        secondary_source: bool,
        destination_x: int,
        destination_y: int,
        transparent: bool,
    ) -> None:
        tile_id = tile_word & 0x3FF
        horizontal_flip = bool(tile_word & 0x400)
        vertical_flip = bool(tile_word & 0x800)
        palette_index = (tile_word >> 12) & 0xF
        palette = (
            palettes[palette_index] if palette_index < len(palettes) else palettes[0]
        )
        if secondary_source and tile_id >= primary_tile_count:
            secondary_index = tile_id - primary_tile_count
            tile = (
                secondary_tiles[secondary_index]
                if secondary_index < len(secondary_tiles)
                else bytes(64)
            )
        else:
            tile = primary_tiles[tile_id] if tile_id < len(primary_tiles) else bytes(64)

        for pixel_y in range(8):
            source_y = 7 - pixel_y if vertical_flip else pixel_y
            for pixel_x in range(8):
                source_x = 7 - pixel_x if horizontal_flip else pixel_x
                color_index = tile[source_y * 8 + source_x]
                if transparent and color_index == 0:
                    continue
                rgb = palette[color_index]
                output_offset = (
                    (destination_y + pixel_y) * output_width + destination_x + pixel_x
                ) * 3
                output_pixels[output_offset : output_offset + 3] = bytes(rgb)

    for map_y in range(height):
        for map_x in range(width):
            metatile_id = map_words[map_y * width + map_x] & 0x3FF
            secondary_source = metatile_id >= primary_metatile_count
            if secondary_source:
                start = (metatile_id - primary_metatile_count) * 16
                payload = secondary_metatiles[start : start + 16]
            else:
                start = metatile_id * 16
                payload = primary_metatiles[start : start + 16]
            metatile_words = (
                struct.unpack("<8H", payload) if len(payload) == 16 else (0,) * 8
            )
            for layer in range(2):
                for quadrant in range(4):
                    quadrant_x, quadrant_y = quadrant % 2, quadrant // 2
                    draw_tile(
                        metatile_words[layer * 4 + quadrant],
                        secondary_source,
                        map_x * 16 + quadrant_x * 8,
                        map_y * 16 + quadrant_y * 8,
                        transparent=layer == 1,
                    )

    output.parent.mkdir(parents=True, exist_ok=True)
    write_rgb_png(output, output_width, output_height, output_pixels)
    if announce:
        print(f"{map_name}: {width}x{height} metatiles -> {output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render one static pokeemerald-family map layout as a PNG."
    )
    parser.add_argument("root", type=Path, help="repository or pinned donor root")
    parser.add_argument("map", help="map directory name")
    parser.add_argument("output", type=Path, help="output PNG")
    arguments = parser.parse_args()
    render(arguments.root, arguments.map, arguments.output)


if __name__ == "__main__":
    main()
