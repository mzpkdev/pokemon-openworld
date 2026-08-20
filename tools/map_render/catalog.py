"""Discover exterior maps and describe their rendered frontend assets."""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import json
from pathlib import Path, PurePosixPath
from typing import Mapping


CATALOG_SCHEMA_VERSION = 2
PIXELS_PER_METATILE = 16
OVERVIEW_SCALE = 4


class MapRenderError(ValueError):
    """Report an invalid source tree or region configuration."""


@dataclass(frozen=True)
class RenderTarget:
    """One exterior map selected for a regional catalog."""

    region_id: str
    region_label: str
    category: str
    group: str
    name: str
    map_data: Mapping[str, object]
    layout: Mapping[str, object]
    world: Mapping[str, object]

    @property
    def image_path(self) -> str:
        return f"maps/{self.region_id}/{self.category}/{self.name}.png"

    @property
    def overview_image_path(self) -> str:
        return f"overviews/{self.region_id}/{self.category}/{self.name}.png"


@dataclass(frozen=True)
class Discovery:
    """Validated region assignments and source-map indexes."""

    config: Mapping[str, object]
    targets: tuple[RenderTarget, ...]
    map_names_by_id: Mapping[str, str]


def asset_output_paths(targets: tuple[RenderTarget, ...]) -> tuple[str, ...]:
    """Validate and return the complete, distinct relative asset path set."""

    owners: dict[str, str] = {}
    for target in targets:
        for path in (target.image_path, target.overview_image_path):
            parsed = PurePosixPath(path)
            if parsed.is_absolute() or ".." in parsed.parts or "\\" in path or not path:
                raise MapRenderError(f"unsafe catalog asset path: {path!r}")
            owner = owners.get(path)
            if owner is not None:
                raise MapRenderError(
                    f"duplicate catalog asset path {path!r}: {owner} and {target.name}"
                )
            owners[path] = target.name
    return tuple(owners)


def default_config_path() -> Path:
    return Path(__file__).with_name("regions.json")


def default_schema_path() -> Path:
    return Path(__file__).with_name("catalog.schema.json")


def load_config(path: Path | None = None) -> Mapping[str, object]:
    config_path = path or default_config_path()
    try:
        config = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise MapRenderError(
            f"cannot load region config {config_path}: {error}"
        ) from error
    if not isinstance(config, dict):
        raise MapRenderError(f"region config {config_path} must be an object")
    if config.get("schemaVersion") != 1:
        raise MapRenderError(f"unsupported region config schema in {config_path}")
    if not isinstance(config.get("exteriorMapTypes"), list):
        raise MapRenderError("region config requires exteriorMapTypes")
    if not all(isinstance(value, str) for value in config["exteriorMapTypes"]):
        raise MapRenderError("region config exteriorMapTypes must contain strings")
    regions = config.get("regions")
    if not isinstance(regions, list) or not regions:
        raise MapRenderError("region config requires at least one region")
    if not all(isinstance(region, dict) for region in regions):
        raise MapRenderError("region config regions must contain objects")
    return config


def _load_source_maps(root: Path) -> tuple[dict[str, dict], dict[str, str]]:
    maps: dict[str, dict] = {}
    names_by_id: dict[str, str] = {}
    for map_path in sorted(root.glob("data/maps/*/map.json")):
        map_data = json.loads(map_path.read_text())
        name = map_path.parent.name
        map_id = map_data.get("id")
        if not isinstance(map_id, str):
            raise MapRenderError(f"{map_path}: map id is missing")
        if map_id in names_by_id:
            raise MapRenderError(
                f"duplicate map id {map_id}: {names_by_id[map_id]} and {name}"
            )
        maps[name] = map_data
        names_by_id[map_id] = name
    return maps, names_by_id


def _matches(rule: Mapping[str, object], group: str, name: str) -> bool:
    if rule.get("group") != group:
        return False
    patterns = rule.get("match", ["*"])
    if isinstance(patterns, str):
        patterns = [patterns]
    if not isinstance(patterns, list) or not all(
        isinstance(pattern, str) for pattern in patterns
    ):
        raise MapRenderError(f"invalid match patterns for {group}")
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def _automatic_category(map_type: str) -> str:
    if map_type in {"MAP_TYPE_TOWN", "MAP_TYPE_CITY"}:
        return "towns"
    if map_type == "MAP_TYPE_UNDERWATER":
        return "underwater"
    return "routes"


