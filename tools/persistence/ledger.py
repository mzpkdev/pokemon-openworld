#!/usr/bin/env python3
"""Seed, validate, and render the persistent-ID ledger.

The frozen save contract is evidence.  The ledger is the reviewed runtime
authority: generation never discovers new numeric assignments from C source.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import errno
import json
from collections import defaultdict
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from tools.persistence.contract import ContractError, load_json, write_json
from tools.persistence.historical_flags import inspect_historical_flags

SCHEMA_VERSION = 1
LEDGER_PATH = Path("src/data/persistence/persistent_ids.json")
SOURCES_PATH = Path("tools/persistence/persistent_sources.json")
CONTRACT_PATH = Path("tools/integrity/save_contract.json")
PUBLISHED_ALLOCATIONS_PATH = Path("tools/persistence/published_allocations.json")
RESIDENT_STORY_SELECTOR = re.compile(
    r"\b(?:IS_FRLG|FIRERED|LEAFGREEN|GAME_VERSION|gGameVersion|CURRENT_(?:REGION|CAMPAIGN))\b"
    r"|\bGetCurrentRegion\s*\("
)


@contextmanager
def _windows_byte_lock(
    lock,
    locking,
    *,
    nonblocking_mode: int,
    unlock_mode: int,
    sleep=time.sleep,
):
    """Retry only ordinary Windows byte-lock contention, then unlock once."""
    while True:
        lock.seek(0)
        try:
            locking(lock.fileno(), nonblocking_mode, 1)
            break
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            sleep(0.01)
    try:
        yield
    finally:
        lock.seek(0)
        locking(lock.fileno(), unlock_mode, 1)


@contextmanager
def _generation_lock(output_root: Path):
    """Serialize aggregate publication with mapjson's generation promotion."""
    parent = output_root.parent
    parent.mkdir(parents=True, exist_ok=True)
    lock_path = parent / ".generation.lock"
    if os.name == "nt":
        while True:
            try:
                lock = lock_path.open("a+b")
                break
            except PermissionError:
                time.sleep(0.01)
        if lock_path.stat().st_size == 0:
            lock.write(b"\0")
            lock.flush()
        try:
            with _windows_byte_lock(
                lock,
                msvcrt.locking,
                nonblocking_mode=msvcrt.LK_NBLCK,
                unlock_mode=msvcrt.LK_UNLCK,
            ):
                yield
        finally:
            lock.close()
    else:
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


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
    alias: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "alias": alias,
        "domain": domain,
        "source": source,
        "state": state,
        "storage": storage,
        "symbol": symbol,
        "value": value,
    }


def _trainer_identity_projection(
    contract: dict[str, Any], sources: dict[str, Any], repo: Path
) -> dict[str, list[dict[str, Any]]]:
    """Project frozen FRLG collisions into distinct live runtime identities."""
    config = sources.get("trainerIdentityProjection")
    required = {
        "additional",
        "legacyIdRange",
        "legacyPath",
        "legacySymbolPrefix",
        "liveSource",
        "liveSymbolPrefix",
        "liveValueOffset",
    }
    if not isinstance(config, dict) or set(config) != required:
        raise ContractError("$.trainerIdentityProjection: malformed projection")
    bounds = config["legacyIdRange"]
    if (
        not isinstance(bounds, list)
        or len(bounds) != 2
        or not all(isinstance(value, int) for value in bounds)
        or bounds[0] > bounds[1]
    ):
        raise ContractError("$.trainerIdentityProjection.legacyIdRange: invalid")
    for key in (
        "legacyPath",
        "legacySymbolPrefix",
        "liveSource",
        "liveSymbolPrefix",
    ):
        if not isinstance(config[key], str) or not config[key]:
            raise ContractError(f"$.trainerIdentityProjection.{key}: invalid")
    if not isinstance(config["liveValueOffset"], int):
        raise ContractError("$.trainerIdentityProjection.liveValueOffset: invalid")

    text = (repo / config["legacyPath"]).read_text(encoding="utf-8")
    macros = [
        (symbol, int(value, 0))
        for symbol, value in re.findall(
            r"^#define\s+(TRAINER_[A-Za-z0-9_]+)\s+"
            r"(0[xX][0-9A-Fa-f]+|[0-9]+)\s*(?://[^\r\n]*)?$",
            text,
            re.MULTILINE,
        )
    ]
    legacy_by_value: dict[int, str] = {}
    for symbol, value in macros:
        if (
            symbol.startswith(config["legacySymbolPrefix"])
            and not symbol.startswith(config["liveSymbolPrefix"])
            and bounds[0] <= value <= bounds[1]
        ):
            previous = legacy_by_value.setdefault(value, symbol)
            if previous != symbol:
                raise ContractError(
                    f"trainer tombstone {value}: duplicate symbols {previous}, {symbol}"
                )
    expected_values = set(range(bounds[0], bounds[1] + 1))
    if set(legacy_by_value) != expected_values:
        missing = sorted(expected_values - set(legacy_by_value))[:10]
        raise ContractError(f"trainer tombstone projection is incomplete: {missing}")

    frozen = {
        (item["symbol"], item["value"])
        for item in contract["publishedBindings"]["trainerIds"]
    }
    tombstones = []
    live = []
    for legacy_value in range(bounds[0], bounds[1] + 1):
        legacy_symbol = legacy_by_value[legacy_value]
        if (legacy_symbol, legacy_value) not in frozen:
            raise ContractError(
                f"trainer tombstone is absent from frozen evidence: {legacy_symbol}"
            )
        suffix = legacy_symbol.removeprefix(config["legacySymbolPrefix"])
        live_value = legacy_value + config["liveValueOffset"]
        tombstones.append({"symbol": legacy_symbol, "value": legacy_value})
        live.append(
            {
                "source": config["liveSource"],
                "symbol": config["liveSymbolPrefix"] + suffix,
                "value": live_value,
            }
        )

    additional = config["additional"]
    if not isinstance(additional, list) or not additional:
        raise ContractError("$.trainerIdentityProjection.additional: expected list")
    for index, item in enumerate(additional):
        if not isinstance(item, dict) or set(item) != {"source", "symbol", "value"}:
            raise ContractError(
                f"$.trainerIdentityProjection.additional[{index}]: invalid"
            )
        if (
            not isinstance(item["source"], str)
            or not isinstance(item["symbol"], str)
            or not isinstance(item["value"], int)
        ):
            raise ContractError(
                f"$.trainerIdentityProjection.additional[{index}]: invalid"
            )
        live.append(dict(item))
    return {"live": live, "tombstones": tombstones}


