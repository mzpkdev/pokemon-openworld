"""Small immutable records shared by the content-port engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .errors import ContentPortError


class CapabilityState(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    DEFERRED = "deferred"
    STORY_OWNED = "story-owned"
    UNSUPPORTED = "unsupported"

    @classmethod
    def parse(cls, value: object, pointer: str) -> "CapabilityState":
        if not isinstance(value, str):
            raise ContentPortError(f"{pointer}: capability state must be a string")
        try:
            return cls(value)
        except ValueError as error:
            allowed = ", ".join(state.value for state in cls)
            raise ContentPortError(
                f"{pointer}: unknown capability state {value!r}; expected one of {allowed}"
            ) from error


@dataclass(frozen=True, order=True)
class ResourceKey:
    domain: str
    name: str

    def __post_init__(self) -> None:
        for field, value in (("domain", self.domain), ("name", self.name)):
            if not isinstance(value, str) or not value or value.strip() != value:
                raise ContentPortError(
                    f"resource {field} must be a non-empty, trimmed string"
                )

    def __str__(self) -> str:
        return f"{self.domain}:{self.name}"


@dataclass(frozen=True)
class DonorPin:
    name: str
    repository: str
    commit: str
    tree_digest: str
    file_count: int
    root: Path
    migration: str | None = None


@dataclass(frozen=True)
class DonorEvidence:
    name: str
    commit: str
    tree_digest: str
    file_count: int


@dataclass(frozen=True)
class CapabilityDecision:
    map_name: str
    capability: str
    state: CapabilityState
    dependencies: tuple[ResourceKey, ...] = ()

    def __post_init__(self) -> None:
        for field, value in (
            ("map_name", self.map_name),
            ("capability", self.capability),
        ):
            if not isinstance(value, str) or not value or value.strip() != value:
                raise ContentPortError(f"capability {field} must be a non-empty string")
        if not isinstance(self.state, CapabilityState):
            raise ContentPortError("capability state must be a CapabilityState")
        if not isinstance(self.dependencies, tuple):
            raise ContentPortError("capability dependencies must be an immutable tuple")
        if any(not isinstance(key, ResourceKey) for key in self.dependencies):
            raise ContentPortError(
                "capability dependencies must contain ResourceKey values"
            )
        if len(self.dependencies) != len(set(self.dependencies)):
            raise ContentPortError(
                f"duplicate resource identity in {self.map_name}/{self.capability}"
            )
