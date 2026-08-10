"""Auditable donor-pin migration reports.

This module proposes descriptor changes.  It never edits a port descriptor or a
donor checkout and a candidate report never grants a new donor tree authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Iterable, Mapping, Sequence

from .donor_paths import validated_donor_checkout, validated_donor_checkouts
from .donors import records_digest, source_tree_records
from .errors import ContentPortError
from .faults import checkpoint


SCHEMA_VERSION = 1
FINALIZED_MIGRATION_SCHEMA_VERSION = 2
PERMISSION_STATES = frozenset(("redistributable", "blocked", "unknown"))
SUPPORT_STATES = frozenset(
    ("enabled", "disabled", "deferred", "story-owned", "unsupported")
)
REVIEW_DECISIONS = frozenset(("candidate", "reviewed", "rejected"))
REVIEWED_DISPOSITIONS = frozenset(("accepted", "adapted"))
_MISSING = object()
MIGRATION_KEYS = {
    "addedPaths",
    "assets",
    "authorityChanges",
    "changedPaths",
    "decision",
    "donor",
    "from",
    "predecessor",
    "policy",
    "removedPaths",
    "repository",
    "schemaVersion",
    "tests",
    "to",
}
FINALIZED_MIGRATION_KEYS = MIGRATION_KEYS | {
    "publicationPolicyDigest",
    "publicationPolicySnapshot",
}
REQUIRED_REVIEW_COMMANDS = (
    (
        "python3",
        "-m",
        "unittest",
        "tools.content_port.tests.test_ci_contract",
        "-q",
    ),
)
PUBLICATION_POLICY_FIELDS = (
    "capabilityPolicy",
    "eventPolicy",
    "legacyReport",
    "adaptations",
    "assetPolicy",
    "allocationLock",
)


class DonorUpdateError(ContentPortError):
    """A donor migration or asset contract is invalid."""


@dataclass(frozen=True)
class TreeIdentity:
    commit: str
    digest: str
    file_count: int
    files: Mapping[str, str]


def _descriptor_policy_file(
    port_dir: Path,
    port_document: Mapping[str, object],
    field: str,
) -> Path:
    """Resolve a descriptor-selected policy through the descriptor contract."""

    # Keep this import local: descriptor loading delegates asset validation back
    # to this module, so importing the helper while modules initialize would
    # create a cycle.
    from .descriptor import _safe_child

    try:
        value = port_document[field]
    except KeyError as error:
        raise DonorUpdateError(f"invalid descriptor policy file $.{field}") from error
    try:
        path = _safe_child(port_dir, value, f"$.{field}")
    except ContentPortError as error:
        raise DonorUpdateError(str(error)) from error
    if not path.is_file():
        raise DonorUpdateError(f"$.{field}: policy file must be a regular file")
    return path


def canonical_bytes(value: object) -> bytes:
    def thaw(item: object) -> object:
        if isinstance(item, Mapping):
            return {key: thaw(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [thaw(child) for child in item]
        return item

    return (
        json.dumps(thaw(value), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _run_git(tree: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ("git", "-C", str(tree), *args),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise DonorUpdateError(
            f"cannot inspect donor checkout {tree}: {detail.strip()}"
        ) from error
    return result.stdout.strip()


def _remove_worktrees(
    worktrees: Iterable[tuple[Path, Path]],
    primary_error: BaseException | None,
) -> None:
    """Remove every temporary worktree without hiding an in-flight failure."""

    failures: list[str] = []
    for checkout, worktree in worktrees:
        try:
            result = subprocess.run(
                (
                    "git",
                    "-C",
                    str(checkout),
                    "worktree",
                    "remove",
                    "--force",
                    str(worktree),
                ),
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as error:
            failures.append(f"{worktree}: {error}")
            continue
        if result.returncode:
            detail = result.stderr.strip() or f"git exited {result.returncode}"
            failures.append(f"{worktree}: {detail}")
    if not failures:
        return
    cleanup_error = DonorUpdateError(
        "temporary donor worktree cleanup failed: " + "; ".join(failures)
    )
    if primary_error is not None:
        primary_error.add_note(str(cleanup_error))
        return
    raise cleanup_error


def _safe_source_path(value: object, pointer: str) -> str:
    if not isinstance(value, str) or not value:
        raise DonorUpdateError(f"{pointer}: expected a non-empty source path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise DonorUpdateError(f"{pointer}: unsafe source path {value!r}")
    return value


def _validated_donor_checkout(donor_root: Path, value: object, pointer: str) -> Path:
    """Validate a descriptor donor root before resolving or mutating paths."""

    return validated_donor_checkout(
        donor_root, value, pointer, error_type=DonorUpdateError
    )


def _validated_donor_checkouts(
    port_document: Mapping[str, object], donor_root: Path
) -> Mapping[str, Path]:
    """Preflight every raw donor root before any caller starts filesystem work."""

    return validated_donor_checkouts(
        port_document, donor_root, error_type=DonorUpdateError
    )


def identify_tree(tree: Path, *, excluded_paths: Iterable[str] = ()) -> TreeIdentity:
    """Return an exact identity for the checked-out commit and file inventory."""

    tree = tree.resolve()
    if not tree.is_dir():
        raise DonorUpdateError(f"donor checkout does not exist: {tree}")
    commit = _run_git(tree, "rev-parse", "HEAD^{commit}")
    records = source_tree_records(tree, excluded_paths=excluded_paths)
    files = {
        str(record["path"]): f"{record['bytes']} {record['sha256']}"
        for record in records
    }
    return TreeIdentity(
        commit=commit,
        digest=records_digest(records),
        file_count=len(files),
        files=files,
    )


def _read_blob(tree: Path, commit: str, source_path: str) -> bytes | None:
    probe = subprocess.run(
        ("git", "-C", str(tree), "cat-file", "-e", f"{commit}:{source_path}"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe.returncode:
        return None
    try:
        return subprocess.run(
            ("git", "-C", str(tree), "show", f"{commit}:{source_path}"),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except subprocess.CalledProcessError as error:
        raise DonorUpdateError(
            f"cannot read donor source {source_path} at {commit}"
        ) from error


def _json_pointer(value: object, pointer: str) -> object:
    if pointer in ("", "/"):
        return value
    if not pointer.startswith("/"):
        raise DonorUpdateError(f"invalid JSON pointer: {pointer!r}")
    current = value
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdecimal():
            index = int(token)
            if index >= len(current):
                return _MISSING
            current = current[index]
        else:
            return _MISSING
    return current


def _field_value(blob: bytes | None, pointer: str | None) -> object:
    if blob is None:
        return _MISSING
    if pointer is None:
        return hashlib.sha256(blob).hexdigest()
    try:
        document = json.loads(blob)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DonorUpdateError(
            f"referenced field {pointer} is not in a JSON source"
        ) from error
    return _json_pointer(document, pointer)


def _layout_field_value(blob: bytes | None, layout_id: str, field: str) -> object:
    if blob is None:
        return _MISSING
    try:
        layouts = json.loads(blob)["layouts"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise DonorUpdateError("donor layout registry is malformed") from error
    if not isinstance(layouts, list) or not all(
        isinstance(item, Mapping) for item in layouts
    ):
        raise DonorUpdateError("donor layout registry is malformed")
    matches = [
        item
        for item in layouts
        if isinstance(item, dict) and item.get("id") == layout_id
    ]
    if not matches:
        return _MISSING
    if len(matches) != 1:
        raise DonorUpdateError(
            f"donor layout registry has invalid {layout_id}.{field} authority"
        )
    return matches[0].get(field, _MISSING)


def _layout_record_value(blob: bytes | None, layout_id: str) -> object:
    if blob is None:
        return _MISSING
    try:
        layouts = json.loads(blob)["layouts"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise DonorUpdateError("donor layout registry is malformed") from error
    if not isinstance(layouts, list) or not all(
        isinstance(item, Mapping) for item in layouts
    ):
        raise DonorUpdateError("donor layout registry is malformed")
    matches = [
        item
        for item in layouts
        if isinstance(item, dict) and item.get("id") == layout_id
    ]
    if not matches:
        return _MISSING
    if len(matches) != 1:
        raise DonorUpdateError(f"donor layout registry duplicates {layout_id}")
    return matches[0]


def _section_record_value(tree: Path, symbol: str) -> object:
    records: list[Mapping[str, object]] = []
    for path in sorted((tree / "src/data/region_map").glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise DonorUpdateError(
                f"cannot inspect donor section metadata {path}"
            ) from error
        if not isinstance(document, Mapping):
            raise DonorUpdateError(f"donor section metadata is malformed: {path}")
        values = document.get("map_sections", [])
        if not isinstance(values, list) or not all(
            isinstance(item, Mapping) for item in values
        ):
            raise DonorUpdateError(f"donor section metadata is malformed: {path}")
        records.extend(
            item
            for item in values
            if isinstance(item, Mapping)
            and item.get("id", item.get("map_section")) == symbol
        )
    distinct = {canonical_bytes(record) for record in records}
    if not records:
        return _MISSING
    if len(distinct) != 1:
        raise DonorUpdateError(f"donor section metadata duplicates {symbol}")
    return records[0]


def _value_hash(value: object) -> str | None:
    if value is _MISSING:
        return None
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _authority_changes(
    old_tree: Path,
    new_tree: Path,
    old: TreeIdentity,
    new: TreeIdentity,
    references: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    for index, reference in enumerate(references):
        pointer = f"$.references[{index}]"
        source_path = _safe_source_path(
            reference.get("sourcePath"), f"{pointer}.sourcePath"
        )
        semantic_identity = reference.get("semanticIdentity")
        authority = reference.get("authority")
        json_pointer = reference.get("jsonPointer")
        if not isinstance(semantic_identity, str) or not semantic_identity:
            raise DonorUpdateError(
                f"{pointer}.semanticIdentity: expected a non-empty string"
            )
        if not isinstance(authority, str) or not authority:
            raise DonorUpdateError(f"{pointer}.authority: expected a non-empty string")
        if json_pointer is not None and not isinstance(json_pointer, str):
            raise DonorUpdateError(f"{pointer}.jsonPointer: expected a string")
        layout_id = reference.get("layoutId")
        field = reference.get("field")
        record_type = reference.get("recordType")
        if record_type == "semantic-evidence":
            old_hash = reference.get("oldHash")
            new_hash = reference.get("newHash")
            for label, value in (("oldHash", old_hash), ("newHash", new_hash)):
                if value is not None and (
                    not isinstance(value, str)
                    or len(value) != 64
                    or any(character not in "0123456789abcdef" for character in value)
                ):
                    raise DonorUpdateError(
                        f"{pointer}.{label}: expected a 64-character lowercase hex "
                        "hash or null"
                    )
            if old_hash != new_hash:
                changes.append(
                    {
                        "authority": authority,
                        "jsonPointer": None,
                        "newHash": new_hash,
                        "oldHash": old_hash,
                        "reviewerDisposition": "pending",
                        "semanticIdentity": semantic_identity,
                        "sourcePath": source_path,
                    }
                )
            continue
        if record_type == "section":
            section_symbol = reference.get("sectionSymbol")
            if not isinstance(section_symbol, str):
                raise DonorUpdateError(f"{pointer}.sectionSymbol: expected a string")
            old_record = _section_record_value(old_tree, section_symbol)
            new_record = _section_record_value(new_tree, section_symbol)
        else:
            old_blob = _read_blob(old_tree, old.commit, source_path)
            new_blob = _read_blob(new_tree, new.commit, source_path)
            if record_type == "map":
                old_record = _field_value(old_blob, "")
                new_record = _field_value(new_blob, "")
            elif record_type == "layout" and isinstance(layout_id, str):
                old_record = _layout_record_value(old_blob, layout_id)
                new_record = _layout_record_value(new_blob, layout_id)
            else:
                old_record = new_record = None
        if record_type in {"map", "layout", "section"}:
            for label, record in (("old", old_record), ("new", new_record)):
                if record is not _MISSING and not isinstance(record, Mapping):
                    raise DonorUpdateError(
                        f"{pointer}: {label} {record_type} record is malformed"
                    )
            old_fields = {} if old_record is _MISSING else old_record
            new_fields = {} if new_record is _MISSING else new_record
            for field_name in sorted(set(old_fields) | set(new_fields)):
                old_value = old_fields.get(field_name, _MISSING)
                new_value = new_fields.get(field_name, _MISSING)
                if old_value == new_value:
                    continue
                token = str(field_name).replace("~", "~0").replace("/", "~1")
                changes.append(
                    {
                        "authority": authority,
                        "jsonPointer": f"/{token}",
                        "newHash": _value_hash(new_value),
                        "oldHash": _value_hash(old_value),
                        "reviewerDisposition": "pending",
                        "semanticIdentity": f"{semantic_identity}.{field_name}",
                        "sourcePath": source_path,
                    }
                )
            continue
        if isinstance(layout_id, str) and isinstance(field, str):
            old_value = _layout_field_value(old_blob, layout_id, field)
            new_value = _layout_field_value(new_blob, layout_id, field)
        else:
            old_value = _field_value(old_blob, json_pointer)
            new_value = _field_value(new_blob, json_pointer)
        if old_value == new_value:
            continue
        changes.append(
            {
                "authority": authority,
                "jsonPointer": json_pointer,
                "newHash": _value_hash(new_value),
                "oldHash": _value_hash(old_value),
                "reviewerDisposition": "pending",
                "semanticIdentity": semantic_identity,
                "sourcePath": source_path,
            }
        )
    unique: dict[tuple[object, ...], dict[str, object]] = {}
    for change in changes:
        identity = (
            change["authority"],
            change["semanticIdentity"],
            change["sourcePath"],
            change["jsonPointer"],
        )
        previous = unique.get(identity)
        if previous is not None and previous != change:
            raise DonorUpdateError(
                f"conflicting authority evidence for {change['semanticIdentity']}"
            )
        unique[identity] = change
    return [unique[identity] for identity in sorted(unique, key=lambda item: str(item))]


def validate_assets(
    document: Mapping[str, object],
    *,
    evidence_root: Path | None = None,
    require_redistributable: bool = True,
) -> tuple[Mapping[str, object], ...]:
    """Validate complete asset provenance and permission metadata."""

    allowed_keys = {
        "key",
        "source",
        "donor",
        "sourcePath",
        "semanticTarget",
        "sourceSha256",
        "targetSha256",
        "conversionCommand",
        "permission",
        "license",
        "permissionEvidence",
        "capability",
        "supportState",
    }
    if set(document) != {"schemaVersion", "permissionRecords", "assets"}:
        raise DonorUpdateError("assets.json: expected exact asset policy fields")
    assets = document.get("assets")
    permission_records = document.get("permissionRecords")
    if (
        document.get("schemaVersion") != SCHEMA_VERSION
        or not isinstance(assets, (list, tuple))
        or not isinstance(permission_records, Mapping)
    ):
        raise DonorUpdateError(
            "assets.json: expected schemaVersion 1, permissionRecords, and assets"
        )
    if evidence_root is None:
        raise DonorUpdateError("assets.json: permission evidence root is required")
    evidence_root = evidence_root.resolve()
    validated_permissions: dict[str, str] = {}
    for key, raw in sorted(permission_records.items()):
        pointer = f"$.permissionRecords.{key}"
        if (
            not isinstance(key, str)
            or len(key) != 64
            or any(character not in "0123456789abcdef" for character in key)
        ):
            raise DonorUpdateError(f"{pointer}: expected content-addressed record key")
        if not isinstance(raw, Mapping) or set(raw) != {
            "decision",
            "path",
            "permission",
            "sha256",
        }:
            raise DonorUpdateError(f"{pointer}: expected exact permission record")
        if raw["decision"] != "reviewed":
            raise DonorUpdateError(f"{pointer}.decision: permission is not reviewed")
        if hashlib.sha256(canonical_bytes(raw)).hexdigest() != key:
            raise DonorUpdateError(f"{pointer}: permission record digest is stale")
        permission = raw["permission"]
        if permission not in PERMISSION_STATES:
            raise DonorUpdateError(f"{pointer}.permission: unknown permission state")
        relative = _safe_source_path(raw["path"], f"{pointer}.path")
        digest = raw["sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise DonorUpdateError(f"{pointer}.sha256: expected lowercase SHA-256")
        evidence_path = evidence_root / PurePosixPath(relative)
        try:
            resolved_evidence = evidence_path.resolve(strict=True)
            resolved_evidence.relative_to(evidence_root)
        except (OSError, ValueError) as error:
            raise DonorUpdateError(
                f"{pointer}.path: permission evidence is missing"
            ) from error
        if resolved_evidence != evidence_path or not evidence_path.is_file():
            raise DonorUpdateError(f"{pointer}.path: permission evidence is missing")
        try:
            actual_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        except OSError as error:
            raise DonorUpdateError(
                f"{pointer}.path: cannot read permission evidence"
            ) from error
        if actual_digest != digest:
            raise DonorUpdateError(f"{pointer}.sha256: permission evidence is stale")
        validated_permissions[key] = str(permission)
    seen: set[str] = set()
    result: list[Mapping[str, object]] = []
    for index, asset in enumerate(assets):
        pointer = f"$.assets[{index}]"
        if not isinstance(asset, Mapping):
            raise DonorUpdateError(f"{pointer}: expected an object")
        unknown = sorted(set(asset) - allowed_keys)
        if unknown:
            raise DonorUpdateError(f"{pointer}: unknown fields {unknown}")
        required = (
            "key",
            "donor",
            "sourcePath",
            "semanticTarget",
            "sourceSha256",
            "targetSha256",
            "conversionCommand",
            "permission",
            "permissionEvidence",
            "capability",
            "supportState",
        )
        missing = [key for key in required if key not in asset]
        if missing:
            raise DonorUpdateError(f"{pointer}: missing fields {missing}")
        key = asset["key"]
        if not isinstance(key, str) or not key:
            raise DonorUpdateError(f"{pointer}.key: expected a non-empty string")
        if key in seen:
            raise DonorUpdateError(f"{pointer}.key: duplicate asset key {key}")
        seen.add(key)
        for field in ("donor", "semanticTarget", "capability"):
            if not isinstance(asset[field], str) or not asset[field]:
                raise DonorUpdateError(
                    f"{pointer}.{field}: expected a non-empty string"
                )
        for field in ("source", "license"):
            if field in asset and (
                not isinstance(asset[field], str) or not asset[field]
            ):
                raise DonorUpdateError(
                    f"{pointer}.{field}: expected a non-empty string"
                )
        _safe_source_path(asset["sourcePath"], f"{pointer}.sourcePath")
        for field in ("sourceSha256", "targetSha256"):
            digest = asset[field]
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise DonorUpdateError(f"{pointer}.{field}: expected lowercase SHA-256")
        command = asset["conversionCommand"]
        if (
            not isinstance(command, (list, tuple))
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            raise DonorUpdateError(
                f"{pointer}.conversionCommand: expected a non-empty argv list"
            )
        permission = asset["permission"]
        if permission not in PERMISSION_STATES:
            raise DonorUpdateError(
                f"{pointer}.permission: unknown permission state {permission!r}"
            )
        if (
            not isinstance(asset["permissionEvidence"], str)
            or not asset["permissionEvidence"]
        ):
            raise DonorUpdateError(
                f"{pointer}.permissionEvidence: expected a non-empty string"
            )
        evidence_key = str(asset["permissionEvidence"])
        evidence_permission = validated_permissions.get(evidence_key)
        if evidence_permission is None:
            raise DonorUpdateError(
                f"{pointer}.permissionEvidence: unknown permission record"
            )
        if permission != evidence_permission:
            raise DonorUpdateError(
                f"{pointer}.permission: differs from reviewed permission record"
            )
        if require_redistributable and permission != "redistributable":
            raise DonorUpdateError(f"asset {key}: permission is {permission}")
        support_state = asset["supportState"]
        if support_state not in SUPPORT_STATES:
            raise DonorUpdateError(
                f"{pointer}.supportState: unknown state {support_state!r}"
            )
        result.append(asset)
    unused_permissions = sorted(
        set(validated_permissions)
        - {str(asset["permissionEvidence"]) for asset in result}
    )
    if unused_permissions:
        raise DonorUpdateError(
            f"assets.json: unused permission record {unused_permissions[0]!r}"
        )
    return tuple(result)


def _asset_changes(
    old_tree: Path,
    new_tree: Path,
    old: TreeIdentity,
    new: TreeIdentity,
    assets: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    for asset in assets:
        source_path = str(asset["sourcePath"])
        old_blob = _read_blob(old_tree, old.commit, source_path)
        new_blob = _read_blob(new_tree, new.commit, source_path)
        old_hash = (
            hashlib.sha256(old_blob).hexdigest() if old_blob is not None else None
        )
        new_hash = (
            hashlib.sha256(new_blob).hexdigest() if new_blob is not None else None
        )
        if old_hash == new_hash:
            continue
        changes.append(
            {
                "conversionCommand": asset["conversionCommand"],
                "key": asset["key"],
                "newHash": new_hash,
                "oldHash": old_hash,
                "permission": asset["permission"],
                "reviewerDisposition": "pending",
                "semanticTarget": asset["semanticTarget"],
                "sourcePath": source_path,
                "supportState": asset["supportState"],
            }
        )
    return changes


def _migration_policy(
    value: object,
    *,
    evidence_root: Path,
) -> tuple[tuple[Mapping[str, object], ...], Mapping[str, object], tuple[str, ...]]:
    if not isinstance(value, Mapping) or set(value) != {
        "assets",
        "excludedPaths",
        "references",
        "schemaVersion",
    }:
        raise DonorUpdateError("$.policy: expected exact migration policy snapshot")
    if value.get("schemaVersion") != SCHEMA_VERSION:
        raise DonorUpdateError("$.policy.schemaVersion: unsupported policy snapshot")
    references = value.get("references")
    excluded_paths = value.get("excludedPaths")
    assets = value.get("assets")
    if (
        not isinstance(references, (list, tuple))
        or not all(isinstance(reference, Mapping) for reference in references)
        or not isinstance(excluded_paths, (list, tuple))
        or not all(isinstance(path, str) for path in excluded_paths)
        or not isinstance(assets, Mapping)
    ):
        raise DonorUpdateError("$.policy: invalid migration policy snapshot")
    validate_assets(
        assets,
        evidence_root=evidence_root,
        require_redistributable=False,
    )
    return tuple(references), assets, tuple(excluded_paths)


def _build_policy_snapshot(
    references: Iterable[Mapping[str, object]],
    assets: Mapping[str, object] | None,
    excluded_paths: Iterable[str],
) -> Mapping[str, object]:
    asset_policy: Mapping[str, object] = assets or {
        "schemaVersion": SCHEMA_VERSION,
        "permissionRecords": {},
        "assets": [],
    }
    value = {
        "assets": asset_policy,
        "excludedPaths": sorted(excluded_paths),
        "references": sorted(
            (dict(reference) for reference in references),
            key=canonical_bytes,
        ),
        "schemaVersion": SCHEMA_VERSION,
    }
    return json.loads(canonical_bytes(value))


def _filter_asset_policy(
    document: Mapping[str, object], assets: Sequence[Mapping[str, object]]
) -> Mapping[str, object]:
    permission_records = document.get("permissionRecords")
    if not isinstance(permission_records, Mapping):
        raise DonorUpdateError("assets.json: permissionRecords must be an object")
    evidence_keys = {str(asset["permissionEvidence"]) for asset in assets}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "permissionRecords": {
            key: permission_records[key] for key in sorted(evidence_keys)
        },
        "assets": list(assets),
    }


def _semantic_policy_references(
    current: Mapping[str, str], target: Mapping[str, str], donor: str
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(donor, str) or not donor:
        raise DonorUpdateError("semantic evidence donor must be a non-empty string")
    identities = set(current) | set(target)
    if not all(isinstance(identity, str) for identity in identities):
        raise DonorUpdateError("semantic evidence identities must be strings")

    def checked_hash(value: object, pointer: str) -> str | None:
        if value is None:
            return None
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise DonorUpdateError(
                f"{pointer}: expected a 64-character lowercase hex hash"
            )
        return value

    prefix = f"{donor}:"
    references: list[Mapping[str, object]] = []
    for identity in sorted(identities):
        if not identity.startswith(prefix):
            continue
        semantic_identity = identity[len(prefix) :]
        if not semantic_identity:
            raise DonorUpdateError(
                f"semantic evidence identity {identity!r} has no resource identity"
            )
        references.append(
            {
                "authority": donor,
                "newHash": checked_hash(
                    target.get(identity), f"semantic evidence {identity!r} target hash"
                ),
                "oldHash": checked_hash(
                    current.get(identity),
                    f"semantic evidence {identity!r} current hash",
                ),
                "recordType": "semantic-evidence",
                "semanticIdentity": semantic_identity,
                "sourcePath": f"semantic-evidence/{semantic_identity.replace(':', '/')}",
            }
        )
    return tuple(references)


def _derive_authored_policy_snapshot(
    port_dir: Path,
    port_document: Mapping[str, object],
    donor: str,
    *,
    evidence_root: Path,
) -> Mapping[str, object]:
    """Derive live authored migration inputs before production closure."""

    record = _descriptor_donor_record(port_document, donor)
    excluded_paths = record.get("excludePaths")
    if not isinstance(excluded_paths, list) or not all(
        isinstance(path, str) for path in excluded_paths
    ):
        raise DonorUpdateError(f"invalid donor exclusions for {donor!r}")
    try:
        adaptations = json.loads(
            _descriptor_policy_file(port_dir, port_document, "adaptations").read_text(
                encoding="utf-8"
            )
        )
        assets_document = json.loads(
            _descriptor_policy_file(port_dir, port_document, "assetPolicy").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as error:
        raise DonorUpdateError("cannot derive live migration policy") from error
    if not isinstance(adaptations, Mapping) or not isinstance(assets_document, Mapping):
        raise DonorUpdateError("live migration policy is invalid")
    allocations = _allocation_policy(port_dir, port_document)
    asset_records = validate_assets(
        assets_document,
        evidence_root=evidence_root,
        require_redistributable=False,
    )
    name = record.get("name")
    filtered_assets = _filter_asset_policy(
        assets_document,
        [asset for asset in asset_records if asset.get("donor") in (donor, name)],
    )
    references = _policy_references(adaptations, donor, allocations)
    return _build_policy_snapshot(references, filtered_assets, excluded_paths)


def _capture_publication_policy(
    port_dir: Path,
    donor: str,
    *,
    evidence_root: Path,
    descriptor_bytes: bytes | None = None,
    descriptor: Mapping[str, object] | None = None,
) -> tuple[Mapping[str, object], Mapping[str, object], str, str]:
    """Capture one raw descriptor generation and its donor-specific semantics."""

    port_path = port_dir / "port.json"
    try:
        if descriptor_bytes is None:
            descriptor_bytes = port_path.read_bytes()
        if descriptor is None:
            descriptor = json.loads(descriptor_bytes)
    except (OSError, json.JSONDecodeError) as error:
        raise DonorUpdateError("cannot re-read migration publication policy") from error
    if not isinstance(descriptor, Mapping):
        raise DonorUpdateError("migration publication policy is invalid")

    def raw_inputs() -> Mapping[str, object]:
        inputs: dict[str, object] = {
            "port.json": hashlib.sha256(descriptor_bytes).hexdigest()
        }
        for field in PUBLICATION_POLICY_FIELDS:
            if descriptor.get(field) is None:
                continue
            try:
                path = _descriptor_policy_file(port_dir, descriptor, field)
                inputs[field] = {
                    "path": descriptor[field],
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            except OSError as error:
                raise DonorUpdateError(
                    "cannot re-read migration publication policy"
                ) from error
        return inputs

    before_inputs = raw_inputs()
    authored = _derive_authored_policy_snapshot(
        port_dir, descriptor, donor, evidence_root=evidence_root
    )
    try:
        if port_path.read_bytes() != descriptor_bytes or raw_inputs() != before_inputs:
            raise DonorUpdateError(
                "migration publication policy drifted during snapshot capture"
            )
    except OSError as error:
        raise DonorUpdateError("cannot re-read migration publication policy") from error
    snapshot = _publication_policy_snapshot(
        port_dir,
        descriptor,
        donor,
        authored_policy=authored,
    )
    digest = hashlib.sha256(canonical_bytes(snapshot)).hexdigest()
    generation_digest = hashlib.sha256(canonical_bytes(before_inputs)).hexdigest()
    return descriptor, snapshot, digest, generation_digest


def _validated_migrations_dir(port_dir: Path, *, create: bool) -> Path:
    """Return a real migrations directory directly below the real port."""

    try:
        resolved_port = port_dir.resolve(strict=True)
    except OSError as error:
        raise DonorUpdateError(f"invalid port directory: {port_dir}") from error
    if not resolved_port.is_dir():
        raise DonorUpdateError(f"invalid port directory: {port_dir}")
    migrations = port_dir / "migrations"
    try:
        metadata = os.lstat(migrations)
    except FileNotFoundError:
        if not create:
            raise DonorUpdateError(
                f"missing reviewed migration directory: {migrations}"
            )
        try:
            migrations.mkdir()
            metadata = os.lstat(migrations)
        except OSError as error:
            raise DonorUpdateError(
                f"cannot create reviewed migration directory: {migrations}"
            ) from error
    except OSError as error:
        raise DonorUpdateError(
            f"invalid reviewed migration directory: {migrations}"
        ) from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise DonorUpdateError(
            f"reviewed migration directory must be a real directory: {migrations}"
        )
    try:
        resolved_migrations = migrations.resolve(strict=True)
    except OSError as error:
        raise DonorUpdateError(
            f"invalid reviewed migration directory: {migrations}"
        ) from error
    if resolved_migrations.parent != resolved_port:
        raise DonorUpdateError(
            f"reviewed migration directory must be directly beneath port: {migrations}"
        )
    return migrations


def _publication_policy_snapshot(
    port_dir: Path,
    descriptor: Mapping[str, object],
    donor: str,
    *,
    authored_policy: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    """Capture canonical, reconstructable policy semantics for one link."""

    if authored_policy is None:
        raise DonorUpdateError("authored migration policy snapshot is required")
    _descriptor_donor_record(descriptor, donor)
    documents: dict[str, object] = {}
    for field in PUBLICATION_POLICY_FIELDS:
        if descriptor.get(field) is None:
            continue
        try:
            document = json.loads(
                _descriptor_policy_file(port_dir, descriptor, field).read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError) as error:
            raise DonorUpdateError(
                f"cannot capture migration publication document {field}"
            ) from error
        documents[field] = {
            "document": document,
            "sha256": hashlib.sha256(canonical_bytes(document)).hexdigest(),
        }
    return json.loads(
        canonical_bytes(
            {
                "authoredPolicy": authored_policy,
                "descriptor": descriptor,
                "policyDocuments": documents,
            }
        )
    )


def _bound_publication_policy_digest(
    report: Mapping[str, object],
    port_dir: Path,
    *,
    evidence_root: Path,
) -> tuple[Mapping[str, object], str]:
    """Recompute this link's donor-specific policy at source or applied state."""

    try:
        descriptor_bytes = (port_dir / "port.json").read_bytes()
        descriptor = json.loads(descriptor_bytes)
    except (OSError, json.JSONDecodeError) as error:
        raise DonorUpdateError(
            "cannot load bound migration publication policy"
        ) from error
    if not isinstance(descriptor, dict) or not isinstance(
        descriptor.get("donors"), dict
    ):
        raise DonorUpdateError("bound migration publication policy is invalid")
    donor = report.get("donor")
    if not isinstance(donor, str):
        raise DonorUpdateError("migration has invalid donor identity")
    current = descriptor["donors"].get(donor)
    if not isinstance(current, dict):
        raise DonorUpdateError(f"port policy has no donor role {donor!r}")
    source = _pin_identity(report.get("from"), "$.from")
    target = _pin_identity(report.get("to"), "$.to")
    predecessor = _migration_link(report.get("predecessor"), "$.predecessor")
    current_pin = {field: current.get(field) for field in source}
    current_migration = current.get("migration")
    if current_pin == source and current_migration == predecessor:
        normalized = descriptor
    elif current_pin == target and current_migration == migration_digest(report):
        normalized = dict(descriptor)
        normalized_donors = dict(descriptor["donors"])
        normalized_record = dict(current)
        normalized_record.update(source)
        normalized_record["migration"] = predecessor
        normalized_donors[donor] = normalized_record
        normalized["donors"] = normalized_donors
    else:
        raise DonorUpdateError(
            "migration publication policy does not match source or applied pin"
        )

    # Capture against the live bytes to detect a torn/racing read.  The durable
    # binding itself is canonical donor-specific semantics, not those raw bytes.
    _capture_publication_policy(
        port_dir,
        donor,
        evidence_root=evidence_root,
        descriptor_bytes=descriptor_bytes,
        descriptor=descriptor,
    )
    authored = _derive_authored_policy_snapshot(
        port_dir, normalized, donor, evidence_root=evidence_root
    )
    try:
        if (port_dir / "port.json").read_bytes() != descriptor_bytes:
            raise DonorUpdateError(
                "migration publication policy drifted during snapshot capture"
            )
    except OSError as error:
        raise DonorUpdateError("cannot re-read migration publication policy") from error
    snapshot = _publication_policy_snapshot(
        port_dir, normalized, donor, authored_policy=authored
    )
    return snapshot, hashlib.sha256(canonical_bytes(snapshot)).hexdigest()


