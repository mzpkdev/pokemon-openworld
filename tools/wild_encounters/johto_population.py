"""Project approved Johto source inventory into runtime encounter data."""

import argparse
import copy
import json
import os
import tempfile
from pathlib import Path

from tools.content_port.ecology_fallbacks import validate_fallback_document
from tools.content_port.errors import ContentPortError


ROOT = Path(__file__).resolve().parents[2]
PORT_ROOT = ROOT / "tools/content_port/ports/johto"
DEFAULT_CLASSIFICATION = PORT_ROOT / "encounter_classification.json"
DEFAULT_ECOLOGY = PORT_ROOT / "encounter_ecology.json"
DEFAULT_FALLBACKS = PORT_ROOT / "encounter_fallbacks.json"
DEFAULT_ENCOUNTERS = ROOT / "src/data/wild_encounters.json"
DEFAULT_REGISTRY = ROOT / "src/data/wild_encounter_registry.json"
DEFAULT_BANDS = ROOT / "src/data/wild_encounter_bands.json"
DEFAULT_TIME_POLICIES = ROOT / "src/data/wild_encounter_time_policies.json"
DEFAULT_MAPS_ROOT = ROOT / "data/maps"


def _default_ecology_source():
    configured = os.environ.get("CONTENT_PORT_DONOR_ROOT")
    if configured:
        donor_root = Path(configured).resolve()
    elif (ROOT / ".references").is_dir():
        donor_root = ROOT / ".references"
    elif (ROOT.parents[2] / ".references").is_dir():
        donor_root = ROOT.parents[2] / ".references"
    else:
        donor_root = ROOT / ".references"
    return donor_root / "pokemonHnS/src/data/wild_encounters.json"


DEFAULT_ECOLOGY_SOURCE = _default_ecology_source()

METHOD_CAPACITIES = {
    "land_mons": 12,
    "water_mons": 5,
    "rock_smash_mons": 5,
    "fishing_mons": 10,
}
METHOD_ORDER = tuple(METHOD_CAPACITIES)
RODS = (("OLD_ROD", "old_rod"), ("GOOD_ROD", "good_rod"), ("SUPER_ROD", "super_rod"))
TIER_LEVELS = ((4, 8), (10, 14), (15, 19), (20, 24))
CLASSIFICATION_COUNTS = {"ordinary": 89, "special": 18, "encounter-free": 147}
ROUTE39_LABELS = {"gRoute39", "gRoute39_Night"}


class ProjectionError(ValueError):
    pass


def _exact(value, keys, location):
    if not isinstance(value, dict) or set(value) != set(keys):
        actual = set(value) if isinstance(value, dict) else set()
        raise ProjectionError(
            f"{location}: expected keys {sorted(keys)}, found {sorted(actual)}"
        )


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectionError(f"{path}: {error}") from error


def _classification(document):
    _exact(document, {"schemaVersion", "maps"}, "classification")
    if document["schemaVersion"] != 1 or not isinstance(document["maps"], list):
        raise ProjectionError("classification: unsupported schema")
    result = {}
    counts = {key: 0 for key in CLASSIFICATION_COUNTS}
    for index, row in enumerate(document["maps"]):
        if not isinstance(row, dict):
            raise ProjectionError(f"classification/maps/{index}: expected object")
        expected = (
            {"map", "kind", "owner"}
            if row.get("kind") == "special"
            else {"map", "kind"}
        )
        _exact(row, expected, f"classification/maps/{index}")
        name, kind = row["map"], row["kind"]
        if (
            not isinstance(name, str)
            or not name
            or kind not in counts
            or name in result
        ):
            raise ProjectionError(f"classification/maps/{index}: invalid map row")
        result[name] = kind
        counts[kind] += 1
    if counts != CLASSIFICATION_COUNTS:
        raise ProjectionError(
            f"classification: expected {CLASSIFICATION_COUNTS}, found {counts}"
        )
    return result


