import argparse
import hashlib
import io
import json
import os
import re
import stat
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENCOUNTERS = ROOT / "src/data/wild_encounters.json"
DEFAULT_REGISTRY = ROOT / "src/data/wild_encounter_registry.json"
DEFAULT_OUTPUT = ROOT / "src/data/wild_encounters.h"
DEFAULT_CONFIG = ROOT / "include/config/overworld.h"
DEFAULT_RTC_CONSTANTS = ROOT / "include/constants/rtc.h"
DEFAULT_MAP_GROUPS = ROOT / "data/maps/map_groups.json"
DEFAULT_MAPS_ROOT = ROOT / "data/maps"
DEFAULT_MAP_SECTIONS = ROOT / "src/data/region_map/region_map_sections.json"
DEFAULT_SPECIES = ROOT / "include/constants/species.h"
DEFAULT_TIME_POLICIES = ROOT / "tools/content_port/ports/johto/adaptations.json"

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
REVIEWED_PROFILE_COUNT = 409
REVIEWED_RESIDENCY_COUNTS = {
    "hoenn": 135,
    "kanto": 132,
    "sevii": 132,
    "johto": 10,
}
# SHA-256 of compact JSON containing every PROFILE_FIELDS value in registry order.
REVIEWED_ORDERED_PROFILE_SHA256 = (
    "4f4c826ed8c64339317e70a069f366ce4928fc51606d0bf86945d3487124c2c7"
)
# Deliberately revised only when authenticated authored encounter content changes.
REVIEWED_AUTHORED_CONTRACT_SHA256 = (
    "2503c282752a86638bbeda5b64d2536df632de29b5658e9a06d7c52ac030367d"
)
NON_MAP_RESIDENCY = {
    "gBattlePyramidWildMonHeaders": "hoenn",
    "gBattlePikeWildMonHeaders": "hoenn",
}
DEFAULT_OUTPUT_MODE = 0o644
REQUIRED_RUNTIME_TIME_POLICIES = {
    "Route39": {
        "dayStart": "06:00",
        "nightStart": "18:00",
        "dayLabel": "gRoute39",
        "nightLabel": "gRoute39_Night",
        "fallbackLabel": "gRoute39",
    }
}
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAP_IDENTIFIER = re.compile(r"^MAP_[A-Z0-9_]+$")
SPECIES_IDENTIFIER = re.compile(r"^SPECIES_[A-Z0-9_]+$")
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


def _load_time_policies(path, profiles, encounters, config):
    document = _load_json(path)
    policy_rows = (
        document.get("encounterTimePolicy") if isinstance(document, dict) else None
    )
    profile_rows = (
        document.get("encounterProfiles") if isinstance(document, dict) else None
    )
    if not isinstance(policy_rows, list) or not isinstance(profile_rows, list):
        raise ValidationError(
            f"{path}: encounterTimePolicy and encounterProfiles must be lists"
        )

    registry_by_label = {profile["label"]: profile for profile in profiles}
    encounter_by_label = {
        encounter["base_label"]: encounter
        for group in encounters["wild_encounter_groups"]
        for encounter in group["encounters"]
    }
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
        if row["map"] in policy_by_map:
            raise ValidationError(f"{location}: duplicate map time policy")
        policy_by_map[row["map"]] = {
            key: value for key, value in row.items() if key != "map"
        }
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
        expected_map = "MAP_" + re.sub(r"(?<!^)(?=[A-Z])", "_", row["map"]).upper()
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
            authored_day["map"] != row["map"]
            or authored_night["map"] != row["map"]
            or authored_day["habitat"] != "land_mons"
            or authored_night["habitat"] != "land_mons"
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
        if day_start >= night_start:
            raise ValidationError(
                f"{location}: daytime interval must not wrap midnight"
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
    if policy_by_map != REQUIRED_RUNTIME_TIME_POLICIES:
        raise ValidationError(
            f"{path}: runtime encounter time policy does not match reviewed authority"
        )
    if set(authored_profile_by_label) != set(labels):
        raise ValidationError(
            f"{path}: encounterProfiles must exactly match profiles consumed by "
            "encounterTimePolicy"
        )
    return labels, headers


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


def render_header(
    encounters, config, profiles, time_policy_labels, time_policy_headers
):
    output = io.StringIO()
    assembler = WildEncounterAssembler(
        output, encounters, config, profiles, time_policy_labels, time_policy_headers
    )
    assembler.write_header()
    assembler.write_macros()
    assembler.write_encounters()
    rendered = output.getvalue()
    if PRODUCT_GUARD.search(rendered):
        raise ValidationError("generated output contains a product residency guard")
    return rendered


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
    output_path=DEFAULT_OUTPUT,
    config_path=DEFAULT_CONFIG,
    rtc_constants_path=DEFAULT_RTC_CONSTANTS,
    map_groups_path=DEFAULT_MAP_GROUPS,
    maps_root=DEFAULT_MAPS_ROOT,
    map_sections_path=DEFAULT_MAP_SECTIONS,
    species_path=DEFAULT_SPECIES,
    time_policies_path=DEFAULT_TIME_POLICIES,
):
    encounters = _load_json(encounters_path)
    registry = _load_json(registry_path)
    config = Config(config_path, rtc_constants_path, encounters)
    maps = _load_map_authority(map_groups_path, maps_root, map_sections_path)
    species = _load_species(species_path)
    profiles = validate_inputs(encounters, registry, config, maps, species)
    time_policy_labels, time_policy_headers = _load_time_policies(
        time_policies_path, profiles, encounters, config
    )
    _select_runtime_profiles(profiles, config, time_policy_labels)
    rendered = render_header(
        encounters, config, profiles, time_policy_labels, time_policy_headers
    )
    _atomic_write(output_path, rendered)


def _arguments():
    parser = argparse.ArgumentParser(
        description="Validate and generate resident wild encounters"
    )
    parser.add_argument("--encounters", type=Path, default=DEFAULT_ENCOUNTERS)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--rtc-constants", type=Path, default=DEFAULT_RTC_CONSTANTS)
    parser.add_argument("--map-groups", type=Path, default=DEFAULT_MAP_GROUPS)
    parser.add_argument("--maps-root", type=Path, default=DEFAULT_MAPS_ROOT)
    parser.add_argument("--map-sections", type=Path, default=DEFAULT_MAP_SECTIONS)
    parser.add_argument("--species", type=Path, default=DEFAULT_SPECIES)
    parser.add_argument("--time-policies", type=Path, default=DEFAULT_TIME_POLICIES)
    return parser.parse_args()


def main():
    arguments = _arguments()
    try:
        generate(
            arguments.encounters,
            arguments.registry,
            arguments.output,
            arguments.config,
            arguments.rtc_constants,
            arguments.map_groups,
            arguments.maps_root,
            arguments.map_sections,
            arguments.species,
            arguments.time_policies,
        )
    except ValidationError as error:
        raise SystemExit(f"wild encounter generation failed: {error}") from error


if __name__ == "__main__":
    main()