def _validate_publication_policy_binding(
    report: Mapping[str, object],
    port_dir: Path,
    *,
    evidence_root: Path,
) -> None:
    digest = report.get("publicationPolicyDigest")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise DonorUpdateError(
            "$.publicationPolicyDigest: finalized migration requires lowercase SHA-256"
        )
    snapshot = report.get("publicationPolicySnapshot")
    if not isinstance(snapshot, Mapping):
        raise DonorUpdateError(
            "$.publicationPolicySnapshot: finalized migration requires an object"
        )
    if digest != hashlib.sha256(canonical_bytes(snapshot)).hexdigest():
        raise DonorUpdateError("migration publication policy snapshot is stale")
    embedded_snapshot = _validate_embedded_publication_policy(
        report, evidence_root=evidence_root
    )
    live_snapshot, _ = _bound_publication_policy_digest(
        report, port_dir, evidence_root=evidence_root
    )
    donor = report.get("donor")
    if not isinstance(donor, str):
        raise DonorUpdateError("migration has invalid donor identity")
    if _donor_publication_policy_binding(
        embedded_snapshot, donor
    ) != _donor_publication_policy_binding(live_snapshot, donor):
        raise DonorUpdateError("migration publication policy is stale")


def _donor_publication_policy_binding(
    snapshot: Mapping[str, object], donor: str
) -> Mapping[str, object]:
    """Project a reconstructable snapshot onto one donor's live-head contract."""

    descriptor = snapshot.get("descriptor")
    authored = snapshot.get("authoredPolicy")
    documents = snapshot.get("policyDocuments")
    if (
        not isinstance(descriptor, Mapping)
        or not isinstance(descriptor.get("donors"), Mapping)
        or not isinstance(authored, Mapping)
        or not isinstance(documents, Mapping)
    ):
        raise DonorUpdateError("migration publication policy snapshot is invalid")
    donor_record = descriptor["donors"].get(donor)
    if not isinstance(donor_record, Mapping):
        raise DonorUpdateError("migration publication donor snapshot is invalid")
    return json.loads(
        canonical_bytes(
            {
                "authoredPolicy": authored,
                "donor": donor_record,
                "policyDocuments": documents,
            }
        )
    )


