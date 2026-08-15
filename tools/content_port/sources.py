"""Normalize expansion-native content into a typed dependency graph."""

from __future__ import annotations

import json
import re
import copy
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Protocol

from .descriptor import PortDescriptor
from .errors import ContentPortError
from .model import (
    ResourceKey,
    TrainerEventRecord,
    TrainerScriptInstruction,
    TrainerText,
)
from .ownership import safe_repo_path
from .trainer_inventory import (
    InventoryExpectations,
    TrainerInventory,
    TrainerProjection,
    load_trainer_inventory,
    require_projection_exact_cover,
)
from .trainer_materialization import (
    ReviewedMaterializationPrefix,
    TrainerMaterializationAuthority,
    load_trainer_materialization,
    materialized_placements,
    require_materialization_exact_cover,
)
from .trainer_payloads import (
    StandardSingleEventProjection,
    StandardSinglePartyProjection,
    project_standard_single_event,
    project_standard_single_party,
)
from .world_graph import WorldEdge, with_dynamic_warps


TRAINER_PIC_ASSET_PROJECTIONS = MappingProxyType(
    {
        "Firebreather HG": (
            "graphics/trainers/front_pics/firebreather.png",
            "graphics/trainers/front_pics/firebreather_hg.png",
        ),
        "Psychic M HG": (
            "graphics/trainers/front_pics/psychic_m.png",
            "graphics/trainers/front_pics/psychic_m_hg.png",
        ),
        "Sage HG": (
            "graphics/trainers/front_pics/sage.png",
            "graphics/trainers/front_pics/sage_hg.png",
        ),
        "Super Nerd HG": (
            "graphics/trainers/front_pics/super_nerd.png",
            "graphics/trainers/front_pics/super_nerd_hg.png",
        ),
    }
)

JOHTO_CLASS_PROJECTIONS = MappingProxyType(
    {
        f"TRAINER_CLASS_{name}": f"JOHTO_TRAINER_CLASS_{name}"
        for name in (
            "BURGLAR",
            "FIREBREATHER",
            "JUGGLER",
            "PSYCHIC_M",
            "SAGE",
            "SUPER_NERD",
        )
    }
)
TRAINER_PIC_PROJECTIONS = MappingProxyType(
    {
        "TRAINER_PIC_BURGLAR": "TRAINER_PIC_BURGLAR_FRLG",
        "TRAINER_PIC_JUGGLER": "TRAINER_PIC_JUGGLER_FRLG",
        "TRAINER_PIC_TWINS": "TRAINER_PIC_TWINS_FRLG",
        "TRAINER_PIC_YOUNGSTER": "TRAINER_PIC_YOUNGSTER_FRLG",
        "TRAINER_PIC_FIREBREATHER": "JOHTO_TRAINER_PIC_FIREBREATHER",
        "TRAINER_PIC_PSYCHIC_M": "JOHTO_TRAINER_PIC_PSYCHIC_M",
        "TRAINER_PIC_SAGE": "JOHTO_TRAINER_PIC_SAGE",
        "TRAINER_PIC_SUPER_NERD": "JOHTO_TRAINER_PIC_SUPER_NERD",
    }
)
TRAINER_MUSIC_PROJECTIONS = MappingProxyType(
    {
        "TRAINER_ENCOUNTER_MUSIC_HG_BOY_1": "TRAINER_ENCOUNTER_MUSIC_MALE",
        "TRAINER_ENCOUNTER_MUSIC_HG_BOY_2": "TRAINER_ENCOUNTER_MUSIC_SWIMMER",
        "TRAINER_ENCOUNTER_MUSIC_HG_GIRL_1": "TRAINER_ENCOUNTER_MUSIC_GIRL",
        "TRAINER_ENCOUNTER_MUSIC_HG_GIRL_2": "TRAINER_ENCOUNTER_MUSIC_FEMALE",
        "TRAINER_ENCOUNTER_MUSIC_HG_SAGE": "TRAINER_ENCOUNTER_MUSIC_SUSPICIOUS",
        "TRAINER_ENCOUNTER_MUSIC_HG_SUSPICIOUS_1": "TRAINER_ENCOUNTER_MUSIC_SUSPICIOUS",
        "TRAINER_ENCOUNTER_MUSIC_HG_SUSPICIOUS_2": "TRAINER_ENCOUNTER_MUSIC_MALE",
    }
)
FEMALE_TRAINER_PICS = frozenset(
    f"TRAINER_PIC_{name}"
    for name in (
        "BEAUTY",
        "COOLTRAINER_F",
        "EXPERT_F",
        "HEX_MANIAC",
        "LASS",
        "PARASOL_LADY",
        "PICNICKER",
        "SWIMMER_F",
    )
)
TRAINER_GRAPHIC_PROJECTIONS = MappingProxyType(
    {
        "OBJ_EVENT_GFX_BATTLE_GIRL": "OBJ_EVENT_GFX_COOLTRAINER_F",
        "OBJ_EVENT_GFX_JUGGLER": "OBJ_EVENT_GFX_CAMERAMAN",
        "OBJ_EVENT_GFX_SAGE": "OBJ_EVENT_GFX_OLD_MAN_1",
        "OBJ_EVENT_GFX_FIREBREATHER": "OBJ_EVENT_GFX_ROCKER",
        "OBJ_EVENT_GFX_BURGLAR": "OBJ_EVENT_GFX_MANIAC",
    }
)


@dataclass(frozen=True, order=True)
class Provenance:
    path: str
    location: str = ""

    def __str__(self) -> str:
        return f"{self.path}{self.location}"


@dataclass(frozen=True)
class SourceRecord:
    value: Mapping[str, Any]
    provenance: Provenance


@dataclass(frozen=True, order=True)
class SourceEdge:
    source: ResourceKey
    target: ResourceKey
    provenance: Provenance
    role: str = field(default="dependency", compare=True)


@dataclass(frozen=True)
class SourceGraph:
    resources: Mapping[ResourceKey, Provenance]
    edges: tuple[SourceEdge, ...]

    @property
    def dependencies(self) -> Mapping[ResourceKey, tuple[ResourceKey, ...]]:
        result: dict[ResourceKey, set[ResourceKey]] = {
            key: set() for key in self.resources
        }
        for edge in self.edges:
            result.setdefault(edge.source, set()).add(edge.target)
        return MappingProxyType(
            {key: tuple(sorted(value)) for key, value in sorted(result.items())}
        )


@dataclass(frozen=True)
class ContractEvidence:
    """Canonical evidence emitted after the real port graph closes."""

    inventory: Mapping[str, int]
    closure: Mapping[str, tuple[str, ...]]
    evidence: Mapping[str, Any]

    def to_report(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "inventory": dict(self.inventory),
                "closure": {key: _thaw(value) for key, value in self.closure.items()},
                "evidence": _thaw(self.evidence),
            }
        )


@dataclass(frozen=True)
class PortSourceState:
    """Immutable, authority-resolved inputs consumed by renderers."""

    maps: Mapping[str, Mapping[str, Any]]
    layouts: Mapping[str, Mapping[str, Any]]
    map_authorities: Mapping[str, str]
    layout_authorities: Mapping[str, str]
    layout_field_authorities: Mapping[str, Mapping[str, str]]
    donor_roots: Mapping[str, Path]
    resources: Mapping[ResourceKey, Provenance]
    inventory: Mapping[str, tuple[str, ...]]
    asset_targets: Mapping[str, str]
    semantic_evidence: Mapping[str, str]
    semantic_values: Mapping[ResourceKey, Mapping[str, Any]]
    trainer_events: Mapping[str, tuple[TrainerEventRecord, ...]]
    trainer_inventory: TrainerInventory
    materialization_maps: Mapping[str, Mapping[str, Any]] | None = None
    trainer_materialization: TrainerMaterializationAuthority | None = None
    trainer_event_projections: Mapping[
        str, tuple[StandardSingleEventProjection, ...]
    ] = MappingProxyType({})
    trainer_party_projections: Mapping[str, StandardSinglePartyProjection] = (
        MappingProxyType({})
    )


class RecordLoader(Protocol):
    def __call__(self, key: ResourceKey) -> SourceRecord: ...


def _c_braced_value(text: str, start: int, path: Path, identity: str) -> str:
    opening = text.find("{", start)
    if opening < 0:
        raise ContentPortError(f"{path}: {identity} has no initializer")
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index]
    raise ContentPortError(f"{path}: {identity} has an unterminated initializer")


def _direct_c_brace_blocks(text: str) -> tuple[str, ...]:
    result: list[str] = []
    depth = 0
    opening = 0
    for index, char in enumerate(text):
        if char == "{":
            if depth == 0:
                opening = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0:
                result.append(text[opening + 1 : index])
    return tuple(result)


def _c_scalar(text: str, field: str, prefix: str) -> str | None:
    match = re.search(
        rf"\.{re.escape(field)}\s*=\s*({re.escape(prefix)}[A-Z0-9_]+)", text
    )
    return match.group(1) if match else None


def _c_list(text: str, field: str, prefix: str) -> list[str]:
    match = re.search(rf"\.{re.escape(field)}\s*=\s*\{{([^}}]*)\}}", text, re.DOTALL)
    if match is None:
        return []
    return re.findall(rf"\b{re.escape(prefix)}[A-Z0-9_]+\b", match.group(1))


def _c_number(text: str, field: str) -> int | None:
    match = re.search(rf"\.{re.escape(field)}\s*=\s*(\d+)", text)
    return int(match.group(1)) if match else None


def _c_token(text: str, field: str) -> str | None:
    match = re.search(rf"\.{re.escape(field)}\s*=\s*([A-Z][A-Z0-9_]*)", text)
    return match.group(1) if match else None


def _c_string(text: str, field: str) -> str | None:
    match = re.search(rf"\.{re.escape(field)}\s*=\s*_\(\s*\"([^\"]*)\"\s*\)", text)
    return match.group(1) if match else None


def _c_expression(text: str, field: str) -> tuple[str, ...]:
    match = re.search(rf"\.{re.escape(field)}\s*=\s*([^,\n]+)", text)
    if match is None:
        return ()
    return tuple(re.findall(r"\b[A-Z][A-Z0-9_]+\b", match.group(1)))


def _index_native_declarations(
    records: dict[ResourceKey, SourceRecord], root: Path
) -> None:
    declarations = {
        root / "include/constants/species.h": (("species", "SPECIES_"),),
        root / "include/constants/moves.h": (("move", "MOVE_"),),
        root / "include/constants/items.h": (("item", "ITEM_"),),
        root / "include/constants/trainers.h": (
            ("trainer-class", "TRAINER_CLASS_"),
            ("asset", "TRAINER_PIC_"),
            ("asset", "TRAINER_ENCOUNTER_MUSIC_"),
        ),
    }
    for path, domains in declarations.items():
        if not path.is_file():
            continue
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            match = re.match(
                r"^\s*(?:#\s*define\s+)?([A-Z][A-Z0-9_]+)\s*(?:=|,|\s)",
                line,
            )
            if match is None:
                continue
            symbol = match.group(1)
            for domain, prefix in domains:
                if symbol.startswith(prefix):
                    records.setdefault(
                        ResourceKey(domain, symbol),
                        SourceRecord(
                            {}, Provenance(path.as_posix(), f":{line_number}")
                        ),
                    )
    tmhm_path = root / "include/constants/tms_hms.h"
    if tmhm_path.is_file():
        family: str | None = None
        for line_number, line in enumerate(
            tmhm_path.read_text(encoding="utf-8").splitlines(), 1
        ):
            declaration = re.match(r"^\s*#\s*define\s+FOREACH_(TM|HM)\(F\)", line)
            if declaration:
                family = declaration.group(1)
                continue
            if family is None:
                continue
            member = re.match(r"^\s*F\(([A-Z][A-Z0-9_]*)\)\s*(?:\\)?\s*$", line)
            if member is None:
                family = None
                continue
            symbol = f"ITEM_{family}_{member.group(1)}"
            records.setdefault(
                ResourceKey("item", symbol),
                SourceRecord({}, Provenance(tmhm_path.as_posix(), f":{line_number}")),
            )


def _require_native_leaf(
    records: Mapping[ResourceKey, SourceRecord],
    domain: str,
    name: str,
    source: Path,
    pointer: str,
) -> None:
    if ResourceKey(domain, name) not in records:
        raise ContentPortError(
            f"{source}{pointer}: {domain} symbol {name} has no authenticated declaration"
        )


class SourceContext:
    """Resource loader with deterministic, path-rich failures.

    Tests and descriptors can supply an exact record mapping. Real ports normally
    supply one loader per domain, keeping donor layout knowledge outside the graph.
    """

    def __init__(
        self,
        records: Mapping[ResourceKey, SourceRecord | Mapping[str, Any]] | None = None,
        loaders: Mapping[str, RecordLoader] | None = None,
        aliases: Mapping[ResourceKey, ResourceKey] | None = None,
        active_capabilities: Iterable[str] | None = None,
        resource_capabilities: Mapping[ResourceKey, Iterable[str]] | None = None,
    ) -> None:
        self._records = dict(records or {})
        self._loaders = dict(loaders or {})
        self._aliases = dict(aliases or {})
        self._active_capabilities = (
            None if active_capabilities is None else frozenset(active_capabilities)
        )
        self._resource_capabilities = {
            key: frozenset(value)
            for key, value in (resource_capabilities or {}).items()
        }

    def canonicalize(self, key: ResourceKey) -> ResourceKey:
        return self._aliases.get(key, key)

    def supports(self, capability: str, key: ResourceKey | None = None) -> bool:
        if key is not None and key in self._resource_capabilities:
            return capability in self._resource_capabilities[key]
        return (
            self._active_capabilities is None or capability in self._active_capabilities
        )

    def load(self, key: ResourceKey) -> SourceRecord:
        key = self.canonicalize(key)
        raw = self._records.get(key)
        if raw is not None:
            if isinstance(raw, SourceRecord):
                return raw
            return SourceRecord(raw, Provenance(f"<{key.domain}:{key.name}>"))
        loader = self._loaders.get(key.domain)
        if loader is None:
            raise ContentPortError(f"no source loader for {key.domain}:{key.name}")
        try:
            return loader(key)
        except ContentPortError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ContentPortError(
                f"cannot load {key.domain}:{key.name}: {exc}"
            ) from exc