def seed_ledger(
    contract: dict[str, Any], sources: dict[str, Any], repo: Path
) -> dict[str, Any]:
    source_by_id = _source_index(sources)
    storage_by_id = _storage_index(sources)
    regional_fact_symbols = {
        fact["symbol"]
        for source in source_by_id.values()
        if source.get("kind") == "regional-fact-policy"
        for fact in load_json(repo / source["path"]).get("exact", [])
    }
    entries: list[dict[str, Any]] = []
    for domain, bindings in sorted(contract["publishedBindings"].items()):
        source_id = _published_source(domain, source_by_id)
        source = source_by_id[source_id]
        storage = source["storage"]
        if storage not in storage_by_id:
            raise ContractError(f"source {source_id}: unallocated storage {storage}")
        for binding in bindings:
            if domain == "flags" and binding["symbol"] in regional_fact_symbols:
                continue
            value = binding["value"]
            state: dict[str, Any] = {"kind": "published-binding"}
            if (
                domain == "trainerIds"
                and 0 <= value < sources["trainerDefeat"]["publishedCount"]
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

    for source_id, source in source_by_id.items():
        if source.get("kind") != "regional-fact-policy":
            continue
        policy = load_json(repo / source["path"])
        for fact in policy.get("exact", []):
            entries.append(
                _entry(
                    "flags",
                    fact["symbol"],
                    fact["value"],
                    source["storage"],
                    {"kind": "allocated-binding"},
                    source_id,
                    {"of": fact["unusedBinding"], "owner": source_id},
                )
            )

    projection = _trainer_identity_projection(contract, sources, repo)
    tombstone_keys = {
        (item["symbol"], item["value"]) for item in projection["tombstones"]
    }
    projected = set()
    for item in entries:
        key = (item["symbol"], item["value"])
        if item["domain"] == "trainerIds" and key in tombstone_keys:
            item["state"] = {"kind": "published-tombstone"}
            projected.add(key)
    if projected != tombstone_keys:
        missing = sorted(tombstone_keys - projected)[:10]
        raise ContractError(f"frozen trainer tombstones are missing: {missing}")
    source_by_id = _source_index(sources)
    bitmap_first = sources["trainerDefeat"]["bitmapStorage"]["firstTrainerId"]
    for item in projection["live"]:
        source = source_by_id.get(item["source"])
        if source is None:
            raise ContractError(f"trainer identity source is missing: {item['source']}")
        entries.append(
            _entry(
                "trainerIds",
                item["symbol"],
                item["value"],
                source["storage"],
                {
                    "bitIndex": item["value"] - bitmap_first,
                    "kind": "trainer-defeat-bitmap",
                },
                item["source"],
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
        if any(item["source"] == "regional-facts" for item in group):
            owner_item = next(
                item for item in group if item["state"]["kind"] == "published-binding"
            )
        else:
            owner_item = group[0]
        owner_item["alias"] = None
        for item in group:
            if item is not owner_item:
                item["alias"] = {"of": owner_item["symbol"], "owner": item["source"]}

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
    bitmap_required = required | {"physicalBinding"}
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(entries):
        path = f"{pointer}.entries[{index}]"
        if not isinstance(item, dict) or set(item) not in (
            required,
            bitmap_required,
        ):
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
        physical = item.get("physicalBinding")
        if physical is not None:
            if (
                item["domain"] != "trainerIds"
                or not isinstance(physical, dict)
                or set(physical) != {"bitIndex", "kind"}
                or physical.get("kind") != "trainer-defeat-bitmap"
                or isinstance(physical.get("bitIndex"), bool)
                or not isinstance(physical.get("bitIndex"), int)
                or physical["bitIndex"] < 0
            ):
                raise ContractError(f"{path}.physicalBinding: invalid bitmap binding")
        identity = (item["domain"], symbol)
        if identity in seen:
            raise ContractError(f"{path}: duplicate published allocation {identity}")
        seen.add(identity)
    return entries


def _allocated_projection(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = ("domain", "source", "storage", "symbol", "value")
    projection = []
    for item in entries:
        kind = item["state"]["kind"]
        if kind not in {"allocated-binding", "trainer-defeat-bitmap"}:
            continue
        published = {field: item[field] for field in fields}
        if kind == "trainer-defeat-bitmap":
            published["physicalBinding"] = {
                "bitIndex": item["state"]["bitIndex"],
                "kind": kind,
            }
        projection.append(published)
    return projection


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
            "published-tombstone",
            "allocated-binding",
            "trainer-defeat-bitmap",
            "trainer-defeat-flag",
            "trainer-defeat-variable-bit",
        }:
            raise ContractError(f"{path}.state: invalid state ownership")
        expected_state_fields = {
            "published-binding": {"kind"},
            "published-tombstone": {"kind"},
            "allocated-binding": {"kind"},
            "trainer-defeat-bitmap": {"bitIndex", "kind"},
            "trainer-defeat-flag": {"kind", "value"},
            "trainer-defeat-variable-bit": {"bit", "kind", "value"},
        }[state["kind"]]
        if set(state) != expected_state_fields:
            raise ContractError(f"{path}.state: malformed trainer defeat binding")
        if state["kind"].startswith("trainer-defeat-") and domain != "trainerIds":
            raise ContractError(
                f"{path}.state: trainer defeat binding outside trainerIds"
            )
        if state["kind"] == "published-tombstone" and domain != "trainerIds":
            raise ContractError(f"{path}.state: tombstone outside trainerIds")
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

    validate_trainer_identity_projection(entries, contract, sources, repo)
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
    validate_regional_fact_policy(entries, sources, repo)
    validate_regional_variable_policy(entries, sources, repo)
    validate_resident_story_admission(sources, repo)


def validate_regional_fact_policy(
    entries: list[dict[str, Any]], sources: dict[str, Any], repo: Path
) -> None:
    policy_sources = [
        source
        for source in sources.get("sources", [])
        if source.get("kind") == "regional-fact-policy"
    ]
    if len(policy_sources) != 1:
        raise ContractError("regional facts: expected exactly one reviewed policy")
    source = policy_sources[0]
    policy = load_json(repo / source["path"])
    if not isinstance(policy, dict) or set(policy) != {
        "ambiguous",
        "exact",
        "historicalFixtures",
        "schemaVersion",
        "unsupported",
        "unused",
    }:
        raise ContractError("regional facts: malformed reviewed policy")
    if policy["schemaVersion"] != 2:
        raise ContractError("regional facts: unsupported policy schema")

    exact = policy["exact"]
    ambiguous = policy["ambiguous"]
    unused = policy["unused"]
    unsupported = policy["unsupported"]
    fixtures = policy["historicalFixtures"]
    if not all(
        isinstance(items, list) and items
        for items in (exact, ambiguous, unused, fixtures)
    ):
        raise ContractError("regional facts: every classification needs evidence")
    if len(exact) != 22 or len(ambiguous) != 8 or len(exact) != len(unused):
        raise ContractError("regional facts: expected representative reviewed facts")

    admitted_capabilities = {
        "CUT",
        "DIVE",
        "FLASH",
        "FLY",
        "ROCK_SMASH",
        "STRENGTH",
        "SURF",
        "WATERFALL",
    }
    if set(unsupported) != {"DEFOG", "ROCK_CLIMB"}:
        raise ContractError("regional facts: unsupported capability inventory changed")

    expected_reserved = [
        ("HOENN_STONE_BADGE", "CUT"),
        ("KANTO_CASCADE_BADGE", "CUT"),
        ("JOHTO_HIVE_BADGE", "CUT"),
        ("HOENN_KNUCKLE_BADGE", "FLASH"),
        ("KANTO_BOULDER_BADGE", "FLASH"),
        ("JOHTO_ZEPHYR_BADGE", "FLASH"),
        ("HOENN_DYNAMO_BADGE", "ROCK_SMASH"),
        ("KANTO_MARSH_BADGE", "ROCK_SMASH"),
        ("HOENN_HEAT_BADGE", "STRENGTH"),
        ("KANTO_RAINBOW_BADGE", "STRENGTH"),
        ("JOHTO_PLAIN_BADGE", "STRENGTH"),
        ("HOENN_BALANCE_BADGE", "SURF"),
        ("KANTO_SOUL_BADGE", "SURF"),
        ("JOHTO_FOG_BADGE", "SURF"),
        ("HOENN_FEATHER_BADGE", "FLY"),
        ("KANTO_THUNDER_BADGE", "FLY"),
        ("JOHTO_STORM_BADGE", "FLY"),
        ("HOENN_MIND_BADGE", "DIVE"),
        ("HOENN_RAIN_BADGE", "WATERFALL"),
        ("KANTO_VOLCANO_BADGE", "WATERFALL"),
        ("JOHTO_RISING_BADGE", "WATERFALL"),
    ]

    by_symbol = {(item["domain"], item["symbol"]): item for item in entries}
    exact_symbols: set[str] = set()
    exact_values: set[int] = set()
    facts: set[str] = set()
    for index, item in enumerate(exact):
        required = {
            "consumerEvidence",
            "fact",
            "grants",
            "lifetime",
            "region",
            "semanticOwner",
            "symbol",
            "unusedBinding",
            "value",
        }
        historical_fields = {"historicalSource", "historicalSymbol", "historicalValue"}
        if not isinstance(item, dict) or set(item) not in (
            required,
            required | historical_fields,
        ):
            raise ContractError(f"regional facts: malformed exact binding {index}")
        if not all(
            isinstance(item[key], str) and item[key]
            for key in (
                "fact",
                "lifetime",
                "region",
                "semanticOwner",
                "symbol",
                "unusedBinding",
            )
        ):
            raise ContractError(f"regional facts: invalid exact binding {index}")
        if (
            item["region"] not in {"HOENN", "KANTO", "SEVII", "JOHTO"}
            or item["lifetime"] != "save"
        ):
            raise ContractError(f"regional facts: invalid regional ownership {index}")
        evidence = item["consumerEvidence"]
        if not isinstance(evidence, list) or not evidence:
            raise ContractError(f"regional facts: missing consumer evidence {index}")
        for relative in evidence:
            path = repo / relative
            if not path.is_file() or item["symbol"] not in path.read_text(
                encoding="utf-8", errors="ignore"
            ):
                raise ContractError(
                    f"regional facts: unresolved consumer for {item['symbol']}"
                )
        if not isinstance(item["value"], int) or item["value"] <= 0:
            raise ContractError(f"regional facts: invalid exact value {index}")
        grants = item["grants"]
        if (
            not isinstance(grants, list)
            or any(capability not in admitted_capabilities for capability in grants)
            or len(grants) != len(set(grants))
            or (item["fact"] != "SEVII_DETOUR_FINISHED" and len(grants) != 1)
            or (item["fact"] == "SEVII_DETOUR_FINISHED" and grants)
        ):
            raise ContractError(
                f"regional facts: invalid capabilities for exact binding {index}"
            )
        if "historicalSymbol" in item:
            historical_path = repo / item["historicalSource"]
            historical_text = (
                historical_path.read_text(encoding="utf-8")
                if historical_path.is_file()
                else ""
            )
            historical_match = re.search(
                rf"(?m)^#define\s+{re.escape(item['historicalSymbol'])}\s+(0[xX][0-9A-Fa-f]+|[0-9]+)\b",
                historical_text,
            )
            if (
                not isinstance(item["historicalSymbol"], str)
                or historical_match is None
                or int(historical_match.group(1), 0) != item["historicalValue"]
                or item["historicalValue"] != item["value"]
            ):
                raise ContractError(
                    f"regional facts: historical meaning moved {item['symbol']}"
                )
        binding = by_symbol.get(("flags", item["symbol"]))
        expected_alias = {"of": item["unusedBinding"], "owner": source["id"]}
        if (
            binding is None
            or binding["source"] != source["id"]
            or binding["storage"] != "flag-id"
            or binding["state"] != {"kind": "allocated-binding"}
            or binding["value"] != item["value"]
            or binding["alias"] != expected_alias
        ):
            raise ContractError(f"regional facts: exact binding moved {item['symbol']}")
        exact_symbols.add(item["symbol"])
        exact_values.add(item["value"])
        facts.add(item["fact"])
    if (
        len(exact_symbols) != len(exact)
        or len(exact_values) != len(exact)
        or len(facts) != len(exact)
        or {item["region"] for item in exact} != {"HOENN", "KANTO", "SEVII", "JOHTO"}
    ):
        raise ContractError("regional facts: exact facts must be distinct and nonzero")

    reserved = sorted(
        (
            item["value"],
            item["fact"],
            item["symbol"],
            item["unusedBinding"],
            tuple(item["grants"]),
        )
        for item in exact
        if 0x020 <= item["value"] <= 0x034
    )
    expected_reserved_bindings = [
        (
            value,
            fact,
            f"FLAG_REGIONAL_FACT_{fact}",
            f"FLAG_UNUSED_0x{value:03X}",
            (capability,),
        )
        for value, (fact, capability) in enumerate(expected_reserved, 0x020)
    ]
    if reserved != expected_reserved_bindings:
        raise ContractError("regional facts: reviewed reserved mapping changed")

    ambiguous_symbols: set[str] = set()
    for index, item in enumerate(ambiguous):
        if not isinstance(item, dict) or set(item) != {
            "shippedCapabilities",
            "symbol",
            "value",
        }:
            raise ContractError(f"regional facts: malformed ambiguous binding {index}")
        if (
            not isinstance(item["shippedCapabilities"], list)
            or len(item["shippedCapabilities"]) != 1
            or item["shippedCapabilities"][0] not in admitted_capabilities
        ):
            raise ContractError(f"regional facts: invalid ambiguous binding {index}")
        binding = by_symbol.get(("flags", item["symbol"]))
        if (
            binding is None
            or binding["state"] != {"kind": "published-binding"}
            or binding["value"] != item["value"]
        ):
            raise ContractError(
                f"regional facts: ambiguous binding moved {item['symbol']}"
            )
        ambiguous_symbols.add(item["symbol"])
    expected_legacy = {
        f"FLAG_BADGE{slot:02d}_GET": (0x866 + slot, capability)
        for slot, capability in enumerate(
            (
                "CUT",
                "FLASH",
                "ROCK_SMASH",
                "STRENGTH",
                "SURF",
                "FLY",
                "DIVE",
                "WATERFALL",
            ),
            1,
        )
    }
    reviewed_legacy = {
        item["symbol"]: (item["value"], item["shippedCapabilities"][0])
        for item in ambiguous
    }
    if ambiguous_symbols != set(expected_legacy) or reviewed_legacy != expected_legacy:
        raise ContractError("regional facts: ambiguous legacy inventory changed")

    unused_by_symbol = {}
    for index, item in enumerate(unused):
        if not isinstance(item, dict) or set(item) != {
            "allocatedTo",
            "symbol",
            "value",
        }:
            raise ContractError(f"regional facts: malformed unused binding {index}")
        binding = by_symbol.get(("flags", item["symbol"]))
        if (
            binding is None
            or binding["state"] != {"kind": "published-binding"}
            or binding["value"] != item["value"]
            or item["allocatedTo"] not in exact_symbols
        ):
            raise ContractError(
                f"regional facts: unused binding moved {item['symbol']}"
            )
        unused_by_symbol[item["symbol"]] = item
    expected_unused = {
        *(f"FLAG_UNUSED_0x{value:03X}" for value in range(0x020, 0x035)),
        "FLAG_UNUSED_0x2A1",
    }
    if set(unused_by_symbol) != expected_unused:
        raise ContractError("regional facts: reviewed-unused inventory is incomplete")
    for fact in exact:
        unused_item = unused_by_symbol.get(fact["unusedBinding"])
        if (
            unused_item is None
            or unused_item["allocatedTo"] != fact["symbol"]
            or unused_item["value"] != fact["value"]
        ):
            raise ContractError("regional facts: unused allocation pairing changed")

    flag_schema = next(
        schema for schema in sources["consumerSchemas"] if schema["domain"] == "flags"
    )
    for symbol in unused_by_symbol:
        token = re.compile(rf"\b{re.escape(symbol)}\b")
        for glob in flag_schema["paths"]:
            for path in repo.glob(glob):
                if path.is_file() and token.search(
                    path.read_text(encoding="utf-8", errors="ignore")
                ):
                    raise ContractError(
                        f"regional facts: reviewed-unused binding has consumer {symbol} in {path}"
                    )

    for index, fixture in enumerate(fixtures):
        if not isinstance(fixture, dict) or set(fixture) != {"path", "sha256"}:
            raise ContractError(f"regional facts: malformed historical fixture {index}")
        inspect_historical_flags(
            repo / fixture["path"], fixture["sha256"], exact_values
        )


def validate_regional_variable_policy(
    entries: list[dict[str, Any]], sources: dict[str, Any], repo: Path
) -> None:
    policy_sources = [
        source
        for source in sources.get("sources", [])
        if source.get("kind") == "regional-variable-policy"
    ]
    if len(policy_sources) != 1:
        raise ContractError("regional variables: expected exactly one reviewed policy")
    policy = load_json(repo / policy_sources[0]["path"])
    if not isinstance(policy, dict) or set(policy) != {"entries", "schemaVersion"}:
        raise ContractError("regional variables: malformed reviewed policy")
    if policy["schemaVersion"] != 1 or not isinstance(policy["entries"], list):
        raise ContractError("regional variables: unsupported policy schema")
    ledger_by_symbol = {
        item["symbol"]: item for item in entries if item["domain"] == "vars"
    }
    seen: set[str] = set()
    admitted_values: set[int] = set()
    admitted_regions: set[str] = set()
    for index, item in enumerate(policy["entries"]):
        path = f"regional variables: entry {index}"
        common = {
            "canonicalOwner",
            "historicalAliases",
            "lifetime",
            "producerEvidence",
            "readerEvidence",
            "region",
            "semanticOwner",
            "status",
            "symbol",
            "value",
        }
        expected = common | (
            {"deferredBoundary"} if item.get("status") == "deferred" else set()
        )
        if not isinstance(item, dict) or set(item) != expected:
            raise ContractError(f"{path}: malformed")
        if item["status"] not in {"admitted", "deferred"}:
            raise ContractError(f"{path}: invalid status")
        if (
            item["region"] not in {"HOENN", "KANTO", "SEVII", "JOHTO"}
            or item["lifetime"] != "save"
        ):
            raise ContractError(f"{path}: invalid regional ownership")
        if (
            item["symbol"] in seen
            or not isinstance(item["value"], int)
            or item["value"] <= 0
        ):
            raise ContractError(f"{path}: identity must be unique and nonzero")
        seen.add(item["symbol"])
        binding = ledger_by_symbol.get(item["symbol"])
        if (
            binding is None
            or binding["value"] != item["value"]
            or binding["state"] != {"kind": "published-binding"}
        ):
            raise ContractError(f"{path}: published binding moved")
        canonical = (
            item["symbol"] if binding["alias"] is None else binding["alias"]["of"]
        )
        if canonical != item["canonicalOwner"]:
            raise ContractError(f"{path}: canonical owner changed")
        group_aliases = {
            candidate["symbol"]
            for candidate in entries
            if candidate["domain"] == "vars"
            and candidate["value"] == item["value"]
            and candidate["symbol"] not in {item["symbol"], item["canonicalOwner"]}
        }
        if set(item["historicalAliases"]) != group_aliases:
            raise ContractError(f"{path}: historical alias ownership changed")
        if item["status"] == "admitted":
            if item["value"] in admitted_values:
                raise ContractError(f"{path}: admitted storage identity is not unique")
            admitted_values.add(item["value"])
            admitted_regions.add(item["region"])
            evidence_patterns = {
                "producerEvidence": re.compile(
                    rf"(?m)^\s*setvar\s+{re.escape(item['symbol'])}\b|"
                    rf"\bVarSet\(\s*{re.escape(item['symbol'])}\b"
                ),
                "readerEvidence": re.compile(
                    rf"(?m)^\s*(?:call_if|goto_if|map_script_2)[A-Za-z0-9_]*\s+{re.escape(item['symbol'])}\b|"
                    rf"\bVarGet\(\s*{re.escape(item['symbol'])}\b|"
                    rf'"var"\s*:\s*"{re.escape(item["symbol"])}"'
                ),
            }
            for evidence_key, evidence_pattern in evidence_patterns.items():
                evidence = item[evidence_key]
                if not isinstance(evidence, list) or not evidence:
                    raise ContractError(f"{path}: missing {evidence_key}")
                for relative in evidence:
                    evidence_path = repo / relative
                    if not evidence_path.is_file() or not evidence_pattern.search(
                        evidence_path.read_text(encoding="utf-8", errors="ignore")
                    ):
                        raise ContractError(f"{path}: unresolved {evidence_key}")
        elif (
            not isinstance(item["deferredBoundary"], str)
            or not item["deferredBoundary"]
        ):
            raise ContractError(f"{path}: deferred state needs a fail-closed boundary")
    if admitted_regions != {"HOENN", "KANTO", "SEVII", "JOHTO"}:
        raise ContractError(
            "regional variables: admitted regional inventory is incomplete"
        )


def validate_resident_story_admission(sources: dict[str, Any], repo: Path) -> None:
    relative = sources.get("residentStoryAdmission")
    if not isinstance(relative, str) or not relative:
        raise ContractError("resident story: missing checked admission inventory")
    inventory = load_json(repo / relative)
    if not isinstance(inventory, dict) or set(inventory) != {
        "entries",
        "schemaVersion",
        "selectorScanPaths",
    }:
        raise ContractError("resident story: malformed admission inventory")
    if (
        inventory["schemaVersion"] != 1
        or not isinstance(inventory["entries"], list)
        or not inventory["entries"]
    ):
        raise ContractError("resident story: unsupported admission inventory")
    selector = RESIDENT_STORY_SELECTOR
    outcomes: set[str] = set()
    identifiers: set[str] = set()
    classified_paths: set[str] = set()
    for index, item in enumerate(inventory["entries"]):
        path = f"resident story: entry {index}"
        required = {"boundary", "id", "outcome", "paths", "rationale"}
        if not isinstance(item, dict) or set(item) != required:
            raise ContractError(f"{path}: malformed")
        if item["id"] in identifiers or item["outcome"] not in {
            "admitted",
            "build-invariant",
            "deferred",
            "non-story",
        }:
            raise ContractError(f"{path}: invalid classification")
        identifiers.add(item["id"])
        outcomes.add(item["outcome"])
        if (
            not isinstance(item["paths"], list)
            or not item["paths"]
            or not item["rationale"]
        ):
            raise ContractError(f"{path}: missing evidence")
        if item["outcome"] == "deferred" and not item["boundary"]:
            raise ContractError(
                f"{path}: deferred content needs a fail-closed boundary"
            )
        for relative_path in item["paths"]:
            classified_paths.add(relative_path)
            evidence_path = repo / relative_path
            if not evidence_path.is_file():
                raise ContractError(f"{path}: missing evidence {relative_path}")
            evidence_text = evidence_path.read_text(encoding="utf-8", errors="ignore")
            if item["outcome"] == "admitted" and selector.search(evidence_text):
                raise ContractError(
                    f"{path}: admitted story meaning uses product/current-region dispatch"
                )
            if item["outcome"] == "deferred" and not selector.search(evidence_text):
                raise ContractError(
                    f"{path}: deferred boundary is not guarded by a legacy selector"
                )
    if not {"admitted", "deferred", "non-story", "build-invariant"}.issubset(outcomes):
        raise ContractError("resident story: classification outcomes are incomplete")
    discovered: set[str] = set()
    for pattern in inventory["selectorScanPaths"]:
        for path in repo.glob(pattern):
            if path.is_file() and selector.search(
                path.read_text(encoding="utf-8", errors="ignore")
            ):
                discovered.add(path.relative_to(repo).as_posix())
    unclassified = sorted(discovered - classified_paths)
    if unclassified:
        raise ContractError(
            f"resident story: unclassified selector paths {unclassified[:5]}"
        )

    admitted_paths = {
        relative_path
        for item in inventory["entries"]
        if item["outcome"] == "admitted"
        for relative_path in item["paths"]
    }
    fact_policy = load_json(
        repo
        / next(
            source["path"]
            for source in sources["sources"]
            if source.get("kind") == "regional-fact-policy"
        )
    )
    variable_policy = load_json(
        repo
        / next(
            source["path"]
            for source in sources["sources"]
            if source.get("kind") == "regional-variable-policy"
        )
    )
    admitted_evidence = {
        relative_path
        for item in fact_policy["exact"]
        for relative_path in item["consumerEvidence"]
    } | {
        relative_path
        for item in variable_policy["entries"]
        if item["status"] == "admitted"
        for key in ("producerEvidence", "readerEvidence")
        for relative_path in item[key]
    }
    missing_admissions = sorted(admitted_evidence - admitted_paths)
    if missing_admissions:
        raise ContractError(
            f"resident story: admitted evidence is unclassified {missing_admissions[:5]}"
        )


def validate_trainer_identity_projection(
    entries: list[dict[str, Any]],
    contract: dict[str, Any],
    sources: dict[str, Any],
    repo: Path,
) -> None:
    projection = _trainer_identity_projection(contract, sources, repo)
    expected_tombstones = {
        (item["symbol"], item["value"]) for item in projection["tombstones"]
    }
    actual_tombstones = {
        (item["symbol"], item["value"])
        for item in entries
        if item["domain"] == "trainerIds"
        and item["state"]["kind"] == "published-tombstone"
    }
    if actual_tombstones != expected_tombstones:
        raise ContractError("trainer tombstone projection moved/deleted")

    expected_live = {
        (item["source"], item["symbol"]): item["value"] for item in projection["live"]
    }
    actual_live = {
        (item["source"], item["symbol"]): item["value"]
        for item in entries
        if item["domain"] == "trainerIds"
        and item["state"]["kind"] == "trainer-defeat-bitmap"
    }
    if actual_live != expected_live:
        raise ContractError("live trainer identity projection moved/deleted")


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
    allocated = {
        (item["domain"], item["symbol"]): item["state"]["kind"] for item in entries
    }

    def validate_reference(domain: str, symbol: str, path: Path) -> None:
        state = allocated.get((domain, symbol))
        if state is None:
            raise ContractError(
                f"{path}: unallocated {domain} consumer reference {symbol}"
            )
        if domain == "trainerIds" and state == "published-tombstone":
            raise ContractError(
                f"{path}: tombstoned trainerIds consumer reference {symbol}"
            )

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
                        validate_reference(domain, symbol, path)
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
                        validate_reference(domain, symbol, path)


def validate_frozen_bindings(
    entries: list[dict[str, Any]], contract: dict[str, Any]
) -> None:
    """Reject any deletion, addition, or move in the published baseline projection."""
    frozen = {
        (domain, item["symbol"]): item["value"]
        for domain, bindings in contract["publishedBindings"].items()
        for item in bindings
    }
    published = {
        (item["domain"], item["symbol"]): item["value"]
        for item in entries
        if (
            item["state"]["kind"]
            in {"published-binding", "published-tombstone", "trainer-defeat-flag"}
            or (
                item["state"]["kind"] == "trainer-defeat-bitmap"
                and (item["domain"], item["symbol"]) in frozen
            )
            or (
                item["source"] == "regional-facts"
                and item["state"]["kind"] == "allocated-binding"
                and (item["domain"], item["symbol"])
                in {
                    (domain, binding["symbol"])
                    for domain, bindings in contract["publishedBindings"].items()
                    for binding in bindings
                }
            )
        )
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
        "bitmapStorage",
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
    bitmap = policy["bitmapStorage"]
    if not isinstance(bitmap, dict) or set(bitmap) != {
        "bitCount",
        "byteCount",
        "firstTrainerId",
    }:
        raise ContractError("$.trainerDefeat.bitmapStorage: malformed policy")
    if not all(isinstance(bitmap[key], int) for key in bitmap):
        raise ContractError("$.trainerDefeat.bitmapStorage: values must be integers")
    if (
        bitmap["bitCount"] <= 0
        or bitmap["byteCount"] != (bitmap["bitCount"] + 7) // 8
        or bitmap["firstTrainerId"] != policy["publishedCount"]
        or policy["count"] != bitmap["firstTrainerId"] + bitmap["bitCount"]
    ):
        raise ContractError("$.trainerDefeat.bitmapStorage: inconsistent bounds")


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
    if kind == "trainer-defeat-bitmap":
        config = policy["bitmapStorage"]
        bit_index = state["bitIndex"]
        expected = trainer_id - config["firstTrainerId"]
        if not isinstance(bit_index, int) or not 0 <= bit_index < config["bitCount"]:
            raise ContractError(f"trainer {trainer_id}: out-of-range bitmap bit")
        if bit_index != expected:
            raise ContractError(f"trainer {trainer_id}: moved bitmap binding")
        return ("bitmap", bit_index // 8, bit_index % 8)

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
            "trainer-defeat-bitmap",
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
        if kind == "bitmap":
            continue
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
    bitmap = policy["bitmapStorage"]
    for trainer_id in range(bitmap["firstTrainerId"], count):
        bit_index = trainer_id - bitmap["firstTrainerId"]
        expected = ("bitmap", bit_index // 8, bit_index % 8)
        if values.get(trainer_id) != expected:
            raise ContractError(f"trainer {trainer_id}: bitmap defeat binding moved")
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
        storage = {
            "bitmap": "TRAINER_DEFEAT_STORAGE_BITMAP",
            "flag": "TRAINER_DEFEAT_STORAGE_FLAG",
            "variable-bit": "TRAINER_DEFEAT_STORAGE_VARIABLE_BIT",
        }[kind]
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
            defined_symbols("include/constants/flags.h", "FLAG_")
            | {
                item["symbol"] for item in entries if item["source"] == "regional-facts"
            },
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
            defined_symbols(
                (
                    "include/constants/opponents.h",
                    "include/constants/opponents_frlg.h",
                ),
                "TRAINER_",
            ),
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
    with _generation_lock(output_root):
        output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="persistent-ids-", dir=output_root
        ) as tmp:
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
