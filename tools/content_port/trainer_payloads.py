"""Validate and project ordinary single-trainer payloads."""

from __future__ import annotations

import copy
import re
from collections.abc import Container, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .errors import ContentPortError
from .model import TrainerEventRecord, TrainerScriptInstruction, TrainerText


_TRAINER_RE = re.compile(r"TRAINER_[A-Z0-9_]+")
_PARTY_RE = re.compile(r"sParty_[A-Za-z0-9_]+")
_STANDARD_SINGLE_COMMANDS = ("trainerbattle_single", "msgbox", "end")
_STANDARD_SINGLE_ARITIES = (3, 2, 0)
_PAIRED_DOUBLE_SHAPES = frozenset(
    {
        (
            ("trainerbattle_double", "special", "msgbox", "release", "end"),
            (4, 1, 2, 0, 0),
            "MSGBOX_DEFAULT",
        ),
        (
            ("trainerbattle_double", "special", "msgbox", "end"),
            (4, 1, 2, 0),
            "MSGBOX_AUTOCLOSE",
        ),
        (
            ("trainerbattle_double", "msgbox", "end"),
            (4, 2, 0),
            "MSGBOX_AUTOCLOSE",
        ),
    }
)
_PAIRED_NOT_ENOUGH_SOURCE_LABEL = "Route104_Text_GinaNotEnoughMons"
PAIRED_NOT_ENOUGH_TARGET_LABEL = "Johto_Text_PairedDoubleNotEnoughMons"
_DEFAULT_PARTY_FIELDS = frozenset({"species", "held_item", "moves", "level", "iv"})


@dataclass(frozen=True)
class StandardSingleEventProjection:
    """An authenticated standard-single event with its target trainer operand."""

    source_trainer: str
    target_trainer: str
    event: TrainerEventRecord


@dataclass(frozen=True)
class PairedDoubleEventProjection:
    """An authenticated paired-double arm with rewritten target operands."""

    source_trainer: str
    target_trainer: str
    event: TrainerEventRecord


@dataclass(frozen=True, order=True)
class DefaultPartyMember:
    """One validated no-item, default-moves party member."""

    species: str
    level: int
    iv: int


@dataclass(frozen=True)
class StandardSinglePartyProjection:
    """An authenticated ordinary trainer party suitable for target rendering."""

    source_trainer: str
    party_name: str
    members: tuple[DefaultPartyMember, ...]


def _trainer(value: object, pointer: str) -> str:
    if not isinstance(value, str) or _TRAINER_RE.fullmatch(value) is None:
        raise ContentPortError(f"{pointer}: expected a trainer identity")
    return value


def _bounded_integer(value: object, minimum: int, maximum: int, pointer: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContentPortError(
            f"{pointer}: expected an integer from {minimum} through {maximum}"
        )
    if not minimum <= value <= maximum:
        raise ContentPortError(
            f"{pointer}: expected an integer from {minimum} through {maximum}"
        )
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(child) for child in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(child) for child in value)
    return copy.deepcopy(value)


def project_standard_single_event(
    event: TrainerEventRecord,
    *,
    source_trainer: str,
    target_trainer: str,
) -> StandardSingleEventProjection:
    """Validate a standard single event and rewrite only its trainer operand."""

    source = _trainer(source_trainer, "source trainer")
    target = _trainer(target_trainer, "target trainer")
    if event.trainers != (source,):
        raise ContentPortError(
            f"{event.script_name}: source trainer closure must be exactly {source}"
        )
    commands = tuple(instruction.command for instruction in event.instructions)
    arities = tuple(len(instruction.operands) for instruction in event.instructions)
    if commands != _STANDARD_SINGLE_COMMANDS or arities != _STANDARD_SINGLE_ARITIES:
        raise ContentPortError(
            f"{event.script_name}: unsupported standard-single script shape"
        )
    battle, msgbox, ending = event.instructions
    if battle.operands[0] != source:
        raise ContentPortError(
            f"{event.script_name}: trainerbattle source does not match {source}"
        )
    if msgbox.operands[1] != "MSGBOX_AUTOCLOSE":
        raise ContentPortError(
            f"{event.script_name}: standard-single msgbox must use MSGBOX_AUTOCLOSE"
        )
    expected_text_labels = (
        battle.operands[1],
        battle.operands[2],
        msgbox.operands[0],
    )
    if len(set(expected_text_labels)) != 3:
        raise ContentPortError(
            f"{event.script_name}: standard-single text labels must be distinct"
        )
    if tuple(text.label for text in event.texts) != expected_text_labels:
        raise ContentPortError(
            f"{event.script_name}: standard-single local text closure must exactly "
            "contain intro, defeat, and after text"
        )
    if any(not text.fragments for text in event.texts):
        raise ContentPortError(
            f"{event.script_name}: standard-single local text must not be empty"
        )

    instructions = tuple(
        TrainerScriptInstruction(
            instruction.command,
            (
                (target, *instruction.operands[1:])
                if index == 0
                else tuple(instruction.operands)
            ),
        )
        for index, instruction in enumerate(event.instructions)
    )
    projected = TrainerEventRecord(
        map_name=event.map_name,
        object_index=event.object_index,
        object_event=_freeze(event.object_event),
        script_name=event.script_name,
        trainers=(target,),
        instructions=instructions,
        texts=tuple(
            TrainerText(text.label, tuple(text.fragments)) for text in event.texts
        ),
    )
    return StandardSingleEventProjection(source, target, projected)