def _validate_embedded_publication_policy(
    report: Mapping[str, object], *, evidence_root: Path
) -> Mapping[str, object]:
    """Authenticate a historical link without consulting unrelated live state."""

    digest = report.get("publicationPolicyDigest")
    snapshot = report.get("publicationPolicySnapshot")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or not isinstance(snapshot, Mapping)
        or digest != hashlib.sha256(canonical_bytes(snapshot)).hexdigest()
    ):
        raise DonorUpdateError("migration publication policy snapshot is stale")
    if set(snapshot) != {"authoredPolicy", "descriptor", "policyDocuments"}:
        raise DonorUpdateError("migration publication policy snapshot is invalid")
    descriptor = snapshot.get("descriptor")
    documents = snapshot.get("policyDocuments")
    authored = snapshot.get("authoredPolicy")
    if (
        not isinstance(descriptor, Mapping)
        or not isinstance(descriptor.get("donors"), Mapping)
        or not isinstance(documents, Mapping)
        or not isinstance(authored, Mapping)
    ):
        raise DonorUpdateError("migration publication policy snapshot is invalid")
    donor = report.get("donor")
    if not isinstance(donor, str):
        raise DonorUpdateError("migration has invalid donor identity")
    donor_record = _descriptor_donor_record(descriptor, donor)
    if not isinstance(donor_record, Mapping):
        raise DonorUpdateError("migration publication donor snapshot is invalid")
    source = _pin_identity(report.get("from"), "$.from")
    if any(donor_record.get(field) != value for field, value in source.items()):
        raise DonorUpdateError("migration publication donor snapshot is stale")
    if donor_record.get("migration") != report.get("predecessor"):
        raise DonorUpdateError("migration publication predecessor snapshot is stale")
    expected_fields = {
        field
        for field in PUBLICATION_POLICY_FIELDS
        if descriptor.get(field) is not None
    }
    if set(documents) != expected_fields:
        raise DonorUpdateError("migration publication policy documents are incomplete")
    with tempfile.TemporaryDirectory(
        prefix="content-port-embedded-policy-"
    ) as directory:
        embedded_port = Path(directory)
        for field in sorted(expected_fields):
            binding = descriptor[field]
            entry = documents[field]
            if not isinstance(entry, Mapping) or set(entry) != {"document", "sha256"}:
                raise DonorUpdateError(
                    f"migration publication policy document {field} is invalid"
                )
            document = entry["document"]
            document_digest = entry["sha256"]
            if (
                not isinstance(document_digest, str)
                or document_digest
                != hashlib.sha256(canonical_bytes(document)).hexdigest()
            ):
                raise DonorUpdateError(
                    f"migration publication policy document {field} is stale"
                )
            from .descriptor import _safe_child

            try:
                policy_path = _safe_child(embedded_port, binding, f"$.{field}")
            except ContentPortError as error:
                raise DonorUpdateError(str(error)) from error
            policy_path.parent.mkdir(parents=True, exist_ok=True)
            existing = policy_path.read_bytes() if policy_path.exists() else None
            payload = canonical_bytes(document)
            if existing is not None and existing != payload:
                raise DonorUpdateError("migration publication policy bindings conflict")
            policy_path.write_bytes(payload)
        embedded_port.joinpath("port.json").write_bytes(canonical_bytes(descriptor))
        recomputed = _derive_authored_policy_snapshot(
            embedded_port, descriptor, donor, evidence_root=evidence_root
        )
    if authored != recomputed:
        raise DonorUpdateError("migration publication authored policy is stale")
    return snapshot


