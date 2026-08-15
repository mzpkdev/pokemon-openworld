"""Bounded lookups over existing repository authorities."""

import json
import re
from pathlib import Path

from .output import envelope


def _matches(value, key):
    if isinstance(value, dict):
        return any(_matches(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_matches(item, key) for item in value)
    return key.casefold() in str(value).casefold()


def _location(path, text, key):
    folded = key.casefold()
    for number, line in enumerate(text.splitlines(), 1):
        if folded in line.casefold():
            return {"path": path.as_posix(), "line": number}
    return {"path": path.as_posix(), "line": 1}


def _compact(value, key):
    """Keep the matching record useful without returning a complete ledger."""
    if not isinstance(value, dict):
        return value
    preferred = (
        "id",
        "name",
        "symbol",
        "domain",
        "source",
        "storage",
        "value",
        "kind",
        "path",
        "port",
        "owner",
        "physicalBinding",
        "structure",
        "purpose",
    )
    result = {field: value[field] for field in preferred if field in value}
    if not result:
        for field, item in value.items():
            if key.casefold() in str(field).casefold() or (
                not isinstance(item, (dict, list))
                and key.casefold() in str(item).casefold()
            ):
                result[field] = item
    return result or {"matchingFields": sorted(value)[:12]}


def _json_records(path, source, key, roots):
    text = path.read_text()
    document = json.loads(text)
    found = []
    for root_key in roots:
        records = document.get(root_key, []) if isinstance(document, dict) else []
        if isinstance(records, dict):
            records = [{"key": name, "value": value} for name, value in records.items()]
        for record in records:
            if _matches(record, key):
                needle = key
                if isinstance(record, dict):
                    for field in ("id", "name", "symbol", "path"):
                        if (
                            field in record
                            and key.casefold() in str(record[field]).casefold()
                        ):
                            needle = str(record[field])
                            break
                found.append(
                    {
                        "record": _compact(record, key),
                        "location": _location(source, text, needle),
                    }
                )
    if not roots and _matches(document, key):

        def visit(value, pointer="$"):
            if isinstance(value, dict):
                direct = any(
                    key.casefold() in str(field).casefold()
                    or (
                        not isinstance(item, (dict, list))
                        and key.casefold() in str(item).casefold()
                    )
                    for field, item in value.items()
                )
                if direct:
                    found.append(
                        {
                            "record": _compact(value, key),
                            "pointer": pointer,
                            "location": _location(source, text, key),
                        }
                    )
                for field, item in value.items():
                    visit(item, f"{pointer}.{field}")
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    visit(item, f"{pointer}[{index}]")

        visit(document)
    return found


def query_map(root, key):
    candidates = []
    direct = root / "data/maps" / key / "map.json"
    if direct.is_file():
        candidates.append(direct)
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold()).removeprefix("map")
    for path in sorted((root / "data/maps").glob("*/map.json")):
        directory = re.sub(r"[^a-z0-9]", "", path.parent.name.casefold())
        if path not in candidates and (
            key.casefold() in path.parent.name.casefold() or normalized == directory
        ):
            candidates.append(path)
    items = []
    for path in candidates:
        text = path.read_text()
        record = json.loads(text)
        if (
            _matches(record.get("id", ""), key)
            or _matches(record.get("name", ""), key)
            or key.casefold() in path.parent.name.casefold()
        ):
            summary = {
                field: record[field]
                for field in ("id", "name", "layout", "region_map_section", "map_type")
                if field in record
            }
            for field in (
                "connections",
                "object_events",
                "warp_events",
                "coord_events",
                "bg_events",
            ):
                if field in record:
                    summary[f"{field}_count"] = len(record[field])
            summary["connections"] = record.get("connections", [])
            items.append(
                {
                    "key": record.get("id", record.get("name")),
                    "record": summary,
                    "source": path.relative_to(root).as_posix(),
                    "location": _location(path.relative_to(root), text, key),
                }
            )
    return items


def query_trainer(root, key):
    items = []
    heading = re.compile(r"^===\s+([^=]+?)\s+===$", re.MULTILINE)
    for path in (
        Path("src/data/trainers.party"),
        Path("src/data/trainers_frlg.party"),
        Path("src/data/debug_trainers.party"),
    ):
        absolute = root / path
        if not absolute.is_file():
            continue
        text = absolute.read_text()
        matches = list(heading.finditer(text))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            block = text[match.start() : end].strip()
            if key.casefold() not in block.casefold():
                continue
            lines = block.splitlines()
            fields = {}
            for line in lines[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    if name in {"Name", "Class", "Gender", "Double Battle"}:
                        fields[name] = value.strip()
            fields["pokemon"] = [
                line
                for line in lines[1:]
                if line and ":" not in line and not line.startswith(("-", "~"))
            ]
            items.append(
                {
                    "key": match.group(1),
                    "record": fields,
                    "source": path.as_posix(),
                    "location": {
                        "path": path.as_posix(),
                        "line": text[: match.start()].count("\n") + 1,
                    },
                }
            )
    exact = [item for item in items if item["key"].casefold() == key.casefold()]
    return exact or items


def query_json_domain(root, key, paths):
    items = []
    for relative, roots in paths:
        path = root / relative
        if not path.is_file():
            continue
        source = path.relative_to(root)
        for found in _json_records(path, source, key, roots):
            item = {
                "key": key,
                "record": found["record"],
                "source": relative,
                "location": found["location"],
            }
            if "pointer" in found:
                item["pointer"] = found["pointer"]
            items.append(item)
    exact = [
        item
        for item in items
        if any(
            not isinstance(value, (dict, list))
            and str(value).casefold() == key.casefold()
            for value in item["record"].values()
        )
    ]
    return exact or items


def run_query(root, kind, key):
    if kind == "map":
        items = query_map(root, key)
    elif kind == "trainer":
        items = query_trainer(root, key)
    elif kind == "persistence":
        items = query_json_domain(
            root,
            key,
            [
                ("tools/persistence/published_allocations.json", ("entries",)),
                (
                    "tools/persistence/persistent_sources.json",
                    ("sources", "records", "entries"),
                ),
                (
                    "src/data/persistence/persistent_ids.json",
                    ("entries", "records", "ids"),
                ),
                ("tools/integrity/save_contract.json", ()),
            ],
        )
    elif kind == "content-port":
        items = query_json_domain(
            root,
            key,
            [
                (path.relative_to(root).as_posix(), ())
                for path in sorted((root / "tools/content_port/ports").glob("*/*.json"))
            ],
        )
    else:
        raise ValueError(f"unknown query kind: {kind}")
    status = "ok" if items else "not-found"
    result = envelope(
        status=status,
        summary=f"found {len(items)} {kind} record(s) for {key!r}",
        inputs={"kind": kind, "key": key},
    )
    result["items"] = items
    return result