def project_paired_double_event(
    event: TrainerEventRecord,
    *,
    source_trainer: str,
    target_trainer: str,
) -> PairedDoubleEventProjection:
    """Validate one of the three reviewed paired-double script shapes."""

    source = _trainer(source_trainer, "source trainer")
    target = _trainer(target_trainer, "target trainer")
    if event.trainers != (source,):
        raise ContentPortError(
            f"{event.script_name}: source trainer closure must be exactly {source}"
        )
    commands = tuple(instruction.command for instruction in event.instructions)
    arities = tuple(len(instruction.operands) for instruction in event.instructions)
    msgbox = next(
        (
            instruction
            for instruction in event.instructions
            if instruction.command == "msgbox"
        ),
        None,
    )
    msgbox_mode = msgbox.operands[1] if msgbox is not None else None
    if (commands, arities, msgbox_mode) not in _PAIRED_DOUBLE_SHAPES:
        raise ContentPortError(
            f"{event.script_name}: unsupported paired-double script shape"
        )
    battle = event.instructions[0]
    if (
        battle.operands[0] != source
        or battle.operands[3] != _PAIRED_NOT_ENOUGH_SOURCE_LABEL
    ):
        raise ContentPortError(
            f"{event.script_name}: paired-double battle operands drifted"
        )
    if "special" in commands:
        special = event.instructions[commands.index("special")]
        if special.operands != ("GetPlayerBigGuyGirlString",):
            raise ContentPortError(
                f"{event.script_name}: paired-double player-string special drifted"
            )
    assert msgbox is not None
    expected_text_labels = (battle.operands[1], battle.operands[2], msgbox.operands[0])
    if len(set(expected_text_labels)) != 3:
        raise ContentPortError(
            f"{event.script_name}: paired-double local text labels must be distinct"
        )
    if tuple(text.label for text in event.texts) != expected_text_labels:
        raise ContentPortError(
            f"{event.script_name}: paired-double local text closure must exactly "
            "contain intro, defeat, and after text"
        )
    if any(not text.fragments for text in event.texts):
        raise ContentPortError(
            f"{event.script_name}: paired-double local text must not be empty"
        )

    instructions = tuple(
        TrainerScriptInstruction(
            instruction.command,
            (
                (target, *instruction.operands[1:3], PAIRED_NOT_ENOUGH_TARGET_LABEL)
                if index == 0
                else tuple(instruction.operands)
            ),
        )
        for index, instruction in enumerate(event.instructions)
    )
    projected = TrainerEventRecord(
        map_name=event.map_name,
        object_index=event.object_index,
        object_event=_freeze(event.object_event),
        script_name=event.script_name,
        trainers=(target,),
        instructions=instructions,
        texts=tuple(
            TrainerText(text.label, tuple(text.fragments)) for text in event.texts
        ),
    )
    return PairedDoubleEventProjection(source, target, projected)


def project_standard_single_party(
    party: Mapping[str, object],
    *,
    source_trainer: str,
    party_name: str,
    known_species: Container[str],
) -> StandardSinglePartyProjection:
    """Validate one default donor party and return an immutable projection."""

    source = _trainer(source_trainer, "source trainer")
    if not isinstance(party_name, str) or _PARTY_RE.fullmatch(party_name) is None:
        raise ContentPortError(
            f"trainer:{source}: invalid party identity {party_name!r}"
        )
    members = party.get("members")
    if not isinstance(members, (list, tuple)):
        raise ContentPortError(f"party:{party_name}/members: expected an array")
    if not 1 <= len(members) <= 6:
        raise ContentPortError(
            f"party:{party_name}/members: expected between one and six members"
        )

    projected: list[DefaultPartyMember] = []
    for index, member in enumerate(members):
        pointer = f"party:{party_name}/members/{index}"
        if not isinstance(member, Mapping):
            raise ContentPortError(f"{pointer}: expected an object")
        fields = frozenset(member)
        if fields != _DEFAULT_PARTY_FIELDS:
            missing = sorted(_DEFAULT_PARTY_FIELDS - fields)
            unknown = sorted(fields - _DEFAULT_PARTY_FIELDS)
            if missing:
                raise ContentPortError(f"{pointer}: missing field {missing[0]!r}")
            raise ContentPortError(f"{pointer}: unknown field {unknown[0]!r}")
        species = member["species"]
        if not isinstance(species, str) or not species:
            raise ContentPortError(f"{pointer}/species: missing species")
        if species not in known_species:
            raise ContentPortError(f"{pointer}/species: unknown species {species!r}")
        if member["held_item"] is not None:
            raise ContentPortError(
                f"{pointer}/held_item: standard-single parties must use no items"
            )
        moves = member["moves"]
        if not isinstance(moves, (list, tuple)) or moves:
            raise ContentPortError(
                f"{pointer}/moves: standard-single parties must use default moves"
            )
        level = _bounded_integer(member["level"], 1, 100, f"{pointer}/level")
        iv = _bounded_integer(member["iv"], 0, 31, f"{pointer}/iv")
        projected.append(DefaultPartyMember(species, level, iv))

    return StandardSinglePartyProjection(source, party_name, tuple(projected))
