"""Compile authenticated source state and authored policy into desired outputs."""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .bindings import load_binding_index
from .descriptor import (
    GENERATED_AUTHORITY_CONTRACT,
    MATERIALIZED_CAPABILITIES,
    MATERIALIZATION_STRIP_EVENT_KINDS,
    PortDescriptor,
    TRAINER_DISPLAY_RE,
)
from .donors import authenticated_donor_snapshot
from .errors import ContentPortError
from .model import DonorPin, ResourceKey
from .ownership import OwnershipManifest, safe_repo_path, verify_desired_claims
from .renderers import RenderContext, RenderUnit, render_units
from .sources import PortSourceState, resolve_port_sources
from .trainer_materialization import require_materialization_exact_cover


_DEFINE_RE = re.compile(
    r"^#define\s+([A-Z][A-Z0-9_]+)\s+(0x[0-9A-Fa-f]+|\d+)", re.MULTILINE
)
_BYTE_IDENTICAL_TRAINER_PICS = MappingProxyType(
    {
        "Twins FRLG": "Twins",
        "Youngster FRLG": "Youngster",
    }
)
_REVIEWED_TRAINER_OBJECT_OVERLAYS = MappingProxyType(
    {
        "SSAqua_RoomNW/1/SSAqua_RoomNW_EventScript_Edward": {"x": 2, "y": 6},
        "SSAqua_RoomNW/2/SSAqua_RoomNW_EventScript_Corey": {"x": 4, "y": 3},
    }
)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw(child) for child in value]
    return copy.deepcopy(value)


def _rendered_materialization_scope(
    descriptor: PortDescriptor, state: PortSourceState
) -> Mapping[str, tuple[str, ...]]:
    authority = state.trainer_materialization
    if authority is None:
        return MappingProxyType({})
    placement_maps = {
        placement.identity: placement.map_name
        for placement in state.trainer_inventory.placements
    }
    rendered_maps = {
        name
        for name, ownership in descriptor.map_ownership.items()
        if ownership == "rendered"
    }
    return MappingProxyType(
        {
            record.identity: tuple(
                placement
                for placement in record.placements
                if placement_maps.get(placement) in rendered_maps
            )
            for record in authority.identities
            if any(
                placement_maps.get(placement) in rendered_maps
                for placement in record.placements
            )
        }
    )


def _require_rendered_materialization_exact_cover(
    descriptor: PortDescriptor,
    state: PortSourceState,
    observed: Mapping[str, Iterable[str]],
    *,
    owner: str,
) -> None:
    authority = state.trainer_materialization
    if authority is None:
        return
    expected = _rendered_materialization_scope(descriptor, state)
    full = {record.identity: record.placements for record in authority.identities}
    if dict(expected) == full:
        require_materialization_exact_cover(authority, observed, owner=owner)
        return
    if set(observed) != set(expected):
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        raise ContentPortError(
            f"{owner}: identities differ from rendered materialization scope; "
            f"missing={missing[:1]}, extra={extra[:1]}"
        )
    for identity, expected_placements in expected.items():
        actual = tuple(observed[identity])
        if len(actual) != len(set(actual)):
            raise ContentPortError(
                f"{owner}: {identity} has duplicate observed placements"
            )
        if set(actual) != set(expected_placements):
            missing = sorted(set(expected_placements) - set(actual))
            extra = sorted(set(actual) - set(expected_placements))
            raise ContentPortError(
                f"{owner}: {identity} differs from rendered materialization scope; "
                f"missing={missing[:1]}, extra={extra[:1]}"
            )


def _port_name(descriptor: PortDescriptor) -> str:
    return descriptor.path.parent.name


def _with_snapshot_donors(
    descriptor: PortDescriptor, snapshots: tuple[DonorPin, ...]
) -> PortDescriptor:
    snapshot_by_name = {pin.name: pin for pin in snapshots}
    expected_names = {pin.name for pin in descriptor.donors}
    if set(snapshot_by_name) != expected_names:
        raise ContentPortError("authenticated donor snapshot does not match descriptor")
    return replace(
        descriptor,
        donors=tuple(snapshot_by_name[pin.name] for pin in descriptor.donors),
        donors_by_role=MappingProxyType(
            {
                role: snapshot_by_name[pin.name]
                for role, pin in descriptor.donors_by_role.items()
            }
        ),
    )


def _read_source(root: Path, relative: str, label: str) -> bytes:
    path = safe_repo_path(root, relative, allow_missing=False)
    try:
        return path.read_bytes()
    except OSError as error:
        raise ContentPortError(f"{label}: cannot read {relative}: {error}") from error