def discover(root: Path, config: Mapping[str, object]) -> Discovery:
    """Assign every configured exterior map to exactly one region."""

    root = root.resolve()
    map_groups = json.loads((root / "data/maps/map_groups.json").read_text())
    group_order = map_groups.get("group_order")
    if not isinstance(group_order, list):
        raise MapRenderError("data/maps/map_groups.json lacks group_order")
    layouts = {
        layout["id"]: layout
        for layout in json.loads((root / "data/layouts/layouts.json").read_text())[
            "layouts"
        ]
    }
    maps, names_by_id = _load_source_maps(root)
    exterior_types = set(config["exteriorMapTypes"])
    regions = config["regions"]
    known_region_ids: set[str] = set()
    for region in regions:
        region_id = region.get("id")
        if not isinstance(region_id, str) or not region_id:
            raise MapRenderError("every region requires an id")
        if region_id in known_region_ids:
            raise MapRenderError(f"duplicate region id: {region_id}")
        if not isinstance(region.get("label"), str) or not region["label"]:
            raise MapRenderError(f"region {region_id} requires a label")
        known_region_ids.add(region_id)

    targets: list[RenderTarget] = []
    map_overrides = config.get("mapOverrides", {})
    if not isinstance(map_overrides, dict):
        raise MapRenderError("region config mapOverrides must be an object")
    for group in group_order:
        if group not in map_groups:
            raise MapRenderError(f"unknown map group in group_order: {group}")
        for name in map_groups[group]:
            map_data = maps.get(name)
            if map_data is None:
                raise MapRenderError(f"map group references missing map: {name}")
            map_type = map_data.get("map_type")
            if map_type not in exterior_types:
                continue
            assignments = []
            for region in regions:
                rules = region.get("rules")
                if not isinstance(rules, list):
                    raise MapRenderError(f"region {region['id']} requires rules")
                if not all(isinstance(candidate, dict) for candidate in rules):
                    raise MapRenderError(f"region {region['id']} rules must be objects")
                rule = next(
                    (
                        candidate
                        for candidate in rules
                        if _matches(candidate, group, name)
                    ),
                    None,
                )
                if rule is not None:
                    assignments.append((region, rule))
            if not assignments:
                raise MapRenderError(f"unassigned exterior map: {group}:{name}")
            if len(assignments) > 1:
                assigned_regions = ", ".join(region["id"] for region, _ in assignments)
                raise MapRenderError(
                    f"exterior map {name} belongs to multiple regions: {assigned_regions}"
                )
            region, rule = assignments[0]
            category = rule.get("category", "auto")
            if category == "auto":
                category = _automatic_category(map_type)
            if map_type == "MAP_TYPE_UNDERWATER":
                category = "underwater"
            if not isinstance(category, str) or not category:
                raise MapRenderError(f"invalid category for {name}")
            layout_id = map_data.get("layout")
            layout = layouts.get(layout_id)
            if layout is None:
                raise MapRenderError(f"{name}: unknown layout {layout_id}")
            override = map_overrides.get(name, {})
            if not isinstance(override, dict):
                raise MapRenderError(f"mapOverrides.{name} must be an object")
            unknown_override_fields = sorted(
                set(override) - {"layer", "defaultVisible", "variantGroup", "variant"}
            )
            if unknown_override_fields:
                raise MapRenderError(
                    f"mapOverrides.{name} has unknown fields: "
                    f"{', '.join(unknown_override_fields)}"
                )
            world = {
                "layer": (
                    "underwater" if map_type == "MAP_TYPE_UNDERWATER" else "surface"
                ),
                "defaultVisible": category not in {"prototypes", "technical"},
                "variantGroup": None,
                "variant": None,
                **override,
            }
            if world["layer"] not in {"surface", "underwater", "generated"}:
                raise MapRenderError(f"mapOverrides.{name}.layer is invalid")
            if not isinstance(world["defaultVisible"], bool):
                raise MapRenderError(
                    f"mapOverrides.{name}.defaultVisible must be boolean"
                )
            if not all(
                value is None or isinstance(value, str)
                for value in (world["variantGroup"], world["variant"])
            ):
                raise MapRenderError(f"mapOverrides.{name} variant values are invalid")
            if (world["variantGroup"] is None) != (world["variant"] is None):
                raise MapRenderError(
                    f"mapOverrides.{name} requires both variantGroup and variant"
                )
            targets.append(
                RenderTarget(
                    region_id=region["id"],
                    region_label=region["label"],
                    category=category,
                    group=group,
                    name=name,
                    map_data=map_data,
                    layout=layout,
                    world=world,
                )
            )

    targets.sort(key=lambda target: (target.region_id, target.category, target.name))
    unknown_overrides = sorted(set(map_overrides) - {target.name for target in targets})
    if unknown_overrides:
        raise MapRenderError(
            f"mapOverrides reference non-exterior maps: {', '.join(unknown_overrides)}"
        )
    return Discovery(config=config, targets=tuple(targets), map_names_by_id=names_by_id)


