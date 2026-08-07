#!/usr/bin/env python3
"""Deterministically validate and materialize the reviewed Johto donor slice.

This tool never writes to either donor.  ``--apply`` writes the validated source
closure into the target repository and a deterministic report to the output path.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


JOHTO_FLAGS = (
    "FLAG_COMPLETED_AERODACTYL_PUZZLE",
    "FLAG_COMPLETED_HOOH_PUZZLE",
    "FLAG_COMPLETED_KABUTO_PUZZLE",
    "FLAG_COMPLETED_OMANYTE_PUZZLE",
    "FLAG_DAY_POKEMON",
    "FLAG_EXP_SHARE",
    "FLAG_GOT_MYSTICWATER",
    "FLAG_GOT_SILK_SCARF",
    "FLAG_GOT_TM_STEEL_WING",
    "FLAG_HIDE_CHERRYGROVE_GUIDE_GENT_HOUSE",
    "FLAG_HIDE_CHIKORITABALL",
    "FLAG_HIDE_CYNDAQUILBALL",
    "FLAG_HIDE_ECRUTEAK_CITY_THEATER_KIMONOS",
    "FLAG_HIDE_ECRUTEAK_CITY_THEATER_NPCS",
    "FLAG_HIDE_ECRUTEAK_SILVER",
    "FLAG_HIDE_GUIDE_GENT_CHERRYGROVE",
    "FLAG_HIDE_LAB_POLICEMAN",
    "FLAG_HIDE_MOMS_FRIEND",
    "FLAG_HIDE_MOMS_FRIEND2",
    "FLAG_HIDE_NEWBARKTOWN_LAB_AIDE",
    "FLAG_HIDE_OLIVINE_PORT_OAK",
    "FLAG_HIDE_ROUTE_30_NPCS",
    "FLAG_HIDE_SILVER_CHERRYGROVE",
    "FLAG_HIDE_SILVER_NEWBARKTOWN",
    "FLAG_HIDE_SSAQUA_1F_GRANDPA",
    "FLAG_HIDE_TOTODILEBALL",
    "FLAG_ITEM_ROUTE_29_POTION",
    "FLAG_MOM_VISITED",
    "FLAG_NIGHT_POKEMON",
    "FLAG_RECEIVED_FIRST_BALLS",
    "FLAG_RECEIVED_FIRST_POTION",
    "FLAG_SHOWN_ELM_TOGEPI",
    "FLAG_VISITED_CHERRYGROVE_CITY",
    "FLAG_VISITED_NEWBARK_TOWN",
)
JOHTO_VARS = (
    "VAR_CHERRYGROVE_CITY_STATE",
    "VAR_ECRUTEAK_CITY_THEATER",
    "VAR_GOLDENROD_CITY_STATE",
    "VAR_NEWBARKTOWN_LABSTATE",
    "VAR_NEWBARK_TOWN_STATE",
)


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
INCLUDE_RE = re.compile(r'^\s*\.include\s+"([^"]+)"', re.MULTILINE)
LABEL_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)::?", re.MULTILINE)
TILESET_BLOB_RE = re.compile(
    r'g(?P<kind>Metatiles|MetatileAttributes)_(?P<name>\w+)\[\].*?"(?P<path>[^"]+)"'
)
GENERATED_ARTIFACTS = {
    "pokemonworld.elf",
    "pokemonworld.map",
    "pokemonworld.sym",
    "pokemonworld.gba",
}
REVIEWED_DONOR_PINS = {
    "mechanicalDonor": {
        "repository": "evilchinesefood/PKMN-World",
        "commit": "d40affe26e58a20f445daad84af5e45be812e69f",
        "sourceTreeDigest": "6bca91e491e7e8304f9268aa41a4c9d629d50baa6d3150fe45d55632b6f4f762",
        "sourceTreeFileCount": 32382,
    },
    "contentAuthority": {
        "repository": "PokemonHnS-Development/pokemonHnS",
        "commit": "751823abaf677020bcd72c45fe3e7cb2b8a576e4",
        "sourceTreeDigest": "6fc60f734085eb0ba6df3f68855cc8b91564499fb0f960eb2d7cffe3cc379703",
        "sourceTreeFileCount": 18314,
    },
}

GAMEPLAY_EVENT_KEYS = ("object_events", "coord_events", "bg_events")
SAVED_LOCATION_INVALID = 0xFF
MET_LOCATION_INVALID = 0xFC
FALLBACK_MAPS = (
    "JohtoIndigoPlateau",
    "JohtoIndigoPlateau_PokemonCenter",
    "JohtoPokemonLeague_BrunosRoom",
    "JohtoPokemonLeague_ChampionsRoom",
    "JohtoPokemonLeague_HallOfFame",
    "JohtoPokemonLeague_KarensRoom",
    "JohtoPokemonLeague_KogasRoom",
    "JohtoPokemonLeague_WillsRoom",
    "JohtoVictoryRoad_1F",
    "JohtoVictoryRoad_B1F",
    "JohtoVictoryRoad_B2F",
    "MahoganyHideout_B1F",
    "MahoganyHideout_B2F",
    "MahoganyHideout_B3F",
)
FINAL_INVENTORY_COUNTS = (254, 255, 25, 58, 71)
FALLBACK_SECTION_METADATA = (
    "MAPSEC_JOHTO_INDIGO_PLATEAU",
    "MAPSEC_MAHOGANY_HIDEOUT",
)
LAYOUT_HEADER_DECISION_KEYS = (
    *(
        (f"LAYOUT_GOLDENROD_CITY_DEPARTMENT_STORE_{floor}F", "secondary_tileset")
        for floor in range(1, 7)
    ),
    ("LAYOUT_GOLDENROD_CITY_GAME_CORNER", "secondary_tileset"),
    ("LAYOUT_NATIONAL_PARK_NORMAL", "primary_tileset"),
    ("LAYOUT_NATIONAL_PARK_BUG_CONTEST", "primary_tileset"),
    ("LAYOUT_SAFARI_ZONE_GATE_SAFARI_ZONE_ENTRANCE", "name"),
)
MAP_FIELD_DECISION_KEYS = (("ReceptionGate", "region_map_section"),)
SECTION_SYMBOL_REMAP_KEYS = (
    ("MAPSEC_VERMILION_CITY", "MAPSEC_JOHTO_VERMILION_PORT", 260),
)
LAYOUT_TILESET_REMAP_KEYS = (("LAYOUT_ROUTE34_DAY_CARE", "secondary_tileset"),)
ATTRIBUTE_FIXTURE_KEYS = (
    ("route28-primary", "LAYOUT_ROUTE28", "primary", "mechanical"),
    ("route28-secondary", "LAYOUT_ROUTE28", "secondary", "mechanical"),
    ("ecruteak-exterior", "LAYOUT_ECRUTEAK_CITY", "secondary", "hns"),
    (
        "olivine-interior",
        "LAYOUT_OLIVINE_CITY_PORT_INSIDE",
        "secondary",
        "hns",
    ),
    ("whirl-cave", "LAYOUT_WHIRL_ISLANDS_1F", "secondary", "hns"),
)
PRESERVE_SPATIAL_UPDATE_KEYS = (
    ("CherrygroveCity", "early-violet-ruins", ("connections",)),
    ("Gate_Route29_Route46", "blackthorn-ice-dark-den", ("warp_events",)),
    (
        "Route29",
        "blackthorn-ice-dark-den",
        ("connections", "warp_events"),
    ),
    ("NewBarkTown", "tohjo-league-hns", ("connections",)),
    (
        "Route28",
        "tohjo-league-hns",
        ("connections", "warp_events"),
    ),
    ("Route28_House", "tohjo-league-hns", ("warp_events",)),
)
INACTIVE_GROUP_PLACEHOLDER_KEYS = (("gMapGroup_IndoorSSAqua", 96, "aqua-vermilion"),)
BATCH_GROUPS = {
    "early-violet-ruins": (
        "gMapGroup_JohtoViolet",
        "gMapGroup_JohtoRuins",
    ),
    "azalea-union-ilex": (
        "gMapGroup_JohtoAzalea",
        "gMapGroup_IndoorAzalea",
        "gMapGroup_JohtoUnion",
    ),
    "goldenrod-park": (
        "gMapGroup_JohtoGoldenrod",
        "gMapGroup_IndoorGoldenrod",
    ),
    "ecruteak-towers": (
        "gMapGroup_JohtoEcruteak",
        "gMapGroup_IndoorEcruteak",
    ),
    "olivine-cianwood-whirl": (
        "gMapGroup_JohtoOlivine",
        "gMapGroup_IndoorOlivine",
        "gMapGroup_JohtoCianwood",
        "gMapGroup_IndoorCianwood",
    ),
    "mahogany-hns": (
        "gMapGroup_JohtoMahogany",
        "gMapGroup_IndoorMahogany",
    ),
    "blackthorn-ice-dark-den": (
        "gMapGroup_JohtoBlackthorn",
        "gMapGroup_IndoorBlackthorn",
    ),
    "safari": ("gMapGroup_SafariZoneJohto",),
    "mt-silver": ("gMapGroup_MtSilver",),
    "aqua-vermilion": ("gMapGroup_IndoorSSAqua",),
    "tohjo-league-hns": ("gMapGroup_JohtoFinal",),
}
BATCH_ORDER = (
    "baseline",
    *BATCH_GROUPS,
    "pkmn-world-fallback",
)
REVIEWED_AUTHORITY_ADAPTATIONS = (
    (
        "baseline",
        "NewBarkTown",
        "warp_events/4/dest_map",
        "MAP_WORLD_HUB",
        "MAP_NEW_BARK_TOWN_LAB",
        "dormant first-slice story/debug transition",
    ),
    (
        "baseline",
        "NewBarkTown",
        "warp_events/5/dest_map",
        "MAP_TIN_TOWER_ROOF_DAY",
        "MAP_NEW_BARK_TOWN_LAB",
        "dormant first-slice story/debug transition",
    ),
    (
        "baseline",
        "NewBarkTown",
        "warp_events/7/dest_map",
        "MAP_WORLD_HUB",
        "MAP_NEW_BARK_TOWN_LAB",
        "dormant first-slice story/debug transition",
    ),
    (
        "baseline",
        "NewBarkTown_PlayersHouse_2F",
        "warp_events/1/dest_map",
        "MAP_NEW_BARK_TOWN_PLAYERS_HOUSE_2F",
        "MAP_NEW_BARK_TOWN_PLAYERS_HOUSE_1F",
        "mechanical donor fixes the downstairs return warp",
    ),
    (
        "baseline",
        "NewBarkTown_PlayersHouse_2F",
        "warp_events/1/dest_warp_id",
        "0",
        "1",
        "mechanical donor fixes the downstairs return warp",
    ),
    (
        "aqua-vermilion",
        "SSAqua_1F",
        "warp_events/0/dest_warp_id",
        "1",
        "0",
        "mechanical donor fixes the Olivine port return to the target's only warp",
    ),
    (
        "tohjo-league-hns",
        "ReceptionGate",
        "warp_events/1/dest_map",
        "MAP_VICTORY_ROAD_KANTO_B2F",
        "MAP_JOHTO_VICTORY_ROAD_1F",
        "mechanical Johto membership defers the north exit to the bounded Phase 8 fallback",
    ),
    (
        "tohjo-league-hns",
        "ReceptionGate",
        "warp_events/2/dest_map",
        "MAP_VICTORY_ROAD_KANTO_B2F",
        "MAP_JOHTO_VICTORY_ROAD_1F",
        "mechanical Johto membership defers the north exit to the bounded Phase 8 fallback",
    ),
    (
        "tohjo-league-hns",
        "ReceptionGate",
        "warp_events/4/dest_map",
        "MAP_ROUTE22",
        "MAP_ROUTE26NORTH",
        "mechanical Johto membership keeps the east exit inside the active Tohjo shell",
    ),
    (
        "pkmn-world-fallback",
        "MahoganyTown_Shop",
        "warp_events/1/dest_map",
        "MAP_ROCKET_HIDEOUT_B1F",
        "MAP_MAHOGANY_HIDEOUT_B1F",
        "mechanical fallback identity restores the reverse Mahogany Hideout warp",
    ),
)
REVIEWED_BATCH_INVENTORY = {
    "baseline": (
        "preserve",
        "50ac109f251908580fbfaa6ba3cf3d02b43431a513554f4eb768b5305347f475",
        "561e9888e0e9259b1fe4becc1c9c911ee1b651dfc526e1ca55e22039743d69be",
    ),
    "early-violet-ruins": (
        "residency",
        "d0f956f7e008696f18837051b0b526591c9d9b13faf42811b781582c300c3376",
        "be788f0d25cc76b0467e10437daa0d6867c278fb81c31e4b8b03aee8af4bb6a9",
    ),
    "azalea-union-ilex": (
        "residency",
        "efb41c0b9184b9d9acb23813291ed74be6aaafa5053baffabfbfabca78f6567a",
        "81621ffa2611d7b8cad6801bbf8eb2c278dceb1e29b63b7d32ec24112c54870c",
    ),
    "goldenrod-park": (
        "residency",
        "188c1a26eef2289ee55720fd2e1ce1abecbf8681d7446287c464d209c98cfd11",
        "53549acb69dc2e997ceada4f28d42044652507c7ebe5572b6742acad7eb86cc6",
    ),
    "ecruteak-towers": (
        "residency",
        "8aa12a63b98ae56c90a9f5a95301d53653690f5e08f46e353fb63fc0940c17b6",
        "f05ab024ab18dbbd2accfca35b845a92ced091b87ad6dc7e40f7e4e3c3bb5c74",
    ),
    "olivine-cianwood-whirl": (
        "residency",
        "53e53cc1e6258d0b4fd08afbdb5f41636a5dd6234b43eb41e2fb3c47bc14762a",
        "1f246046b0b5569796d59a1344a25191c5cbc0770ccef8e71d4a89a31b169cba",
    ),
    "mahogany-hns": (
        "residency",
        "b479cb20f5a0e5623e5c3631bac59aeeaef491027b08ea8a027aff39c0ded212",
        "defd16781bdfa30fb505c1bcb3e467d76fa38251f6d8d466cbf8ff4034284791",
    ),
    "blackthorn-ice-dark-den": (
        "residency",
        "ae7af35a2618a5b636b95bc125962a1e730dfa28ba26bf118497350fab7b70d5",
        "14876054194e62fd5d5ca785c27d5b101e55bbf028f5b6ae7a9bf911e4516a2c",
    ),
    "safari": (
        "residency",
        "a854fc2fff0b33cda15ab65855e6f42dcbabe94fd4bc286057cf204a261fd4a1",
        "5f42b60f00ebe851316b52ca90962550d23645cc53f535a1cfb03de44dc0ff52",
    ),
    "mt-silver": (
        "residency",
        "e812cc4163d06b01f475cbc61445a6c454bc913c5461d6bf8fe595db73f0d322",
        "3d915bbf43fb807a66714bda2cd96d9d69e717448ae44504794a37c083b3728c",
    ),
    "aqua-vermilion": (
        "residency",
        "769df76b9e511becd67ec976bc72170f5b738b81acf86ab5d9315bc264a9dfd6",
        "ee2c8bf5a4d95b55e18ce024d619f1c9f8ff97173dcbca46fa2dfc7e95529fc8",
    ),
    "tohjo-league-hns": (
        "residency",
        "2469e0128d53399e3f45d4d84b6d52b63b1fcb9e9b4c7af9967f39e92983189c",
        "b879f778271d56d49475a6deee7824abbfebc15d46f709ef0ddfceef48547d2e",
    ),
    "pkmn-world-fallback": (
        "residency",
        "df4b5fc51c6fbdd65c7d791709f10c9e4ef29b5f4d38adb8a7b9aa8fa6e9bf50",
        "a2d7aaecd003f1590fd63d7c320bbefee314b3d14f003c0aff45b527310bbdad",
    ),
}
BASELINE_GROUP_IDS = {
    "gMapGroup_JohtoTownsAndRoutes": 75,
    "gMapGroup_IndoorNewBark": 76,
    "gMapGroup_IndoorCherrygrove": 77,
    "gMapGroup_IndoorBlackthorn": 78,
    "gMapGroup_MtSilver": 79,
}
BASELINE_SECTION_IDS = {
    "MAPSEC_NEW_BARK_TOWN": 209,
    "MAPSEC_ROUTE_29": 210,
    "MAPSEC_CHERRYGROVE_CITY": 211,
    "MAPSEC_ROUTE_28": 212,
    "MAPSEC_MT_SILVER": 213,
}


class ImportError(ValueError):
    """The donor evidence or reviewed manifest violates the import contract."""


@dataclass(frozen=True)
class DonorPin:
    name: str
    commit: str
    source_tree_digest: str
    source_tree_file_count: int


@dataclass(frozen=True)
class Closure:
    maps: tuple[str, ...]
    layouts: tuple[str, ...]
    groups: tuple[str, ...]
    sections: tuple[str, ...]
    tilesets: tuple[str, ...]
    symbols: tuple[str, ...]
    deferred_edges: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class Inventory:
    maps: tuple[str, ...]
    layouts: tuple[str, ...]
    groups: tuple[str, ...]
    sections: tuple[str, ...]
    tilesets: tuple[str, ...]


@dataclass(frozen=True)
class AuthorityRules:
    hns_content: tuple[str, ...]
    mechanical_adaptations: tuple[str, ...]

    def is_hns_content(self, path: str) -> bool:
        return any(
            path == item or path.startswith(item + "/") for item in self.hns_content
        )

    def is_mechanical_adaptation(self, path: str) -> bool:
        return path in self.mechanical_adaptations


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ImportError(f"cannot read JSON {path}: {error}") from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ImportError(f"cannot hash donor input {path}: {error}") from error
    return digest.hexdigest()


def source_tree_records(root: Path) -> list[dict[str, Any]]:
    """Return the same stable source evidence used by the capacity measurement."""
    if not root.is_dir():
        raise ImportError(f"donor directory does not exist: {root}")
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if (
            not path.is_file()
            or relative.parts[0] in {".git", "build", "test-results"}
            or path.name in GENERATED_ARTIFACTS
        ):
            continue
        records.append(
            {
                "path": relative.as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    if not records:
        raise ImportError(f"donor source tree contains no evidence files: {root}")
    return records


def records_digest(records: Iterable[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(
            f"{record['path']}\0{record['bytes']}\0{record['sha256']}\n".encode("utf-8")
        )
    return digest.hexdigest()


def inventory_digest(values: Sequence[str]) -> str:
    encoded = (
        json.dumps(sorted(values), ensure_ascii=True, separators=(",", ":")) + "\n"
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def ordered_inventory_digest(values: Sequence[str]) -> str:
    encoded = json.dumps(values, ensure_ascii=True, separators=(",", ":")) + "\n"
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def materialize_resident_map(source: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(source)
    for key in GAMEPLAY_EVENT_KEYS:
        value[key] = []
    return value


def resident_map_script(name: str) -> str:
    return f"{name}_MapScripts::\n\t.byte 0\n"


def should_materialize(item: Mapping[str, Any]) -> bool:
    return item["materialization"] == "residency"


def materialized_tree_record(
    root: Path,
    selection: Sequence[Mapping[str, Any]],
    layouts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    relative_paths = {
        relative
        for item in selection
        for relative in (
            f"data/maps/{item['name']}/map.json",
            f"data/maps/{item['name']}/scripts.inc",
        )
    }
    if layouts:
        registry = {
            item["id"]: item
            for item in _json(root / "data/layouts/layouts.json")["layouts"]
        }
        relative_paths.update(
            str(registry[item["id"]][key])
            for item in layouts
            for key in ("blockdata_filepath", "border_filepath")
        )
    for relative in sorted(relative_paths):
        path = root / relative
        if path.is_file():
            records.append(
                {
                    "path": relative,
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    return {"fileCount": len(records), "digest": records_digest(records)}


def authenticate_donor(root: Path, pin: DonorPin) -> list[dict[str, Any]]:
    if not COMMIT_RE.fullmatch(pin.commit):
        raise ImportError(f"malformed pin for {pin.name}: expected a 40-hex commit")
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    actual = result.stdout.strip()
    if result.returncode == 0 and COMMIT_RE.fullmatch(actual) and actual != pin.commit:
        raise ImportError(
            f"{pin.name} checkout commit {actual} does not match pin {pin.commit}"
        )
    records = source_tree_records(root)
    actual_digest = records_digest(records)
    if actual_digest != pin.source_tree_digest:
        raise ImportError(
            f"{pin.name} source-tree digest mismatch: expected {pin.source_tree_digest}, "
            f"got {actual_digest}"
        )
    if len(records) != pin.source_tree_file_count:
        raise ImportError(
            f"{pin.name} source-tree file count drift: expected {pin.source_tree_file_count}, "
            f"got {len(records)}"
        )
    return records


def attribute_format(metatile_bytes: int, attribute_bytes: int) -> str:
    count, remainder = divmod(metatile_bytes, 16)
    if remainder or not count:
        raise ImportError("metatile blob is not an integral metatile set")
    if attribute_bytes == count * 2:
        return "METATILE_ATTRIBUTES_EMERALD_U16"
    if attribute_bytes == count * 4:
        return "METATILE_ATTRIBUTES_FRLG_U32"
    raise ImportError("attribute blob width does not match metatile count")


def authoritative_value(
    path: str, hns: object, mechanical: object, rules: AuthorityRules
) -> object:
    # Exact reviewed adaptations override their broader HnS-owned content class.
    if rules.is_mechanical_adaptation(path):
        return mechanical
    if rules.is_hns_content(path):
        return hns
    if hns != mechanical:
        raise ImportError(f"unclassified donor divergence: {path}")
    return hns


def _require_unique(items: Sequence[Mapping[str, Any]], key: str, label: str) -> None:
    values = [item.get(key) for item in items]
    if any(not isinstance(value, str) or not value for value in values):
        raise ImportError(f"{label} has a missing {key}")
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ImportError(f"duplicate {label} {key}: {', '.join(duplicates)}")


def discover_inventory(
    root: Path,
) -> tuple[Inventory, dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    layout_doc = _json(root / "data/layouts/layouts.json")
    layouts = layout_doc.get("layouts") if isinstance(layout_doc, dict) else None
    if not isinstance(layouts, list):
        raise ImportError("layout registry has no layouts array")
    johto_layouts = [item for item in layouts if item.get("layout_version") == "johto"]
    _require_unique(johto_layouts, "id", "Johto layout")
    layout_by_id = {item["id"]: item for item in johto_layouts}

    maps: list[dict[str, Any]] = []
    for path in sorted((root / "data/maps").glob("*/map.json")):
        item = _json(path)
        if item.get("layout") in layout_by_id:
            item["__path"] = path.relative_to(root).as_posix()
            maps.append(item)
    _require_unique(maps, "name", "Johto map")
    _require_unique(maps, "id", "Johto map")
    map_by_name = {item["name"]: item for item in maps}

    group_doc = _json(root / "data/maps/map_groups.json")
    order = group_doc.get("group_order") if isinstance(group_doc, dict) else None
    if not isinstance(order, list):
        raise ImportError("map group registry has no group_order")
    try:
        first = order.index("gMapGroup_JohtoTownsAndRoutes")
        boundary = order.index("gMapGroup_RegionHub", first)
    except ValueError as error:
        raise ImportError(
            "cannot locate the donor Johto group-slot boundary"
        ) from error
    groups = order[first:boundary]
    if any(not isinstance(group_doc.get(group), list) for group in groups):
        raise ImportError("a Johto group slot has no member array")

    inventory = Inventory(
        maps=tuple(sorted(map_by_name)),
        layouts=tuple(sorted(layout_by_id)),
        groups=tuple(sorted(groups)),
        sections=tuple(sorted({item["region_map_section"] for item in maps})),
        tilesets=tuple(
            sorted(
                {
                    item[key]
                    for item in johto_layouts
                    for key in ("primary_tileset", "secondary_tileset")
                }
            )
        ),
    )
    return inventory, map_by_name, layout_by_id


def validate_expected_inventory(
    inventory: Inventory, expected: Mapping[str, Any]
) -> None:
    for field in ("maps", "layouts", "groups", "sections", "tilesets"):
        values = getattr(inventory, field)
        record = expected.get(field)
        if not isinstance(record, dict):
            raise ImportError(f"manifest has no expected {field} inventory")
        if record.get("count") != len(values):
            raise ImportError(
                f"{field} count drift: expected {record.get('count')}, got {len(values)}"
            )
        actual_digest = inventory_digest(values)
        if record.get("digest") != actual_digest:
            raise ImportError(f"{field} inventory digest drift")


def _edge_records(map_item: Mapping[str, Any]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for index, edge in enumerate(map_item.get("connections") or []):
        records.append(
            {
                "source": str(map_item["name"]),
                "path": f"connections/{index}",
                "kind": "connection",
                "destination": str(edge["map"]),
            }
        )
    for index, edge in enumerate(map_item.get("warp_events") or []):
        records.append(
            {
                "source": str(map_item["name"]),
                "path": f"warp_events/{index}",
                "kind": "warp",
                "destination": str(edge["dest_map"]),
            }
        )
    return records


def _edge_key(item: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return tuple(str(item[key]) for key in ("source", "path", "kind", "destination"))


def validate_edges(
    selected_maps: Sequence[Mapping[str, Any]],
    retained: Sequence[Mapping[str, Any]],
    deferred: Sequence[Mapping[str, Any]],
) -> tuple[tuple[str, str, str], ...]:
    selected_ids = {str(item["id"]) for item in selected_maps}
    actual_retained: set[tuple[str, str, str, str]] = set()
    actual_deferred: set[tuple[str, str, str, str]] = set()
    for map_item in selected_maps:
        for edge in _edge_records(map_item):
            target = (
                actual_retained
                if edge["destination"] in selected_ids
                else actual_deferred
            )
            target.add(_edge_key(edge))
    reviewed_retained = {_edge_key(item) for item in retained}
    reviewed_deferred = {_edge_key(item) for item in deferred}
    if len(reviewed_retained) != len(retained) or len(reviewed_deferred) != len(
        deferred
    ):
        raise ImportError("duplicate reviewed edge")
    unexpected = sorted(actual_deferred - reviewed_deferred)
    if unexpected:
        source, path, kind, destination = unexpected[0]
        raise ImportError(
            f"undeclared outbound edge: {source} {path} ({kind}) -> {destination}"
        )
    stale = sorted(reviewed_deferred - actual_deferred)
    if stale:
        raise ImportError(f"stale deferred edge: {stale[0]}")
    if actual_retained != reviewed_retained:
        missing = sorted(actual_retained - reviewed_retained)
        extra = sorted(reviewed_retained - actual_retained)
        raise ImportError(
            f"retained edge manifest drift: missing={missing[:1]} extra={extra[:1]}"
        )
    return tuple(
        sorted(
            (source, kind, destination)
            for source, _path, kind, destination in actual_deferred
        )
    )


def validate_warp_transforms(
    manifest: Mapping[str, Any], selected_maps: Sequence[Mapping[str, Any]]
) -> None:
    """Validate every deferred-warp removal and resulting incoming-ID rewrite."""
    removals = manifest.get("warpRemovals")
    reindexes = manifest.get("warpReindexes")
    if not isinstance(removals, list) or not isinstance(reindexes, list):
        raise ImportError("warp removal/reindex manifest is malformed")

    maps = {str(item["name"]): item for item in selected_maps}
    deferred_warps = {
        (str(edge["source"]), str(edge["path"]), str(edge["destination"]))
        for edge in manifest.get("deferredEdges", [])
        if edge.get("kind") == "warp"
    }
    reviewed_removals: set[tuple[str, str, str]] = set()
    removed_indices: dict[str, list[int]] = {}
    for rule in removals:
        source = str(rule.get("source"))
        path = str(rule.get("path"))
        destination = str(rule.get("destination"))
        match = re.fullmatch(r"warp_events/(\d+)", path)
        if source not in maps or match is None:
            raise ImportError("warp removal names an unknown selected map or path")
        edge = _pointer(maps[source], path)
        if (
            not isinstance(edge, dict)
            or edge.get("dest_map") != destination
            or edge.get("dest_warp_id") != rule.get("destWarpId")
        ):
            raise ImportError(f"warp removal drift: {source}/{path}")
        key = (source, path, destination)
        if key in reviewed_removals:
            raise ImportError("duplicate warp removal")
        reviewed_removals.add(key)
        removed_indices.setdefault(str(maps[source]["id"]), []).append(
            int(match.group(1))
        )
    if reviewed_removals != deferred_warps:
        missing = sorted(deferred_warps - reviewed_removals)
        extra = sorted(reviewed_removals - deferred_warps)
        raise ImportError(
            f"warp removal manifest drift: missing={missing[:1]} extra={extra[:1]}"
        )

    required_reindexes: set[tuple[str, str, str, str, str]] = set()
    for source, map_item in maps.items():
        for index, edge in enumerate(map_item.get("warp_events") or []):
            destination = str(edge.get("dest_map"))
            if destination not in removed_indices:
                continue
            old_id = str(edge.get("dest_warp_id"))
            try:
                old_index = int(old_id)
            except ValueError as error:
                raise ImportError(
                    f"non-numeric incoming warp id: {source}/warp_events/{index}"
                ) from error
            shift = sum(item < old_index for item in removed_indices[destination])
            if shift:
                required_reindexes.add(
                    (
                        source,
                        f"warp_events/{index}/dest_warp_id",
                        str(map_item["warp_events"][index]["dest_map"]),
                        old_id,
                        str(old_index - shift),
                    )
                )

    reviewed_reindexes: set[tuple[str, str, str, str, str]] = set()
    for rule in reindexes:
        source = str(rule.get("source"))
        path = str(rule.get("path"))
        destination = str(rule.get("destination"))
        old_id = str(rule.get("from"))
        new_id = str(rule.get("to"))
        if source not in maps or not re.fullmatch(
            r"warp_events/\d+/dest_warp_id", path
        ):
            raise ImportError("warp reindex names an unknown selected map or path")
        if _pointer(maps[source], path) != old_id:
            raise ImportError(f"warp reindex drift: {source}/{path}")
        edge_path = path.rsplit("/", 1)[0]
        if _pointer(maps[source], f"{edge_path}/dest_map") != destination:
            raise ImportError(f"warp reindex destination drift: {source}/{path}")
        key = (source, path, destination, old_id, new_id)
        if key in reviewed_reindexes:
            raise ImportError("duplicate warp reindex")
        reviewed_reindexes.add(key)
    if reviewed_reindexes != required_reindexes:
        missing = sorted(required_reindexes - reviewed_reindexes)
        extra = sorted(reviewed_reindexes - required_reindexes)
        raise ImportError(
            f"warp reindex manifest drift: missing={missing[:1]} extra={extra[:1]}"
        )


def validate_destination_warp_bounds(
    maps: Sequence[Mapping[str, Any]],
    *,
    involved_map_ids: set[str] | None = None,
) -> None:
    """Require numeric retained warp IDs to index an emitted destination warp."""
    maps_by_id = {str(item["id"]): item for item in maps}
    for source in maps:
        source_id = str(source["id"])
        source_name = str(source["name"])
        for index, edge in enumerate(source.get("warp_events") or []):
            destination_id = str(edge.get("dest_map"))
            destination = maps_by_id.get(destination_id)
            if destination is None or (
                involved_map_ids is not None
                and source_id not in involved_map_ids
                and destination_id not in involved_map_ids
            ):
                continue
            warp_id = str(edge.get("dest_warp_id"))
            try:
                destination_index = int(warp_id)
            except ValueError:
                continue
            destination_warps = destination.get("warp_events") or []
            if destination_index < 0 or destination_index >= len(destination_warps):
                raise ImportError(
                    "destination warp out of bounds: "
                    f"{source_name}/warp_events/{index} -> {destination_id}/"
                    f"warp_events/{warp_id} (count={len(destination_warps)})"
                )


def _pointer(value: Any, path: str) -> Any:
    current = value
    for part in path.split("/"):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as error:
                raise ImportError(f"invalid adaptation path {path}") from error
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise ImportError(f"invalid adaptation path {path}")
    return current


def _set_pointer(value: Any, path: str, replacement: Any) -> None:
    parts = path.split("/")
    if not parts:
        raise ImportError(f"invalid adaptation path {path}")
    parent = value
    for part in parts[:-1]:
        if isinstance(parent, list):
            try:
                parent = parent[int(part)]
            except (ValueError, IndexError) as error:
                raise ImportError(f"invalid adaptation path {path}") from error
        elif isinstance(parent, dict) and part in parent:
            parent = parent[part]
        else:
            raise ImportError(f"invalid adaptation path {path}")
    final = parts[-1]
    if isinstance(parent, list):
        try:
            parent[int(final)] = replacement
        except (ValueError, IndexError) as error:
            raise ImportError(f"invalid adaptation path {path}") from error
    elif isinstance(parent, dict) and final in parent:
        parent[final] = replacement
    else:
        raise ImportError(f"invalid adaptation path {path}")


def validate_adaptations(
    manifest: Mapping[str, Any],
    mechanical_maps: Mapping[str, Mapping[str, Any]],
    hns_root: Path,
    selected_names: set[str] | None = None,
) -> AuthorityRules:
    authority = manifest.get("authority", {})
    hns_categories = authority.get("hnsContent", [])
    adaptations = manifest.get("adaptations", [])
    if not isinstance(hns_categories, list) or not isinstance(adaptations, list):
        raise ImportError("authority or adaptation manifest is malformed")
    active_batches = manifest.get("activeBatches", [])
    if not isinstance(active_batches, list):
        raise ImportError("active batch selection is malformed")
    canonical = {
        (source, path): {
            "source": source,
            "path": path,
            "hns": hns,
            "mechanical": mechanical,
            "reason": reason,
        }
        for activation_batch, source, path, hns, mechanical, reason in REVIEWED_AUTHORITY_ADAPTATIONS
        if activation_batch in active_batches
    }
    all_canonical = {
        (source, path): activation_batch
        for activation_batch, source, path, _hns, _mechanical, _reason in REVIEWED_AUTHORITY_ADAPTATIONS
    }
    exact_paths: list[str] = []
    declared: set[tuple[str, str]] = set()
    for rule in adaptations:
        if not isinstance(rule, Mapping):
            raise ImportError("authority adaptation declaration is malformed")
        source = rule.get("source")
        path = rule.get("path")
        if not isinstance(source, str) or not isinstance(path, str):
            raise ImportError("authority adaptation source or path is malformed")
        key = (source, path)
        if key in declared:
            raise ImportError(f"duplicate adaptation path: {source}/{path}")
        declared.add(key)
        if source not in mechanical_maps or (
            selected_names is not None and source not in selected_names
        ):
            raise ImportError(
                f"adaptation targets an unknown or unselected map: {source}/{path}"
            )
        if key not in canonical:
            if key in all_canonical:
                raise ImportError(
                    f"adaptation targets inactive batch {all_canonical[key]}: "
                    f"{source}/{path}"
                )
            raise ImportError(f"unexpected authority adaptation: {source}/{path}")
        expected = canonical[key]
        if dict(rule) != expected:
            raise ImportError(
                f"authority adaptation declaration drift: {source}/{path}"
            )
        expected_hns, expected_mechanical = expected["hns"], expected["mechanical"]
        hns = _json(hns_root / "data/maps" / source / "map.json")
        actual_hns = _pointer(hns, path)
        actual_mechanical = _pointer(mechanical_maps[source], path)
        if actual_hns != expected_hns or actual_mechanical != expected_mechanical:
            raise ImportError(
                f"adaptation donor drift: {source}/{path}; "
                f"expected hns={expected_hns!r} mechanical={expected_mechanical!r}, "
                f"got hns={actual_hns!r} mechanical={actual_mechanical!r}"
            )
        exact_paths.append(f"maps/{source}/{path}")
    missing = sorted(set(canonical) - declared)
    if missing:
        source, path = missing[0]
        raise ImportError(f"missing required authority adaptation: {source}/{path}")
    return AuthorityRules(
        tuple(str(item) for item in hns_categories), tuple(exact_paths)
    )


def effective_selected_maps(
    selection: Sequence[Mapping[str, Any]],
    mechanical_maps: Mapping[str, Mapping[str, Any]],
    hns_root: Path,
    adaptations: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build the authoritative HnS map view with only exact mechanical overlays."""
    effective: dict[str, dict[str, Any]] = {}
    fallback = (
        set(manifest.get("contentFallback", {}).get("maps", [])) if manifest else set()
    )
    for declared in selection:
        name = str(declared["name"])
        data = (
            copy.deepcopy(mechanical_maps[name])
            if name in fallback
            else _json(hns_root / "data/maps" / name / "map.json")
        )
        if not isinstance(data, dict):
            raise ImportError(f"content-authority map is not an object: {name}")
        effective[name] = copy.deepcopy(data)
    if manifest:
        for rule in manifest.get("mapFieldDecisions", []):
            source = str(rule["map"])
            if source in effective:
                effective[source][str(rule["field"])] = mechanical_maps[source][
                    str(rule["field"])
                ]
    for rule in adaptations:
        source = str(rule["source"])
        if source not in effective:
            raise ImportError("adaptation names an unknown selected map or path")
        path = str(rule["path"])
        mechanical = _pointer(mechanical_maps[source], path)
        if mechanical != rule.get("mechanical"):
            raise ImportError(f"adaptation drift: {source}/{path}")
        _set_pointer(effective[source], path, mechanical)
    return [effective[str(item["name"])] for item in selection]