def _asset_units(
    descriptor: PortDescriptor, state: PortSourceState
) -> list[RenderUnit]:
    units: list[RenderUnit] = []
    seen: set[str] = set()
    rendered_targets: dict[str, str] = {}
    records = descriptor.assets.get("assets")
    if not isinstance(records, tuple):
        raise ContentPortError("asset policy requires an immutable assets array")
    declared_capabilities = {
        decision.capability for decision in descriptor.capabilities
    }
    for index, raw in enumerate(records):
        item = _thaw(raw)
        if not isinstance(item, dict):
            raise ContentPortError(f"assets[{index}]: expected object")
        capability = item.get("capability")
        if capability not in declared_capabilities:
            raise ContentPortError(
                f"assets[{index}]: unknown capability {capability!r}"
            )
        if item.get("supportState") != "enabled":
            raise ContentPortError(
                f"assets[{index}]: asset emission requires enabled support"
            )
        target = item.get("semanticTarget")
        role = item.get("donor")
        source = item.get("sourcePath")
        command = item.get("conversionCommand")
        if not all(
            isinstance(value, str) and value for value in (target, role, source)
        ):
            raise ContentPortError(f"assets[{index}]: incomplete source binding")
        if role not in state.donor_roots:
            raise ContentPortError(f"assets[{index}]: unknown donor role {role!r}")
        source_key = ResourceKey("asset", f"{role}:{source}")
        if source_key not in state.resources:
            raise ContentPortError(
                f"assets[{index}]: source is absent from authenticated closure: "
                f"{source_key}"
            )
        if source_key.name in rendered_targets:
            raise ContentPortError(
                f"assets[{index}]: duplicate authenticated source {source_key.name}"
            )
        rendered_targets[source_key.name] = target
        if item.get("permission") != "redistributable":
            raise ContentPortError(f"assets[{index}]: asset is not redistributable")
        if target in seen:
            raise ContentPortError(f"duplicate asset target {target}")
        seen.add(target)
        payload = _read_source(state.donor_roots[role], source, f"assets[{index}]")
        source_digest = hashlib.sha256(payload).hexdigest()
        if source_digest != item.get("sourceSha256"):
            raise ContentPortError(f"assets[{index}]: donor hash drift for {target}")
        if command == ["copy-bytes"]:
            converted = payload
        elif (
            isinstance(command, (list, tuple))
            and len(command) == 4
            and command[0] == "replace-le16"
        ):
            try:
                offset = int(command[1], 0)
                expected = int(command[2], 0)
                replacement = int(command[3], 0)
            except (TypeError, ValueError) as error:
                raise ContentPortError(
                    f"assets[{index}]: invalid replace-le16 arguments"
                ) from error
            if (
                offset < 0
                or offset % 2
                or offset + 2 > len(payload)
                or not 0 <= expected <= 0xFFFF
                or not 0 <= replacement <= 0xFFFF
            ):
                raise ContentPortError(f"assets[{index}]: invalid replace-le16 bounds")
            actual = int.from_bytes(payload[offset : offset + 2], "little")
            if actual != expected:
                raise ContentPortError(
                    f"assets[{index}]: replace-le16 expected 0x{expected:04x} "
                    f"at offset {offset}, found 0x{actual:04x}"
                )
            converted_bytes = bytearray(payload)
            converted_bytes[offset : offset + 2] = replacement.to_bytes(2, "little")
            converted = bytes(converted_bytes)
        else:
            raise ContentPortError(f"assets[{index}]: unsupported conversion command")
        if hashlib.sha256(converted).hexdigest() != item.get("targetSha256"):
            raise ContentPortError(f"assets[{index}]: target hash drift for {target}")
        units.append(
            RenderUnit(f"asset:{target}", "tileset-assets", target, {target: converted})
        )
    authorized_sources = set(state.inventory.get("asset-policy", ()))
    required_sources = set(state.inventory.get("asset-required", ()))
    if authorized_sources != required_sources:
        missing = sorted(required_sources - authorized_sources)
        extra = sorted(authorized_sources - required_sources)
        raise ContentPortError(
            "asset policy does not match required physical closure: "
            f"missing={missing[:1]}, extra={extra[:1]}"
        )
    rendered_sources = set(rendered_targets)
    if rendered_sources != required_sources:
        missing = sorted(required_sources - rendered_sources)
        extra = sorted(rendered_sources - required_sources)
        raise ContentPortError(
            "asset render inventory does not match authenticated closure: "
            f"missing={missing[:1]}, extra={extra[:1]}"
        )
    required_targets = dict(state.asset_targets)
    if rendered_targets != required_targets:
        mismatched = sorted(
            source
            for source in rendered_sources & set(required_targets)
            if rendered_targets[source] != required_targets[source]
        )
        raise ContentPortError(
            "asset render targets do not match authenticated closure: "
            f"mismatched={mismatched[:1]}"
        )
    return units