class ExpansionSourceContext(SourceContext):
    """Index expansion-native JSON and ASM identities from a donor checkout."""

    def __init__(
        self,
        donor_root: Path | str,
        *,
        capabilities: Mapping[str, Mapping[str, Any]] | None = None,
        persistent_ledger: Path | str | None = None,
        active_capabilities: Iterable[str] = ("spatial",),
    ) -> None:
        root = Path(donor_root)
        self.donor_root = root
        records: dict[ResourceKey, SourceRecord] = {}
        aliases: dict[ResourceKey, ResourceKey] = {}
        _index_native_declarations(records, root)

        maps_root = root / "data/maps"
        for path in sorted(maps_root.glob("*/map.json")):
            record = json_record(path)
            name = str(record.value.get("name", path.parent.name))
            canonical = ResourceKey("map", name)
            records[canonical] = record
            map_id = record.value.get("id")
            if isinstance(map_id, str):
                aliases[ResourceKey("map", map_id.removeprefix("MAP_"))] = canonical
                aliases[ResourceKey("map", map_id)] = canonical

            script_path = path.parent / "scripts.inc"
            if script_path.exists():
                for line_number, line in enumerate(
                    script_path.read_text(encoding="utf-8").splitlines(), 1
                ):
                    match = re.match(
                        r"^\s*([A-Za-z_][A-Za-z0-9_]*)::?\s*(?:@.*)?$", line
                    )
                    if match:
                        service = ResourceKey("service", match.group(1))
                        records.setdefault(
                            service,
                            SourceRecord(
                                {
                                    "script_path": script_path.relative_to(
                                        root
                                    ).as_posix(),
                                    "script_root": root.as_posix(),
                                },
                                Provenance(script_path.as_posix(), f":{line_number}"),
                            ),
                        )

        script_sources = list((root / "data/scripts").glob("**/*.inc"))
        script_sources.extend((root / "data").glob("*.s"))
        for script_path in sorted(set(script_sources)):
            for line_number, line in enumerate(
                script_path.read_text(encoding="utf-8").splitlines(), 1
            ):
                match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)::?\s*(?:@.*)?$", line)
                if match:
                    records.setdefault(
                        ResourceKey("service", match.group(1)),
                        SourceRecord(
                            {
                                "script_path": script_path.relative_to(root).as_posix(),
                                "script_root": root.as_posix(),
                            },
                            Provenance(script_path.as_posix(), f":{line_number}"),
                        ),
                    )

        trainer_path = root / "src/data/trainers.h"
        party_path = root / "src/data/trainer_parties.h"
        if party_path.is_file():
            text = party_path.read_text(encoding="utf-8")
            starts = list(
                re.finditer(
                    r"static\s+const\s+struct\s+\w+\s+"
                    r"(sParty_[A-Za-z0-9_]+)\[\]\s*=",
                    text,
                )
            )
            for match in starts:
                body = _c_braced_value(text, match.end(), party_path, match.group(1))
                members: list[dict[str, Any]] = []
                for member_body in _direct_c_brace_blocks(body):
                    species = _c_scalar(member_body, "species", "SPECIES_")
                    if species is None:
                        continue
                    held_item = _c_scalar(member_body, "heldItem", "ITEM_")
                    moves = _c_list(member_body, "moves", "MOVE_")
                    level = _c_number(member_body, "lvl")
                    iv = _c_number(member_body, "iv")
                    members.append(
                        {
                            "species": species,
                            "held_item": held_item,
                            "moves": moves,
                            "level": level,
                            "iv": iv,
                        }
                    )
                    _require_native_leaf(
                        records, "species", species, party_path, f":{match.start()}"
                    )
                    if held_item is not None:
                        _require_native_leaf(
                            records,
                            "item",
                            held_item,
                            party_path,
                            f":{match.start()}",
                        )
                    for move in moves:
                        _require_native_leaf(
                            records, "move", move, party_path, f":{match.start()}"
                        )
                records[ResourceKey("party", match.group(1))] = SourceRecord(
                    {"members": members},
                    Provenance(party_path.as_posix(), f":{match.start()}"),
                )
        if trainer_path.is_file():
            text = trainer_path.read_text(encoding="utf-8")
            starts = list(
                re.finditer(r"^\s*\[(TRAINER_[A-Za-z0-9_]+)\]\s*=", text, re.MULTILINE)
            )
            for index, match in enumerate(starts):
                end = (
                    starts[index + 1].start() if index + 1 < len(starts) else len(text)
                )
                block = text[match.start() : end]
                parties = tuple(
                    dict.fromkeys(re.findall(r"\b(sParty_[A-Za-z0-9_]+)\b", block))
                )
                trainer_pic = _c_scalar(block, "trainerPic", "TRAINER_PIC_")
                encounter_music = _c_scalar(
                    block, "encounterMusic_gender", "TRAINER_ENCOUNTER_MUSIC_"
                )
                trainer_class = _c_scalar(block, "trainerClass", "TRAINER_CLASS_")
                items = _c_list(block, "items", "ITEM_")
                trainer_name = _c_string(block, "trainerName")
                double_battle = _c_token(block, "doubleBattle")
                ai_flags = _c_expression(block, "aiFlags")
                party_format_match = re.search(
                    r"\.party\s*=\s*([A-Z][A-Z0-9_]*)\s*\(", block
                )
                party_format = (
                    party_format_match.group(1) if party_format_match else None
                )
                for asset in (trainer_pic, encounter_music):
                    if asset is not None:
                        _require_native_leaf(
                            records,
                            "asset",
                            asset,
                            trainer_path,
                            f":{match.start()}",
                        )
                if trainer_class is not None:
                    _require_native_leaf(
                        records,
                        "trainer-class",
                        trainer_class,
                        trainer_path,
                        f":{match.start()}",
                    )
                for item in items:
                    _require_native_leaf(
                        records, "item", item, trainer_path, f":{match.start()}"
                    )
                records[ResourceKey("trainer", match.group(1))] = SourceRecord(
                    {
                        "parties": parties,
                        "trainer_pic": trainer_pic,
                        "encounter_music": encounter_music,
                        "trainer_class": trainer_class,
                        "items": items,
                        "trainer_name": trainer_name,
                        "double_battle": double_battle,
                        "ai_flags": ai_flags,
                        "gender": "Female" if "F_TRAINER_FEMALE" in block else "Male",
                        "party_format": party_format,
                    },
                    Provenance(trainer_path.as_posix(), f":{match.start()}"),
                )
        encounters_path = root / "src/data/wild_encounters.json"
        if encounters_path.is_file():
            document = json.loads(encounters_path.read_text(encoding="utf-8"))
            for group in document.get("wild_encounter_groups", []):
                for index, encounter in enumerate(group.get("encounters", [])):
                    if not isinstance(encounter, Mapping):
                        continue
                    name = encounter.get("base_label") or encounter.get("map")
                    map_name = encounter.get("map")
                    if isinstance(name, str) and isinstance(map_name, str):
                        habitat_fields = {
                            "land_mons",
                            "water_mons",
                            "fishing_mons",
                            "rock_smash_mons",
                            "hidden_mons",
                        }
                        unknown_fields = set(encounter) - {
                            "map",
                            "base_label",
                            *habitat_fields,
                        }
                        if unknown_fields:
                            raise ContentPortError(
                                f"{encounters_path}/{name}/{index}: unknown encounter "
                                f"field {sorted(unknown_fields)[0]!r}"
                            )
                        species_values: set[str] = set()
                        for habitat in sorted(habitat_fields & set(encounter)):
                            habitat_value = encounter[habitat]
                            if not isinstance(habitat_value, Mapping) or set(
                                habitat_value
                            ) != {"encounter_rate", "mons"}:
                                raise ContentPortError(
                                    f"{encounters_path}/{name}/{habitat}: malformed "
                                    "habitat record"
                                )
                            mons = habitat_value["mons"]
                            if not isinstance(mons, list):
                                raise ContentPortError(
                                    f"{encounters_path}/{name}/{habitat}/mons: "
                                    "must be a list"
                                )
                            for mon_index, mon in enumerate(mons):
                                if not isinstance(mon, Mapping) or set(mon) != {
                                    "min_level",
                                    "max_level",
                                    "species",
                                }:
                                    raise ContentPortError(
                                        f"{encounters_path}/{name}/{habitat}/mons/"
                                        f"{mon_index}: malformed encounter member"
                                    )
                                symbol = mon["species"]
                                if not isinstance(symbol, str):
                                    raise ContentPortError(
                                        f"{encounters_path}/{name}/{habitat}/mons/"
                                        f"{mon_index}/species: must be a string"
                                    )
                                species_values.add(symbol)
                        species = sorted(species_values)
                        for symbol in species:
                            _require_native_leaf(
                                records,
                                "species",
                                symbol,
                                encounters_path,
                                f"/{name}/{index}/species",
                            )
                        records[ResourceKey("encounter", name)] = SourceRecord(
                            {
                                "maps": [map_name],
                                "species": species,
                                "profile": copy.deepcopy(dict(encounter)),
                            },
                            Provenance(encounters_path.as_posix(), f"/{name}/{index}"),
                        )
                        raw_map_key = ResourceKey("map", map_name)
                        map_key = aliases.get(
                            raw_map_key,
                            aliases.get(
                                ResourceKey("map", map_name.removeprefix("MAP_")),
                                raw_map_key,
                            ),
                        )
                        map_record = records.get(map_key)
                        if map_record is None:
                            raise ContentPortError(
                                f"{encounters_path}/{name}/{index}: encounter map "
                                f"{map_name} is not indexed"
                            )
                        map_value = dict(map_record.value)
                        encounter_roots = list(map_value.get("_encounter_roots", ()))
                        if name in encounter_roots:
                            raise ContentPortError(
                                f"{encounters_path}/{name}/{index}: duplicate "
                                "encounter root identity"
                            )
                        encounter_roots.append(name)
                        map_value["_encounter_roots"] = sorted(encounter_roots)
                        records[map_key] = SourceRecord(
                            map_value, map_record.provenance
                        )

        # Pair every trainer object with its script, text, and typed trainer
        # dependency. Capability policy selects from these records later; it
        # never roots every trainer object on a map implicitly.
        from .semantics import parse_scripts

        script_cache: dict[str, Any] = {}
        trainer_events: dict[ResourceKey, TrainerEventRecord] = {}
        for map_key, map_record in tuple(records.items()):
            if map_key.domain != "map":
                continue
            event_roots: list[str] = []
            for event_index, event in enumerate(
                map_record.value.get("object_events", []) or []
            ):
                if not isinstance(event, Mapping) or event.get("trainer_type") in {
                    None,
                    0,
                    "TRAINER_TYPE_NONE",
                }:
                    continue
                label = event.get("script")
                service = (
                    records.get(ResourceKey("service", label))
                    if isinstance(label, str)
                    else None
                )
                if service is None:
                    raise ContentPortError(
                        f"{map_record.provenance.path}: trainer event script "
                        f"{label!r} is not indexed"
                    )
                script_path = service.value.get("script_path")
                if not isinstance(script_path, str):
                    raise ContentPortError(
                        f"{service.provenance.path}: trainer script has no source"
                    )
                program = script_cache.get(script_path)
                if program is None:
                    try:
                        program = parse_scripts([script_path], root=root)
                    except ContentPortError as error:
                        if "duplicate label" not in str(error):
                            raise
                        program = False
                    script_cache[script_path] = program
                if program is False:
                    continue
                instructions = program.labels.get(label)
                if instructions is None:
                    raise ContentPortError(
                        f"{service.provenance.path}: trainer label {label} is missing"
                    )
                trainer_roots: list[str] = []
                text_labels: list[str] = []
                typed_instructions: list[TrainerScriptInstruction] = []
                for instruction in instructions:
                    typed_instructions.append(
                        TrainerScriptInstruction(
                            instruction.command, instruction.operands
                        )
                    )
                    opcode = program.opcodes.get(instruction.command)
                    if opcode is not None:
                        for domain, operand_index in opcode.dependencies:
                            if domain != "trainer":
                                continue
                            if operand_index >= len(instruction.operands):
                                raise ContentPortError(
                                    f"{instruction.source}:{instruction.line}: "
                                    "trainer dependency operand is missing"
                                )
                            trainer_roots.append(instruction.operands[operand_index])
                    if instruction.command == "trainerbattle_single":
                        text_labels.extend(instruction.operands[1:3])
                    elif instruction.command == "msgbox" and instruction.operands:
                        text_labels.append(instruction.operands[0])
                if not trainer_roots:
                    # Some expansion objects use a trainer-shaped movement field
                    # but dispatch dynamic facilities without a trainer operand.
                    # They are not selectable paired trainer events.
                    continue
                texts: list[TrainerText] = []
                for text_label in dict.fromkeys(text_labels):
                    fragments = program.texts.get(text_label)
                    if fragments is None:
                        continue
                    texts.append(TrainerText(text_label, fragments))
                identity = f"{map_key.name}/{event_index}/{label}"
                event_key = ResourceKey("trainer-event", identity)
                typed = TrainerEventRecord(
                    map_key.name,
                    event_index,
                    MappingProxyType(dict(event)),
                    label,
                    tuple(dict.fromkeys(trainer_roots)),
                    tuple(typed_instructions),
                    tuple(texts),
                )
                trainer_events[event_key] = typed
                records[event_key] = SourceRecord(
                    {
                        "service": label,
                        "trainers": list(typed.trainers),
                        "object_index": event_index,
                        "instructions": [
                            {
                                "command": instruction.command,
                                "operands": list(instruction.operands),
                            }
                            for instruction in typed.instructions
                        ],
                        "texts": [
                            {
                                "label": text.label,
                                "fragments": list(text.fragments),
                            }
                            for text in typed.texts
                        ],
                    },
                    service.provenance,
                )
                event_roots.append(identity)
            if event_roots:
                map_value = dict(map_record.value)
                map_value["_trainer_event_roots"] = event_roots
                records[map_key] = SourceRecord(map_value, map_record.provenance)

        layouts_path = root / "data/layouts/layouts.json"
        if layouts_path.exists():
            document = json.loads(layouts_path.read_text(encoding="utf-8"))
            for index, layout in enumerate(document.get("layouts", [])):
                if not isinstance(layout, Mapping) or not isinstance(
                    layout.get("id"), str
                ):
                    raise ContentPortError(
                        f"{layouts_path}/layouts/{index}: malformed layout"
                    )
                key = ResourceKey("layout", layout["id"])
                records[key] = SourceRecord(
                    layout, Provenance(layouts_path.as_posix(), f"/layouts/{index}")
                )
                for field_name in ("border_filepath", "blockdata_filepath"):
                    asset_name = layout.get(field_name)
                    if isinstance(asset_name, str) and (root / asset_name).is_file():
                        records.setdefault(
                            ResourceKey("asset", asset_name),
                            SourceRecord(
                                {}, Provenance((root / asset_name).as_posix())
                            ),
                        )

        # Assets are semantic leaves here. Renderers own their byte-level source
        # and conversion metadata; the graph still proves every referenced path
        # or tileset symbol exists in the donor checkout.
        for path in (
            sorted((root / "data/tilesets").glob("**/*"))
            if (root / "data/tilesets").exists()
            else ()
        ):
            if path.is_file():
                records.setdefault(
                    ResourceKey("asset", path.relative_to(root).as_posix()),
                    SourceRecord({}, Provenance(path.as_posix())),
                )
        headers = root / "data/tilesets/headers.inc"
        header_sources = [headers, root / "src/data/tilesets/headers.h"]
        for headers in header_sources:
            if headers.exists():
                for line_number, line in enumerate(
                    headers.read_text(encoding="utf-8").splitlines(), 1
                ):
                    match = re.search(r"\b(gTileset_[A-Za-z0-9_]+)\b\s*(?::|=)", line)
                    if not match:
                        continue
                    records[ResourceKey("asset", match.group(1))] = SourceRecord(
                        {}, Provenance(headers.as_posix(), f":{line_number}")
                    )

        if persistent_ledger is not None:
            ledger_path = Path(persistent_ledger)
            document = json.loads(ledger_path.read_text(encoding="utf-8"))
            for index, binding in enumerate(document.get("entries", [])):
                if isinstance(binding, Mapping) and isinstance(
                    binding.get("symbol"), str
                ):
                    records.setdefault(
                        ResourceKey("binding", binding["symbol"]),
                        SourceRecord(
                            binding,
                            Provenance(ledger_path.as_posix(), f"/entries/{index}"),
                        ),
                    )
        for name, capability in sorted((capabilities or {}).items()):
            records[ResourceKey("capability", name)] = SourceRecord(
                capability, Provenance("<descriptor>", f"/capabilities/{name}")
            )
        self._trainer_events = MappingProxyType(dict(trainer_events))
        super().__init__(
            records=records, aliases=aliases, active_capabilities=active_capabilities
        )

    def trainer_event(self, key: ResourceKey) -> TrainerEventRecord:
        try:
            return self._trainer_events[key]
        except KeyError as error:
            raise ContentPortError(f"{key}: typed trainer event is missing") from error


def _canonical_trainer_identities(
    root: Path,
    map_names: Iterable[str],
    additional_identities: Iterable[str] = (),
) -> tuple[str, ...]:
    """Return resident trainerbattle dependencies in donor numeric order."""

    from .semantics import parse_scripts

    referenced = set(additional_identities)
    for map_name in map_names:
        script_path = Path("data/maps") / map_name / "scripts.inc"
        if not (root / script_path).is_file():
            continue
        program = parse_scripts((script_path,), root=root)
        for instructions in program.labels.values():
            for instruction in instructions:
                if not instruction.command.startswith("trainerbattle_"):
                    continue
                if not instruction.operands:
                    raise ContentPortError(
                        f"{instruction.source}:{instruction.line}: trainerbattle "
                        "dependency operand is missing"
                    )
                referenced.add(instruction.operands[0])

    opponents_path = root / "include/constants/opponents.h"
    try:
        lines = opponents_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ContentPortError(
            f"cannot read trainer identity declarations {opponents_path}: {error}"
        ) from error
    numeric_values: dict[str, int] = {}
    for line_number, line in enumerate(lines, 1):
        match = re.match(r"^\s*#\s*define\s+(TRAINER_[A-Z0-9_]+)\s+(\d+)\b", line)
        if match is None or match.group(1) not in referenced:
            continue
        identity = match.group(1)
        if identity in numeric_values:
            raise ContentPortError(
                f"{opponents_path}:{line_number}: duplicate trainer identity {identity}"
            )
        numeric_values[identity] = int(match.group(2))
    missing = sorted(referenced - set(numeric_values))
    if missing:
        raise ContentPortError(
            f"{opponents_path}: resident trainer identity {missing[0]} has no numeric declaration"
        )
    by_number: dict[int, str] = {}
    for identity, number in numeric_values.items():
        previous = by_number.setdefault(number, identity)
        if previous != identity:
            raise ContentPortError(
                f"{opponents_path}: resident trainers {previous} and {identity} "
                f"share numeric identity {number}"
            )
    return tuple(
        identity
        for identity, _ in sorted(numeric_values.items(), key=lambda item: item[1])
    )