def _destination(map_id: object, names_by_id: Mapping[str, str]) -> dict[str, object]:
    return {
        "destinationMapId": map_id,
        "destinationMap": names_by_id.get(map_id) if isinstance(map_id, str) else None,
    }


def map_entry(
    target: RenderTarget,
    names_by_id: Mapping[str, str],
    image_sha256: str,
    overview_sha256: str,
) -> dict[str, object]:
    """Build one frontend-facing map record."""

    map_data = target.map_data
    layout = target.layout
    width = layout["width"]
    height = layout["height"]
    connections = [
        {
            "direction": connection["direction"],
            "offsetMetatiles": connection["offset"],
            **_destination(connection["map"], names_by_id),
        }
        for connection in map_data.get("connections") or []
    ]
    warps = [
        {
            "warpId": str(warp_id),
            "xMetatiles": warp["x"],
            "yMetatiles": warp["y"],
            "elevation": warp["elevation"],
            "destinationWarpId": warp["dest_warp_id"],
            **_destination(warp["dest_map"], names_by_id),
        }
        for warp_id, warp in enumerate(map_data.get("warp_events") or [])
    ]
    return {
        "name": target.name,
        "id": map_data["id"],
        "region": target.region_id,
        "category": target.category,
        "sourceGroup": target.group,
        "sourceRegion": map_data.get("region"),
        "mapType": map_data.get("map_type"),
        "mapSection": map_data.get("region_map_section"),
        "image": {
            "path": target.image_path,
            "sha256": image_sha256,
            "widthPixels": width * PIXELS_PER_METATILE,
            "heightPixels": height * PIXELS_PER_METATILE,
            "overview": {
                "path": target.overview_image_path,
                "sha256": overview_sha256,
                "widthPixels": width * PIXELS_PER_METATILE // OVERVIEW_SCALE,
                "heightPixels": height * PIXELS_PER_METATILE // OVERVIEW_SCALE,
            },
        },
        "layout": {
            "id": layout["id"],
            "format": layout.get("format", "emerald"),
            "widthMetatiles": width,
            "heightMetatiles": height,
            "primaryTileset": layout["primary_tileset"],
            "secondaryTileset": layout["secondary_tileset"],
        },
        "world": dict(target.world),
        "presentation": {
            "music": map_data.get("music"),
            "weather": map_data.get("weather"),
            "showMapName": map_data.get("show_map_name"),
            "requiresFlash": map_data.get("requires_flash"),
        },
        "connections": connections,
        "warps": warps,
    }


def build_catalog(
    discovery: Discovery,
    targets: tuple[RenderTarget, ...],
    image_hashes: Mapping[str, str],
    overview_hashes: Mapping[str, str],
    *,
    source_revision: str,
    working_tree_dirty: bool,
) -> dict[str, object]:
    """Build the versioned catalog consumed by a future map browser."""

    entries = [
        map_entry(
            target,
            discovery.map_names_by_id,
            image_hashes[target.name],
            overview_hashes[target.name],
        )
        for target in targets
    ]
    selected_region_ids = {target.region_id for target in targets}
    regions = []
    for configured_region in discovery.config["regions"]:
        region_id = configured_region["id"]
        if region_id not in selected_region_ids:
            continue
        map_names = [entry["name"] for entry in entries if entry["region"] == region_id]
        regions.append(
            {
                "id": region_id,
                "label": configured_region["label"],
                "mapCount": len(map_names),
                "maps": map_names,
            }
        )
    return {
        "$schema": "catalog.schema.json",
        "schemaVersion": CATALOG_SCHEMA_VERSION,
        "format": "pokemon-openworld-exterior-map-catalog",
        "pixelsPerMetatile": PIXELS_PER_METATILE,
        "source": {
            "revision": source_revision,
            "workingTreeDirty": working_tree_dirty,
        },
        "regions": regions,
        "maps": entries,
    }