def _publication_policy_digest(
    port_dir: Path,
    donor: str,
    *,
    evidence_root: Path,
) -> str:
    """Hash freshly read descriptor and authored inputs guarding publication."""

    _, _, _, digest = _capture_publication_policy(
        port_dir, donor, evidence_root=evidence_root
    )
    return digest


def _derive_live_policy_snapshot(
    port_dir: Path,
    port_document: Mapping[str, object],
    donor_root: Path,
    donor: str,
    repo: Path,
    report: Mapping[str, object],
    *,
    evidence_root: Path,
) -> Mapping[str, object]:
    """Derive the only policy snapshot eligible for a new review publication."""

    authored = _derive_authored_policy_snapshot(
        port_dir, port_document, donor, evidence_root=evidence_root
    )
    references, filtered_assets, excluded_paths = _migration_policy(
        authored, evidence_root=evidence_root
    )
    current_evidence = _semantic_evidence_at_pin(
        repo,
        port_dir,
        donor_root,
        donor,
        _pin_identity(report.get("from"), "$.from"),
        port_document=port_document,
    )
    target_evidence = _validate_target_pin(
        repo,
        port_dir,
        donor_root,
        donor,
        report,
        port_document=port_document,
    )
    references = (
        *references,
        *_semantic_policy_references(current_evidence, target_evidence, donor),
    )
    return _build_policy_snapshot(references, filtered_assets, excluded_paths)


def build_migration(
    *,
    donor: str,
    repository: str,
    old_tree: Path,
    new_tree: Path,
    references: Iterable[Mapping[str, object]] = (),
    assets: Mapping[str, object] | None = None,
    tests: Iterable[Mapping[str, object]] = (),
    predecessor: str | None = None,
    excluded_paths: Iterable[str] = (),
    evidence_root: Path | None = None,
) -> dict[str, object]:
    """Build a deterministic, non-authoritative donor migration candidate."""

    references = tuple(references)
    excluded_paths = tuple(excluded_paths)
    old = identify_tree(old_tree, excluded_paths=excluded_paths)
    new = identify_tree(new_tree, excluded_paths=excluded_paths)
    old_paths = set(old.files)
    new_paths = set(new.files)
    added_paths = [
        {"newSha256": new.files[path].split(" ", 1)[1], "path": path}
        for path in sorted(new_paths - old_paths)
    ]
    removed_paths = [
        {"oldSha256": old.files[path].split(" ", 1)[1], "path": path}
        for path in sorted(old_paths - new_paths)
    ]
    changed_paths = [
        {
            "newSha256": new.files[path].split(" ", 1)[1],
            "oldSha256": old.files[path].split(" ", 1)[1],
            "path": path,
        }
        for path in sorted(old_paths & new_paths)
        if old.files[path] != new.files[path]
    ]
    asset_specs = ()
    if assets:
        asset_specs = validate_assets(
            assets,
            evidence_root=evidence_root,
            require_redistributable=False,
        )
    report: dict[str, object] = {
        "addedPaths": added_paths,
        "assets": _asset_changes(old_tree, new_tree, old, new, asset_specs),
        "authorityChanges": _authority_changes(
            old_tree, new_tree, old, new, references
        ),
        "decision": "candidate",
        "donor": donor,
        "from": {
            "commit": old.commit,
            "fileCount": old.file_count,
            "treeDigest": old.digest,
        },
        "predecessor": predecessor,
        "policy": _build_policy_snapshot(references, assets, excluded_paths),
        "removedPaths": removed_paths,
        "repository": repository,
        "schemaVersion": SCHEMA_VERSION,
        "tests": sorted(
            (dict(test) for test in tests),
            key=lambda test: tuple(test.get("command", [])),
        ),
        "to": {
            "commit": new.commit,
            "fileCount": new.file_count,
            "treeDigest": new.digest,
        },
        "changedPaths": changed_paths,
    }
    return report


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _open_publication_directory(directory: Path, *, create: bool = True) -> int:
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    try:
        return os.open(directory, _directory_flags())
    except OSError as error:
        raise DonorUpdateError(
            f"publication parent must be a real directory: {directory}"
        ) from error


