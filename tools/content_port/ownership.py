"""Exact ownership and desired-state reconciliation for content ports."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
from types import MappingProxyType
from typing import Iterable, Mapping

from .errors import ContentPortError
from .faults import checkpoint


SCHEMA_VERSION = 1
UNIT_KINDS = frozenset({"file", "section", "registry-record"})
_SHA256_LENGTH = 64


def canonical_json(value: object) -> bytes:
    """Return the one JSON encoding used by manifests, reports, and records."""

    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode()


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _validate_hash(value: str, label: str) -> None:
    if len(value) != _SHA256_LENGTH or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise ContentPortError(f"{label}: expected a lowercase SHA-256 digest")


def validate_relative_path(value: str) -> PurePosixPath:
    """Validate an exact repository-relative path without touching the filesystem."""

    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ContentPortError(f"unsafe owned path {value!r}")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value.endswith("/")
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ContentPortError(f"unsafe owned path {value!r}")
    if path.parts[0] == ".git":
        raise ContentPortError("ownership cannot target .git")
    return path


def safe_repo_path(root: Path, value: str, *, allow_missing: bool = True) -> Path:
    """Resolve an owned path while refusing symlinks in every existing component."""

    relative = validate_relative_path(value)
    root = root.resolve(strict=True)
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if not allow_missing and index == len(relative.parts) - 1:
                raise ContentPortError(f"owned path does not exist: {value}") from None
            continue
        if stat.S_ISLNK(mode):
            raise ContentPortError(f"owned path crosses symlink: {value}")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(mode):
            raise ContentPortError(f"owned path has non-directory parent: {value}")
        if index == len(relative.parts) - 1 and stat.S_ISDIR(mode):
            raise ContentPortError(f"broad directory ownership is forbidden: {value}")
    return current


@dataclass(frozen=True, order=True)
class OwnershipUnit:
    kind: str
    path: str
    sha256: str
    name: str | None = None
    registry: str | None = None
    key: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in UNIT_KINDS:
            raise ContentPortError(f"unknown ownership kind {self.kind!r}")
        validate_relative_path(self.path)
        _validate_hash(self.sha256, f"{self.identity}")
        if self.kind == "file":
            if (
                self.name is not None
                or self.registry is not None
                or self.key is not None
            ):
                raise ContentPortError(
                    f"{self.path}: file ownership has sub-unit fields"
                )
        elif self.kind == "section":
            if not self.name or self.registry is not None or self.key is not None:
                raise ContentPortError(
                    f"{self.path}: section ownership requires only name"
                )
            _validate_token(self.name, "section name")
        elif not self.registry or not self.key or self.name is not None:
            raise ContentPortError(
                f"{self.path}: registry-record ownership requires registry and key"
            )
        else:
            _validate_token(self.registry, "registry name")
            _validate_token(self.key, "registry key")

    @property
    def identity(self) -> tuple[str, ...]:
        if self.kind == "file":
            return (self.kind, self.path)
        if self.kind == "section":
            return (self.kind, self.path, self.name or "")
        return (self.kind, self.path, self.registry or "", self.key or "")

    def to_json(self) -> dict[str, str]:
        result = {"kind": self.kind, "path": self.path, "sha256": self.sha256}
        if self.name is not None:
            result["name"] = self.name
        if self.registry is not None:
            result["registry"] = self.registry
        if self.key is not None:
            result["key"] = self.key
        return result

    @classmethod
    def from_json(cls, value: object, pointer: str = "$.units[]") -> "OwnershipUnit":
        if not isinstance(value, dict):
            raise ContentPortError(f"{pointer}: expected object")
        allowed = {"kind", "path", "sha256", "name", "registry", "key"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ContentPortError(f"{pointer}: unknown field {unknown[0]}")
        required = {"kind", "path", "sha256"}
        missing = sorted(required - set(value))
        if missing:
            raise ContentPortError(f"{pointer}: missing field {missing[0]}")
        if any(not isinstance(value.get(field), str) for field in value):
            raise ContentPortError(f"{pointer}: ownership fields must be strings")
        return cls(**value)  # type: ignore[arg-type]


def _validate_token(value: str, label: str) -> None:
    if not value.strip() or "\n" in value or "\r" in value:
        raise ContentPortError(f"invalid {label} {value!r}")


@dataclass(frozen=True)
class OwnershipManifest:
    port: str
    units: tuple[OwnershipUnit, ...]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ContentPortError(
                f"unsupported ownership schema {self.schema_version}"
            )
        _validate_token(self.port, "port name")
        ordered = tuple(sorted(self.units, key=lambda unit: unit.identity))
        if self.units != ordered:
            object.__setattr__(self, "units", ordered)
        seen: set[tuple[str, ...]] = set()
        whole_files: set[str] = set()
        subunits: set[str] = set()
        for unit in self.units:
            if unit.identity in seen:
                raise ContentPortError(f"duplicate ownership unit {unit.identity}")
            seen.add(unit.identity)
            if unit.kind == "file":
                whole_files.add(unit.path)
            else:
                subunits.add(unit.path)
        overlap = sorted(whole_files & subunits)
        if overlap:
            raise ContentPortError(f"file/sub-unit ownership overlaps at {overlap[0]}")

    @property
    def by_identity(self) -> Mapping[tuple[str, ...], OwnershipUnit]:
        return MappingProxyType({unit.identity: unit for unit in self.units})

    def to_json(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "port": self.port,
            "units": [unit.to_json() for unit in self.units],
        }

    def write(self, path: Path) -> None:
        _atomic_write(path, canonical_json(self.to_json()))

    @classmethod
    def from_json(cls, value: object) -> "OwnershipManifest":
        if not isinstance(value, dict):
            raise ContentPortError("ownership manifest: expected object")
        allowed = {"schemaVersion", "port", "units"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ContentPortError(f"ownership manifest: unknown field {unknown[0]}")
        if set(value) != allowed:
            missing = sorted(allowed - set(value))
            raise ContentPortError(f"ownership manifest: missing field {missing[0]}")
        if not isinstance(value["schemaVersion"], int) or not isinstance(
            value["port"], str
        ):
            raise ContentPortError("ownership manifest: invalid schemaVersion or port")
        if not isinstance(value["units"], list):
            raise ContentPortError("ownership manifest: units must be an array")
        units = tuple(
            OwnershipUnit.from_json(unit, f"$.units[{index}]")
            for index, unit in enumerate(value["units"])
        )
        return cls(value["port"], units, value["schemaVersion"])

    @classmethod
    def load(cls, path: Path) -> "OwnershipManifest":
        try:
            value = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise ContentPortError(
                f"cannot load ownership manifest {path}: {error}"
            ) from error
        return cls.from_json(value)

    def verify(self, root: Path) -> None:
        verify_owned_baseline(root, self)


def section_markers(port: str, name: str) -> tuple[bytes, bytes]:
    _validate_token(port, "port name")
    _validate_token(name, "section name")
    return (
        f"CONTENT PORT BEGIN {port}:{name}".encode(),
        f"CONTENT PORT END {port}:{name}".encode(),
    )


def _section_span(content: bytes, port: str, name: str) -> tuple[int, int, bytes]:
    begin, end = section_markers(port, name)
    begin_positions = _all_positions(content, begin)
    end_positions = _all_positions(content, end)
    if len(begin_positions) != 1 or len(end_positions) != 1:
        raise ContentPortError(
            f"section {port}:{name} must have exactly one marker pair"
        )
    marker_start = begin_positions[0]
    start = content.rfind(b"\n", 0, marker_start) + 1
    marker_finish = end_positions[0] + len(end)
    if end_positions[0] <= marker_start:
        raise ContentPortError(f"section {port}:{name} has reversed markers")
    line_finish = content.find(b"\n", marker_finish)
    finish = len(content) if line_finish < 0 else line_finish + 1
    return start, finish, content[start:finish]


def _legacy_section_markers(port: str, name: str) -> tuple[bytes, bytes]:
    token = port.upper().encode()
    encoded_name = name.encode()
    return (
        token + b" IMPORT BEGIN: " + encoded_name,
        token + b" IMPORT END: " + encoded_name,
    )


def _owned_section_span(content: bytes, port: str, name: str) -> tuple[int, int, bytes]:
    begin, end = section_markers(port, name)
    if _all_positions(content, begin) or _all_positions(content, end):
        return _section_span(content, port, name)
    legacy_begin, legacy_end = _legacy_section_markers(port, name)
    begin_positions = _all_positions(content, legacy_begin)
    end_positions = _all_positions(content, legacy_end)
    if len(begin_positions) != 1 or len(end_positions) != 1:
        raise ContentPortError(
            f"section {port}:{name} must have exactly one marker pair"
        )
    marker_start = begin_positions[0]
    start = content.rfind(b"\n", 0, marker_start) + 1
    finish = end_positions[0] + len(legacy_end)
    if end_positions[0] <= marker_start:
        raise ContentPortError(f"section {port}:{name} has reversed markers")
    finish = content.find(b"\n", finish)
    finish = len(content) if finish < 0 else finish + 1
    return start, finish, content[start:finish]


def _all_positions(content: bytes, needle: bytes) -> list[int]:
    positions: list[int] = []
    offset = 0
    while True:
        found = content.find(needle, offset)
        if found < 0:
            return positions
        positions.append(found)
        offset = found + len(needle)


def _registry_container(value: object, registry: str) -> object:
    current = value
    if registry in {"$", "root"}:
        return current
    for part in registry.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ContentPortError(f"registry {registry!r} does not exist")
        current = current[part]
    return current


def _record_index(records: list[object], key: str) -> int:
    matches = [
        index
        for index, record in enumerate(records)
        if isinstance(record, dict)
        and any(record.get(field) == key for field in ("key", "id", "name"))
    ]
    if len(matches) != 1:
        raise ContentPortError(f"registry key {key!r} must identify exactly one record")
    return matches[0]


def extract_owned_content(root: Path, port: str, unit: OwnershipUnit) -> bytes:
    path = safe_repo_path(root, unit.path, allow_missing=False)
    try:
        content = path.read_bytes()
    except OSError as error:
        raise ContentPortError(
            f"cannot read owned path {unit.path}: {error}"
        ) from error
    if unit.kind == "file":
        return content
    if unit.kind == "section":
        return _owned_section_span(content, port, unit.name or "")[2]
    try:
        document = json.loads(content)
    except json.JSONDecodeError as error:
        raise ContentPortError(
            f"owned registry {unit.path} is not valid JSON: {error}"
        ) from error
    records = _registry_container(document, unit.registry or "")
    if isinstance(records, dict):
        if unit.key not in records:
            raise ContentPortError(
                f"registry key {unit.key!r} does not exist in {unit.path}"
            )
        record = records[unit.key]
    elif isinstance(records, list):
        record = records[_record_index(records, unit.key or "")]
    else:
        raise ContentPortError(
            f"registry {unit.registry!r} is not keyed in {unit.path}"
        )
    return canonical_json(record)


def verify_owned_baseline(root: Path, manifest: OwnershipManifest) -> None:
    for unit in manifest.units:
        actual = content_sha256(extract_owned_content(root, manifest.port, unit))
        if actual != unit.sha256:
            raise ContentPortError(
                f"unexpected edit to generated unit {unit.identity}: "
                f"expected {unit.sha256}, got {actual}"
            )


def require_exact_file_ownership(
    manifest: OwnershipManifest, paths: Iterable[str], *, label: str = "emitted files"
) -> None:
    """Fail when an emitted file inventory and file ownership differ at all."""

    expected = {str(validate_relative_path(path)) for path in paths}
    actual = {unit.path for unit in manifest.units if unit.kind == "file"}
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing:
        raise ContentPortError(f"{label}: missing file ownership for {missing[0]}")
    if unexpected:
        raise ContentPortError(
            f"{label}: unexpected file ownership for {unexpected[0]}"
        )


def _coerce_payload(unit: OwnershipUnit, value: object) -> bytes:
    if unit.kind == "registry-record":
        if isinstance(value, bytes):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as error:
                raise ContentPortError(
                    f"{unit.identity}: invalid JSON payload"
                ) from error
        return canonical_json(value)
    if isinstance(value, str):
        return value.encode()
    if not isinstance(value, bytes):
        raise ContentPortError(f"{unit.identity}: expected bytes payload")
    return value


def reconcile_owned(
    root: Path,
    previous: OwnershipManifest,
    desired: OwnershipManifest,
    payloads: Mapping[tuple[str, ...], object],
) -> None:
    """Converge exact owned units after proving the checked baseline is untouched."""

    if previous.port != desired.port:
        raise ContentPortError(
            "cannot reconcile ownership manifests for different ports"
        )
    verify_owned_baseline(root, previous)
    desired_by_id = desired.by_identity
    if set(payloads) != set(desired_by_id):
        missing = sorted(set(desired_by_id) - set(payloads))
        extra = sorted(set(payloads) - set(desired_by_id))
        detail = missing[0] if missing else extra[0]
        raise ContentPortError(
            f"desired payload set does not match ownership manifest: {detail}"
        )
    normalized: dict[tuple[str, ...], bytes] = {}
    for identity, unit in desired_by_id.items():
        payload = _coerce_payload(unit, payloads[identity])
        if content_sha256(payload) != unit.sha256:
            raise ContentPortError(f"desired payload hash does not match {identity}")
        normalized[identity] = payload

    stale = [unit for unit in previous.units if unit.identity not in desired_by_id]
    for unit in sorted(stale, key=lambda item: item.identity, reverse=True):
        _remove_unit(root, previous.port, unit)
    for unit in desired.units:
        _write_unit(root, desired.port, unit, normalized[unit.identity])
        checkpoint(f"after-render:{unit.identity}")
    verify_owned_baseline(root, desired)


def _remove_unit(root: Path, port: str, unit: OwnershipUnit) -> None:
    path = safe_repo_path(root, unit.path, allow_missing=False)
    if unit.kind == "file":
        path.unlink()
        return
    content = path.read_bytes()
    if unit.kind == "section":
        start, finish, _ = _owned_section_span(content, port, unit.name or "")
        _atomic_write(path, content[:start] + content[finish:])
        return
    document = json.loads(content)
    records = _registry_container(document, unit.registry or "")
    if isinstance(records, dict):
        del records[unit.key or ""]
    elif isinstance(records, list):
        del records[_record_index(records, unit.key or "")]
    else:
        raise ContentPortError(
            f"registry {unit.registry!r} is not keyed in {unit.path}"
        )
    _atomic_write(path, canonical_json(document))


def _write_unit(root: Path, port: str, unit: OwnershipUnit, payload: bytes) -> None:
    path = safe_repo_path(root, unit.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if unit.kind == "file":
        if path.exists() and path.read_bytes() == payload:
            return
        _atomic_write(path, payload)
        return
    if not path.exists():
        if unit.kind == "section":
            _atomic_write(path, payload)
            return
        document = {}
        if unit.registry not in {"$", "root"}:
            current = document
            parts = (unit.registry or "").split(".")
            for part in parts:
                child: dict[str, object] = {}
                current[part] = child
                current = child
    else:
        content = path.read_bytes()
        if unit.kind == "section":
            begin, end = section_markers(port, unit.name or "")
            begins = _all_positions(content, begin)
            ends = _all_positions(content, end)
            legacy_begin, legacy_end = _legacy_section_markers(port, unit.name or "")
            legacy_begins = _all_positions(content, legacy_begin)
            legacy_ends = _all_positions(content, legacy_end)
            if not begins and not ends and not legacy_begins and not legacy_ends:
                separator = b"" if not content or content.endswith(b"\n") else b"\n"
                _atomic_write(path, content + separator + payload)
                return
            start, finish, _ = _owned_section_span(content, port, unit.name or "")
            if content[start:finish] == payload:
                return
            _atomic_write(path, content[:start] + payload + content[finish:])
            return
        document = json.loads(content)
    records = _registry_container(document, unit.registry or "")
    record = json.loads(payload)
    if isinstance(records, dict):
        if unit.key in records and canonical_json(records[unit.key or ""]) == payload:
            return
        records[unit.key or ""] = record
    elif isinstance(records, list):
        try:
            index = _record_index(records, unit.key or "")
        except ContentPortError:
            records.append(record)
        else:
            if canonical_json(records[index]) == payload:
                return
            records[index] = record
    else:
        raise ContentPortError(
            f"registry {unit.registry!r} is not keyed in {unit.path}"
        )
    _atomic_write(path, canonical_json(document))


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def manifest_for_payloads(
    port: str,
    outputs: Iterable[tuple[OwnershipUnit, object]],
) -> tuple[OwnershipManifest, Mapping[tuple[str, ...], object]]:
    """Build a hash-checked manifest from unhashed output unit templates."""

    units: list[OwnershipUnit] = []
    payloads: dict[tuple[str, ...], object] = {}
    for template, value in outputs:
        payload = _coerce_payload(template, value)
        unit = OwnershipUnit(
            kind=template.kind,
            path=template.path,
            sha256=content_sha256(payload),
            name=template.name,
            registry=template.registry,
            key=template.key,
        )
        units.append(unit)
        payloads[unit.identity] = value
    manifest = OwnershipManifest(port=port, units=tuple(units))
    return manifest, MappingProxyType(payloads)
