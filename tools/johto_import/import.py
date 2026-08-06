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
    exact_paths: list[str] = []
    for rule in adaptations:
        source = rule.get("source")
        path = rule.get("path")
        if (
            source not in mechanical_maps
            or (selected_names is not None and source not in selected_names)
            or not isinstance(path, str)
        ):
            raise ImportError("adaptation names an unknown selected map or path")
        hns = _json(hns_root / "data/maps" / source / "map.json")
        actual_hns = _pointer(hns, path)
        actual_mechanical = _pointer(mechanical_maps[source], path)
        if actual_hns != rule.get("hns") or actual_mechanical != rule.get("mechanical"):
            raise ImportError(f"adaptation drift: {source}/{path}")
        exact_paths.append(f"maps/{source}/{path}")
    if len(exact_paths) != len(set(exact_paths)):
        raise ImportError("duplicate adaptation path")
    return AuthorityRules(
        tuple(str(item) for item in hns_categories), tuple(exact_paths)
    )


def effective_selected_maps(
    selection: Sequence[Mapping[str, Any]],
    mechanical_maps: Mapping[str, Mapping[str, Any]],
    hns_root: Path,
    adaptations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build the authoritative HnS map view with only exact mechanical overlays."""
    effective: dict[str, dict[str, Any]] = {}
    for declared in selection:
        name = str(declared["name"])
        data = _json(hns_root / "data/maps" / name / "map.json")
        if not isinstance(data, dict):
            raise ImportError(f"HnS map is not an object: {name}")
        effective[name] = copy.deepcopy(data)
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
    mechanical_layouts: Mapping[str, Mapping[str, Any]],
    hns: Path,
) -> None:
    for item in selection:
        name, layout_id = item["name"], item["layout"]
        hns_map = _json(hns / "data/maps" / name / "map.json")
        if (
            hns_map.get("name") != name
            or hns_map.get("id") != item["id"]
            or hns_map.get("layout") != layout_id
        ):
            raise ImportError(f"HnS content identity drift for {name}")
        hns_layout = _find_layout(hns / "data/layouts/layouts.json", layout_id)
        mechanical = mechanical_layouts[layout_id]
        for key in (
            "id",
            "name",
            "width",
            "height",
            "primary_tileset",
            "secondary_tileset",
        ):
            if hns_layout.get(key) != mechanical.get(key):
                raise ImportError(
                    f"unclassified donor divergence: layouts/{layout_id}/{key}"
                )
        for key in ("border_filepath", "blockdata_filepath"):
            path = hns / str(hns_layout[key])
            if not path.is_file():
                raise ImportError(f"missing HnS layout binary: {hns_layout[key]}")


def validate_route28_widths(
    pkmn_world: Path, manifest: Mapping[str, Any]
) -> dict[str, str]:
    route28 = _find_layout(pkmn_world / "data/layouts/layouts.json", "LAYOUT_ROUTE28")
    header_path = pkmn_world / "src/data/tilesets/metatiles.h"
    try:
        header = header_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ImportError(
            f"cannot read tileset declarations {header_path}: {error}"
        ) from error
    declared_paths = {
        (match.group("kind"), f"gTileset_{match.group('name')}"): match.group("path")
        for match in TILESET_BLOB_RE.finditer(header)
    }
    results: dict[str, str] = {}
    for item in manifest.get("attributeFixtures", []):
        role = item.get("role")
        if role not in {"primary", "secondary"}:
            raise ImportError("Route 28 attribute fixture has an invalid role")
        expected_tileset = route28.get(f"{role}_tileset")
        if item.get("tileset") != expected_tileset:
            raise ImportError(
                f"Route 28 {role} fixture does not match LAYOUT_ROUTE28 tileset"
            )
        expected_metatiles = declared_paths.get(("Metatiles", expected_tileset))
        expected_attributes = declared_paths.get(
            ("MetatileAttributes", expected_tileset)
        )
        if (
            item.get("metatiles") != expected_metatiles
            or item.get("attributes") != expected_attributes
        ):
            raise ImportError(
                f"Route 28 fixture paths do not match tileset declarations: {expected_tileset}"
            )
        metatiles = pkmn_world / item["metatiles"]
        attributes = pkmn_world / item["attributes"]
        if (
            _sha256(metatiles) != item["metatilesSha256"]
            or _sha256(attributes) != item["attributesSha256"]
        ):
            raise ImportError(
                f"Route 28 tileset evidence hash drift: {item['tileset']}"
            )
        actual = attribute_format(metatiles.stat().st_size, attributes.stat().st_size)
        if actual != item["format"]:
            raise ImportError(
                f"wrong attribute width for {item['tileset']}: expected {item['format']}, got {actual}"
            )
        results[item["tileset"]] = actual
    required = {route28["primary_tileset"], route28["secondary_tileset"]}
    if set(results) != required or len(manifest.get("attributeFixtures", [])) != 2:
        raise ImportError(
            "Route 28 must declare both primary and secondary attribute fixtures"
        )
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
    selection: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]
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
    layout_indices = [item.get("targetLayoutIndex") for item in selection]
    if len(layout_indices) != len(set(layout_indices)):
        raise ImportError("duplicate allocation: targetLayoutIndex")
    if sorted(item.get("targetLayoutIndex") for item in selection) != list(
        range(785, 801)
    ):
        raise ImportError("layout allocations must occupy indices 785 through 800")
    if sorted(item.get("targetId") for item in groups) != list(range(75, 80)):
        raise ImportError("group allocations must occupy IDs 75 through 79")
    if sorted(item.get("targetId") for item in sections) != list(range(209, 214)):
        raise ImportError("section allocations must occupy IDs 209 through 213")
    group_names = {str(item["name"]) for item in groups}
    selected_groups = {str(item.get("targetGroup")) for item in selection}
    unknown_groups = sorted(selected_groups - group_names)
    if unknown_groups:
        raise ImportError(
            f"selected map uses unallocated targetGroup: {', '.join(unknown_groups)}"
        )
    if selected_groups != group_names:
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
        members[str(item["targetGroup"])].append(str(item["name"]))
    for allocation in ordered_allocations:
        name = str(allocation["name"])
        target_id = int(allocation["targetId"])
        if len(order) != target_id:
            raise ImportError(
                f"map group allocation drift: {name} cannot occupy ID {target_id}"
            )
        result[name] = members[name]
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
    validate_materialization_adaptations(manifest, pkmn_world, hns)

    selection = manifest.get("selection", {}).get("maps", [])
    if not isinstance(selection, list) or len(selection) != 16:
        raise ImportError("manifest selection must contain exactly 16 maps")
    _require_unique(selection, "name", "selected map")
    _require_unique(selection, "id", "selected map")
    _validate_allocations(selection, manifest)
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
    if len({item["layout"] for item in selected}) != 16:
        raise ImportError("selected closure must contain exactly 16 layouts")

    validate_content_authority(selection, layouts_by_id, hns)
    selected_names = {str(item["name"]) for item in selection}
    rules = validate_adaptations(manifest, maps_by_name, hns, selected_names)
    # Exercise every exact adaptation through the same authority resolver used by apply.
    for rule in manifest.get("adaptations", []):
        path = f"maps/{rule['source']}/{rule['path']}"
        authoritative_value(path, rule["hns"], rule["mechanical"], rules)
    effective_maps = effective_selected_maps(
        selection, maps_by_name, hns, manifest.get("adaptations", [])
    )
    validate_warp_transforms(manifest, effective_maps)
    deferred = validate_edges(
        effective_maps,
        manifest.get("retainedEdges", []),
        manifest.get("deferredEdges", []),
    )
    widths = validate_route28_widths(pkmn_world, manifest)
    definitions, input_records = referenced_symbols(hns, selection)
    validate_map_local_symbols(hns, selection, definitions)

    selected_layouts = [layouts_by_id[item["layout"]] for item in selected]
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
        layouts=tuple(item["layout"] for item in selection),
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
        "route28AttributeFormats": widths,
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
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise ImportError("unsupported or malformed import manifest")
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


def _tilesets(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    records = _exact_records(
        manifest,
        "tilesetAdaptations",
        {"role", "directory", "symbol", "secondary", "paletteCount", "authority"},
    )
    _require_unique(records, "directory", "tileset adaptation")
    for item in records:
        if (
            item["role"] not in {"primary", "secondary"}
            or not isinstance(item["secondary"], bool)
            or not isinstance(item["paletteCount"], int)
            or item["paletteCount"] <= 0
            or item["authority"] not in {"hns", "mechanical"}
        ):
            raise ImportError("invalid tileset adaptation")
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
        f"Battle Type: {item['battleType']}\n\n{item['species']}\n"
        f"Level: {item['level']}\nIVs: {item['ivs']}"
        for item in ordered
    )
    macros = "\n".join(f"#define {item['id']} {item['targetId']}" for item in ordered)
    return parties, macros, count


def validate_materialization_adaptations(
    manifest: Mapping[str, Any], pkmn_world: Path, hns: Path
) -> None:
    """Validate every content-changing materialization rule against pinned inputs."""
    selection = manifest["selection"]["maps"]
    names = {str(item["name"]) for item in selection}

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
        map_item = _json(hns / "data/maps" / name / "map.json")
        source_music = map_item.get("music")
        if isinstance(source_music, str) and source_music.startswith("MUS_HG_"):
            if source_music not in music:
                raise ImportError(f"undeclared music adaptation: {name}/{source_music}")
            used_music.add(source_music)
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
        script = (hns / "data/maps" / name / "scripts.inc").read_text(encoding="utf-8")
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
    scripts = {
        name: (hns / "data/maps" / name / "scripts.inc").read_text(encoding="utf-8")
        for name in names
    }
    for rule in substitutions:
        source, old, new, occurrences = (
            rule["source"],
            rule["old"],
            rule["new"],
            rule["occurrences"],
        )
        if (
            source not in names
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
        actual = scripts[str(source)].count(old)
        if actual != occurrences:
            raise ImportError(
                f"script substitution drift: {source}/{old!r}: expected {occurrences}, got {actual}"
            )
        scripts[str(source)] = scripts[str(source)].replace(old, new)

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

    layouts = _exact_records(
        manifest, "layoutBinaryAuthorities", {"source", "layout", "authority"}
    )
    _require_unique(layouts, "source", "layout binary authority")
    expected_layouts = {(str(item["name"]), str(item["layout"])) for item in selection}
    actual_layouts = {(str(item["source"]), str(item["layout"])) for item in layouts}
    if actual_layouts != expected_layouts or any(
        item["authority"] not in {"hns", "mechanical"} for item in layouts
    ):
        raise ImportError("layout binary authority declaration drift")

    tilesets = _tilesets(manifest)
    expected_tilesets = {
        str(layout[key])
        for layout in (
            _find_layout(pkmn_world / "data/layouts/layouts.json", str(item["layout"]))
            for item in selection
        )
        for key in ("primary_tileset", "secondary_tileset")
    }
    declared_tilesets = {f"gTileset_{item['symbol']}" for item in tilesets}
    target_tileset_header = _without_generated_section(
        (Path(__file__).parents[2] / "include/tilesets.h").read_text(encoding="utf-8"),
        "externs",
    )
    existing_tilesets = set(
        re.findall(r"\bgTileset_[A-Za-z0-9_]+\b", target_tileset_header)
    )
    if not declared_tilesets <= expected_tilesets or not expected_tilesets <= (
        declared_tilesets | existing_tilesets
    ):
        raise ImportError("tileset adaptation declaration drift")
    for item in tilesets:
        authority = pkmn_world if item["authority"] == "mechanical" else hns
        source = (
            authority / "data/tilesets" / str(item["role"]) / str(item["directory"])
        )
        palettes = list((source / "palettes").glob("*.pal"))
        if not source.is_dir() or len(palettes) != item["paletteCount"]:
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
    inventory: Inventory, closure: Closure, evidence: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "inventory": {
            key: len(getattr(inventory, key))
            for key in ("maps", "layouts", "groups", "sections", "tilesets")
        },
        "closure": asdict(closure),
        "evidence": evidence,
    }


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


def _replace_generated_section(path: Path, name: str, body: str) -> None:
    begin = f"// JOHTO IMPORT BEGIN: {name}"
    end = f"// JOHTO IMPORT END: {name}"
    text = path.read_text(encoding="utf-8")
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
    text = text.rstrip() + f"\n\n{begin}\n{body.rstrip()}\n{end}\n"
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


def _materialized_map(
    item: Mapping[str, Any], hns: Path, manifest: Mapping[str, Any]
) -> dict[str, Any]:
    name = str(item["name"])
    value = _json(hns / "data/maps" / name / "map.json")
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


def _tileset_graphics(manifest: Mapping[str, Any]) -> str:
    blocks: list[str] = ["#if HAS_JOHTO_TILESETS"]
    for item in _tilesets(manifest):
        role, directory, symbol = item["role"], item["directory"], item["symbol"]
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
        role, directory, symbol = item["role"], item["directory"], item["symbol"]
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
        symbol, secondary = item["symbol"], item["secondary"]
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


def materialize_source_tree(
    target: Path, manifest: Mapping[str, Any], pkmn_world: Path, hns: Path
) -> None:
    selection = manifest["selection"]["maps"]
    music_adaptations = _mapping(manifest, "musicAdaptations")
    script_substitutions: dict[str, list[Mapping[str, Any]]] = {}
    for rule in manifest["scriptSubstitutions"]:
        script_substitutions.setdefault(str(rule["source"]), []).append(rule)
    for item in selection:
        name = str(item["name"])
        destination = target / "data/maps" / name
        atomic_write(
            destination / "map.json",
            _dump_source(_materialized_map(item, hns, manifest)),
        )
        script = (hns / "data/maps" / name / "scripts.inc").read_text(encoding="utf-8")
        for rule in script_substitutions.get(name, []):
            actual = script.count(str(rule["old"]))
            if actual != rule["occurrences"]:
                raise ImportError(
                    f"script substitution drift: {name}/{rule['old']!r}: "
                    f"expected {rule['occurrences']}, got {actual}"
                )
            script = script.replace(str(rule["old"]), str(rule["new"]))
        for source_music, target_music in music_adaptations.items():
            script = script.replace(source_music, target_music)
        script = normalize_materialized_text(script)
        atomic_write(destination / "scripts.inc", script.encode("utf-8"))

    mechanical_layouts = {
        item["id"]: item
        for item in _json(pkmn_world / "data/layouts/layouts.json")["layouts"]
    }
    target_layouts = _json(target / "data/layouts/layouts.json")
    selected_ids = {str(item["layout"]) for item in selection}
    target_layouts["layouts"] = [
        item for item in target_layouts["layouts"] if item["id"] not in selected_ids
    ]
    for item in selection:
        layout = copy.deepcopy(mechanical_layouts[item["layout"]])
        layout.pop("layout_version", None)
        layout["format"] = "johto"
        target_layouts["layouts"].append(layout)
        name = str(item["name"])
        authority = next(
            rule["authority"]
            for rule in manifest["layoutBinaryAuthorities"]
            if rule["source"] == name
        )
        layout_source = pkmn_world if authority == "mechanical" else hns
        for filename in ("map.bin", "border.bin"):
            _copy_file(
                layout_source / "data/layouts" / name / filename,
                target / "data/layouts" / name / filename,
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

    for item in _tilesets(manifest):
        role, directory = item["role"], item["directory"]
        authority = pkmn_world if item["authority"] == "mechanical" else hns
        _copy_tree_without_generated(
            authority / "data/tilesets" / role / directory,
            target / "data/tilesets" / role / directory,
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
            for symbol in (item["symbol"] for item in _tilesets(manifest))
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

    opponents = target / "include/constants/opponents.h"
    opponent_text = opponents.read_text(encoding="utf-8")
    trainers, opponent_macros, trainer_count = _trainer_materialization(
        manifest, opponent_text
    )
    _replace_generated_section(
        target / "src/data/trainers.party", "rival trainers", trainers
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
                _dump(report_document(inventory, closure, evidence)).encode("utf-8"),
            )
            print(
                f"materialized {len(closure.maps)}-map Johto closure in "
                f"{args.target_root}; wrote validated closure report: {args.output}"
            )
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
