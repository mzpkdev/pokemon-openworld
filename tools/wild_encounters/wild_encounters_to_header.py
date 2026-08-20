import argparse
from fractions import Fraction
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENCOUNTERS = ROOT / "src/data/wild_encounters.json"
DEFAULT_REGISTRY = ROOT / "src/data/wild_encounter_registry.json"
DEFAULT_SCALING = ROOT / "src/data/wild_encounter_scaling.json"
DEFAULT_WILD_ENCOUNTER_SPECIES = ROOT / "src/data/wild_encounter_species.json"
DEFAULT_OUTPUT = ROOT / "src/data/wild_encounters.h"
DEFAULT_BALANCE_AUDIT = ROOT / "build/wild-encounter-balance-audit.json"
DEFAULT_CONFIG = ROOT / "include/config/overworld.h"
DEFAULT_RTC_CONSTANTS = ROOT / "include/constants/rtc.h"
DEFAULT_MAP_GROUPS = ROOT / "data/maps/map_groups.json"
DEFAULT_MAPS_ROOT = ROOT / "data/maps"
DEFAULT_MAP_SECTIONS = ROOT / "src/data/region_map/region_map_sections.json"
DEFAULT_SPECIES = ROOT / "include/constants/species.h"
DEFAULT_SPECIES_INFO = ROOT / "src/data/pokemon/species_info.h"
DEFAULT_SPECIES_CONFIG = ROOT / "include/config/pokemon.h"
DEFAULT_REGIONAL_FACTS = ROOT / "include/regional_fact.h"
DEFAULT_TIME_POLICIES = ROOT / "src/data/wild_encounter_time_policies.json"

REVIEWED_METHOD_TIME_FALLBACKS = frozenset(
    {
        ("RuinsOfAlph_Outside", "rock_smash_mons", "TIME_NIGHT", "TIME_DAY"),
        ("CianwoodCity", "rock_smash_mons", "TIME_NIGHT", "TIME_DAY"),
        ("MtSilver_MountainSide", "fishing_mons", "TIME_NIGHT", "TIME_DAY"),
        ("Route26", "rock_smash_mons", "TIME_NIGHT", "TIME_DAY"),
        ("Route26North", "rock_smash_mons", "TIME_NIGHT", "TIME_DAY"),
    }
)

PROFILE_FIELDS = (
    "group",
    "label",
    "header",
    "residency",
    "time",
    "alternate_of",
    "variant_set",
    "variant_index",
)
FALLBACK_TIME_ROLE = "TIME_FALLBACK"
RESIDENCIES = {"hoenn", "kanto", "sevii", "johto"}
REVIEWED_PROFILE_COUNT = 547
REVIEWED_RESIDENCY_COUNTS = {
    "hoenn": 136,
    "kanto": 132,
    "sevii": 132,
    "johto": 147,
}
# SHA-256 of compact JSON containing every PROFILE_FIELDS value in registry order.
REVIEWED_ORDERED_PROFILE_SHA256 = (
    "be359a0f716d3710d7ab9ded8b04eeed90040c446bf95c491783c9c80f79a683"
)
# Deliberately revised only when authenticated authored encounter content changes.
REVIEWED_AUTHORED_CONTRACT_SHA256 = (
    "a4645b254cfd3721f535ce983ee7a778bea9747b1215e9522b5b09321263d4bc"
)
NON_MAP_RESIDENCY = {
    "gBattlePyramidWildMonHeaders": "hoenn",
    "gBattlePikeWildMonHeaders": "hoenn",
}
DEFAULT_OUTPUT_MODE = 0o644
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAP_IDENTIFIER = re.compile(r"^MAP_[A-Z0-9_]+$")
SPECIES_IDENTIFIER = re.compile(r"^SPECIES_[A-Z0-9_]+$")
METHOD_AREAS = {
    "land_mons": "WILD_AREA_LAND",
    "water_mons": "WILD_AREA_WATER",
    "rock_smash_mons": "WILD_AREA_ROCKS",
    "fishing_mons": "WILD_AREA_FISHING",
}
FISHING_RODS = {
    "NONE": "WILD_ENCOUNTER_FISHING_ROD_NONE",
    "OLD_ROD": "OLD_ROD",
    "GOOD_ROD": "GOOD_ROD",
    "SUPER_ROD": "SUPER_ROD",
}
MAX_TRAINER_RATING_PROJECTION_CAP = 0xFF
MAX_TRAINER_RATING_SOURCE_VALUE = 0xFF
MAX_TRAINER_RATING_MAXIMUM = 0xFFFF
MAX_PROFILE_LEVEL_OFFSET = 5
MAX_ORDINARY_WILD_LEVEL = 100
MAX_WILD_ENCOUNTER_SPECIES_METADATA = 0xFFFF
TRAINER_RATING_SOURCE_KINDS = {"badge", "story"}
ZONE_IDENTITY_SHAPES = {"quadraticEaseOut", "quadraticEaseIn"}
REQUIRED_AUDIT_RATINGS = (0, 4, 8, 16, 20, 29, 30, 39, 40, 55, 65, 71, 80)
NON_LEVEL_EVOLUTION_METHODS = {
    "EVO_TRADE",
    "EVO_ITEM",
    "EVO_SPLIT_FROM_EVO",
    "EVO_SCRIPT_TRIGGER",
    "EVO_LEVEL_BATTLE_ONLY",
    "EVO_BATTLE_END",
    "EVO_SPIN",
}
PRODUCT_GUARD = re.compile(
    r"^\s*#\s*(?:if|ifdef|ifndef)\b[^\n]*\b(?:EMERALD|FIRERED|LEAFGREEN)\b",
    re.MULTILINE,
)


def _altering_cave_labels(prefix, product=""):
    if product:
        return tuple(
            f"{prefix}{'' if index == 1 else f'_{index}'}_{product}"
            for index in range(1, 10)
        )
    return tuple(f"{prefix}{index}" for index in range(1, 10))


ALTERING_CAVE_VARIANTS = {
    "hoenn_altering_cave": {
        "labels": _altering_cave_labels("gAlteringCave"),
        "map": "MAP_ALTERING_CAVE",
        "residency": "hoenn",
        "alternates": (None,) * 9,
    },
    "sevii_altering_cave_firered": {
        "labels": _altering_cave_labels("sSixIslandAlteringCave", "FireRed"),
        "map": "MAP_SIX_ISLAND_ALTERING_CAVE",
        "residency": "sevii",
        "alternates": (None,) * 9,
    },
    "sevii_altering_cave_leafgreen": {
        "labels": _altering_cave_labels("sSixIslandAlteringCave", "LeafGreen"),
        "map": "MAP_SIX_ISLAND_ALTERING_CAVE",
        "residency": "sevii",
        "alternates": _altering_cave_labels("sSixIslandAlteringCave", "FireRed"),
    },
}


class ValidationError(ValueError):
    pass


def _load_json(path):
    try:
        with Path(path).open(encoding="utf-8") as source:
            return json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"{path}: {error}") from error


def _require_exact_keys(value, expected, location):
    if not isinstance(value, dict):
        raise ValidationError(f"{location}: expected object")
    actual = set(value)
    expected = set(expected)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing {missing}")
        if unexpected:
            details.append(f"unexpected {unexpected}")
        raise ValidationError(f"{location}: {'; '.join(details)}")


def _require_identifier(value, location, pattern=IDENTIFIER):
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValidationError(f"{location}: invalid identifier {value!r}")
    return value


def _require_int(value, location, minimum, maximum):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValidationError(
            f"{location}: expected integer from {minimum} through {maximum}"
        )
    return value


def _load_regional_facts(path):
    try:
        source = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise ValidationError(f"{path}: {error}") from error
    match = re.search(r"enum\s+RegionalFact\s*\{(.*?)\};", source, re.DOTALL)
    if match is None:
        raise ValidationError(f"{path}: missing enum RegionalFact")
    facts = set(re.findall(r"\bREGIONAL_FACT_[A-Z0-9_]+\b", match.group(1)))
    facts.discard("REGIONAL_FACT_COUNT")
    if not facts:
        raise ValidationError(f"{path}: enum RegionalFact has no facts")
    return facts


def _interpolate_fraction(start, end, progress):
    return start + (end - start) * progress