def _ecology(document, ordinary):
    _exact(document, {"schemaVersion", "source", "records"}, "ecology")
    if document["schemaVersion"] != 1 or not isinstance(document["records"], list):
        raise ProjectionError("ecology: unsupported schema")
    records = {}
    profiles = {}
    for index, row in enumerate(document["records"]):
        if not isinstance(row, dict):
            raise ProjectionError(f"ecology/records/{index}: invalid keys")
        expected = (
            {"map", "status", "reason", "evidenceNeeded"}
            if row.get("status") == "blocked"
            else {"map", "status", "profiles"}
            | ({"reviewNotes"} if "reviewNotes" in row else set())
        )
        _exact(row, expected, f"ecology/records/{index}")
        name = row["map"]
        if (
            name not in ordinary
            or name in records
            or row["status"] not in {"inventoried", "blocked"}
        ):
            raise ProjectionError(
                f"ecology/records/{index}: invalid ordinary map record"
            )
        row_profiles = row.get("profiles", [])
        if not isinstance(row_profiles, list):
            raise ProjectionError(f"ecology/records/{index}/profiles: expected list")
        records[name] = row
        for profile in row_profiles:
            label = profile.get("label") if isinstance(profile, dict) else None
            if not isinstance(label, str) or label in profiles:
                raise ProjectionError(
                    f"ecology/records/{index}: duplicate or invalid profile"
                )
            profiles[label] = profile
    if set(records) != ordinary:
        raise ProjectionError("ecology: records do not exactly cover ordinary maps")
    return records, profiles


def _source_profiles(document, wanted=None):
    groups = (
        document.get("wild_encounter_groups") if isinstance(document, dict) else None
    )
    if not isinstance(groups, list):
        raise ProjectionError("ecology source: missing wild_encounter_groups")
    result = {}
    for group in groups:
        fields = group.get("fields", []) if isinstance(group, dict) else []
        weights = {field["type"]: field["encounter_rates"] for field in fields}
        fishing_groups = next(
            (
                field.get("groups", {})
                for field in fields
                if field.get("type") == "fishing_mons"
            ),
            {},
        )
        rod_by_index = {
            slot: rod for rod, slots in fishing_groups.items() for slot in slots
        }
        for row in group.get("encounters", []) if isinstance(group, dict) else []:
            label = row.get("base_label") if isinstance(row, dict) else None
            if not isinstance(label, str) or label in result:
                continue
            if wanted is not None and label not in wanted:
                continue
            methods = []
            for method in METHOD_ORDER:
                if method not in row:
                    continue
                entry = row[method]
                method_weights = weights.get(method)
                if not isinstance(entry, dict) or not isinstance(method_weights, list):
                    raise ProjectionError(
                        f"ecology source/{label}/{method}: invalid source method"
                    )
                slots = []
                for index, mon in enumerate(entry.get("mons", [])):
                    if index >= len(method_weights):
                        raise ProjectionError(
                            f"ecology source/{label}/{method}: source overflow"
                        )
                    slot = {
                        "index": index,
                        "weight": method_weights[index],
                        "species": mon["species"],
                        "observedMinLevel": mon.get("min_level", 2),
                        "observedMaxLevel": mon.get("max_level", 100),
                    }
                    if method == "fishing_mons":
                        slot["rodGroup"] = rod_by_index.get(index)
                    slots.append(slot)
                methods.append(
                    {
                        "method": method,
                        "encounterRate": entry["encounter_rate"],
                        "slots": slots,
                    }
                )
            result[label] = {
                "sourceMap": row.get("map"),
                "label": label,
                "methods": methods,
            }
    return result


def _fallback_rows(document, blocked, source_profiles):
    _exact(
        document,
        {"schemaVersion", "ecologySource", "spatialSource", "records"},
        "fallbacks",
    )
    if document["schemaVersion"] != 1 or not isinstance(document["records"], list):
        raise ProjectionError("fallbacks: unsupported schema")
    result = {}
    for index, row in enumerate(document["records"]):
        location = f"fallbacks/records/{index}"
        _exact(
            row,
            {
                "targetName",
                "targetMap",
                "sourceMap",
                "profiles",
                "rationale",
                "spatialEvidence",
            },
            location,
        )
        name = row["targetName"]
        if (
            name not in blocked
            or name in result
            or not isinstance(row["targetMap"], str)
        ):
            raise ProjectionError(f"{location}: invalid fallback target")
        if not isinstance(row["profiles"], list) or not row["profiles"]:
            raise ProjectionError(f"{location}/profiles: expected nonempty list")
        projected = []
        for profile_index, binding in enumerate(row["profiles"]):
            binding_location = f"{location}/profiles/{profile_index}"
            _exact(
                binding, {"sourceLabel", "targetLabel", "condition"}, binding_location
            )
            if binding["condition"] not in {"day", "night"}:
                raise ProjectionError(
                    f"{binding_location}: condition must be day or night"
                )
            source = source_profiles.get(binding["sourceLabel"])
            if source is None:
                raise ProjectionError(f"{binding_location}: unresolved sourceLabel")
            if source.get("sourceMap") != row["sourceMap"]:
                raise ProjectionError(
                    f"{binding_location}: sourceLabel does not belong to sourceMap"
                )
            clone = copy.deepcopy(source)
            clone["label"] = binding["targetLabel"]
            clone["condition"] = binding["condition"]
            projected.append(clone)
        result[name] = (row["targetMap"], projected)
    if set(result) != blocked:
        raise ProjectionError(
            "fallbacks: rows do not exactly cover blocked ordinary maps"
        )
    return result