def _authenticated_trainer_inventory(
    descriptor: PortDescriptor,
    content: ExpansionSourceContext,
    canonical_maps: tuple[str, ...],
    fallback_maps: set[str],
) -> TrainerInventory:
    """Authenticate and load the authored inventory without enabling trainers."""

    content_maps: list[str] = []
    authenticated_events: dict[str, Mapping[str, tuple[str, ...]]] = {}
    authenticated_pairs: dict[str, list[str]] = {}
    resident_event_trainers: set[str] = set()
    for map_name in canonical_maps:
        if map_name in fallback_maps:
            authenticated_events[map_name] = MappingProxyType({})
            continue
        content_maps.append(map_name)
        map_record = content.load(ResourceKey("map", map_name))
        events: dict[str, tuple[str, ...]] = {}
        for identity in map_record.value.get("_trainer_event_roots", ()):
            event = content.trainer_event(ResourceKey("trainer-event", str(identity)))
            events[str(identity)] = event.trainers
            resident_event_trainers.update(event.trainers)
            if any(
                instruction.command == "trainerbattle_double"
                for instruction in event.instructions
            ):
                if len(event.trainers) != 1:
                    raise ContentPortError(
                        f"{identity}: paired double must reference one shared trainer identity"
                    )
                authenticated_pairs.setdefault(event.trainers[0], []).append(
                    str(identity)
                )
        authenticated_events[map_name] = MappingProxyType(events)

    canonical_identities = _canonical_trainer_identities(
        descriptor.donor("content").root,
        content_maps,
        resident_event_trainers,
    )
    expected = descriptor.expected_trainer_inventory
    expected_identities = expected["identities"]
    expected_events = expected["events"]
    assert isinstance(expected_identities, Mapping)
    assert isinstance(expected_events, Mapping)
    inventory = load_trainer_inventory(
        descriptor.trainer_policy_path,
        canonical_identities,
        canonical_maps,
        MappingProxyType(authenticated_events),
        content_maps,
        MappingProxyType(
            {
                identity: tuple(events)
                for identity, events in authenticated_pairs.items()
            }
        ),
        expectations=InventoryExpectations(
            identities=int(expected_identities["count"]),
            placements=int(expected_events["count"]),
            identity_classifications=expected["identityClassifications"],
            admitted_identities=int(expected["admittedIdentities"]),
            admitted_placements=int(expected["admittedEvents"]),
        ),
        expected_digest=str(descriptor.expected_trainer_inventory["documentDigest"]),
    )
    sentinels = {
        "identities": (
            len(inventory.identities),
            inventory.identity_membership_digest,
        ),
        "events": (
            len(inventory.placements),
            inventory.placement_membership_digest,
        ),
    }
    for domain, (count, digest) in sentinels.items():
        expected_domain = expected[domain]
        assert isinstance(expected_domain, Mapping)
        if count != expected_domain["count"]:
            raise ContentPortError(
                f"trainer {domain} count {count} != reviewed {expected_domain['count']}"
            )
        if digest != expected_domain["digest"]:
            raise ContentPortError(
                f"trainer {domain} digest {digest} != reviewed {expected_domain['digest']}"
            )
    if inventory.digest != expected["documentDigest"]:
        raise ContentPortError(
            f"trainer inventory document digest {inventory.digest} != reviewed "
            f"{expected['documentDigest']}"
        )
    affected_admitted_maps = {
        placement.map_name for placement in inventory.placements if placement.admitted
    }
    if len(affected_admitted_maps) != expected["affectedAdmittedMaps"]:
        raise ContentPortError(
            "trainer affected admitted map count "
            f"{len(affected_admitted_maps)} != reviewed "
            f"{expected['affectedAdmittedMaps']}"
        )
    return inventory


def _trainerproc_constant(prefix: str, display: str) -> str:
    if prefix == "TRAINER_CLASS" and display.endswith(" Johto"):
        prefix = "JOHTO_TRAINER_CLASS"
        display = display.removesuffix(" Johto")
    elif prefix == "TRAINER_PIC" and display.endswith(" HG"):
        prefix = "JOHTO_TRAINER_PIC"
        display = display.removesuffix(" HG")
    suffix = "".join(
        char.upper() if char.isascii() and char.isalnum() else "_"
        for char in display
        if char != "'"
    )
    return f"{prefix}_{suffix or 'NONE'}"


def _validate_trainer_projection_rule(
    identity: str, projection: TrainerProjection, trainer: Mapping[str, Any]
) -> None:
    donor_class = trainer.get("trainer_class")
    donor_pic = trainer.get("trainer_pic")
    donor_music = trainer.get("encounter_music")
    expected = {
        "class": JOHTO_CLASS_PROJECTIONS.get(donor_class, donor_class),
        "pic": TRAINER_PIC_PROJECTIONS.get(donor_pic, donor_pic),
        "music": TRAINER_MUSIC_PROJECTIONS.get(donor_music),
        "gender": "Female" if donor_pic in FEMALE_TRAINER_PICS else "Male",
        "ai": "AI_FLAG_CHECK_BAD_MOVE",
    }
    actual = {
        "class": _trainerproc_constant("TRAINER_CLASS", projection.trainer_class),
        "pic": _trainerproc_constant("TRAINER_PIC", projection.pic),
        "music": _trainerproc_constant("TRAINER_ENCOUNTER_MUSIC", projection.music),
        "gender": projection.gender,
        "ai": _trainerproc_constant("AI_FLAG", projection.ai),
    }
    for field_name in expected:
        if actual[field_name] != expected[field_name]:
            raise ContentPortError(
                f"trainer:{identity}/{field_name}: projection differs from reviewed donor mapping"
            )
    if projection.reward != "preserve" or projection.party != "preserve":
        raise ContentPortError(
            f"trainer:{identity}: reward and party projections must preserve donor facts"
        )


def _validate_overworld_graphic_rule(
    identity: str, donor_graphic: str, donor_class: str, target_graphic: str
) -> None:
    if donor_graphic == "OBJ_EVENT_GFX_SUPER_NERD":
        expected = (
            "OBJ_EVENT_GFX_MANIAC"
            if donor_class == "TRAINER_CLASS_POKEMANIAC"
            else "OBJ_EVENT_GFX_SCIENTIST_1"
            if donor_class == "TRAINER_CLASS_SUPER_NERD"
            else None
        )
    else:
        expected = TRAINER_GRAPHIC_PROJECTIONS.get(donor_graphic, donor_graphic)
    if target_graphic != expected:
        raise ContentPortError(
            f"trainer-event:{identity}/overworldGraphic: "
            "projection differs from reviewed donor mapping"
        )


def _declared_constants(path: Path, prefix: str) -> frozenset[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ContentPortError(
            f"cannot read target declarations {path}: {error}"
        ) from error
    return frozenset(re.findall(rf"\b{re.escape(prefix)}_[A-Z0-9_]+\b", text))


def _trainer_class_money(path: Path, *, target: bool) -> Mapping[str, int]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ContentPortError(
            f"cannot read trainer reward authority {path}: {error}"
        ) from error
    if target:
        records = re.findall(
            r"\[((?:JOHTO_)?TRAINER_CLASS_[A-Z0-9_]+)\]\s*=\s*"
            r"\{\s*_\(\"[^\"]*\"\)(?:,\s*(\d+))?",
            text,
        )
        return MappingProxyType({symbol: int(raw or 0) or 5 for symbol, raw in records})
    records = re.findall(r"\{(TRAINER_CLASS_[A-Z0-9_]+),\s*(\d+)\}", text)
    return MappingProxyType({symbol: int(raw) for symbol, raw in records})


def _authenticate_trainer_projection_authority(
    inventory: TrainerInventory,
    content: ExpansionSourceContext,
    target_root: Path,
    ledger: Any,
    enabled_trainers: frozenset[str],
) -> None:
    """Bind authored projections to donor facts and target declarations."""

    trainer_constants = target_root / "include/constants/trainers.h"
    target_classes = _declared_constants(
        trainer_constants, "TRAINER_CLASS"
    ) | _declared_constants(trainer_constants, "JOHTO_TRAINER_CLASS")
    target_pics = _declared_constants(
        trainer_constants, "TRAINER_PIC"
    ) | _declared_constants(trainer_constants, "JOHTO_TRAINER_PIC")
    target_music = _declared_constants(
        target_root / "include/constants/trainers.h", "TRAINER_ENCOUNTER_MUSIC"
    )
    target_ai = _declared_constants(
        target_root / "include/constants/battle_ai.h", "AI_FLAG"
    )
    target_graphics = _declared_constants(
        target_root / "include/constants/event_objects.h", "OBJ_EVENT_GFX"
    )
    donor_trainer_constants = content.donor_root / "include/constants/trainers.h"
    donor_classes = _declared_constants(donor_trainer_constants, "TRAINER_CLASS")
    donor_pics = _declared_constants(donor_trainer_constants, "TRAINER_PIC")
    donor_music = _declared_constants(
        donor_trainer_constants, "TRAINER_ENCOUNTER_MUSIC"
    )
    donor_graphics = _declared_constants(
        content.donor_root / "include/constants/event_objects.h", "OBJ_EVENT_GFX"
    )
    donor_money = _trainer_class_money(
        content.donor_root / "src/battle_main.c", target=False
    )
    target_money = _trainer_class_money(target_root / "src/battle_main.c", target=True)
    authenticated: list[str] = []
    donor_class_by_trainer: dict[str, str] = {}
    for identity in inventory.identities:
        projection = identity.projection
        if projection is None:
            continue
        authenticated.append(identity.trainer)
        if identity.trainer in enabled_trainers:
            ledger.resolve(projection.target, domain="trainerIds")
        trainer = content.load(ResourceKey("trainer", identity.trainer)).value
        for field_name, declarations in (
            ("trainer_class", donor_classes),
            ("trainer_pic", donor_pics),
            ("encounter_music", donor_music),
        ):
            donor_symbol = trainer.get(field_name)
            if donor_symbol not in declarations:
                raise ContentPortError(
                    f"trainer:{identity.trainer}/{field_name}: donor authority is invalid"
                )
        donor_class_by_trainer[identity.trainer] = trainer["trainer_class"]
        if trainer.get("gender") not in {"Male", "Female"}:
            raise ContentPortError(
                f"trainer:{identity.trainer}/gender: donor gender authority is invalid"
            )
        if tuple(trainer.get("ai_flags", ())) != ("AI_SCRIPT_CHECK_BAD_MOVE",):
            raise ContentPortError(
                f"trainer:{identity.trainer}/ai_flags: projection differs from donor"
            )
        if (
            trainer.get("items")
            or trainer.get("party_format") != "NO_ITEM_DEFAULT_MOVES"
        ):
            raise ContentPortError(
                f"trainer:{identity.trainer}: preserve projection requires a default donor party"
            )
        parties = tuple(trainer.get("parties", ()))
        if len(parties) != 1:
            raise ContentPortError(
                f"trainer:{identity.trainer}: preserve projection requires exactly one donor party"
            )
        content.load(ResourceKey("party", parties[0]))
        _validate_trainer_projection_rule(identity.trainer, projection, trainer)
        target_class = _trainerproc_constant("TRAINER_CLASS", projection.trainer_class)
        target_pic = _trainerproc_constant("TRAINER_PIC", projection.pic)
        target_music_symbol = _trainerproc_constant(
            "TRAINER_ENCOUNTER_MUSIC", projection.music
        )
        target_ai_symbol = _trainerproc_constant("AI_FLAG", projection.ai)
        for symbol, declarations, field_name in (
            (target_class, target_classes, "class"),
            (target_pic, target_pics, "pic"),
            (target_music_symbol, target_music, "music"),
            (target_ai_symbol, target_ai, "ai"),
        ):
            if symbol not in declarations:
                raise ContentPortError(
                    f"trainer:{identity.trainer}/{field_name}: target symbol {symbol} is absent"
                )
        donor_class = trainer.get("trainer_class")
        if not isinstance(donor_class, str):
            raise ContentPortError(
                f"trainer:{identity.trainer}/class: donor reward authority is absent"
            )
        if target_class not in target_money:
            raise ContentPortError(
                f"trainer:{identity.trainer}/class: target reward authority is absent"
            )
        donor_reward = donor_money.get(donor_class, 5)
        if donor_reward != target_money[target_class]:
            raise ContentPortError(
                f"trainer:{identity.trainer}/reward: class money differs "
                f"({donor_reward} != {target_money[target_class]})"
            )
    require_projection_exact_cover(
        inventory, authenticated, owner="authenticated trainer projection surface"
    )
    for placement in inventory.placements:
        if not placement.admitted:
            continue
        event = content.trainer_event(ResourceKey("trainer-event", placement.identity))
        donor_graphic = event.object_event.get("graphics_id")
        if donor_graphic not in donor_graphics:
            raise ContentPortError(
                f"trainer-event:{placement.identity}: donor overworld graphic authority is invalid"
            )
        _validate_overworld_graphic_rule(
            placement.identity,
            donor_graphic,
            donor_class_by_trainer[placement.trainer],
            placement.overworld_graphic,
        )
        if placement.overworld_graphic not in target_graphics:
            raise ContentPortError(
                f"trainer-event:{placement.identity}: target overworld graphic "
                f"{placement.overworld_graphic} is absent"
            )


def json_record(path: Path, pointer: str = "") -> SourceRecord:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentPortError(f"{path}: invalid source JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ContentPortError(f"{path}: source record must be an object")
    return SourceRecord(value, Provenance(path.as_posix(), pointer))


def _key(
    domain: str, value: Any, *, prefixes: tuple[str, ...] = ()
) -> ResourceKey | None:
    if (
        not isinstance(value, str)
        or not value
        or value in {"0", "NULL", "NONE", "MAP_DYNAMIC", "MAP_NONE", "MAP_UNDEFINED"}
    ):
        return None
    for prefix in prefixes:
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    return ResourceKey(domain, value)


def _edge(
    key: ResourceKey,
    domain: str,
    value: Any,
    record: SourceRecord,
    pointer: str,
    *,
    prefixes: tuple[str, ...] = (),
    role: str = "dependency",
) -> SourceEdge | None:
    target = _key(domain, value, prefixes=prefixes)
    if target is None:
        return None
    return SourceEdge(key, target, Provenance(record.provenance.path, pointer), role)


def _array(record: SourceRecord, field_name: str) -> Iterable[Any]:
    value = record.value.get(field_name, ())
    if value is None or value == 0 or value == () or value == []:
        return ()
    if not isinstance(value, list):
        raise ContentPortError(
            f"{record.provenance.path}/{field_name}: must be an array or 0"
        )
    return value


def extract_map_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    value = record.value
    candidates: list[SourceEdge | None] = [
        _edge(key, "layout", value.get("layout"), record, "/layout"),
        _edge(key, "encounter", value.get("encounter"), record, "/encounter")
        if context.supports("encounters", key)
        else None,
    ]
    if context.supports("encounters", key):
        for index, encounter in enumerate(value.get("_encounter_roots", ())):
            candidates.append(
                _edge(
                    key,
                    "encounter",
                    encounter,
                    record,
                    f"/_encounter_roots/{index}",
                    role="encounter",
                )
            )
    for index, connection in enumerate(_array(record, "connections")):
        if isinstance(connection, Mapping):
            candidates.append(
                _edge(
                    key,
                    "map",
                    connection.get("map"),
                    record,
                    f"/connections/{index}/map",
                    prefixes=("MAP_",),
                    role="connection",
                )
            )
    for index, warp in enumerate(_array(record, "warp_events")):
        if isinstance(warp, Mapping):
            candidates.append(
                _edge(
                    key,
                    "map",
                    warp.get("dest_map"),
                    record,
                    f"/warp_events/{index}/dest_map",
                    prefixes=("MAP_",),
                    role="warp",
                )
            )
    if context.supports("trainers", key):
        for index, trainer_event in enumerate(
            record.value.get("_trainer_event_roots", ())
        ):
            candidates.append(
                _edge(
                    key,
                    "trainer-event",
                    trainer_event,
                    record,
                    f"/_trainer_event_roots/{index}",
                    role="trainer",
                )
            )
    if not context.supports("events", key) and not context.supports("trainers", key):
        return tuple(edge for edge in candidates if edge is not None)
    for collection in ("object_events", "coord_events", "bg_events"):
        for index, event in enumerate(_array(record, collection)):
            if not isinstance(event, Mapping):
                continue
            if context.supports("events", key):
                candidates.append(
                    _edge(
                        key,
                        "service",
                        event.get("script"),
                        record,
                        f"/{collection}/{index}/script",
                        role="event",
                    )
                )
                for field_name, prefix in (("flag", "FLAG_"), ("var", "VAR_")):
                    symbol = event.get(field_name)
                    if isinstance(symbol, str) and symbol.startswith(prefix):
                        candidates.append(
                            _edge(
                                key,
                                "binding",
                                symbol,
                                record,
                                f"/{collection}/{index}/{field_name}",
                                role="persistent",
                            )
                        )
            if context.supports("trainers", key) and event.get("trainer") is not None:
                candidates.append(
                    _edge(
                        key,
                        "trainer",
                        event.get("trainer"),
                        record,
                        f"/{collection}/{index}/trainer",
                        role="trainer",
                    )
                )
    return tuple(edge for edge in candidates if edge is not None)


def extract_layout_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context
    candidates: list[SourceEdge | None] = []
    authorities = record.value.get("_asset_authorities", {})
    for field_name in ("primary_tileset", "secondary_tileset"):
        asset = record.value.get(field_name)
        role = authorities.get(field_name) if isinstance(authorities, Mapping) else None
        if isinstance(asset, str) and isinstance(role, str):
            asset = f"{role}:{asset}"
        candidates.append(
            _edge(
                key,
                "asset",
                asset,
                record,
                f"/{field_name}",
                role="tileset",
            )
        )
    for field_name in ("border_filepath", "blockdata_filepath"):
        asset = record.value.get(field_name)
        role = authorities.get(field_name) if isinstance(authorities, Mapping) else None
        if isinstance(asset, str) and isinstance(role, str):
            asset = f"{role}:{asset}"
        candidates.append(
            _edge(
                key,
                "asset",
                asset,
                record,
                f"/{field_name}",
                role="layout-data",
            )
        )
    return tuple(edge for edge in candidates if edge is not None)


def extract_trainer_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context
    result: list[SourceEdge] = []
    parties = record.value.get("parties", record.value.get("party"))
    if isinstance(parties, str):
        parties = [parties]
    if isinstance(parties, Iterable) and not isinstance(parties, (str, bytes, Mapping)):
        for index, party in enumerate(parties):
            edge = _edge(key, "party", party, record, f"/parties/{index}", role="party")
            if edge:
                result.append(edge)
    for field_name in (
        "front_pic",
        "back_pic",
        "palette",
        "trainer_pic",
        "encounter_music",
    ):
        edge = _edge(
            key,
            "asset",
            record.value.get(field_name),
            record,
            f"/{field_name}",
            role="presentation",
        )
        if edge:
            result.append(edge)
    for field_name, domain in (("trainer_class", "trainer-class"), ("items", "item")):
        values = record.value.get(field_name, ())
        if isinstance(values, str):
            values = [values]
        if values is None:
            continue
        if not isinstance(values, Iterable) or isinstance(values, (bytes, Mapping)):
            raise ContentPortError(
                f"{record.provenance.path}/{field_name}: must be a string or list"
            )
        for index, value in enumerate(values):
            edge = _edge(
                key,
                domain,
                value,
                record,
                f"/{field_name}/{index}",
                role=field_name,
            )
            if edge:
                result.append(edge)
    return tuple(result)


def extract_trainer_event_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context
    result: list[SourceEdge] = []
    service = _edge(
        key, "service", record.value.get("service"), record, "/service", role="script"
    )
    if service:
        result.append(service)
    for index, trainer in enumerate(record.value.get("trainers", ())):
        edge = _edge(
            key, "trainer", trainer, record, f"/trainers/{index}", role="trainer"
        )
        if edge:
            result.append(edge)
    return tuple(result)


def extract_party_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context
    result: list[SourceEdge] = []
    for index, member in enumerate(
        record.value.get("members", record.value.get("pokemon", ()))
    ):
        if not isinstance(member, Mapping):
            continue
        for field_name in ("sprite", "icon", "cry"):
            edge = _edge(
                key,
                "asset",
                member.get(field_name),
                record,
                f"/members/{index}/{field_name}",
                role="presentation",
            )
            if edge:
                result.append(edge)
        for field_name, domain in (
            ("species", "species"),
            ("held_item", "item"),
            ("item", "item"),
            ("moves", "move"),
        ):
            values = member.get(field_name)
            if values is None:
                continue
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, Iterable) or isinstance(values, (bytes, Mapping)):
                raise ContentPortError(
                    f"{record.provenance.path}/members/{index}/{field_name}: "
                    "must be a string or list"
                )
            for value_index, value in enumerate(values):
                edge = _edge(
                    key,
                    domain,
                    value,
                    record,
                    f"/members/{index}/{field_name}/{value_index}",
                    role=field_name,
                )
                if edge:
                    result.append(edge)
    return tuple(result)


def extract_encounter_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context
    result: list[SourceEdge] = []
    maps = record.value.get("maps", ())
    if isinstance(maps, str):
        maps = [maps]
    for index, name in enumerate(maps):
        edge = _edge(
            key,
            "map",
            name,
            record,
            f"/maps/{index}",
            prefixes=("MAP_",),
            role="encounter-map",
        )
        if edge:
            result.append(edge)
    species = record.value.get("species", ())
    if isinstance(species, str):
        species = [species]
    if not isinstance(species, Iterable) or isinstance(species, (bytes, Mapping)):
        raise ContentPortError(f"{record.provenance.path}/species: must be a list")
    for index, name in enumerate(species):
        edge = _edge(
            key,
            "species",
            name,
            record,
            f"/species/{index}",
            role="encounter-species",
        )
        if edge:
            result.append(edge)
    return tuple(result)


def _generic_declared_edges(
    key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    """Read typed native references, never an opaque dependency graph."""
    result: list[SourceEdge] = []
    refs = record.value.get("references", {})
    if not isinstance(refs, Mapping):
        raise ContentPortError(f"{record.provenance}: /references must be an object")
    for domain, names in sorted(refs.items()):
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, list):
            raise ContentPortError(
                f"{record.provenance.path}/references/{domain}: must be a list"
            )
        for index, name in enumerate(names):
            edge = _edge(key, domain, name, record, f"/references/{domain}/{index}")
            if edge:
                result.append(edge)
    return tuple(result)


def extract_service_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context
    result = list(_generic_declared_edges(key, record))
    instructions = record.value.get("instructions")
    script_path = record.value.get("script_path")
    script_root = record.value.get("script_root")
    if (
        instructions is None
        and isinstance(script_path, str)
        and isinstance(script_root, str)
    ):
        from .semantics import parse_scripts

        program = parse_scripts([script_path], root=script_root, opcodes={})
        native = program.labels.get(key.name)
        if native is None:
            raise ContentPortError(
                f"{record.provenance.path}: indexed script label {key.name} is missing"
            )
        instructions = [
            {
                "command": instruction.command,
                "operands": list(instruction.operands),
                "scope": instruction.scope,
                "line": instruction.line,
            }
            for instruction in native
        ]
    if instructions is None:
        instructions = []
    if not isinstance(instructions, list):
        raise ContentPortError(f"{record.provenance.path}/instructions: must be a list")
    if not instructions:
        return tuple(result)
    from .semantics import load_opcodes

    opcodes = load_opcodes()
    for index, instruction in enumerate(instructions):
        if not isinstance(instruction, Mapping):
            raise ContentPortError(
                f"{record.provenance.path}/instructions/{index}: must be an object"
            )
        command = instruction.get("command")
        operands = instruction.get("operands")
        scope = instruction.get("scope")
        if (
            not isinstance(command, str)
            or not isinstance(operands, list)
            or not all(isinstance(value, str) for value in operands)
            or not isinstance(scope, str)
        ):
            raise ContentPortError(
                f"{record.provenance.path}/instructions/{index}: malformed instruction"
            )
        opcode = opcodes.get(command)
        if opcode is None:
            line = instruction.get("line", "?")
            raise ContentPortError(
                f"{record.provenance.path}:{line}: unknown script opcode {command}"
            )
        for call_index in opcode.calls:
            if call_index >= len(operands):
                raise ContentPortError(
                    f"{record.provenance.path}/instructions/{index}: "
                    f"{command} lacks label operand {call_index}"
                )
            target = operands[call_index]
            if target.startswith("."):
                target = f"{scope}{target}"
            edge = _edge(
                key,
                "service",
                target,
                record,
                f"/instructions/{index}/operands/{call_index}",
                role="script-call",
            )
            if edge:
                result.append(edge)
        for domain, operand_index in opcode.dependencies:
            if operand_index >= len(operands):
                raise ContentPortError(
                    f"{record.provenance.path}/instructions/{index}: "
                    f"{command} lacks dependency operand {operand_index}"
                )
            edge = _edge(
                key,
                domain,
                operands[operand_index],
                record,
                f"/instructions/{index}/operands/{operand_index}",
                role="typed-operand",
            )
            if edge:
                result.append(edge)
        for kind, operand_index in opcode.effects:
            if operand_index is None or operand_index >= len(operands):
                continue
            operand = operands[operand_index]
            if kind in {"state-read", "state-write"} and operand.startswith(
                ("FLAG_", "VAR_")
            ):
                domain, role = "binding", kind
            else:
                continue
            edge = _edge(
                key,
                domain,
                operand,
                record,
                f"/instructions/{index}/operands/{operand_index}",
                role=role,
            )
            if edge:
                result.append(edge)
    return tuple(result)


def extract_asset_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context
    return _generic_declared_edges(key, record)


def extract_capability_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context
    # Capability records name activated resources by domain. A field named
    # "dependencies" is deliberately rejected: that would be a precomputed graph.
    if "dependencies" in record.value:
        raise ContentPortError(
            f"{record.provenance.path}/dependencies: precomputed dependency graphs are forbidden"
        )
    return _generic_declared_edges(key, record)


def extract_binding_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context, key, record
    return ()


EXTRACTORS: Mapping[
    str, Callable[[SourceContext, ResourceKey, SourceRecord], Iterable[SourceEdge]]
] = {
    "map": extract_map_edges,
    "layout": extract_layout_edges,
    "trainer": extract_trainer_edges,
    "trainer-event": extract_trainer_event_edges,
    "party": extract_party_edges,
    "encounter": extract_encounter_edges,
    "service": extract_service_edges,
    "asset": extract_asset_edges,
    "capability": extract_capability_edges,
    "binding": extract_binding_edges,
    "species": extract_binding_edges,
    "move": extract_binding_edges,
    "item": extract_binding_edges,
    "trainer-class": extract_binding_edges,
}


def build_source_graph(
    context: SourceContext, roots: Iterable[ResourceKey]
) -> SourceGraph:
    resources: dict[ResourceKey, Provenance] = {}
    edges: set[SourceEdge] = set()
    pending = list(sorted({context.canonicalize(key) for key in roots}, reverse=True))
    while pending:
        key = pending.pop()
        if key in resources:
            continue
        extractor = EXTRACTORS.get(key.domain)
        if extractor is None:
            raise ContentPortError(f"unsupported source domain {key.domain}:{key.name}")
        try:
            record = context.load(key)
        except ContentPortError as exc:
            raise ContentPortError(
                f"while loading {key.domain}:{key.name}: {exc}"
            ) from exc
        resources[key] = record.provenance
        for edge in extractor(context, key, record):
            target = context.canonicalize(edge.target)
            canonical_edge = SourceEdge(edge.source, target, edge.provenance, edge.role)
            edges.add(canonical_edge)
            pending.append(target)
    return SourceGraph(
        MappingProxyType(dict(sorted(resources.items()))), tuple(sorted(edges))
    )


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw(child) for child in value]
    return copy.deepcopy(value)