def _animation_units(descriptor: PortDescriptor) -> list[RenderUnit]:
    """Materialize only policy-required frames from the authenticated donor."""
    from .animations import required_frame_payloads, verify_preserved_runtime_payloads

    if not descriptor.animations:
        return []
    verify_preserved_runtime_payloads(
        descriptor.animations,
        target_root=descriptor.event_policy_path.parents[4],
    )
    donor_root = descriptor.donor("content").root
    units: list[RenderUnit] = []
    for source, target in required_frame_payloads(descriptor.animations):
        payload = _read_source(donor_root, source, f"animation frame {source}")
        units.append(
            RenderUnit(
                f"animation:{target}",
                "tileset-assets",
                target,
                {target: payload},
            )
        )
    return units


def _map_units(descriptor: PortDescriptor, state: PortSourceState) -> list[RenderUnit]:
    for decision in descriptor.capabilities:
        if (
            decision.state.value == "enabled"
            and decision.capability not in MATERIALIZED_CAPABILITIES
        ):
            raise ContentPortError(
                f"{decision.map_name}: enabled capability {decision.capability!r} "
                "is not materialized"
            )
    profile = descriptor.adaptations["materializationProfile"]
    strip = tuple(profile["stripEventKinds"])
    if strip != MATERIALIZATION_STRIP_EVENT_KINDS:
        raise ContentPortError(
            "materialization profile must strip every non-warp event collection"
        )
    content_field = descriptor.adaptations["donorFieldRoles"]["content"]
    section_remaps = {
        item["source"]: item["target"]
        for item in descriptor.adaptations["sectionSymbolRemaps"]
    }
    music_remaps = {
        item[content_field]: item["target"]
        for item in descriptor.adaptations["musicAdaptations"]
    }
    graphics_remaps = {
        item[content_field]: item["target"]
        for item in descriptor.adaptations["graphicsAdaptations"]
    }
    projections = {
        identity.trainer: identity.projection
        for identity in state.trainer_inventory.identities
        if identity.projection is not None
    }
    placements = {
        placement.identity: placement
        for placement in state.trainer_inventory.placements
        if placement.admitted
    }
    units: list[RenderUnit] = []
    observed_objects: dict[str, list[str]] = {}
    observed_scripts: dict[str, list[str]] = {}
    materialization_maps = state.materialization_maps or state.maps
    for name, ownership in descriptor.map_ownership.items():
        if ownership != "rendered":
            continue
        allocation = descriptor.allocation_index.map_allocation(name)
        value = _thaw(materialization_maps[name])
        value.pop("_encounter_roots", None)
        value.pop("_trainer_event_roots", None)
        donor_fields = descriptor.adaptations["donorFieldRoles"]
        for decision in descriptor.adaptations["mapFieldDecisions"]:
            if decision["map"] == name:
                value[decision["field"]] = decision[donor_fields[decision["authority"]]]
        value["id"] = allocation.map_id
        value["layout"] = allocation.layout
        value["region_map_section"] = section_remaps.get(
            allocation.section, allocation.section
        )
        value["region"] = descriptor.target_bindings.region  # type: ignore[union-attr]
        music = value.get("music")
        if isinstance(music, str):
            value["music"] = music_remaps.get(music, music)
        value["connections"] = list(value.get("connections") or ())
        for decision in descriptor.adaptations["berryTreeAllocations"]:
            if decision["source"] == name:
                _set_pointer(value, decision["path"], decision["target"])
        for event in value.get("object_events") or ():
            graphics = event.get("graphics_id")
            if isinstance(graphics, str):
                event["graphics_id"] = graphics_remaps.get(graphics, graphics)
        for field in strip:
            if field not in value:
                raise ContentPortError(f"{name}: missing stripped event field {field}")
            value[field] = []
        rendered_events: list[dict[str, Any]] = []
        selected_objects: list[dict[str, Any]] = []
        event_rows: tuple[tuple[str, Any], ...]
        if state.trainer_materialization is not None:
            event_rows = tuple(
                (row.source_trainer, row.event)
                for row in state.trainer_event_projections.get(name, ())
            )
        else:
            event_rows = tuple(
                (event.trainers[0], event)
                for event in state.trainer_events.get(name, ())
                if len(event.trainers) == 1
            )
        for source_trainer, event in event_rows:
            if source_trainer not in projections:
                raise ContentPortError(
                    f"{name}: selected trainer event has no exact projection"
                )
            projection = projections[source_trainer]
            event_identity = f"{name}/{event.object_index}/{event.script_name}"
            placement = placements.get(event_identity)
            if placement is None or placement.trainer != source_trainer:
                raise ContentPortError(
                    f"{name}: selected trainer event has no exact admitted inventory placement"
                )
            instructions = []
            for index, instruction in enumerate(event.instructions):
                operands = list(instruction.operands)
                if index == 0 and state.trainer_materialization is None:
                    operands[0] = projection.target
                instructions.append(
                    {"command": instruction.command, "operands": operands}
                )
            # Route 26 North's connection clones intentionally reference the
            # canonical Route 26-owned script and text closure.
            if not (
                name == "Route26North"
                and event.script_name
                in {"Route26_EventScript_Jake", "Route26_EventScript_Joyce"}
            ):
                rendered_events.append(
                    {
                        "script": event.script_name,
                        "instructions": instructions,
                        "texts": [
                            {"label": text.label, "fragments": list(text.fragments)}
                            for text in event.texts
                        ],
                    }
                )
            object_event = _thaw(event.object_event)
            object_event["graphics_id"] = placement.overworld_graphic
            object_event.update(
                _REVIEWED_TRAINER_OBJECT_OVERLAYS.get(event_identity, {})
            )
            selected_objects.append(object_event)
            observed_objects.setdefault(source_trainer, []).append(event_identity)
            observed_scripts.setdefault(source_trainer, []).append(event_identity)
        value["object_events"] = selected_objects
        units.append(
            RenderUnit(
                f"map:{name}",
                "map-json",
                f"data/maps/{name}/map.json",
                value,
                options={"sortKeys": False, "ensureAscii": True},
            )
        )
        if profile["mapScripts"] == "empty" and rendered_events:
            raise ContentPortError(
                f"{name}: empty map-script profile cannot render trainer events"
            )
        if profile["mapScripts"] not in {"empty", "selected-trainers"}:
            raise ContentPortError("unsupported map-script materialization profile")
        path = f"data/maps/{name}/scripts.inc"
        units.append(
            RenderUnit(
                f"map-script:{name}",
                "trainer-script",
                path,
                {"map": name, "events": rendered_events},
            )
        )
    if state.trainer_materialization is not None:
        _require_rendered_materialization_exact_cover(
            descriptor,
            state,
            observed_objects,
            owner="emitted trainer objects",
        )
        _require_rendered_materialization_exact_cover(
            descriptor,
            state,
            observed_scripts,
            owner="emitted trainer scripts",
        )
    return units