def _trim_method(method, location):
    if not isinstance(method, dict) or set(method) != {
        "method",
        "encounterRate",
        "slots",
    }:
        raise ProjectionError(f"{location}: invalid method")
    name, rate, slots = method["method"], method["encounterRate"], method["slots"]
    if (
        name not in METHOD_CAPACITIES
        or isinstance(rate, bool)
        or not isinstance(rate, int)
        or not 0 <= rate <= 255
    ):
        raise ProjectionError(f"{location}: invalid method identity or encounter rate")
    if not isinstance(slots, list):
        raise ProjectionError(f"{location}/slots: expected list")
    capacity = METHOD_CAPACITIES[name]
    overflow = slots[capacity:]
    if any(
        slot.get("weight") is not None for slot in overflow if isinstance(slot, dict)
    ) or any(not isinstance(slot, dict) for slot in overflow):
        raise ProjectionError(
            f"{location}: non-null overflow exceeds canonical capacity {capacity}"
        )
    slots = slots[:capacity]
    if len(slots) != capacity:
        raise ProjectionError(
            f"{location}: expected exactly {capacity} canonical slots after overflow"
        )
    for slot_index, slot in enumerate(slots):
        required = {
            "index",
            "weight",
            "species",
            "observedMinLevel",
            "observedMaxLevel",
        }
        if name == "fishing_mons":
            required.add("rodGroup")
        _exact(slot, required, f"{location}/slots/{slot_index}")
        if (
            slot["index"] != slot_index
            or isinstance(slot["weight"], bool)
            or not isinstance(slot["weight"], int)
            or slot["weight"] <= 0
        ):
            raise ProjectionError(
                f"{location}/slots/{slot_index}: invalid canonical weight/index"
            )
    if rate == 0 or all(slot["species"] == "SPECIES_NONE" for slot in slots):
        return None
    if any(slot["species"] == "SPECIES_NONE" for slot in slots):
        raise ProjectionError(
            f"{location}: mixed SPECIES_NONE method is not projectable"
        )
    return {"name": name, "rate": rate, "slots": slots}


def _profile(label, map_id, source, location):
    methods = []
    for index, method in enumerate(source.get("methods", [])):
        trimmed = _trim_method(method, f"{location}/methods/{index}")
        if trimmed is not None:
            methods.append(trimmed)
    if not methods:
        raise ProjectionError(f"{location}: profile has no eligible runtime method")
    encounter = {"base_label": label, "map": map_id}
    bands = []
    for method in methods:
        encounter[method["name"]] = {
            "encounter_rate": method["rate"],
            "mons": [
                {
                    "min_level": slot["observedMinLevel"],
                    "max_level": slot["observedMaxLevel"],
                    "species": slot["species"],
                }
                for slot in method["slots"]
            ],
        }
        rod_groups = RODS if method["name"] == "fishing_mons" else (("NONE", None),)
        for rod, donor_rod in rod_groups:
            slots = [
                slot
                for slot in method["slots"]
                if donor_rod is None or slot["rodGroup"] == donor_rod
            ]
            if not slots:
                raise ProjectionError(f"{location}/{method['name']}: empty {rod} group")
            species_weights = {}
            for slot in slots:
                species_weights.setdefault(slot["species"], 0)
                species_weights[slot["species"]] += slot["weight"]
            condition = (
                "TIME_NIGHT" if source["condition"] == "night" else "TIME_FALLBACK"
            )
            bands.append(
                {
                    "label": label,
                    "header": label.removesuffix("_Night")
                    if condition == "TIME_NIGHT"
                    else label,
                    "method": method["name"],
                    "condition": condition,
                    "fishing_rod": rod,
                    "missing_band_policy": "complete",
                    "tiers": [
                        {
                            "tier": tier,
                            "entries": [
                                {
                                    "species": species,
                                    "weight": weight,
                                    "min_level": levels[0],
                                    "max_level": levels[1],
                                }
                                for species, weight in species_weights.items()
                            ],
                        }
                        for tier, levels in enumerate(TIER_LEVELS)
                    ],
                }
            )
    return encounter, bands, {method["name"] for method in methods}