def _round_half_up(value):
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def _load_scaling(path, regional_facts_path):
    document = _load_json(path)
    _require_exact_keys(
        document,
        {
            "schemaVersion",
            "trainerRating",
            "levelAnchors",
            "zoneIdentity",
            "profileOffsets",
        },
        path,
    )
    if document["schemaVersion"] != 1 or isinstance(document["schemaVersion"], bool):
        raise ValidationError(f"{path}/schemaVersion: expected 1")

    trainer_rating = document["trainerRating"]
    _require_exact_keys(
        trainer_rating,
        {"projectionCap", "badgeSegments", "sources"},
        f"{path}/trainerRating",
    )
    projection_cap = _require_int(
        trainer_rating["projectionCap"],
        f"{path}/trainerRating/projectionCap",
        1,
        MAX_TRAINER_RATING_PROJECTION_CAP,
    )
    regional_facts = _load_regional_facts(regional_facts_path)

    segments = trainer_rating["badgeSegments"]
    if not isinstance(segments, list) or not segments:
        raise ValidationError(
            f"{path}/trainerRating/badgeSegments: expected nonempty list"
        )
    badge_segments = []
    expected_first_badge = 1
    for index, row in enumerate(segments):
        location = f"{path}/trainerRating/badgeSegments/{index}"
        _require_exact_keys(row, {"firstBadgeOrdinal", "badgeCount", "value"}, location)
        first_badge = _require_int(
            row["firstBadgeOrdinal"], f"{location}/firstBadgeOrdinal", 1, 255
        )
        badge_count = _require_int(row["badgeCount"], f"{location}/badgeCount", 1, 255)
        value = _require_int(
            row["value"],
            f"{location}/value",
            1,
            MAX_TRAINER_RATING_SOURCE_VALUE,
        )
        if first_badge != expected_first_badge:
            raise ValidationError(
                f"{location}/firstBadgeOrdinal: badge segments must be contiguous from 1"
            )
        if first_badge + badge_count - 1 > 255:
            raise ValidationError(f"{location}: badge ordinal exceeds 255")
        expected_first_badge += badge_count
        badge_segments.append(
            {
                "first_badge_ordinal": first_badge,
                "badge_count": badge_count,
                "value": value,
            }
        )

    sources = trainer_rating["sources"]
    if not isinstance(sources, list) or not sources:
        raise ValidationError(f"{path}/trainerRating/sources: expected nonempty list")
    source_ids = set()
    normalized_sources = []
    badge_source_count = 0
    story_rating = 0
    for index, row in enumerate(sources):
        location = f"{path}/trainerRating/sources/{index}"
        if not isinstance(row, dict):
            raise ValidationError(f"{location}: expected object")
        kind = row.get("kind")
        expected_keys = {"id", "kind"} if kind == "badge" else {"id", "kind", "value"}
        _require_exact_keys(row, expected_keys, location)
        source_id = _require_identifier(row["id"], f"{location}/id")
        if source_id not in regional_facts:
            raise ValidationError(f"{location}/id: unknown regional fact {source_id}")
        if source_id in source_ids:
            raise ValidationError(f"{location}/id: duplicate rating source")
        source_ids.add(source_id)
        if kind not in TRAINER_RATING_SOURCE_KINDS:
            raise ValidationError(f"{location}/kind: expected badge or story")
        if kind == "badge":
            badge_source_count += 1
            value = 0
        else:
            value = _require_int(
                row["value"],
                f"{location}/value",
                1,
                MAX_TRAINER_RATING_SOURCE_VALUE,
            )
            story_rating += value
        normalized_sources.append(
            {
                "id": source_id,
                "kind": kind,
                "value": value,
            }
        )

    configured_badges = sum(segment["badge_count"] for segment in badge_segments)
    if badge_source_count > configured_badges:
        raise ValidationError(
            f"{path}/trainerRating/sources: {badge_source_count} badge sources exceed "
            f"the {configured_badges} configured badge ordinals"
        )
    badge_rating = 0
    remaining_badges = badge_source_count
    for segment in badge_segments:
        earned_badges = min(remaining_badges, segment["badge_count"])
        badge_rating += earned_badges * segment["value"]
        remaining_badges -= earned_badges
    maximum_rating = badge_rating + story_rating
    if maximum_rating > MAX_TRAINER_RATING_MAXIMUM:
        raise ValidationError(
            f"{path}/trainerRating: configured maximum rating {maximum_rating} "
            f"does not fit u16"
        )

    anchors = document["levelAnchors"]
    if not isinstance(anchors, list) or len(anchors) < 2:
        raise ValidationError(f"{path}/levelAnchors: expected at least two anchors")
    normalized_anchors = []
    previous_rating = None
    previous_level = None
    for index, row in enumerate(anchors):
        location = f"{path}/levelAnchors/{index}"
        _require_exact_keys(row, {"rating", "level"}, location)
        rating = _require_int(row["rating"], f"{location}/rating", 0, projection_cap)
        level = _require_int(
            row["level"], f"{location}/level", 1, MAX_ORDINARY_WILD_LEVEL
        )
        if previous_rating is not None and rating <= previous_rating:
            raise ValidationError(
                f"{location}/rating: anchors must be strictly ordered"
            )
        if previous_level is not None and level <= previous_level:
            raise ValidationError(f"{location}/level: anchors must rise with rating")
        previous_rating = rating
        previous_level = level
        normalized_anchors.append({"rating": rating, "level": level})
    if normalized_anchors[0]["rating"] != 0:
        raise ValidationError(f"{path}/levelAnchors: first anchor must be rating 0")
    if normalized_anchors[-1]["rating"] != projection_cap:
        raise ValidationError(
            f"{path}/levelAnchors: final anchor must equal projection cap {projection_cap}"
        )

    zone_identity = document["zoneIdentity"]
    _require_exact_keys(
        zone_identity, {"opening", "convergence"}, f"{path}/zoneIdentity"
    )
    normalized_identity = []
    for name in ("opening", "convergence"):
        row = zone_identity[name]
        location = f"{path}/zoneIdentity/{name}"
        _require_exact_keys(
            row,
            {
                "startRating",
                "endRating",
                "startRetentionBasisPoints",
                "endRetentionBasisPoints",
                "shape",
            },
            location,
        )
        start_rating = _require_int(
            row["startRating"], f"{location}/startRating", 0, projection_cap
        )
        end_rating = _require_int(
            row["endRating"], f"{location}/endRating", 0, projection_cap
        )
        if end_rating <= start_rating:
            raise ValidationError(f"{location}: endRating must follow startRating")
        start_retention = _require_int(
            row["startRetentionBasisPoints"],
            f"{location}/startRetentionBasisPoints",
            0,
            10000,
        )
        end_retention = _require_int(
            row["endRetentionBasisPoints"],
            f"{location}/endRetentionBasisPoints",
            0,
            10000,
        )
        shape = row["shape"]
        if shape not in ZONE_IDENTITY_SHAPES:
            raise ValidationError(
                f"{location}/shape: expected one of {sorted(ZONE_IDENTITY_SHAPES)}"
            )
        normalized_identity.append(
            {
                "start_rating": start_rating,
                "end_rating": end_rating,
                "start_retention": start_retention,
                "end_retention": end_retention,
                "shape": shape,
            }
        )
    if normalized_identity[0]["start_rating"] != 0:
        raise ValidationError(f"{path}/zoneIdentity/opening: must begin at rating 0")
    if normalized_identity[-1]["end_rating"] != projection_cap:
        raise ValidationError(
            f"{path}/zoneIdentity/convergence: must end at projection cap {projection_cap}"
        )
    if normalized_identity[0]["end_rating"] != normalized_identity[1]["start_rating"]:
        raise ValidationError(f"{path}/zoneIdentity: segments must be contiguous")
    if (
        normalized_identity[0]["end_retention"]
        != normalized_identity[1]["start_retention"]
    ):
        raise ValidationError(f"{path}/zoneIdentity: segment retentions must join")

    points = []
    anchor_index = 0
    identity_index = 0
    for rating in range(projection_cap + 1):
        while rating > normalized_anchors[anchor_index + 1]["rating"]:
            anchor_index += 1
        anchor_start = normalized_anchors[anchor_index]
        anchor_end = normalized_anchors[anchor_index + 1]
        anchor_progress = Fraction(
            rating - anchor_start["rating"],
            anchor_end["rating"] - anchor_start["rating"],
        )
        anchor_level = _round_half_up(
            _interpolate_fraction(
                Fraction(anchor_start["level"]),
                Fraction(anchor_end["level"]),
                anchor_progress,
            )
        )
        while rating > normalized_identity[identity_index]["end_rating"]:
            identity_index += 1
        identity = normalized_identity[identity_index]
        progress = Fraction(
            rating - identity["start_rating"],
            identity["end_rating"] - identity["start_rating"],
        )
        if identity["shape"] == "quadraticEaseOut":
            eased = 1 - (1 - progress) ** 2
        else:
            eased = progress**2
        retention = _interpolate_fraction(
            Fraction(identity["start_retention"], 10000),
            Fraction(identity["end_retention"], 10000),
            eased,
        )
        if retention.numerator > 0xFFFF or retention.denominator > 0xFFFF:
            raise ValidationError(
                f"{path}/zoneIdentity: retention for rating {rating} does not fit u16"
            )
        points.append(
            {
                "anchor_level": anchor_level,
                "retention_numerator": retention.numerator,
                "retention_denominator": retention.denominator,
            }
        )

    return {
        "projection_cap": projection_cap,
        "maximum_rating": maximum_rating,
        "badge_segments": badge_segments,
        "sources": normalized_sources,
        "anchors": normalized_anchors,
        "points": points,
        "profile_offsets": document["profileOffsets"],
    }


class Config:
    def __init__(self, config_file_name, rtc_constants_file_name, encounters_json_data):
        self.times_of_day = self._parse_time_enum(rtc_constants_file_name)
        self.time_default = self._parse_time_default(
            rtc_constants_file_name, self.times_of_day
        )
        self.mon_types = self._parse_mon_types(encounters_json_data)
        definitions = self._parse_time_config(config_file_name)
        self.time_encounters = definitions["OW_TIME_OF_DAY_ENCOUNTERS"] == "TRUE"
        self.disable_time_fallback = (
            definitions["OW_TIME_OF_DAY_DISABLE_FALLBACK"] == "TRUE"
        )
        self.time_fallback = definitions["OW_TIME_OF_DAY_FALLBACK"]
        if self.time_fallback not in self.times_of_day:
            raise ValidationError(
                f"{config_file_name}: unresolved OW_TIME_OF_DAY_FALLBACK "
                f"{self.time_fallback!r}"
            )
        self.runtime_canonical_time = (
            self.time_fallback if self.time_encounters else self.time_default
        )

    @staticmethod
    def _parse_time_enum(path):
        try:
            source = Path(path).read_text(encoding="utf-8")
        except OSError as error:
            raise ValidationError(f"{path}: {error}") from error
        match = re.search(
            r"enum\s+TimeOfDay\s*\{(?P<body>.*?)\}\s*;", source, re.DOTALL
        )
        if match is None:
            raise ValidationError(f"{path}: failed to parse enum TimeOfDay")
        names = re.findall(r"\bTIME_[A-Z0-9_]+\b", match.group("body"))
        if not names or len(names) != len(set(names)):
            raise ValidationError(f"{path}: invalid or duplicate time identities")
        return {
            name: name.removeprefix("TIME_").title().replace("_", "") for name in names
        }

    @staticmethod
    def _parse_time_default(path, times):
        try:
            source = Path(path).read_text(encoding="utf-8")
        except OSError as error:
            raise ValidationError(f"{path}: {error}") from error
        values = re.findall(
            r"^\s*#define\s+TIME_OF_DAY_DEFAULT\s+([A-Z0-9_]+)\s*(?://.*)?$",
            source,
            re.MULTILINE,
        )
        if len(values) != 1:
            raise ValidationError(
                f"{path}: expected exactly one TIME_OF_DAY_DEFAULT definition"
            )
        value = values[0]
        if value in times:
            return value
        if value.isdecimal():
            index = int(value)
            names = list(times)
            if 0 <= index < len(names):
                return names[index]
        raise ValidationError(f"{path}: unresolved TIME_OF_DAY_DEFAULT {value!r}")

    @staticmethod
    def _parse_mon_types(encounters):
        groups = encounters.get("wild_encounter_groups")
        if not isinstance(groups, list):
            raise ValidationError(
                "wild_encounters.json: wild_encounter_groups must be a list"
            )
        result = []
        for group in groups:
            if isinstance(group, dict):
                for field in group.get("fields", []):
                    if isinstance(field, dict) and isinstance(field.get("type"), str):
                        result.append(field["type"])
        if not result or len(result) != len(set(result)):
            raise ValidationError(
                "wild_encounters.json: fields must define unique encounter types"
            )
        return result

    @staticmethod
    def _parse_time_config(path):
        try:
            source = Path(path).read_text(encoding="utf-8")
        except OSError as error:
            raise ValidationError(f"{path}: {error}") from error
        names = (
            "OW_TIME_OF_DAY_ENCOUNTERS",
            "OW_TIME_OF_DAY_DISABLE_FALLBACK",
            "OW_TIME_OF_DAY_FALLBACK",
        )
        definitions = {}
        for name in names:
            values = re.findall(
                rf"^\s*#define\s+{name}\s+(\w+)\s*(?://.*)?$", source, re.MULTILINE
            )
            if len(values) != 1:
                raise ValidationError(f"{path}: expected exactly one {name} definition")
            definitions[name] = values[0]
        for name in names[:2]:
            if definitions[name] not in {"TRUE", "FALSE"}:
                raise ValidationError(f"{path}: {name} must be TRUE or FALSE")
        return definitions


def _load_map_authority(map_groups_path, maps_root, map_sections_path):
    groups = _load_json(map_groups_path)
    if not isinstance(groups, dict) or not isinstance(groups.get("group_order"), list):
        raise ValidationError(f"{map_groups_path}: invalid group_order")
    group_names = groups["group_order"]
    if len(group_names) != len(set(group_names)):
        raise ValidationError(f"{map_groups_path}: duplicate map group")

    sections_document = _load_json(map_sections_path)
    _require_exact_keys(
        sections_document, {"map_section_count", "map_sections"}, map_sections_path
    )
    sections = sections_document["map_sections"]
    if not isinstance(sections, list) or sections_document["map_section_count"] != len(
        sections
    ):
        raise ValidationError(f"{map_sections_path}: map section count mismatch")
    section_by_id = {}
    for index, section in enumerate(sections):
        location = f"{map_sections_path}/map_sections/{index}"
        if not isinstance(section, dict):
            raise ValidationError(f"{location}: expected object")
        section_id = _require_identifier(section.get("id"), f"{location}/id")
        if section_id in section_by_id:
            raise ValidationError(f"{location}: duplicate map section {section_id}")
        section_by_id[section_id] = section

    maps = {}
    for group_name in group_names:
        map_names = groups.get(group_name)
        if not isinstance(group_name, str) or not isinstance(map_names, list):
            raise ValidationError(
                f"{map_groups_path}: invalid map group {group_name!r}"
            )
        for map_name in map_names:
            if not isinstance(map_name, str):
                raise ValidationError(
                    f"{map_groups_path}/{group_name}: invalid map name"
                )
            map_path = Path(maps_root) / map_name / "map.json"
            map_data = _load_json(map_path)
            canonical_map_name = _require_identifier(
                map_data.get("name"), f"{map_path}/name"
            )
            if canonical_map_name != map_name:
                raise ValidationError(
                    f"{map_path}: map name {canonical_map_name} does not match "
                    f"registered name {map_name}"
                )
            map_id = _require_identifier(
                map_data.get("id"), f"{map_path}/id", MAP_IDENTIFIER
            )
            if map_id in maps:
                raise ValidationError(f"{map_path}: duplicate map identity {map_id}")
            section_id = _require_identifier(
                map_data.get("region_map_section"), f"{map_path}/region_map_section"
            )
            if section_id not in section_by_id:
                raise ValidationError(
                    f"{map_path}: unresolved map section {section_id}"
                )
            maps[map_id] = (map_data, section_by_id[section_id])
    return maps


def _expected_residency(map_data, section):
    region = map_data.get("region")
    if region == "REGION_JOHTO":
        return "johto"
    if region == "REGION_HOENN":
        return "hoenn"
    if region == "REGION_KANTO":
        presentation = section.get("region_map_type")
        if presentation == "REGION_MAP_KANTO":
            return "kanto"
        if presentation in {
            "REGION_MAP_SEVII123",
            "REGION_MAP_SEVII45",
            "REGION_MAP_SEVII67",
        }:
            return "sevii"
    raise ValidationError(
        f"map {map_data.get('id')}: unresolved residency from {region!r}/"
        f"{section.get('region_map_type')!r}"
    )