def _open_migrations_publication_directory(
    port_dir: Path,
) -> tuple[Path, int, int, bool]:
    """Open the migration directory beneath a held, non-symlink port handle."""

    port_fd = _open_publication_directory(port_dir, create=False)
    created = False
    try:
        try:
            os.mkdir("migrations", dir_fd=port_fd)
            created = True
            os.fsync(port_fd)
        except FileExistsError:
            pass
        try:
            migrations_fd = os.open("migrations", _directory_flags(), dir_fd=port_fd)
        except OSError as error:
            raise DonorUpdateError(
                "reviewed migration directory must be a real directory: "
                f"{port_dir / 'migrations'}"
            ) from error
        current = os.stat("migrations", dir_fd=port_fd, follow_symlinks=False)
        opened = os.fstat(migrations_fd)
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            os.close(migrations_fd)
            raise DonorUpdateError("reviewed migration directory changed while opening")
        return port_dir / "migrations", port_fd, migrations_fd, created
    except BaseException:
        os.close(port_fd)
        raise


def _remove_anchored_directory(parent_fd: int, name: str, directory_fd: int) -> None:
    """Remove a created directory only while its pathname names the held inode."""

    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    opened = os.fstat(directory_fd)
    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
        return
    try:
        os.rmdir(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except OSError:
        pass


def _read_publication_path(directory_fd: int, name: str) -> bytes | None:
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory_fd,
        )
    except FileNotFoundError:
        return None
    except OSError as error:
        raise DonorUpdateError(f"cannot preserve publication target {name}") from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise DonorUpdateError(f"publication target must be a regular file: {name}")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(descriptor)


def _assert_publication_parent(directory: Path, directory_fd: int) -> None:
    """Require a held publication handle to remain the pathname's directory."""

    try:
        current = os.stat(directory, follow_symlinks=False)
        opened = os.fstat(directory_fd)
    except OSError as error:
        raise DonorUpdateError(
            f"publication parent changed during write: {directory}"
        ) from error
    if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (
        opened.st_dev,
        opened.st_ino,
    ):
        raise DonorUpdateError(f"publication parent changed during write: {directory}")