def project_documents(
    classification,
    ecology,
    fallbacks,
    encounters,
    registry,
    bands,
    map_ids,
    ecology_source,
):
    """Return the four projected documents without mutating any input."""
    try:
        validate_fallback_document(fallbacks)
    except ContentPortError as error:
        raise ProjectionError(f"fallbacks: {error}") from error
    kinds = _classification(classification)
    ordinary = {name for name, kind in kinds.items() if kind == "ordinary"}
    records, source_profiles = _ecology(ecology, ordinary)
    blocked = {name for name, row in records.items() if row["status"] == "blocked"}
    wanted_sources = {
        binding.get("sourceLabel")
        for row in fallbacks.get("records", [])
        if isinstance(row, dict)
        for binding in row.get("profiles", [])
        if isinstance(binding, dict)
    }
    fallback_sources = dict(source_profiles)
    fallback_sources.update(
        _source_profiles(ecology_source, wanted_sources - set(source_profiles))
    )
    fallback_by_map = _fallback_rows(fallbacks, blocked, fallback_sources)

    selected = []
    for name in (
        row["map"] for row in classification["maps"] if row["kind"] == "ordinary"
    ):
        record = records[name]
        if name == "Route39":
            continue
        if record["status"] == "blocked":
            map_id, profiles = fallback_by_map[name]
        else:
            map_id = map_ids[name]
            profiles = record["profiles"]
            if name == "MtSilver_Snow":
                profiles = [
                    copy.deepcopy(profile)
                    for profile in profiles
                    if profile["condition"] in {"legacy-day", "legacy-night"}
                ]
                for profile in profiles:
                    profile["condition"] = (
                        "day" if profile["condition"] == "legacy-day" else "night"
                    )
                    profile["label"] = "gMtSilver_Snow" + (
                        "_Night" if profile["condition"] == "night" else ""
                    )
            else:
                profiles = [
                    profile
                    for profile in profiles
                    if profile["condition"] in {"day", "night"}
                ]
        selected.append((name, map_id, profiles))

    projected_encounters, projected_registry, projected_bands = [], [], []
    pair_info = []
    for name, map_id, profiles in selected:
        if map_id != map_ids[name]:
            raise ProjectionError(
                f"{name}: fallback targetMap is not the target map identity"
            )
        built = []
        conditions = set()
        for index, source in enumerate(profiles):
            condition = source["condition"]
            if condition in conditions:
                raise ProjectionError(f"{name}: duplicate {condition} profile")
            conditions.add(condition)
            label = source["label"]
            encounter, authored_bands, methods = _profile(
                label, map_id, source, f"{name}/profiles/{index}"
            )
            header = label.removesuffix("_Night") if condition == "night" else label
            built.append((condition, label, header, methods))
            projected_encounters.append(encounter)
            projected_registry.append(
                [
                    "gWildMonHeaders",
                    label,
                    header,
                    "johto",
                    "TIME_NIGHT" if condition == "night" else "TIME_FALLBACK",
                    None,
                    None,
                    None,
                ]
            )
            projected_bands.extend(authored_bands)
        if not built:
            raise ProjectionError(f"{name}: ordinary map has no selected profile")
        if conditions == {"day", "night"}:
            day = next(row for row in built if row[0] == "day")
            night = next(row for row in built if row[0] == "night")
            shared = next(
                (method for method in METHOD_ORDER if method in day[3] & night[3]), None
            )
            if shared is None or day[2] != night[2]:
                raise ProjectionError(
                    f"{name}: selected pair has no shared runtime habitat/header"
                )
            pair_info.append((name, day[1], night[1], shared))
        elif conditions != {"day"}:
            raise ProjectionError(f"{name}: selected profiles must be day or day/night")

    output_encounters = copy.deepcopy(encounters)
    group = next(
        (
            row
            for row in output_encounters["wild_encounter_groups"]
            if row["label"] == "gWildMonHeaders"
        ),
        None,
    )
    if group is None:
        raise ProjectionError("encounters: missing gWildMonHeaders")
    route39_encounters = [
        copy.deepcopy(row)
        for row in group["encounters"]
        if row["base_label"] in ROUTE39_LABELS
    ]
    non_johto_labels = {row[1] for row in registry["profiles"] if row[3] != "johto"}
    group["encounters"] = (
        [
            copy.deepcopy(row)
            for row in group["encounters"]
            if row["base_label"] in non_johto_labels
        ]
        + projected_encounters
        + route39_encounters
    )

    output_registry = copy.deepcopy(registry)
    non_johto_registry = [
        copy.deepcopy(row) for row in registry["profiles"] if row[3] != "johto"
    ]
    route39_registry = [
        copy.deepcopy(row) for row in registry["profiles"] if row[1] in ROUTE39_LABELS
    ]
    split = next(
        (i for i, row in enumerate(non_johto_registry) if row[0] != "gWildMonHeaders"),
        len(non_johto_registry),
    )
    output_registry["profiles"] = (
        non_johto_registry[:split]
        + projected_registry
        + route39_registry
        + non_johto_registry[split:]
    )

    output_bands = copy.deepcopy(bands)
    route39_bands = [
        copy.deepcopy(row)
        for row in bands["profiles"]
        if row["label"] in ROUTE39_LABELS
    ]
    johto_labels = {row[1] for row in registry["profiles"] if row[3] == "johto"}
    output_bands["profiles"] = (
        [
            copy.deepcopy(row)
            for row in bands["profiles"]
            if row["label"] not in johto_labels
        ]
        + projected_bands
        + route39_bands
    )

    typed = []
    policies = []
    for name, day_label, night_label, habitat in pair_info:
        typed.extend(
            [
                {
                    "map": name,
                    "label": day_label,
                    "habitat": habitat,
                    "authority": "content",
                    "time": "TIME_DAY",
                },
                {
                    "map": name,
                    "label": night_label,
                    "habitat": habitat,
                    "authority": "content",
                    "time": "TIME_NIGHT",
                },
            ]
        )
        policies.append(
            {
                "map": name,
                "dayStart": "06:00",
                "nightStart": "18:00",
                "dayLabel": day_label,
                "nightLabel": night_label,
                "fallbackLabel": day_label,
            }
        )
    typed.extend(
        [
            {
                "map": "Route39",
                "label": "gRoute39",
                "habitat": "land_mons",
                "authority": "content",
                "time": "TIME_DAY",
            },
            {
                "map": "Route39",
                "label": "gRoute39_Night",
                "habitat": "land_mons",
                "authority": "content",
                "time": "TIME_NIGHT",
            },
        ]
    )
    policies.append(
        {
            "map": "Route39",
            "dayStart": "06:00",
            "nightStart": "18:00",
            "dayLabel": "gRoute39",
            "nightLabel": "gRoute39_Night",
            "fallbackLabel": "gRoute39",
        }
    )
    time_policies = {
        "schema_version": 1,
        "encounterProfiles": typed,
        "encounterTimePolicy": policies,
    }
    return output_encounters, output_registry, output_bands, time_policies


