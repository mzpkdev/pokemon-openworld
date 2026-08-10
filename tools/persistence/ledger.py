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
import subprocess
import sys
import tempfile
from typing import Any

from tools.persistence.contract import ContractError, load_json, write_json

SCHEMA_VERSION = 1
LEDGER_PATH = Path("src/data/persistence/persistent_ids.json")
SOURCES_PATH = Path("tools/persistence/persistent_sources.json")
CONTRACT_PATH = Path("tools/integrity/save_contract.json")
PUBLISHED_ALLOCATIONS_PATH = Path("tools/persistence/published_allocations.json")


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
    matches = [
        key for key, value in sources.items() if value.get("contractDomain") == domain
    ]
    if len(matches) != 1:
        raise ContractError(
            f"published domain {domain}: expected exactly one allocated source"
        )
    return matches[0]


def _entry(
    domain: str,
    symbol: str,
    value: int,
    storage: str,
    state: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    return {
        "alias": None,
        "domain": domain,
        "source": source,
        "state": state,
        "storage": storage,
        "symbol": symbol,
        "value": value,
    }


def seed_ledger(
    contract: dict[str, Any], sources: dict[str, Any], repo: Path
) -> dict[str, Any]:
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
            if (
                domain == "trainerIds"
                and 0 <= value < sources["trainerDefeat"]["count"]
            ):
                state = {
                    "kind": "trainer-defeat-flag",
                    "value": sources["trainerDefeat"]["flagBase"] + value,
                }
            entries.append(
                _entry(domain, binding["symbol"], value, storage, state, source_id)
            )

    # Heal-location IDs used to be derived from JSON array position.  Seed their
    # current values once so subsequent source reordering cannot move a save ID.
    heal_source = source_by_id["heal-locations"]
    heal_data = load_json(repo / heal_source["path"])
    entries.append(
        _entry(
            "checkpoints",
            "HEAL_LOCATION_NONE",
            0,
            heal_source["storage"],
            {"kind": "allocated-binding"},
            "heal-locations",
        )
    )
    for value, record in enumerate(heal_data["heal_locations"], 1):
        entries.append(
            _entry(
                "checkpoints",
                record["id"],
                value,
                heal_source["storage"],
                {"kind": "allocated-binding"},
                "heal-locations",
            )
        )
    for allocation in sources.get("explicitAllocations", []):
        source = source_by_id[allocation["source"]]
        entries.append(
            _entry(
                allocation["domain"],
                allocation["symbol"],
                allocation["value"],
                source["storage"],
                {"kind": "allocated-binding"},
                allocation["source"],
            )
        )

    entries.sort(
        key=lambda item: (
            item["domain"],
            item["storage"],
            item["value"],
            item["symbol"],
        )
    )
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
        "locationCodecs": _read_location_codecs(
            repo / sources["locationCodecs"]["path"]
        ),
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
            saved[code] = {
                "code": code,
                "section": saved_symbol,
                "sectionValue": values[saved_symbol],
            }
        met_code = item.get("met_location")
        met_symbol = item.get("met_location_display")
        if met_code is not None and met_symbol is not None:
            record = {
                "code": met_code,
                "section": met_symbol,
                "sectionValue": values[met_symbol],
            }
            if met[met_code]["section"] not in ("MAPSEC_INVALID", met_symbol):
                raise ContractError(
                    f"met-location code {met_code}: conflicting canonical sections"
                )
            met[met_code] = record
    return {"met": met, "saved": saved}


def _published_allocation_entries(
    publication: dict[str, Any], pointer: str = "$"
) -> list[dict[str, Any]]:
    if not isinstance(publication, dict) or set(publication) != {
        "baselineCommit",
        "entries",
        "schemaVersion",
    }:
        raise ContractError(f"{pointer}: invalid published allocation keys")
    if publication["schemaVersion"] != 1:
        raise ContractError(f"{pointer}.schemaVersion: unsupported")
    baseline = publication["baselineCommit"]
    if not isinstance(baseline, str) or not re.fullmatch(r"[0-9a-f]{40}", baseline):
        raise ContractError(f"{pointer}.baselineCommit: expected full commit SHA")
    entries = publication["entries"]
    if not isinstance(entries, list) or not entries:
        raise ContractError(f"{pointer}.entries: expected a nonempty list")
    required = {"domain", "source", "storage", "symbol", "value"}
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(entries):
        path = f"{pointer}.entries[{index}]"
        if not isinstance(item, dict) or set(item) != required:
            raise ContractError(f"{path}: invalid published allocation fields")
        for field in ("domain", "source", "storage"):
            value = item[field]
            if not isinstance(value, str) or not value or value.strip() != value:
                raise ContractError(f"{path}.{field}: expected a nonempty string")
        symbol = item["symbol"]
        if not isinstance(symbol, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", symbol
        ):
            raise ContractError(f"{path}.symbol: invalid C symbol")
        if isinstance(item["value"], bool) or not isinstance(item["value"], int):
            raise ContractError(f"{path}.value: expected integer")
        identity = (item["domain"], symbol)
        if identity in seen:
            raise ContractError(f"{path}: duplicate published allocation {identity}")
        seen.add(identity)
    return entries


def _allocated_projection(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = ("domain", "source", "storage", "symbol", "value")
    return [
        {field: item[field] for field in fields}
        for item in entries
        if item["state"]["kind"] == "allocated-binding"
    ]


def validate_published_allocations(
    entries: list[dict[str, Any]], publication: dict[str, Any]
) -> None:
    """Bind every durable allocation to the checked publication baseline."""
    published_entries = _published_allocation_entries(publication)
    published = {(item["domain"], item["symbol"]): item for item in published_entries}
    actual_entries = _allocated_projection(entries)
    actual = {(item["domain"], item["symbol"]): item for item in actual_entries}
    if actual != published:
        missing = sorted(set(published) - set(actual))[:5]
        extra = sorted(set(actual) - set(published))[:5]
        changed = sorted(
            identity
            for identity in set(actual) & set(published)
            if actual[identity] != published[identity]
        )[:5]
        raise ContractError(
            "published allocations moved/deleted/unreviewed "
            f"(missing={missing}, extra={extra}, changed={changed})"
        )


def validate_published_allocation_history(
    publication: dict[str, Any], previous: dict[str, Any]
) -> None:
    """Require allocation publication history to grow by exact append only."""
    current_entries = _published_allocation_entries(publication)
    previous_entries = _published_allocation_entries(previous, "$previous")
    if publication["baselineCommit"] != previous["baselineCommit"]:
        raise ContractError("$.baselineCommit: published allocation baseline changed")
    if len(current_entries) < len(previous_entries):
        raise ContractError("$.entries: published allocation history was truncated")
    for index, prior in enumerate(previous_entries):
        if current_entries[index] != prior:
            raise ContractError(
                f"$.entries[{index}]: published allocation history changed"
            )
    occupied = {(item["domain"], item["value"]) for item in previous_entries}
    for index, item in enumerate(
        current_entries[len(previous_entries) :], len(previous_entries)
    ):
        slot = (item["domain"], item["value"])
        if slot in occupied:
            raise ContractError(
                f"$.entries[{index}].value: reuses published allocation {slot}"
            )
        occupied.add(slot)


def load_published_allocation_baseline(
    repo: Path,
    publication: dict[str, Any],
    publication_path: Path,
    *,
    baseline_path: Path | None = None,
    baseline_ref: str | None = None,
    required: bool = False,
    allow_bootstrap: bool = False,
) -> dict[str, Any] | None:
    _published_allocation_entries(publication)
    if baseline_path is not None and baseline_ref is not None:
        raise ContractError("choose one published allocation baseline path or ref")
    if baseline_path is not None:
        try:
            return load_json(baseline_path)
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(
                f"published allocation baseline is unavailable: {baseline_path}"
            ) from exc
    if baseline_ref is None:
        if required:
            raise ContractError("published allocation history baseline is required")
        return None
    if not isinstance(baseline_ref, str) or not baseline_ref.strip():
        raise ContractError("published allocation baseline ref is empty")
    revision = subprocess.run(
        ("git", "rev-parse", "--verify", f"{baseline_ref}^{{commit}}"),
        cwd=repo,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if revision.returncode != 0:
        raise ContractError(
            f"published allocation baseline ref is unavailable: {baseline_ref}"
        )
    try:
        relative = publication_path.resolve().relative_to(repo.resolve())
    except ValueError as exc:
        raise ContractError(
            "published allocation file must be inside the repository"
        ) from exc
    revision_sha = revision.stdout.strip()
    tree_entry = subprocess.run(
        ("git", "ls-tree", "--name-only", revision_sha, "--", relative.as_posix()),
        cwd=repo,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if tree_entry.returncode != 0:
        raise ContractError(
            f"cannot read published allocation baseline at {baseline_ref}"
        )
    baseline_exists = tree_entry.stdout.strip() == relative.as_posix()
    if not baseline_exists and not allow_bootstrap:
        raise ContractError(
            f"published allocation baseline is unavailable at {baseline_ref}"
        )
    if not baseline_exists:
        bootstrap = publication.get("baselineCommit")
        for ancestor, descendant, message in (
            (bootstrap, "HEAD", "bootstrap commit is not in current history"),
            (
                bootstrap,
                revision_sha,
                "bootstrap commit is already in baseline history",
            ),
        ):
            check = subprocess.run(
                ("git", "merge-base", "--is-ancestor", str(ancestor), descendant),
                cwd=repo,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            is_ancestor = check.returncode == 0
            if descendant == "HEAD" and not is_ancestor:
                raise ContractError(message)
            if descendant == revision_sha and is_ancestor:
                raise ContractError(message)
            if check.returncode not in {0, 1}:
                raise ContractError("cannot authenticate allocation bootstrap history")
        bootstrap_ledger = subprocess.run(
            ("git", "show", f"{bootstrap}:{LEDGER_PATH.as_posix()}"),
            cwd=repo,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if bootstrap_ledger.returncode != 0:
            raise ContractError("allocation bootstrap commit has no persistent ledger")
        try:
            ledger_document = json.loads(bootstrap_ledger.stdout)
        except json.JSONDecodeError as exc:
            raise ContractError("allocation bootstrap ledger is invalid JSON") from exc
        if not isinstance(ledger_document, dict) or not isinstance(
            ledger_document.get("entries"), list
        ):
            raise ContractError("allocation bootstrap ledger has no entries")
        validate_published_allocations(ledger_document["entries"], publication)
        return None
    result = subprocess.run(
        ("git", "show", f"{revision_sha}:{relative.as_posix()}"),
        cwd=repo,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise ContractError(
            f"cannot read published allocation baseline at {baseline_ref}"
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError(
            "published allocation history baseline is invalid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ContractError("published allocation history baseline is not an object")
    return value


def validate_ledger(
    ledger: dict[str, Any],
    contract: dict[str, Any],
    sources: dict[str, Any],
    published_allocations: dict[str, Any],
    repo: Path,
) -> None:
    if ledger.get("schemaVersion") != SCHEMA_VERSION:
        raise ContractError("$.schemaVersion: unsupported")
    if ledger.get("baselineCommit") != contract.get("baselineCommit"):
        raise ContractError(
            "$.baselineCommit: ledger is not based on the frozen contract"
        )
    entries = ledger.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ContractError("$.entries: expected a nonempty list")
    source_by_id = _source_index(sources)
    storage_by_id = _storage_index(sources)
    allocated_domains = {
        allocation["domain"] for allocation in sources.get("explicitAllocations", [])
    }
    allowed_domains = (
        set(contract["publishedBindings"]) | {"checkpoints"} | allocated_domains
    )
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
        if not isinstance(symbol, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", symbol
        ):
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
        if (
            sentinel is not None
            and value == sentinel
            and symbol not in storage.get("sentinelSymbols", [])
        ):
            raise ContractError(f"{path}.value: sentinel collision")
        state = item["state"]
        if not isinstance(state, dict) or state.get("kind") not in {
            "published-binding",
            "allocated-binding",
            "trainer-defeat-flag",
            "trainer-defeat-variable-bit",
        }:
            raise ContractError(f"{path}.state: invalid state ownership")
        expected_state_fields = {
            "published-binding": {"kind"},
            "allocated-binding": {"kind"},
            "trainer-defeat-flag": {"kind", "value"},
            "trainer-defeat-variable-bit": {"bit", "kind", "value"},
        }[state["kind"]]
        if set(state) != expected_state_fields:
            raise ContractError(f"{path}.state: malformed trainer defeat binding")
        if state["kind"].startswith("trainer-defeat-") and domain != "trainerIds":
            raise ContractError(
                f"{path}.state: trainer defeat binding outside trainerIds"
            )
        by_key[(domain, item["storage"], value)].append(item)
        by_symbol[(domain, item["storage"], symbol)] = item

    for key, group in by_key.items():
        owners = [item for item in group if item["alias"] is None]
        if len(owners) != 1:
            raise ContractError(
                f"duplicate value {key}: expected exactly one canonical owner"
            )
        owner = owners[0]
        for item in group:
            alias = item["alias"]
            if item is owner:
                continue
            if not isinstance(alias, dict) or set(alias) != {"of", "owner"}:
                raise ContractError(
                    f"{item['symbol']}: duplicate value without an authorized alias"
                )
            if alias["of"] != owner["symbol"] or alias["owner"] != item["source"]:
                raise ContractError(f"{item['symbol']}: unauthorized alias")
            if alias["owner"] not in source_by_id:
                raise ContractError(f"{item['symbol']}: unallocated alias owner")

    _trainer_bindings(entries, sources["trainerDefeat"])
    validate_frozen_bindings(entries, contract)
    validate_published_allocations(entries, published_allocations)

    for source_id, source in source_by_id.items():
        if source.get("kind") == "json-symbol-list":
            data = load_json(repo / source["path"])
            allocated = {
                item["symbol"] for item in entries if item["source"] == source_id
            }
            referenced = {source["noneSymbol"]} | {
                item[source["symbolField"]] for item in data[source["listKey"]]
            }
            if allocated != referenced:
                raise ContractError(
                    f"source {source_id}: unallocated source references"
                )
        elif source.get("kind") == "explicit-source":
            text = (repo / source["path"]).read_text(encoding="utf-8")
            allocated = {
                item["symbol"]: item["value"]
                for item in entries
                if item["source"] == source_id
            }
            for symbol, value in allocated.items():
                match = re.search(
                    rf"^#define\s+{re.escape(symbol)}\s+([^/\s]+)", text, re.MULTILINE
                )
                if match is None or int(match.group(1), 0) != value:
                    raise ContractError(
                        f"source {source_id}: moved/deleted binding {symbol}"
                    )
    validate_location_codecs(ledger.get("locationCodecs"), sources, repo)
    validate_consumer_references(entries, sources.get("consumerSchemas"), repo)


def validate_location_codecs(codecs: Any, sources: dict[str, Any], repo: Path) -> None:
    expected = _read_location_codecs(repo / sources["locationCodecs"]["path"])
    if codecs != expected:
        raise ContractError(
            "$.locationCodecs: moved/deleted/unallocated saved or met location binding"
        )


def validate_consumer_references(
    entries: list[dict[str, Any]], schemas: Any, repo: Path
) -> None:
    if not isinstance(schemas, list):
        raise ContractError("$.consumerSchemas: expected list")
    domains = {item["domain"] for item in entries}
    if {schema.get("domain") for schema in schemas} != domains:
        raise ContractError(
            "$.consumerSchemas: every persisted domain needs exactly one schema"
        )
    allocated = {(item["domain"], item["symbol"]) for item in entries}
    for schema in schemas:
        domain = schema["domain"]
        paths = schema.get("paths")
        patterns = schema.get("patterns")
        if (
            not isinstance(paths, list)
            or not paths
            or not isinstance(patterns, list)
            or not patterns
        ):
            raise ContractError(
                f"consumer schema {domain}: paths/patterns must be nonempty"
            )
        for glob in paths:
            for path in repo.glob(glob):
                if not path.is_file() or any(
                    part in {"build", ".references", ".git"} for part in path.parts
                ):
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                for pattern in patterns:
                    for match in re.finditer(pattern, text, re.MULTILINE):
                        symbol = match.group("symbol")
                        if (domain, symbol) not in allocated:
                            raise ContractError(
                                f"{path}: unallocated {domain} consumer reference {symbol}"
                            )
        script = schema.get("scriptTokens")
        if script is not None:
            script_paths = script.get("paths")
            prefixes = script.get("prefixes")
            excluded = set(script.get("exclude", []))
            excluded_prefixes = tuple(script.get("excludePrefixes", []))
            opcodes = set(script.get("opcodes", []))
            opcode_prefixes = tuple(script.get("opcodePrefixes", []))
            if (
                not isinstance(script_paths, list)
                or not script_paths
                or not isinstance(prefixes, list)
                or not prefixes
            ):
                raise ContractError(
                    f"consumer schema {domain}: invalid script token inventory"
                )
            token_re = re.compile(
                r"\b(?:"
                + "|".join(re.escape(prefix) for prefix in prefixes)
                + r")[A-Za-z0-9_]+\b"
            )
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
                            if opcode not in opcodes and not opcode.startswith(
                                opcode_prefixes
                            ):
                                continue
                        lines.append(line)
                    executable = "\n".join(lines)
                    for symbol in token_re.findall(executable):
                        if symbol in excluded or symbol.startswith(excluded_prefixes):
                            continue
                        if (domain, symbol) not in allocated:
                            raise ContractError(
                                f"{path}: unallocated {domain} script reference {symbol}"
                            )


def validate_frozen_bindings(
    entries: list[dict[str, Any]], contract: dict[str, Any]
) -> None:
    """Reject any deletion, addition, or move in the published baseline projection."""
    published = {
        (item["domain"], item["symbol"]): item["value"]
        for item in entries
        if item["state"]["kind"] in {"published-binding", "trainer-defeat-flag"}
    }
    frozen = {
        (domain, item["symbol"]): item["value"]
        for domain, bindings in contract["publishedBindings"].items()
        for item in bindings
    }
    if published != frozen:
        missing = sorted(set(frozen) - set(published))[:5]
        extra = sorted(set(published) - set(frozen))[:5]
        moved = sorted(
            key for key in set(frozen) & set(published) if frozen[key] != published[key]
        )[:5]
        raise ContractError(
            f"published bindings moved/deleted (missing={missing}, extra={extra}, moved={moved})"
        )


def _validate_trainer_storage_policy(policy: Any) -> None:
    if not isinstance(policy, dict) or set(policy) != {
        "count",
        "flagBase",
        "flagStorage",
        "publishedCount",
        "variableBitStorage",
    }:
        raise ContractError("$.trainerDefeat: malformed storage policy")
    if not all(
        isinstance(policy[key], int) for key in ("count", "flagBase", "publishedCount")
    ):
        raise ContractError("$.trainerDefeat: count/base values must be integers")
    flag = policy["flagStorage"]
    if not isinstance(flag, dict) or set(flag) != {
        "daily",
        "debugReserved",
        "persistent",
        "special",
        "transient",
    }:
        raise ContractError("$.trainerDefeat.flagStorage: malformed policy")
    variable = policy["variableBitStorage"]
    if not isinstance(variable, dict) or set(variable) != {
        "bitCount",
        "daily",
        "debugReserved",
        "persistent",
        "special",
        "transient",
    }:
        raise ContractError("$.trainerDefeat.variableBitStorage: malformed policy")


def _in_range(value: int, bounds: Any) -> bool:
    return (
        isinstance(bounds, list)
        and len(bounds) == 2
        and all(isinstance(item, int) for item in bounds)
        and bounds[0] <= value <= bounds[1]
    )


def _validate_trainer_binding(
    trainer_id: int, state: dict[str, Any], policy: dict[str, Any]
) -> tuple[str, int, int]:
    kind = state["kind"]
    value = state["value"]
    if not isinstance(value, int):
        raise ContractError(f"trainer {trainer_id}: binding value must be an integer")
    if kind == "trainer-defeat-flag":
        config = policy["flagStorage"]
        if _in_range(value, config["transient"]):
            raise ContractError(f"trainer {trainer_id}: transient flag binding")
        if _in_range(value, config["daily"]):
            raise ContractError(f"trainer {trainer_id}: daily flag binding")
        if _in_range(value, config["special"]):
            raise ContractError(f"trainer {trainer_id}: special flag binding")
        if value in config["debugReserved"]:
            raise ContractError(f"trainer {trainer_id}: debug-reserved flag binding")
        if not _in_range(value, config["persistent"]):
            raise ContractError(f"trainer {trainer_id}: out-of-range flag binding")
        return ("flag", value, 0)

    config = policy["variableBitStorage"]
    bit = state["bit"]
    if not isinstance(bit, int) or not 0 <= bit < config["bitCount"]:
        raise ContractError(f"trainer {trainer_id}: out-of-range variable bit")
    if _in_range(value, config["transient"]):
        raise ContractError(f"trainer {trainer_id}: transient variable binding")
    if value in config["daily"]:
        raise ContractError(f"trainer {trainer_id}: daily variable binding")
    if _in_range(value, config["special"]):
        raise ContractError(f"trainer {trainer_id}: special variable binding")
    if _in_range(value, config["debugReserved"]):
        raise ContractError(f"trainer {trainer_id}: debug-reserved variable binding")
    if not _in_range(value, config["persistent"]):
        raise ContractError(f"trainer {trainer_id}: out-of-range variable binding")
    return ("variable-bit", value, bit)


def _trainer_bindings(
    entries: list[dict[str, Any]], policy: dict[str, Any]
) -> list[tuple[str, int, int]]:
    _validate_trainer_storage_policy(policy)
    count = policy["count"]
    values: dict[int, tuple[str, int, int]] = {}
    for item in entries:
        state = item["state"]
        if item["domain"] == "trainerIds" and state["kind"] in {
            "trainer-defeat-flag",
            "trainer-defeat-variable-bit",
        }:
            trainer_id = item["value"]
            if not isinstance(trainer_id, int) or not 0 <= trainer_id < count:
                raise ContractError(
                    f"trainer defeat binding ID out of range: {trainer_id}"
                )
            binding = _validate_trainer_binding(trainer_id, state, policy)
            previous = values.setdefault(trainer_id, binding)
            if previous != binding:
                raise ContractError(
                    f"trainer {trainer_id}: conflicting defeat bindings"
                )
    if set(values) != set(range(count)):
        missing = sorted(set(range(count)) - set(values))[:10]
        raise ContractError(f"trainer defeat table is incomplete: {missing}")

    physical_owners: dict[tuple[str, int, int], int] = {}
    for trainer_id, binding in values.items():
        previous = physical_owners.setdefault(binding, trainer_id)
        if previous != trainer_id:
            raise ContractError(
                f"trainer {trainer_id}: duplicate physical defeat binding owned by trainer {previous}"
            )

    external_owners = _external_trainer_storage_owners(entries)
    for trainer_id, (kind, value, _bit) in values.items():
        owner = external_owners[kind].get(value)
        if owner is not None:
            raise ContractError(
                f"trainer {trainer_id}: {kind} binding collides with published owner {owner}"
            )

    published_count = policy["publishedCount"]
    flag_base = policy["flagBase"]
    for trainer_id in range(published_count):
        expected = ("flag", flag_base + trainer_id, 0)
        if values.get(trainer_id) != expected:
            raise ContractError(f"trainer {trainer_id}: published defeat binding moved")
    return [values[index] for index in range(count)]


def _external_trainer_storage_owners(
    entries: list[dict[str, Any]],
) -> dict[str, dict[int, str]]:
    """Index current published physical owners outside trainer defeat storage.

    Phase 2 can extend this boundary with its reviewed semantic reference
    inventory. Until then, every flag identity and whole-variable identity in
    the existing ledger is conservatively treated as owning its physical state.
    """
    owners: dict[str, dict[int, str]] = {"flag": {}, "variable-bit": {}}
    for item in entries:
        if item["domain"] == "trainerIds":
            continue
        if item["storage"] == "flag-id":
            owners["flag"].setdefault(item["value"], item["symbol"])
        elif item["domain"] == "vars":
            owners["variable-bit"].setdefault(item["value"], item["symbol"])
    return owners


def render(ledger: dict[str, Any], sources: dict[str, Any], output_root: Path) -> None:
    entries = ledger["entries"]
    bindings = _trainer_bindings(entries, sources["trainerDefeat"])
    table = [
        "/* Generated from persistent_ids.json; do not edit. */",
        "const u16 gTrainerDefeatFlagById[PERSISTENT_TRAINER_COUNT] =",
        "{",
    ]
    table.extend(
        f"    [{index}] = 0x{binding[1]:04X},"
        if binding[0] == "flag"
        else f"    [{index}] = 0xFFFF,"
        for index, binding in enumerate(bindings)
    )
    table.extend(["};", ""])
    outputs: dict[Path, bytes] = {}
    table_path = Path("src/data/persistence/trainer_defeat_flags.inc.c")
    outputs[table_path] = "\n".join(table).encode()

    typed_table = [
        "/* Generated from persistent_ids.json; do not edit. */",
        "const struct TrainerDefeatBinding gTrainerDefeatBindingById[PERSISTENT_TRAINER_COUNT] =",
        "{",
    ]
    for index, (kind, value, bit) in enumerate(bindings):
        storage = (
            "TRAINER_DEFEAT_STORAGE_FLAG"
            if kind == "flag"
            else "TRAINER_DEFEAT_STORAGE_VARIABLE_BIT"
        )
        typed_table.append(
            f"    [{index}] = {{.id = 0x{value:04X}, .storage = {storage}, .bit = {bit}}},"
        )
    typed_table.extend(["};", ""])
    outputs[Path("src/data/persistence/trainer_defeat_bindings.inc.c")] = "\n".join(
        typed_table
    ).encode()

    heal = [item for item in entries if item["source"] == "heal-locations"]
    heal.sort(key=lambda item: item["value"])
    header = [
        "#ifndef GUARD_CONSTANTS_HEAL_LOCATIONS_H",
        "#define GUARD_CONSTANTS_HEAL_LOCATIONS_H",
        "",
        "/* Generated from persistent_ids.json; safe for C and assembler. */",
    ]
    header.extend(f"#define {item['symbol']} {item['value']}" for item in heal)
    header.extend(
        [
            f"#define NUM_HEAL_LOCATIONS {max(item['value'] for item in heal) + 1}",
            "",
            "#endif // GUARD_CONSTANTS_HEAL_LOCATIONS_H",
            "",
        ]
    )
    header_path = Path("include/constants/heal_locations.h")
    outputs[header_path] = "\n".join(header).encode()

    facade = [
        "/* Generated from persistent_ids.json; do not edit. */",
        "#define PERSISTENT_SAVED_LOCATION_BINDINGS(_) \\",
    ]
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
    outputs[Path("src/data/persistence/location_codecs.inc.c")] = "\n".join(
        facade
    ).encode()

    bindings = [
        "#ifndef GUARD_CONSTANTS_PERSISTENT_BINDINGS_H",
        "#define GUARD_CONSTANTS_PERSISTENT_BINDINGS_H",
        "",
        "/* Generated ledger facades; public names remain source-compatible. */",
    ]
    for item in entries:
        domain = re.sub(r"(?<!^)(?=[A-Z])", "_", item["domain"]).upper()
        bindings.append(f"#define PERSISTENT_{domain}_{item['symbol']} {item['value']}")
    bindings.extend(["", "#endif // GUARD_CONSTANTS_PERSISTENT_BINDINGS_H", ""])
    outputs[Path("include/constants/persistent_bindings.h")] = "\n".join(
        bindings
    ).encode()

    # These overlays are included at the end of the corresponding public
    # constants headers.  Undefining the legacy spelling before mapping it to
    # the ledger facade makes the generated value the compiler-visible
    # authority without breaking any existing public name.
    def defined_symbols(paths: str | tuple[str, ...], prefix: str) -> set[str]:
        if isinstance(paths, str):
            paths = (paths,)
        result: set[str] = set()
        for path in paths:
            result.update(
                re.findall(
                    rf"^#define\s+({prefix}[A-Za-z0-9_]+)\b",
                    Path(path).read_text(encoding="utf-8"),
                    re.MULTILINE,
                )
            )
        return result

    facade_specs = {
        "persistent_flags.inc.h": (
            "flags",
            defined_symbols("include/constants/flags.h", "FLAG_"),
        ),
        "persistent_vars.inc.h": (
            "vars",
            defined_symbols(
                (
                    "include/constants/vars.h",
                    "include/constants/vars_frlg.h",
                    "include/config/item.h",
                ),
                "VAR_",
            ),
        ),
        "persistent_game_stats.inc.h": (
            "gameStats",
            defined_symbols("include/constants/game_stat.h", "GAME_STAT_"),
        ),
        "persistent_maps.inc.h": (
            "checkpoints",
            defined_symbols("include/constants/maps.h", "WARP_ID_"),
        ),
        "persistent_facilities.inc.h": (
            "facilities",
            defined_symbols(
                "include/constants/battle_frontier.h",
                "(?:FRONTIER_FACILITY_|FACILITY_BATTLE_)",
            ),
        ),
        "persistent_opponents.inc.h": (
            "trainerIds",
            defined_symbols("include/constants/opponents.h", "TRAINER_"),
        ),
        "persistent_trainer_special.inc.h": (
            "trainerIds",
            defined_symbols("include/constants/trainers.h", "TRAINER_"),
        ),
        "persistent_trainer_hill.inc.h": (
            "facilities",
            defined_symbols("include/constants/trainer_hill.h", "HILL_MODE_"),
        ),
    }
    public_facades = {
        filename: [
            item
            for item in entries
            if item["domain"] == domain and item["symbol"] in symbols
        ]
        for filename, (domain, symbols) in facade_specs.items()
    }
    public_facades.update(
        {
            "persistent_locations.inc.h": [
                item
                for item in entries
                if item["domain"] in {"savedLocations", "metLocations"}
            ],
        }
    )
    for filename, selected in public_facades.items():
        lines = [
            "/* Generated public bindings; do not edit. */",
            '#include "constants/persistent_bindings.h"',
            "",
        ]
        for item in sorted(selected, key=lambda entry: entry["symbol"]):
            domain = re.sub(r"(?<!^)(?=[A-Z])", "_", item["domain"]).upper()
            lines.extend(
                (
                    f"#undef {item['symbol']}",
                    f"#define {item['symbol']} PERSISTENT_{domain}_{item['symbol']}",
                )
            )
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
    parser.add_argument(
        "--published-allocations", type=Path, default=PUBLISHED_ALLOCATIONS_PATH
    )
    baseline = parser.add_mutually_exclusive_group()
    baseline.add_argument("--published-baseline", type=Path)
    baseline.add_argument("--published-baseline-ref")
    parser.add_argument("--require-published-baseline", action="store_true")
    parser.add_argument("--allow-published-baseline-bootstrap", action="store_true")
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args(argv)
    try:
        repo = Path.cwd()
        contract = load_json(args.contract)
        sources = load_json(args.sources)
        published_allocations = load_json(args.published_allocations)
        published_baseline = load_published_allocation_baseline(
            repo,
            published_allocations,
            args.published_allocations,
            baseline_path=args.published_baseline,
            baseline_ref=args.published_baseline_ref,
            required=args.require_published_baseline,
            allow_bootstrap=args.allow_published_baseline_bootstrap,
        )
        if published_baseline is not None:
            validate_published_allocation_history(
                published_allocations, published_baseline
            )
        if args.command == "seed":
            ledger = seed_ledger(contract, sources, repo)
            validate_ledger(ledger, contract, sources, published_allocations, repo)
            write_json(args.ledger, ledger)
            print(f"PASS: seeded {len(ledger['entries'])} explicit persistent bindings")
        else:
            ledger = load_json(args.ledger)
            validate_ledger(ledger, contract, sources, published_allocations, repo)
            if args.command == "generate":
                if args.output_root is None:
                    raise ContractError("--output-root is required for generate")
                render(ledger, sources, args.output_root)
                print(
                    f"PASS: generated persistent-ID bindings under {args.output_root}"
                )
            else:
                print(f"PASS: {args.ledger}")
        return 0
    except (ContractError, OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