def _freeze_state(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_state(child) for key, child in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_state(child) for child in value)
    return value


def _semantic_record_digest(
    authority: str, key: ResourceKey, value: Mapping[str, Any]
) -> str:
    normalized = _thaw(value)
    if key.domain == "service":
        # Snapshot roots are authenticated transport locations, not semantic
        # payload. Keeping one here makes exact-pin evidence nondeterministic.
        normalized.pop("script_root", None)
    return hashlib.sha256(
        json.dumps(
            {
                "authority": authority,
                "domain": key.domain,
                "name": key.name,
                "value": normalized,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _validate_selected_trainer_event(event: TrainerEventRecord) -> None:
    if tuple(instruction.command for instruction in event.instructions) != (
        "trainerbattle_single",
        "msgbox",
        "end",
    ) or tuple(len(instruction.operands) for instruction in event.instructions) != (
        3,
        2,
        0,
    ):
        raise ContentPortError(
            f"{event.script_name}: unsupported selected trainer script shape"
        )
    expected_text_labels = (
        event.instructions[0].operands[1],
        event.instructions[0].operands[2],
        event.instructions[1].operands[0],
    )
    if len(set(expected_text_labels)) != len(expected_text_labels):
        raise ContentPortError(
            f"{event.script_name}: selected trainer text labels must be distinct"
        )
    if tuple(text.label for text in event.texts) != expected_text_labels:
        raise ContentPortError(
            f"{event.script_name}: selected trainer text closure must exactly "
            "contain intro, defeat, and after text"
        )
    if any(not text.fragments for text in event.texts):
        raise ContentPortError(
            f"{event.script_name}: selected trainer text must not be empty"
        )


def _path_value(document: Mapping[str, Any], path: str) -> Any:
    current: Any = document
    for part in path.split("/"):
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def _set_path(document: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split("/")
    current: Any = document
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    final = parts[-1]
    if isinstance(current, list):
        current[int(final)] = value
    else:
        current[final] = value


def _canonical_digest(values: Iterable[str]) -> str:
    payload = json.dumps(
        sorted(set(values)), separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _inventory_digest(values: Iterable[str]) -> str:
    payload = (
        json.dumps(sorted(values), separators=(",", ":"), ensure_ascii=True) + "\n"
    )
    return hashlib.sha256(payload.encode()).hexdigest()


_INCLUDE_RE = re.compile(r'^\s*\.include\s+"([^"]+)"', re.MULTILINE)
_LABEL_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)::?", re.MULTILINE)
_TILESET_BLOB_RE = re.compile(
    r'g(?P<kind>Metatiles|MetatileAttributes)_(?P<name>\w+)\[\].*?"(?P<path>[^"]+)"'
)


def _referenced_inputs(
    root: Path, map_names: Iterable[str]
) -> tuple[tuple[str, ...], tuple[Mapping[str, object], ...]]:
    """Rebuild the legacy recursive symbol and byte-evidence closure."""
    pending: list[Path] = []
    for name in map_names:
        map_path = root / "data" / "maps" / name / "map.json"
        pending.append(map_path)
        for sibling_name in ("scripts.inc", "text.inc"):
            sibling = map_path.with_name(sibling_name)
            if sibling.is_file():
                pending.append(sibling)
    root = root.resolve()
    seen: set[Path] = set()
    symbols: set[str] = set()
    records: dict[str, Mapping[str, object]] = {}
    while pending:
        path = pending.pop()
        try:
            resolved = path.resolve(strict=True)
            relative = resolved.relative_to(root).as_posix()
        except (OSError, ValueError) as error:
            raise ContentPortError(
                f"missing or escaping referenced input: {path}"
            ) from error
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            data = resolved.read_bytes()
            text = data.decode("utf-8")
        except (OSError, UnicodeError) as error:
            raise ContentPortError(
                f"cannot read referenced input {relative}: {error}"
            ) from error
        if resolved.suffix.lower() != ".json":
            symbols.update(_LABEL_RE.findall(text))
        records[relative] = MappingProxyType(
            {
                "path": relative,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
        for include in _INCLUDE_RE.findall(text):
            included = root / include
            if not included.is_file():
                raise ContentPortError(
                    f"missing recursively referenced input: {include}"
                )
            pending.append(included)
    return tuple(sorted(symbols)), tuple(records[key] for key in sorted(records))


def _attribute_format(metatile_bytes: int, attribute_bytes: int) -> str:
    count, remainder = divmod(metatile_bytes, 16)
    if remainder or not count:
        raise ContentPortError("metatile blob is not an integral metatile set")
    if attribute_bytes == count * 2:
        return "METATILE_ATTRIBUTES_EMERALD_U16"
    if attribute_bytes == count * 4:
        return "METATILE_ATTRIBUTES_FRLG_U32"
    raise ContentPortError("attribute blob width does not match metatile count")


def _attribute_fixture_evidence(
    fixtures: Iterable[Mapping[str, object]],
    donor_fields: Mapping[str, str],
    contexts: Mapping[str, ExpansionSourceContext],
    donor_roots: Mapping[str, Path],
) -> Mapping[str, Mapping[str, str]]:
    field_roles = {field: role for role, field in donor_fields.items()}
    declared_by_role: dict[str, dict[tuple[str, str], str]] = {}
    results: dict[str, Mapping[str, str]] = {}
    for item in fixtures:
        representative = str(item["representative"])
        layout_id = str(item["layout"])
        tileset_role = str(item["role"])
        policy_authority = str(item["authority"])
        source_role = field_roles.get(policy_authority)
        if source_role is None or source_role not in contexts:
            raise ContentPortError(
                f"attribute fixture {representative} names unknown donor authority"
            )
        layout = contexts[source_role].load(ResourceKey("layout", layout_id)).value
        expected_tileset = layout.get(f"{tileset_role}_tileset")
        if item.get("tileset") != expected_tileset:
            raise ContentPortError(
                f"attribute fixture role drift: {representative}/{layout_id}/{tileset_role}"
            )
        if source_role not in declared_by_role:
            header_path = donor_roots[source_role] / "src/data/tilesets/metatiles.h"
            try:
                header = header_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                raise ContentPortError(
                    f"cannot read tileset declarations {header_path}: {error}"
                ) from error
            declared_by_role[source_role] = {
                (match.group("kind"), f"gTileset_{match.group('name')}"): match.group(
                    "path"
                )
                for match in _TILESET_BLOB_RE.finditer(header)
            }
        declarations = declared_by_role[source_role]
        if item.get("metatiles") != declarations.get(
            ("Metatiles", str(expected_tileset))
        ) or item.get("attributes") != declarations.get(
            ("MetatileAttributes", str(expected_tileset))
        ):
            raise ContentPortError(
                f"attribute fixture path drift: {representative}/{expected_tileset}"
            )
        metatiles = donor_roots[source_role] / str(item["metatiles"])
        attributes = donor_roots[source_role] / str(item["attributes"])
        try:
            metatile_data = metatiles.read_bytes()
            attribute_data = attributes.read_bytes()
        except OSError as error:
            raise ContentPortError(
                f"cannot read attribute fixture {representative}: {error}"
            ) from error
        if hashlib.sha256(metatile_data).hexdigest() != item.get(
            "metatilesSha256"
        ) or hashlib.sha256(attribute_data).hexdigest() != item.get("attributesSha256"):
            raise ContentPortError(f"attribute fixture hash drift: {representative}")
        actual_format = _attribute_format(len(metatile_data), len(attribute_data))
        if actual_format != item.get("format"):
            raise ContentPortError(
                f"wrong attribute width for {expected_tileset}: expected "
                f"{item.get('format')}, got {actual_format}"
            )
        results[representative] = MappingProxyType(
            {
                "layout": layout_id,
                "role": tileset_role,
                "tileset": str(expected_tileset),
                "format": actual_format,
            }
        )
    return MappingProxyType(dict(sorted(results.items())))


def _extract_preserved_script_warps(
    maps: Mapping[str, Mapping[str, Any]],
    ownership: Mapping[str, str],
    target_root: Path,
) -> tuple[
    tuple[WorldEdge, ...], Mapping[str, frozenset[str]], tuple[tuple[str, Any], ...]
]:
    """Return parsed script-warp edges and their map-owned entry inventory."""

    from .semantics import extract_script_warps, parse_scripts

    owned_entries: dict[str, frozenset[str]] = {}
    result: list[WorldEdge] = []
    dynamic_arms: list[tuple[str, Any]] = []
    map_aliases = {
        str(document.get("id", name)).removeprefix("MAP_"): name
        for name, document in maps.items()
    }
    for name, document in sorted(maps.items()):
        if ownership[name] != "preserve":
            continue
        entries = frozenset(
            str(event["script"])
            for collection in ("object_events", "coord_events", "bg_events")
            for event in (document.get(collection, []) or [])
            if isinstance(event, Mapping)
            and isinstance(event.get("script"), str)
            and event["script"] not in {"NULL", "0"}
        )
        if not entries:
            owned_entries[name] = frozenset()
            continue
        script_path = Path("data") / "maps" / name / "scripts.inc"
        if not (target_root / script_path).is_file():
            owned_entries[name] = frozenset()
            continue
        program = parse_scripts([script_path], root=target_root)
        # Map events may intentionally reference globally linked common
        # services. Only entries actually defined by this map's script unit are
        # map-owned evidence and eligible for a script-warp declaration.
        local_entries = frozenset(entry for entry in entries if entry in program.labels)
        owned_entries[name] = local_entries
        for entry in sorted(local_entries):
            for warp in extract_script_warps(program, entry):
                result.append(
                    WorldEdge(
                        name,
                        map_aliases.get(warp.destination, warp.destination),
                        "script-warp",
                        warp.index,
                        script_entry=warp.entry,
                        script_label=warp.label,
                        command=warp.command,
                        x=warp.x,
                        y=warp.y,
                    )
                )
                if warp.dynamic_arm is not None:
                    dynamic_arms.append((name, warp))
    return tuple(result), MappingProxyType(owned_entries), tuple(dynamic_arms)


def _bind_dynamic_warp_policy(
    graph: Any,
    declarations: object,
    ownership: Mapping[str, str],
    owned_entries: Mapping[str, frozenset[str]],
    dynamic_arms: tuple[tuple[str, Any], ...],
    map_aliases: Mapping[str, str],
) -> tuple[Any, Mapping[str, str], frozenset[str]]:
    """Bind each dynamic map exit to its exact, adjacent arming transition."""

    if not isinstance(declarations, list):
        raise ContentPortError("worldPolicy.dynamicWarps must be an array")
    required = {"source", "index", "token", "sourceOwnership", "destinations"}
    option_fields = {
        "destination",
        "x",
        "y",
        "armingSource",
        "script",
        "label",
        "index",
        "immediateDestination",
        "immediateCommand",
        "immediateIndex",
        "immediateX",
        "immediateY",
        "sourceRegion",
        "targetRegion",
        "armingRegion",
        "destinationOwnership",
        "armingOwnership",
    }
    declared_static: dict[str, str] = {}
    resolved: list[WorldEdge] = []
    for declaration_index, item in enumerate(declarations):
        pointer = f"worldPolicy.dynamicWarps/{declaration_index}"
        if not isinstance(item, dict) or set(item) != required:
            raise ContentPortError(f"{pointer}: malformed dynamic warp")
        source = str(item["source"])
        static_key = f"{source}:warp:{item['index']}"
        matches = [
            edge
            for edge in graph.edges
            if edge.key == static_key
            and edge.kind == "warp"
            and not isinstance(edge.target_warp, int)
        ]
        if len(matches) != 1 or str(matches[0].target_warp) != str(item["token"]):
            raise ContentPortError(f"{pointer}: stale dynamic warp declaration")
        if ownership.get(source) != item["sourceOwnership"]:
            raise ContentPortError(f"{pointer}: dynamic warp ownership evidence drift")
        if static_key in declared_static:
            raise ContentPortError("duplicate dynamic warp declaration")
        declared_static[static_key] = str(item["token"])
        options = item["destinations"]
        if not isinstance(options, list) or not options:
            raise ContentPortError(f"{pointer}: destinations must be a non-empty array")
        for option_index, option in enumerate(options):
            option_pointer = f"{pointer}/destinations/{option_index}"
            if not isinstance(option, dict) or set(option) != option_fields:
                raise ContentPortError(
                    f"{option_pointer}: malformed dynamic destination"
                )
            candidates = []
            for arming_source, warp in dynamic_arms:
                arm = warp.dynamic_arm
                arm_destination = (
                    map_aliases.get(arm.destination, arm.destination)
                    if arm is not None
                    else None
                )
                if (
                    arm is not None
                    and arming_source == option["armingSource"]
                    and arm_destination == option["destination"]
                    and arm.x == option["x"]
                    and arm.y == option["y"]
                    and arm.entry == option["script"]
                    and arm.label == option["label"]
                    and arm.index == option["index"]
                    and map_aliases.get(warp.destination, warp.destination)
                    == option["immediateDestination"]
                    and warp.command == option["immediateCommand"]
                    and warp.index == option["immediateIndex"]
                    and warp.x == option["immediateX"]
                    and warp.y == option["immediateY"]
                    and map_aliases.get(warp.destination, warp.destination) == source
                ):
                    candidates.append((arming_source, warp))
            if len(candidates) != 1:
                actual = [
                    (
                        arming_source,
                        map_aliases.get(
                            warp.dynamic_arm.destination, warp.dynamic_arm.destination
                        ),
                        warp.dynamic_arm.entry,
                        warp.dynamic_arm.label,
                        warp.destination,
                    )
                    for arming_source, warp in dynamic_arms
                    if warp.dynamic_arm is not None
                ]
                raise ContentPortError(
                    f"{option_pointer}: stale dynamic destination; parsed arms {actual!r}"
                )
            arming_source, warp = candidates[0]
            destination = str(option["destination"])
            if destination not in graph.maps:
                raise ContentPortError(
                    f"{option_pointer}: destination map is outside the closed world graph"
                )
            if (
                ownership.get(destination) != option["destinationOwnership"]
                or ownership.get(arming_source) != option["armingOwnership"]
                or str(option["script"])
                not in owned_entries.get(arming_source, frozenset())
            ):
                raise ContentPortError(
                    f"{option_pointer}: dynamic warp ownership evidence drift"
                )
            if (
                graph.maps[source].region != option["sourceRegion"]
                or graph.maps[destination].region != option["targetRegion"]
                or graph.maps[arming_source].region != option["armingRegion"]
            ):
                raise ContentPortError(
                    f"{option_pointer}: dynamic warp region evidence drift"
                )
            arm = warp.dynamic_arm
            resolved.append(
                WorldEdge(
                    source,
                    destination,
                    "dynamic-warp",
                    int(item["index"]),
                    x=arm.x,
                    y=arm.y,
                    arming_source=arming_source,
                    arming_entry=arm.entry,
                    arming_label=arm.label,
                    arming_index=arm.index,
                    immediate_target=map_aliases.get(
                        warp.destination, warp.destination
                    ),
                    immediate_command=warp.command,
                    immediate_index=warp.index,
                    immediate_x=warp.x,
                    immediate_y=warp.y,
                )
            )
    observed_static = {
        edge.key: str(edge.target_warp)
        for edge in graph.edges
        if edge.kind == "warp" and not isinstance(edge.target_warp, int)
    }
    if declared_static != observed_static:
        raise ContentPortError("dynamic warp policy differs from resolved topology")
    observed_arms = {
        (
            arming_source,
            warp.dynamic_arm.entry,
            warp.dynamic_arm.label,
            warp.dynamic_arm.index,
            map_aliases.get(warp.dynamic_arm.destination, warp.dynamic_arm.destination),
            warp.dynamic_arm.x,
            warp.dynamic_arm.y,
            map_aliases.get(warp.destination, warp.destination),
            warp.command,
            warp.index,
            warp.x,
            warp.y,
        )
        for arming_source, warp in dynamic_arms
        if warp.dynamic_arm is not None
    }
    resolved_arms = {
        (
            edge.arming_source,
            edge.arming_entry,
            edge.arming_label,
            edge.arming_index,
            edge.target,
            edge.x,
            edge.y,
            edge.immediate_target,
            edge.immediate_command,
            edge.immediate_index,
            edge.immediate_x,
            edge.immediate_y,
        )
        for edge in resolved
    }
    if resolved_arms != observed_arms:
        raise ContentPortError("dynamic warp destinations differ from parsed arms")
    graph = with_dynamic_warps(graph, resolved)
    gateways = frozenset(
        edge.key
        for edge in resolved
        if graph.maps[edge.source].region != graph.maps[edge.target].region
    )
    return graph, MappingProxyType(declared_static), gateways


def _bind_script_warp_policy(
    graph: Any,
    declarations: object,
    ownership: Mapping[str, str],
    owned_entries: Mapping[str, frozenset[str]],
) -> frozenset[str]:
    """Bind reviewed policy to independently parsed script-warp evidence."""

    if not isinstance(declarations, list):
        raise ContentPortError("worldPolicy.scriptWarps must be an array")
    declared_keys: set[str] = set()
    gateway_keys: set[str] = set()
    required = {
        "source",
        "destination",
        "script",
        "label",
        "command",
        "index",
        "x",
        "y",
        "sourceRegion",
        "targetRegion",
    }
    for index, item in enumerate(declarations):
        if not isinstance(item, dict) or set(item) != required:
            raise ContentPortError(
                f"worldPolicy.scriptWarps/{index}: malformed script warp"
            )
        source = str(item["source"])
        if ownership.get(source) != "preserve":
            raise ContentPortError(
                f"worldPolicy.scriptWarps/{index}: source map does not preserve "
                "script ownership"
            )
        if str(item["script"]) not in owned_entries.get(source, frozenset()):
            raise ContentPortError(
                f"worldPolicy.scriptWarps/{index}: script entry is not owned by "
                f"source map {source}"
            )
        matches = [
            edge
            for edge in graph.edges
            if edge.kind == "script-warp"
            and edge.source == source
            and edge.target == item["destination"]
            and edge.script_entry == item["script"]
            and edge.script_label == item["label"]
            and edge.command == item["command"]
            and edge.index == item["index"]
            and edge.x == item["x"]
            and edge.y == item["y"]
        ]
        if len(matches) != 1:
            raise ContentPortError(
                f"worldPolicy.scriptWarps/{index}: stale script warp declaration"
            )
        edge = matches[0]
        target = graph.maps.get(edge.target)
        if target is None:
            raise ContentPortError(
                f"worldPolicy.scriptWarps/{index}: destination map is outside the "
                "closed world graph"
            )
        if (
            graph.maps[edge.source].region != item["sourceRegion"]
            or target.region != item["targetRegion"]
        ):
            raise ContentPortError(
                f"worldPolicy.scriptWarps/{index}: script warp region evidence drift"
            )
        if edge.key in declared_keys:
            raise ContentPortError("duplicate script warp declaration")
        declared_keys.add(edge.key)
        if graph.maps[edge.source].region != target.region:
            gateway_keys.add(edge.key)
    observed_keys = {edge.key for edge in graph.edges if edge.kind == "script-warp"}
    if declared_keys != observed_keys:
        raise ContentPortError("script warp policy differs from resolved topology")
    return frozenset(gateway_keys)


def _automatic_unreachable_shells(
    graph: Any, warp_removals_by_map: Mapping[str, set[int]]
) -> frozenset[str]:
    outgoing_sources = {edge.source for edge in graph.edges}
    return frozenset(
        name
        for name, indexes in warp_removals_by_map.items()
        if indexes and name not in outgoing_sources
    )


def _require_trainer_geometry_adapter(
    authority: TrainerMaterializationAuthority,
) -> None:
    """Keep future standard-single batches behind authenticated geometry evidence.

    The seeded closure predates the cumulative batch pipeline. Any appended
    Phase 3 batch must call the geometry adapter here and supply its complete
    map census before this guard can be relaxed.
    """

    pending = tuple(
        batch.key for batch in authority.batches if batch.kind == "standard-singles"
    )
    if pending:
        raise ContentPortError(
            "trainer materialization requires the authenticated geometry adapter "
            f"before standard-single batch activation: {pending[0]}"
        )


def resolve_port_sources(
    descriptor: PortDescriptor, repo: Path | str
) -> tuple[ContractEvidence, PortSourceState]:
    """Close and validate every enabled resource in a loaded ``PortDescriptor``.

    Donor selection and policy live in the descriptor. This generic entry point
    merely applies its exact field decisions, builds the expansion-native graph,
    resolves persistence, and validates the rendered spatial world.
    """
    from .bindings import load_binding_index
    from .closure import close_source_graph
    from .model import CapabilityState
    from .semantics import (
        EventEntry,
        analyze_entry,
        parse_scripts,
        validate_effects,
        validate_event_policy_capabilities,
    )
    from .world_graph import (
        WorldPolicy,
        validate_world_graph,
        with_script_warps,
        world_graph_from_maps,
    )

    target_root = Path(repo)
    donor_pins = descriptor.donors_by_role
    donor_roots = {role: pin.root for role, pin in donor_pins.items()}
    contexts = {
        role: ExpansionSourceContext(pin.root, active_capabilities=("spatial",))
        for role, pin in donor_pins.items()
    }
    mechanical_pin = descriptor.donor("mechanical")
    content_pin = descriptor.donor("content")
    mechanical = contexts["mechanical"]
    content = contexts["content"]

    adaptations = _thaw(descriptor.adaptations)
    donor_fields = adaptations.get("donorFieldRoles")
    if not isinstance(donor_fields, dict) or set(donor_fields) != {
        "content",
        "mechanical",
    }:
        raise ContentPortError(
            "donorFieldRoles must name content and mechanical policy fields"
        )
    content_field = donor_fields["content"]
    mechanical_field = donor_fields["mechanical"]
    if not all(isinstance(value, str) and value for value in donor_fields.values()):
        raise ContentPortError("donorFieldRoles values must be field names")
    fallback = set(adaptations["contentFallback"]["maps"])
    map_names = tuple(descriptor.map_ownership)
    if fallback - set(map_names):
        raise ContentPortError(
            f"content fallback names unknown map {sorted(fallback - set(map_names))[0]}"
        )
    for name in sorted(fallback):
        try:
            content.load(ResourceKey("map", name))
        except ContentPortError:
            pass
        else:
            raise ContentPortError(
                f"fallback map {name} exists in the content donor; mechanical authority is forbidden"
            )
    trainer_inventory = _authenticated_trainer_inventory(
        descriptor, content, map_names, fallback
    )

    selected_maps: dict[str, dict[str, Any]] = {}
    map_authorities: dict[str, str] = {}
    source_records: dict[ResourceKey, SourceRecord] = {}
    aliases: dict[ResourceKey, ResourceKey] = {}
    input_evidence: list[str] = []
    for name in map_names:
        authority = mechanical if name in fallback else content
        authority_root = mechanical_pin.root if name in fallback else content_pin.root
        try:
            record = authority.load(ResourceKey("map", name))
        except ContentPortError as exc:
            role = "mechanical fallback" if name in fallback else "content authority"
            raise ContentPortError(f"{role} map {name}: {exc}") from exc
        selected_record = record
        selected_role = "mechanical" if name in fallback else "content"
        if descriptor.map_ownership[name] == "preserve":
            target_path = target_root / "data" / "maps" / name / "map.json"
            if target_path.is_symlink():
                raise ContentPortError(
                    f"preserved target map {name} must not be a symbolic link"
                )
            try:
                selected_record = json_record(target_path)
            except ContentPortError as error:
                raise ContentPortError(
                    f"preserved target map {name} is unavailable: {error}"
                ) from error
            selected_role = "target"
        document = _thaw(selected_record.value)
        for semantic_root_field in ("_encounter_roots", "_trainer_event_roots"):
            roots = record.value.get(semantic_root_field)
            if roots:
                document[semantic_root_field] = list(roots)
        selected_maps[name] = document
        map_authorities[name] = selected_role
        canonical = ResourceKey("map", name)
        source_records[canonical] = SourceRecord(document, selected_record.provenance)
        map_id = document.get("id")
        if isinstance(map_id, str):
            aliases[ResourceKey("map", map_id)] = canonical
            aliases[ResourceKey("map", map_id.removeprefix("MAP_"))] = canonical
        source_path = Path(record.provenance.path)
        if source_path.is_file():
            data = source_path.read_bytes()
            input_evidence.append(
                f"{source_path.relative_to(authority_root).as_posix()}:"
                f"{hashlib.sha256(data).hexdigest()}:{len(data)}"
            )

    # Exact reviewed field substitutions are checked against both donors before
    # the mechanical value becomes desired state.
    for decision in adaptations["adaptations"]:
        name = decision["source"]
        if name not in selected_maps:
            raise ContentPortError(f"adaptation names unknown map {name}")
        content_record = content.load(ResourceKey("map", name))
        mechanical_record = mechanical.load(ResourceKey("map", name))
        path = decision["path"]
        actual_content = _path_value(content_record.value, path)
        actual_mechanical = _path_value(mechanical_record.value, path)
        if actual_content != decision[content_field]:
            raise ContentPortError(f"{name}/{path}: content adaptation preimage drift")
        if actual_mechanical != decision[mechanical_field]:
            raise ContentPortError(
                f"{name}/{path}: mechanical adaptation evidence drift"
            )
        if descriptor.map_ownership[name] == "preserve":
            if _path_value(selected_maps[name], path) != decision[mechanical_field]:
                raise ContentPortError(
                    f"{name}/{path}: preserved target map differs from reviewed state"
                )
        else:
            _set_path(selected_maps[name], path, decision[mechanical_field])

    # Map-field decisions are renderer inputs, so authenticate every declared
    # donor value here before the selected authority can affect desired state.
    for decision in adaptations["mapFieldDecisions"]:
        name = decision["map"]
        path = decision["field"]
        if name not in selected_maps:
            raise ContentPortError(f"map-field decision names unknown map {name}")
        for source_role, policy_field in donor_fields.items():
            context = contexts.get(source_role)
            if context is None:
                raise ContentPortError(
                    f"{name}/{path}: unknown map-field donor role {source_role}"
                )
            try:
                source_record = context.load(ResourceKey("map", name))
                actual = _path_value(source_record.value, path)
            except (ContentPortError, KeyError, IndexError, TypeError) as error:
                raise ContentPortError(
                    f"{name}/{path}: cannot resolve {source_role} map-field evidence"
                ) from error
            if actual != decision[policy_field]:
                raise ContentPortError(
                    f"{name}/{path}: {source_role} map-field evidence drift"
                )
        authority_role = decision["authority"]
        policy_field = donor_fields.get(authority_role)
        if policy_field is None:
            raise ContentPortError(
                f"{name}/{path}: unknown map-field authority {authority_role}"
            )
        if descriptor.map_ownership[name] == "preserve":
            if _path_value(selected_maps[name], path) != decision[policy_field]:
                raise ContentPortError(
                    f"{name}/{path}: preserved target map differs from reviewed state"
                )
        else:
            _set_path(selected_maps[name], path, decision[policy_field])

    # Reindexes are part of resolved topology, not a renderer-side mutation.
    reindex_identities = [
        (decision["source"], decision["path"])
        for decision in adaptations["warpReindexes"]
    ]
    if len(reindex_identities) != len(set(reindex_identities)):
        raise ContentPortError("duplicate warp reindex identity")
    for decision in adaptations["warpReindexes"]:
        name = decision["source"]
        path = decision["path"]
        if name not in selected_maps:
            raise ContentPortError(f"warp reindex names unknown map {name}")
        try:
            current = _path_value(selected_maps[name], path)
        except (KeyError, IndexError, TypeError) as error:
            raise ContentPortError(
                f"{name}/{path}: warp reindex path is invalid"
            ) from error
        if descriptor.map_ownership[name] == "preserve":
            if current != decision["to"]:
                raise ContentPortError(
                    f"{name}/{path}: preserved target map lacks reviewed warp reindex"
                )
        else:
            _set_path(selected_maps[name], path, decision["to"])

    for name, document in selected_maps.items():
        allocation = descriptor.allocation_index.map_allocation(name)
        for field_name, expected in (
            ("id", allocation.map_id),
            ("layout", allocation.layout),
            ("region_map_section", allocation.section),
        ):
            if document.get(field_name) != expected:
                raise ContentPortError(
                    f"{name}/{field_name}: resolved map binding differs from "
                    "allocation authority"
                )

    # Validate the authored retained/deferred inventory against the adapted maps
    # before reviewed removals are applied.
    actual_edges: set[tuple[str, str, str, str]] = set()
    for name, document in selected_maps.items():
        for field_name, kind, target_field in (
            ("connections", "connection", "map"),
            ("warp_events", "warp", "dest_map"),
        ):
            for index, edge in enumerate(document.get(field_name, []) or []):
                actual_edges.add(
                    (name, f"{field_name}/{index}", kind, str(edge[target_field]))
                )
    reviewed_retained = {
        (item["source"], item["path"], item["kind"], item["destination"])
        for item in adaptations["retainedEdges"]
    }
    reviewed_deferred = {
        (item["source"], item["path"], item["kind"], item["destination"])
        for item in adaptations["deferredEdges"]
    }
    if actual_edges != reviewed_retained | reviewed_deferred:
        unexpected = sorted(actual_edges - reviewed_retained - reviewed_deferred)
        stale = sorted((reviewed_retained | reviewed_deferred) - actual_edges)
        raise ContentPortError(
            f"reviewed world edge drift: unexpected={unexpected[:1]} stale={stale[:1]}"
        )

    removal_identities = [
        (removal["source"], removal["path"]) for removal in adaptations["warpRemovals"]
    ]
    if len(removal_identities) != len(set(removal_identities)):
        raise ContentPortError("duplicate warp removal identity")
    deferred_identities = [
        (item["source"], item["path"]) for item in adaptations["deferredEdges"]
    ]
    if len(deferred_identities) != len(set(deferred_identities)):
        raise ContentPortError("duplicate deferred edge identity")
    warp_removals_by_map: dict[str, set[int]] = {}
    for removal in adaptations["warpRemovals"]:
        name = removal["source"]
        index = int(removal["path"].split("/")[-1])
        warps = selected_maps[name].get("warp_events", [])
        if index >= len(warps):
            raise ContentPortError(
                f"{name}/{removal['path']}: warp removal is out of bounds"
            )
        warp = warps[index]
        if (
            str(warp.get("dest_map")) != removal["destination"]
            or str(warp.get("dest_warp_id")) != removal["destWarpId"]
        ):
            raise ContentPortError(
                f"{name}/{removal['path']}: warp removal preimage drift"
            )
        warp_removals_by_map.setdefault(name, set()).add(index)

    # Reachability closes over removals below. The established residency
    # projection is deliberately narrower: it removes only authored deferred
    # edges and explicit removals, without cascading into retained physical
    # warps or renumbering their destination operands.
    materialization_maps = copy.deepcopy(selected_maps)
    physical_removals: dict[tuple[str, str], set[int]] = {}
    for item in (*adaptations["deferredEdges"], *adaptations["warpRemovals"]):
        field_name, raw_index = item["path"].split("/")
        physical_removals.setdefault((item["source"], field_name), set()).add(
            int(raw_index)
        )
    for (name, field_name), indexes in physical_removals.items():
        for index in sorted(indexes, reverse=True):
            del materialization_maps[name][field_name][index]
    deferred_removals: dict[tuple[str, str], list[int]] = {}
    explicit_removals = {
        (item["source"], item["path"]) for item in adaptations["warpRemovals"]
    }
    for item in adaptations["deferredEdges"]:
        if (item["source"], item["path"]) in explicit_removals:
            continue
        field_name, raw_index = item["path"].split("/")
        deferred_removals.setdefault((item["source"], field_name), []).append(
            int(raw_index)
        )
    for (name, field_name), indexes in deferred_removals.items():
        if field_name == "warp_events":
            warp_removals_by_map.setdefault(name, set()).update(indexes)
            continue
        for index in sorted(indexes, reverse=True):
            del selected_maps[name][field_name][index]

    # Warp indices are positional identities. Close removals over incoming
    # references to deleted slots, then shift every surviving destination index
    # exactly once against the authenticated pre-removal arrays.
    map_aliases = {
        alias: name
        for name, document in selected_maps.items()
        for alias in (name, str(document.get("id", name)))
    }
    changed = True
    while changed:
        changed = False
        for source, document in selected_maps.items():
            removed = warp_removals_by_map.setdefault(source, set())
            for index, warp in enumerate(document.get("warp_events", []) or []):
                if index in removed:
                    continue
                destination = map_aliases.get(str(warp.get("dest_map")))
                raw_target = str(warp.get("dest_warp_id"))
                if destination is None or not raw_target.lstrip("-").isdigit():
                    continue
                target_index = int(raw_target)
                destination_removals = warp_removals_by_map.get(destination, set())
                if target_index not in destination_removals:
                    continue
                destination_warps = (
                    selected_maps[destination].get("warp_events", []) or []
                )
                successor = next(
                    (
                        candidate
                        for candidate in range(target_index + 1, len(destination_warps))
                        if candidate not in destination_removals
                    ),
                    None,
                )
                if (
                    successor is not None
                    and destination_warps[successor] == destination_warps[target_index]
                ):
                    continue
                removed.add(index)
                changed = True
    for source, document in selected_maps.items():
        removed = warp_removals_by_map.get(source, set())
        resolved_warps: list[dict[str, Any]] = []
        for index, warp in enumerate(document.get("warp_events", []) or []):
            if index in removed:
                continue
            resolved = dict(warp)
            destination = map_aliases.get(str(resolved.get("dest_map")))
            raw_target = resolved.get("dest_warp_id")
            rendered_target = str(raw_target)
            if destination is not None and rendered_target.lstrip("-").isdigit():
                target_index = int(rendered_target)
                target_index -= sum(
                    removed_index < target_index
                    for removed_index in warp_removals_by_map.get(destination, set())
                )
                resolved["dest_warp_id"] = (
                    str(target_index) if isinstance(raw_target, str) else target_index
                )
            resolved_warps.append(resolved)
        document["warp_events"] = resolved_warps

    # Resolve each layout from its exact typed authority. The source map proves
    # that the reviewed layout identity belongs to that donor and source.
    selected_layouts: dict[str, SourceRecord] = {}
    layout_authorities: dict[str, str] = {}
    for name, document in selected_maps.items():
        descriptor.allocation_index.map_slot(name)
        layout_id = str(document["layout"])
        descriptor.allocation_index.layout_slot(layout_id)
    allocated_layouts = set(descriptor.allocation_index.layouts)
    declared_layouts = {item.layout for item in descriptor.layout_binary_authorities}
    if declared_layouts != allocated_layouts or len(declared_layouts) != len(
        descriptor.layout_binary_authorities
    ):
        raise ContentPortError(
            "layout binary authorities must uniquely cover every allocated layout"
        )
    for authority in descriptor.layout_binary_authorities:
        context = contexts.get(authority.source_role)
        if context is None:
            raise ContentPortError(
                f"{authority.layout}: unknown layout source role {authority.source_role}"
            )
        if authority.source != authority.layout:
            try:
                source_map = context.load(ResourceKey("map", authority.source))
            except ContentPortError as error:
                raise ContentPortError(
                    f"{authority.layout}: source map {authority.source} is absent from "
                    f"the {authority.source_role} donor"
                ) from error
            if source_map.value.get("layout") != authority.layout:
                raise ContentPortError(
                    f"{authority.layout}: source map {authority.source} in the "
                    f"{authority.source_role} donor resolves layout "
                    f"{source_map.value.get('layout')!r}"
                )
        try:
            record = context.load(ResourceKey("layout", authority.layout))
        except ContentPortError as error:
            raise ContentPortError(
                f"{authority.layout}: layout is absent from its reviewed "
                f"{authority.source_role} donor"
            ) from error
        if authority.layout in selected_layouts:
            raise ContentPortError(
                f"{authority.layout}: overlapping layout binary authorities"
            )
        selected_layouts[authority.layout] = record
        layout_authorities[authority.layout] = authority.source_role

    for layout_id, record in list(selected_layouts.items()):
        selected_layouts[layout_id] = SourceRecord(
            _thaw(record.value), record.provenance
        )
    layout_field_authorities: dict[str, dict[str, str]] = {
        layout_id: {field: layout_authorities[layout_id] for field in record.value}
        for layout_id, record in selected_layouts.items()
    }
    applied_field_rules: set[tuple[str, str]] = set()
    for authority in descriptor.layout_field_authorities:
        matching_layouts = sorted(
            layout_id
            for layout_id, role in layout_authorities.items()
            if role == authority.layout_role
        )
        if not matching_layouts:
            raise ContentPortError(
                f"layout field authority {authority.layout_role}/{authority.field} "
                "matches no allocated layout"
            )
        source_context = contexts[authority.source_role]
        for layout_id in matching_layouts:
            selected = selected_layouts[layout_id].value
            if authority.field in selected:
                raise ContentPortError(
                    f"{layout_id}/{authority.field}: field authority expects the "
                    f"{authority.layout_role} donor field to be absent"
                )
            try:
                source_layout = source_context.load(
                    ResourceKey("layout", layout_id)
                ).value
            except ContentPortError as error:
                raise ContentPortError(
                    f"{layout_id}/{authority.field}: field authority source layout is "
                    f"absent from the {authority.source_role} donor"
                ) from error
            if authority.field not in source_layout:
                raise ContentPortError(
                    f"{layout_id}/{authority.field}: field authority is absent from "
                    f"the {authority.source_role} donor"
                )
            selected[authority.field] = _thaw(source_layout[authority.field])
            layout_field_authorities[layout_id][authority.field] = authority.source_role
            applied_field_rules.add((authority.layout_role, authority.field))
    declared_field_rules = {
        (authority.layout_role, authority.field)
        for authority in descriptor.layout_field_authorities
    }
    if applied_field_rules != declared_field_rules:
        raise ContentPortError("layout field authorities were not applied exactly")
    for decision in adaptations["layoutHeaderDecisions"]:
        layout_id, field_name = decision["layout"], decision["field"]
        content_value = content.load(ResourceKey("layout", layout_id)).value[field_name]
        mechanical_value = mechanical.load(ResourceKey("layout", layout_id)).value[
            field_name
        ]
        if (
            content_value != decision[content_field]
            or mechanical_value != decision[mechanical_field]
        ):
            raise ContentPortError(
                f"{layout_id}/{field_name}: layout authority evidence drift"
            )
        selected_layouts[layout_id].value[field_name] = (
            decision[content_field]
            if decision["authority"] == "content"
            else decision[mechanical_field]
        )
        layout_field_authorities[layout_id][field_name] = decision["authority"]
    required_layout_fields = {
        "blockdata_filepath",
        "border_filepath",
        "border_height",
        "border_width",
        "height",
        "id",
        "name",
        "primary_tileset",
        "secondary_tileset",
        "width",
    }
    for layout_id, record in selected_layouts.items():
        missing_fields = sorted(required_layout_fields - set(record.value))
        if missing_fields:
            raise ContentPortError(
                f"{layout_id}: unresolved layout field {missing_fields[0]!r}; "
                "exact field authority is required"
            )
    for decision in adaptations["layoutTilesetRemaps"]:
        layout_id, field_name = decision["layout"], decision["field"]
        if selected_layouts[layout_id].value[field_name] != decision["source"]:
            raise ContentPortError(
                f"{layout_id}/{field_name}: tileset remap preimage drift"
            )
        # The graph identity remains the authenticated donor asset. The target
        # renderer binding is validated below without replacing source authority.

    asset_fields = (
        "primary_tileset",
        "secondary_tileset",
        "border_filepath",
        "blockdata_filepath",
    )
    for layout_id, record in selected_layouts.items():
        graph_layout = _thaw(record.value)
        graph_layout["_asset_authorities"] = {
            field_name: layout_field_authorities[layout_id][field_name]
            for field_name in asset_fields
        }
        source_records[ResourceKey("layout", layout_id)] = SourceRecord(
            graph_layout, record.provenance
        )
        for field_name in asset_fields:
            asset_name = str(record.value[field_name])
            authority_role = layout_field_authorities[layout_id][field_name]
            qualified_key = ResourceKey("asset", f"{authority_role}:{asset_name}")
            if qualified_key in source_records:
                continue
            try:
                asset_record = contexts[authority_role].load(
                    ResourceKey("asset", asset_name)
                )
            except ContentPortError as error:
                raise ContentPortError(
                    f"{layout_id}/{field_name}: asset is absent from its reviewed "
                    f"{authority_role} donor"
                ) from error
            source_records[qualified_key] = asset_record
    # Renderer bindings are authored policy. Installed generated headers are
    # outputs and must never become authority for their own desired state.
    policy_tilesets = {
        f"gTileset_{item['targetSymbol'] if 'targetSymbol' in item else item['symbol']}"
        for item in adaptations["tilesetAdaptations"]
    }
    for decision in adaptations["layoutTilesetRemaps"]:
        if decision["target"] not in policy_tilesets:
            raise ContentPortError(
                f"{decision['layout']}: target tileset binding {decision['target']} "
                "is missing from typed policy"
            )

    enabled = tuple(
        decision
        for decision in descriptor.capabilities
        if decision.state == CapabilityState.ENABLED
    )
    enabled_by_map: dict[str, set[str]] = {}
    for decision in enabled:
        enabled_by_map.setdefault(decision.map_name, set()).add(decision.capability)
    ledger_path = target_root / "src/data/persistence/persistent_ids.json"
    ledger = load_binding_index(ledger_path)
    trainer_materialization: TrainerMaterializationAuthority | None = None
    if descriptor.trainer_materialization_path is not None:
        if (
            descriptor.trainer_materialization_prefix_count is None
            or descriptor.trainer_materialization_prefix_digest is None
        ):
            raise ContentPortError(
                "trainer materialization descriptor lacks reviewed prefix pins"
            )
        trainer_materialization = load_trainer_materialization(
            descriptor.trainer_materialization_path,
            trainer_inventory,
            ledger,
            reviewed_prefix=ReviewedMaterializationPrefix(
                descriptor.trainer_materialization_prefix_count,
                descriptor.trainer_materialization_prefix_digest,
            ),
        )
        _require_trainer_geometry_adapter(trainer_materialization)

    selected_trainer_events: dict[str, tuple[TrainerEventRecord, ...]] = {}
    projected_trainer_events: dict[str, tuple[StandardSingleEventProjection, ...]] = {}
    enabled_trainer_decisions = tuple(
        decision for decision in enabled if decision.capability == "trainers"
    )
    if trainer_materialization is not None:
        inventory_placements = {
            placement.identity: placement
            for placement in trainer_inventory.placements
            if placement.admitted
        }
        targets = {
            identity.trainer: identity.projection.target
            for identity in trainer_inventory.identities
            if identity.projection is not None
        }
        observed: dict[str, list[str]] = {}
        for decision in enabled_trainer_decisions:
            requested = tuple(
                dependency
                for dependency in decision.dependencies
                if dependency.domain == "trainer"
            )
            if len(requested) != len(decision.dependencies) or not requested:
                raise ContentPortError(
                    f"{decision.map_name}/trainers: enabled trainer capability "
                    "requires only explicit trainer dependencies"
                )
            role = "mechanical" if decision.map_name in fallback else "content"
            roots = tuple(
                selected_maps[decision.map_name].get("_trainer_event_roots", ())
            )
            available = {
                root: contexts[role].trainer_event(
                    ResourceKey("trainer-event", str(root))
                )
                for root in roots
            }
            selected_rows: list[
                tuple[TrainerEventRecord, StandardSingleEventProjection, str, str]
            ] = []
            for dependency in requested:
                placements = [
                    placement
                    for placement in inventory_placements.values()
                    if placement.map_name == decision.map_name
                    and placement.trainer == dependency.name
                ]
                if not placements:
                    raise ContentPortError(
                        f"{decision.map_name}/trainers: {dependency} has no admitted "
                        "inventory placement"
                    )
                for placement in placements:
                    event = available.get(placement.identity)
                    if event is None:
                        raise ContentPortError(
                            f"{decision.map_name}/trainers: selected placement "
                            f"{placement.identity} is absent from authenticated donor roots"
                        )
                    projected = project_standard_single_event(
                        event,
                        source_trainer=dependency.name,
                        target_trainer=targets[dependency.name],
                    )
                    selected_rows.append(
                        (event, projected, dependency.name, placement.identity)
                    )
            selected_rows.sort(key=lambda row: row[0].object_index)
            chosen = [row[0] for row in selected_rows]
            projections = [row[1] for row in selected_rows]
            placement_names = [row[3] for row in selected_rows]
            if len(chosen) != len({event.object_index for event in chosen}):
                raise ContentPortError(
                    f"{decision.map_name}/trainers: duplicate donor object index"
                )
            for _event, _projection, source, placement_name in selected_rows:
                observed.setdefault(source, []).append(placement_name)
            selected_trainer_events[decision.map_name] = tuple(chosen)
            projected_trainer_events[decision.map_name] = tuple(projections)
            selected_maps[decision.map_name]["_trainer_event_roots"] = placement_names
            map_key = ResourceKey("map", decision.map_name)
            source_records[map_key] = SourceRecord(
                selected_maps[decision.map_name], source_records[map_key].provenance
            )
        require_materialization_exact_cover(
            trainer_materialization,
            observed,
            owner="authenticated selected trainer closure",
        )
    else:
        for decision in enabled_trainer_decisions:
            requested = tuple(
                dependency
                for dependency in decision.dependencies
                if dependency.domain == "trainer"
            )
            if len(requested) != len(decision.dependencies) or not requested:
                raise ContentPortError(
                    f"{decision.map_name}/trainers: enabled trainer capability "
                    "requires only explicit trainer dependencies"
                )
            role = "mechanical" if decision.map_name in fallback else "content"
            roots = tuple(
                selected_maps[decision.map_name].get("_trainer_event_roots", ())
            )
            available = [
                contexts[role].trainer_event(ResourceKey("trainer-event", root))
                for root in roots
            ]
            available_by_identity = {
                f"{event.map_name}/{event.object_index}/{event.script_name}": event
                for event in available
            }
            chosen: list[TrainerEventRecord] = []
            for dependency in requested:
                placements = [
                    placement
                    for placement in trainer_inventory.placements
                    if placement.map_name == decision.map_name
                    and placement.trainer == dependency.name
                    and placement.admitted
                ]
                if len(placements) != 1:
                    raise ContentPortError(
                        f"{decision.map_name}/trainers: {dependency} must select "
                        "exactly one admitted inventory placement"
                    )
                event = available_by_identity.get(placements[0].identity)
                if event is None or event.trainers != (dependency.name,):
                    raise ContentPortError(
                        f"{decision.map_name}/trainers: admitted placement "
                        f"{placements[0].identity} is absent from donor event roots"
                    )
                chosen.append(event)
            for event in chosen:
                _validate_selected_trainer_event(event)
            selected_trainer_events[decision.map_name] = tuple(chosen)
            selected_maps[decision.map_name]["_trainer_event_roots"] = [
                f"{event.map_name}/{event.object_index}/{event.script_name}"
                for event in chosen
            ]
            map_key = ResourceKey("map", decision.map_name)
            source_records[map_key] = SourceRecord(
                selected_maps[decision.map_name], source_records[map_key].provenance
            )
    _authenticate_trainer_projection_authority(
        trainer_inventory,
        content,
        target_root,
        ledger,
        frozenset(
            trainer
            for events in selected_trainer_events.values()
            for event in events
            for trainer in event.trainers
        ),
    )
    explicit_dependencies = {
        dependency for decision in enabled for dependency in decision.dependencies
    }
    event_capabilities = {
        decision.capability for decision in descriptor.capabilities
    } - {
        "spatial",
        "encounters",
        "environment-assets",
        "trainers",
    }
    semantic_domains = frozenset(
        {
            "trainer",
            "trainer-event",
            "party",
            "encounter",
            "service",
            "species",
            "move",
            "item",
            "trainer-class",
            "asset",
        }
    )
    pending_semantics: list[tuple[str, ResourceKey]] = []
    binding_dependencies = {
        dependency
        for dependency in explicit_dependencies
        if dependency.domain == "binding"
    }
    for decision in enabled:
        role = "mechanical" if decision.map_name in fallback else "content"
        pending_semantics.extend(
            (role, dependency)
            for dependency in decision.dependencies
            if dependency.domain in semantic_domains
        )
        map_key = ResourceKey("map", decision.map_name)
        active = enabled_by_map[decision.map_name]
        map_capabilities = (
            ({"encounters"} if "encounters" in active else set())
            | ({"trainers"} if "trainers" in active else set())
            | ({"events"} if active & event_capabilities else set())
        )
        gate = SourceContext(resource_capabilities={map_key: map_capabilities})
        for edge in extract_map_edges(gate, map_key, source_records[map_key]):
            if edge.target.domain in semantic_domains:
                pending_semantics.append((role, edge.target))
            elif edge.target.domain == "binding":
                binding_dependencies.add(edge.target)

    semantic_authorities: dict[ResourceKey, str] = {}
    encounter_policies = {
        ResourceKey("encounter", str(item["label"])): item
        for item in adaptations["encounterProfiles"]
    }
    enabled_encounter_dependencies = {
        dependency
        for decision in enabled
        if decision.capability == "encounters"
        for dependency in decision.dependencies
        if dependency.domain == "encounter"
    }
    policy_labels = {
        ResourceKey("encounter", str(policy[field]))
        for policy in adaptations["encounterTimePolicy"]
        for field in ("dayLabel", "nightLabel")
    }
    if (
        set(encounter_policies) != enabled_encounter_dependencies
        or set(encounter_policies) != policy_labels
    ):
        raise ContentPortError(
            "authored encounter profiles must exactly match enabled encounter "
            "dependencies and reviewed time-policy labels"
        )
    enabled_encounter_maps = {
        decision.map_name for decision in enabled if decision.capability == "encounters"
    }
    if enabled_encounter_maps != {
        str(item["map"]) for item in adaptations["encounterProfiles"]
    }:
        raise ContentPortError(
            "enabled encounter maps must exactly match authored encounter profiles"
        )
    event_policy_path = descriptor.event_policy_path
    entries = dict(descriptor.event_entries)
    effect_policy = dict(descriptor.effect_policy)
    for events in (
        selected_trainer_events.values() if trainer_materialization is not None else ()
    ):
        for event in events:
            if event.script_name in entries:
                raise ContentPortError(
                    f"{event.script_name}: cumulative trainer materialization must "
                    "not be restated in events policy"
                )
            entries[event.script_name] = EventEntry(
                event.script_name, "trainers", CapabilityState.ENABLED.value
            )
            msgbox = event.instructions[1]
            effect_key = ("side-effect", "msgbox", msgbox.operands[0])
            previous_owner = effect_policy.setdefault(effect_key, "trainers")
            if previous_owner != "trainers":
                raise ContentPortError(
                    f"{event.script_name}: derived trainer effect conflicts with "
                    f"owner {previous_owner!r}"
                )
    validate_event_policy_capabilities(
        entries,
        effect_policy,
        descriptor.capabilities,
        source=event_policy_path,
    )
    while pending_semantics:
        role, dependency = pending_semantics.pop()
        previous_role = semantic_authorities.get(dependency)
        if previous_role is not None:
            if previous_role != role:
                raise ContentPortError(
                    f"{dependency}: ambiguous semantic donor authority "
                    f"{previous_role}/{role}"
                )
            continue
        try:
            record = contexts[role].load(dependency)
        except ContentPortError as error:
            raise ContentPortError(
                f"{dependency}: missing from {role} semantic authority"
            ) from error
        if dependency.domain == "encounter":
            policy = encounter_policies.get(dependency)
            if policy is None:
                raise ContentPortError(
                    f"{dependency}: reachable encounter has no materialization policy"
                )
            expected_role = str(policy["authority"])
            if role != expected_role:
                raise ContentPortError(
                    f"{dependency}: policy authority {expected_role!r} differs from {role!r}"
                )
            profile = record.value.get("profile")
            habitat = str(policy["habitat"])
            required_profile_fields = {"map", "base_label", habitat}
            if not isinstance(profile, Mapping) or not required_profile_fields <= set(
                profile
            ):
                raise ContentPortError(
                    f"{dependency}: authenticated encounter profile is incomplete"
                )
            if (
                profile["base_label"] != dependency.name
                or profile["map"] != f"MAP_{policy['map'].upper()}"
            ):
                raise ContentPortError(
                    f"{dependency}: authenticated encounter identity differs from policy"
                )
            habitat_value = profile[habitat]
            if not isinstance(habitat_value, Mapping):
                raise ContentPortError(f"{dependency}/{habitat}: expected an object")
            mons = habitat_value.get("mons")
            if not isinstance(mons, list):
                raise ContentPortError(f"{dependency}/{habitat}/mons: expected a list")
            projected_species = sorted(
                {str(mon.get("species")) for mon in mons if isinstance(mon, Mapping)}
            )
            if len(projected_species) == 0 or "None" in projected_species:
                raise ContentPortError(
                    f"{dependency}/{habitat}: encounter members are malformed"
                )
            record = SourceRecord(
                {
                    "maps": [profile["map"]],
                    "species": projected_species,
                    "profile": {
                        "map": profile["map"],
                        "base_label": profile["base_label"],
                        habitat: copy.deepcopy(habitat_value),
                    },
                },
                record.provenance,
            )
        semantic_authorities[dependency] = role
        source_records[dependency] = record
        if dependency.domain == "service" and dependency.name not in entries:
            raise ContentPortError(
                f"reachable event service {dependency.name} has no classification"
            )
        extractor = EXTRACTORS[dependency.domain]
        for edge in extractor(contexts[role], dependency, record):
            if edge.target.domain in semantic_domains:
                pending_semantics.append((role, edge.target))
            elif edge.target.domain == "binding":
                binding_dependencies.add(edge.target)

    trainer_party_projections: dict[str, StandardSinglePartyProjection] = {}
    if trainer_materialization is not None:
        declared_species = {
            key.name for key in source_records if key.domain == "species"
        }
        claimed_parties: set[str] = set()
        observed_party_rows: dict[str, tuple[str, ...]] = {}
        expected_placements = materialized_placements(trainer_materialization)
        for source in trainer_materialization.identity_names:
            trainer_key = ResourceKey("trainer", source)
            trainer = source_records.get(trainer_key)
            if trainer is None:
                raise ContentPortError(
                    f"trainer:{source}: authenticated materialized payload is missing"
                )
            parties = tuple(trainer.value.get("parties", ()))
            if len(parties) != 1 or not isinstance(parties[0], str):
                raise ContentPortError(
                    f"trainer:{source}: exactly one authenticated party edge is required"
                )
            party_name = parties[0]
            if party_name in claimed_parties:
                raise ContentPortError(
                    f"party:{party_name}: materialized trainer party edge is not unique"
                )
            claimed_parties.add(party_name)
            party_key = ResourceKey("party", party_name)
            party = source_records.get(party_key)
            if party is None:
                raise ContentPortError(
                    f"party:{party_name}: authenticated materialized payload is missing"
                )
            trainer_party_projections[source] = project_standard_single_party(
                party.value,
                source_trainer=source,
                party_name=party_name,
                known_species=declared_species,
            )
            observed_party_rows[source] = expected_placements[source]
        require_materialization_exact_cover(
            trainer_materialization,
            observed_party_rows,
            owner="authenticated trainer party closure",
        )

    for dependency in sorted(binding_dependencies):
        binding_domain = (
            "flags"
            if dependency.name.startswith("FLAG_")
            else "vars"
            if dependency.name.startswith("VAR_")
            else None
        )
        ledger.resolve(dependency.name, domain=binding_domain)
        source_records[dependency] = SourceRecord(
            {}, Provenance(ledger_path.as_posix(), f"/{dependency.name}")
        )
    enabled_capability_names = {decision.capability for decision in enabled}
    required_assets: set[ResourceKey] = set()
    required_asset_targets: dict[str, str] = {}
    for layout_id, record in selected_layouts.items():
        for field_name in ("border_filepath", "blockdata_filepath"):
            role = layout_field_authorities[layout_id][field_name]
            relative = str(record.value[field_name])
            safe_repo_path(donor_roots[role], relative, allow_missing=False)
            qualified = f"{role}:{relative}"
            required_assets.add(ResourceKey("asset", qualified))
            required_asset_targets[qualified] = relative
    authority_roles = {value: role for role, value in donor_fields.items()}
    for index, item in enumerate(adaptations["tilesetAdaptations"]):
        role = authority_roles.get(item["authority"])
        if role is None:
            raise ContentPortError(
                f"tilesetAdaptations/{index}: unknown donor field authority"
            )
        directory = (
            donor_roots[role]
            / "data"
            / "tilesets"
            / str(item["role"])
            / str(item["directory"])
        )
        direct_files = [path for path in directory.glob("*") if path.is_file()]
        palettes = directory / "palettes"
        palette_files = (
            [path for path in palettes.rglob("*") if path.is_file()]
            if palettes.is_dir()
            else []
        )
        if not direct_files:
            raise ContentPortError(
                f"tilesetAdaptations/{index}: authenticated tileset directory is empty"
            )
        for path in direct_files + palette_files:
            relative = path.relative_to(donor_roots[role]).as_posix()
            safe_repo_path(donor_roots[role], relative, allow_missing=False)
            qualified = f"{role}:{relative}"
            required_assets.add(ResourceKey("asset", qualified))
            target_directory = item.get("targetDirectory", item["directory"])
            target = (
                Path("data")
                / "tilesets"
                / str(item["role"])
                / str(target_directory)
                / path.relative_to(directory)
            ).as_posix()
            required_asset_targets[qualified] = target
    admitted_pic_tokens = {
        identity.projection.pic
        for identity in trainer_inventory.identities
        if identity.projection is not None
    }
    for pic, (source, target) in TRAINER_PIC_ASSET_PROJECTIONS.items():
        if pic not in admitted_pic_tokens:
            continue
        safe_repo_path(content_pin.root, source, allow_missing=False)
        qualified = f"content:{source}"
        required_assets.add(ResourceKey("asset", qualified))
        required_asset_targets[qualified] = target
    asset_policy_references: dict[str, list[str]] = {}
    policy_asset_targets: dict[str, str] = {}
    asset_records = descriptor.assets.get("assets")
    if not isinstance(asset_records, tuple):
        raise ContentPortError("asset policy requires an immutable assets array")
    for index, raw_asset in enumerate(asset_records):
        asset = _thaw(raw_asset)
        if not isinstance(asset, dict):
            raise ContentPortError(f"assets[{index}]: expected object")
        capability = asset.get("capability")
        role = asset.get("donor")
        source_path = asset.get("sourcePath")
        if capability not in enabled_capability_names:
            continue
        if not isinstance(role, str) or role not in donor_roots:
            raise ContentPortError(f"assets[{index}]: unknown donor role {role!r}")
        if not isinstance(source_path, str):
            raise ContentPortError(f"assets[{index}]: invalid sourcePath")
        path = safe_repo_path(donor_roots[role], source_path, allow_missing=False)
        qualified_name = f"{role}:{source_path}"
        semantic_target = asset.get("semanticTarget")
        if not isinstance(semantic_target, str):
            raise ContentPortError(f"assets[{index}]: invalid semanticTarget")
        key = ResourceKey("asset", qualified_name)
        previous = source_records.get(key)
        record = SourceRecord({}, Provenance(path.as_posix(), f"/assets/{index}"))
        if previous is not None and Path(previous.provenance.path) != path:
            raise ContentPortError(
                f"assets[{index}]: conflicting graph provenance for {qualified_name}"
            )
        source_records[key] = record
        asset_policy_references.setdefault(str(capability), []).append(qualified_name)
        if qualified_name in policy_asset_targets:
            raise ContentPortError(
                f"assets[{index}]: duplicate qualified asset {qualified_name}"
            )
        policy_asset_targets[qualified_name] = semantic_target
    asset_policy_keys = {
        ResourceKey("asset", name)
        for names in asset_policy_references.values()
        for name in names
    }
    missing_assets = sorted(required_assets - asset_policy_keys, key=str)
    extra_assets = sorted(asset_policy_keys - required_assets, key=str)
    if missing_assets or extra_assets:
        raise ContentPortError(
            "asset policy must exactly cover resolved physical dependencies; "
            f"missing={missing_assets[:1]}, extra={extra_assets[:1]}"
        )
    if policy_asset_targets != required_asset_targets:
        drift = sorted(
            key
            for key in set(policy_asset_targets) | set(required_asset_targets)
            if policy_asset_targets.get(key) != required_asset_targets.get(key)
        )
        raise ContentPortError(
            "asset policy semantic targets differ from resolved render dependencies; "
            f"drift={drift[:1]}"
        )
    capability_roots: list[ResourceKey] = []
    for decision in enabled:
        key = ResourceKey("capability", f"{decision.map_name}/{decision.capability}")
        references: dict[str, list[str]] = {"map": [decision.map_name]}
        for dependency in decision.dependencies:
            required_capability = {
                "trainer": "trainers",
                "party": "trainers",
                "encounter": "encounters",
            }.get(dependency.domain)
            if (
                required_capability is not None
                and required_capability not in enabled_by_map[decision.map_name]
            ):
                raise ContentPortError(
                    f"{decision.map_name}: dependency {dependency} belongs to "
                    f"disabled capability {required_capability}"
                )
            references.setdefault(dependency.domain, []).append(dependency.name)
        source_records[key] = SourceRecord(
            {"references": references},
            Provenance(
                descriptor.path.as_posix(),
                f"/capabilities/{decision.map_name}/{decision.capability}",
            ),
        )
        capability_roots.append(key)
    for capability, names in sorted(asset_policy_references.items()):
        key = ResourceKey("capability", f"asset-policy/{capability}")
        source_records[key] = SourceRecord(
            {"references": {"asset": sorted(names)}},
            Provenance(descriptor.path.as_posix(), f"/assets/{capability}"),
        )
        capability_roots.append(key)
    resource_capabilities = {
        ResourceKey("map", name): (
            ({"encounters"} if "encounters" in capabilities else set())
            | ({"trainers"} if "trainers" in capabilities else set())
            | ({"events"} if capabilities & event_capabilities else set())
        )
        for name, capabilities in enabled_by_map.items()
    }
    context = SourceContext(
        source_records, aliases=aliases, resource_capabilities=resource_capabilities
    )
    graph = build_source_graph(context, capability_roots)
    enabled_spatial_maps = {
        decision.map_name for decision in enabled if decision.capability == "spatial"
    }
    allowed: set[ResourceKey] = (
        set(capability_roots) | explicit_dependencies | asset_policy_keys
    )
    pending_explicit = list(explicit_dependencies)
    while pending_explicit:
        dependency = pending_explicit.pop()
        for child in graph.dependencies.get(dependency, ()):
            if child not in allowed:
                allowed.add(child)
                pending_explicit.append(child)
    allowed.update(ResourceKey("map", name) for name in enabled_spatial_maps)
    for name in enabled_spatial_maps:
        layout_key = ResourceKey("layout", str(selected_maps[name]["layout"]))
        allowed.add(layout_key)
        layout = selected_layouts[layout_key.name]
        for field_name in (
            "primary_tileset",
            "secondary_tileset",
            "border_filepath",
            "blockdata_filepath",
        ):
            raw_asset = layout.value.get(field_name)
            authority_role = layout_field_authorities[layout_key.name][field_name]
            asset = _key(
                "asset",
                f"{authority_role}:{raw_asset}" if isinstance(raw_asset, str) else None,
            )
            if asset is not None:
                allowed.add(asset)
    enabled_domain_names: set[str] = set()
    for capabilities in enabled_by_map.values():
        if "encounters" in capabilities:
            enabled_domain_names.update(("encounter", "species"))
        if "trainers" in capabilities:
            enabled_domain_names.update(
                (
                    "trainer-event",
                    "trainer",
                    "party",
                    "species",
                    "move",
                    "item",
                    "trainer-class",
                    "asset",
                    "service",
                )
            )
        if capabilities & event_capabilities:
            enabled_domain_names.update(("service", "binding", "asset"))
    allowed.update(key for key in graph.resources if key.domain in enabled_domain_names)
    closure = close_source_graph(graph, capability_roots, frozenset(allowed))
    semantic_evidence: dict[str, str] = {}
    evidenced_domains = {
        "trainer",
        "trainer-event",
        "party",
        "encounter",
        "service",
        "binding",
        "species",
        "move",
        "item",
        "trainer-class",
    }
    for key in sorted(closure):
        if key.domain not in evidenced_domains:
            continue
        role = semantic_authorities.get(
            key, "target" if key.domain == "binding" else ""
        )
        if not role:
            raise ContentPortError(
                f"{key}: resolved semantic resource has no authority"
            )
        record = source_records[key]
        identity = f"{role}:{key.domain}:{key.name}"
        semantic_evidence[identity] = _semantic_record_digest(role, key, record.value)

    rendered_graph = world_graph_from_maps(selected_maps)
    world_policy = adaptations.get("worldPolicy")
    if not isinstance(world_policy, dict) or set(world_policy) != {
        "roots",
        "unreachableShells",
        "gateways",
        "dynamicWarps",
        "scriptWarps",
    }:
        raise ContentPortError(
            "worldPolicy requires exact roots, unreachableShells, gateways, "
            "dynamicWarps, and scriptWarps arrays"
        )
    if not all(isinstance(item, str) and item for item in world_policy["roots"]):
        raise ContentPortError("worldPolicy.roots must contain map names")
    if not all(
        isinstance(item, str) and item for item in world_policy["unreachableShells"]
    ):
        raise ContentPortError("worldPolicy.unreachableShells must contain map names")
    script_edges, owned_script_entries, dynamic_arms = _extract_preserved_script_warps(
        selected_maps, descriptor.map_ownership, target_root
    )
    rendered_graph = with_script_warps(rendered_graph, script_edges)
    deferred_dynamic = frozenset(
        edge.key
        for edge in rendered_graph.edges
        if edge.kind == "warp"
        and not isinstance(edge.target_warp, int)
        and any(
            item["source"] == edge.source
            and item["path"] == f"warp_events/{edge.index}"
            for item in adaptations["deferredEdges"]
        )
    )
    reviewed_one_way = frozenset(
        edge.key
        for edge in rendered_graph.edges
        if edge.kind == "connection"
        and edge.target in rendered_graph.maps
        and not rendered_graph.has_reciprocal(edge)
        and (
            edge.source,
            f"connections/{edge.index}",
            "connection",
            f"MAP_{edge.target}",
        )
        in reviewed_retained
    )
    dynamic_map_aliases = {
        str(document.get("id", name)).removeprefix("MAP_"): name
        for name, document in selected_maps.items()
    }
    for name in selected_maps:
        installed_map = target_root / "data" / "maps" / name / "map.json"
        if installed_map.is_file():
            installed_document = json.loads(installed_map.read_text(encoding="utf-8"))
            dynamic_map_aliases[
                str(installed_document.get("id", name)).removeprefix("MAP_")
            ] = name
    rendered_graph, declared_dynamic_warps, dynamic_gateway_keys = (
        _bind_dynamic_warp_policy(
            rendered_graph,
            world_policy["dynamicWarps"],
            descriptor.map_ownership,
            owned_script_entries,
            dynamic_arms,
            dynamic_map_aliases,
        )
    )
    gateway_keys: set[str] = set()
    for index, item in enumerate(world_policy["gateways"]):
        if not isinstance(item, dict) or set(item) != {
            "source",
            "destination",
            "kind",
            "index",
            "sourceRegion",
            "targetRegion",
        }:
            raise ContentPortError(f"worldPolicy.gateways/{index}: malformed gateway")
        matches = [
            edge
            for edge in rendered_graph.edges
            if edge.kind != "script-warp"
            and edge.source == item["source"]
            and edge.target == item["destination"]
            and edge.kind == item["kind"]
            and edge.index == item["index"]
        ]
        if len(matches) != 1:
            raise ContentPortError(
                f"worldPolicy.gateways/{index}: stale gateway declaration"
            )
        edge = matches[0]
        if (
            rendered_graph.maps[edge.source].region != item["sourceRegion"]
            or rendered_graph.maps[edge.target].region != item["targetRegion"]
        ):
            raise ContentPortError(
                f"worldPolicy.gateways/{index}: gateway region evidence drift"
            )
        gateway_keys.add(edge.key)
    gateway_keys.update(
        _bind_script_warp_policy(
            rendered_graph,
            world_policy["scriptWarps"],
            descriptor.map_ownership,
            owned_script_entries,
        )
    )
    gateway_keys.update(dynamic_gateway_keys)
    validate_world_graph(
        rendered_graph,
        WorldPolicy(
            reviewed_one_way=reviewed_one_way,
            deferred_exits=deferred_dynamic,
            dynamic_warps=declared_dynamic_warps,
            inter_region_gateways=frozenset(gateway_keys),
            roots=frozenset(world_policy["roots"]),
            unreachable_shells=frozenset(world_policy["unreachableShells"])
            | _automatic_unreachable_shells(rendered_graph, warp_removals_by_map),
        ),
    )

    enabled_capabilities = {decision.capability for decision in enabled}
    reachable_services = {key.name for key in closure if key.domain == "service"}
    missing_entries = sorted(reachable_services - set(entries))
    if missing_entries:
        raise ContentPortError(
            f"reachable event service {missing_entries[0]} has no classification"
        )
    stale_enabled_entries = sorted(
        entry.name
        for entry in entries.values()
        if entry.classification == CapabilityState.ENABLED.value
        and entry.capability in enabled_capabilities
        and entry.name not in reachable_services
    )
    if stale_enabled_entries:
        raise ContentPortError(
            f"enabled event entry {stale_enabled_entries[0]} is not reachable"
        )
    for service in sorted(reachable_services):
        entry = entries[service]
        key = ResourceKey("service", service)
        role = semantic_authorities.get(key)
        if role is None:
            raise ContentPortError(
                f"reachable event service {service} has no authority"
            )
        record = source_records[key]
        script_path = record.value.get("script_path")
        if not isinstance(script_path, str):
            raise ContentPortError(
                f"reachable event service {service} has no script source"
            )
        program = parse_scripts([script_path], root=donor_roots[role])
        effects = analyze_entry(program, service)
        validate_effects(entry, effects, effect_policy)
        for effect in effects:
            if (
                effect.kind not in {"state-read", "state-write"}
                or effect.operand is None
            ):
                continue
            binding_domain = (
                "flags"
                if effect.operand.startswith("FLAG_")
                else "vars"
                if effect.operand.startswith("VAR_")
                else None
            )
            ledger.resolve(effect.operand, domain=binding_domain)

    maps_in_closure = tuple(
        name for name in map_names if ResourceKey("map", name) in closure
    )
    layouts_in_closure = tuple(descriptor.allocation_index.layouts)
    tilesets = tuple(
        sorted(
            {
                str(record.value[field_name])
                for record in selected_layouts.values()
                for field_name in ("primary_tileset", "secondary_tileset")
            }
        )
    )
    preserved_maps = tuple(
        name
        for name, ownership in descriptor.map_ownership.items()
        if ownership == "preserve"
    )
    symbols, legacy_inputs = _referenced_inputs(content_pin.root, preserved_maps)
    attribute_formats = _attribute_fixture_evidence(
        adaptations["attributeFixtures"], donor_fields, contexts, donor_roots
    )
    inventory = MappingProxyType(
        {
            "maps": len(maps_in_closure),
            "layouts": len(layouts_in_closure),
            "groups": len(descriptor.allocation_index.groups),
            "sections": len(descriptor.allocation_index.sections),
            "tilesets": len(tilesets),
        }
    )
    inventory_values: Mapping[str, tuple[str, ...]] = {
        "maps": tuple(maps_in_closure),
        "layouts": tuple(layouts_in_closure),
        "groups": tuple(descriptor.allocation_index.groups),
        "sections": tuple(descriptor.allocation_index.sections),
        "tilesets": tilesets,
    }
    for domain, expected in descriptor.expected_inventory.items():
        if inventory[domain] != expected["count"]:
            raise ContentPortError(
                f"{domain} inventory count {inventory[domain]} != reviewed {expected['count']}"
            )
        actual_digest = _inventory_digest(inventory_values[domain])
        if actual_digest != expected["digest"]:
            raise ContentPortError(
                f"{domain} inventory digest {actual_digest} != reviewed {expected['digest']}"
            )
    closure_report = MappingProxyType(
        {
            "maps": maps_in_closure,
            "layouts": layouts_in_closure,
            "groups": tuple(sorted(descriptor.allocation_index.groups)),
            "sections": tuple(sorted(descriptor.allocation_index.sections)),
            "tilesets": tilesets,
            "symbols": symbols,
            "deferred_edges": tuple(
                sorted(
                    (item["source"], item["kind"], item["destination"])
                    for item in adaptations["deferredEdges"]
                )
            ),
            "resources": tuple(str(key) for key in closure),
        }
    )
    legacy = descriptor.legacy_report
    actual_legacy_evidence = {
        "attributeFormats": _thaw(attribute_formats),
        "inputs": _thaw(legacy_inputs),
        "donors": {
            role: {
                "commit": pin.commit,
                "sourceTreeDigest": pin.tree_digest,
                "fileCount": pin.file_count,
            }
            for role, pin in donor_pins.items()
        },
    }
    if legacy is not None:
        legacy_inventory = legacy.get("inventory")
        legacy_closure = legacy.get("closure")
        legacy_evidence = legacy.get("evidence")
        if (
            not isinstance(legacy_inventory, Mapping)
            or not isinstance(legacy_closure, Mapping)
            or not isinstance(legacy_evidence, Mapping)
        ):
            raise ContentPortError(
                "declared legacy baseline lacks inventory, closure, or evidence"
            )
        if dict(inventory) != dict(legacy_inventory):
            raise ContentPortError(
                "current inventory differs from declared legacy baseline"
            )
        for field_name in (
            "maps",
            "layouts",
            "groups",
            "sections",
            "tilesets",
            "symbols",
            "deferred_edges",
        ):
            if _thaw(closure_report[field_name]) != _thaw(
                legacy_closure.get(field_name)
            ):
                raise ContentPortError(
                    f"current closure field {field_name} differs from declared legacy baseline"
                )
        for field_name, value in actual_legacy_evidence.items():
            if value != _thaw(legacy_evidence.get(field_name)):
                raise ContentPortError(
                    f"current evidence field {field_name} differs from declared legacy baseline"
                )
    provenance_roots = tuple(
        (role, root.resolve()) for role, root in sorted(donor_roots.items())
    ) + (("target", target_root.resolve()),)

    def stable_provenance(value: Provenance) -> str:
        if value.path.startswith("<"):
            return str(value)
        path = Path(value.path).resolve()
        for role, root in provenance_roots:
            try:
                return f"{role}:{path.relative_to(root).as_posix()}{value.location}"
            except ValueError:
                continue
        return f"external:{path.name}{value.location}"

    evidence = MappingProxyType(
        {
            "graphDigest": _canonical_digest(
                f"{edge.source}->{edge.target}@{stable_provenance(edge.provenance)}"
                for edge in graph.edges
            ),
            "resourceDigest": _canonical_digest(str(key) for key in closure),
            "inputDigest": _canonical_digest(input_evidence),
            "resourceCount": len(closure),
            "edgeCount": len(graph.edges),
            "enabledCapabilityCount": len(enabled),
            "attributeFormats": attribute_formats,
            "inputs": legacy_inputs,
        }
    )
    contract = ContractEvidence(inventory, closure_report, evidence)
    state = PortSourceState(
        maps=_freeze_state(selected_maps),
        layouts=_freeze_state(
            {name: record.value for name, record in selected_layouts.items()}
        ),
        map_authorities=MappingProxyType(dict(map_authorities)),
        layout_authorities=MappingProxyType(dict(layout_authorities)),
        layout_field_authorities=MappingProxyType(
            {
                layout_id: MappingProxyType(dict(sorted(fields.items())))
                for layout_id, fields in sorted(layout_field_authorities.items())
            }
        ),
        donor_roots=MappingProxyType(dict(donor_roots)),
        resources=graph.resources,
        inventory=MappingProxyType(
            {
                **inventory_values,
                "asset-policy": tuple(sorted(key.name for key in asset_policy_keys)),
                "asset-required": tuple(sorted(key.name for key in required_assets)),
            }
        ),
        asset_targets=MappingProxyType(dict(sorted(required_asset_targets.items()))),
        semantic_evidence=MappingProxyType(dict(sorted(semantic_evidence.items()))),
        semantic_values=MappingProxyType(
            {
                key: _freeze_state(source_records[key].value)
                for key in sorted(closure)
                if key.domain in semantic_domains
            }
        ),
        trainer_events=MappingProxyType(
            {name: events for name, events in sorted(selected_trainer_events.items())}
        ),
        trainer_inventory=trainer_inventory,
        materialization_maps=_freeze_state(materialization_maps),
        trainer_materialization=trainer_materialization,
        trainer_event_projections=MappingProxyType(
            {name: events for name, events in sorted(projected_trainer_events.items())}
        ),
        trainer_party_projections=MappingProxyType(
            dict(sorted(trainer_party_projections.items()))
        ),
    )
    return contract, state


def validate_port_sources(
    descriptor: PortDescriptor, repo: Path | str
) -> ContractEvidence:
    """Validate a port and return its deterministic contract evidence."""
    return resolve_port_sources(descriptor, repo)[0]