def _map_ids(classification, maps_root):
    result = {}
    for row in classification["maps"]:
        if row["kind"] != "ordinary":
            continue
        path = Path(maps_root) / row["map"] / "map.json"
        document = _load(path)
        map_id = document.get("id") if isinstance(document, dict) else None
        if not isinstance(map_id, str) or not map_id.startswith("MAP_"):
            raise ProjectionError(f"{path}: missing target map identity")
        result[row["map"]] = map_id
    return result


def _encoded(document):
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode()


def check_or_write(outputs, write=False):
    """Check output bytes, or atomically replace every mismatching output."""
    mismatches = [
        Path(path)
        for path, document in outputs.items()
        if not Path(path).exists() or Path(path).read_bytes() != _encoded(document)
    ]
    if not write:
        return mismatches
    staged = []
    try:
        for path, document in outputs.items():
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{path.name}.", dir=path.parent
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(_encoded(document))
                stream.flush()
                os.fsync(stream.fileno())
            staged.append((Path(temporary), path))
        for temporary, path in staged:
            os.replace(temporary, path)
        return mismatches
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classification", type=Path, default=DEFAULT_CLASSIFICATION)
    parser.add_argument("--ecology", type=Path, default=DEFAULT_ECOLOGY)
    parser.add_argument("--fallbacks", type=Path, default=DEFAULT_FALLBACKS)
    parser.add_argument("--encounters", type=Path, default=DEFAULT_ENCOUNTERS)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--bands", type=Path, default=DEFAULT_BANDS)
    parser.add_argument("--time-policies", type=Path, default=DEFAULT_TIME_POLICIES)
    parser.add_argument("--maps-root", type=Path, default=DEFAULT_MAPS_ROOT)
    parser.add_argument("--ecology-source", type=Path, default=DEFAULT_ECOLOGY_SOURCE)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    classification = _load(args.classification)
    projected = project_documents(
        classification,
        _load(args.ecology),
        _load(args.fallbacks),
        _load(args.encounters),
        _load(args.registry),
        _load(args.bands),
        _map_ids(classification, args.maps_root),
        _load(args.ecology_source),
    )
    paths = (args.encounters, args.registry, args.bands, args.time_policies)
    mismatches = check_or_write(dict(zip(paths, projected)), write=args.write)
    if mismatches and not args.write:
        for path in mismatches:
            print(f"out of date: {path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
