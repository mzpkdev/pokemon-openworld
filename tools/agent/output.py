"""Stable envelopes and size-bounded rendering."""

import json

from . import SCHEMA_VERSION

CONTEXT_LIMIT = 12 * 1024
CHECK_LIMIT = 8 * 1024
DIAGNOSTIC_LIMIT = 1024


def envelope(status="ok", summary="", inputs=None):
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "summary": summary,
        "inputs": inputs or {},
        "items": [],
        "impacts": [],
        "checks": [],
        "diagnostics": [],
        "logs": [],
        "truncated": {"value": False, "omittedRecords": 0, "omittedBytes": 0},
    }


def _encoded(document):
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def bound(document, limit):
    """Remove whole records or long optional fields until JSON fits *limit*."""
    original = len(_encoded(document).encode())
    omitted = 0
    for field in ("items", "diagnostics", "checks", "impacts", "logs"):
        while len(_encoded(document).encode()) > limit and document[field]:
            document[field].pop()
            omitted += 1
    if len(_encoded(document).encode()) > limit:
        document["summary"] = document["summary"][:160]
        document["inputs"] = {"omitted": True}
    final = len(_encoded(document).encode())
    if final > limit:
        raise ValueError(f"result envelope cannot fit {limit} bytes")
    if original != final:
        document["truncated"] = {
            "value": True,
            "omittedRecords": omitted,
            "omittedBytes": max(0, original - final),
        }
        while len(_encoded(document).encode()) > limit:
            for field in ("items", "diagnostics", "checks", "impacts", "logs"):
                if document[field]:
                    document[field].pop()
                    document["truncated"]["omittedRecords"] += 1
                    break
            else:
                document["summary"] = document["summary"][:80]
                break
    if len(_encoded(document).encode()) > limit:
        raise ValueError(f"result envelope cannot fit {limit} bytes")
    return document


def render_json(document, limit):
    return _encoded(bound(document, limit)) + "\n"


def render_text(document, limit=None):
    if limit is not None:
        bound(document, limit)
    lines = [f"{document['status']}: {document['summary']}"]
    for item in document["items"]:
        label = item.get("path") or item.get("key") or item.get("id") or "item"
        lines.append(
            f"- {label}: {item.get('summary', item.get('authority', 'match'))}"
        )
    for check in document["checks"]:
        lines.append(f"- check {check['id']} ({check['tier']}): {check['reason']}")
    for diagnostic in document["diagnostics"]:
        lines.append(
            f"- {diagnostic.get('kind', 'diagnostic')}: {diagnostic.get('excerpt', '')}"
        )
    if document["truncated"]["value"]:
        lines.append(f"truncated: {document['truncated']}")
    if limit is None:
        return "\n".join(lines) + "\n"
    admitted = []
    omitted = 0
    for line in lines:
        candidate = "\n".join([*admitted, line]) + "\n"
        if len(candidate.encode()) <= limit:
            admitted.append(line)
        else:
            omitted += 1
    if omitted:
        notice = f"truncated: {omitted} text record(s) omitted"
        candidate = "\n".join([*admitted, notice]) + "\n"
        if len(candidate.encode()) <= limit:
            admitted.append(notice)
    return "\n".join(admitted) + "\n"
