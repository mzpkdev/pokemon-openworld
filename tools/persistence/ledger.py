#!/usr/bin/env python3
"""Seed, validate, and render the persistent-ID ledger.

The frozen save contract is evidence.  The ledger is the reviewed runtime
authority: generation never discovers new numeric assignments from C source.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

from tools.persistence.contract import ContractError, canonical_bytes, load_json, write_json

SCHEMA_VERSION = 1
LEDGER_PATH = Path("src/data/persistence/persistent_ids.json")
SOURCES_PATH = Path("tools/persistence/persistent_sources.json")
CONTRACT_PATH = Path("tools/integrity/save_contract.json")


def _source_index(sources: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = sources.get("sources")
    if not isinstance(records, list) or not records:
        raise ContractError("$.sources: expected a nonempty list")
    index: dict[str, dict[str, Any]] = {}
    for record in records:
        source_id = record.get("id")
        if not isinstance(source_id, str) or not source_id:
            raise ContractError("$.sources[*].id: expected a nonempty string")
        if source_id in index:
            raise ContractError(f"$.sources: duplicate source {source_id}")
        index[source_id] = record
    return index


def _storage_index(sources: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = sources.get("storages")
    if not isinstance(records, list) or not records:
        raise ContractError("$.storages: expected a nonempty list")
    index = {record["id"]: record for record in records}
    if len(index) != len(records):
        raise ContractError("$.storages: duplicate storage id")
    return index


def _published_source(domain: str, sources: dict[str, dict[str, Any]]) -> str:
    matches = [key for key, value in sources.items()
               if value.get("contractDomain") == domain]
    if len(matches) != 1:
        raise ContractError(f"published domain {domain}: expected exactly one allocated source")
    return matches[0]


def _entry(domain: str, symbol: str, value: int, storage: str, state: dict[str, Any],
           source: str) -> dict[str, Any]:
    return {
        "alias": None,
        "domain": domain,
        "source": source,
        "state": state,
        "storage": storage,
        "symbol": symbol,
        "value": value,
    }


def seed_ledger(contract: dict[str, Any], sources: dict[str, Any], repo: Path) -> dict[str, Any]:
    source_by_id = _source_index(sources)
    storage_by_id = _storage_index(sources)
    entries: list[dict[str, Any]] = []
    for domain, bindings in sorted(contract["publishedBindings"].items()):
        source_id = _published_source(domain, source_by_id)
        source = source_by_id[source_id]
        storage = source["storage"]
        if storage not in storage_by_id:
            raise ContractError(f"source {source_id}: unallocated storage {storage}")
        for binding in bindings:
            value = binding["value"]
            state: dict[str, Any] = {"kind": "published-binding"}
            if domain == "trainerIds" and 0 <= value < sources["trainerDefeat"]["count"]:
                state = {
                    "kind": "trainer-defeat-flag",
                    "value": sources["trainerDefeat"]["flagBase"] + value,
                }
            entries.append(_entry(domain, binding["symbol"], value, storage, state, source_id))

    # Heal-location IDs used to be derived from JSON array position.  Seed their
    # current values once so subsequent source reordering cannot move a save ID.
    heal_source = source_by_id["heal-locations"]
    heal_data = load_json(repo / heal_source["path"])
    entries.append(_entry("checkpoints", "HEAL_LOCATION_NONE", 0,
                          heal_source["storage"], {"kind": "allocated-binding"},
                          "heal-locations"))
    for value, record in enumerate(heal_data["heal_locations"], 1):
        entries.append(_entry("checkpoints", record["id"], value,
                              heal_source["storage"], {"kind": "allocated-binding"},
                              "heal-locations"))
    for allocation in sources.get("explicitAllocations", []):
        source = source_by_id[allocation["source"]]
        entries.append(_entry(allocation["domain"], allocation["symbol"], allocation["value"],
                              source["storage"], {"kind": "allocated-binding"}, allocation["source"]))

    entries.sort(key=lambda item: (item["domain"], item["storage"], item["value"], item["symbol"]))
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for item in entries:
        groups[(item["domain"], item["storage"], item["value"])].append(item)
    for group in groups.values():
        owner = group[0]["symbol"]
        for item in group[1:]:
            item["alias"] = {"of": owner, "owner": item["source"]}

    return {
        "baselineCommit": contract["baselineCommit"],
        "entries": entries,
        "locationCodecs": _read_location_codecs(repo / sources["locationCodecs"]["path"]),
        "schemaVersion": SCHEMA_VERSION,
    }


def _read_location_codecs(path: Path) -> dict[str, list[dict[str, Any]]]:
    data = load_json(path)
    sections = data["map_sections"]
    values = {item["id"]: item["value"] for item in sections}
    invalid = {"section": "MAPSEC_INVALID", "sectionValue": 0xFFFF}
    saved = [{"code": code, **invalid} for code in range(256)]
    met = [{"code": code, **invalid} for code in range(256)]
    for item in sections:
        saved_symbol = item.get("saved_location")
        if saved_symbol is not None:
            code = values[saved_symbol]
            saved[code] = {"code": code, "section": saved_symbol, "sectionValue": values[saved_symbol]}
        met_code = item.get("met_location")
        met_symbol = item.get("met_location_display")
        if met_code is not None and met_symbol is not None:
            record = {"code": met_code, "section": met_symbol, "sectionValue": values[met_symbol]}
            if met[met_code]["section"] not in ("MAPSEC_INVALID", met_symbol):
                raise ContractError(f"met-location code {met_code}: conflicting canonical sections")
            met[met_code] = record
    return {"met": met, "saved": saved}


def validate_ledger(ledger: dict[str, Any], contract: dict[str, Any], sources: dict[str, Any],
                    repo: Path) -> None:
    if ledger.get("schemaVersion") != SCHEMA_VERSION:
        raise ContractError("$.schemaVersion: unsupported")
    if ledger.get("baselineCommit") != contract.get("baselineCommit"):
        raise ContractError("$.baselineCommit: ledger is not based on the frozen contract")
    entries = ledger.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ContractError("$.entries: expected a nonempty list")
    source_by_id = _source_index(sources)
    storage_by_id = _storage_index(sources)
    allowed_domains = set(contract["publishedBindings"]) | {"checkpoints"}
    seen_symbols: set[tuple[str, str]] = set()
    by_key: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    by_symbol: dict[tuple[str, str, str], dict[str, Any]] = {}
    for index, item in enumerate(entries):
        path = f"$.entries[{index}]"
        required = {"alias", "domain", "source", "state", "storage", "symbol", "value"}
        if set(item) != required:
            raise ContractError(f"{path}: fields changed")
        domain, symbol = item["domain"], item["symbol"]
        if domain not in allowed_domains:
            raise ContractError(f"{path}.domain: unknown domain {domain}")
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol):
            raise ContractError(f"{path}.symbol: invalid C symbol")
        symbol_key = (domain, symbol)
        if symbol_key in seen_symbols:
            raise ContractError(f"{path}: duplicate symbol {domain}.{symbol}")
        seen_symbols.add(symbol_key)
        source = source_by_id.get(item["source"])
        if source is None:
            raise ContractError(f"{path}.source: unallocated source reference")
        if domain not in source.get("domains", []):
            raise ContractError(f"{path}.source: source does not own domain {domain}")
        storage = storage_by_id.get(item["storage"])
        if storage is None:
            raise ContractError(f"{path}.storage: unallocated storage reference")
        if item["storage"] != source.get("storage"):
            raise ContractError(f"{path}.storage: source/storage ownership mismatch")
        value = item["value"]
        if not isinstance(value, int):
            raise ContractError(f"{path}.value: expected integer")
        width = storage["width"]
        minimum = -(1 << (width - 1)) if storage.get("signed") else 0
        maximum = (1 << (width - (1 if storage.get("signed") else 0))) - 1
        if not minimum <= value <= maximum:
            raise ContractError(f"{path}.value: width/storage overflow")
        sentinel = storage.get("sentinel")
        if sentinel is not None and value == sentinel and symbol not in storage.get("sentinelSymbols", []):
            raise ContractError(f"{path}.value: sentinel collision")
        state = item["state"]
        if not isinstance(state, dict) or state.get("kind") not in {"published-binding", "allocated-binding", "trainer-defeat-flag"}:
            raise ContractError(f"{path}.state: invalid state ownership")
        if state.get("kind") == "trainer-defeat-flag":
            flag = state.get("value")
            flag_storage = storage_by_id["saveblock1.flags"]
            if not isinstance(flag, int) or not 0 <= flag < (1 << flag_storage["width"]):
                raise ContractError(f"{path}.state.value: width/storage overflow")
            if flag == flag_storage.get("sentinel"):
                raise ContractError(f"{path}.state.value: sentinel collision")
        by_key[(domain, item["storage"], value)].append(item)
        by_symbol[(domain, item["storage"], symbol)] = item

    for key, group in by_key.items():
        owners = [item for item in group if item["alias"] is None]
        if len(owners) != 1:
            raise ContractError(f"duplicate value {key}: expected exactly one canonical owner")
        owner = owners[0]
        for item in group:
            alias = item["alias"]
            if item is owner:
                continue
            if not isinstance(alias, dict) or set(alias) != {"of", "owner"}:
                raise ContractError(f"{item['symbol']}: duplicate value without an authorized alias")
            if alias["of"] != owner["symbol"] or alias["owner"] != item["source"]:
                raise ContractError(f"{item['symbol']}: unauthorized alias")
            if alias["owner"] not in source_by_id:
                raise ContractError(f"{item['symbol']}: unallocated alias owner")

    validate_frozen_bindings(entries, contract)

    for source_id, source in source_by_id.items():
        if source.get("kind") == "json-symbol-list":
            data = load_json(repo / source["path"])
            allocated = {item["symbol"] for item in entries if item["source"] == source_id}
            referenced = {source["noneSymbol"]} | {item[source["symbolField"]] for item in data[source["listKey"]]}
            if allocated != referenced:
                raise ContractError(f"source {source_id}: unallocated source references")
        elif source.get("kind") == "explicit-source":
            text = (repo / source["path"]).read_text(encoding="utf-8")
            allocated = {item["symbol"]: item["value"] for item in entries if item["source"] == source_id}
            for symbol, value in allocated.items():
                match = re.search(rf"^#define\s+{re.escape(symbol)}\s+([^/\s]+)", text, re.MULTILINE)
                if match is None or int(match.group(1), 0) != value:
                    raise ContractError(f"source {source_id}: moved/deleted binding {symbol}")
    validate_location_codecs(ledger.get("locationCodecs"), sources, repo)
    validate_consumer_references(entries, sources.get("consumerSchemas"), repo)


def validate_location_codecs(codecs: Any, sources: dict[str, Any], repo: Path) -> None:
    expected = _read_location_codecs(repo / sources["locationCodecs"]["path"])
    if codecs != expected:
        raise ContractError("$.locationCodecs: moved/deleted/unallocated saved or met location binding")


def validate_consumer_references(entries: list[dict[str, Any]], schemas: Any, repo: Path) -> None:
    if not isinstance(schemas, list):
        raise ContractError("$.consumerSchemas: expected list")
    domains = {item["domain"] for item in entries}
    if {schema.get("domain") for schema in schemas} != domains:
        raise ContractError("$.consumerSchemas: every persisted domain needs exactly one schema")
    allocated = {(item["domain"], item["symbol"]) for item in entries}
    for schema in schemas:
        domain = schema["domain"]
        paths = schema.get("paths")
        patterns = schema.get("patterns")
        if not isinstance(paths, list) or not paths or not isinstance(patterns, list) or not patterns:
            raise ContractError(f"consumer schema {domain}: paths/patterns must be nonempty")
        for glob in paths:
            for path in repo.glob(glob):
                if not path.is_file() or any(part in {"build", ".references", ".git"} for part in path.parts):
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                for pattern in patterns:
                    for match in re.finditer(pattern, text, re.MULTILINE):
                        symbol = match.group("symbol")
                        if (domain, symbol) not in allocated:
                            raise ContractError(f"{path}: unallocated {domain} consumer reference {symbol}")
        script = schema.get("scriptTokens")
        if script is not None:
            script_paths = script.get("paths")
            prefixes = script.get("prefixes")
            excluded = set(script.get("exclude", []))
            excluded_prefixes = tuple(script.get("excludePrefixes", []))
            opcodes = set(script.get("opcodes", []))
            opcode_prefixes = tuple(script.get("opcodePrefixes", []))
            if not isinstance(script_paths, list) or not script_paths or not isinstance(prefixes, list) or not prefixes:
                raise ContractError(f"consumer schema {domain}: invalid script token inventory")
            token_re = re.compile(r"\b(?:" + "|".join(re.escape(prefix) for prefix in prefixes)
                                  + r")[A-Za-z0-9_]+\b")
            for glob in script_paths:
                for path in repo.glob(glob):
                    if not path.is_file():
                        continue
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    # Script comments cannot serialize an identity. Everything
                    # else—including macro operands and raw data directives—is
                    # intentionally token-scanned rather than opcode-guessed.
                    lines = []
                    for line in text.splitlines():
                        line = line.split("@", 1)[0].split("//", 1)[0]
                        if opcodes or opcode_prefixes:
                            opcode_match = re.match(r"^\s*([a-z][a-z0-9_]*)\b", line)
                            if opcode_match is None:
                                continue
                            opcode = opcode_match.group(1)
                            if opcode not in opcodes and not opcode.startswith(opcode_prefixes):
                                continue
                        lines.append(line)
                    executable = "\n".join(lines)
                    for symbol in token_re.findall(executable):
                        if symbol in excluded or symbol.startswith(excluded_prefixes):
                            continue
                        if (domain, symbol) not in allocated:
                            raise ContractError(f"{path}: unallocated {domain} script reference {symbol}")


def validate_frozen_bindings(entries: list[dict[str, Any]], contract: dict[str, Any]) -> None:
    """Reject any deletion, addition, or move in the published baseline projection."""
    published = {(item["domain"], item["symbol"]): item["value"] for item in entries
                 if item["state"]["kind"] in {"published-binding", "trainer-defeat-flag"}}
    frozen = {(domain, item["symbol"]): item["value"]
              for domain, bindings in contract["publishedBindings"].items() for item in bindings}
    if published != frozen:
        missing = sorted(set(frozen) - set(published))[:5]
        extra = sorted(set(published) - set(frozen))[:5]
        moved = sorted(key for key in set(frozen) & set(published) if frozen[key] != published[key])[:5]
        raise ContractError(f"published bindings moved/deleted (missing={missing}, extra={extra}, moved={moved})")

def _trainer_bindings(entries: list[dict[str, Any]], count: int) -> list[int]:
    values: dict[int, int] = {}
    for item in entries:
        state = item["state"]
        if item["domain"] == "trainerIds" and state["kind"] == "trainer-defeat-flag":
            previous = values.setdefault(item["value"], state["value"])
            if previous != state["value"]:
                raise ContractError(f"trainer {item['value']}: conflicting defeat flags")
    if set(values) != set(range(count)):
        missing = sorted(set(range(count)) - set(values))[:10]
        raise ContractError(f"trainer defeat table is incomplete: {missing}")
    return [values[index] for index in range(count)]


def render(ledger: dict[str, Any], sources: dict[str, Any], output_root: Path) -> None:
    entries = ledger["entries"]
    count = sources["trainerDefeat"]["count"]
    flags = _trainer_bindings(entries, count)
    table = ["/* Generated from persistent_ids.json; do not edit. */",
             "const u16 gTrainerDefeatFlagById[PERSISTENT_TRAINER_COUNT] =", "{"]
    table.extend(f"    [{index}] = 0x{flag:04X}," for index, flag in enumerate(flags))
    table.extend(["};", ""])
    outputs: dict[Path, bytes] = {}
    table_path = Path("src/data/persistence/trainer_defeat_flags.inc.c")
    outputs[table_path] = "\n".join(table).encode()

    heal = [item for item in entries if item["source"] == "heal-locations"]
    heal.sort(key=lambda item: item["value"])
    header = ["#ifndef GUARD_CONSTANTS_HEAL_LOCATIONS_H", "#define GUARD_CONSTANTS_HEAL_LOCATIONS_H", "",
              "/* Generated from persistent_ids.json; safe for C and assembler. */"]
    header.extend(f"#define {item['symbol']} {item['value']}" for item in heal)
    header.extend([f"#define NUM_HEAL_LOCATIONS {max(item['value'] for item in heal) + 1}", "",
                   "#endif // GUARD_CONSTANTS_HEAL_LOCATIONS_H", ""])
    header_path = Path("include/constants/heal_locations.h")
    outputs[header_path] = "\n".join(header).encode()

    facade = ["/* Generated from persistent_ids.json; do not edit. */",
              "#define PERSISTENT_SAVED_LOCATION_BINDINGS(_) \\"]
    saved = ledger["locationCodecs"]["saved"]
    for index, item in enumerate(saved):
        suffix = " \\" if index + 1 < len(saved) else ""
        facade.append(f"    _({item['code']}, {item['section']}){suffix}")
    facade.extend(["", "#define PERSISTENT_MET_LOCATION_BINDINGS(_) \\"])
    met = ledger["locationCodecs"]["met"]
    for index, item in enumerate(met):
        suffix = " \\" if index + 1 < len(met) else ""
        facade.append(f"    _({item['code']}, {item['section']}){suffix}")
    facade.append("")
    outputs[Path("src/data/persistence/location_codecs.inc.c")] = "\n".join(facade).encode()

    bindings = ["#ifndef GUARD_CONSTANTS_PERSISTENT_BINDINGS_H",
                "#define GUARD_CONSTANTS_PERSISTENT_BINDINGS_H", "",
                "/* Generated ledger facades; public names remain source-compatible. */"]
    for item in entries:
        domain = re.sub(r"(?<!^)(?=[A-Z])", "_", item["domain"]).upper()
        bindings.append(f"#define PERSISTENT_{domain}_{item['symbol']} {item['value']}")
    bindings.extend(["", "#endif // GUARD_CONSTANTS_PERSISTENT_BINDINGS_H", ""])
    outputs[Path("include/constants/persistent_bindings.h")] = "\n".join(bindings).encode()

    # These overlays are included at the end of the corresponding public
    # constants headers.  Undefining the legacy spelling before mapping it to
    # the ledger facade makes the generated value the compiler-visible
    # authority without breaking any existing public name.
    def defined_symbols(paths: str | tuple[str, ...], prefix: str) -> set[str]:
        if isinstance(paths, str):
            paths = (paths,)
        result: set[str] = set()
        for path in paths:
            result.update(re.findall(rf"^#define\s+({prefix}[A-Za-z0-9_]+)\b",
                                     Path(path).read_text(encoding="utf-8"), re.MULTILINE))
        return result

    facade_specs = {
        "persistent_flags.inc.h": ("flags", defined_symbols("include/constants/flags.h", "FLAG_")),
        "persistent_vars.inc.h": ("vars", defined_symbols(("include/constants/vars.h",
                                                             "include/constants/vars_frlg.h",
                                                             "include/config/item.h"), "VAR_")),
        "persistent_game_stats.inc.h": ("gameStats", defined_symbols("include/constants/game_stat.h", "GAME_STAT_")),
        "persistent_maps.inc.h": ("checkpoints", defined_symbols("include/constants/maps.h", "WARP_ID_")),
        "persistent_facilities.inc.h": ("facilities", defined_symbols("include/constants/battle_frontier.h", "(?:FRONTIER_FACILITY_|FACILITY_BATTLE_)")),
        "persistent_opponents.inc.h": ("trainerIds", defined_symbols("include/constants/opponents.h", "TRAINER_")),
        "persistent_trainer_special.inc.h": ("trainerIds", defined_symbols("include/constants/trainers.h", "TRAINER_")),
        "persistent_trainer_hill.inc.h": ("facilities", defined_symbols("include/constants/trainer_hill.h", "HILL_MODE_")),
    }
    public_facades = {
        filename: [item for item in entries
                   if item["domain"] == domain and item["symbol"] in symbols]
        for filename, (domain, symbols) in facade_specs.items()
    }
    public_facades.update({
        "persistent_locations.inc.h": [item for item in entries
                                       if item["domain"] in {"savedLocations", "metLocations"}],
    })
    for filename, selected in public_facades.items():
        lines = ["/* Generated public bindings; do not edit. */",
                 '#include "constants/persistent_bindings.h"', ""]
        for item in sorted(selected, key=lambda entry: entry["symbol"]):
            domain = re.sub(r"(?<!^)(?=[A-Z])", "_", item["domain"]).upper()
            lines.extend((f"#undef {item['symbol']}",
                          f"#define {item['symbol']} PERSISTENT_{domain}_{item['symbol']}"))
        lines.append("")
        outputs[Path("include/constants") / filename] = "\n".join(lines).encode()

    # Render the complete output set off-tree, then promote each finished file.
    # Combined with make's grouped target, a missing sibling always regenerates
    # the whole deterministic set and no consumer can observe a partial file.
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="persistent-ids-", dir=output_root) as tmp:
        staging = Path(tmp)
        for relative, content in outputs.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        for relative in outputs:
            destination = output_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            (staging / relative).replace(destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("seed", "validate", "generate"))
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--sources", type=Path, default=SOURCES_PATH)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args(argv)
    try:
        repo = Path.cwd()
        contract = load_json(args.contract)
        sources = load_json(args.sources)
        if args.command == "seed":
            ledger = seed_ledger(contract, sources, repo)
            validate_ledger(ledger, contract, sources, repo)
            write_json(args.ledger, ledger)
            print(f"PASS: seeded {len(ledger['entries'])} explicit persistent bindings")
        else:
            ledger = load_json(args.ledger)
            validate_ledger(ledger, contract, sources, repo)
            if args.command == "generate":
                if args.output_root is None:
                    raise ContractError("--output-root is required for generate")
                render(ledger, sources, args.output_root)
                print(f"PASS: generated persistent-ID bindings under {args.output_root}")
            else:
                print(f"PASS: {args.ledger}")
        return 0
    except (ContractError, OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