def _find_layout(layouts_path: Path, layout_id: str) -> Mapping[str, Any]:
    layouts = _json(layouts_path).get("layouts", [])
    found = [item for item in layouts if item.get("id") == layout_id]
    if len(found) != 1:
        raise ImportError(f"content authority does not contain exactly one {layout_id}")
    return found[0]


def validate_content_authority(
    selection: Sequence[Mapping[str, Any]],
    selected_layouts: Sequence[Mapping[str, Any]],
    mechanical_maps: Mapping[str, Mapping[str, Any]],
    mechanical_layouts: Mapping[str, Mapping[str, Any]],
    pkmn_world: Path,
    hns: Path,
    manifest: Mapping[str, Any],
) -> None:
    fallback = set(manifest["contentFallback"]["maps"])
    decisions = {
        (str(rule["layout"]), str(rule["field"])): rule
        for rule in manifest["layoutHeaderDecisions"]
    }
    fallback_layouts = {
        str(item["layout"]) for item in selection if str(item["name"]) in fallback
    }
    for item in selection:
        name, layout_id = item["name"], item["layout"]
        authority = pkmn_world if name in fallback else hns
        source_map = _json(authority / "data/maps" / name / "map.json")
        if (
            source_map.get("name") != name
            or source_map.get("id") != item["id"]
            or source_map.get("layout") != layout_id
        ):
            raise ImportError(f"content identity drift for {name}")
    for item in selected_layouts:
        layout_id = str(item["id"])
        authority = pkmn_world if layout_id in fallback_layouts else hns
        source_layout = _find_layout(authority / "data/layouts/layouts.json", layout_id)
        mechanical = mechanical_layouts[layout_id]
        for key in (
            "id",
            "name",
            "width",
            "height",
            "primary_tileset",
            "secondary_tileset",
        ):
            if source_layout.get(key) != mechanical.get(key) and (
                layout_id in fallback_layouts or (layout_id, key) not in decisions
            ):
                raise ImportError(
                    f"unclassified donor divergence: layouts/{layout_id}/{key}"
                )
        for key in ("border_filepath", "blockdata_filepath"):
            path = authority / str(source_layout[key])
            if not path.is_file():
                raise ImportError(
                    f"missing content layout binary: {source_layout[key]}"
                )