def _load_species(path):
    try:
        source = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise ValidationError(f"{path}: {error}") from error
    species = set(re.findall(r"\bSPECIES_[A-Z0-9_]+\b", source))
    if not species:
        raise ValidationError(f"{path}: no species identities found")
    return species


def _find_matching_delimiter(source, start, opening, closing, location):
    depth = 0
    quote = None
    escaped = False
    for index in range(start, len(source)):
        character = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return index
    raise ValidationError(f"{location}: unbalanced {opening}{closing} delimiters")


def _split_top_level(value):
    parts = []
    start = 0
    parentheses = 0
    braces = 0
    brackets = 0
    quote = None
    escaped = False
    for index, character in enumerate(value):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "(":
            parentheses += 1
        elif character == ")":
            parentheses -= 1
        elif character == "{":
            braces += 1
        elif character == "}":
            braces -= 1
        elif character == "[":
            brackets += 1
        elif character == "]":
            brackets -= 1
        elif character == "," and not parentheses and not braces and not brackets:
            parts.append(value[start:index].strip())
            start = index + 1
    parts.append(value[start:].strip())
    return parts


def _top_level_braced_items(source, location):
    items = []
    depth = 0
    start = None
    quote = None
    escaped = False
    for index, character in enumerate(source):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "{":
            if depth == 0:
                start = index
            depth += 1
        elif character == "}":
            depth -= 1
            if depth < 0:
                raise ValidationError(f"{location}: unbalanced braces")
            if depth == 0:
                items.append(source[start + 1 : index])
    if depth != 0:
        raise ValidationError(f"{location}: unbalanced braces")
    return items


def _preprocess_species_info(path):
    command = [
        os.environ.get("CPP", "cpp"),
        "-P",
        "-DTRUE=1",
        "-DFALSE=0",
        "-I",
        str(ROOT / "include"),
        "-I",
        str(ROOT),
        "-include",
        str(DEFAULT_SPECIES_CONFIG),
        str(path),
    ]
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False)
    except OSError as error:
        raise ValidationError(
            f"{path}: failed to run active-source preprocessor: {error}"
        ) from error
    if result.returncode != 0:
        details = result.stderr.strip() or f"exit status {result.returncode}"
        raise ValidationError(f"{path}: active-source preprocessing failed: {details}")
    return result.stdout


def _extract_active_evolution_entries(species_info_path):
    source = _preprocess_species_info(species_info_path)
    entries = {}
    for match in re.finditer(r"\[\s*(SPECIES_[A-Z0-9_]+)\s*\]\s*=\s*\{", source):
        species = match.group(1)
        start = match.end() - 1
        end = _find_matching_delimiter(source, start, "{", "}", species_info_path)
        body = source[start : end + 1]
        evolution_match = re.search(r"\.evolutions\s*=", body)
        if evolution_match is None:
            evolutions = []
        else:
            expression_start = evolution_match.end()
            first_brace = body.find("{", expression_start)
            if first_brace == -1:
                raise ValidationError(
                    f"{species_info_path}/{species}: malformed evolutions"
                )
            prefix = body[expression_start:first_brace]
            if "EVOLUTION" in prefix:
                opening = body.find("(", expression_start, first_brace)
                if opening == -1:
                    raise ValidationError(
                        f"{species_info_path}/{species}: malformed EVOLUTION"
                    )
                closing = _find_matching_delimiter(
                    body, opening, "(", ")", f"{species_info_path}/{species}"
                )
                rows = _top_level_braced_items(
                    body[opening + 1 : closing], f"{species_info_path}/{species}"
                )
            else:
                closing = _find_matching_delimiter(
                    body, first_brace, "{", "}", f"{species_info_path}/{species}"
                )
                rows = _top_level_braced_items(
                    body[first_brace + 1 : closing], f"{species_info_path}/{species}"
                )
            evolutions = []
            for row in rows:
                fields = _split_top_level(row)
                if fields == ["EVOLUTIONS_END"]:
                    continue
                if len(fields) < 3:
                    raise ValidationError(
                        f"{species_info_path}/{species}: malformed evolution row"
                    )
                method, parameter, target = fields[:3]
                if not IDENTIFIER.fullmatch(method):
                    raise ValidationError(
                        f"{species_info_path}/{species}: invalid evolution method {method!r}"
                    )
                if not SPECIES_IDENTIFIER.fullmatch(target):
                    raise ValidationError(
                        f"{species_info_path}/{species}: invalid evolution target {target!r}"
                    )
                evolutions.append(
                    {"method": method, "parameter": parameter, "target": target}
                )
        if species in entries:
            raise ValidationError(
                f"{species_info_path}: duplicate active species {species}"
            )
        entries[species] = evolutions
    if not entries:
        raise ValidationError(
            f"{species_info_path}: no active species evolution entries"
        )
    return entries


def _ordinary_runtime_species(profiles, encounters, config, time_policy_labels):
    encounter_by_label = {
        encounter["base_label"]: encounter
        for group in encounters["wild_encounter_groups"]
        for encounter in group["encounters"]
    }
    species = set()
    for profile in _select_runtime_profiles(profiles, config, time_policy_labels):
        if profile["group"] != "gWildMonHeaders":
            continue
        encounter = encounter_by_label[profile["label"]]
        for method in config.mon_types:
            for mon in encounter.get(method, {}).get("mons", []):
                species.add(mon["species"])
    if not species:
        raise ValidationError("standard encounter authority has no active species")
    return species


def _load_wild_encounter_species_metadata(
    path, species_info_path, known_species, ordinary_species
):
    document = _load_json(path)
    _require_exact_keys(
        document,
        {"schemaVersion", "minimumOrdinaryWildLevels", "predecessorResolutions"},
        path,
    )
    if document["schemaVersion"] != 1 or isinstance(document["schemaVersion"], bool):
        raise ValidationError(f"{path}/schemaVersion: expected 1")

    minimum_rows = document["minimumOrdinaryWildLevels"]
    if not isinstance(minimum_rows, list):
        raise ValidationError(f"{path}/minimumOrdinaryWildLevels: expected list")
    minimum_levels = {}
    for index, row in enumerate(minimum_rows):
        location = f"{path}/minimumOrdinaryWildLevels/{index}"
        _require_exact_keys(row, {"species", "minimumOrdinaryWildLevel"}, location)
        species = _require_identifier(
            row["species"], f"{location}/species", SPECIES_IDENTIFIER
        )
        if species not in known_species:
            raise ValidationError(f"{location}/species: unknown species {species}")
        if species in minimum_levels:
            raise ValidationError(f"{location}/species: duplicate minimum level")
        minimum_levels[species] = _require_int(
            row["minimumOrdinaryWildLevel"],
            f"{location}/minimumOrdinaryWildLevel",
            1,
            MAX_ORDINARY_WILD_LEVEL,
        )

    active_evolutions = _extract_active_evolution_entries(species_info_path)
    active_species = set(active_evolutions)
    candidates = {}
    for predecessor, evolutions in active_evolutions.items():
        for evolution in evolutions:
            if evolution["method"] != "EVO_LEVEL":
                continue
            parameter = evolution["parameter"]
            if not parameter.isdecimal():
                raise ValidationError(
                    f"{species_info_path}/{predecessor}: EVO_LEVEL threshold must be numeric"
                )
            level = int(parameter)
            if level == 0:
                continue
            if not 1 <= level <= MAX_ORDINARY_WILD_LEVEL:
                raise ValidationError(
                    f"{species_info_path}/{predecessor}: EVO_LEVEL threshold must be from 1 through {MAX_ORDINARY_WILD_LEVEL}"
                )
            target = evolution["target"]
            if target not in known_species or target not in active_species:
                raise ValidationError(
                    f"{species_info_path}/{predecessor}: missing active predecessor target {target}"
                )
            candidates.setdefault(target, set()).add((predecessor, level))

    resolution_rows = document["predecessorResolutions"]
    if not isinstance(resolution_rows, list):
        raise ValidationError(f"{path}/predecessorResolutions: expected list")
    resolutions = {}
    for index, row in enumerate(resolution_rows):
        location = f"{path}/predecessorResolutions/{index}"
        _require_exact_keys(
            row, {"species", "predecessorSpecies", "predecessorLevel"}, location
        )
        species = _require_identifier(
            row["species"], f"{location}/species", SPECIES_IDENTIFIER
        )
        predecessor = _require_identifier(
            row["predecessorSpecies"],
            f"{location}/predecessorSpecies",
            SPECIES_IDENTIFIER,
        )
        level = _require_int(
            row["predecessorLevel"],
            f"{location}/predecessorLevel",
            1,
            MAX_ORDINARY_WILD_LEVEL,
        )
        if species in resolutions:
            raise ValidationError(
                f"{location}/species: duplicate predecessor resolution"
            )
        if species not in candidates or len(candidates[species]) < 2:
            raise ValidationError(
                f"{location}/species: predecessor resolution requires an ambiguous numeric predecessor"
            )
        if (predecessor, level) not in candidates[species]:
            raise ValidationError(
                f"{location}: predecessor resolution is not an active numeric evolution edge"
            )
        resolutions[species] = (predecessor, level)

    predecessors = {}
    for species, choices in candidates.items():
        if len(choices) == 1:
            predecessors[species] = next(iter(choices))
        elif species in resolutions:
            predecessors[species] = resolutions[species]
        else:
            rendered = ", ".join(
                f"{predecessor}@{level}" for predecessor, level in sorted(choices)
            )
            raise ValidationError(
                f"{species_info_path}/{species}: ambiguous numeric predecessors {rendered}; "
                "add a narrow predecessor resolution"
            )

    for species in predecessors:
        seen = set()
        current = species
        while current in predecessors:
            if current in seen:
                raise ValidationError(
                    f"{species_info_path}/{species}: numeric predecessor cycle at {current}"
                )
            seen.add(current)
            current = predecessors[current][0]

    reachable_species = set()
    for species in ordinary_species:
        current = species
        while True:
            reachable_species.add(current)
            predecessor = predecessors.get(current)
            if predecessor is None:
                break
            current = predecessor[0]
    for species in minimum_levels:
        if species not in reachable_species:
            raise ValidationError(
                f"{path}: minimum level species {species} is not reachable from an "
                "active ordinary encounter species"
            )

    metadata = []
    for species in sorted(reachable_species):
        predecessor, predecessor_level = predecessors.get(species, ("SPECIES_NONE", 0))
        has_alternate_non_level_route = any(
            evolution["method"] in NON_LEVEL_EVOLUTION_METHODS
            and evolution["target"] == species
            for evolution in active_evolutions.get(predecessor, [])
        )
        metadata.append(
            {
                "species": species,
                "minimum_level": minimum_levels.get(species, 1),
                "predecessor": predecessor,
                "predecessor_level": predecessor_level,
                "has_alternate_non_level_route": has_alternate_non_level_route,
            }
        )
    if len(metadata) > MAX_WILD_ENCOUNTER_SPECIES_METADATA:
        raise ValidationError(f"{path}: too many ordinary species metadata rows")
    return metadata


def _resolve_profile_time(profile, config, time_policy_labels=None):
    if time_policy_labels and profile["label"] in time_policy_labels:
        return time_policy_labels[profile["label"]]["time"]
    if profile["time"] == FALLBACK_TIME_ROLE:
        return config.runtime_canonical_time
    return profile["time"]


def _profile_emits_runtime(profile, config, time_policy_labels=None):
    if profile["alternate_of"] is not None:
        return False
    if time_policy_labels and profile["label"] in time_policy_labels:
        return True
    return config.time_encounters or profile["time"] == FALLBACK_TIME_ROLE


def _select_runtime_profiles(profiles, config, time_policy_labels=None):
    bindings = {}
    for profile in profiles:
        if not _profile_emits_runtime(profile, config, time_policy_labels):
            continue
        binding = (
            profile["group"],
            profile["header"],
            _resolve_profile_time(profile, config, time_policy_labels),
        )
        existing = bindings.get(binding)
        if existing is None:
            bindings[binding] = profile
            continue
        existing_is_fallback = existing["time"] == FALLBACK_TIME_ROLE
        current_is_fallback = profile["time"] == FALLBACK_TIME_ROLE
        if existing_is_fallback != current_is_fallback:
            if existing_is_fallback:
                bindings[binding] = profile
            continue
        raise ValidationError(f"registry: duplicate header/time identity {binding}")
    return tuple(bindings.values())