def _trainer_units(
    descriptor: PortDescriptor, state: PortSourceState, repo: Path
) -> list[RenderUnit]:
    independently_selected: dict[str, list[str]] = {}
    if state.trainer_materialization is not None:
        for map_name, rows in state.trainer_event_projections.items():
            for row in rows:
                identity = (
                    f"{row.event.map_name}/{row.event.object_index}/"
                    f"{row.event.script_name}"
                )
                independently_selected.setdefault(row.source_trainer, []).append(
                    identity
                )
        selected = set(independently_selected)
    else:
        selected = {
            trainer
            for map_name, events in state.trainer_events.items()
            if descriptor.map_ownership.get(map_name) == "rendered"
            for event in events
            for trainer in event.trainers
        }
    projections = {
        identity.trainer: identity.projection
        for identity in state.trainer_inventory.identities
        if identity.projection is not None
    }
    if selected - set(projections):
        raise ContentPortError(
            "trainer projections must cover selected trainer dependencies"
        )
    if not selected:
        return []
    ledger = load_binding_index(repo / "src/data/persistence/persistent_ids.json")
    rendered: list[dict[str, Any]] = []
    observed_parties: dict[str, tuple[str, ...]] = {}
    observed_runtime_rows: dict[str, tuple[str, ...]] = {}
    for source in sorted(selected):
        projection = projections[source]
        ledger.resolve(projection.target, domain="trainerIds")
        trainer = state.semantic_values.get(ResourceKey("trainer", source))
        if trainer is None:
            raise ContentPortError(
                f"trainer:{source}: authenticated payload is missing"
            )
        if tuple(trainer.get("ai_flags", ())) != ("AI_SCRIPT_CHECK_BAD_MOVE",):
            raise ContentPortError(
                f"trainer:{source}/ai_flags: projection preimage drift"
            )
        if (
            trainer.get("items")
            or trainer.get("party_format") != "NO_ITEM_DEFAULT_MOVES"
        ):
            raise ContentPortError(f"trainer:{source}: unsupported party payload")
        trainer_name = trainer.get("trainer_name")
        if (
            not isinstance(trainer_name, str)
            or TRAINER_DISPLAY_RE.fullmatch(trainer_name) is None
        ):
            raise ContentPortError(f"trainer:{source}: invalid trainer name payload")
        double_token = trainer.get("double_battle")
        if double_token not in {"TRUE", "FALSE"}:
            raise ContentPortError(f"trainer:{source}: invalid double-battle payload")
        parties = tuple(trainer.get("parties", ()))
        if len(parties) != 1:
            raise ContentPortError(f"trainer:{source}: exactly one party is required")
        if state.trainer_materialization is not None:
            party_projection = state.trainer_party_projections.get(source)
            if party_projection is None or party_projection.party_name != parties[0]:
                raise ContentPortError(
                    f"trainer:{source}: typed materialized party projection is missing"
                )
            members = [
                {
                    "species": member.species,
                    "level": member.level,
                    "iv": member.iv,
                }
                for member in party_projection.members
            ]
            placements = tuple(independently_selected[source])
            observed_parties[source] = placements
            observed_runtime_rows[source] = placements
        else:
            party = state.semantic_values.get(ResourceKey("party", parties[0]))
            if party is None:
                raise ContentPortError(
                    f"party:{parties[0]}: authenticated payload is missing"
                )
            members = []
            for index, member in enumerate(party.get("members", ())):
                if member.get("held_item") is not None or member.get("moves"):
                    raise ContentPortError(
                        f"party:{parties[0]}/members/{index}: default party format drift"
                    )
                if (
                    type(member.get("level")) is not int
                    or type(member.get("iv")) is not int
                ):
                    raise ContentPortError(
                        f"party:{parties[0]}/members/{index}: level and IV are required"
                    )
                members.append(
                    {
                        "species": member["species"],
                        "level": member["level"],
                        "iv": member["iv"],
                    }
                )
        rendered.append(
            {
                "target": projection.target,
                "name": trainer_name,
                "class": projection.trainer_class,
                "pic": _BYTE_IDENTICAL_TRAINER_PICS.get(projection.pic, projection.pic),
                "gender": projection.gender,
                "music": projection.music,
                "double": double_token == "TRUE",
                "ai": [projection.ai],
                "party": members,
            }
        )
    if state.trainer_materialization is not None:
        require_materialization_exact_cover(
            state.trainer_materialization,
            observed_parties,
            owner="emitted trainer parties",
        )
        require_materialization_exact_cover(
            state.trainer_materialization,
            observed_runtime_rows,
            owner="emitted trainer runtime rows",
        )
    return [
        RenderUnit(
            "selected-trainer-parties",
            "trainer-party",
            "src/data/trainers.party",
            rendered,
            name="selected trainer parties",
        )
    ]