def _atomic_write_at(
    directory_fd: int, name: str, data: bytes, checkpoint_name: str
) -> None:
    temporary: str | None = None
    descriptor: int | None = None
    try:
        for _ in range(128):
            candidate = f".{name}.tmp-{secrets.token_hex(16)}"
            try:
                descriptor = os.open(
                    candidate,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o666,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                continue
            temporary = candidate
            break
        if descriptor is None or temporary is None:
            raise DonorUpdateError("cannot allocate secure publication temporary")
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(
            temporary,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary = None
        os.fsync(directory_fd)
        checkpoint(checkpoint_name)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
                os.fsync(directory_fd)
            except FileNotFoundError:
                pass


def _atomic_write(
    output: Path,
    data: bytes,
    checkpoint_name: str,
    *,
    directory_fd: int | None = None,
) -> None:
    owned_directory_fd = directory_fd is None
    if directory_fd is None:
        directory_fd = _open_publication_directory(output.parent)
    try:
        _atomic_write_at(directory_fd, output.name, data, checkpoint_name)
    finally:
        if owned_directory_fd:
            os.close(directory_fd)


def _restore_publication_path(
    output: Path, previous: bytes | None, *, directory_fd: int | None = None
) -> None:
    owned_directory_fd = directory_fd is None
    if directory_fd is None:
        directory_fd = _open_publication_directory(output.parent, create=False)
    try:
        if previous is None:
            try:
                os.unlink(output.name, dir_fd=directory_fd)
            except FileNotFoundError:
                return
            os.fsync(directory_fd)
            return
        _atomic_write(
            output,
            previous,
            f"after-migration-publication-restore:{output.name}",
            directory_fd=directory_fd,
        )
    finally:
        if owned_directory_fd:
            os.close(directory_fd)


def _write_policy_bound_artifact(
    output: Path,
    data: bytes,
    checkpoint_name: str,
    *,
    port_dir: Path,
    donor: str,
    evidence_root: Path,
    policy_digest: str,
    directory_fd: int | None = None,
    anchored_directories: Sequence[tuple[Path, int]] = (),
) -> bytes | None:
    """Publish atomically and roll back if live policy changes around the write."""

    owned_directory_fd = directory_fd is None
    if directory_fd is None:
        directory_fd = _open_publication_directory(output.parent)
    try:
        publication_directories = ((output.parent, directory_fd), *anchored_directories)
        for directory, descriptor in publication_directories:
            _assert_publication_parent(directory, descriptor)
        previous = _read_publication_path(directory_fd, output.name)
        if policy_digest != _publication_policy_digest(
            port_dir, donor, evidence_root=evidence_root
        ):
            raise DonorUpdateError("migration publication policy drifted before write")
        try:
            _atomic_write(
                output,
                data,
                checkpoint_name,
                directory_fd=directory_fd,
            )
            after_policy_digest = _publication_policy_digest(
                port_dir, donor, evidence_root=evidence_root
            )
            parent_error: DonorUpdateError | None = None
            try:
                for directory, descriptor in publication_directories:
                    _assert_publication_parent(directory, descriptor)
            except DonorUpdateError as error:
                parent_error = error
            if policy_digest != after_policy_digest:
                raise DonorUpdateError(
                    "migration publication policy drifted during write"
                )
            if parent_error is not None:
                raise parent_error
        except BaseException as error:
            try:
                _restore_publication_path(output, previous, directory_fd=directory_fd)
            except BaseException as cleanup_error:
                error.add_note(f"publication rollback failed: {cleanup_error}")
            raise
        return previous
    finally:
        if owned_directory_fd:
            os.close(directory_fd)


def write_candidate_migration(output: Path, **kwargs: object) -> dict[str, object]:
    report = build_migration(**kwargs)  # type: ignore[arg-type]
    _atomic_write(
        output,
        canonical_bytes(report),
        f"after-donor-update-write:{output.name}",
    )
    return report


def migration_digest(report: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_bytes(report)).hexdigest()


def migration_filename(report: Mapping[str, object]) -> str:
    return f"{migration_digest(report)}.json"


def _migration_link(value: object, pointer: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DonorUpdateError(f"{pointer}: expected null or lowercase SHA-256")
    return value


def _pin_identity(value: object, pointer: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "commit",
        "fileCount",
        "treeDigest",
    }:
        raise DonorUpdateError(f"{pointer}: expected exact pin identity")
    commit = value["commit"]
    digest = value["treeDigest"]
    count = value["fileCount"]
    if (
        not isinstance(commit, str)
        or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
    ):
        raise DonorUpdateError(f"{pointer}.commit: expected 40 lowercase hex")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise DonorUpdateError(f"{pointer}.treeDigest: expected lowercase SHA-256")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise DonorUpdateError(f"{pointer}.fileCount: expected a positive integer")
    return value


def _validate_reviewed_contents(report: Mapping[str, object]) -> None:
    for field in ("authorityChanges", "assets"):
        changes = report.get(field)
        if not isinstance(changes, list):
            raise DonorUpdateError(f"$.{field}: expected a list")
        for index, change in enumerate(changes):
            if not isinstance(change, dict):
                raise DonorUpdateError(f"$.{field}[{index}]: expected an object")
            disposition = change.get("reviewerDisposition")
            if disposition not in REVIEWED_DISPOSITIONS:
                raise DonorUpdateError(
                    f"$.{field}[{index}].reviewerDisposition: review is incomplete"
                )
            if field == "assets" and change.get("permission") != "redistributable":
                raise DonorUpdateError(
                    f"asset {change.get('key')}: permission is {change.get('permission')}"
                )
    tests = report.get("tests")
    if not isinstance(tests, list):
        raise DonorUpdateError("$.tests: reviewed migration needs recorded tests")
    commands: list[tuple[str, ...]] = []
    for index, evidence in enumerate(tests):
        if not isinstance(evidence, dict) or set(evidence) != {"command", "result"}:
            raise DonorUpdateError(f"$.tests[{index}]: expected exact command evidence")
        command = evidence["command"]
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
            or evidence["result"] != "passed"
        ):
            raise DonorUpdateError(f"$.tests[{index}]: test evidence is not passing")
        commands.append(tuple(command))
    if tuple(sorted(commands)) != tuple(sorted(REQUIRED_REVIEW_COMMANDS)):
        raise DonorUpdateError("$.tests: required donor migration commands are missing")


def run_review_commands(repo: Path) -> tuple[Mapping[str, object], ...]:
    evidence: list[Mapping[str, object]] = []
    for command in REQUIRED_REVIEW_COMMANDS:
        try:
            result = subprocess.run(
                command,
                cwd=repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as error:
            raise DonorUpdateError(
                f"cannot run migration review command: {' '.join(command)}"
            ) from error
        if result.returncode:
            detail = result.stderr.decode(errors="replace").splitlines()[-20:]
            raise DonorUpdateError(
                f"migration review command failed: {' '.join(command)}\n"
                + "\n".join(detail)
            )
        evidence.append({"command": list(command), "result": "passed"})
    return tuple(evidence)


def _semantic_evidence_at_pin(
    repo: Path,
    port_dir: Path,
    donor_root: Path,
    donor: str,
    pin: Mapping[str, object],
    *,
    port_document: Mapping[str, object] | None = None,
) -> Mapping[str, str]:
    """Derive production semantics from authenticated, detached donor commits."""

    if port_document is None:
        try:
            port = json.loads((port_dir / "port.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise DonorUpdateError("cannot load target-pin port policy") from error
    else:
        port = port_document
    if not isinstance(port, dict) or not isinstance(port.get("donors"), dict):
        raise DonorUpdateError("target-pin port policy has no donors object")
    selected = _pin_identity(pin, "$.pin")
    if donor not in port["donors"]:
        raise DonorUpdateError(f"target-pin port policy has no donor role {donor!r}")

    checkouts = _validated_donor_checkouts(port, donor_root)
    donor_records: list[tuple[str, Mapping[str, object], Path, str]] = []
    for role, raw in sorted(port["donors"].items()):
        if not isinstance(raw, Mapping):
            raise DonorUpdateError(f"invalid donor record {role!r}")
        commit = selected["commit"] if role == donor else raw.get("commit")
        if not isinstance(commit, str):
            raise DonorUpdateError(f"invalid donor record {role!r}")
        donor_records.append((role, raw, checkouts[role], commit))

    semantic_evidence: Mapping[str, str] | None = None
    # Keep the detached descriptor beneath the repository so descriptor loading
    # retains the repository root used by content-addressed permission evidence.
    with tempfile.TemporaryDirectory(
        prefix=".content-port-target-pin-", dir=repo
    ) as directory:
        temporary = Path(directory)
        temporary_port = temporary / "ports" / port_dir.name
        temporary_donors = temporary / "donors"
        shutil.copytree(port_dir, temporary_port)
        temporary_donors.mkdir()
        worktrees: list[tuple[Path, Path]] = []
        try:
            for role, raw, checkout, commit in donor_records:
                root = raw["root"]
                assert isinstance(root, str)
                worktree = temporary_donors / root
                worktree.parent.mkdir(parents=True, exist_ok=True)
                _run_git(
                    checkout,
                    "worktree",
                    "add",
                    "--detach",
                    str(worktree),
                    commit,
                )
                worktrees.append((checkout, worktree))

            proposed = dict(port)
            proposed_donors = {role: dict(raw) for role, raw in port["donors"].items()}
            for role, frozen_record in proposed_donors.items():
                try:
                    frozen_pin = {
                        field: frozen_record[field]
                        for field in ("commit", "fileCount", "treeDigest")
                    }
                except KeyError as error:
                    raise DonorUpdateError(f"invalid donor record {role!r}") from error
                _pin_identity(frozen_pin, f"$.donors.{role}")
                frozen_record["genesis"] = frozen_pin
                frozen_record["migration"] = None
            proposed_record = proposed_donors[donor]
            proposed_record.update(selected)
            # The temporary descriptor represents the proposed pin as its own
            # reviewed baseline. The real predecessor linkage remains enforced
            # independently by finalize_migration and descriptor-chain loading.
            proposed_record["genesis"] = dict(selected)
            proposed_record["migration"] = None
            proposed["donors"] = proposed_donors
            (temporary_port / "port.json").write_bytes(canonical_bytes(proposed))

            from .descriptor import load_port
            from .donors import authenticate_donors
            from .materialize import derive_desired_state
            from .sources import resolve_port_sources

            descriptor = load_port(temporary_port, temporary_donors)
            authenticate_donors(descriptor.donors, require_git=True)
            _, state = resolve_port_sources(descriptor, repo)
            semantic_evidence = state.semantic_evidence
            derive_desired_state(descriptor, repo)
        except ContentPortError as error:
            raise DonorUpdateError(
                f"target pin production check failed: {error}"
            ) from error
        finally:
            _remove_worktrees(reversed(worktrees), primary_error=sys.exception())
    if semantic_evidence is None:
        raise DonorUpdateError("target pin production check produced no evidence")
    return semantic_evidence


def _validate_target_pin(
    repo: Path,
    port_dir: Path,
    donor_root: Path,
    donor: str,
    report: Mapping[str, object],
    *,
    port_document: Mapping[str, object] | None = None,
) -> Mapping[str, str]:
    """Run production source and materialization validation at a proposed pin."""

    return _semantic_evidence_at_pin(
        repo,
        port_dir,
        donor_root,
        donor,
        _pin_identity(report.get("to"), "$.to"),
        port_document=port_document,
    )


def finalize_migration(
    candidate: Path,
    port_dir: Path,
    donor_root: Path | None = None,
    repo: Path | None = None,
    evidence_root: Path | None = None,
) -> tuple[Path, Path]:
    """Publish a human-reviewed record and an exact, non-mutating pin proposal."""

    try:
        report = json.loads(candidate.read_text(encoding="utf-8"))
        port_bytes = (port_dir / "port.json").read_bytes()
        port = json.loads(port_bytes)
    except (OSError, json.JSONDecodeError) as error:
        raise DonorUpdateError(
            "cannot load migration candidate or port policy"
        ) from error
    if not isinstance(report, dict) or set(report) != MIGRATION_KEYS:
        raise DonorUpdateError("migration candidate has fields outside the contract")
    if report.get("schemaVersion") != SCHEMA_VERSION:
        raise DonorUpdateError("migration candidate has unsupported schemaVersion")
    if report.get("decision") != "reviewed":
        raise DonorUpdateError("migration candidate is not reviewed")
    _migration_link(report.get("predecessor"), "$.predecessor")
    donor = report.get("donor")
    repository = report.get("repository")
    if not isinstance(donor, str) or not isinstance(repository, str):
        raise DonorUpdateError("migration candidate has invalid donor identity")
    source = _pin_identity(report.get("from"), "$.from")
    target = _pin_identity(report.get("to"), "$.to")
    if source["commit"] == target["commit"]:
        raise DonorUpdateError(f"donor {donor}: reviewed migration is a no-op")
    _validate_reviewed_contents(report)
    if repo is None:
        repo = port_dir.resolve().parents[3]
    repo = repo.resolve()
    if evidence_root is None:
        evidence_root = repo
    if not isinstance(port, dict) or not isinstance(port.get("donors"), dict):
        raise DonorUpdateError("port policy has no donors object")
    current = port["donors"].get(donor)
    if not isinstance(current, dict):
        raise DonorUpdateError(f"port policy has no donor role {donor!r}")
    if current.get("repository") != repository:
        raise DonorUpdateError(f"donor {donor}: repository differs from port policy")
    predecessor = report.get("predecessor")
    if predecessor != current.get("migration"):
        raise DonorUpdateError(
            f"donor {donor}: migration predecessor is not the published pin"
        )
    for field in ("commit", "treeDigest", "fileCount"):
        if current.get(field) != source[field]:
            raise DonorUpdateError(f"donor {donor}: candidate source {field} is stale")
    if donor_root is None:
        donor_root = Path(
            os.environ.get("CONTENT_PORT_DONOR_ROOT", repo / ".references")
        )
    _validated_donor_checkouts(port, donor_root)
    (
        port,
        publication_policy_snapshot,
        publication_policy_digest,
        publication_generation_digest,
    ) = _capture_publication_policy(
        port_dir,
        donor,
        evidence_root=evidence_root,
        descriptor_bytes=port_bytes,
        descriptor=port,
    )
    if list(run_review_commands(repo)) != report["tests"]:
        raise DonorUpdateError("$.tests: recorded command evidence is stale")
    live_policy = _derive_live_policy_snapshot(
        port_dir,
        port,
        donor_root,
        donor,
        repo,
        report,
        evidence_root=evidence_root,
    )
    if report.get("policy") != live_policy:
        raise DonorUpdateError("migration policy snapshot differs from live policy")
    verify_migration_evidence(
        report,
        port_dir,
        _validated_donor_checkout(
            donor_root, current.get("root"), f"$.donors.{donor}.root"
        ),
        evidence_root=evidence_root,
        donor_root=donor_root,
        repo=repo,
        port_document=port,
    )
    if publication_generation_digest != _publication_policy_digest(
        port_dir, donor, evidence_root=evidence_root
    ):
        raise DonorUpdateError(
            "migration publication policy drifted during evidence verification"
        )
    finalized_report = dict(report)
    finalized_report["schemaVersion"] = FINALIZED_MIGRATION_SCHEMA_VERSION
    finalized_report["publicationPolicyDigest"] = publication_policy_digest
    finalized_report["publicationPolicySnapshot"] = publication_policy_snapshot
    digest = migration_digest(finalized_report)
    migrations, port_fd, migrations_fd, migrations_created = (
        _open_migrations_publication_directory(port_dir)
    )
    record_path = migrations / f"{digest}.json"
    try:
        try:
            previous_record = _write_policy_bound_artifact(
                record_path,
                canonical_bytes(finalized_report),
                f"after-migration-finalize-write:{record_path.name}",
                port_dir=port_dir,
                donor=donor,
                evidence_root=evidence_root,
                policy_digest=publication_generation_digest,
                directory_fd=migrations_fd,
                anchored_directories=((port_dir, port_fd),),
            )
        except BaseException:
            if migrations_created:
                _remove_anchored_directory(port_fd, "migrations", migrations_fd)
            raise
        proposed_donor = dict(current)
        proposed_donor.update(target)
        proposed_donor["migration"] = digest
        proposal = {
            "donor": donor,
            "migration": digest,
            "port": port_dir.name,
            "publicationPolicyDigest": publication_policy_digest,
            "proposedDonorRecord": proposed_donor,
            "schemaVersion": FINALIZED_MIGRATION_SCHEMA_VERSION,
        }
        proposal_path = candidate.with_name("donor-port-update.json")
        try:
            _write_policy_bound_artifact(
                proposal_path,
                canonical_bytes(proposal),
                f"after-migration-finalize-proposal:{proposal_path.name}",
                port_dir=port_dir,
                donor=donor,
                evidence_root=evidence_root,
                policy_digest=publication_generation_digest,
                anchored_directories=(
                    (port_dir, port_fd),
                    (migrations, migrations_fd),
                ),
            )
        except BaseException as error:
            try:
                _restore_publication_path(
                    record_path, previous_record, directory_fd=migrations_fd
                )
            except BaseException as cleanup_error:
                error.add_note(f"record publication rollback failed: {cleanup_error}")
            if migrations_created:
                _remove_anchored_directory(port_fd, "migrations", migrations_fd)
            raise
        return record_path, proposal_path
    finally:
        os.close(migrations_fd)
        os.close(port_fd)


def validate_reviewed_migration(
    report: Mapping[str, object],
    *,
    donor: str,
    repository: str | None = None,
    from_commit: str,
    from_tree_digest: str | None = None,
    from_file_count: int | None = None,
    to_commit: str,
    to_tree_digest: str | None = None,
    to_file_count: int | None = None,
    expected_assets: Mapping[str, Mapping[str, object]] | None = None,
    port_dir: Path | None = None,
    donor_checkout: Path | None = None,
    review_repo: Path | None = None,
    evidence_root: Path | None = None,
    validate_live_publication_policy: bool = True,
) -> None:
    """Require an exact reviewed record for a descriptor pin transition."""

    embedded_publication_policy: Mapping[str, object] | None = None
    schema_version = report.get("schemaVersion")
    if schema_version not in (SCHEMA_VERSION, FINALIZED_MIGRATION_SCHEMA_VERSION):
        raise DonorUpdateError("migration record has unsupported schemaVersion")
    if schema_version == FINALIZED_MIGRATION_SCHEMA_VERSION:
        if (
            "publicationPolicyDigest" not in report
            or "publicationPolicySnapshot" not in report
        ):
            raise DonorUpdateError(
                "finalized migration record requires publicationPolicyDigest and publicationPolicySnapshot"
            )
        if set(report) != FINALIZED_MIGRATION_KEYS:
            raise DonorUpdateError(
                "finalized migration record has fields outside the contract"
            )
        if validate_live_publication_policy and port_dir is None:
            raise DonorUpdateError(
                "finalized migration record needs live publication policy"
            )
        if evidence_root is None:
            evidence_root = (
                review_repo
                if review_repo is not None
                else Path(__file__).resolve().parents[2]
            )
        if validate_live_publication_policy:
            assert port_dir is not None
            _validate_publication_policy_binding(
                report, port_dir, evidence_root=evidence_root
            )
        else:
            embedded_publication_policy = _validate_embedded_publication_policy(
                report, evidence_root=evidence_root
            )
    if schema_version == SCHEMA_VERSION and set(report) != MIGRATION_KEYS:
        raise DonorUpdateError(
            "legacy migration record has fields outside the contract"
        )
    if report.get("decision") != "reviewed":
        raise DonorUpdateError(f"donor {donor}: migration record is not reviewed")
    _migration_link(report.get("predecessor"), "$.predecessor")
    if report.get("donor") != donor:
        raise DonorUpdateError(f"donor {donor}: migration record names another donor")
    if repository is not None and report.get("repository") != repository:
        raise DonorUpdateError(f"donor {donor}: migration repository is stale")
    source = report.get("from")
    target = report.get("to")
    if not isinstance(source, dict) or source.get("commit") != from_commit:
        raise DonorUpdateError(f"donor {donor}: migration source pin is stale")
    if not isinstance(target, dict) or target.get("commit") != to_commit:
        raise DonorUpdateError(f"donor {donor}: migration target pin is stale")
    if source == target:
        raise DonorUpdateError(f"donor {donor}: reviewed migration is a no-op")
    expected_source = {
        "treeDigest": from_tree_digest,
        "fileCount": from_file_count,
    }
    expected_target = {
        "treeDigest": to_tree_digest,
        "fileCount": to_file_count,
    }
    for field, expected in expected_source.items():
        if expected is not None and source.get(field) != expected:
            raise DonorUpdateError(f"donor {donor}: migration source {field} is stale")
    for field, expected in expected_target.items():
        if expected is not None and target.get(field) != expected:
            raise DonorUpdateError(f"donor {donor}: migration target {field} is stale")
    if report.get("decision") not in REVIEW_DECISIONS:
        raise DonorUpdateError(f"donor {donor}: unknown review decision")
    _validate_reviewed_contents(report)
    if review_repo is None:
        review_repo = Path(__file__).resolve().parents[2]
    if evidence_root is None:
        evidence_root = review_repo
    if list(run_review_commands(review_repo)) != report["tests"]:
        raise DonorUpdateError("$.tests: recorded command evidence is stale")
    if expected_assets is not None:
        changes = report.get("assets")
        if not isinstance(changes, list):
            raise DonorUpdateError(f"donor {donor}: migration assets are missing")
        for index, change in enumerate(changes):
            if not isinstance(change, dict) or not isinstance(change.get("key"), str):
                raise DonorUpdateError(f"donor {donor}: invalid asset change {index}")
            key = str(change["key"])
            expected = expected_assets.get(key)
            if expected is None:
                raise DonorUpdateError(f"donor {donor}: unclassified asset {key}")
            if change.get("conversionCommand") != expected.get("conversionCommand"):
                raise DonorUpdateError(f"asset {key}: conversion command drift")
            if change.get("permission") != expected.get("permission"):
                raise DonorUpdateError(f"asset {key}: permission review is stale")
            if change.get("permission") != "redistributable":
                raise DonorUpdateError(
                    f"asset {key}: permission is {change.get('permission')}"
                )
    if port_dir is None or donor_checkout is None:
        raise DonorUpdateError(
            f"donor {donor}: reviewed migration needs authenticated from/to trees"
        )
    verify_migration_evidence(
        report,
        port_dir,
        donor_checkout,
        evidence_root=evidence_root,
        publication_policy_snapshot=embedded_publication_policy,
    )


def load_reviewed_migration(
    migrations: Path,
    digest: str,
    *,
    evidence_root: Path | None = None,
) -> Mapping[str, object]:
    checked_migrations = _validated_migrations_dir(migrations.parent, create=False)
    if checked_migrations != migrations:
        raise DonorUpdateError(
            f"reviewed migration directory must be directly beneath port: {migrations}"
        )
    path = checked_migrations / f"{digest}.json"
    if not path.is_file():
        raise DonorUpdateError(f"missing reviewed migration record: {path}")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DonorUpdateError(f"invalid migration record: {path}") from error
    if not isinstance(report, dict) or migration_digest(report) != digest:
        raise DonorUpdateError(f"migration record filename is stale: {path}")
    schema_version = report.get("schemaVersion")
    if schema_version == FINALIZED_MIGRATION_SCHEMA_VERSION:
        if (
            "publicationPolicyDigest" not in report
            or "publicationPolicySnapshot" not in report
        ):
            raise DonorUpdateError(
                "finalized migration record requires publicationPolicyDigest and publicationPolicySnapshot"
            )
        if set(report) != FINALIZED_MIGRATION_KEYS:
            raise DonorUpdateError(
                "finalized migration record has fields outside the contract"
            )
        if evidence_root is None:
            evidence_root = migrations.parent.resolve().parents[3]
        _validate_publication_policy_binding(
            report,
            migrations.parent,
            evidence_root=evidence_root,
        )
    elif schema_version == SCHEMA_VERSION:
        if set(report) != MIGRATION_KEYS:
            raise DonorUpdateError(
                "legacy migration record has fields outside the contract"
            )
    else:
        raise DonorUpdateError("migration record has unsupported schemaVersion")
    return report


def _descriptor_donor_record(
    port_document: Mapping[str, object], donor: str
) -> Mapping[str, object]:
    donors = port_document.get("donors")
    if not isinstance(donors, dict):
        raise DonorUpdateError("port descriptor has no donors object")
    record = donors.get(donor)
    if record is None:
        matches = [
            candidate
            for candidate in donors.values()
            if isinstance(candidate, dict) and candidate.get("name") == donor
        ]
        if len(matches) != 1:
            raise DonorUpdateError(f"unknown donor {donor!r}")
        record = matches[0]
    if not isinstance(record, dict):
        raise DonorUpdateError(f"invalid donor record {donor!r}")
    return record


def _allocation_policy(
    port_dir: Path, port_document: Mapping[str, object]
) -> Mapping[str, object] | None:
    filename = port_document.get("allocationLock")
    if filename is None:
        return None
    try:
        document = json.loads(
            _descriptor_policy_file(
                port_dir, port_document, "allocationLock"
            ).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise DonorUpdateError("cannot load migration allocation policy") from error
    if not isinstance(document, Mapping):
        raise DonorUpdateError("migration allocation policy is invalid")
    return document


def _policy_references(
    adaptations: Mapping[str, object],
    donor: str,
    allocations: Mapping[str, object] | None = None,
) -> tuple[Mapping[str, object], ...]:
    """Translate donor-backed authority decisions into field comparisons."""

    references: list[Mapping[str, object]] = []
    donor_fields = adaptations.get("donorFieldRoles", {})

    def add_map_reference(source: object, path: object, authority: str) -> None:
        if not isinstance(source, str) or not isinstance(path, str):
            return
        references.append(
            {
                "authority": authority,
                "jsonPointer": f"/{path}",
                "semanticIdentity": f"map:{source}.{path}",
                "sourcePath": f"data/maps/{source}/map.json",
            }
        )

    if isinstance(donor_fields, Mapping) and donor in donor_fields:
        for decision in adaptations.get("adaptations", []):
            if isinstance(decision, Mapping):
                add_map_reference(decision.get("source"), decision.get("path"), donor)

    fallback_policy = adaptations.get("contentFallback", {})
    fallback_maps: set[str] = set()
    if isinstance(fallback_policy, Mapping):
        raw_fallback = fallback_policy.get("maps", [])
        if isinstance(raw_fallback, (list, tuple)):
            fallback_maps = {name for name in raw_fallback if isinstance(name, str)}
    if allocations is not None:
        allocation_maps = allocations.get("maps", [])
        if isinstance(allocation_maps, list):
            for item in allocation_maps:
                if not isinstance(item, Mapping):
                    continue
                source = item.get("name")
                if not isinstance(source, str):
                    continue
                selected_role = "mechanical" if source in fallback_maps else "content"
                if donor == selected_role:
                    references.append(
                        {
                            "authority": donor,
                            "jsonPointer": "",
                            "recordType": "map",
                            "semanticIdentity": f"map:{source}",
                            "sourcePath": f"data/maps/{source}/map.json",
                        }
                    )
    for policy_key in (
        "warpReindexes",
        "warpRemovals",
        "berryTreeAllocations",
        "deferredEdges",
    ):
        for decision in adaptations.get(policy_key, []):
            if not isinstance(decision, Mapping):
                continue
            source = decision.get("source")
            selected_role = (
                "mechanical"
                if isinstance(source, str) and source in fallback_maps
                else "content"
            )
            if donor == selected_role:
                add_map_reference(source, decision.get("path"), donor)

    for decision in adaptations.get("mapFieldDecisions", []):
        if (
            not isinstance(decision, dict)
            or not isinstance(donor_fields, Mapping)
            or donor not in donor_fields
        ):
            continue
        map_name = decision.get("map")
        field = decision.get("field")
        if not isinstance(map_name, str) or not isinstance(field, str):
            continue
        references.append(
            {
                "authority": donor,
                "jsonPointer": f"/{field}",
                "semanticIdentity": f"map:{map_name}.{field}",
                "sourcePath": f"data/maps/{map_name}/map.json",
            }
        )
    layout_decisions = (
        list(adaptations.get("layoutHeaderDecisions", []))
        if isinstance(donor_fields, Mapping) and donor in donor_fields
        else []
    )
    if donor == "content":
        layout_decisions.extend(adaptations.get("layoutTilesetRemaps", []))
    for decision in layout_decisions:
        if not isinstance(decision, dict):
            continue
        layout_id = decision.get("layout")
        field = decision.get("field")
        if not isinstance(layout_id, str) or not isinstance(field, str):
            continue
        references.append(
            {
                "authority": donor,
                "field": field,
                "jsonPointer": f"/layouts/@{layout_id}/{field}",
                "layoutId": layout_id,
                "semanticIdentity": f"layout:{layout_id}.{field}",
                "sourcePath": "data/layouts/layouts.json",
            }
        )
    field_authorities = adaptations.get("layoutFieldAuthorities", [])
    binary_authorities = adaptations.get("layoutBinaryAuthorities", [])
    if isinstance(binary_authorities, (list, tuple)):
        for layout_policy in binary_authorities:
            if (
                not isinstance(layout_policy, Mapping)
                or layout_policy.get("sourceRole") != donor
            ):
                continue
            layout_id = layout_policy.get("layout")
            if not isinstance(layout_id, str):
                continue
            references.append(
                {
                    "authority": donor,
                    "jsonPointer": f"/layouts/@{layout_id}",
                    "layoutId": layout_id,
                    "recordType": "layout",
                    "semanticIdentity": f"layout:{layout_id}",
                    "sourcePath": "data/layouts/layouts.json",
                }
            )
    if isinstance(field_authorities, (list, tuple)) and isinstance(
        binary_authorities, (list, tuple)
    ):
        for field_policy in field_authorities:
            if not isinstance(field_policy, Mapping):
                continue
            field = field_policy.get("field")
            layout_role = field_policy.get("layoutRole")
            source_role = field_policy.get("sourceRole")
            if (
                not isinstance(source_role, str)
                or not isinstance(field, str)
                or not isinstance(layout_role, str)
                or donor not in {layout_role, source_role}
            ):
                continue
            for layout_policy in binary_authorities:
                if (
                    not isinstance(layout_policy, Mapping)
                    or layout_policy.get("sourceRole") != layout_role
                ):
                    continue
                layout_id = layout_policy.get("layout")
                if not isinstance(layout_id, str):
                    continue
                references.append(
                    {
                        "authority": donor,
                        "field": field,
                        "jsonPointer": f"/layouts/@{layout_id}/{field}",
                        "layoutId": layout_id,
                        "semanticIdentity": f"layout:{layout_id}.{field}",
                        "sourcePath": "data/layouts/layouts.json",
                    }
                )
    section_authorities = adaptations.get("sectionMetadataAuthorities", [])
    if isinstance(section_authorities, (list, tuple)):
        for section_policy in section_authorities:
            if (
                not isinstance(section_policy, Mapping)
                or section_policy.get("sourceRole") != donor
            ):
                continue
            section = section_policy.get("section")
            symbol = section_policy.get("sourceSymbol")
            if not isinstance(section, str) or not isinstance(symbol, str):
                continue
            references.append(
                {
                    "authority": donor,
                    "jsonPointer": "",
                    "recordType": "section",
                    "sectionSymbol": symbol,
                    "semanticIdentity": f"section:{section}",
                    "sourcePath": "src/data/region_map",
                }
            )
    unique: list[Mapping[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for reference in references:
        identity = tuple(
            reference.get(field)
            for field in (
                "authority",
                "sourcePath",
                "jsonPointer",
                "semanticIdentity",
                "layoutId",
                "field",
                "recordType",
                "sectionSymbol",
            )
        )
        if identity not in seen:
            seen.add(identity)
            unique.append(reference)
    return tuple(unique)


def _without_disposition(changes: object, pointer: str) -> list[dict[str, object]]:
    if not isinstance(changes, list):
        raise DonorUpdateError(f"{pointer}: expected a list")
    result: list[dict[str, object]] = []
    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            raise DonorUpdateError(f"{pointer}[{index}]: expected an object")
        result.append(
            {
                key: value
                for key, value in change.items()
                if key != "reviewerDisposition"
            }
        )
    return result


def verify_migration_evidence(
    report: Mapping[str, object],
    port_dir: Path,
    donor_checkout: Path,
    *,
    evidence_root: Path | None = None,
    donor_root: Path | None = None,
    repo: Path | None = None,
    port_document: Mapping[str, object] | None = None,
    publication_policy_snapshot: Mapping[str, object] | None = None,
) -> None:
    """Recompute every claimed drift field from the two authenticated commits."""

    if publication_policy_snapshot is not None:
        descriptor = publication_policy_snapshot.get("descriptor")
        documents = publication_policy_snapshot.get("policyDocuments")
        if not isinstance(descriptor, Mapping) or not isinstance(documents, Mapping):
            raise DonorUpdateError("migration publication policy snapshot is invalid")
        if repo is None:
            try:
                repo = port_dir.resolve().parents[3]
            except IndexError:
                if evidence_root is None:
                    raise DonorUpdateError(
                        "cannot recompute migration semantic evidence"
                    )
                repo = evidence_root.resolve()
        with tempfile.TemporaryDirectory(
            prefix=".content-port-historical-policy-", dir=repo
        ) as directory:
            historical_port = Path(directory) / "ports" / port_dir.name
            historical_port.mkdir(parents=True)
            historical_descriptor = json.loads(canonical_bytes(descriptor))
            donors = historical_descriptor.get("donors")
            if not isinstance(donors, dict):
                raise DonorUpdateError(
                    "migration publication donor snapshot is invalid"
                )
            for role, raw in donors.items():
                if not isinstance(raw, dict):
                    raise DonorUpdateError(f"invalid donor record {role!r}")
                raw["genesis"] = {
                    field: raw[field] for field in ("commit", "fileCount", "treeDigest")
                }
                raw["migration"] = None
            for field, entry in documents.items():
                if not isinstance(field, str) or not isinstance(entry, Mapping):
                    raise DonorUpdateError(
                        "migration publication policy snapshot is invalid"
                    )
                from .descriptor import _safe_child

                path = _safe_child(
                    historical_port, historical_descriptor[field], f"$.{field}"
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(canonical_bytes(entry["document"]))
            historical_port.joinpath("port.json").write_bytes(
                canonical_bytes(historical_descriptor)
            )
            verify_migration_evidence(
                report,
                historical_port,
                donor_checkout,
                evidence_root=evidence_root,
                donor_root=donor_root,
                repo=repo,
                port_document=historical_descriptor,
            )
        return

    donor = report.get("donor")
    repository = report.get("repository")
    source = _pin_identity(report.get("from"), "$.from")
    target = _pin_identity(report.get("to"), "$.to")
    if not isinstance(donor, str) or not isinstance(repository, str):
        raise DonorUpdateError("migration has invalid donor identity")
    if evidence_root is None:
        evidence_root = port_dir.resolve().parent
    references, filtered_assets, excluded_paths = _migration_policy(
        report.get("policy"), evidence_root=evidence_root
    )
    semantic_references = tuple(
        reference
        for reference in references
        if reference.get("recordType") == "semantic-evidence"
    )
    if semantic_references:
        if port_document is None:
            try:
                port_document = json.loads(
                    (port_dir / "port.json").read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as error:
                raise DonorUpdateError(
                    "cannot recompute migration semantic evidence"
                ) from error
        if not isinstance(port_document, Mapping):
            raise DonorUpdateError("cannot recompute migration semantic evidence")
        donor_record = _descriptor_donor_record(port_document, donor)
        donor_root_name = donor_record.get("root")
        if not isinstance(donor_root_name, str):
            raise DonorUpdateError("cannot recompute migration semantic evidence")
        if donor_root is None:
            donor_root = donor_checkout.resolve()
            for _ in PurePosixPath(donor_root_name).parts:
                donor_root = donor_root.parent
        if repo is None:
            try:
                repo = port_dir.resolve().parents[3]
            except IndexError as error:
                raise DonorUpdateError(
                    "cannot recompute migration semantic evidence"
                ) from error
        current_evidence = _semantic_evidence_at_pin(
            repo,
            port_dir,
            donor_root,
            donor,
            source,
            port_document=port_document,
        )
        target_evidence = _semantic_evidence_at_pin(
            repo,
            port_dir,
            donor_root,
            donor,
            target,
            port_document=port_document,
        )
        references = (
            *(
                reference
                for reference in references
                if reference.get("recordType") != "semantic-evidence"
            ),
            *_semantic_policy_references(current_evidence, target_evidence, donor),
        )
    with tempfile.TemporaryDirectory(
        prefix="content-port-migration-verify-"
    ) as directory:
        temporary = Path(directory)
        old_tree = temporary / "old"
        new_tree = temporary / "new"
        worktrees: list[tuple[Path, Path]] = []
        try:
            _run_git(
                donor_checkout,
                "worktree",
                "add",
                "--detach",
                str(old_tree),
                str(source["commit"]),
            )
            worktrees.append((donor_checkout, old_tree))
            _run_git(
                donor_checkout,
                "worktree",
                "add",
                "--detach",
                str(new_tree),
                str(target["commit"]),
            )
            worktrees.append((donor_checkout, new_tree))
            recomputed = build_migration(
                donor=donor,
                repository=repository,
                old_tree=old_tree,
                new_tree=new_tree,
                references=references,
                assets=filtered_assets,
                tests=report.get("tests", ()),  # type: ignore[arg-type]
                predecessor=report.get("predecessor"),  # type: ignore[arg-type]
                excluded_paths=excluded_paths,
                evidence_root=evidence_root,
            )
        finally:
            _remove_worktrees(
                reversed(worktrees),
                primary_error=sys.exception(),
            )
    for field in (
        "from",
        "to",
        "policy",
        "addedPaths",
        "removedPaths",
        "changedPaths",
    ):
        if report.get(field) != recomputed[field]:
            raise DonorUpdateError(f"migration {field} evidence is fabricated or stale")
    for field in ("authorityChanges", "assets"):
        actual = _without_disposition(report.get(field), f"$.{field}")
        expected = _without_disposition(recomputed[field], f"recomputed.{field}")
        if actual != expected:
            raise DonorUpdateError(f"migration {field} evidence is fabricated or stale")


def run_donor_update(
    repo: Path,
    port: str,
    donor_root: Path,
    donor: str,
    revision: str,
    output: Path,
) -> Path:
    """Propose one pin migration without mutating the descriptor or checkout."""

    repo = repo.resolve()
    port_dir = repo / "tools/content_port/ports" / port
    try:
        port_document = json.loads((port_dir / "port.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DonorUpdateError(f"cannot load port policy {port!r}") from error
    if not isinstance(port_document, dict):
        raise DonorUpdateError(f"invalid port policy {port!r}")
    _validated_donor_checkouts(port_document, donor_root)
    record = _descriptor_donor_record(port_document, donor)
    root = record.get("root")
    commit = record.get("commit")
    repository = record.get("repository")
    name = record.get("name")
    if not all(
        isinstance(value, str) and value for value in (root, commit, repository, name)
    ):
        raise DonorUpdateError(f"invalid donor record {donor!r}")
    checkout = _validated_donor_checkout(donor_root, root, f"$.donors.{donor}.root")
    if not checkout.is_dir():
        raise DonorUpdateError(f"donor checkout does not exist: {checkout}")
    excluded_paths = record.get("excludePaths")
    if not isinstance(excluded_paths, list) or not all(
        isinstance(path, str) for path in excluded_paths
    ):
        raise DonorUpdateError(f"invalid donor exclusions for {donor!r}")

    authored_policy = _derive_authored_policy_snapshot(
        port_dir, port_document, donor, evidence_root=repo
    )
    references, filtered_assets, live_excluded_paths = _migration_policy(
        authored_policy, evidence_root=repo
    )
    if tuple(excluded_paths) != live_excluded_paths:
        raise DonorUpdateError(f"donor {donor}: live exclusion policy is inconsistent")

    with tempfile.TemporaryDirectory(prefix="content-port-donor-update-") as directory:
        temporary = Path(directory)
        old_tree = temporary / "old"
        new_tree = temporary / "new"
        worktrees: list[tuple[Path, Path]] = []
        try:
            _run_git(
                checkout, "worktree", "add", "--detach", str(old_tree), str(commit)
            )
            worktrees.append((checkout, old_tree))
            _run_git(checkout, "worktree", "add", "--detach", str(new_tree), revision)
            worktrees.append((checkout, new_tree))
            provisional = build_migration(
                donor=donor,
                repository=str(repository),
                old_tree=old_tree,
                new_tree=new_tree,
                references=references,
                assets=filtered_assets,
                tests=run_review_commands(repo),
                predecessor=record.get("migration"),
                excluded_paths=excluded_paths,
                evidence_root=repo,
            )
            live_policy = _derive_live_policy_snapshot(
                port_dir,
                port_document,
                donor_root,
                donor,
                repo,
                provisional,
                evidence_root=repo,
            )
            references, filtered_assets, _ = _migration_policy(
                live_policy, evidence_root=repo
            )
            report = build_migration(
                donor=donor,
                repository=str(repository),
                old_tree=old_tree,
                new_tree=new_tree,
                references=references,
                assets=filtered_assets,
                tests=provisional["tests"],  # type: ignore[arg-type]
                predecessor=record.get("migration"),
                excluded_paths=excluded_paths,
                evidence_root=repo,
            )
            _atomic_write(
                output,
                canonical_bytes(report),
                f"after-donor-update-write:{output.name}",
            )
        finally:
            _remove_worktrees(
                reversed(worktrees),
                primary_error=sys.exception(),
            )
    return output
