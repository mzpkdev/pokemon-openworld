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
import subprocess
import tempfile
from typing import Iterable, Mapping, Sequence

from .donors import records_digest, source_tree_records
from .errors import ContentPortError
from .faults import checkpoint


SCHEMA_VERSION = 1
PERMISSION_STATES = frozenset(("redistributable", "blocked", "unknown"))
SUPPORT_STATES = frozenset(
    ("enabled", "disabled", "deferred", "story-owned", "unsupported")
)
REVIEW_DECISIONS = frozenset(("candidate", "reviewed", "rejected"))
REVIEWED_DISPOSITIONS = frozenset(("accepted", "adapted"))
MIGRATION_KEYS = {
    "addedPaths",
    "assets",
    "authorityChanges",
    "changedPaths",
    "decision",
    "donor",
    "from",
    "removedPaths",
    "repository",
    "schemaVersion",
    "tests",
    "to",
}


class DonorUpdateError(ContentPortError):
    """A donor migration or asset contract is invalid."""


@dataclass(frozen=True)
class TreeIdentity:
    commit: str
    digest: str
    file_count: int
    files: Mapping[str, str]


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
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


def _safe_source_path(value: object, pointer: str) -> str:
    if not isinstance(value, str) or not value:
        raise DonorUpdateError(f"{pointer}: expected a non-empty source path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise DonorUpdateError(f"{pointer}: unsafe source path {value!r}")
    return value


def identify_tree(tree: Path) -> TreeIdentity:
    """Return an exact identity for the checked-out commit and file inventory."""

    tree = tree.resolve()
    if not tree.is_dir():
        raise DonorUpdateError(f"donor checkout does not exist: {tree}")
    commit = _run_git(tree, "rev-parse", "HEAD^{commit}")
    records = source_tree_records(tree)
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
                raise DonorUpdateError(f"JSON pointer does not exist: {pointer}")
            current = current[index]
        else:
            raise DonorUpdateError(f"JSON pointer does not exist: {pointer}")
    return current


def _field_value(blob: bytes | None, pointer: str | None) -> object:
    if blob is None:
        return None
    if pointer is None:
        return hashlib.sha256(blob).hexdigest()
    try:
        document = json.loads(blob)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DonorUpdateError(
            f"referenced field {pointer} is not in a JSON source"
        ) from error
    return _json_pointer(document, pointer)


def _value_hash(value: object) -> str | None:
    if value is None:
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
        old_value = _field_value(
            _read_blob(old_tree, old.commit, source_path), json_pointer
        )
        new_value = _field_value(
            _read_blob(new_tree, new.commit, source_path), json_pointer
        )
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
    return changes


def validate_assets(
    document: Mapping[str, object],
    *,
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
    assets = document.get("assets")
    if document.get("schemaVersion") != SCHEMA_VERSION or not isinstance(assets, list):
        raise DonorUpdateError("assets.json: expected schemaVersion 1 and assets list")
    seen: set[str] = set()
    result: list[Mapping[str, object]] = []
    for index, asset in enumerate(assets):
        pointer = f"$.assets[{index}]"
        if not isinstance(asset, dict):
            raise DonorUpdateError(f"{pointer}: expected an object")
        unknown = sorted(set(asset) - allowed_keys)
        if unknown:
            raise DonorUpdateError(f"{pointer}: unknown fields {unknown}")
        required = (
            "key",
            "source",
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
        for field in ("source", "donor", "semanticTarget", "capability"):
            if not isinstance(asset[field], str) or not asset[field]:
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
            not isinstance(command, list)
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
        if require_redistributable and permission != "redistributable":
            raise DonorUpdateError(f"asset {key}: permission is {permission}")
        support_state = asset["supportState"]
        if support_state not in SUPPORT_STATES:
            raise DonorUpdateError(
                f"{pointer}.supportState: unknown state {support_state!r}"
            )
        result.append(asset)
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


def build_migration(
    *,
    donor: str,
    repository: str,
    old_tree: Path,
    new_tree: Path,
    references: Iterable[Mapping[str, object]] = (),
    assets: Mapping[str, object] | None = None,
    tests: Iterable[str] = (),
) -> dict[str, object]:
    """Build a deterministic, non-authoritative donor migration candidate."""

    old = identify_tree(old_tree)
    new = identify_tree(new_tree)
    old_paths = set(old.files)
    new_paths = set(new.files)
    changed_paths = sorted(
        path for path in old_paths & new_paths if old.files[path] != new.files[path]
    )
    asset_specs = (
        validate_assets(assets, require_redistributable=False) if assets else ()
    )
    report: dict[str, object] = {
        "addedPaths": sorted(new_paths - old_paths),
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
        "removedPaths": sorted(old_paths - new_paths),
        "repository": repository,
        "schemaVersion": SCHEMA_VERSION,
        "tests": sorted(set(tests)),
        "to": {
            "commit": new.commit,
            "fileCount": new.file_count,
            "treeDigest": new.digest,
        },
        "changedPaths": changed_paths,
    }
    return report


def _atomic_write(output: Path, data: bytes, checkpoint_name: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(output)
    directory = os.open(output.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    checkpoint(checkpoint_name)


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
    if (
        not isinstance(tests, list)
        or not tests
        or not all(isinstance(test, str) and test for test in tests)
    ):
        raise DonorUpdateError("$.tests: reviewed migration needs recorded tests")


def finalize_migration(candidate: Path, port_dir: Path) -> tuple[Path, Path]:
    """Publish a human-reviewed record and an exact, non-mutating pin proposal."""

    try:
        report = json.loads(candidate.read_text(encoding="utf-8"))
        port = json.loads((port_dir / "port.json").read_text(encoding="utf-8"))
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
    donor = report.get("donor")
    repository = report.get("repository")
    if not isinstance(donor, str) or not isinstance(repository, str):
        raise DonorUpdateError("migration candidate has invalid donor identity")
    source = _pin_identity(report.get("from"), "$.from")
    target = _pin_identity(report.get("to"), "$.to")
    if source["commit"] == target["commit"]:
        raise DonorUpdateError(f"donor {donor}: reviewed migration is a no-op")
    _validate_reviewed_contents(report)
    if not isinstance(port, dict) or not isinstance(port.get("donors"), dict):
        raise DonorUpdateError("port policy has no donors object")
    current = port["donors"].get(donor)
    if not isinstance(current, dict):
        raise DonorUpdateError(f"port policy has no donor role {donor!r}")
    if current.get("repository") != repository:
        raise DonorUpdateError(f"donor {donor}: repository differs from port policy")
    for field in ("commit", "treeDigest", "fileCount"):
        if current.get(field) != source[field]:
            raise DonorUpdateError(f"donor {donor}: candidate source {field} is stale")

    digest = migration_digest(report)
    record_path = port_dir / "migrations" / f"{digest}.json"
    _atomic_write(
        record_path,
        canonical_bytes(report),
        f"after-migration-finalize-write:{record_path.name}",
    )
    proposed_donor = dict(current)
    proposed_donor.update(target)
    proposed_donor["migration"] = digest
    proposal = {
        "donor": donor,
        "migration": digest,
        "port": port_dir.name,
        "proposedDonorRecord": proposed_donor,
        "schemaVersion": SCHEMA_VERSION,
    }
    proposal_path = candidate.with_name("donor-port-update.json")
    _atomic_write(
        proposal_path,
        canonical_bytes(proposal),
        f"after-migration-finalize-proposal:{proposal_path.name}",
    )
    return record_path, proposal_path


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
) -> None:
    """Require an exact reviewed record for a descriptor pin transition."""

    if report.get("schemaVersion") != SCHEMA_VERSION:
        raise DonorUpdateError("migration record has unsupported schemaVersion")
    if report.get("decision") != "reviewed":
        raise DonorUpdateError(f"donor {donor}: migration record is not reviewed")
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
    if expected_assets is None:
        return
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


def load_reviewed_migration(
    migrations: Path,
    digest: str,
) -> Mapping[str, object]:
    path = migrations / f"{digest}.json"
    if not path.is_file():
        raise DonorUpdateError(f"missing reviewed migration record: {path}")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DonorUpdateError(f"invalid migration record: {path}") from error
    if not isinstance(report, dict) or migration_digest(report) != digest:
        raise DonorUpdateError(f"migration record filename is stale: {path}")
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


def _layout_index(tree: Path, layout_id: str) -> int:
    commit = _run_git(tree, "rev-parse", "HEAD^{commit}")
    blob = _read_blob(tree, commit, "data/layouts/layouts.json")
    if blob is None:
        raise DonorUpdateError("donor has no data/layouts/layouts.json")
    try:
        layouts = json.loads(blob)["layouts"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise DonorUpdateError("donor layout registry is malformed") from error
    matches = [
        index
        for index, item in enumerate(layouts)
        if isinstance(item, dict) and item.get("id") == layout_id
    ]
    if len(matches) != 1:
        raise DonorUpdateError(
            f"donor layout registry does not contain exactly one {layout_id}"
        )
    return matches[0]


def _policy_references(
    adaptations: Mapping[str, object], donor: str, old_tree: Path
) -> tuple[Mapping[str, object], ...]:
    """Translate donor-backed authority decisions into field comparisons."""

    references: list[Mapping[str, object]] = []
    for decision in adaptations.get("mapFieldDecisions", []):
        if not isinstance(decision, dict):
            continue
        map_name = decision.get("map")
        field = decision.get("field")
        if not isinstance(map_name, str) or not isinstance(field, str):
            continue
        references.append(
            {
                "authority": decision.get("authority", "content"),
                "jsonPointer": f"/{field}",
                "semanticIdentity": f"map:{map_name}.{field}",
                "sourcePath": f"data/maps/{map_name}/map.json",
            }
        )
    layout_decisions = list(adaptations.get("layoutHeaderDecisions", []))
    if donor == "content":
        layout_decisions.extend(adaptations.get("layoutTilesetRemaps", []))
    for decision in layout_decisions:
        if not isinstance(decision, dict):
            continue
        layout_id = decision.get("layout")
        field = decision.get("field")
        if not isinstance(layout_id, str) or not isinstance(field, str):
            continue
        index = _layout_index(old_tree, layout_id)
        references.append(
            {
                "authority": decision.get("authority", "content"),
                "jsonPointer": f"/layouts/{index}/{field}",
                "semanticIdentity": f"layout:{layout_id}.{field}",
                "sourcePath": "data/layouts/layouts.json",
            }
        )
    return tuple(references)


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
        assets_document = json.loads(
            (port_dir / "assets.json").read_text(encoding="utf-8")
        )
        adaptations_document = json.loads(
            (port_dir / "adaptations.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise DonorUpdateError(f"cannot load port policy {port!r}") from error
    if (
        not isinstance(port_document, dict)
        or not isinstance(assets_document, dict)
        or not isinstance(adaptations_document, dict)
    ):
        raise DonorUpdateError(f"invalid port policy {port!r}")
    record = _descriptor_donor_record(port_document, donor)
    root = record.get("root")
    commit = record.get("commit")
    repository = record.get("repository")
    name = record.get("name")
    if not all(
        isinstance(value, str) and value for value in (root, commit, repository, name)
    ):
        raise DonorUpdateError(f"invalid donor record {donor!r}")
    checkout = (donor_root / str(root)).resolve()
    if not checkout.is_dir():
        raise DonorUpdateError(f"donor checkout does not exist: {checkout}")

    asset_records = validate_assets(assets_document, require_redistributable=False)
    filtered_assets = {
        "schemaVersion": assets_document.get("schemaVersion"),
        "assets": [
            asset
            for asset in asset_records
            if isinstance(asset, dict) and asset.get("donor") in (donor, name)
        ],
    }

    with tempfile.TemporaryDirectory(prefix="content-port-donor-update-") as directory:
        temporary = Path(directory)
        old_tree = temporary / "old"
        new_tree = temporary / "new"
        try:
            _run_git(
                checkout, "worktree", "add", "--detach", str(old_tree), str(commit)
            )
            _run_git(checkout, "worktree", "add", "--detach", str(new_tree), revision)
            references = _policy_references(adaptations_document, donor, old_tree)
            write_candidate_migration(
                output,
                donor=donor,
                repository=str(repository),
                old_tree=old_tree,
                new_tree=new_tree,
                references=references,
                assets=filtered_assets,
                tests=(
                    "python3 -m tools.content_port check "
                    f"--port {port} --donor-root {donor_root}",
                ),
            )
        finally:
            for tree in (old_tree, new_tree):
                if tree.exists():
                    subprocess.run(
                        (
                            "git",
                            "-C",
                            str(checkout),
                            "worktree",
                            "remove",
                            "--force",
                            str(tree),
                        ),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
    return output