def _set_pointer(value: object, pointer: str, replacement: object) -> None:
    parts = pointer.split("/")
    current = value
    for part in parts[:-1]:
        if isinstance(current, list) and part.isdecimal():
            current = current[int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise ContentPortError(f"invalid materialization pointer {pointer}")
    final = parts[-1]
    if isinstance(current, list) and final.isdecimal():
        current[int(final)] = replacement
    elif isinstance(current, dict) and final in current:
        current[final] = replacement
    else:
        raise ContentPortError(f"invalid materialization pointer {pointer}")


def _layout_units(
    descriptor: PortDescriptor, state: PortSourceState
) -> list[RenderUnit]:
    bindings = descriptor.target_bindings
    if bindings is None:
        raise ContentPortError("port has no renderer target bindings")
    remaps = {
        (item["layout"], item["field"]): item["target"]
        for item in descriptor.adaptations["layoutTilesetRemaps"]
    }
    units: list[RenderUnit] = []
    preserved_layouts = {
        allocation.layout
        for name, allocation in descriptor.allocation_index.maps.items()
        if descriptor.map_ownership.get(name) == "preserve"
    }
    for layout_id in descriptor.allocation_index.layouts:
        value = _thaw(state.layouts[layout_id])
        for field in ("primary_tileset", "secondary_tileset"):
            replacement = remaps.get((layout_id, field))
            if replacement is not None:
                value[field] = replacement
        value.pop("layout_version", None)
        value["format"] = bindings.layout_format
        supplemental = tuple(
            field
            for field in ("border_height", "border_width")
            if layout_id not in preserved_layouts
            and state.layout_field_authorities[layout_id][field]
            != state.layout_authorities[layout_id]
        )
        units.append(
            RenderUnit(
                layout_id,
                "layout-registry",
                "data/layouts/layouts.json",
                value,
                record_key=layout_id,
                slot=descriptor.allocation_index.layout_slot(layout_id),
                options={"omitFields": supplemental},
            )
        )
    return units


def _encounter_units(
    descriptor: PortDescriptor, state: PortSourceState
) -> list[RenderUnit]:
    units: list[RenderUnit] = []
    for policy in descriptor.adaptations["encounterProfiles"]:
        key = ResourceKey("encounter", str(policy["label"]))
        value = state.semantic_values.get(key)
        if value is None:
            raise ContentPortError(f"{key}: encounter profile is not in the closure")
        profile = value.get("profile")
        if not isinstance(profile, Mapping):
            raise ContentPortError(f"{key}: encounter profile payload is missing")
        units.append(
            RenderUnit(
                f"encounter:{key.name}",
                "encounter-registry",
                "src/data/wild_encounters.json",
                _thaw(profile),
                registry="wild_encounter_groups.0.encounters",
                record_key=key.name,
            )
        )
    return units


def _group_units(descriptor: PortDescriptor) -> list[RenderUnit]:
    members: dict[str, list[tuple[int, str]]] = {
        name: [] for name in descriptor.allocation_index.groups
    }
    for allocation in descriptor.allocation_index.maps.values():
        members[allocation.target_group].append(
            (allocation.target_member, allocation.name)
        )
    units: list[RenderUnit] = []
    for name, slot in descriptor.allocation_index.groups.items():
        units.extend(
            (
                RenderUnit(
                    f"group:{name}",
                    "map-group-registry",
                    "data/maps/map_groups.json",
                    [map_name for _, map_name in sorted(members[name])],
                    registry="$",
                    record_key=name,
                ),
                RenderUnit(
                    f"group-order:{name}",
                    "map-group-registry",
                    "data/maps/map_groups.json",
                    name,
                    registry="group_order",
                    record_key=name,
                    slot=slot,
                ),
            )
        )
    return units


def _section_documents(root: Path) -> Iterable[tuple[Path, Mapping[str, Any]]]:
    for path in sorted((root / "src/data/region_map").glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ContentPortError(
                f"cannot read section metadata {path}: {error}"
            ) from error
        for item in document.get("map_sections", []):
            if isinstance(item, dict):
                yield path, item


def _section_units(
    descriptor: PortDescriptor, state: PortSourceState, repo: Path
) -> list[RenderUnit]:
    bindings = descriptor.target_bindings
    if bindings is None:
        raise ContentPortError("port has no renderer target bindings")
    remaps = {
        item["source"]: item["target"]
        for item in descriptor.adaptations["sectionSymbolRemaps"]
    }
    ledger = load_binding_index(repo / "src/data/persistence/persistent_ids.json")
    saved_location_invalid = ledger.resolve(
        bindings.saved_location_invalid_binding.symbol,
        domain=bindings.saved_location_invalid_binding.domain,
    ).value
    met_location_invalid = ledger.resolve(
        bindings.met_location_invalid_binding.symbol,
        domain=bindings.met_location_invalid_binding.domain,
    ).value
    codecs = {item.section: item for item in bindings.section_persistence_codecs}
    cache: dict[str, tuple[tuple[Path, Mapping[str, Any]], ...]] = {}
    rendered_sections = {
        allocation.section
        for name, allocation in descriptor.allocation_index.maps.items()
        if descriptor.map_ownership.get(name) == "rendered"
    }
    units: list[RenderUnit] = []
    for authority in descriptor.section_metadata_authorities:
        matches = cache.setdefault(
            authority.source_role,
            tuple(_section_documents(state.donor_roots[authority.source_role])),
        )
        records = [
            (path, item)
            for path, item in matches
            if item.get("id", item.get("map_section")) == authority.source_symbol
        ]
        distinct = {
            json.dumps(item, sort_keys=True, separators=(",", ":"))
            for _, item in records
        }
        if not records or len(distinct) != 1:
            raise ContentPortError(
                f"{authority.section}: section source {authority.source_role}:{authority.source_symbol} resolved {len(records)} records"
            )
        source = records[0][1]
        target = remaps.get(authority.section, authority.section)
        slot = descriptor.allocation_index.section_slot(authority.section)
        destination_binding = ledger.resolve(
            target, domain=bindings.met_location_invalid_binding.domain
        )
        saved_location_binding = ledger.resolve(
            target, domain=bindings.saved_location_invalid_binding.domain
        )
        for kind, binding in (
            ("destination", destination_binding),
            ("saved location", saved_location_binding),
        ):
            if binding.value != slot:
                raise ContentPortError(
                    f"{authority.section}: persistent {kind} binding {binding.value} "
                    f"disagrees with allocation {slot}"
                )
        value: dict[str, object] = {
            "id": target,
            "value": destination_binding.value,
            "kind": bindings.section_kind,
            "region": bindings.region,
            "region_map_type": bindings.region_map_type,
            "saved_location": target
            if saved_location_binding.value < saved_location_invalid
            else None,
            "met_location": destination_binding.value
            if destination_binding.value < met_location_invalid
            else None,
            "met_location_display": target
            if destination_binding.value < met_location_invalid
            else None,
            "name": source["name"],
        }
        codec = codecs.get(authority.section)
        if codec is not None:
            if (
                codec.met_location_binding.domain
                != bindings.met_location_invalid_binding.domain
                or codec.met_location_binding.symbol != codec.met_location_display
            ):
                raise ContentPortError(
                    f"{authority.section}: met-location binding must match its display identity"
                )
            ledger.resolve(
                codec.saved_location,
                domain=bindings.saved_location_invalid_binding.domain,
            )
            value["saved_location"] = codec.saved_location
            value["met_location"] = ledger.resolve(
                codec.met_location_binding.symbol,
                domain=codec.met_location_binding.domain,
            ).value
            value["met_location_display"] = codec.met_location_display
        if authority.section in rendered_sections:
            for field in ("x", "y", "width", "height"):
                if field in source:
                    value[field] = source[field]
        units.append(
            RenderUnit(
                f"section:{target}",
                "region-section-registry",
                "src/data/region_map/region_map_sections.json",
                value,
                registry="map_sections",
                record_key=target,
                slot=slot,
            )
        )
    return units


def _binding_body(
    descriptor: PortDescriptor, state: PortSourceState, repo: Path, kind: str
) -> str:
    del state
    prefix = "FLAG_" if kind == "flag-bindings" else "VAR_"
    ledger = load_binding_index(repo / "src/data/persistence/persistent_ids.json")
    domain = "flags" if prefix == "FLAG_" else "vars"
    bindings = descriptor.target_bindings
    assert bindings is not None
    selected = bindings.flag_exports if domain == "flags" else bindings.var_exports
    return "\n".join(
        f"#define {name:<60} 0x{ledger.resolve(name, domain=domain).value:X}"
        for name in selected
    )


def _tilesets(descriptor: PortDescriptor) -> list[dict[str, Any]]:
    return [_thaw(item) for item in descriptor.adaptations["tilesetAdaptations"]]


def _generated_body(
    symbol: str, descriptor: PortDescriptor, state: PortSourceState, repo: Path
) -> str:
    if symbol == "map-scripts":
        bindings = descriptor.target_bindings
        assert bindings is not None
        includes = "\n".join(
            f'\t.include "data/maps/{name}/scripts.inc"'
            for name in descriptor.allocation_index.maps
        )
        body = (
            includes
            + f"\n\n{bindings.time_encounter_label}::\n\treturn\n\n"
            + f"{bindings.deferred_call_label}::\n"
            + f'\t.string "{bindings.deferred_call_text}"\n'
        )
        shared_text = state.paired_double_not_enough_text
        if shared_text is not None:
            body += f"\n{shared_text.label}::\n"
            body += "".join(
                f"\t.string {fragment}\n" for fragment in shared_text.fragments
            )
        return body
    if symbol in {"flag-bindings", "var-bindings"}:
        return _binding_body(descriptor, state, repo, symbol)
    if symbol == "berry-bindings":
        bindings = descriptor.target_bindings
        assert bindings is not None
        allocations = descriptor.adaptations["berryTreeAllocations"]
        anchor = bindings.berry_tree_binding
        if not allocations or allocations[0]["target"] != anchor.symbol:
            raise ContentPortError(
                "berry-tree policy anchor does not match the first allocation"
            )
        ledger = load_binding_index(repo / "src/data/persistence/persistent_ids.json")
        return "\n".join(
            f"#define {item['target']:<35} "
            f"{ledger.resolve(item['target'], domain=anchor.domain).value}"
            for item in allocations
        )
    if symbol == "trainer-bindings":
        ledger = load_binding_index(repo / "src/data/persistence/persistent_ids.json")
        return "\n".join(
            f"#define {item['id']} {ledger.resolve(item['id']).value}"
            for item in descriptor.adaptations["trainerPresentation"]
        )
    if symbol == "trainer-parties":
        doubles = {"Singles": "No", "Doubles": "Yes"}
        return "\n\n".join(
            f"=== {item['id']} ===\nName: {item['name']}\nClass: {item['class']}\nPic: {item['pic']}\nGender: {item['gender']}\nMusic: {item['music']}\nDouble Battle: {doubles[item['battleType']]}\n\n{item['species']}\nLevel: {item['level']}\nIVs: {item['ivs']}"
            for item in descriptor.adaptations["trainerPresentation"]
        )
    tilesets = _tilesets(descriptor)
    bindings = descriptor.target_bindings
    assert bindings is not None
    feature = bindings.tileset_feature_macro
    if symbol == "tileset-externs":
        return (
            f"#if {feature}\n"
            + "\n".join(
                f"extern const struct Tileset gTileset_{item.get('targetSymbol', item.get('symbol'))};"
                for item in tilesets
            )
            + f"\n#endif // {feature}"
        )
    if symbol == "tileset-graphics":
        blocks = [f"#if {feature}"]
        for item in tilesets:
            role = item["role"]
            directory = item.get("targetDirectory", item.get("directory"))
            name = item.get("targetSymbol", item.get("symbol"))
            count = item["paletteCount"]
            palettes = "\n\n".join(
                f'    INCGFX_U16("data/tilesets/{role}/{directory}/palettes/{index:02}.pal", ".gbapal"),'
                for index in range(count)
            )
            blocks.append(
                f'const u32 gTilesetTiles_{name}[] = INCGFX_U32("data/tilesets/{role}/{directory}/tiles.png", ".4bpp.fastSmol");\n\nconst u16 gTilesetPalettes_{name}[][16] =\n{{\n\n{palettes}\n\n}};'
            )
        return "\n\n".join(blocks + [f"#endif // {feature}"])
    if symbol == "tileset-metatiles":
        lines = [f"#if {feature}"]
        for item in tilesets:
            role = item["role"]
            directory = item.get("targetDirectory", item.get("directory"))
            name = item.get("targetSymbol", item.get("symbol"))
            lines.extend(
                (
                    f'const u16 gMetatiles_{name}[] = INCBIN_U16("data/tilesets/{role}/{directory}/metatiles.bin");',
                    f'const u16 gMetatileAttributes_{name}[] = INCBIN_U16("data/tilesets/{role}/{directory}/metatile_attributes.bin");',
                    "",
                )
            )
        return "\n".join(lines + [f"#endif // {feature}"])
    if symbol == "tileset-headers":
        blocks = [f"#if {feature}"]
        for item in tilesets:
            name = item.get("targetSymbol", item.get("symbol"))
            secondary = "TRUE" if item["secondary"] else "FALSE"
            callback = item.get("animationCallback", "NULL")
            blocks.append(
                f"const struct Tileset gTileset_{name} =\n{{\n    .isCompressed = TRUE,\n    .flags = TILESET_FLAGS({secondary}, METATILE_ATTRIBUTES_EMERALD_U16),\n    .tiles = gTilesetTiles_{name},\n    .palettes = gTilesetPalettes_{name},\n    .metatiles = gMetatiles_{name},\n    .metatileAttributes = gMetatileAttributes_{name},\n    .callback = {callback},\n}};"
            )
        return "\n\n".join(blocks + [f"#endif // {feature}"])
    raise ContentPortError(f"unknown generated source symbol {symbol!r}")


def _generated_units(
    descriptor: PortDescriptor, state: PortSourceState, repo: Path
) -> list[RenderUnit]:
    units: list[RenderUnit] = []
    for policy in descriptor.generated_sections:
        expected_authorities = GENERATED_AUTHORITY_CONTRACT.get(policy.source_symbol)
        if policy.authorities != expected_authorities:
            raise ContentPortError(
                f"{policy.source_symbol}: generated authority contract drift"
            )
        options: dict[str, object] = {"markerDialect": "legacy-import"}
        if policy.source_symbol == "trainer-parties":
            options.update({"markerStyle": "preprocessor", "blankLineBeforeEnd": True})
        units.append(
            RenderUnit(
                f"generated:{policy.source_symbol}",
                "generated-section",
                policy.path,
                _generated_body(policy.source_symbol, descriptor, state, repo),
                name=policy.key,
                options=options,
            )
        )
    return units


def derive_desired_state(
    descriptor: PortDescriptor, repo: Path | str
) -> tuple[OwnershipManifest, Mapping[tuple[str, ...], object]]:
    """Return complete desired ownership compiled without reading owned target payloads."""
    root = Path(repo).resolve()
    with authenticated_donor_snapshot(descriptor.donors) as snapshots:
        snapshot_descriptor = _with_snapshot_donors(descriptor, snapshots)
        _, state = resolve_port_sources(snapshot_descriptor, root)
        if (
            snapshot_descriptor.target_bindings is None
            or not snapshot_descriptor.generated_sections
        ):
            raise ContentPortError("port descriptor has no complete renderer policy")
        units = [
            *_map_units(snapshot_descriptor, state),
            *_layout_units(snapshot_descriptor, state),
            *_group_units(snapshot_descriptor),
            *_section_units(snapshot_descriptor, state, root),
            *_asset_units(snapshot_descriptor, state),
            *_animation_units(snapshot_descriptor),
            *_trainer_units(snapshot_descriptor, state, root),
            *_encounter_units(snapshot_descriptor, state),
            *_generated_units(snapshot_descriptor, state, root),
        ]
        manifest, payloads = render_units(
            RenderContext(
                _port_name(snapshot_descriptor),
                root=root,
                allocations=snapshot_descriptor.allocation_index,
            ),
            units,
        )
        installed_path = (
            root
            / "tools/content_port/ports"
            / _port_name(snapshot_descriptor)
            / "ownership.json"
        )
        installed = (
            OwnershipManifest.load(installed_path)
            if installed_path.exists()
            else OwnershipManifest(_port_name(snapshot_descriptor), ())
        )
        verify_desired_claims(root, installed, manifest)
        return manifest, payloads


def derive_released_map_files(
    descriptor: PortDescriptor,
    repo: Path | str,
    desired: OwnershipManifest,
) -> frozenset[str]:
    """Return ledgered full map files explicitly handed to target ownership.

    Map ownership is the descriptor's only full-file release signal. Preserve
    therefore releases only the map JSON and script source formerly emitted by
    the map renderer; layouts and other derived resources retain their own
    independent ownership decisions.
    """

    root = Path(repo).resolve()
    installed_path = (
        root / "tools/content_port/ports" / _port_name(descriptor) / "ownership.json"
    )
    installed = (
        OwnershipManifest.load(installed_path)
        if installed_path.exists()
        else OwnershipManifest(_port_name(descriptor), ())
    )
    candidates = {
        path
        for name, ownership in descriptor.map_ownership.items()
        if ownership == "preserve"
        for path in (
            f"data/maps/{name}/map.json",
            f"data/maps/{name}/scripts.inc",
        )
    }
    desired_paths = {unit.path for unit in desired.units}
    collisions = sorted(candidates & desired_paths)
    if collisions:
        raise ContentPortError(
            f"preserved map file still has desired ownership: {collisions[0]}"
        )
    return frozenset(
        unit.path
        for unit in installed.units
        if unit.kind == "file" and unit.path in candidates
    )