def validate_attribute_fixtures(
    pkmn_world: Path, hns: Path, manifest: Mapping[str, Any]
) -> dict[str, dict[str, str]]:
    """Classify representative layout roles and verify their exact blob widths."""
    fixtures = manifest.get("attributeFixtures", [])
    keys = [
        (
            item.get("representative"),
            item.get("layout"),
            item.get("role"),
            item.get("authority"),
        )
        for item in fixtures
        if isinstance(item, dict)
    ]
    if keys != list(ATTRIBUTE_FIXTURE_KEYS):
        raise ImportError("attribute fixture classification drift")

    roots = {"mechanical": pkmn_world, "hns": hns}
    declared_by_authority: dict[str, dict[tuple[str, str], str]] = {}
    results: dict[str, dict[str, str]] = {}
    for item in fixtures:
        representative = str(item["representative"])
        layout_id = str(item["layout"])
        role = str(item["role"])
        authority = str(item["authority"])
        root = roots[authority]
        layout = _find_layout(root / "data/layouts/layouts.json", layout_id)
        expected_tileset = layout.get(f"{role}_tileset")
        if item.get("tileset") != expected_tileset:
            raise ImportError(
                f"attribute fixture role drift: {representative}/{layout_id}/{role}"
            )

        if authority not in declared_by_authority:
            header_path = root / "src/data/tilesets/metatiles.h"
            try:
                header = header_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                raise ImportError(
                    f"cannot read tileset declarations {header_path}: {error}"
                ) from error
            declared_by_authority[authority] = {
                (match.group("kind"), f"gTileset_{match.group('name')}"): match.group(
                    "path"
                )
                for match in TILESET_BLOB_RE.finditer(header)
            }
        declared_paths = declared_by_authority[authority]
        expected_metatiles = declared_paths.get(("Metatiles", expected_tileset))
        expected_attributes = declared_paths.get(
            ("MetatileAttributes", expected_tileset)
        )
        if (
            item.get("metatiles") != expected_metatiles
            or item.get("attributes") != expected_attributes
        ):
            raise ImportError(
                f"attribute fixture path drift: {representative}/{expected_tileset}"
            )
        metatiles = root / str(item["metatiles"])
        attributes = root / str(item["attributes"])
        if _sha256(metatiles) != item.get("metatilesSha256") or _sha256(
            attributes
        ) != item.get("attributesSha256"):
            raise ImportError(f"attribute fixture hash drift: {representative}")
        actual = attribute_format(metatiles.stat().st_size, attributes.stat().st_size)
        if actual != item.get("format"):
            raise ImportError(
                f"wrong attribute width for {expected_tileset}: "
                f"expected {item.get('format')}, got {actual}"
            )
        results[representative] = {
            "layout": layout_id,
            "role": role,
            "tileset": str(expected_tileset),
            "format": actual,
        }
    return results


