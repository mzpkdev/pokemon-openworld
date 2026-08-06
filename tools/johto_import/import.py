#!/usr/bin/env python3
"""Deterministically inventory and validate the reviewed Johto donor slice.

This tool never writes to either donor.  ``--apply`` only writes a validated,
deterministic closure report to the explicitly supplied output path.
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


def build_closure(
    manifest: Mapping[str, Any], pkmn_world: Path, hns: Path
) -> tuple[Inventory, Closure, dict[str, Any]]:
    mechanical_pin = _pin(manifest, "mechanicalDonor", "PKMN-World")
    content_pin = _pin(manifest, "contentAuthority", "Pokémon Heart & Soul")
    mechanical_records = authenticate_donor(pkmn_world, mechanical_pin)
    content_records = authenticate_donor(hns, content_pin)
    inventory, maps_by_name, layouts_by_id = discover_inventory(pkmn_world)
    validate_expected_inventory(inventory, manifest.get("expectedInventory", {}))

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
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


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
        help="atomically write the validated closure report",
    )
    parser.add_argument("--pkmn-world", type=Path, required=True)
    parser.add_argument("--hns", type=Path, required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("import_manifest.json"),
    )
    parser.add_argument("--output", type=Path, help="report file required by --apply")
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
            atomic_write(
                args.output,
                _dump(report_document(inventory, closure, evidence)).encode("utf-8"),
            )
            print(f"wrote validated closure report: {args.output}")
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
