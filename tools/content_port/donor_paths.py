"""Shared validation for descriptor-authored donor checkout paths."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path, PurePosixPath

from .errors import ContentPortError


def validated_donor_checkout(
    donor_root: Path,
    value: object,
    pointer: str,
    *,
    error_type: type[ContentPortError] = ContentPortError,
) -> Path:
    """Resolve a donor checkout lexically while rejecting every symlink component."""

    if not isinstance(value, str) or not value or value.strip() != value:
        raise error_type(f"{pointer}: expected a non-empty, trimmed string")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
        raise error_type(f"{pointer}: unsafe donor checkout path")

    root = Path(os.path.abspath(donor_root))
    checkout = root.joinpath(*relative.parts)
    current = Path(checkout.anchor)
    for part in checkout.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise error_type(
                f"{pointer}: donor checkout path must not contain a symbolic link"
            )
    return checkout


def validated_donor_checkouts(
    port_document: Mapping[str, object],
    donor_root: Path,
    *,
    error_type: type[ContentPortError] = ContentPortError,
) -> Mapping[str, Path]:
    """Preflight every raw donor root before callers perform donor-backed work."""

    donors = port_document.get("donors")
    if not isinstance(donors, Mapping):
        raise error_type("target-pin port policy has no donors object")
    checkouts: dict[str, Path] = {}
    for role, raw in sorted(donors.items()):
        if not isinstance(role, str) or not isinstance(raw, Mapping):
            raise error_type(f"invalid donor record {role!r}")
        checkouts[role] = validated_donor_checkout(
            donor_root,
            raw.get("root"),
            f"$.donors.{role}.root",
            error_type=error_type,
        )
    return checkouts