def _runtime_header_indices(profiles, config, time_policy_labels):
    indices = {}
    next_index = 0
    for profile in _select_runtime_profiles(profiles, config, time_policy_labels):
        if profile["group"] != "gWildMonHeaders":
            continue
        header = profile["header"]
        if header not in indices:
            indices[header] = next_index
            next_index += 1
    return indices


def _parse_registry(registry, config):
    _require_exact_keys(
        registry, {"schema_version", "profile_fields", "profiles"}, "registry"
    )
    if registry["schema_version"] != 1:
        raise ValidationError("registry/schema_version: expected 1")
    if registry["profile_fields"] != list(PROFILE_FIELDS):
        raise ValidationError("registry/profile_fields: unexpected profile schema")
    rows = registry["profiles"]
    if not isinstance(rows, list):
        raise ValidationError("registry/profiles: expected list")
    profiles = []
    labels = set()
    for index, row in enumerate(rows):
        location = f"registry/profiles/{index}"
        if not isinstance(row, list) or len(row) != len(PROFILE_FIELDS):
            raise ValidationError(f"{location}: expected {len(PROFILE_FIELDS)} fields")
        profile = dict(zip(PROFILE_FIELDS, row, strict=True))
        for field in ("group", "label", "header"):
            _require_identifier(profile[field], f"{location}/{field}")
        if profile["label"] in labels:
            raise ValidationError(f"{location}: duplicate profile {profile['label']}")
        labels.add(profile["label"])
        if profile["residency"] not in RESIDENCIES:
            raise ValidationError(f"{location}/residency: invalid residency")
        if (
            profile["time"] != FALLBACK_TIME_ROLE
            and profile["time"] not in config.times_of_day
        ):
            raise ValidationError(
                f"{location}/time: unresolved time {profile['time']!r}"
            )
        alternate = profile["alternate_of"]
        if alternate is not None:
            _require_identifier(alternate, f"{location}/alternate_of")
        variant_set = profile["variant_set"]
        variant_index = profile["variant_index"]
        if (variant_set is None) != (variant_index is None):
            raise ValidationError(
                f"{location}: variant_set and variant_index must coexist"
            )
        if variant_set is not None:
            _require_identifier(variant_set, f"{location}/variant_set")
            if (
                isinstance(variant_index, bool)
                or not isinstance(variant_index, int)
                or variant_index < 0
            ):
                raise ValidationError(
                    f"{location}/variant_index: expected non-negative integer"
                )
        profiles.append(profile)
    return profiles


def _validate_reviewed_inventory(profiles):
    if len(profiles) != REVIEWED_PROFILE_COUNT:
        raise ValidationError(
            f"registry: reviewed inventory must contain {REVIEWED_PROFILE_COUNT} profiles"
        )
    residency_counts = {
        residency: sum(profile["residency"] == residency for profile in profiles)
        for residency in RESIDENCIES
    }
    if residency_counts != REVIEWED_RESIDENCY_COUNTS:
        raise ValidationError(
            "registry: residency totals do not match the reviewed inventory"
        )
    ordered_profiles = [
        [profile[field] for field in PROFILE_FIELDS] for profile in profiles
    ]
    payload = json.dumps(
        ordered_profiles, ensure_ascii=True, separators=(",", ":")
    ).encode()
    if hashlib.sha256(payload).hexdigest() != REVIEWED_ORDERED_PROFILE_SHA256:
        raise ValidationError(
            "registry: ordered profile metadata does not match the reviewed inventory"
        )


def _validate_reviewed_authored_contract(encounters, profiles):
    contract = {
        "profiles": [
            [profile[field] for field in PROFILE_FIELDS] for profile in profiles
        ],
        "wild_encounter_groups": encounters["wild_encounter_groups"],
    }
    payload = json.dumps(
        contract, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()
    if hashlib.sha256(payload).hexdigest() != REVIEWED_AUTHORED_CONTRACT_SHA256:
        raise ValidationError(
            "wild encounters: authored payload does not match the reviewed contract"
        )


def _validate_map_header_semantics(profiles, encounter_by_label):
    profiles_by_map = {}
    for profile in profiles:
        map_id = encounter_by_label[profile["label"]].get("map")
        if map_id is not None:
            profiles_by_map.setdefault((profile["group"], map_id), []).append(profile)

    for (group, map_id), map_profiles in profiles_by_map.items():
        runtime_profiles = [
            profile for profile in map_profiles if profile["alternate_of"] is None
        ]
        ordinary_profiles = [
            profile for profile in runtime_profiles if profile["variant_set"] is None
        ]
        variant_profiles = [
            profile
            for profile in runtime_profiles
            if profile["variant_set"] is not None
        ]
        if ordinary_profiles and variant_profiles:
            raise ValidationError(
                f"registry/{group}/{map_id}: ordinary and variant headers cannot coexist"
            )
        if ordinary_profiles:
            primary_headers = {profile["header"] for profile in ordinary_profiles}
            if len(primary_headers) != 1:
                raise ValidationError(
                    f"registry/{group}/{map_id}: expected exactly one canonical header"
                )
            continue
        if not variant_profiles:
            raise ValidationError(
                f"registry/{group}/{map_id}: map has no runtime-canonical header"
            )

        variant_sets = {profile["variant_set"] for profile in variant_profiles}
        if len(variant_sets) != 1:
            raise ValidationError(
                f"registry/{group}/{map_id}: runtime variants span multiple sets"
            )
        variant_headers = {}
        ordered_indices = []
        for profile in variant_profiles:
            index = profile["variant_index"]
            if index not in variant_headers:
                ordered_indices.append(index)
            variant_headers.setdefault(index, set()).add(profile["header"])
        if ordered_indices != list(range(len(ordered_indices))):
            raise ValidationError(
                f"registry/{group}/{map_id}: canonical variant 0 must be emitted first"
            )
        if any(len(headers) != 1 for headers in variant_headers.values()):
            raise ValidationError(
                f"registry/{group}/{map_id}: variant identity has multiple headers"
            )


def _validate_fields(field_definitions, location):
    seen = set()
    for index, field in enumerate(field_definitions):
        field_location = f"{location}/fields/{index}"
        allowed = (
            {"type", "encounter_rates", "groups"}
            if "groups" in field
            else {"type", "encounter_rates"}
        )
        _require_exact_keys(field, allowed, field_location)
        field_type = _require_identifier(field["type"], f"{field_location}/type")
        if field_type in seen:
            raise ValidationError(
                f"{field_location}: duplicate encounter type {field_type}"
            )
        seen.add(field_type)
        rates = field["encounter_rates"]
        if not isinstance(rates, list) or not rates:
            raise ValidationError(
                f"{field_location}/encounter_rates: expected nonempty list"
            )
        if any(
            isinstance(rate, bool) or not isinstance(rate, int) or rate <= 0
            for rate in rates
        ):
            raise ValidationError(
                f"{field_location}/encounter_rates: expected positive integers"
            )
        groups = field.get("groups", {})
        if not isinstance(groups, dict):
            raise ValidationError(f"{field_location}/groups: expected object")
        claimed = set()
        for group_name, indices in groups.items():
            _require_identifier(group_name, f"{field_location}/groups")
            if not isinstance(indices, list) or not indices:
                raise ValidationError(
                    f"{field_location}/groups/{group_name}: expected nonempty list"
                )
            for slot in indices:
                if (
                    isinstance(slot, bool)
                    or not isinstance(slot, int)
                    or not 0 <= slot < len(rates)
                ):
                    raise ValidationError(
                        f"{field_location}/groups/{group_name}: invalid slot {slot!r}"
                    )
                if slot in claimed:
                    raise ValidationError(
                        f"{field_location}: encounter slot {slot} belongs to two groups"
                    )
                claimed.add(slot)


def validate_inputs(encounters, registry, config, maps, species):
    _require_exact_keys(encounters, {"wild_encounter_groups"}, "wild_encounters.json")
    groups = encounters["wild_encounter_groups"]
    if not isinstance(groups, list) or not groups:
        raise ValidationError(
            "wild_encounters.json/wild_encounter_groups: expected nonempty list"
        )
    profiles = _parse_registry(registry, config)
    _validate_reviewed_inventory(profiles)
    _validate_reviewed_authored_contract(encounters, profiles)
    profile_index = 0
    encounter_by_label = {}
    metadata_by_label = {profile["label"]: profile for profile in profiles}
    variant_sets = {}
    group_labels = set()

    for group_index, group in enumerate(groups):
        location = f"wild_encounters.json/wild_encounter_groups/{group_index}"
        allowed = {"label", "for_maps", "encounters"}
        if "fields" in group:
            allowed.add("fields")
        _require_exact_keys(group, allowed, location)
        group_label = _require_identifier(group["label"], f"{location}/label")
        if group_label in group_labels:
            raise ValidationError(
                f"{location}: duplicate encounter group {group_label}"
            )
        group_labels.add(group_label)
        if not isinstance(group["for_maps"], bool):
            raise ValidationError(f"{location}/for_maps: expected boolean")
        if "fields" in group:
            if not isinstance(group["fields"], list):
                raise ValidationError(f"{location}/fields: expected list")
            _validate_fields(group["fields"], location)
        rows = group["encounters"]
        if not isinstance(rows, list) or not rows:
            raise ValidationError(f"{location}/encounters: expected nonempty list")
        for encounter_index, encounter in enumerate(rows):
            row_location = f"{location}/encounters/{encounter_index}"
            if not isinstance(encounter, dict):
                raise ValidationError(f"{row_location}: expected object")
            allowed_row = {"base_label"} | set(config.mon_types)
            if group["for_maps"]:
                allowed_row.add("map")
            actual_row = set(encounter)
            if not {"base_label"}.issubset(actual_row) or not actual_row <= allowed_row:
                _require_exact_keys(
                    encounter, actual_row & allowed_row | {"base_label"}, row_location
                )
            if group["for_maps"] and "map" not in encounter:
                raise ValidationError(f"{row_location}: missing ['map']")
            encounter_types = set(config.mon_types) & set(encounter)
            if not encounter_types:
                raise ValidationError(
                    f"{row_location}: profile must define at least one encounter type"
                )
            label = _require_identifier(
                encounter["base_label"], f"{row_location}/base_label"
            )
            if label in encounter_by_label:
                raise ValidationError(
                    f"{row_location}: duplicate encounter profile {label}"
                )
            if profile_index >= len(profiles):
                raise ValidationError(
                    f"{row_location}: missing registry profile for {label}"
                )
            profile = profiles[profile_index]
            if profile["group"] != group_label or profile["label"] != label:
                raise ValidationError(
                    f"{row_location}: registry inventory mismatch; expected "
                    f"{group_label}/{label}, found {profile['group']}/{profile['label']}"
                )
            if group["for_maps"]:
                map_id = _require_identifier(
                    encounter["map"], f"{row_location}/map", MAP_IDENTIFIER
                )
                if map_id not in maps:
                    raise ValidationError(f"{row_location}: unresolved map {map_id}")
                expected_residency = _expected_residency(*maps[map_id])
                if profile["residency"] != expected_residency:
                    raise ValidationError(
                        f"{row_location}: residency {profile['residency']} does not match "
                        f"map authority {expected_residency}"
                    )
            else:
                expected_residency = NON_MAP_RESIDENCY.get(group_label)
                if expected_residency is None:
                    raise ValidationError(
                        f"{row_location}: non-map group {group_label} has no residency authority"
                    )
                if profile["residency"] != expected_residency:
                    raise ValidationError(
                        f"{row_location}: residency {profile['residency']} does not match "
                        f"non-map authority {expected_residency}"
                    )
            for mon_type in config.mon_types:
                if mon_type not in encounter:
                    continue
                mon_entry = encounter[mon_type]
                mon_location = f"{row_location}/{mon_type}"
                _require_exact_keys(mon_entry, {"encounter_rate", "mons"}, mon_location)
                rate = mon_entry["encounter_rate"]
                if (
                    isinstance(rate, bool)
                    or not isinstance(rate, int)
                    or not 0 <= rate <= 255
                ):
                    raise ValidationError(
                        f"{mon_location}/encounter_rate: expected byte"
                    )
                mons = mon_entry["mons"]
                field_slot_count = next(
                    len(field["encounter_rates"])
                    for candidate_group in groups
                    for field in candidate_group.get("fields", [])
                    if field["type"] == mon_type
                )
                if not isinstance(mons, list) or len(mons) != field_slot_count:
                    raise ValidationError(
                        f"{mon_location}/mons: expected exactly {field_slot_count} slots"
                    )
                for mon_index, mon in enumerate(mons):
                    member_location = f"{mon_location}/mons/{mon_index}"
                    if not isinstance(mon, dict):
                        raise ValidationError(f"{member_location}: expected object")
                    allowed_mon = {"species"}
                    if "min_level" in mon:
                        allowed_mon.add("min_level")
                    if "max_level" in mon:
                        allowed_mon.add("max_level")
                    _require_exact_keys(mon, allowed_mon, member_location)
                    species_id = _require_identifier(
                        mon["species"], f"{member_location}/species", SPECIES_IDENTIFIER
                    )
                    if species_id not in species:
                        raise ValidationError(
                            f"{member_location}: unresolved species {species_id}"
                        )
                    minimum = mon.get("min_level", 2)
                    maximum = mon.get("max_level", 100)
                    if (
                        isinstance(minimum, bool)
                        or isinstance(maximum, bool)
                        or not isinstance(minimum, int)
                        or not isinstance(maximum, int)
                        or not 1 <= minimum <= maximum <= 100
                    ):
                        raise ValidationError(
                            f"{member_location}: invalid level interval"
                        )
            encounter_by_label[label] = encounter
            if profile["variant_set"] is not None:
                variant_sets.setdefault(profile["variant_set"], []).append(profile)
            profile_index += 1

    if profile_index != len(profiles):
        extra = profiles[profile_index]
        raise ValidationError(
            f"registry: unexpected profile {extra['group']}/{extra['label']} after encounter inventory"
        )

    for profile in profiles:
        alternate = profile["alternate_of"]
        if alternate is None:
            continue
        if alternate == profile["label"] or alternate not in metadata_by_label:
            raise ValidationError(
                f"registry/{profile['label']}: unresolved alternate identity {alternate!r}"
            )
        primary = metadata_by_label[alternate]
        if primary["alternate_of"] is not None:
            raise ValidationError(
                f"registry/{profile['label']}: alternate chains are forbidden"
            )
        current_encounter = encounter_by_label[profile["label"]]
        primary_encounter = encounter_by_label[alternate]
        if (
            profile["group"] != primary["group"]
            or profile["time"] != primary["time"]
            or current_encounter.get("map") != primary_encounter.get("map")
        ):
            raise ValidationError(
                f"registry/{profile['label']}: alternate identity scope mismatch"
            )

    profile_positions = {
        profile["label"]: index for index, profile in enumerate(profiles)
    }
    for profile in profiles:
        if not profile["label"].endswith("_LeafGreen"):
            continue
        primary_label = profile["label"].removesuffix("_LeafGreen") + "_FireRed"
        if profile["alternate_of"] != primary_label:
            raise ValidationError(
                f"registry/{profile['label']}: LeafGreen profile must be an exact "
                f"alternate of {primary_label}"
            )
        if primary_label not in metadata_by_label:
            raise ValidationError(
                f"registry/{profile['label']}: unresolved FireRed primary {primary_label}"
            )
        if profile_positions[primary_label] >= profile_positions[profile["label"]]:
            raise ValidationError(
                f"registry/{profile['label']}: FireRed primary must precede LeafGreen alternate"
            )

    _validate_map_header_semantics(profiles, encounter_by_label)

    if set(variant_sets) != set(ALTERING_CAVE_VARIANTS):
        raise ValidationError(
            "registry: Altering Cave variant sets must be exactly "
            f"{sorted(ALTERING_CAVE_VARIANTS)}"
        )
    for name, authority in ALTERING_CAVE_VARIANTS.items():
        variants = variant_sets[name]
        labels = tuple(profile["label"] for profile in variants)
        if labels != authority["labels"]:
            raise ValidationError(
                f"registry: variant set {name} must contain exact ordered labels "
                f"{list(authority['labels'])}"
            )
        for index, (profile, alternate) in enumerate(
            zip(variants, authority["alternates"], strict=True)
        ):
            encounter = encounter_by_label[profile["label"]]
            expected_metadata = {
                "group": "gWildMonHeaders",
                "header": profile["label"],
                "residency": authority["residency"],
                "time": FALLBACK_TIME_ROLE,
                "alternate_of": alternate,
                "variant_set": name,
                "variant_index": index,
            }
            actual_metadata = {field: profile[field] for field in expected_metadata}
            if actual_metadata != expected_metadata:
                raise ValidationError(
                    f"registry/{profile['label']}: invalid Altering Cave metadata"
                )
            if encounter.get("map") != authority["map"]:
                raise ValidationError(
                    f"registry/{profile['label']}: Altering Cave map must be "
                    f"{authority['map']}"
                )

    return profiles


def _parse_policy_clock(value, location):
    if (
        not isinstance(value, str)
        or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value) is None
    ):
        raise ValidationError(f"{location}: expected 24-hour HH:MM")
    hours, minutes = (int(part) for part in value.split(":"))
    return hours * 60 + minutes