def referenced_symbols(
    root: Path, selected: Sequence[Mapping[str, Any]]
) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    pending: list[Path] = []
    definitions: set[str] = set()
    records: dict[str, dict[str, Any]] = {}
    for item in selected:
        map_path = root / "data/maps" / item["name"] / "map.json"
        pending.append(map_path)
        for sibling in (
            map_path.with_name("scripts.inc"),
            map_path.with_name("text.inc"),
        ):
            if sibling.is_file():
                pending.append(sibling)
    seen: set[Path] = set()
    while pending:
        path = pending.pop()
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root.resolve())
        except (OSError, ValueError) as error:
            raise ImportError(
                f"missing or escaping referenced input: {path}"
            ) from error
        if resolved in seen:
            continue
        seen.add(resolved)
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() != ".json":
            definitions.update(LABEL_RE.findall(text))
        relative = path.relative_to(root).as_posix()
        records[relative] = {
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for include in INCLUDE_RE.findall(text):
            included = root / include
            if not included.is_file():
                raise ImportError(f"missing recursively referenced input: {include}")
            pending.append(included)
    return tuple(sorted(definitions)), [records[key] for key in sorted(records)]


def validate_map_local_symbols(
    root: Path, selected: Sequence[Mapping[str, Any]], definitions: Sequence[str]
) -> None:
    """Fail when a selected-map-local script target is absent from the recursive closure."""
    available = set(definitions)
    prefixes = tuple(f"{item['name']}_" for item in selected)
    required: set[str] = set()
    for item in selected:
        data = _json(root / "data/maps" / item["name"] / "map.json")
        for event_key in ("object_events", "coord_events", "bg_events"):
            for event in data.get(event_key) or []:
                script = event.get("script")
                if isinstance(script, str) and script.startswith(prefixes):
                    required.add(script)
    missing = sorted(required - available)
    if missing:
        raise ImportError(f"missing symbols in selected closure: {', '.join(missing)}")


def _validate_allocations(
    selection: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    layouts: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    groups = manifest.get("groupAllocations", [])
    sections = manifest.get("sectionAllocations", [])
    if not isinstance(groups, list) or not isinstance(sections, list):
        raise ImportError("allocation registries must be arrays")
    for label, records in (("group", groups), ("section", sections)):
        for key in ("name", "targetId"):
            values = [item.get(key) for item in records]
            if len(values) != len(set(values)):
                raise ImportError(f"duplicate allocation: {label} {key}")
    layout_indices = [
        item.get("targetIndex" if layouts is not None else "targetLayoutIndex")
        for item in (layouts if layouts is not None else selection)
    ]
    if len(layout_indices) != len(set(layout_indices)):
        raise ImportError("duplicate allocation: targetLayoutIndex")
    for label, values in (
        ("layout", layout_indices),
        ("section", [item.get("targetId") for item in sections]),
    ):
        if not values or any(not isinstance(value, int) for value in values):
            raise ImportError(f"{label} allocations must be integers")
        if sorted(values) != list(range(min(values), min(values) + len(values))):
            raise ImportError(f"{label} allocations must be append-only and contiguous")
    group_ids = [item.get("targetId") for item in groups]
    if not group_ids or any(not isinstance(value, int) for value in group_ids):
        raise ImportError("group allocations must be integers")
    group_names = {str(item["name"]) for item in groups}
    selected_groups = {str(item.get("targetGroup")) for item in selection}
    unknown_groups = sorted(selected_groups - group_names)
    if unknown_groups:
        raise ImportError(
            f"selected map uses unallocated targetGroup: {', '.join(unknown_groups)}"
        )
    placeholder_names = {
        str(item["name"]) for item in _inactive_group_placeholders(manifest)
    }
    if group_names - selected_groups != placeholder_names - selected_groups:
        raise ImportError("group allocation has no selected map")
    section_ids = {str(item["name"]): item["targetId"] for item in sections}
    for item in selection:
        section = str(item.get("section"))
        if section not in section_ids:
            raise ImportError(f"selected map uses unallocated section: {section}")
        if item.get("targetSection") != section_ids[section]:
            raise ImportError(
                f"section allocation mismatch: {section} must map to {section_ids[section]}"
            )


def _validate_allocation_lock(lock: Mapping[str, Any]) -> None:
    groups = lock.get("groups", [])
    sections = lock.get("sections", [])
    layouts = lock.get("layouts", [])
    locked_maps = lock.get("maps", [])
    if (
        len(locked_maps) != 254
        or len(layouts) != 255
        or len(groups) != 25
        or len(sections) != 58
    ):
        raise ImportError("allocation-lock cardinality drift")
    for label, records, key, expected in (
        ("group", groups, "targetId", range(75, 100)),
        ("layout", layouts, "targetIndex", range(785, 1040)),
        ("section", sections, "targetId", range(209, 267)),
    ):
        values = [item.get(key) for item in records]
        if sorted(values) != list(expected) or len(values) != len(set(values)):
            raise ImportError(f"{label} allocation-lock drift")
    layout_ids = [item.get("id") for item in layouts]
    if any(not isinstance(value, str) or not value for value in layout_ids) or len(
        layout_ids
    ) != len(set(layout_ids)):
        raise ImportError("layout allocation-lock ID drift")
    group_ids = {item.get("name"): item.get("targetId") for item in groups}
    members: dict[str, list[int]] = {}
    for item in locked_maps:
        group = item.get("targetGroup")
        member = item.get("targetMember")
        if (
            not isinstance(group, str)
            or not isinstance(member, int)
            or item.get("targetGroupId") != group_ids.get(group)
        ):
            raise ImportError("map allocation-lock member drift")
        members.setdefault(group, []).append(member)
    for group, values in members.items():
        if sorted(values) != list(range(len(values))) or len(values) != len(
            set(values)
        ):
            raise ImportError(f"map allocation-lock member drift: {group}")
    if any(
        not isinstance(item["targetId"], int) or not 0 <= item["targetId"] <= 0xFFFE
        for item in sections
    ):
        raise ImportError("section allocation exceeds MapSectionId")


def _validate_locked_layout_inventory(
    lock: Mapping[str, Any], discovered_layouts: Sequence[str]
) -> None:
    locked_layout_ids = [item.get("id") for item in lock.get("layouts", [])]
    if set(locked_layout_ids) != set(discovered_layouts) or len(
        locked_layout_ids
    ) != len(discovered_layouts):
        raise ImportError("allocation lock layouts do not partition the full inventory")


def active_selection(
    manifest: Mapping[str, Any], lock: Mapping[str, Any]
) -> list[dict[str, Any]]:
    active = manifest.get("activeBatches")
    if (
        not isinstance(active, list)
        or len(active) != len(set(active))
        or any(name not in BATCH_ORDER for name in active)
        or active != list(BATCH_ORDER[: len(active)])
    ):
        raise ImportError("active batch selection drift")
    selected = [
        copy.deepcopy(item)
        for item in lock.get("maps", [])
        if item.get("batch") in active
    ]
    return sorted(selected, key=lambda item: item["targetLayoutIndex"])


def active_layout_selection(
    manifest: Mapping[str, Any], lock: Mapping[str, Any]
) -> list[dict[str, Any]]:
    active = set(manifest["activeBatches"])
    batch_by_layout = {
        layout_id: (batch["name"], batch["materialization"])
        for batch in manifest["batches"]
        for layout_id in batch["layouts"]
    }
    selected: list[dict[str, Any]] = []
    for record in lock.get("layouts", []):
        batch, materialization = batch_by_layout[record["id"]]
        if batch in active:
            selected.append(
                copy.deepcopy(record)
                | {"batch": batch, "materialization": materialization}
            )
    return sorted(selected, key=lambda item: item["targetIndex"])


def validate_authority_decisions(
    manifest: Mapping[str, Any],
    mechanical_maps: Mapping[str, Mapping[str, Any]],
    mechanical_layouts: Mapping[str, Mapping[str, Any]],
    pkmn_world: Path,
    hns: Path,
) -> None:
    fallback = manifest.get("contentFallback")
    if fallback != {
        "authority": "PKMN-World",
        "reason": "absent from pinned HnS content authority",
        "maps": list(FALLBACK_MAPS),
    }:
        raise ImportError("content fallback allowlist drift")
    for name in FALLBACK_MAPS:
        hns_path = hns / "data/maps" / name / "map.json"
        mechanical_path = pkmn_world / "data/maps" / name / "map.json"
        if hns_path.exists() or not mechanical_path.is_file():
            raise ImportError(f"content fallback authority drift: {name}")

    layout_decisions = manifest.get("layoutHeaderDecisions")
    if not isinstance(layout_decisions, list) or [
        (item.get("layout"), item.get("field")) for item in layout_decisions
    ] != list(LAYOUT_HEADER_DECISION_KEYS):
        raise ImportError("layout-header decision drift")
    hns_layouts = {
        item["id"]: item for item in _json(hns / "data/layouts/layouts.json")["layouts"]
    }
    for rule in layout_decisions:
        layout, field = str(rule["layout"]), str(rule["field"])
        if (
            rule.get("authority") != "mechanical"
            or hns_layouts[layout].get(field) != rule.get("hns")
            or mechanical_layouts[layout].get(field) != rule.get("mechanical")
            or rule.get("hns") == rule.get("mechanical")
        ):
            raise ImportError(f"layout-header decision drift: {layout}/{field}")

    map_decisions = manifest.get("mapFieldDecisions")
    if not isinstance(map_decisions, list) or [
        (item.get("map"), item.get("field")) for item in map_decisions
    ] != list(MAP_FIELD_DECISION_KEYS):
        raise ImportError("map-field decision drift")
    for rule in map_decisions:
        name, field = str(rule["map"]), str(rule["field"])
        hns_map = _json(hns / "data/maps" / name / "map.json")
        if (
            rule.get("authority") != "mechanical"
            or hns_map.get(field) != rule.get("hns")
            or mechanical_maps[name].get(field) != rule.get("mechanical")
            or rule.get("hns") == rule.get("mechanical")
        ):
            raise ImportError(f"map-field decision drift: {name}/{field}")


def validate_full_port_contract(
    manifest: Mapping[str, Any],
    inventory: Inventory,
    maps: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    actual_counts = tuple(
        len(getattr(inventory, field))
        for field in ("maps", "layouts", "groups", "sections", "tilesets")
    )
    if actual_counts != FINAL_INVENTORY_COUNTS:
        raise ImportError(
            f"final Johto inventory count drift: expected {FINAL_INVENTORY_COUNTS}, "
            f"got {actual_counts}"
        )
    if manifest.get("activeBatches") != list(BATCH_ORDER):
        raise ImportError("final Johto import must activate every canonical batch")
    profile = manifest.get("materializationProfile")
    if profile != {
        "mapScripts": "empty",
        "retainEventKinds": ["warp_events"],
        "stripEventKinds": list(GAMEPLAY_EVENT_KEYS),
        "encounters": False,
        "gameplayGlobals": False,
    }:
        raise ImportError("residency materialization profile drift")
    batches = manifest.get("batches")
    if tuple(REVIEWED_BATCH_INVENTORY) != BATCH_ORDER:
        raise ImportError("canonical batch inventory configuration drift")
    if not isinstance(batches, list) or [item.get("name") for item in batches] != list(
        BATCH_ORDER
    ):
        raise ImportError("batch inventory order drift")
    all_maps: list[str] = []
    all_layouts: list[str] = []
    for batch in batches:
        names, layouts = batch.get("maps"), batch.get("layouts")
        if not isinstance(names, list) or not isinstance(layouts, list):
            raise ImportError("batch inventory is malformed")
        expected_materialization, expected_maps, expected_layouts = (
            REVIEWED_BATCH_INVENTORY[batch["name"]]
        )
        if (
            batch.get("materialization") != expected_materialization
            or ordered_inventory_digest(names) != expected_maps
            or ordered_inventory_digest(layouts) != expected_layouts
        ):
            raise ImportError(f"canonical batch inventory drift: {batch['name']}")
        if batch.get("mapCount") != len(names) or batch.get(
            "mapDigest"
        ) != inventory_digest(names):
            raise ImportError(f"batch map digest drift: {batch['name']}")
        if batch.get("layoutCount") != len(layouts) or batch.get(
            "layoutDigest"
        ) != inventory_digest(layouts):
            raise ImportError(f"batch layout digest drift: {batch['name']}")
        all_maps.extend(names)
        all_layouts.extend(layouts)
    if sorted(all_maps) != list(inventory.maps) or len(all_maps) != len(set(all_maps)):
        raise ImportError("batch maps do not partition the full inventory")
    if sorted(all_layouts) != list(inventory.layouts) or len(all_layouts) != len(
        set(all_layouts)
    ):
        raise ImportError("batch layouts do not partition the full inventory")
    lock_name = manifest.get("allocationLock")
    manifest_path = manifest.get("__manifestPath")
    if not isinstance(lock_name, str) or not isinstance(manifest_path, str):
        raise ImportError("manifest has no allocation lock")
    lock = _json(Path(manifest_path).parent / lock_name)
    _validate_allocation_lock(lock)
    _validate_locked_layout_inventory(lock, inventory.layouts)
    locked_maps = lock.get("maps", [])
    by_name = {item.get("name"): item for item in locked_maps}
    if set(by_name) != set(inventory.maps):
        raise ImportError("allocation lock map inventory drift")
    batch_by_map = {
        name: (batch["name"], batch["materialization"])
        for batch in batches
        for name in batch["maps"]
    }
    layout_indices = {
        item["id"]: item["targetIndex"] for item in lock.get("layouts", [])
    }
    group_ids = {item["name"]: item["targetId"] for item in lock.get("groups", [])}
    section_ids = {item["name"]: item["targetId"] for item in lock.get("sections", [])}
    members: set[tuple[str, int]] = set()
    for name, actual in maps.items():
        item = by_name[name]
        if (item.get("id"), item.get("layout"), item.get("section")) != (
            actual.get("id"),
            actual.get("layout"),
            actual.get("region_map_section"),
        ):
            raise ImportError(f"allocation lock identity drift: {name}")
        if (item.get("batch"), item.get("materialization")) != batch_by_map[name]:
            raise ImportError(f"allocation lock batch drift: {name}")
        if item.get("targetLayoutIndex") != layout_indices[item["layout"]]:
            raise ImportError(f"allocation lock layout drift: {name}")
        if item.get("targetGroupId") != group_ids.get(item.get("targetGroup")):
            raise ImportError(f"allocation lock group drift: {name}")
        if item.get("targetSection") != section_ids.get(item.get("section")):
            raise ImportError(f"allocation lock section drift: {name}")
        member = (item["targetGroup"], item["targetMember"])
        if member in members:
            raise ImportError(f"allocation lock member drift: {name}")
        members.add(member)
    active_selection(manifest, lock)
    active_layout_selection(manifest, lock)
    return lock


def proposal_document(
    manifest: Mapping[str, Any], lock: Mapping[str, Any]
) -> dict[str, Any]:
    return {"schemaVersion": 1, "batches": manifest["batches"], "allocationLock": lock}


def _materialized_group_registry(
    groups: Mapping[str, Any],
    selection: Sequence[Mapping[str, Any]],
    allocations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Place imported groups at the numeric slots declared by targetId."""
    result = copy.deepcopy(dict(groups))
    order = result.get("group_order")
    if not isinstance(order, list):
        raise ImportError("map group registry has no group_order")
    ordered_allocations = sorted(allocations, key=lambda item: item["targetId"])
    allocation_names = [str(item["name"]) for item in ordered_allocations]
    order = [name for name in order if name not in allocation_names]
    first_id = int(ordered_allocations[0]["targetId"])
    if len(order) != first_id:
        raise ImportError(
            f"map group target baseline drift: expected {first_id} groups, got {len(order)}"
        )
    members = {name: [] for name in allocation_names}
    for item in selection:
        members[str(item["targetGroup"])].append(item)
    for allocation in ordered_allocations:
        name = str(allocation["name"])
        target_id = int(allocation["targetId"])
        if len(order) != target_id:
            raise ImportError(
                f"map group allocation drift: {name} cannot occupy ID {target_id}"
            )
        ordered_members = sorted(members[name], key=lambda item: item["targetMember"])
        result[name] = [str(item["name"]) for item in ordered_members]
        order.append(name)
    result["group_order"] = order
    return {"group_order": order} | {name: result[name] for name in order}


def build_closure(
    manifest: Mapping[str, Any], pkmn_world: Path, hns: Path
) -> tuple[Inventory, Closure, dict[str, Any]]:
    mechanical_pin = _pin(manifest, "mechanicalDonor", "PKMN-World")
    content_pin = _pin(manifest, "contentAuthority", "Pokémon Heart & Soul")
    mechanical_records = authenticate_donor(pkmn_world, mechanical_pin)
    content_records = authenticate_donor(hns, content_pin)
    inventory, maps_by_name, layouts_by_id = discover_inventory(pkmn_world)
    validate_expected_inventory(inventory, manifest.get("expectedInventory", {}))
    validate_full_port_contract(manifest, inventory, maps_by_name)
    validate_authority_decisions(manifest, maps_by_name, layouts_by_id, pkmn_world, hns)
    validate_materialization_adaptations(manifest, pkmn_world, hns)

    selection = manifest.get("selection", {}).get("maps", [])
    lock = _json(Path(manifest["__manifestPath"]).parent / manifest["allocationLock"])
    selected_layout_records = active_layout_selection(manifest, lock)
    expected_active = sum(
        batch["mapCount"]
        for batch in manifest["batches"]
        if batch["name"] in manifest["activeBatches"]
    )
    if not isinstance(selection, list) or len(selection) != expected_active:
        raise ImportError(
            f"manifest selection must contain exactly {expected_active} maps"
        )
    _require_unique(selection, "name", "selected map")
    _require_unique(selection, "id", "selected map")
    _validate_allocations(selection, manifest, selected_layout_records)
    selected: list[Mapping[str, Any]] = []
    for declared in selection:
        actual = maps_by_name.get(declared["name"])
        if actual is None:
            raise ImportError(
                f"selected map is not a Johto-layout map: {declared['name']}"
            )
        for key in ("id", "layout", "region_map_section"):
            manifest_key = "section" if key == "region_map_section" else key
            if actual.get(key) != declared.get(manifest_key):
                raise ImportError(
                    f"selected map identity drift: {declared['name']}/{key}"
                )
        selected.append(actual)
    expected_layouts = sum(
        batch["layoutCount"]
        for batch in manifest["batches"]
        if batch["name"] in manifest["activeBatches"]
    )
    if len(selected_layout_records) != expected_layouts:
        raise ImportError(
            f"selected closure must contain exactly {expected_layouts} layouts"
        )

    validate_content_authority(
        selection,
        selected_layout_records,
        maps_by_name,
        layouts_by_id,
        pkmn_world,
        hns,
        manifest,
    )
    selected_names = {str(item["name"]) for item in selection}
    rules = validate_adaptations(manifest, maps_by_name, hns, selected_names)
    # Exercise every exact adaptation through the same authority resolver used by apply.
    for rule in manifest.get("adaptations", []):
        path = f"maps/{rule['source']}/{rule['path']}"
        authoritative_value(path, rule["hns"], rule["mechanical"], rules)
    effective_maps = effective_selected_maps(
        selection,
        maps_by_name,
        hns,
        manifest.get("adaptations", []),
        manifest,
    )
    effective_maps = [
        value if not should_materialize(item) else materialize_resident_map(value)
        for item, value in zip(selection, effective_maps, strict=True)
    ]
    validate_warp_transforms(manifest, effective_maps)
    deferred = validate_edges(
        effective_maps,
        manifest.get("retainedEdges", []),
        manifest.get("deferredEdges", []),
    )
    materialized_maps = [
        _materialized_map(item, pkmn_world, hns, manifest) for item in selection
    ]
    fallback_ids = {
        str(item["id"])
        for item in selection
        if str(item["name"]) in manifest["contentFallback"]["maps"]
    }
    validate_destination_warp_bounds(materialized_maps, involved_map_ids=fallback_ids)
    formats = validate_attribute_fixtures(pkmn_world, hns, manifest)
    preserved = [item for item in selection if not should_materialize(item)]
    definitions, input_records = referenced_symbols(hns, preserved)
    validate_map_local_symbols(hns, preserved, definitions)

    selected_layouts = [layouts_by_id[item["id"]] for item in selected_layout_records]
    group_names = tuple(sorted({item["targetGroup"] for item in selection}))
    sections = tuple(sorted({item["section"] for item in selection}))
    tilesets = tuple(
        sorted(
            {
                layout[key]
                for layout in selected_layouts
                for key in ("primary_tileset", "secondary_tileset")
            }
        )
    )
    closure = Closure(
        maps=tuple(item["name"] for item in selection),
        layouts=tuple(item["id"] for item in selected_layout_records),
        groups=group_names,
        sections=sections,
        tilesets=tilesets,
        symbols=definitions,
        deferred_edges=deferred,
    )
    evidence = {
        "donors": {
            "mechanical": {
                "commit": mechanical_pin.commit,
                "sourceTreeDigest": records_digest(mechanical_records),
                "fileCount": len(mechanical_records),
            },
            "content": {
                "commit": content_pin.commit,
                "sourceTreeDigest": records_digest(content_records),
                "fileCount": len(content_records),
            },
        },
        "attributeFormats": formats,
        "inputs": input_records,
    }
    return inventory, closure, evidence


def _pin(manifest: Mapping[str, Any], key: str, name: str) -> DonorPin:
    item = manifest.get(key, {})
    reviewed = REVIEWED_DONOR_PINS.get(key)
    if reviewed is None or any(
        item.get(field) != value for field, value in reviewed.items()
    ):
        raise ImportError(
            f"manifest {key} pin differs from the immutable reviewed binding"
        )
    try:
        return DonorPin(
            name, item["commit"], item["sourceTreeDigest"], item["sourceTreeFileCount"]
        )
    except (KeyError, TypeError) as error:
        raise ImportError(f"manifest has an incomplete {key} pin") from error


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = _json(path)
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 3:
        raise ImportError("unsupported or malformed import manifest")
    manifest["__manifestPath"] = str(path.resolve())
    lock_name = manifest.get("allocationLock")
    if not isinstance(lock_name, str):
        raise ImportError("manifest has no allocation lock")
    lock = _json(path.parent / lock_name)
    selection = manifest.get("selection")
    if not isinstance(selection, dict) or selection.get("source") != "allocationLock":
        raise ImportError("manifest selection is malformed")
    selection["maps"] = active_selection(manifest, lock)
    selected_groups = {item["targetGroup"] for item in selection["maps"]}
    selected_groups.update(
        str(item["name"]) for item in _inactive_group_placeholders(manifest)
    )
    selected_sections = {item["section"] for item in selection["maps"]}
    manifest["groupAllocations"] = sorted(
        (item for item in lock["groups"] if item["name"] in selected_groups),
        key=lambda item: item["targetId"],
    )
    manifest["sectionAllocations"] = sorted(
        (item for item in lock["sections"] if item["name"] in selected_sections),
        key=lambda item: item["targetId"],
    )
    return manifest


def _exact_records(
    manifest: Mapping[str, Any], key: str, required: set[str]
) -> list[Mapping[str, Any]]:
    records = manifest.get(key)
    if not isinstance(records, list) or not records:
        raise ImportError(f"manifest {key} must be a non-empty array")
    for record in records:
        if not isinstance(record, dict) or not required.issubset(record):
            raise ImportError(f"manifest {key} has an incomplete record")
    return records


def _mapping(manifest: Mapping[str, Any], key: str) -> dict[str, str]:
    records = _exact_records(manifest, key, {"hns", "target"})
    _require_unique(records, "hns", key)
    result: dict[str, str] = {}
    for record in records:
        target = record.get("target")
        if not isinstance(target, str) or not target:
            raise ImportError(f"manifest {key} has an invalid target")
        result[str(record["hns"])] = target
    return result


def _preserve_spatial_updates(
    manifest: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    records = manifest.get("preserveSpatialUpdates")
    if not isinstance(records, list):
        raise ImportError("preserve spatial update allowlist drift")
    actual: list[tuple[str, str, tuple[str, ...]]] = []
    for item in records:
        if not isinstance(item, dict) or not isinstance(item.get("fields"), list):
            raise ImportError("preserve spatial update allowlist drift")
        fields = item["fields"]
        if any(not isinstance(field, str) for field in fields):
            raise ImportError("preserve spatial update allowlist drift")
        actual.append(
            (
                str(item.get("source")),
                str(item.get("activationBatch")),
                tuple(fields),
            )
        )
    if actual != list(PRESERVE_SPATIAL_UPDATE_KEYS):
        raise ImportError("preserve spatial update allowlist drift")
    return records


def _section_symbol_remaps(
    manifest: Mapping[str, Any], *, required: bool = False
) -> dict[str, str]:
    records = manifest.get("sectionSymbolRemaps")
    if records is None and not required:
        return {}
    if not isinstance(records, list):
        raise ImportError("section symbol remap allowlist drift")
    actual = [
        (item.get("source"), item.get("target"), item.get("targetId"))
        for item in records
        if isinstance(item, dict)
    ]
    if actual != list(SECTION_SYMBOL_REMAP_KEYS) or any(
        set(item) != {"source", "target", "targetId", "reason"} for item in records
    ):
        raise ImportError("section symbol remap allowlist drift")
    return {str(item["source"]): str(item["target"]) for item in records}


def _inactive_group_placeholders(
    manifest: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    records = manifest.get("inactiveGroupPlaceholders")
    if not isinstance(records, list):
        raise ImportError("inactive group placeholder allowlist drift")
    actual = [
        (item.get("name"), item.get("targetId"), item.get("activationBatch"))
        for item in records
        if isinstance(item, dict)
    ]
    if actual != list(INACTIVE_GROUP_PLACEHOLDER_KEYS):
        raise ImportError("inactive group placeholder allowlist drift")
    return records


def _tilesets(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    records = _exact_records(
        manifest,
        "tilesetAdaptations",
        {"role", "directory", "symbol", "secondary", "paletteCount", "authority"},
    )
    _require_unique(records, "directory", "tileset adaptation")
    _require_unique(records, "symbol", "tileset adaptation")
    for item in records:
        target_directory = item.get("targetDirectory", item["directory"])
        target_symbol = item.get("targetSymbol", item["symbol"])
        if (
            item["role"] not in {"primary", "secondary"}
            or not isinstance(item["secondary"], bool)
            or not isinstance(item["paletteCount"], int)
            or item["paletteCount"] <= 0
            or item["authority"] not in {"hns", "mechanical"}
            or re.fullmatch(r"[a-z0-9_]+", str(item["directory"])) is None
            or re.fullmatch(r"[A-Za-z0-9_]+", str(item["symbol"])) is None
            or not isinstance(target_directory, str)
            or re.fullmatch(r"[a-z0-9_]+", target_directory) is None
            or not isinstance(target_symbol, str)
            or re.fullmatch(r"[A-Za-z0-9_]+", target_symbol) is None
        ):
            raise ImportError("invalid tileset adaptation")
    targets = [
        {
            "directory": str(item.get("targetDirectory", item["directory"])),
            "symbol": str(item.get("targetSymbol", item["symbol"])),
        }
        for item in records
    ]
    _require_unique(targets, "directory", "tileset target")
    _require_unique(targets, "symbol", "tileset target")
    return records


def _tileset_target_directory(item: Mapping[str, Any]) -> str:
    return str(item.get("targetDirectory", item["directory"]))


def _tileset_target_symbol(item: Mapping[str, Any]) -> str:
    return str(item.get("targetSymbol", item["symbol"]))


def _layout_tileset_remaps(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    records = _exact_records(
        manifest,
        "layoutTilesetRemaps",
        {"layout", "field", "source", "target"},
    )
    if [(item.get("layout"), item.get("field")) for item in records] != list(
        LAYOUT_TILESET_REMAP_KEYS
    ):
        raise ImportError("layout tileset remap drift")
    if any(
        not isinstance(item.get(key), str)
        or not item[key]
        or (key in {"source", "target"} and not item[key].startswith("gTileset_"))
        for item in records
        for key in ("layout", "field", "source", "target")
    ):
        raise ImportError("invalid layout tileset remap")
    return records


def _without_generated_section(text: str, name: str) -> str:
    """Return source text without one importer-owned generated section."""
    begin = f"// JOHTO IMPORT BEGIN: {name}"
    end = f"// JOHTO IMPORT END: {name}"
    begin_count = text.count(begin)
    end_count = text.count(end)
    if begin_count != end_count or begin_count > 1:
        raise ImportError(f"ambiguous generated section: {name}")
    if not begin_count:
        return text
    pattern = re.compile(
        rf"(?m)^{re.escape(begin)}\n.*?^{re.escape(end)}(?:\n|$)", re.DOTALL
    )
    text, replacements = pattern.subn("", text)
    if replacements != 1:
        raise ImportError(f"malformed generated section: {name}")
    return text


def _trainer_materialization(
    manifest: Mapping[str, Any], opponent_text: str
) -> tuple[str, str, int]:
    """Validate the target append boundary and render one coherent trainer allocation."""
    required = {
        "id",
        "targetId",
        "name",
        "class",
        "pic",
        "gender",
        "music",
        "battleType",
        "species",
        "level",
        "ivs",
    }
    trainers = _exact_records(manifest, "trainerPresentation", required)
    if any(set(item) != required for item in trainers):
        raise ImportError("trainer presentation record fields drift")
    _require_unique(trainers, "id", "trainer presentation")
    target_ids = [item.get("targetId") for item in trainers]
    if any(
        not isinstance(value, int) or isinstance(value, bool) for value in target_ids
    ):
        raise ImportError("trainer presentation has an invalid targetId")
    if len(target_ids) != len(set(target_ids)):
        raise ImportError("duplicate trainer presentation targetId")
    double_battle_values = {"Singles": "No", "Doubles": "Yes"}
    unsupported_battle_types = sorted(
        {
            str(item["battleType"])
            for item in trainers
            if item["battleType"] not in double_battle_values
        }
    )
    if unsupported_battle_types:
        raise ImportError(
            "unsupported trainer presentation battleType: "
            + ", ".join(unsupported_battle_types)
        )

    base_text = _without_generated_section(opponent_text, "rival opponents")
    existing = {
        name: int(value)
        for name, value in re.findall(
            r"^#define\s+(TRAINER_[A-Z0-9_]+)\s+(\d+)\s*$", base_text, re.MULTILINE
        )
    }
    if not existing:
        raise ImportError("target trainer baseline has no numeric opponents")
    baseline = max(existing.values()) + 1
    expected_ids = list(range(baseline, baseline + len(trainers)))
    if sorted(target_ids) != expected_ids:
        raise ImportError(
            f"trainer allocations must append at target IDs {expected_ids[0]} through {expected_ids[-1]}"
        )
    collisions = sorted(str(item["id"]) for item in trainers if item["id"] in existing)
    if collisions:
        raise ImportError(f"trainer allocation name collision: {', '.join(collisions)}")

    count_matches = re.findall(
        r"^#define\s+TRAINERS_COUNT_EMERALD\s+(\d+)\s*$", base_text, re.MULTILINE
    )
    max_matches = re.findall(
        r"^#define\s+MAX_TRAINERS_COUNT_EMERALD\s+(\d+)\s*$",
        base_text,
        re.MULTILINE,
    )
    if len(count_matches) != 1 or len(max_matches) != 1:
        raise ImportError("target trainer count baseline is ambiguous")
    count = expected_ids[-1] + 1
    current_count = int(count_matches[0])
    max_count = int(max_matches[0])
    if current_count not in {baseline, count}:
        raise ImportError(
            f"target trainer count baseline drift: expected {baseline} or {count}, got {current_count}"
        )
    if count > max_count:
        raise ImportError(
            f"trainer allocations exceed allowed append range below {max_count}"
        )

    ordered = sorted(trainers, key=lambda item: int(item["targetId"]))
    parties = "\n\n".join(
        f"=== {item['id']} ===\n"
        f"Name: {item['name']}\nClass: {item['class']}\nPic: {item['pic']}\n"
        f"Gender: {item['gender']}\nMusic: {item['music']}\n"
        f"Double Battle: {double_battle_values[item['battleType']]}\n\n{item['species']}\n"
        f"Level: {item['level']}\nIVs: {item['ivs']}"
        for item in ordered
    )
    macros = "\n".join(f"#define {item['id']} {item['targetId']}" for item in ordered)
    return parties, macros, count


def _apply_script_substitution(
    source: str, script: str, old: str, new: str, occurrences: int
) -> str:
    """Apply one manifest-scoped script rewrite, rejecting donor drift."""
    actual = script.count(old)
    if actual != occurrences:
        raise ImportError(
            f"script substitution drift: {source}/{old!r}: "
            f"expected {occurrences}, got {actual}"
        )
    return script.replace(old, new)


def _berry_tree_materialization(
    manifest: Mapping[str, Any], berry_text: str, hns: Path
) -> str:
    """Validate and render target-owned berry tree IDs for imported maps."""
    allocations = _exact_records(
        manifest,
        "berryTreeAllocations",
        {"source", "path", "hns", "target", "targetId"},
    )
    if len(allocations) != 1:
        raise ImportError("berry tree allocation declaration drift")
    _require_unique(allocations, "target", "berry tree allocation")

    base_text = _without_generated_section(berry_text, "berry tree allocations")
    existing = {
        name: int(value)
        for name, value in re.findall(
            r"^#define\s+(BERRY_TREE_[A-Z0-9_]+)\s+(\d+)\s*$",
            base_text,
            re.MULTILINE,
        )
        if name != "BERRY_TREES_COUNT"
    }
    count_matches = re.findall(
        r"^#define\s+BERRY_TREES_COUNT\s+(\d+)\s*$", base_text, re.MULTILINE
    )
    if len(count_matches) != 1 or not existing:
        raise ImportError("target berry tree allocation baseline is ambiguous")
    count = int(count_matches[0])
    expected_ids = list(
        range(max(existing.values()) + 1, max(existing.values()) + 1 + len(allocations))
    )
    if any(not isinstance(item["targetId"], int) for item in allocations):
        raise ImportError("berry tree allocation has an invalid targetId")
    target_ids = sorted(item["targetId"] for item in allocations)
    if len(target_ids) != len(set(target_ids)):
        raise ImportError("duplicate berry tree allocation targetId")
    if target_ids != expected_ids:
        raise ImportError(
            f"berry tree allocations must append at target IDs {expected_ids[0]} "
            f"through {expected_ids[-1]}"
        )
    if target_ids[-1] >= count:
        raise ImportError(f"berry tree allocations exceed target count {count}")

    selected = {str(item["name"]) for item in manifest["selection"]["maps"]}
    for item in allocations:
        source = item["source"]
        path = item["path"]
        target = item["target"]
        if (
            source not in selected
            or not isinstance(path, str)
            or not re.fullmatch(
                r"object_events/\d+/trainer_sight_or_berry_tree_id", path
            )
            or not isinstance(target, str)
            or not re.fullmatch(r"BERRY_TREE_[A-Z0-9_]+", target)
        ):
            raise ImportError("invalid berry tree allocation declaration")
        donor_map = _json(hns / "data/maps" / str(source) / "map.json")
        if _pointer(donor_map, path) != item["hns"]:
            raise ImportError(f"berry tree allocation drift: {source}/{path}")
        if target in existing:
            raise ImportError(f"berry tree allocation name collision: {target}")

    return "\n".join(
        f"#define {item['target']:<35} {item['targetId']}"
        for item in sorted(allocations, key=lambda value: value["targetId"])
    )


def validate_materialization_adaptations(
    manifest: Mapping[str, Any], pkmn_world: Path, hns: Path
) -> None:
    """Validate every content-changing materialization rule against pinned inputs."""
    selection = manifest["selection"]["maps"]
    names = {str(item["name"]) for item in selection}
    preserved_names = {
        str(item["name"]) for item in selection if not should_materialize(item)
    }

    _preserve_spatial_updates(manifest)
    _section_symbol_remaps(manifest, required=True)
    for source, activation_batch, fields in PRESERVE_SPATIAL_UPDATE_KEYS:
        if source not in preserved_names:
            raise ImportError(
                f"preserve spatial update is not a preserve map: {source}"
            )
        if activation_batch not in BATCH_ORDER or any(
            field not in {"connections", "warp_events"} for field in fields
        ):
            raise ImportError(f"invalid preserve spatial update: {source}")

    region = manifest.get("regionAssignment")
    if region != {"hns": None, "target": "REGION_JOHTO"}:
        raise ImportError("region assignment declaration drift")

    graphics = _mapping(manifest, "graphicsAdaptations")
    music = _mapping(manifest, "musicAdaptations")
    target_constants = (
        Path(__file__).parents[2] / "include/constants/event_objects.h"
    ).read_text(encoding="utf-8")
    target_graphics = set(re.findall(r"\bOBJ_EVENT_GFX_[A-Z0-9_]+\b", target_constants))
    used_graphics: set[str] = set()
    used_music: set[str] = set()
    for name in sorted(names):
        map_item, script = _content_map_and_script(name, manifest, pkmn_world, hns)
        source_music = map_item.get("music")
        if isinstance(source_music, str) and source_music.startswith("MUS_HG_"):
            if source_music not in music:
                raise ImportError(f"undeclared music adaptation: {name}/{source_music}")
            used_music.add(source_music)
        if name not in preserved_names:
            continue
        for event in map_item.get("object_events") or []:
            source = event.get("graphics_id")
            if not isinstance(source, str):
                continue
            base = source.split("+", 1)[0]
            if "+SPECIES_" in source or base not in target_graphics:
                if source not in graphics:
                    raise ImportError(
                        f"undeclared graphics adaptation: {name}/{source}"
                    )
                used_graphics.add(source)
        for token in set(re.findall(r"\bMUS_HG_[A-Z0-9_]+\b", script)):
            if token not in music:
                raise ImportError(f"undeclared music adaptation: {name}/{token}")
            used_music.add(token)
    if used_graphics != set(graphics):
        raise ImportError("unused or missing graphics adaptation declaration")
    if used_music != set(music):
        raise ImportError("unused or missing music adaptation declaration")

    substitutions = _exact_records(
        manifest, "scriptSubstitutions", {"source", "old", "new", "occurrences"}
    )
    seen_substitutions: set[tuple[str, str]] = set()
    scripts: dict[str, str] = {}
    for name in preserved_names:
        _map_item, scripts[name] = _content_map_and_script(
            name, manifest, pkmn_world, hns
        )
    for rule in substitutions:
        source, old, new, occurrences = (
            rule["source"],
            rule["old"],
            rule["new"],
            rule["occurrences"],
        )
        if (
            source not in preserved_names
            or not isinstance(old, str)
            or not old
            or not isinstance(new, str)
            or not isinstance(occurrences, int)
            or occurrences <= 0
        ):
            raise ImportError("invalid script substitution declaration")
        key = (str(source), old)
        if key in seen_substitutions:
            raise ImportError("duplicate script substitution declaration")
        seen_substitutions.add(key)
        scripts[str(source)] = _apply_script_substitution(
            str(source), scripts[str(source)], old, new, occurrences
        )

    target_items = set(
        re.findall(
            r"\bITEM_[A-Z0-9_]+\b",
            (Path(__file__).parents[2] / "include/constants/items.h").read_text(
                encoding="utf-8"
            ),
        )
    )
    unresolved_items = {
        token
        for script in scripts.values()
        for token in re.findall(r"\bITEM_[A-Z0-9_]+\b", script)
        if token not in target_items
    }
    if unresolved_items:
        raise ImportError(
            f"undeclared script item adaptation: {sorted(unresolved_items)[0]}"
        )
    _berry_tree_materialization(
        manifest,
        (Path(__file__).parents[2] / "include/constants/berry.h").read_text(
            encoding="utf-8"
        ),
        hns,
    )
    layouts = _exact_records(
        manifest, "layoutBinaryAuthorities", {"source", "layout", "authority"}
    )
    _require_unique(layouts, "source", "layout binary authority")
    actual_layouts = {(str(item["source"]), str(item["layout"])) for item in layouts}
    selected_pairs = {
        (str(item["name"]), str(item["layout"]))
        for item in selection
        if not should_materialize(item)
    }
    if actual_layouts != selected_pairs or any(
        item["authority"] not in {"hns", "mechanical"} for item in layouts
    ):
        raise ImportError("layout binary authority declaration drift")

    tilesets = _tilesets(manifest)
    remaps = _layout_tileset_remaps(manifest)
    lock = _json(Path(manifest["__manifestPath"]).parent / manifest["allocationLock"])
    mechanical_layouts = {
        str(item["id"]): item
        for item in _json(pkmn_world / "data/layouts/layouts.json")["layouts"]
    }
    expected_tilesets = {
        str(layout[key])
        for layout in (
            _materialized_layout(item, mechanical_layouts, manifest, pkmn_world, hns)
            for item in active_layout_selection(manifest, lock)
        )
        for key in ("primary_tileset", "secondary_tileset")
    }
    declared_tilesets = {
        f"gTileset_{_tileset_target_symbol(item)}" for item in tilesets
    }
    source_to_target = {
        f"gTileset_{item['symbol']}": f"gTileset_{_tileset_target_symbol(item)}"
        for item in tilesets
    }
    hns_layouts = {
        str(item["id"]): item
        for item in _json(hns / "data/layouts/layouts.json")["layouts"]
    }
    for remap in remaps:
        layout, field = str(remap["layout"]), str(remap["field"])
        if (
            hns_layouts.get(layout, {}).get(field) != remap["source"]
            or source_to_target.get(str(remap["source"])) != remap["target"]
            or remap["source"] == remap["target"]
        ):
            raise ImportError(f"layout tileset remap drift: {layout}/{field}")
    target_tileset_header = _without_generated_section(
        (Path(__file__).parents[2] / "include/tilesets.h").read_text(encoding="utf-8"),
        "externs",
    )
    existing_tilesets = set(
        re.findall(r"\bgTileset_[A-Za-z0-9_]+\b", target_tileset_header)
    )
    target_headers = _without_generated_section(
        (Path(__file__).parents[2] / "src/data/tilesets/headers.h").read_text(
            encoding="utf-8"
        ),
        "headers",
    )
    target_definitions = set(
        re.findall(r"\bconst struct Tileset (gTileset_[A-Za-z0-9_]+)\b", target_headers)
    )
    collisions = declared_tilesets & (existing_tilesets | target_definitions)
    if collisions:
        raise ImportError(
            f"tileset target collides with target-defined symbol: {sorted(collisions)[0]}"
        )
    existing_tilesets |= target_definitions
    if not declared_tilesets <= expected_tilesets or not expected_tilesets <= (
        declared_tilesets | existing_tilesets
    ):
        raise ImportError("tileset adaptation declaration drift")
    for item in tilesets:
        authority = pkmn_world if item["authority"] == "mechanical" else hns
        source = (
            authority / "data/tilesets" / str(item["role"]) / str(item["directory"])
        )
        required_assets = [
            source / "tiles.png",
            source / "metatiles.bin",
            source / "metatile_attributes.bin",
        ] + [
            source / "palettes" / f"{index:02}.pal"
            for index in range(item["paletteCount"])
        ]
        if not source.is_dir() or not all(path.is_file() for path in required_assets):
            raise ImportError(f"tileset authority drift: {item['directory']}")

    encounter = manifest.get("encounterAdaptations")
    water = encounter.get("water12To5") if isinstance(encounter, dict) else None
    if not isinstance(water, dict) or water.get("targetWeights") != [60, 30, 5, 4, 1]:
        raise ImportError("encounter adaptation declaration drift")
    indices = water.get("sourceIndices")
    if (
        not isinstance(indices, list)
        or len(indices) != 5
        or any(
            not isinstance(index, int) or index < 0 or index >= 12 for index in indices
        )
    ):
        raise ImportError("encounter source indices are invalid")

    trainers = _exact_records(
        manifest,
        "trainerPresentation",
        {
            "id",
            "targetId",
            "name",
            "class",
            "pic",
            "gender",
            "music",
            "battleType",
            "species",
            "level",
            "ivs",
        },
    )
    _require_unique(trainers, "id", "trainer presentation")
    if len(trainers) != 3:
        raise ImportError("trainer presentation must declare exactly three rivals")
    _trainer_materialization(
        manifest,
        (Path(__file__).parents[2] / "include/constants/opponents.h").read_text(
            encoding="utf-8"
        ),
    )


def report_document(
    inventory: Inventory,
    closure: Closure,
    evidence: Mapping[str, Any],
    materialized_tree: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report = {
        "schemaVersion": 1,
        "inventory": {
            key: len(getattr(inventory, key))
            for key in ("maps", "layouts", "groups", "sections", "tilesets")
        },
        "closure": asdict(closure),
        "evidence": evidence,
    }
    if materialized_tree is not None:
        report["materializedTree"] = dict(materialized_tree)
    return report


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = path.stat().st_mode & 0o777 if path.exists() else None
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if existing_mode is not None:
            os.chmod(temporary, existing_mode)
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _dump_source(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def normalize_materialized_text(text: str) -> str:
    """Remove donor-only line-end whitespace and emit exactly one final newline."""
    text = re.sub(r"[ \t]+(?=\r?(?:\n|\Z))", "", text)
    return text.rstrip("\r\n") + "\n"


def _ordered(value: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    return {key: value[key] for key in keys if key in value} | {
        key: item for key, item in value.items() if key not in keys
    }


def _ordered_encounters(document: Mapping[str, Any]) -> dict[str, Any]:
    groups = []
    for group in document["wild_encounter_groups"]:
        if group.get("label") != "gWildMonHeaders" and group.get("fields") is None:
            group = {key: item for key, item in group.items() if key != "fields"}
        group = _ordered(group, ("label", "for_maps", "fields", "encounters"))
        if "fields" in group:
            group["fields"] = (
                [
                    _ordered(field, ("type", "encounter_rates", "groups"))
                    for field in group.get("fields") or []
                ]
                if group.get("fields") is not None
                else group.get("fields")
            )
            for field in group.get("fields") or []:
                if "groups" in field:
                    field["groups"] = _ordered(
                        field["groups"], ("old_rod", "good_rod", "super_rod")
                    )
        records = []
        for record in group.get("encounters") or []:
            record = _ordered(
                record,
                (
                    "map",
                    "base_label",
                    "land_mons",
                    "water_mons",
                    "rock_smash_mons",
                    "fishing_mons",
                ),
            )
            for kind in ("land_mons", "water_mons", "rock_smash_mons", "fishing_mons"):
                if kind not in record:
                    continue
                record[kind] = _ordered(record[kind], ("encounter_rate", "mons"))
                record[kind]["mons"] = [
                    _ordered(mon, ("min_level", "max_level", "species"))
                    for mon in record[kind]["mons"]
                ]
            records.append(record)
        group["encounters"] = records
        groups.append(group)
    return {"wild_encounter_groups": groups}


def _copy_file(source: Path, destination: Path) -> None:
    atomic_write(destination, source.read_bytes())


def _replace_generated_section(
    path: Path,
    name: str,
    body: str,
    *,
    blank_line_before_end: bool = False,
    preprocessor_markers: bool = False,
) -> None:
    begin = f"// JOHTO IMPORT BEGIN: {name}"
    end = f"// JOHTO IMPORT END: {name}"
    text = path.read_text(encoding="utf-8")
    begin_count = text.count(begin)
    end_count = text.count(end)
    if begin_count != end_count or begin_count > 1:
        raise ImportError(f"ambiguous generated section in {path}: {name}")
    if begin_count:
        pattern = re.compile(
            rf"(?m)^[^\n]*{re.escape(begin)}[^\n]*\n.*?"
            rf"^[^\n]*{re.escape(end)}[^\n]*(?:\n|$)",
            re.DOTALL,
        )
        text, replacements = pattern.subn("", text)
        if replacements != 1:
            raise ImportError(f"malformed generated section in {path}: {name}")
    terminator = "\n\n" if blank_line_before_end else "\n"
    begin_line = f"#if 1 /* {begin} */" if preprocessor_markers else begin
    end_line = f"#endif /* {end} */" if preprocessor_markers else end
    text = text.rstrip() + f"\n\n{begin_line}\n{body.rstrip()}{terminator}{end_line}\n"
    atomic_write(path, text.encode("utf-8"))


def _replace_generated_section_before(
    path: Path, name: str, body: str, marker: str
) -> None:
    """Replace one generated section immediately before one structural marker."""
    begin = f"// JOHTO IMPORT BEGIN: {name}"
    end = f"// JOHTO IMPORT END: {name}"
    text = path.read_text(encoding="utf-8")
    marker_matches = list(re.finditer(rf"(?m)^{re.escape(marker)}[ \t]*$", text))
    if len(marker_matches) != 1:
        raise ImportError(
            f"expected exactly one placement marker in {path}: {marker!r}"
        )

    begin_count = text.count(begin)
    end_count = text.count(end)
    if begin_count != end_count or begin_count > 1:
        raise ImportError(f"ambiguous generated section in {path}: {name}")
    if begin_count:
        pattern = re.compile(
            rf"(?m)^{re.escape(begin)}\n.*?^{re.escape(end)}(?:\n|$)", re.DOTALL
        )
        text, replacements = pattern.subn("", text)
        if replacements != 1:
            raise ImportError(f"malformed generated section in {path}: {name}")

    marker_matches = list(re.finditer(rf"(?m)^{re.escape(marker)}[ \t]*$", text))
    if len(marker_matches) != 1:
        raise ImportError(
            f"expected exactly one placement marker in {path}: {marker!r}"
        )
    marker_match = marker_matches[0]
    prefix = text[: marker_match.start()].rstrip("\n")
    suffix = text[marker_match.end() :]
    if suffix.strip():
        raise ImportError(f"placement marker is not final in {path}: {marker!r}")
    section = f"{begin}\n{body.rstrip()}\n{end}"
    text = f"{prefix}\n\n{section}\n\n{marker_match.group()}\n"
    atomic_write(path, text.encode("utf-8"))


def _copy_tree_without_generated(source: Path, destination: Path) -> None:
    if destination.exists():
        for item in sorted(destination.rglob("*"), reverse=True):
            relative = item.relative_to(destination)
            if item.is_symlink():
                raise ImportError(f"tileset destination contains a symlink: {item}")
            if item.is_file() and (item.suffix == ".inc" or "anim" in relative.parts):
                item.unlink()
            elif item.is_dir() and not any(item.iterdir()):
                item.rmdir()
    for item in sorted(source.rglob("*")):
        if not item.is_file() or item.suffix == ".inc" or "anim" in item.parts:
            continue
        _copy_file(item, destination / item.relative_to(source))


def _tree_payload(root: Path) -> dict[str, bytes]:
    payload: dict[str, bytes] = {}
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root)
        if item.is_symlink():
            raise ImportError(f"tileset tree contains a symlink: {item}")
        if item.is_file() and item.suffix != ".inc" and "anim" not in relative.parts:
            payload[relative.as_posix()] = item.read_bytes()
    return payload


def _copy_imported_tileset_tree(source: Path, destination: Path) -> None:
    """Create an importer-owned tree without overwriting an existing asset tree."""
    if destination.exists():
        if not destination.is_dir() or _tree_payload(destination) != _tree_payload(
            source
        ):
            raise ImportError(
                f"refusing to overwrite pre-existing tileset destination: {destination}"
            )
        return
    _copy_tree_without_generated(source, destination)


def _content_authority_root(
    name: str, manifest: Mapping[str, Any], pkmn_world: Path, hns: Path
) -> Path:
    return pkmn_world if name in manifest["contentFallback"]["maps"] else hns


def _content_map_and_script(
    name: str, manifest: Mapping[str, Any], pkmn_world: Path, hns: Path
) -> tuple[dict[str, Any], str]:
    authority = _content_authority_root(name, manifest, pkmn_world, hns)
    map_item = _json(authority / "data/maps" / name / "map.json")
    try:
        script = (authority / "data/maps" / name / "scripts.inc").read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeError) as error:
        raise ImportError(f"cannot read content script for {name}: {error}") from error
    return map_item, script


def _materialized_map(
    item: Mapping[str, Any],
    pkmn_world: Path,
    hns: Path,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    name = str(item["name"])
    authority = _content_authority_root(name, manifest, pkmn_world, hns)
    value = _json(authority / "data/maps" / name / "map.json")
    mechanical = _json(pkmn_world / "data/maps" / name / "map.json")
    for rule in manifest.get("mapFieldDecisions", []):
        if rule["map"] == name:
            value[str(rule["field"])] = mechanical[str(rule["field"])]
    if "region_map_section" in value:
        value["region_map_section"] = _section_symbol_remaps(manifest).get(
            str(value["region_map_section"]), str(value["region_map_section"])
        )
    value["region"] = manifest["regionAssignment"]["target"]
    music = _mapping(manifest, "musicAdaptations")
    value["music"] = music.get(value.get("music"), value.get("music"))
    for rule in manifest.get("adaptations", []):
        if rule["source"] == name:
            _set_pointer(value, str(rule["path"]), rule["mechanical"])
    deferred = {
        (str(edge["path"]), str(edge["kind"]))
        for edge in manifest.get("deferredEdges", [])
        if edge["source"] == name
    }
    value["connections"] = [
        edge
        for index, edge in enumerate(value.get("connections") or [])
        if (f"connections/{index}", "connection") not in deferred
    ]
    for rule in manifest.get("warpReindexes", []):
        if rule["source"] == name:
            _set_pointer(value, str(rule["path"]), rule["to"])
    for rule in manifest.get("berryTreeAllocations", []):
        if rule["source"] == name:
            _set_pointer(value, str(rule["path"]), rule["target"])
    removed_warps = {
        str(rule["path"])
        for rule in manifest.get("warpRemovals", [])
        if rule["source"] == name
    }
    value["warp_events"] = [
        edge
        for index, edge in enumerate(value.get("warp_events") or [])
        if f"warp_events/{index}" not in removed_warps
    ]
    for event in value.get("object_events") or []:
        graphics = event.get("graphics_id")
        if isinstance(graphics, str):
            adaptations = _mapping(manifest, "graphicsAdaptations")
            if graphics in adaptations:
                event["graphics_id"] = adaptations[graphics]
    return value


def _materialize_selected_map_trees(
    target: Path,
    selection: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    pkmn_world: Path,
    hns: Path,
) -> None:
    for item in selection:
        if not should_materialize(item):
            continue
        name = str(item["name"])
        destination = target / "data/maps" / name
        value = materialize_resident_map(
            _materialized_map(item, pkmn_world, hns, manifest)
        )
        atomic_write(destination / "map.json", _dump_source(value))
        atomic_write(
            destination / "scripts.inc",
            resident_map_script(name).encode("utf-8"),
        )


def _materialize_preserved_spatial_updates(
    target: Path,
    selection: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    pkmn_world: Path,
    hns: Path,
) -> None:
    """Apply only reviewed spatial closure fields to existing preserve maps."""
    selected = {str(item["name"]): item for item in selection}
    active_batches = set(manifest["activeBatches"])
    for declaration in _preserve_spatial_updates(manifest):
        if declaration["activationBatch"] not in active_batches:
            continue
        name = str(declaration["source"])
        item = selected.get(name)
        if item is None or should_materialize(item):
            raise ImportError(f"invalid preserve spatial update target: {name}")
        path = target / "data/maps" / name / "map.json"
        current = _json(path)
        reviewed = _materialized_map(item, pkmn_world, hns, manifest)
        for field in declaration["fields"]:
            current[str(field)] = copy.deepcopy(reviewed[str(field)])
        atomic_write(path, _dump_source(current))


def _materialized_layout(
    item: Mapping[str, Any],
    mechanical_layouts: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
    pkmn_world: Path,
    hns: Path,
) -> dict[str, Any]:
    layout_id = str(item.get("layout", item.get("id")))
    fallback_layouts = {
        str(selected["layout"])
        for selected in manifest["selection"]["maps"]
        if str(selected["name"]) in manifest["contentFallback"]["maps"]
    }
    authority_root = pkmn_world if layout_id in fallback_layouts else hns
    layout = copy.deepcopy(
        _find_layout(authority_root / "data/layouts/layouts.json", layout_id)
    )
    for rule in manifest.get("layoutHeaderDecisions", []):
        if rule["layout"] == layout_id:
            layout[str(rule["field"])] = mechanical_layouts[layout_id][
                str(rule["field"])
            ]
    for rule in _layout_tileset_remaps(manifest):
        if rule["layout"] == layout_id:
            field = str(rule["field"])
            if layout.get(field) != rule["source"]:
                raise ImportError(
                    f"layout tileset remap source drift: {layout_id}/{field}"
                )
            layout[field] = rule["target"]
    layout.pop("layout_version", None)
    layout["format"] = "johto"
    return layout


def _tileset_graphics(manifest: Mapping[str, Any]) -> str:
    blocks: list[str] = ["#if HAS_JOHTO_TILESETS"]
    for item in _tilesets(manifest):
        role = item["role"]
        directory = _tileset_target_directory(item)
        symbol = _tileset_target_symbol(item)
        blocks.append(
            f"const u32 gTilesetTiles_{symbol}[] = INCGFX_U32("
            f'"data/tilesets/{role}/{directory}/tiles.png", ".4bpp.fastSmol");\n\n'
            f"const u16 gTilesetPalettes_{symbol}[][16] =\n{{"
        )
        count = item["paletteCount"]
        blocks.extend(
            f'    INCGFX_U16("data/tilesets/{role}/{directory}/palettes/{index:02}.pal", ".gbapal"),'
            for index in range(count)
        )
        blocks.append("};")
    blocks.append("#endif // HAS_JOHTO_TILESETS")
    return "\n\n".join(blocks)


def _tileset_metatiles(manifest: Mapping[str, Any]) -> str:
    lines = ["#if HAS_JOHTO_TILESETS"]
    for item in _tilesets(manifest):
        role = item["role"]
        directory = _tileset_target_directory(item)
        symbol = _tileset_target_symbol(item)
        lines.extend(
            (
                f'const u16 gMetatiles_{symbol}[] = INCBIN_U16("data/tilesets/{role}/{directory}/metatiles.bin");',
                f'const u16 gMetatileAttributes_{symbol}[] = INCBIN_U16("data/tilesets/{role}/{directory}/metatile_attributes.bin");',
                "",
            )
        )
    lines.append("#endif // HAS_JOHTO_TILESETS")
    return "\n".join(lines)


def _tileset_headers(manifest: Mapping[str, Any]) -> str:
    blocks = ["#if HAS_JOHTO_TILESETS"]
    for item in _tilesets(manifest):
        symbol, secondary = _tileset_target_symbol(item), item["secondary"]
        blocks.append(
            f"const struct Tileset gTileset_{symbol} =\n{{\n"
            f"    .isCompressed = TRUE,\n"
            f"    .flags = TILESET_FLAGS({'TRUE' if secondary else 'FALSE'}, METATILE_ATTRIBUTES_EMERALD_U16),\n"
            f"    .tiles = gTilesetTiles_{symbol},\n"
            f"    .palettes = gTilesetPalettes_{symbol},\n"
            f"    .metatiles = gMetatiles_{symbol},\n"
            f"    .metatileAttributes = gMetatileAttributes_{symbol},\n"
            f"    .callback = NULL,\n}};"
        )
    blocks.append("#endif // HAS_JOHTO_TILESETS")
    return "\n\n".join(blocks)


def _append_layouts_at_locked_indices(
    existing: Sequence[Mapping[str, Any]],
    emitted: Sequence[tuple[int, Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    result = [copy.deepcopy(dict(item)) for item in existing]
    ordered = sorted(emitted, key=lambda item: item[0])
    first_index = ordered[0][0] if ordered else len(result)
    if len(result) != first_index:
        raise ImportError(
            "layout target baseline drift: "
            f"expected {first_index} layouts, got {len(result)}"
        )
    for target_index, layout in ordered:
        if len(result) != target_index:
            raise ImportError(
                f"layout allocation drift: {layout['id']} cannot occupy index {target_index}"
            )
        result.append(copy.deepcopy(dict(layout)))
    return result


def _materialize_section_registry(
    target: Path,
    manifest: Mapping[str, Any],
    hns: Path,
    pkmn_world: Path | None = None,
) -> None:
    """Materialize residency-owned sections at their allocation-locked values."""
    path = target / "src/data/region_map/region_map_sections.json"
    document = _json(path)
    sections = document.get("map_sections")
    if not isinstance(sections, list):
        raise ImportError("target region-map section registry is malformed")
    existing = {str(item.get("id")) for item in sections}
    section_remaps = _section_symbol_remaps(manifest)
    residency_sections = {
        str(item["section"])
        for item in manifest["selection"]["maps"]
        if should_materialize(item)
    }
    source_document = _json(hns / "src/data/region_map/region_map_sections_johto.json")
    source_sections = {
        str(item["map_section"]): item
        for item in source_document.get("map_sections", [])
    }
    fallback_sections: dict[str, Mapping[str, Any]] = {}
    if pkmn_world is not None:
        mechanical_document = _json(
            pkmn_world / "src/data/region_map/region_map_sections.json"
        )
        fallback_sections = {
            str(item["id"]): item
            for item in mechanical_document.get("map_sections", [])
            if item.get("id") in FALLBACK_SECTION_METADATA
        }
        if tuple(sorted(fallback_sections)) != tuple(sorted(FALLBACK_SECTION_METADATA)):
            raise ImportError("PKMN-World fallback section metadata drift")
    metadata_sources = {
        str(item["mechanical"]): str(item["hns"])
        for item in manifest.get("mapFieldDecisions", [])
        if item.get("field") == "region_map_section"
    }
    for allocation in manifest["sectionAllocations"]:
        name = str(allocation["name"])
        target_name = section_remaps.get(name, name)
        if target_name in existing and name not in residency_sections:
            continue
        target_id = int(allocation["targetId"])
        source_name = metadata_sources.get(name, name)
        source = source_sections.get(source_name)
        if source is None and name in FALLBACK_SECTION_METADATA:
            source = fallback_sections.get(name)
        if source is None:
            raise ImportError(f"HnS has no region-map section metadata for {name}")
        emitted = {
            "id": target_name,
            "value": target_id,
            "kind": "geographic",
            "region": "REGION_JOHTO",
            "region_map_type": "REGION_MAP_HOENN",
            "saved_location": (
                target_name if target_id < SAVED_LOCATION_INVALID else None
            ),
            "met_location": target_id if target_id < MET_LOCATION_INVALID else None,
            "met_location_display": (
                target_name if target_id < MET_LOCATION_INVALID else None
            ),
            "name": source["name"],
        }
        for key in ("x", "y", "width", "height"):
            if key in source:
                emitted[key] = source[key]
        if target_name in existing:
            matching_indices = [
                index
                for index, item in enumerate(sections)
                if item.get("id") == target_name
            ]
            if matching_indices != [target_id]:
                raise ImportError(
                    f"section allocation drift: {name} cannot occupy ID {target_id}"
                )
            sections[target_id] = emitted
        else:
            if len(sections) != target_id:
                raise ImportError(
                    f"section allocation drift: {name} cannot occupy ID {target_id}"
                )
            sections.append(emitted)
        existing.add(target_name)
    document["map_section_count"] = len(sections)
    atomic_write(
        path,
        (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )


def materialize_source_tree(
    target: Path, manifest: Mapping[str, Any], pkmn_world: Path, hns: Path
) -> None:
    selection = manifest["selection"]["maps"]
    active_batches = {
        item["name"]: item
        for item in manifest["batches"]
        if item["name"] in manifest["activeBatches"]
    }
    if active_batches and not any(
        should_materialize(item) for item in active_batches.values()
    ):
        return
    _materialize_selected_map_trees(target, selection, manifest, pkmn_world, hns)
    _materialize_preserved_spatial_updates(target, selection, manifest, pkmn_world, hns)

    mechanical_layouts = {
        item["id"]: item
        for item in _json(pkmn_world / "data/layouts/layouts.json")["layouts"]
    }
    lock = _json(Path(manifest["__manifestPath"]).parent / manifest["allocationLock"])
    layout_selection = active_layout_selection(manifest, lock)
    target_layouts = _json(target / "data/layouts/layouts.json")
    residency_layouts = [item for item in layout_selection if should_materialize(item)]
    selected_ids = {str(item["id"]) for item in residency_layouts}
    target_layouts["layouts"] = [
        item for item in target_layouts["layouts"] if item["id"] not in selected_ids
    ]
    emitted_layouts: list[tuple[int, dict[str, Any]]] = []
    for item in residency_layouts:
        layout = _materialized_layout(
            item, mechanical_layouts, manifest, pkmn_world, hns
        )
        emitted_layouts.append((int(item["targetIndex"]), layout))
        layout_id = str(item["id"])
        matching_map = next(
            (selected for selected in selection if selected["layout"] == layout_id),
            None,
        )
        authority = next(
            (
                rule["authority"]
                for rule in manifest["layoutBinaryAuthorities"]
                if matching_map is not None
                and rule["source"] == matching_map["name"]
                and rule["layout"] == layout_id
            ),
            "mechanical"
            if matching_map is not None
            and matching_map["name"] in manifest["contentFallback"]["maps"]
            else "hns",
        )
        layout_source = pkmn_world if authority == "mechanical" else hns
        source_layout = _find_layout(
            layout_source / "data/layouts/layouts.json", layout_id
        )
        for path_key in ("blockdata_filepath", "border_filepath"):
            relative = Path(str(source_layout[path_key]))
            _copy_file(
                layout_source / relative,
                target / relative,
            )
    target_layouts["layouts"] = _append_layouts_at_locked_indices(
        target_layouts["layouts"], emitted_layouts
    )
    layout_keys = (
        "id",
        "name",
        "width",
        "height",
        "border_width",
        "border_height",
        "primary_tileset",
        "secondary_tileset",
        "border_filepath",
        "blockdata_filepath",
        "format",
    )
    target_layouts = {
        "layouts_table_label": target_layouts["layouts_table_label"],
        "layouts": [_ordered(item, layout_keys) for item in target_layouts["layouts"]],
    }
    atomic_write(target / "data/layouts/layouts.json", _dump_source(target_layouts))

    groups = _json(target / "data/maps/map_groups.json")
    groups = _materialized_group_registry(
        groups, selection, manifest["groupAllocations"]
    )
    atomic_write(target / "data/maps/map_groups.json", _dump_source(groups))
    _materialize_section_registry(target, manifest, hns, pkmn_world)

    for item in _tilesets(manifest):
        role = item["role"]
        source_directory = str(item["directory"])
        target_directory = _tileset_target_directory(item)
        authority = pkmn_world if item["authority"] == "mechanical" else hns
        _copy_imported_tileset_tree(
            authority / "data/tilesets" / role / source_directory,
            target / "data/tilesets" / role / target_directory,
        )
    _replace_generated_section(
        target / "src/data/tilesets/graphics.h",
        "graphics",
        _tileset_graphics(manifest),
    )
    _replace_generated_section(
        target / "src/data/tilesets/metatiles.h",
        "metatiles",
        _tileset_metatiles(manifest),
    )
    _replace_generated_section(
        target / "src/data/tilesets/headers.h", "headers", _tileset_headers(manifest)
    )
    externs = (
        "#if HAS_JOHTO_TILESETS\n"
        + "\n".join(
            f"extern const struct Tileset gTileset_{symbol};"
            for symbol in (_tileset_target_symbol(item) for item in _tilesets(manifest))
        )
        + "\n#endif // HAS_JOHTO_TILESETS"
    )
    _replace_generated_section_before(
        target / "include/tilesets.h",
        "externs",
        externs,
        "#endif //GUARD_tilesets_H",
    )
    includes = "\n".join(
        f'\t.include "data/maps/{item["name"]}/scripts.inc"' for item in selection
    )
    includes += """

Johto_EventScript_SetTimeEncounters::
	return

Johto_Text_DeferredElmCall::
	.string "PROF. ELM will call again later.$"
"""
    _replace_generated_section(target / "data/event_scripts.s", "map scripts", includes)

    profile = manifest["materializationProfile"]
    if not profile["encounters"] and not profile["gameplayGlobals"]:
        return

    target_encounters = _json(target / "src/data/wild_encounters.json")
    hns_groups = _json(hns / "src/data/wild_encounters.json")["wild_encounter_groups"]
    selected_map_ids = {str(item["id"]) for item in selection}
    imported = [
        copy.deepcopy(encounter)
        for group in hns_groups
        if group.get("label") == "gWildMonHeaders"
        for encounter in group.get("encounters", [])
        if encounter.get("map") in selected_map_ids
    ]
    # HnS encodes some surfing tables using its twelve land-slot shape. Map the
    # cumulative 60/30/5/4/1 target thresholds to source slots deterministically.
    for encounter in imported:
        water = encounter.get("water_mons")
        if water and len(water.get("mons", [])) == 12:
            indices = manifest["encounterAdaptations"]["water12To5"]["sourceIndices"]
            water["mons"] = [water["mons"][index] for index in indices]
    for group in target_encounters["wild_encounter_groups"]:
        if group.get("label") == "gWildMonHeaders":
            group["encounters"] = [
                item
                for item in group["encounters"]
                if item.get("map") not in selected_map_ids
            ] + imported
            break
    atomic_write(
        target / "src/data/wild_encounters.json",
        _dump_source(_ordered_encounters(target_encounters)),
    )

    flag_values = [*range(0x8E5, 0x8FE), *range(0x900, 0x909)]
    flag_lines = "\n".join(
        f"#define {name:<60} 0x{value:X}"
        for name, value in zip(JOHTO_FLAGS, flag_values, strict=True)
    )
    _replace_generated_section_before(
        target / "include/constants/flags.h",
        "flags",
        flag_lines,
        "#endif // GUARD_CONSTANTS_FLAGS_H",
    )
    var_lines = "\n".join(
        f"#define {name:<60} 0x{value:X}"
        for name, value in zip(JOHTO_VARS, range(0x40F7, 0x40FC), strict=True)
    )
    _replace_generated_section_before(
        target / "include/constants/vars.h",
        "vars",
        var_lines,
        "#endif // GUARD_CONSTANTS_VARS_H",
    )
    berry_constants = target / "include/constants/berry.h"
    berry_lines = _berry_tree_materialization(
        manifest, berry_constants.read_text(encoding="utf-8"), hns
    )
    _replace_generated_section_before(
        berry_constants,
        "berry tree allocations",
        berry_lines,
        "#endif // GUARD_CONSTANTS_BERRY_H",
    )

    opponents = target / "include/constants/opponents.h"
    opponent_text = opponents.read_text(encoding="utf-8")
    trainers, opponent_macros, trainer_count = _trainer_materialization(
        manifest, opponent_text
    )
    _replace_generated_section(
        target / "src/data/trainers.party",
        "rival trainers",
        trainers,
        blank_line_before_end=True,
        preprocessor_markers=True,
    )
    opponent_text = re.sub(
        r"#define TRAINERS_COUNT_EMERALD\s+\d+",
        f"#define TRAINERS_COUNT_EMERALD     {trainer_count}",
        opponent_text,
    )
    atomic_write(opponents, opponent_text.encode())
    _replace_generated_section_before(
        opponents,
        "rival opponents",
        opponent_macros,
        "#endif  // GUARD_CONSTANTS_OPPONENTS_H",
    )

    menu_constants = target / "include/constants/script_menu.h"
    menu_text = menu_constants.read_text(encoding="utf-8")
    if "MULTI_DAYS_OF_WEEK" not in menu_text:
        anchor = "    MULTI_HOF_EGGS_VICTORIES_QUIT,\n"
        if anchor not in menu_text:
            raise ImportError("cannot place Johto weekday multichoice ID")
        menu_text = menu_text.replace(anchor, anchor + "    MULTI_DAYS_OF_WEEK,\n")
        atomic_write(menu_constants, menu_text.encode())
    menu_data = target / "src/data/script_menu.h"
    menu_text = menu_data.read_text(encoding="utf-8")
    if "MultichoiceList_DaysOfWeek" not in menu_text:
        definition = """static const struct MenuAction MultichoiceList_DaysOfWeek[] =
{
    {COMPOUND_STRING("SUNDAY")},
    {COMPOUND_STRING("MONDAY")},
    {COMPOUND_STRING("TUESDAY")},
    {COMPOUND_STRING("WEDNESDAY")},
    {COMPOUND_STRING("THURSDAY")},
    {COMPOUND_STRING("FRIDAY")},
    {COMPOUND_STRING("SATURDAY")},
    {gText_Exit},
};

"""
        anchor = "struct MultichoiceListStruct\n"
        if anchor not in menu_text:
            raise ImportError("cannot place Johto weekday multichoice list")
        menu_text = menu_text.replace(anchor, definition + anchor, 1)
        entry_anchor = (
            "    [MULTI_TAG_MATCH_TYPE]             = "
            "MULTICHOICE(MultichoiceList_TagMatchType),\n"
        )
        if entry_anchor not in menu_text:
            raise ImportError("cannot register Johto weekday multichoice list")
        menu_text = menu_text.replace(
            entry_anchor,
            entry_anchor
            + "    [MULTI_DAYS_OF_WEEK]             = MULTICHOICE(MultichoiceList_DaysOfWeek),\n",
            1,
        )
        atomic_write(menu_data, menu_text.encode())


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--inventory",
        action="store_true",
        help="print the authenticated full inventory",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="validate inventory, authority, and selected closure",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="materialize the validated source closure and write its report",
    )
    mode.add_argument(
        "--propose",
        type=Path,
        metavar="PATH",
        help="write the deterministic reviewed batch/allocation candidate",
    )
    parser.add_argument("--pkmn-world", type=Path, required=True)
    parser.add_argument("--hns", type=Path, required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("import_manifest.json"),
    )
    parser.add_argument("--output", type=Path, help="report file required by --apply")
    parser.add_argument(
        "--target-root",
        type=Path,
        default=Path.cwd(),
        help="repository root materialized by --apply (default: current directory)",
    )
    args = parser.parse_args(argv)
    if args.apply and args.output is None:
        parser.error("--apply requires --output")
    if not args.apply and args.output is not None:
        parser.error("--output is only valid with --apply")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        inventory, closure, evidence = build_closure(
            manifest, args.pkmn_world, args.hns
        )
        if args.inventory:
            print(_dump(asdict(inventory)), end="")
        elif args.apply:
            materialize_source_tree(
                args.target_root, manifest, args.pkmn_world, args.hns
            )
            atomic_write(
                args.output,
                _dump(
                    report_document(
                        inventory,
                        closure,
                        evidence,
                        materialized_tree_record(
                            args.target_root,
                            manifest["selection"]["maps"],
                            active_layout_selection(
                                manifest,
                                _json(
                                    Path(manifest["__manifestPath"]).parent
                                    / manifest["allocationLock"]
                                ),
                            ),
                        ),
                    )
                ).encode("utf-8"),
            )
            print(
                f"materialized {len(closure.maps)}-map Johto closure in "
                f"{args.target_root}; wrote validated closure report: {args.output}"
            )
        elif args.propose:
            lock = _json(
                Path(manifest["__manifestPath"]).parent / manifest["allocationLock"]
            )
            atomic_write(
                args.propose, _dump(proposal_document(manifest, lock)).encode("utf-8")
            )
            print(f"wrote deterministic Johto allocation proposal: {args.propose}")
        else:
            print(
                "clean Johto import: "
                f"{len(inventory.maps)} maps, {len(inventory.layouts)} layouts, "
                f"{len(inventory.groups)} groups, {len(inventory.sections)} sections, "
                f"{len(inventory.tilesets)} tilesets; "
                f"{len(closure.maps)}-map selected closure; "
                f"{len(closure.deferred_edges)} reviewed deferred edges; no unresolved reference "
                "or donor-authority divergence"
            )
        return 0
    except ImportError as error:
        print(f"johto import error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
