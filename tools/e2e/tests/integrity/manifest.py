from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from collections.abc import Iterable
from typing import Any


@dataclass(frozen=True)
class MapSectionContract:
    id: str
    value: int
    region: str
    region_value: int
    kind: str
    kind_value: int
    region_map_type: str
    region_map_type_value: int
    saved_location_code: int
    met_location_code: int
    saved_location_reverse_target: int
    met_location_reverse_target: int


@dataclass(frozen=True)
class ManifestMap:
    name: str
    group: int
    number: int
    region: str
    layout_id: str
    layout_number: int
    layout: str
    events: str
    scripts: str
    connections: str | None
    region_map_section: str
    region_map_section_value: int
    battle_type: int
    width: int
    height: int
    primary_tileset: str
    secondary_tileset: str
    layout_format: str
    section: MapSectionContract

    @property
    def map_id(self) -> tuple[int, int]:
        return self.group, self.number


@dataclass(frozen=True)
class RepresentativeMap:
    name: str
    region: str
    kind: str
    seed_vars: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class SettlementFrontage:
    entry: ManifestMap
    x: int
    y: int


REPRESENTATIVE_REGION_BY_MAP_TYPE = {
    "REGION_MAP_HOENN": "hoenn",
    "REGION_MAP_KANTO": "kanto",
    "REGION_MAP_SEVII123": "sevii123",
    "REGION_MAP_SEVII45": "sevii45",
    "REGION_MAP_SEVII67": "sevii67",
}

INTERIOR_PRIMARY_TILESETS = {
    "gTileset_Building",
    "gTileset_BuildingFrlg",
    "gTileset_Johto_Building",
}

INTERIOR_SECONDARY_TILESETS = {
    "gTileset_PortIndoor",
}

CAVE_SECONDARY_TILESETS = {
    "gTileset_Cave",
    "gTileset_Cave_Default",
    "gTileset_Cave_DragonsDen",
    "gTileset_Cave_Frlg",
    "gTileset_Cave_Gray",
    "gTileset_Cave_Ice",
    "gTileset_RuinsOfAlph_B1F",
    "gTileset_SeafoamIslands",
    "gTileset_WhirlIslands",
}

EXTERIOR_PRIMARY_TILESETS = {
    "gTileset_General",
    "gTileset_General_Frlg",
    "gTileset_Johto_General",
    "gTileset_Johto_NorthEast",
    "gTileset_Johto_NorthWest",
}

STARTING_TOWNS = ("LittlerootTown", "PalletTown_Frlg", "NewBarkTown")
SEVII_ISLAND_SETTLEMENTS = tuple(
    f"{name}Island_Frlg"
    for name in ("One", "Two", "Three", "Four", "Five", "Six", "Seven")
)


def integrity_manifest_path() -> Path:
    return Path(
        os.environ.get(
            "INTEGRITY_MANIFEST",
            "build/generated/allregions/current/integrity-manifest.json",
        )
    )


def _required(entry: dict[str, Any], key: str, index: int) -> Any:
    try:
        return entry[key]
    except KeyError as error:
        raise ValueError(
            f"manifest maps[{index}] is missing required field {key!r}"
        ) from error


def _required_with_aliases(
    entry: dict[str, Any], key: str, aliases: tuple[str, ...], index: int
) -> Any:
    present = [candidate for candidate in (key, *aliases) if candidate in entry]
    if not present:
        raise ValueError(f"manifest maps[{index}] is missing required field {key!r}")
    value = entry[present[0]]
    if any(entry[candidate] != value for candidate in present[1:]):
        raise ValueError(
            f"manifest maps[{index}] has conflicting values for {key!r}: {present}"
        )
    return value