def _load_time_policies(
    path,
    profiles,
    encounters,
    config,
    maps,
    expected_method_fallbacks=None,
):
    document = _load_json(path)
    _require_exact_keys(
        document,
        {
            "schema_version",
            "encounterProfiles",
            "encounterTimePolicy",
            "methodFallbacks",
        },
        path,
    )
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValidationError(f"{path}/schema_version: expected 1")
    policy_rows = document["encounterTimePolicy"]
    profile_rows = document["encounterProfiles"]
    method_fallback_rows = document["methodFallbacks"]
    if (
        not isinstance(policy_rows, list)
        or not isinstance(profile_rows, list)
        or not isinstance(method_fallback_rows, list)
    ):
        raise ValidationError(f"{path}: time-policy collections must be lists")
    if not policy_rows:
        raise ValidationError(f"{path}: encounterTimePolicy must not be empty")

    registry_by_label = {profile["label"]: profile for profile in profiles}
    encounter_by_label = {
        encounter["base_label"]: encounter
        for group in encounters["wild_encounter_groups"]
        for encounter in group["encounters"]
    }
    map_id_by_name = {}
    for map_id, (map_data, _) in maps.items():
        map_name = map_data["name"]
        if map_name in map_id_by_name:
            raise ValidationError(f"map authority: duplicate map name {map_name}")
        map_id_by_name[map_name] = map_id
    authored_profile_by_label = {}
    for index, row in enumerate(profile_rows):
        location = f"{path}/encounterProfiles/{index}"
        _require_exact_keys(
            row, {"map", "label", "habitat", "authority", "time"}, location
        )
        label = _require_identifier(row["label"], f"{location}/label")
        _require_identifier(row["map"], f"{location}/map")
        _require_identifier(row["habitat"], f"{location}/habitat")
        if row["authority"] != "content":
            raise ValidationError(f"{location}/authority: expected content")
        if row["time"] not in config.times_of_day:
            raise ValidationError(f"{location}/time: unresolved time")
        if label in authored_profile_by_label:
            raise ValidationError(f"{location}: duplicate authored profile {label}")
        authored_profile_by_label[label] = row

    policies = []
    labels = {}
    headers = {}
    policy_by_map = {}
    for index, row in enumerate(policy_rows):
        location = f"{path}/encounterTimePolicy/{index}"
        _require_exact_keys(
            row,
            {
                "map",
                "dayStart",
                "nightStart",
                "dayLabel",
                "nightLabel",
                "fallbackLabel",
            },
            location,
        )
        map_name = _require_identifier(row["map"], f"{location}/map")
        expected_map = map_id_by_name.get(map_name)
        if expected_map is None:
            raise ValidationError(f"{location}/map: unresolved canonical map")
        if map_name in policy_by_map:
            raise ValidationError(f"{location}: duplicate map time policy")
        policy_by_map[map_name] = row
        day_label = _require_identifier(row["dayLabel"], f"{location}/dayLabel")
        night_label = _require_identifier(row["nightLabel"], f"{location}/nightLabel")
        if row["fallbackLabel"] != day_label:
            raise ValidationError(f"{location}: fallbackLabel must equal dayLabel")
        if day_label == night_label or day_label in labels or night_label in labels:
            raise ValidationError(f"{location}: duplicate policy profile identity")
        if day_label not in registry_by_label or night_label not in registry_by_label:
            raise ValidationError(f"{location}: unresolved policy profile")
        day_profile = registry_by_label[day_label]
        night_profile = registry_by_label[night_label]
        if (
            day_profile["group"] != "gWildMonHeaders"
            or night_profile["group"] != "gWildMonHeaders"
            or day_profile["header"] != night_profile["header"]
            or day_profile["alternate_of"] is not None
            or night_profile["alternate_of"] is not None
        ):
            raise ValidationError(
                f"{location}: policy profiles must share one runtime header"
            )
        if (
            encounter_by_label[day_label].get("map") != expected_map
            or encounter_by_label[night_label].get("map") != expected_map
        ):
            raise ValidationError(
                f"{location}: policy map does not match encounter profiles"
            )
        authored_day = authored_profile_by_label.get(day_label)
        authored_night = authored_profile_by_label.get(night_label)
        if authored_day is None or authored_night is None:
            raise ValidationError(f"{location}: missing typed encounter profile")
        if (
            authored_day["map"] != map_name
            or authored_night["map"] != map_name
            or authored_day["habitat"] != authored_night["habitat"]
            or authored_day["habitat"] not in config.mon_types
            or authored_day["habitat"] not in encounter_by_label[day_label]
            or authored_night["habitat"] not in encounter_by_label[night_label]
            or authored_day["authority"] != "content"
            or authored_night["authority"] != "content"
            or authored_day["time"] != "TIME_DAY"
            or authored_night["time"] != "TIME_NIGHT"
            or day_profile["time"] != FALLBACK_TIME_ROLE
            or night_profile["time"] != authored_night["time"]
        ):
            raise ValidationError(f"{location}: invalid typed encounter profile")
        day_start = _parse_policy_clock(row["dayStart"], f"{location}/dayStart")
        night_start = _parse_policy_clock(row["nightStart"], f"{location}/nightStart")
        if day_start != 6 * 60 or night_start != 18 * 60:
            raise ValidationError(
                f"{location}: dayStart and nightStart must be 06:00 and 18:00"
            )
        policy = {
            "header": day_profile["header"],
            "day_start": day_start,
            "night_start": night_start,
            "day_time": authored_day["time"],
            "night_time": authored_night["time"],
        }
        if policy["header"] in headers:
            raise ValidationError(f"{location}: duplicate header time policy")
        headers[policy["header"]] = policy
        labels[day_label] = {"time": policy["day_time"], "policy": policy}
        labels[night_label] = {"time": policy["night_time"], "policy": policy}
        policies.append(policy)

    fallback_identities = set()
    for index, row in enumerate(method_fallback_rows):
        location = f"{path}/methodFallbacks/{index}"
        _require_exact_keys(
            row,
            {"map", "method", "missingCondition", "sourceCondition"},
            location,
        )
        map_name = _require_identifier(row["map"], f"{location}/map")
        method = _require_identifier(row["method"], f"{location}/method")
        if method not in config.mon_types:
            raise ValidationError(f"{location}/method: unresolved encounter method")
        missing_condition = row["missingCondition"]
        source_condition = row["sourceCondition"]
        if (
            missing_condition not in {"TIME_DAY", "TIME_NIGHT"}
            or source_condition not in {"TIME_DAY", "TIME_NIGHT"}
            or missing_condition == source_condition
        ):
            raise ValidationError(f"{location}: invalid condition fallback")
        identity = (map_name, method, missing_condition, source_condition)
        if identity in fallback_identities:
            raise ValidationError(f"{location}: duplicate method fallback")
        fallback_identities.add(identity)
        policy = policy_by_map.get(map_name)
        if policy is None:
            raise ValidationError(f"{location}/map: missing encounter time policy")
        label_by_condition = {
            "TIME_DAY": policy["dayLabel"],
            "TIME_NIGHT": policy["nightLabel"],
        }
        missing_encounter = encounter_by_label[label_by_condition[missing_condition]]
        source_encounter = encounter_by_label[label_by_condition[source_condition]]
        if (
            method not in missing_encounter
            or method not in source_encounter
            or missing_encounter[method] != source_encounter[method]
        ):
            raise ValidationError(
                f"{location}: fallback method must exactly copy its source condition"
            )
    if (
        expected_method_fallbacks is not None
        and fallback_identities != expected_method_fallbacks
    ):
        raise ValidationError(
            f"{path}/methodFallbacks: expected exact reviewed method fallback set"
        )
    if set(authored_profile_by_label) != set(labels):
        raise ValidationError(
            f"{path}: encounterProfiles must exactly match profiles consumed by "
            "encounterTimePolicy"
        )
    return labels, headers


def _load_profile_offsets(
    rows, scaling_path, profiles, encounters, config, time_policy_labels
):
    if not isinstance(rows, list):
        raise ValidationError(f"{scaling_path}/profileOffsets: expected list")
    profile_by_label = {profile["label"]: profile for profile in profiles}
    encounter_by_label = {
        encounter["base_label"]: encounter
        for group in encounters["wild_encounter_groups"]
        for encounter in group["encounters"]
    }
    runtime_profiles = {
        profile["label"]: profile
        for profile in _select_runtime_profiles(profiles, config, time_policy_labels)
        if profile["group"] == "gWildMonHeaders"
    }
    header_indices = _runtime_header_indices(profiles, config, time_policy_labels)
    offsets = []
    identities = set()
    for index, row in enumerate(rows):
        location = f"{scaling_path}/profileOffsets/{index}"
        _require_exact_keys(
            row, {"label", "method", "fishingRod", "levelOffset"}, location
        )
        label = _require_identifier(row["label"], f"{location}/label")
        profile = profile_by_label.get(label)
        if profile is None or label not in runtime_profiles:
            raise ValidationError(f"{location}/label: unknown active standard profile")
        method = row["method"]
        if method not in config.mon_types or method not in METHOD_AREAS:
            raise ValidationError(f"{location}/method: unknown encounter method")
        if method not in encounter_by_label[label]:
            raise ValidationError(
                f"{location}/method: profile does not support {method!r}"
            )
        fishing_rod = row["fishingRod"]
        if fishing_rod not in FISHING_RODS:
            raise ValidationError(f"{location}/fishingRod: unknown rod condition")
        if method == "fishing_mons":
            if fishing_rod == "NONE":
                raise ValidationError(
                    f"{location}/fishingRod: fishing method requires a rod"
                )
        elif fishing_rod != "NONE":
            raise ValidationError(
                f"{location}/fishingRod: non-fishing method requires NONE"
            )
        level_offset = _require_int(
            row["levelOffset"],
            f"{location}/levelOffset",
            -MAX_PROFILE_LEVEL_OFFSET,
            MAX_PROFILE_LEVEL_OFFSET,
        )
        identity = (
            header_indices[profile["header"]],
            METHOD_AREAS[method],
            _resolve_profile_time(profile, config, time_policy_labels),
            FISHING_RODS[fishing_rod],
        )
        if identity in identities:
            raise ValidationError(f"{location}: duplicate resolved profile offset")
        identities.add(identity)
        offsets.append(
            {
                "header_id": identity[0],
                "area": identity[1],
                "time_of_day": identity[2],
                "fishing_rod": identity[3],
                "level_offset": level_offset,
            }
        )
    offsets.sort(
        key=lambda offset: (
            offset["header_id"],
            offset["area"],
            offset["time_of_day"],
            offset["fishing_rod"],
        )
    )
    return offsets


class WildEncounterAssembler:
    def __init__(
        self,
        output_file,
        json_data,
        config,
        profiles,
        time_policy_labels,
        time_policy_headers,
    ):
        self.output_file = output_file
        self.json_data = json_data
        self.config = config
        self.runtime_profile_labels = {
            profile["label"]
            for profile in _select_runtime_profiles(
                profiles, config, time_policy_labels
            )
        }
        self.time_policy_labels = time_policy_labels
        self.time_policy_headers = time_policy_headers
        self.profiles = iter(profiles)

    def write_line(self, line="", indents=0):
        self.output_file.write(4 * indents * " " + line + "\n")

    def write_header(self):
        self.write_line("//")
        self.write_line(
            "// DO NOT MODIFY THIS FILE! It is auto-generated by tools/wild_encounters/wild_encounters_to_header.py"
        )
        self.write_line("//")
        self.output_file.write("\n\n")

    def write_macro(self, macro, value):
        self.output_file.write(f"#define {macro} {value}\n")

    def write_macros(self):
        for group in self.json_data["wild_encounter_groups"]:
            for field in group.get("fields", []):
                field_type = field["type"]
                macro_base = "ENCOUNTER_CHANCE_" + field_type.upper()
                previous_group = None
                previous_macro = None
                encounter_rates = field["encounter_rates"]
                group_name_mapping = len(encounter_rates) * [""]
                for group_name, indices in field.get("groups", {}).items():
                    for index in indices:
                        group_name_mapping[index] = "_" + group_name.upper()
                for index, rate in enumerate(encounter_rates):
                    macro_name = f"{macro_base}{group_name_mapping[index]}_SLOT_{index}"
                    macro_value = str(rate)
                    if previous_group == group_name_mapping[index]:
                        macro_value = f"({previous_macro} + {macro_value})"
                    elif index > 0:
                        self.write_macro(
                            f"{macro_base}{group_name_mapping[index - 1]}_TOTAL",
                            f"({previous_macro})",
                        )
                    self.write_macro(macro_name, macro_value)
                    previous_group = group_name_mapping[index]
                    previous_macro = macro_name
                    if index == len(encounter_rates) - 1:
                        self.write_macro(
                            f"{macro_base}{group_name_mapping[index]}_TOTAL",
                            f"({previous_macro})",
                        )
                self.write_line()

    def write_mon_infos(self, name, mons, encounter_rate):
        self.write_line(f"const struct WildPokemon {name}[] =")
        self.write_line("{")
        for mon in mons:
            self.write_line(
                f"{{ {mon.get('min_level', 2)}, {mon.get('max_level', 100)}, {mon['species']} }},",
                1,
            )
        self.write_line("};")
        self.write_line()
        self.write_line(
            f"const struct WildPokemonInfo {name}Info = {{ {encounter_rate}, {name} }};"
        )
        self.write_line()

    def write_terminator(self):
        self.write_line("{", 1)
        self.write_line(".mapGroup = MAP_GROUP(MAP_UNDEFINED),", 2)
        self.write_line(".mapNum = MAP_NUM(MAP_UNDEFINED),", 2)
        self.write_line(".encounterTypes =", 2)
        self.write_line("{", 2)
        for time in self.config.times_of_day:
            if (
                not self.config.time_encounters
                and time != self.config.runtime_canonical_time
            ):
                continue
            self.write_line(f"[{time}] =", 3)
            self.write_line("{", 3)
            for mon_type in self.config.mon_types:
                member_name = mon_type.title().replace("_", "")
                member_name = member_name[0].lower() + member_name[1:] + "Info"
                self.write_line(f".{member_name} = NULL,", 4)
            self.write_line("},", 3)
        self.write_line("},", 2)
        self.write_line("},", 1)

    def write_pokemon_headers(self, headers):
        storage = "static " if headers["label"] == "gWildMonHeaders" else ""
        self.write_line(
            f"{storage}const struct WildPokemonHeader {headers['label']}[] ="
        )
        self.write_line("{")
        for shared_label, map_data in headers["data"].items():
            self.write_line()
            self.write_line("{", 1)
            self.write_line(f".mapGroup = {map_data['mapGroup']},", 2)
            self.write_line(f".mapNum = {map_data['mapNum']},", 2)
            self.write_line(".encounterTypes =", 2)
            self.write_line("{", 2)
            for time in self.config.times_of_day:
                if (
                    not self.config.time_encounters
                    and time != self.config.runtime_canonical_time
                    and time not in map_data
                ):
                    continue
                self.write_line(f"[{time}] =", 4)
                self.write_line("{", 4)
                for mon_type in self.config.mon_types:
                    member_name = mon_type.title().replace("_", "")
                    member_name = member_name[0].lower() + member_name[1:] + "Info"
                    value = map_data.get(time, {}).get(mon_type, "NULL")
                    if value != "NULL":
                        value = "&" + value
                    self.write_line(f".{member_name} = {value},", 5)
                self.write_line("},", 3)
            self.write_line("},", 2)
            self.write_line("},", 1)
        if headers["label"] != "gWildMonHeaders":
            self.write_terminator()
        self.write_line("};")
        if headers["label"] == "gWildMonHeaders":
            self.write_line()
            self.write_line(
                "static const struct WildEncounterTimePolicy gWildMonHeaderTimePolicies[] ="
            )
            self.write_line("{")
            for shared_label in headers["data"]:
                policy = self.time_policy_headers.get(shared_label)
                self.write_line("{", 1)
                if policy is None:
                    self.write_line(
                        ".dayStartMinutes = WILD_ENCOUNTER_TIME_POLICY_NONE,", 2
                    )
                else:
                    self.write_line(f".dayStartMinutes = {policy['day_start']},", 2)
                    self.write_line(f".nightStartMinutes = {policy['night_start']},", 2)
                    self.write_line(f".dayTime = {policy['day_time']},", 2)
                    self.write_line(f".nightTime = {policy['night_time']},", 2)
                self.write_line("},", 1)
            self.write_line("};")
            self.write_line()
            self.write_line(
                "STATIC_ASSERT(ARRAY_COUNT(gWildMonHeaders) == "
                "ARRAY_COUNT(gWildMonHeaderTimePolicies), "
                "WildEncounterRegistryParallelArraysMustMatch);"
            )
            self.write_line()
            self.write_line(
                "static const struct WildEncounterRegistry sWildEncounterRegistry ="
            )
            self.write_line("{")
            self.write_line(".headers = gWildMonHeaders,", 1)
            self.write_line(".timePolicies = gWildMonHeaderTimePolicies,", 1)
            self.write_line(".count = ARRAY_COUNT(gWildMonHeaders),", 1)
            self.write_line("};")

    def write_encounters(self):
        for group in self.json_data["wild_encounter_groups"]:
            headers = {"label": group["label"], "data": {}}
            map_num_counter = 1
            for encounter in group["encounters"]:
                profile = next(self.profiles)
                if profile["label"] not in self.runtime_profile_labels:
                    continue
                map_group = "0"
                map_num = str(map_num_counter)
                if group["for_maps"]:
                    map_name = encounter["map"]
                    map_group = f"MAP_GROUP({map_name})"
                    map_num = f"MAP_NUM({map_name})"
                map_num_counter += 1
                shared_label = profile["header"]
                time = _resolve_profile_time(
                    profile, self.config, self.time_policy_labels
                )
                if shared_label not in headers["data"]:
                    headers["data"][shared_label] = {
                        "mapGroup": map_group,
                        "mapNum": map_num,
                    }
                map_data = headers["data"][shared_label]
                if map_data["mapGroup"] != map_group or map_data["mapNum"] != map_num:
                    raise ValidationError(
                        f"registry/{profile['label']}: header identity spans multiple maps"
                    )
                time_data = map_data.setdefault(time, {})
                for mon_type in self.config.mon_types:
                    if mon_type not in encounter:
                        continue
                    entry = encounter[mon_type]
                    array_name = (
                        encounter["base_label"]
                        + "_"
                        + mon_type.title().replace("_", "")
                    )
                    self.write_mon_infos(
                        array_name, entry["mons"], entry["encounter_rate"]
                    )
                    if mon_type in time_data:
                        raise ValidationError(
                            f"registry/{profile['label']}: duplicate {time}/{mon_type} binding"
                        )
                    time_data[mon_type] = array_name + "Info"
            self.write_pokemon_headers(headers)