def load_manifest_maps(path: Path) -> list[ManifestMap]:
    try:
        document = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"Integrity manifest does not exist: {path}; build the all-regions "
            "debug ROM and its integrity manifest first"
        ) from error
    if not isinstance(document, dict):
        raise ValueError("integrity manifest root must be an object")
    if document.get("schemaVersion") not in (1, 2, 3, 4):
        raise ValueError(
            "integrity manifest schemaVersion must be 1, 2, 3, or 4, got "
            f"{document.get('schemaVersion')!r}"
        )
    metadata_entries = document.get("mapSectionMetadata")
    if not isinstance(metadata_entries, list) or not metadata_entries:
        raise ValueError(
            "integrity manifest mapSectionMetadata must be a non-empty array"
        )
    codecs = document.get("codecs")
    if not isinstance(codecs, dict):
        raise ValueError("integrity manifest codecs must be an object")
    codec_names = (
        "sectionToSavedLocation",
        "sectionToMetLocation",
        "savedLocationToSection",
        "metLocationToSection",
    )
    for name in codec_names:
        if not isinstance(codecs.get(name), list):
            raise ValueError(f"integrity manifest codecs.{name} must be an array")

    sections: dict[int, MapSectionContract] = {}
    section_ids: set[str] = set()
    for index, raw_section in enumerate(metadata_entries):
        if not isinstance(raw_section, dict):
            raise ValueError(f"manifest mapSectionMetadata[{index}] must be an object")
        required = {
            name: _required(raw_section, name, index)
            for name in (
                "id",
                "value",
                "region",
                "regionValue",
                "kind",
                "kindValue",
                "regionMapType",
                "regionMapTypeValue",
            )
        }
        for name in ("id", "region", "kind", "regionMapType"):
            if not isinstance(required[name], str) or not required[name]:
                raise ValueError(
                    f"manifest mapSectionMetadata[{index}].{name} must be a "
                    "non-empty string"
                )
        for name in ("value", "regionValue", "kindValue", "regionMapTypeValue"):
            value = required[name]
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= 0xFFFF
            ):
                raise ValueError(
                    f"manifest mapSectionMetadata[{index}].{name} must be an "
                    "unsigned integer"
                )
        section_value = required["value"]
        if section_value != index:
            raise ValueError(
                "integrity manifest mapSectionMetadata must be ordered by value: "
                f"index={index}, value={section_value}"
            )
        if required["id"] in section_ids:
            raise ValueError(
                f"integrity manifest repeats map-section id {required['id']!r}"
            )
        section_ids.add(required["id"])
        section_to_saved = codecs["sectionToSavedLocation"]
        section_to_met = codecs["sectionToMetLocation"]
        if section_value >= len(section_to_saved) or section_value >= len(
            section_to_met
        ):
            raise ValueError(
                f"integrity manifest codecs do not cover map section {section_value}"
            )
        saved_code = section_to_saved[section_value]
        met_code = section_to_met[section_value]
        for name, code in (
            ("sectionToSavedLocation", saved_code),
            ("sectionToMetLocation", met_code),
        ):
            if (
                isinstance(code, bool)
                or not isinstance(code, int)
                or not -1 <= code <= 0xFF
            ):
                raise ValueError(
                    f"integrity manifest codecs.{name}[{section_value}] is invalid"
                )

        def reverse_target(name: str, code: int) -> int:
            if code < 0:
                return -1
            reverse = codecs[name]
            if code >= len(reverse):
                raise ValueError(
                    f"integrity manifest codecs.{name} does not cover code {code}"
                )
            target = reverse[code]
            if (
                isinstance(target, bool)
                or not isinstance(target, int)
                or not -1 <= target <= 0xFFFF
            ):
                raise ValueError(f"integrity manifest codecs.{name}[{code}] is invalid")
            return target

        sections[section_value] = MapSectionContract(
            id=required["id"],
            value=section_value,
            region=required["region"],
            region_value=required["regionValue"],
            kind=required["kind"],
            kind_value=required["kindValue"],
            region_map_type=required["regionMapType"],
            region_map_type_value=required["regionMapTypeValue"],
            saved_location_code=saved_code,
            met_location_code=met_code,
            saved_location_reverse_target=reverse_target(
                "savedLocationToSection", saved_code
            ),
            met_location_reverse_target=reverse_target(
                "metLocationToSection", met_code
            ),
        )
    entries = document.get("maps")
    if not isinstance(entries, list) or not entries:
        raise ValueError("integrity manifest maps must be a non-empty array")
    layout_entries = document.get("layouts")
    if not isinstance(layout_entries, list) or not layout_entries:
        raise ValueError("integrity manifest layouts must be a non-empty array")
    layouts: dict[str, dict[str, Any]] = {}
    for index, layout in enumerate(layout_entries):
        if not isinstance(layout, dict):
            raise ValueError(f"manifest layouts[{index}] must be an object")
        layout_id = _required(layout, "id", index)
        if not isinstance(layout_id, str) or not layout_id:
            raise ValueError(f"manifest layouts[{index}].id must be a non-empty string")
        if layout_id in layouts:
            raise ValueError(f"integrity manifest repeats layout id {layout_id!r}")
        layouts[layout_id] = layout

    maps: list[ManifestMap] = []
    seen_ids: set[tuple[int, int]] = set()
    seen_names: set[str] = set()
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            raise ValueError(f"manifest maps[{index}] must be an object")
        name = _required(raw_entry, "name", index)
        group = _required_with_aliases(raw_entry, "group", ("mapGroup",), index)
        number = _required_with_aliases(
            raw_entry, "number", ("mapNum", "mapNumber"), index
        )
        region = _required(raw_entry, "region", index)
        layout_id = _required(raw_entry, "layoutId", index)
        layout_name = _required(raw_entry, "mapLayout", index)
        events = _required(raw_entry, "mapEvents", index)
        scripts = _required(raw_entry, "mapScripts", index)
        connections = _required(raw_entry, "mapConnections", index)
        region_map_section = _required(raw_entry, "regionMapSection", index)
        region_map_section_value = _required(raw_entry, "regionMapSectionValue", index)
        battle_type = _required(raw_entry, "battleType", index)
        if not isinstance(name, str) or not name:
            raise ValueError(f"manifest maps[{index}].name must be a non-empty string")
        if not isinstance(region, str) or not region:
            raise ValueError(
                f"manifest maps[{index}].region must be a non-empty string"
            )
        for field, value in (
            ("layoutId", layout_id),
            ("mapLayout", layout_name),
            ("mapEvents", events),
            ("mapScripts", scripts),
            ("regionMapSection", region_map_section),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"manifest maps[{index}].{field} must be a non-empty string"
                )
        if connections is not None and (
            not isinstance(connections, str) or not connections
        ):
            raise ValueError(
                f"manifest maps[{index}].mapConnections must be null or a "
                "non-empty string"
            )
        for field, value, upper in (
            ("regionMapSectionValue", region_map_section_value, 0xFFFF),
            ("battleType", battle_type, 0xFF),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= upper
            ):
                raise ValueError(
                    f"manifest maps[{index}].{field} must be an unsigned integer"
                )
        if (
            isinstance(group, bool)
            or not isinstance(group, int)
            or not 0 <= group <= 0xFFFF
        ):
            raise ValueError(f"manifest maps[{index}].group must be a u16 integer")
        if (
            isinstance(number, bool)
            or not isinstance(number, int)
            or not 0 <= number <= 0xFFFF
        ):
            raise ValueError(f"manifest maps[{index}].number must be a u16 integer")
        map_id = (group, number)
        if name in seen_names:
            raise ValueError(f"integrity manifest repeats map name {name!r}")
        if map_id in seen_ids:
            raise ValueError(f"integrity manifest repeats map id {map_id}")
        seen_names.add(name)
        seen_ids.add(map_id)
        try:
            layout = layouts[layout_id]
        except KeyError as error:
            raise ValueError(
                f"manifest maps[{index}] references unknown layout {layout_id!r}"
            ) from error
        if layout.get("name") != layout_name:
            raise ValueError(
                f"manifest maps[{index}] layout name does not match {layout_id!r}"
            )
        try:
            section = sections[region_map_section_value]
        except KeyError as error:
            raise ValueError(
                f"manifest maps[{index}] references unknown map-section value "
                f"{region_map_section_value}"
            ) from error
        if section.id != region_map_section:
            raise ValueError(
                f"manifest maps[{index}] map-section id does not match value "
                f"{region_map_section_value}"
            )
        if (region == "REGION_JOHTO") != (section.region == "REGION_JOHTO"):
            raise ValueError(
                f"manifest maps[{index}] has one-sided Johto ownership: "
                f"map region {region!r}, map-section region {section.region!r}"
            )
        layout_number = _required(layout, "number", index)
        width = _required(layout, "width", index)
        height = _required(layout, "height", index)
        primary_tileset = _required(layout, "primaryTileset", index)
        secondary_tileset = _required(layout, "secondaryTileset", index)
        layout_format = _required(layout, "format", index)
        for field, value in (
            ("number", layout_number),
            ("width", width),
            ("height", height),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(
                    f"manifest layout {layout_id!r}.{field} must be a positive integer"
                )
        for field, value in (
            ("primaryTileset", primary_tileset),
            ("secondaryTileset", secondary_tileset),
            ("format", layout_format),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"manifest layout {layout_id!r}.{field} must be a non-empty string"
                )
        maps.append(
            ManifestMap(
                name=name,
                group=group,
                number=number,
                region=region,
                layout_id=layout_id,
                layout_number=layout_number,
                layout=layout_name,
                events=events,
                scripts=scripts,
                connections=connections,
                region_map_section=region_map_section,
                region_map_section_value=region_map_section_value,
                battle_type=battle_type,
                width=width,
                height=height,
                primary_tileset=primary_tileset,
                secondary_tileset=secondary_tileset,
                layout_format=layout_format,
                section=section,
            )
        )
    return maps


def _representative_region(entry: ManifestMap) -> str:
    # Johto content temporarily uses Hoenn's RegionMapType for presentation.
    # Its manifest content origin remains authoritative for residency coverage.
    if entry.region == "REGION_JOHTO":
        return "johto"
    try:
        return REPRESENTATIVE_REGION_BY_MAP_TYPE[entry.section.region_map_type]
    except KeyError as error:
        raise ValueError(
            f"representative {entry.name!r} has unsupported manifest geography "
            f"{entry.section.region_map_type!r}"
        ) from error


def _representative_kind(entry: ManifestMap) -> str:
    if entry.secondary_tileset in CAVE_SECONDARY_TILESETS:
        return "cave"
    if entry.secondary_tileset in INTERIOR_SECONDARY_TILESETS:
        return "interior"
    if entry.primary_tileset in INTERIOR_PRIMARY_TILESETS:
        return "interior"
    if entry.primary_tileset in EXTERIOR_PRIMARY_TILESETS:
        return "exterior"
    raise ValueError(
        f"representative {entry.name!r} has unsupported manifest layout "
        f"{entry.primary_tileset!r}/{entry.secondary_tileset!r}"
    )


def load_settlement_frontages(
    manifest_maps: Iterable[ManifestMap], maps_root: Path = Path("data/maps")
) -> list[SettlementFrontage]:
    maps = list(manifest_maps)
    maps_by_name = {entry.name: entry for entry in maps}
    selected: dict[str, SettlementFrontage] = {}

    for entry in maps:
        if (
            entry.primary_tileset in INTERIOR_PRIMARY_TILESETS
            or entry.secondary_tileset in INTERIOR_SECONDARY_TILESETS
            or entry.secondary_tileset in CAVE_SECONDARY_TILESETS
        ):
            continue
        document = json.loads((maps_root / entry.name / "map.json").read_text())
        center_warps = [
            warp
            for warp in document.get("warp_events", [])
            if isinstance(warp.get("dest_map"), str)
            and any(
                marker in warp["dest_map"]
                for marker in ("_POKEMON_CENTER", "_POKECENTER")
            )
        ]
        if not center_warps:
            continue
        warp = min(
            center_warps,
            key=lambda item: (item.get("y", -1), item.get("x", -1)),
        )
        x = warp.get("x")
        y = warp.get("y")
        if (
            isinstance(x, bool)
            or not isinstance(x, int)
            or isinstance(y, bool)
            or not isinstance(y, int)
            or not 0 <= x < entry.width
            or not 0 <= y + 1 < entry.height
        ):
            raise ValueError(f"{entry.name} has an invalid Pokemon Center frontage")
        selected[entry.name] = SettlementFrontage(entry=entry, x=x, y=y + 1)

    required_names = (*STARTING_TOWNS, *SEVII_ISLAND_SETTLEMENTS)
    missing = sorted(name for name in required_names if name not in maps_by_name)
    if missing:
        raise ValueError(f"settlement frontage maps absent from manifest: {missing}")
    for name in STARTING_TOWNS:
        entry = maps_by_name[name]
        selected[name] = SettlementFrontage(
            entry=entry,
            x=entry.width // 2,
            y=entry.height // 2,
        )
    missing_frontages = sorted(
        name for name in SEVII_ISLAND_SETTLEMENTS if name not in selected
    )
    if missing_frontages:
        raise ValueError(
            f"Sevii settlements lack Pokemon Center frontages: {missing_frontages}"
        )

    return [selected[entry.name] for entry in maps if entry.name in selected]


def _validate_representative_coverage(
    representatives: list[RepresentativeMap], manifest_maps: Iterable[ManifestMap]
) -> None:
    maps_by_name = {entry.name: entry for entry in manifest_maps}
    missing = sorted(
        representative.name
        for representative in representatives
        if representative.name not in maps_by_name
    )
    if missing:
        raise ValueError(f"representatives absent from integrity manifest: {missing}")

    actual_regions: set[str] = set()
    actual_kinds: set[str] = set()
    for representative in representatives:
        entry = maps_by_name[representative.name]
        actual_region = _representative_region(entry)
        actual_kind = _representative_kind(entry)
        if representative.region != actual_region:
            raise ValueError(
                f"representative {representative.name!r} declares region "
                f"{representative.region!r}, but manifest geography is "
                f"{actual_region!r} ({entry.section.region_map_type})"
            )
        if representative.kind != actual_kind:
            raise ValueError(
                f"representative {representative.name!r} declares kind "
                f"{representative.kind!r}, but manifest layout is "
                f"{actual_kind!r} ({entry.primary_tileset}/"
                f"{entry.secondary_tileset})"
            )
        actual_regions.add(actual_region)
        actual_kinds.add(actual_kind)

    required_regions = {
        "hoenn",
        "kanto",
        "sevii123",
        "sevii45",
        "sevii67",
        "johto",
    }
    if not required_regions <= actual_regions:
        raise ValueError(
            "representatives are missing required manifest region classes: "
            f"{sorted(required_regions - actual_regions)}"
        )
    required_kinds = {"exterior", "interior", "cave"}
    if not required_kinds <= actual_kinds:
        raise ValueError(
            "representatives are missing required manifest map kinds: "
            f"{sorted(required_kinds - actual_kinds)}"
        )


def load_representatives(
    path: Path, manifest_maps: Iterable[ManifestMap] | None = None
) -> list[RepresentativeMap]:
    document = json.loads(path.read_text())
    if document.get("schemaVersion") != 1:
        raise ValueError("representative map schemaVersion must be 1")
    entries = document.get("representatives")
    if not isinstance(entries, list) or not entries:
        raise ValueError("representatives must be a non-empty array")
    representatives: list[RepresentativeMap] = []
    for index, entry in enumerate(entries):
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("name"), str)
            or not entry["name"]
        ):
            raise ValueError(
                f"representatives[{index}].name must be a non-empty string"
            )
        if not isinstance(entry.get("region"), str) or not entry["region"]:
            raise ValueError(
                f"representatives[{index}].region must be a non-empty string"
            )
        if not isinstance(entry.get("kind"), str) or not entry["kind"]:
            raise ValueError(
                f"representatives[{index}].kind must be a non-empty string"
            )
        seed_vars = entry.get("seedVars", [])
        if not isinstance(seed_vars, list):
            raise ValueError(f"representatives[{index}].seedVars must be an array")
        parsed_vars: list[tuple[int, int]] = []
        for var_index, seed_var in enumerate(seed_vars):
            if not isinstance(seed_var, dict):
                raise ValueError(
                    f"representatives[{index}].seedVars[{var_index}] must be an object"
                )
            var_id = seed_var.get("id")
            value = seed_var.get("value")
            if (
                isinstance(var_id, bool)
                or not isinstance(var_id, int)
                or not 0x4000 <= var_id <= 0x40FF
            ):
                raise ValueError(
                    f"representatives[{index}].seedVars[{var_index}].id "
                    "must be a saved variable id"
                )
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= 0xFFFF
            ):
                raise ValueError(
                    f"representatives[{index}].seedVars[{var_index}].value must be u16"
                )
            parsed_vars.append((var_id, value))
        representatives.append(
            RepresentativeMap(
                name=entry["name"],
                region=entry["region"],
                kind=entry["kind"],
                seed_vars=tuple(parsed_vars),
            )
        )
    names = [representative.name for representative in representatives]
    if len(names) != len(set(names)):
        raise ValueError("representative map names must be unique")
    if manifest_maps is not None:
        _validate_representative_coverage(representatives, manifest_maps)
    return representatives