def _render_scaling(output, scaling, profile_offsets, species_metadata):
    output.write("\n")
    output.write("const struct TrainerRatingSource gTrainerRatingSources[] =\n")
    output.write("{\n")
    for source in scaling["sources"]:
        kind = f"TRAINER_RATING_SOURCE_{source['kind'].upper()}"
        output.write(f"    {{ {source['id']}, {source['value']}, {kind} }},\n")
    output.write("};\n")
    output.write(
        "const u16 gTrainerRatingSourceCount = ARRAY_COUNT(gTrainerRatingSources);\n\n"
    )
    output.write(
        "const struct TrainerRatingBadgeSegment gTrainerRatingBadgeSegments[] =\n"
    )
    output.write("{\n")
    for segment in scaling["badge_segments"]:
        output.write(
            "    { "
            f"{segment['first_badge_ordinal']}, {segment['badge_count']}, "
            f"{segment['value']}"
            " },\n"
        )
    output.write("};\n")
    output.write(
        "const u16 gTrainerRatingBadgeSegmentCount = "
        "ARRAY_COUNT(gTrainerRatingBadgeSegments);\n\n"
    )
    output.write(
        "const struct WildEncounterScalingBalance gWildEncounterScalingBalance =\n"
    )
    output.write("{\n")
    output.write(f"    .projectionCap = {scaling['projection_cap']},\n")
    output.write(f"    .maximumRating = {scaling['maximum_rating']},\n")
    output.write("};\n\n")
    output.write(
        "const struct WildEncounterScalingAnchor gWildEncounterScalingAnchors[] =\n"
    )
    output.write("{\n")
    for anchor in scaling["anchors"]:
        output.write(f"    {{ {anchor['rating']}, {anchor['level']} }},\n")
    output.write("};\n")
    output.write(
        "const u16 gWildEncounterScalingAnchorCount = "
        "ARRAY_COUNT(gWildEncounterScalingAnchors);\n\n"
    )
    output.write(
        "const struct WildEncounterScalingPoint gWildEncounterScalingPoints[] =\n"
    )
    output.write("{\n")
    for point in scaling["points"]:
        output.write(
            "    { "
            f"{point['anchor_level']}, {point['retention_numerator']}, "
            f"{point['retention_denominator']}"
            " },\n"
        )
    output.write("};\n")
    output.write(
        "const u16 gWildEncounterScalingPointCount = "
        "ARRAY_COUNT(gWildEncounterScalingPoints);\n\n"
    )
    output.write(
        "const struct WildEncounterProfileOffset gWildEncounterProfileOffsets[] =\n"
    )
    output.write("{\n")
    if profile_offsets:
        for offset in profile_offsets:
            output.write("    {\n")
            output.write(f"        .headerId = {offset['header_id']},\n")
            output.write(f"        .area = {offset['area']},\n")
            output.write(f"        .timeOfDay = {offset['time_of_day']},\n")
            output.write(f"        .fishingRod = {offset['fishing_rod']},\n")
            output.write(f"        .levelOffset = {offset['level_offset']},\n")
            output.write("    },\n")
    else:
        output.write("    { 0 }, // Typed sentinel; count remains zero.\n")
    output.write("};\n")
    if profile_offsets:
        output.write(
            "const u16 gWildEncounterProfileOffsetCount = "
            "ARRAY_COUNT(gWildEncounterProfileOffsets);\n"
        )
    else:
        output.write("const u16 gWildEncounterProfileOffsetCount = 0;\n")
    output.write("\n")
    output.write(
        "const struct WildEncounterSpeciesMetadata gWildEncounterSpeciesMetadata[] =\n"
    )
    output.write("{\n")
    for metadata in species_metadata:
        alternate = "TRUE" if metadata["has_alternate_non_level_route"] else "FALSE"
        output.write(
            "    { "
            f"{metadata['species']}, {metadata['minimum_level']}, "
            f"{metadata['predecessor']}, {metadata['predecessor_level']}, {alternate}"
            " },\n"
        )
    output.write("};\n")
    output.write(
        "const u16 gWildEncounterSpeciesMetadataCount = "
        "ARRAY_COUNT(gWildEncounterSpeciesMetadata);\n"
    )


def render_header(
    encounters,
    config,
    profiles,
    time_policy_labels,
    time_policy_headers,
    scaling,
    profile_offsets,
    species_metadata,
):
    output = io.StringIO()
    assembler = WildEncounterAssembler(
        output, encounters, config, profiles, time_policy_labels, time_policy_headers
    )
    assembler.write_header()
    assembler.write_macros()
    assembler.write_encounters()
    _render_scaling(output, scaling, profile_offsets, species_metadata)
    rendered = output.getvalue()
    if PRODUCT_GUARD.search(rendered):
        raise ValidationError("generated output contains a product residency guard")
    return rendered


def _divide_round_signed(numerator, denominator):
    if numerator >= 0:
        return (numerator + denominator // 2) // denominator
    return -((-numerator + denominator // 2) // denominator)


def _profile_offset_map(profile_offsets):
    return {
        (
            offset["header_id"],
            offset["area"],
            offset["time_of_day"],
            offset["fishing_rod"],
        ): offset["level_offset"]
        for offset in profile_offsets
    }


def _project_levels(scaling, vanilla_level, rating_cap, level_offset):
    base_level = scaling["points"][0]["anchor_level"]
    high_water_level = 0
    levels = []
    for rating in range(rating_cap + 1):
        point = scaling["points"][rating]
        raw_level = point["anchor_level"] + _divide_round_signed(
            (vanilla_level - base_level) * point["retention_numerator"],
            point["retention_denominator"],
        )
        high_water_level = max(high_water_level, raw_level)
        levels.append(
            min(max(high_water_level + level_offset, 1), MAX_ORDINARY_WILD_LEVEL)
        )
    return levels


def _effective_species(species, vanilla_level, level, metadata_by_species):
    effective_species = species
    stage_changes = []
    while True:
        metadata = metadata_by_species[effective_species]
        predecessor = metadata["predecessor"]
        if (
            predecessor == "SPECIES_NONE"
            or metadata["has_alternate_non_level_route"]
            or vanilla_level < metadata["predecessor_level"]
            or level >= metadata["predecessor_level"]
        ):
            return effective_species, stage_changes
        stage_changes.append((effective_species, predecessor))
        effective_species = predecessor


def _summarize_slot_outcomes(slot, scaling, level_offset, metadata_by_species):
    rating_cap = scaling["projection_cap"]
    summaries = [
        {
            "locked": False,
            "outcomes": {},
            "stage_changes": set(),
            "level_sum": 0,
            "level_count": 0,
        }
        for _ in range(rating_cap + 1)
    ]
    previous_levels = {}
    for vanilla_level in range(slot["min_level"], slot["max_level"] + 1):
        projected_levels = _project_levels(
            scaling, vanilla_level, rating_cap, level_offset
        )
        previous_level = None
        for rating, level in enumerate(projected_levels):
            effective_species, stage_changes = _effective_species(
                slot["species"], vanilla_level, level, metadata_by_species
            )
            summary = summaries[rating]
            outcome = summary["outcomes"].setdefault(
                effective_species, {"min_level": level, "max_level": level}
            )
            outcome["min_level"] = min(outcome["min_level"], level)
            outcome["max_level"] = max(outcome["max_level"], level)
            summary["stage_changes"].update(stage_changes)
            summary["level_sum"] += level
            summary["level_count"] += 1
            if level < metadata_by_species[effective_species]["minimum_level"]:
                summary["locked"] = True
            if previous_level is not None and level < previous_level:
                previous_levels.setdefault(vanilla_level, []).append(
                    (rating - 1, previous_level, rating, level)
                )
            previous_level = level
    return summaries, previous_levels


def _field_weights(group, method, fishing_rod, entry_count):
    fields = {field["type"]: field for field in group.get("fields", [])}
    field = fields.get(method)
    if field is None:
        raise ValidationError(
            f"balance audit: {group['label']} has no {method} weights"
        )
    if method == "fishing_mons":
        slot_indices = field["groups"][fishing_rod.lower()]
    else:
        slot_indices = range(len(field["encounter_rates"]))
    weights = [field["encounter_rates"][index] for index in slot_indices]
    if len(weights) != entry_count:
        raise ValidationError(
            f"balance audit: {group['label']}/{method} weight count does not match slots"
        )
    return weights


def _audit_profile_slots(
    label,
    method,
    fishing_rod,
    encounter,
    weights,
    scaling,
    level_offset,
    metadata_by_species,
):
    rating_cap = scaling["projection_cap"]
    required_ratings = [
        rating for rating in REQUIRED_AUDIT_RATINGS if rating <= rating_cap
    ]
    slot_rows = []
    failures = []
    for index, (slot, weight) in enumerate(
        zip(encounter[method]["mons"], weights, strict=True)
    ):
        normalized_slot = {
            "species": slot["species"],
            "min_level": slot.get("min_level", 2),
            "max_level": slot.get("max_level", 100),
        }
        summaries, decreasing_levels = _summarize_slot_outcomes(
            normalized_slot, scaling, level_offset, metadata_by_species
        )
        for vanilla_level, transitions in decreasing_levels.items():
            for previous_rating, previous_level, rating, level in transitions:
                failures.append(
                    f"{label}/{method}/{fishing_rod}/slot {index}/"
                    f"vanilla {vanilla_level}: level decreases from {previous_level} "
                    f"at rating {previous_rating} to {level} at rating {rating}"
                )
        unlock_rating = None
        unlocked = False
        for rating, summary in enumerate(summaries):
            eligible = not summary["locked"]
            if eligible and unlock_rating is None:
                unlock_rating = rating
            if unlocked and not eligible:
                failures.append(
                    f"{label}/{method}/{fishing_rod}/slot {index}: relocks at rating {rating}"
                )
            unlocked |= eligible

        slot_rows.append(
            {
                "slot": index,
                "species": normalized_slot["species"],
                "weight": weight,
                "vanilla": {
                    "minimumLevel": normalized_slot["min_level"],
                    "maximumLevel": normalized_slot["max_level"],
                },
                "startsLocked": summaries[0]["locked"],
                "unlockRating": unlock_rating,
                "summaries": summaries,
            }
        )

    original_minimum = min(row["vanilla"]["minimumLevel"] for row in slot_rows)
    original_maximum = max(row["vanilla"]["maximumLevel"] for row in slot_rows)
    original_average_numerator = sum(
        row["weight"]
        * sum(
            range(
                row["vanilla"]["minimumLevel"],
                row["vanilla"]["maximumLevel"] + 1,
            )
        )
        for row in slot_rows
    )
    original_average_denominator = sum(
        row["weight"]
        * (row["vanilla"]["maximumLevel"] - row["vanilla"]["minimumLevel"] + 1)
        for row in slot_rows
    )
    matrix = []
    for rating in required_ratings:
        eligible_rows = [
            row for row in slot_rows if not row["summaries"][rating]["locked"]
        ]
        locked_rows = [row for row in slot_rows if row["summaries"][rating]["locked"]]
        eligible_weight = sum(row["weight"] for row in eligible_rows)
        locked_weight = sum(row["weight"] for row in locked_rows)
        if not eligible_rows:
            failures.append(
                f"{label}/{method}/{fishing_rod}: all slots are locked at rating {rating}"
            )
            effective_minimum = None
            effective_maximum = None
            effective_average_numerator = 0
            effective_average_denominator = 0
        else:
            effective_minimum = min(
                outcome["min_level"]
                for row in eligible_rows
                for outcome in row["summaries"][rating]["outcomes"].values()
            )
            effective_maximum = max(
                outcome["max_level"]
                for row in eligible_rows
                for outcome in row["summaries"][rating]["outcomes"].values()
            )
            effective_average_numerator = sum(
                row["weight"] * row["summaries"][rating]["level_sum"]
                for row in eligible_rows
            )
            effective_average_denominator = sum(
                row["weight"] * row["summaries"][rating]["level_count"]
                for row in eligible_rows
            )

        slot_outcomes = []
        effective_species = set()
        stage_changes = []
        for row in slot_rows:
            summary = row["summaries"][rating]
            outcomes = [
                {
                    "species": species,
                    "minimumLevel": outcome["min_level"],
                    "maximumLevel": outcome["max_level"],
                }
                for species, outcome in sorted(summary["outcomes"].items())
            ]
            changes = [
                {"fromSpecies": source, "toSpecies": target}
                for source, target in sorted(summary["stage_changes"])
            ]
            if not summary["locked"]:
                effective_species.update(outcome["species"] for outcome in outcomes)
                stage_changes.extend(
                    {
                        "slot": row["slot"],
                        "fromSpecies": change["fromSpecies"],
                        "toSpecies": change["toSpecies"],
                    }
                    for change in changes
                )
            slot_outcomes.append(
                {
                    "slot": row["slot"],
                    "weight": row["weight"],
                    "original": row["vanilla"],
                    "effective": outcomes,
                    "stageChanges": changes,
                    "locked": summary["locked"],
                    "unlockRating": row["unlockRating"],
                }
            )
        matrix.append(
            {
                "rating": rating,
                "original": {
                    "minimumLevel": original_minimum,
                    "weightedAverage": {
                        "numerator": original_average_numerator,
                        "denominator": original_average_denominator,
                    },
                    "maximumLevel": original_maximum,
                },
                "effective": {
                    "minimumLevel": effective_minimum,
                    "weightedAverage": {
                        "numerator": effective_average_numerator,
                        "denominator": effective_average_denominator,
                    },
                    "maximumLevel": effective_maximum,
                    "species": sorted(effective_species),
                },
                "stageChanges": stage_changes,
                "lockedSlots": [row["slot"] for row in locked_rows],
                "eligibleSlotCount": len(eligible_rows),
                "lockedSlotCount": len(locked_rows),
                "unlockRatings": [
                    {"slot": row["slot"], "rating": row["unlockRating"]}
                    for row in slot_rows
                ],
                "totalWeight": sum(weights),
                "eligibleWeight": eligible_weight,
                "lockedWeight": locked_weight,
                "renormalizedProbabilities": [
                    {
                        "slot": row["slot"],
                        "weight": row["weight"],
                        "numerator": row["weight"],
                        "denominator": eligible_weight,
                    }
                    for row in eligible_rows
                ],
                "slotOutcomes": slot_outcomes,
            }
        )
    for row in slot_rows:
        row.pop("summaries")
    return slot_rows, matrix, failures


def _cross_profile_ordering_failures(profiles):
    failures = []
    profiles_by_method = {}
    for profile in profiles:
        profiles_by_method.setdefault(
            (profile["method"], profile["fishingRod"]), []
        ).append(profile)

    for (method, fishing_rod), method_profiles in sorted(profiles_by_method.items()):
        for index, weaker_profile in enumerate(method_profiles):
            weaker_matrix = {row["rating"]: row for row in weaker_profile["matrix"]}
            for stronger_profile in method_profiles[index + 1 :]:
                stronger_matrix = {
                    row["rating"]: row for row in stronger_profile["matrix"]
                }
                for rating in REQUIRED_AUDIT_RATINGS:
                    first = weaker_matrix[rating]
                    second = stronger_matrix[rating]
                    if (
                        first["original"]["maximumLevel"]
                        < second["original"]["minimumLevel"]
                    ):
                        weaker, stronger = first, second
                        weaker_label, stronger_label = (
                            weaker_profile["label"],
                            stronger_profile["label"],
                        )
                    elif (
                        second["original"]["maximumLevel"]
                        < first["original"]["minimumLevel"]
                    ):
                        weaker, stronger = second, first
                        weaker_label, stronger_label = (
                            stronger_profile["label"],
                            weaker_profile["label"],
                        )
                    else:
                        continue
                    if (
                        weaker["effective"]["maximumLevel"] is not None
                        and stronger["effective"]["minimumLevel"] is not None
                        and weaker["effective"]["maximumLevel"]
                        > stronger["effective"]["minimumLevel"]
                    ):
                        failures.append(
                            "cross-profile ordering: "
                            f"{method}/{fishing_rod} rating {rating} projects "
                            f"{weaker_label} above the strictly stronger vanilla "
                            f"profile {stronger_label}"
                        )
    return failures


def build_wild_encounter_balance_audit(
    encounters_path=DEFAULT_ENCOUNTERS,
    registry_path=DEFAULT_REGISTRY,
    scaling_path=DEFAULT_SCALING,
    config_path=DEFAULT_CONFIG,
    rtc_constants_path=DEFAULT_RTC_CONSTANTS,
    map_groups_path=DEFAULT_MAP_GROUPS,
    maps_root=DEFAULT_MAPS_ROOT,
    map_sections_path=DEFAULT_MAP_SECTIONS,
    species_path=DEFAULT_SPECIES,
    time_policies_path=DEFAULT_TIME_POLICIES,
    enforce_reviewed_method_fallbacks=True,
    wild_encounter_species_path=DEFAULT_WILD_ENCOUNTER_SPECIES,
    species_info_path=DEFAULT_SPECIES_INFO,
):
    encounters = _load_json(encounters_path)
    registry = _load_json(registry_path)
    config = Config(config_path, rtc_constants_path, encounters)
    maps = _load_map_authority(map_groups_path, maps_root, map_sections_path)
    species = _load_species(species_path)
    profiles = validate_inputs(encounters, registry, config, maps, species)
    time_policy_labels, _ = _load_time_policies(
        time_policies_path,
        profiles,
        encounters,
        config,
        maps,
        (REVIEWED_METHOD_TIME_FALLBACKS if enforce_reviewed_method_fallbacks else None),
    )
    scaling = _load_scaling(scaling_path, DEFAULT_REGIONAL_FACTS)
    if any(rating > scaling["projection_cap"] for rating in REQUIRED_AUDIT_RATINGS):
        raise ValidationError(
            f"{scaling_path}: projection cap must cover required balance audit ratings"
        )
    profile_offsets = _load_profile_offsets(
        scaling["profile_offsets"],
        scaling_path,
        profiles,
        encounters,
        config,
        time_policy_labels,
    )
    species_metadata = _load_wild_encounter_species_metadata(
        wild_encounter_species_path,
        species_info_path,
        species,
        _ordinary_runtime_species(profiles, encounters, config, time_policy_labels),
    )
    metadata_by_species = {
        metadata["species"]: metadata for metadata in species_metadata
    }
    offsets = _profile_offset_map(profile_offsets)
    header_indices = _runtime_header_indices(profiles, config, time_policy_labels)
    encounter_by_label = {
        encounter["base_label"]: (group, encounter)
        for group in encounters["wild_encounter_groups"]
        for encounter in group["encounters"]
    }
    failures = []
    audit_profiles = []
    for profile in _select_runtime_profiles(profiles, config, time_policy_labels):
        if profile["group"] != "gWildMonHeaders":
            continue
        group, encounter = encounter_by_label[profile["label"]]
        header_id = header_indices[profile["header"]]
        time_of_day = _resolve_profile_time(profile, config, time_policy_labels)
        for method in config.mon_types:
            if method not in encounter:
                continue
            fishing_rods = (
                ("OLD_ROD", "GOOD_ROD", "SUPER_ROD")
                if method == "fishing_mons"
                else ("NONE",)
            )
            for fishing_rod in fishing_rods:
                if method == "fishing_mons":
                    indices = next(
                        field["groups"][fishing_rod.lower()]
                        for field in group["fields"]
                        if field["type"] == method
                    )
                    audit_encounter = {
                        method: {
                            "mons": [
                                encounter[method]["mons"][index] for index in indices
                            ]
                        }
                    }
                else:
                    audit_encounter = encounter
                weights = _field_weights(
                    group,
                    method,
                    fishing_rod,
                    len(audit_encounter[method]["mons"]),
                )
                context = (
                    header_id,
                    METHOD_AREAS[method],
                    time_of_day,
                    FISHING_RODS[fishing_rod],
                )
                slot_rows, aggregates, profile_failures = _audit_profile_slots(
                    profile["label"],
                    method,
                    fishing_rod,
                    audit_encounter,
                    weights,
                    scaling,
                    offsets.get(context, 0),
                    metadata_by_species,
                )
                failures.extend(profile_failures)
                audit_profiles.append(
                    {
                        "label": profile["label"],
                        "header": profile["header"],
                        "headerId": header_id,
                        "residency": profile["residency"],
                        "timeOfDay": time_of_day,
                        "method": method,
                        "fishingRod": fishing_rod,
                        "encounterRate": encounter[method]["encounter_rate"],
                        "levelOffset": offsets.get(context, 0),
                        "matrix": aggregates,
                        "slots": slot_rows,
                    }
                )
    audit_profiles.sort(
        key=lambda profile: (
            profile["headerId"],
            profile["timeOfDay"],
            profile["method"],
            profile["fishingRod"],
            profile["label"],
        )
    )
    failures.extend(_cross_profile_ordering_failures(audit_profiles))
    return {
        "schemaVersion": 1,
        "ratings": list(REQUIRED_AUDIT_RATINGS),
        "balance": {
            "projectionCap": scaling["projection_cap"],
            "maximumRating": scaling["maximum_rating"],
        },
        "profiles": audit_profiles,
        "invariants": {"passed": not failures, "failures": failures},
    }


def generate_wild_encounter_balance_audit(output_path=DEFAULT_BALANCE_AUDIT, **kwargs):
    audit = build_wild_encounter_balance_audit(**kwargs)
    if audit["invariants"]["failures"]:
        raise ValidationError(
            "wild encounter balance audit invariant failures: "
            + "; ".join(audit["invariants"]["failures"])
        )
    _atomic_write(
        output_path,
        json.dumps(audit, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
    )
    return audit


def _atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        output_mode = DEFAULT_OUTPUT_MODE
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(content)
            temporary.flush()
            os.fchmod(temporary.fileno(), output_mode)
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
        raise


def generate(
    encounters_path=DEFAULT_ENCOUNTERS,
    registry_path=DEFAULT_REGISTRY,
    scaling_path=DEFAULT_SCALING,
    output_path=DEFAULT_OUTPUT,
    config_path=DEFAULT_CONFIG,
    rtc_constants_path=DEFAULT_RTC_CONSTANTS,
    map_groups_path=DEFAULT_MAP_GROUPS,
    maps_root=DEFAULT_MAPS_ROOT,
    map_sections_path=DEFAULT_MAP_SECTIONS,
    species_path=DEFAULT_SPECIES,
    time_policies_path=DEFAULT_TIME_POLICIES,
    enforce_reviewed_method_fallbacks=True,
    wild_encounter_species_path=DEFAULT_WILD_ENCOUNTER_SPECIES,
    species_info_path=DEFAULT_SPECIES_INFO,
):
    encounters = _load_json(encounters_path)
    registry = _load_json(registry_path)
    config = Config(config_path, rtc_constants_path, encounters)
    maps = _load_map_authority(map_groups_path, maps_root, map_sections_path)
    species = _load_species(species_path)
    profiles = validate_inputs(encounters, registry, config, maps, species)
    time_policy_labels, time_policy_headers = _load_time_policies(
        time_policies_path,
        profiles,
        encounters,
        config,
        maps,
        (REVIEWED_METHOD_TIME_FALLBACKS if enforce_reviewed_method_fallbacks else None),
    )
    _select_runtime_profiles(profiles, config, time_policy_labels)
    scaling = _load_scaling(scaling_path, DEFAULT_REGIONAL_FACTS)
    profile_offsets = _load_profile_offsets(
        scaling["profile_offsets"],
        scaling_path,
        profiles,
        encounters,
        config,
        time_policy_labels,
    )
    species_metadata = _load_wild_encounter_species_metadata(
        wild_encounter_species_path,
        species_info_path,
        species,
        _ordinary_runtime_species(profiles, encounters, config, time_policy_labels),
    )
    rendered = render_header(
        encounters,
        config,
        profiles,
        time_policy_labels,
        time_policy_headers,
        scaling,
        profile_offsets,
        species_metadata,
    )
    _atomic_write(output_path, rendered)


def _arguments():
    parser = argparse.ArgumentParser(
        description="Validate and generate resident wild encounters"
    )
    parser.add_argument("--encounters", type=Path, default=DEFAULT_ENCOUNTERS)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--scaling", type=Path, default=DEFAULT_SCALING)
    parser.add_argument(
        "--balance-audit",
        type=Path,
        nargs="?",
        const=DEFAULT_BALANCE_AUDIT,
        help="write a deterministic ordinary-encounter balance audit",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--rtc-constants", type=Path, default=DEFAULT_RTC_CONSTANTS)
    parser.add_argument("--map-groups", type=Path, default=DEFAULT_MAP_GROUPS)
    parser.add_argument("--maps-root", type=Path, default=DEFAULT_MAPS_ROOT)
    parser.add_argument("--map-sections", type=Path, default=DEFAULT_MAP_SECTIONS)
    parser.add_argument("--species", type=Path, default=DEFAULT_SPECIES)
    parser.add_argument(
        "--wild-encounter-species", type=Path, default=DEFAULT_WILD_ENCOUNTER_SPECIES
    )
    parser.add_argument("--species-info", type=Path, default=DEFAULT_SPECIES_INFO)
    parser.add_argument("--time-policies", type=Path, default=DEFAULT_TIME_POLICIES)
    return parser.parse_args()


def main():
    arguments = _arguments()
    common_arguments = {
        "encounters_path": arguments.encounters,
        "registry_path": arguments.registry,
        "scaling_path": arguments.scaling,
        "config_path": arguments.config,
        "rtc_constants_path": arguments.rtc_constants,
        "map_groups_path": arguments.map_groups,
        "maps_root": arguments.maps_root,
        "map_sections_path": arguments.map_sections,
        "species_path": arguments.species,
        "time_policies_path": arguments.time_policies,
        "wild_encounter_species_path": arguments.wild_encounter_species,
        "species_info_path": arguments.species_info,
    }
    try:
        if arguments.balance_audit is not None:
            audit = generate_wild_encounter_balance_audit(
                arguments.balance_audit, **common_arguments
            )
            print(
                "wild encounter balance audit passed: "
                f"{arguments.balance_audit} ({len(audit['profiles'])} profile rows)"
            )
        else:
            generate(output_path=arguments.output, **common_arguments)
    except ValidationError as error:
        raise SystemExit(f"wild encounter generation failed: {error}") from error


if __name__ == "__main__":
    main()
