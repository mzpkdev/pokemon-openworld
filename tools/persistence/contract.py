#!/usr/bin/env python3
"""Freeze and validate the serialized save ABI using ARM DWARF facts only."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import operator
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterable

BASELINE_SHA = "b47a41e9e4635cc40a8003249f9425578e257e1e"
SCHEMA_VERSION = 1
CONTRACT_METADATA_KEYS = frozenset(
    (
        "baselineCommit",
        "compatibleTailExtension",
        "purposeBudgets",
        "purposeAbiEvidence",
    )
)
MEASURED_ABI_KEYS = frozenset(
    ("schemaVersion", "target", "structs", "physical", "checksums", "publishedBindings")
)
PUBLISHED_BINDING_DOMAINS = frozenset(
    (
        "trainerIds",
        "flags",
        "vars",
        "rewardState",
        "tradeState",
        "checkpoints",
        "destinations",
        "facilities",
        "savedLocations",
        "metLocations",
        "gameStats",
    )
)
NON_PERSISTENT_CONFIG_BINDINGS = frozenset(
    (
        "FLAG_DEBUG_NO_TRAINER_SIGHT",
        "FLAG_DEBUG_NO_WILD_ENCOUNTERS",
    )
)
# Live post-baseline trainer identities are owned by persistent_ids.json. The
# save contract retains the colliding pre-ledger TRAINER_* spellings as frozen
# tombstone evidence instead of silently rewriting that historical projection.
LEDGER_ONLY_TRAINER_SUFFIX = "_JOHTO"
ABI_PURPOSES = ("normal", "debug", "release", "test-runner", "headless-test")
ROOT_TYPES = (
    "SaveBlock1",
    "SaveBlock2",
    "SaveBlock3",
    "PokemonStorage",
    "BoxPokemon",
    "Pokemon",
    "PokemonSubstruct0",
    "PokemonSubstruct1",
    "PokemonSubstruct2",
    "PokemonSubstruct3",
    "DayCare",
    "BattleFrontier",
    "EmeraldBattleTowerRecord",
    "RSBattleTowerRecord",
    "RecordedBattleSave",
    "TrainerHillSave",
    "TrainerHillChallenge",
    "HallofFameTeam",
    "GabbyAndTyData",
    "SaveSector",
    "PlayerRecordEmerald",
    "PlayerRecordRS",
)


class ContractError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_bytes(value)
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def compare(expected: Any, actual: Any, path: str = "$") -> None:
    if type(expected) is not type(actual):
        raise ContractError(f"{path}: type changed")
    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            missing = sorted(expected.keys() - actual.keys())
            extra = sorted(actual.keys() - expected.keys())
            raise ContractError(
                f"{path}: keys changed (missing={missing}, extra={extra})"
            )
        for key in expected:
            compare(expected[key], actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            raise ContractError(
                f"{path}: length changed ({len(expected)} != {len(actual)})"
            )
        for index, value in enumerate(expected):
            compare(value, actual[index], f"{path}[{index}]")
    elif expected != actual:
        raise ContractError(f"{path}: {expected!r} != {actual!r}")


def _run(
    args: list[str],
    cwd: Path,
    *,
    input_bytes: bytes | None = None,
    env: dict[str, str] | None = None,
) -> bytes:
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            env=env,
        ).stdout
    except FileNotFoundError as exc:
        raise ContractError(f"required tool not found: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        tail = exc.stderr.decode(errors="replace").splitlines()[-20:]
        raise ContractError(
            f"command failed: {' '.join(args)}\n" + "\n".join(tail)
        ) from exc


def export_baseline(repo: Path, revision: str, destination: Path) -> str:
    sha = _run(["git", "rev-parse", f"{revision}^{{commit}}"], repo).decode().strip()
    archive = _run(["git", "archive", "--format=tar", sha], repo)
    proc = subprocess.run(
        ["tar", "-xf", "-", "-C", str(destination)],
        input=archive,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        raise ContractError(proc.stderr.decode(errors="replace"))
    return sha


def _prepare_tree(tree: Path) -> Path:
    generated = tree / "build/generated/allregions/current"
    if not generated.exists():
        # Archives deliberately contain no ignored host-tool binaries. Build only
        # the generators needed here; the aggregate `tools` target also runs the
        # git-history check, which is intentionally unavailable in an archive.
        _run(["make", "-s", "-j2", "tools/jsonproc", "tools/mapjson"], tree)
        # Map generation owns atomic publication of the shared generated root.
        # Publish its symlink before parallel aggregate generators add outputs;
        # otherwise one of them can create `current` as a legacy directory first.
        _run(
            [
                "make",
                "-s",
                "-j2",
                "build/generated/allregions/current/.map-build-policy",
            ],
            tree,
        )
        _run(["make", "-s", "-j2", "generated"], tree)
    if not generated.exists():
        raise ContractError("generated include tree was not produced")
    return generated.resolve()


def _purpose_defines(purpose: str) -> list[str]:
    if purpose not in ABI_PURPOSES:
        raise ContractError(f"unknown ABI purpose: {purpose}")
    testing = purpose in ("test-runner", "headless-test")
    defines = [
        "-DMODERN=1",
        f"-DTESTING={int(testing)}",
        "-DEMERALD=1",
        "-DALL_REGIONS=1",
    ]
    if purpose == "debug":
        defines.append("-DDEBUG=1")
    elif purpose == "release":
        defines.append("-DRELEASE=1")
    return defines


def _compile_units(tree: Path, output_dir: Path, purpose: str) -> list[Path]:
    generated = _prepare_tree(tree)
    anchor = tree / "tools/persistence/abi_anchor.c"
    if not anchor.exists():
        raise ContractError(f"missing ABI anchor: {anchor}")
    common = [
        "arm-none-eabi-gcc",
        "-c",
        "-g3",
        "-gdwarf-4",
        "-fno-eliminate-unused-debug-types",
        "-O0",
        "-mthumb",
        "-mthumb-interwork",
        "-mabi=apcs-gnu",
        "-mtune=arm7tdmi",
        "-march=armv4t",
        "-std=gnu17",
        *_purpose_defines(purpose),
        "-Wno-pointer-to-int-cast",
        "-Wno-address-of-packed-member",
        "-iquote",
        str(generated / "include/constants"),
        "-iquote",
        str(generated / "src"),
        "-iquote",
        str(generated / "include"),
        "-iquote",
        str(tree / "include"),
        "-include",
        str(generated / "include/constants/map_groups.h"),
        "-include",
        str(generated / "include/constants/layouts.h"),
        "-include",
        str(generated / "include/constants/map_event_ids.h"),
    ]
    units = [anchor, tree / "src/record_mixing.c"]
    objects: list[Path] = []
    for source in units:
        obj = output_dir / (source.stem + ".o")
        _run(common + [str(source), "-o", str(obj)], tree)
        objects.append(obj)
    return objects


_DIE_RE = re.compile(
    r"^\s*<(\d+)><([0-9a-f]+)>: Abbrev Number: \d+(?: \((DW_TAG_[^)]+)\))?"
)
_ATTR_RE = re.compile(r"^\s*<[0-9a-f]+>\s+(DW_AT_[A-Za-z0-9_]+)\s*:\s*(.*)$")
_REF_RE = re.compile(r"<0x([0-9a-f]+)>")


def _attr_text(raw: str) -> str:
    # Binutils versions render the same DWARF form as `(string) name`,
    # `(strp) name`, or `(indirect string, offset: 0x12): name`. Forms are
    # presentation metadata, not part of the attribute value.
    text = raw.strip()
    form = re.compile(
        r"^\((?:indirect string|indexed string|string|strp|line_strp|data[1248]|"
        r"udata|sdata|ref[1248]|addr|offset)(?:[^)]*)\)\s*:?[ \t]*"
    )
    while match := form.match(text):
        text = text[match.end() :]
    return text.strip()


def _attr_int(raw: str) -> int:
    text = _attr_text(raw)
    match = re.search(r"(?:^|\s)(-?0x[0-9a-fA-F]+|-?\d+)(?:\s|$)", text)
    if not match:
        raise ContractError(f"unreadable DWARF integer: {raw}")
    return int(match.group(1), 0)


def _parse_dwarf(text: str) -> dict[int, dict[str, Any]]:
    dies: dict[int, dict[str, Any]] = {}
    stack: list[int] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        match = _DIE_RE.match(line)
        if match:
            depth, offset, tag = (
                int(match.group(1)),
                int(match.group(2), 16),
                match.group(3),
            )
            stack = stack[:depth]
            if not tag:
                current = None
                continue
            die = {"offset": offset, "tag": tag, "attrs": {}, "children": []}
            dies[offset] = die
            if stack and stack[-1] in dies:
                dies[stack[-1]]["children"].append(offset)
            stack.append(offset)
            current = die
            continue
        match = _ATTR_RE.match(line)
        if match and current is not None:
            current["attrs"][match.group(1)] = match.group(2)
    return dies


def _merge_dies(objects: Iterable[Path], tree: Path) -> list[dict[int, dict[str, Any]]]:
    result = []
    for obj in objects:
        dump = _run(
            ["arm-none-eabi-readelf", "--debug-dump=info", "--wide", str(obj)], tree
        )
        result.append(_parse_dwarf(dump.decode(errors="replace")))
    return result


def _type_ref(die: dict[str, Any]) -> int | None:
    raw = die["attrs"].get("DW_AT_type")
    match = _REF_RE.search(raw or "")
    return int(match.group(1), 16) if match else None


def _die_name(die: dict[str, Any]) -> str | None:
    raw = die["attrs"].get("DW_AT_name")
    return _attr_text(raw) if raw else None


def _structural_layout(
    layout: dict[str, Any], structs: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Describe a layout without CU-local anonymous DIE identities."""
    visiting: set[str] = set()

    def describe(desc: dict[str, Any]) -> dict[str, Any]:
        kind = desc.get("kind")
        if kind in ("struct", "union"):
            name = desc["name"]
            if not name.startswith("anonymous@"):
                return {"kind": kind, "name": name}
            if name in visiting:
                raise ContractError(f"recursive anonymous by-value layout: {name}")
            visiting.add(name)
            value = normalize(structs[name])
            visiting.remove(name)
            return {"kind": kind, "anonymous": value}
        if kind == "typedef":
            return describe(desc["target"])
        if kind == "array":
            return {
                "kind": "array",
                "dimensions": desc["dimensions"],
                "element": describe(desc["element"]),
            }
        if kind == "pointer":
            return {"kind": "pointer", "size": desc.get("size", 4)}
        if kind == "base":
            return {
                "kind": "base",
                "size": desc.get("size", 0),
                "encoding": desc.get("encoding", 0),
            }
        return dict(sorted(desc.items()))

    def normalize(value: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": value["kind"],
            "size": value["size"],
            "alignment": value["alignment"],
            "members": [
                {
                    **{key: item for key, item in member.items() if key != "type"},
                    "type": describe(member["type"]),
                }
                for member in value["members"]
            ],
        }

    return normalize(layout)


def _canonicalize_anonymous_layouts(
    structs: dict[str, dict[str, Any]],
    roots: Iterable[str] = ROOT_TYPES,
) -> dict[str, dict[str, Any]]:
    """Replace toolchain-local anonymous DIE keys with structural identities.

    Readelf DIE offsets and declaration coordinates are not ABI facts and vary
    across GCC/binutils releases. Content addressing also makes a producer that
    shares one anonymous DIE equivalent to one that emits identical DIE copies.
    Only the root-reachable by-value graph is retained; pointers are terminals.
    """
    anonymous = {name for name in structs if name.startswith("anonymous@")}
    aliases: dict[str, str] = {}
    claimed: dict[str, str] = {}
    visiting: set[str] = set()
    reached: set[str] = set()
    fingerprint_cache: dict[str, str] = {}
    fingerprint_visiting: set[str] = set()

    def fingerprint_desc(desc: dict[str, Any]) -> dict[str, Any]:
        kind = desc.get("kind")
        if kind == "pointer":
            return {"kind": "pointer", "size": desc.get("size", 4)}
        if kind in ("struct", "union"):
            name = desc["name"]
            if name in anonymous:
                return {"kind": kind, "anonymousFingerprint": fingerprint_layout(name)}
            return {"kind": kind, "name": name}
        if kind == "typedef":
            return fingerprint_desc(desc["target"])
        if kind == "array":
            return {
                "kind": "array",
                "dimensions": desc["dimensions"],
                "element": fingerprint_desc(desc["element"]),
            }
        if kind == "base":
            return {
                "kind": "base",
                "size": desc.get("size", 0),
                "encoding": desc.get("encoding", 0),
            }
        return dict(sorted(desc.items()))

    def fingerprint_layout(name: str) -> str:
        cached = fingerprint_cache.get(name)
        if cached is not None:
            return cached
        if name in fingerprint_visiting:
            raise ContractError(f"recursive anonymous by-value layout: {name}")
        fingerprint_visiting.add(name)
        layout = structs[name]
        payload = {
            "kind": layout["kind"],
            "size": layout["size"],
            "alignment": layout["alignment"],
            "members": [
                {
                    **{key: value for key, value in member.items() if key != "type"},
                    "type": fingerprint_desc(member["type"]),
                }
                for member in layout["members"]
            ],
        }
        fingerprint_visiting.remove(name)
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        fingerprint_cache[name] = digest
        return digest

    def visit_desc(desc: dict[str, Any]) -> None:
        kind = desc.get("kind")
        if kind in ("struct", "union"):
            visit_struct(desc["name"])
        elif kind == "typedef":
            visit_desc(desc["target"])
        elif kind == "array":
            visit_desc(desc["element"])

    def visit_struct(name: str) -> None:
        if name not in structs:
            if name.startswith("anonymous@"):
                raise ContractError(
                    f"anonymous canonicalization references missing layout {name!r}"
                )
            # A pointer may name an incomplete external aggregate.  It has no
            # inline layout facts to canonicalize or serialize.
            return
        if name in anonymous and name not in aliases:
            canonical = f"anonymous::{fingerprint_layout(name)}"
            previous = claimed.get(canonical)
            if canonical in structs and canonical != name:
                raise ContractError(
                    f"anonymous canonical identity collides with named layout: {canonical}"
                )
            aliases[name] = canonical
            if previous is None:
                claimed[canonical] = name
        if name in visiting:
            return
        reached.add(name)
        visiting.add(name)
        for member in structs[name]["members"]:
            visit_desc(member["type"])
        visiting.remove(name)

    for name in roots:
        if name not in structs:
            raise ContractError(f"required ARM DWARF root missing: {name}")
        visit_struct(name)

    def rewrite(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("kind") == "pointer":
                # Pointee identity is not an inline serialized layout fact and
                # may itself be an anonymous, toolchain-local declaration.
                value["target"] = {"kind": "void"}
                return
            if (
                value.get("kind") in ("struct", "union")
                and value.get("name") in aliases
            ):
                value["name"] = aliases[value["name"]]
            for child in value.values():
                rewrite(child)
        elif isinstance(value, list):
            for child in value:
                rewrite(child)

    for name in reached:
        layout = structs[name]
        rewrite(layout)
    result: dict[str, dict[str, Any]] = {}
    for name in reached:
        layout = structs[name]
        canonical = aliases.get(name, name)
        if canonical in result:
            if result[canonical] != layout:
                raise ContractError(f"anonymous structural hash collision: {canonical}")
            continue
        result[canonical] = layout
    return dict(sorted(result.items()))


class DwarfLayouts:
    def __init__(self, units: list[dict[int, dict[str, Any]]]):
        self.units = units
        self.structs: dict[str, dict[str, Any]] = {}
        self.enums: dict[str, int] = {}
        self._building: set[tuple[int, int]] = set()
        self._recorded: dict[tuple[int, int], str] = {}
        self._named_candidates: dict[str, list[dict[str, Any]]] = {}

    def collect(self) -> tuple[dict[str, Any], dict[str, int]]:
        for unit_index, dies in enumerate(self.units):
            for offset, die in dies.items():
                if die["tag"] == "DW_TAG_enumerator":
                    name = _die_name(die)
                    value = die["attrs"].get("DW_AT_const_value")
                    if name and value is not None:
                        self.enums[name] = _attr_int(value)
                if die["tag"] in (
                    "DW_TAG_structure_type",
                    "DW_TAG_union_type",
                ) and _die_name(die):
                    self._record(unit_index, offset)
        for name, candidates in sorted(self._named_candidates.items()):
            expected = _structural_layout(candidates[0], self.structs)
            for candidate in candidates[1:]:
                actual = _structural_layout(candidate, self.structs)
                if actual != expected:
                    raise ContractError(
                        f"named aggregate {name!r} disagrees across compilation units"
                    )
        missing = [name for name in ROOT_TYPES if name not in self.structs]
        if missing:
            raise ContractError(
                f"required ARM DWARF roots missing: {', '.join(missing)}"
            )
        return _canonicalize_anonymous_layouts(self.structs, ROOT_TYPES), dict(
            sorted(self.enums.items())
        )

    def _record(self, unit_index: int, offset: int) -> str:
        dies = self.units[unit_index]
        die = dies[offset]
        name = _die_name(die) or f"anonymous@{unit_index}:{offset:x}"
        key = (unit_index, offset)
        if key in self._recorded or key in self._building:
            return name
        if "DW_AT_byte_size" not in die["attrs"]:
            return name
        self._building.add(key)
        self._recorded[key] = name
        members = []
        member_alignments = []
        for child_offset in die["children"]:
            child = dies[child_offset]
            if child["tag"] != "DW_TAG_member":
                continue
            member: dict[str, Any] = {"name": _die_name(child) or "<anonymous>"}
            location = child["attrs"].get("DW_AT_data_member_location")
            member["offset"] = _attr_int(location) if location else 0
            ref = _type_ref(child)
            member["type"] = (
                self._describe(unit_index, ref) if ref is not None else {"kind": "void"}
            )
            if "DW_AT_bit_size" in child["attrs"]:
                member["bitSize"] = _attr_int(child["attrs"]["DW_AT_bit_size"])
                bit_offset = child["attrs"].get("DW_AT_data_bit_offset")
                if bit_offset is not None:
                    member["bitOffset"] = _attr_int(bit_offset)
                elif "DW_AT_bit_offset" in child["attrs"]:
                    storage_size = self._type_size(member["type"])
                    member["bitOffset"] = (
                        member["offset"] * 8
                        + storage_size * 8
                        - _attr_int(child["attrs"]["DW_AT_bit_offset"])
                        - member["bitSize"]
                    )
            member_alignments.append(self._alignment(member["type"], member["offset"]))
            members.append(member)
        size = _attr_int(die["attrs"]["DW_AT_byte_size"])
        explicit = die["attrs"].get("DW_AT_alignment")
        alignment = (
            _attr_int(explicit)
            if explicit
            else self._aggregate_alignment(size, members, member_alignments)
        )
        layout = {
            "kind": "union" if die["tag"] == "DW_TAG_union_type" else "struct",
            "size": size,
            "alignment": alignment,
            "members": members,
        }
        if _die_name(die):
            self._named_candidates.setdefault(name, []).append(layout)
            self.structs.setdefault(name, layout)
        else:
            self.structs[name] = layout
        self._building.remove(key)
        return name

    def _type_size(self, desc: dict[str, Any]) -> int:
        kind = desc.get("kind")
        if kind == "typedef":
            return self._type_size(desc["target"])
        if kind in ("base", "enum", "pointer"):
            return int(desc["size"])
        raise ContractError(f"bitfield has unsupported storage type {kind!r}")

    def _describe(self, unit_index: int, offset: int) -> dict[str, Any]:
        dies = self.units[unit_index]
        die = dies.get(offset)
        if die is None:
            return {"kind": "unresolved", "dwarfOffset": offset}
        tag = die["tag"]
        if tag in (
            "DW_TAG_typedef",
            "DW_TAG_const_type",
            "DW_TAG_volatile_type",
            "DW_TAG_restrict_type",
        ):
            ref = _type_ref(die)
            value = (
                self._describe(unit_index, ref) if ref is not None else {"kind": "void"}
            )
            return value
        if tag in ("DW_TAG_structure_type", "DW_TAG_union_type"):
            return {
                "kind": "struct" if tag == "DW_TAG_structure_type" else "union",
                "name": self._record(unit_index, offset),
            }
        if tag == "DW_TAG_array_type":
            ref = _type_ref(die)
            element = (
                self._describe(unit_index, ref) if ref is not None else {"kind": "void"}
            )
            dimensions = []
            for child_offset in die["children"]:
                child = dies[child_offset]
                if child["tag"] != "DW_TAG_subrange_type":
                    continue
                if "DW_AT_count" in child["attrs"]:
                    dimensions.append(_attr_int(child["attrs"]["DW_AT_count"]))
                elif "DW_AT_upper_bound" in child["attrs"]:
                    dimensions.append(
                        _attr_int(child["attrs"]["DW_AT_upper_bound"]) + 1
                    )
                else:
                    raise ContractError("array has no target-readable bound")
            return {"kind": "array", "dimensions": dimensions, "element": element}
        if tag == "DW_TAG_pointer_type":
            ref = _type_ref(die)
            return {
                "kind": "pointer",
                "size": _attr_int(die["attrs"].get("DW_AT_byte_size", "4")),
                "target": self._describe(unit_index, ref)
                if ref is not None
                else {"kind": "void"},
            }
        if tag == "DW_TAG_enumeration_type":
            return {
                "kind": "enum",
                "name": _die_name(die) or "<anonymous>",
                "size": _attr_int(die["attrs"].get("DW_AT_byte_size", "4")),
            }
        if tag == "DW_TAG_base_type":
            encoding = die["attrs"].get("DW_AT_encoding")
            return {
                "kind": "base",
                "size": _attr_int(die["attrs"].get("DW_AT_byte_size", "0")),
                "encoding": _attr_int(encoding) if encoding is not None else 0,
            }
        if tag == "DW_TAG_subroutine_type":
            return {"kind": "function"}
        return {
            "kind": tag.removeprefix("DW_TAG_"),
            "name": _die_name(die) or "<anonymous>",
        }

    def _alignment(self, desc: dict[str, Any], offset: int) -> int:
        kind = desc["kind"]
        if kind == "typedef":
            return self._alignment(desc["target"], offset)
        if kind == "array":
            return self._alignment(desc["element"], offset)
        if kind in ("pointer", "base", "enum"):
            natural = min(int(desc.get("size", 1)), 4)
        elif kind in ("struct", "union") and desc.get("name") in self.structs:
            natural = self.structs[desc["name"]]["alignment"]
        else:
            natural = 1
        while natural > 1 and offset % natural:
            natural //= 2
        return max(1, natural)

    @staticmethod
    def _aggregate_alignment(
        size: int, members: list[dict[str, Any]], aligns: list[int]
    ) -> int:
        candidate = max(aligns, default=1)
        while candidate > 1 and size % candidate:
            candidate //= 2
        for member, alignment in zip(members, aligns):
            while candidate > 1 and member["offset"] % min(candidate, alignment):
                candidate //= 2
        return candidate


_MACRO_RE = re.compile(r"^#define\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.+)$")
_INT_SUFFIX_RE = re.compile(r"(?<=\d)[uUlL]+\b")
_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.BitOr: operator.or_,
    ast.BitAnd: operator.and_,
    ast.BitXor: operator.xor,
}
_ALLOWED_UNARY = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Invert: operator.invert,
}


def _eval_expr(expr: str, values: dict[str, int]) -> int:
    expr = _INT_SUFFIX_RE.sub("", expr).replace("/", "//")
    node = ast.parse(expr, mode="eval").body

    def visit(item: ast.AST) -> int:
        if isinstance(item, ast.Constant) and isinstance(item.value, int):
            return item.value
        if isinstance(item, ast.Name) and item.id in values:
            return values[item.id]
        if isinstance(item, ast.BinOp) and type(item.op) in _ALLOWED_BINOPS:
            return _ALLOWED_BINOPS[type(item.op)](visit(item.left), visit(item.right))
        if isinstance(item, ast.UnaryOp) and type(item.op) in _ALLOWED_UNARY:
            return _ALLOWED_UNARY[type(item.op)](visit(item.operand))
        raise ValueError(expr)

    return visit(node)


def _extract_constants(
    tree: Path, generated: Path, enums: dict[str, int], purpose: str
) -> dict[str, int]:
    args = [
        "arm-none-eabi-gcc",
        "-dM",
        "-E",
        "-x",
        "c",
        "-",
        *_purpose_defines(purpose),
        "-iquote",
        str(generated / "include/constants"),
        "-iquote",
        str(generated / "include"),
        "-iquote",
        str(tree / "include"),
        "-include",
        "global.h",
        "-include",
        "save.h",
        "-include",
        "hall_of_fame.h",
        "-include",
        "constants/trade.h",
    ]
    text = _run(args, tree, input_bytes=b"\n").decode(errors="replace")
    expressions: dict[str, str] = {}
    for line in text.splitlines():
        match = _MACRO_RE.match(line)
        if match and "(" not in match.group(1):
            expressions[match.group(1)] = match.group(2).strip()
    values = dict(enums)
    for _ in range(20):
        changed = False
        for name, expr in expressions.items():
            if name in values:
                continue
            try:
                values[name] = _eval_expr(expr, values)
                changed = True
            except (SyntaxError, ValueError, ZeroDivisionError):
                pass
        if not changed:
            break
    return values


def _bindings(values: dict[str, int]) -> dict[str, list[dict[str, Any]]]:
    domains = {
        "trainerIds": ("TRAINER_",),
        "flags": ("FLAG_",),
        "vars": ("VAR_",),
        "rewardState": ("FLAG_RECEIVED_", "FLAG_GOT_", "FLAG_REWARD_"),
        "tradeState": ("INGAME_TRADE_",),
        "checkpoints": ("HEAL_LOCATION_", "WARP_ID_"),
        "destinations": ("MAPSEC_", "FLAG_LANDMARK_", "FLAG_WORLD_MAP_"),
        "facilities": ("FRONTIER_", "TRAINER_HILL_", "HILL_MODE_"),
        "savedLocations": ("MAPSEC_",),
        "metLocations": ("METLOC_",),
        "gameStats": ("GAME_STAT_",),
    }
    result = {}
    for domain, prefixes in domains.items():
        entries = [
            {"symbol": name, "value": value}
            for name, value in values.items()
            if name.startswith(prefixes)
            and name not in NON_PERSISTENT_CONFIG_BINDINGS
            and not (
                domain == "trainerIds"
                and (
                    name.startswith("TRAINER_FRLG_")
                    or name.endswith(LEDGER_ONLY_TRAINER_SUFFIX)
                )
            )
        ]
        result[domain] = sorted(
            entries, key=lambda item: (item["value"], item["symbol"])
        )
    return result


def _physical(values: dict[str, int], structs: dict[str, Any]) -> dict[str, Any]:
    names = (
        "SECTOR_DATA_SIZE",
        "SAVE_BLOCK_3_CHUNK_SIZE",
        "SECTOR_FOOTER_SIZE",
        "SECTOR_SIZE",
        "NUM_SAVE_SLOTS",
        "SECTOR_SIGNATURE",
        "SPECIAL_SECTOR_SENTINEL",
        "SECTOR_ID_SAVEBLOCK2",
        "SECTOR_ID_SAVEBLOCK1_START",
        "SECTOR_ID_SAVEBLOCK1_END",
        "SECTOR_ID_PKMN_STORAGE_START",
        "SECTOR_ID_PKMN_STORAGE_END",
        "NUM_SECTORS_PER_SLOT",
        "SECTOR_ID_HOF_1",
        "SECTOR_ID_HOF_2",
        "SECTOR_ID_TRAINER_HILL",
        "SECTOR_ID_RECORDED_BATTLE",
        "SECTORS_COUNT",
    )
    missing = [name for name in names if name not in values]
    if missing:
        raise ContractError(f"physical constants missing: {', '.join(missing)}")
    constants = {name: values[name] for name in names}
    sector_members = {m["name"]: m["offset"] for m in structs["SaveSector"]["members"]}
    constants["SECTOR_SIGNATURE_OFFSET"] = sector_members["signature"]
    constants["SECTOR_COUNTER_OFFSET"] = sector_members["counter"]
    roots = (
        ("SaveBlock2", values["SECTOR_ID_SAVEBLOCK2"]),
        ("SaveBlock1", values["SECTOR_ID_SAVEBLOCK1_START"]),
        ("PokemonStorage", values["SECTOR_ID_PKMN_STORAGE_START"]),
    )
    slot_layout = []
    for structure, first_sector in roots:
        remaining = structs[structure]["size"]
        chunk = 0
        while remaining:
            size = min(remaining, values["SECTOR_DATA_SIZE"])
            sector_id = first_sector + chunk
            slot_layout.append(
                {
                    "sectorId": sector_id,
                    "payload": {
                        "structure": structure,
                        "offset": chunk * values["SECTOR_DATA_SIZE"],
                        "size": size,
                    },
                    "saveBlock3Chunk": {
                        "offset": sector_id * values["SAVE_BLOCK_3_CHUNK_SIZE"],
                        "size": min(
                            max(
                                structs["SaveBlock3"]["size"]
                                - sector_id * values["SAVE_BLOCK_3_CHUNK_SIZE"],
                                0,
                            ),
                            values["SAVE_BLOCK_3_CHUNK_SIZE"],
                        ),
                    },
                }
            )
            remaining -= size
            chunk += 1
    return {
        "constants": constants,
        "slotLayout": slot_layout,
        "saveBlock3Stream": {
            "sectorOffset": values["SECTOR_DATA_SIZE"],
            "chunkSize": values["SAVE_BLOCK_3_CHUNK_SIZE"],
            "chunkCount": values["NUM_SECTORS_PER_SLOT"],
            "capacity": values["SAVE_BLOCK_3_CHUNK_SIZE"]
            * values["NUM_SECTORS_PER_SLOT"],
            "serializedSize": structs["SaveBlock3"]["size"],
        },
        "slotSectorIds": {
            "saveBlock2": [values["SECTOR_ID_SAVEBLOCK2"]],
            "saveBlock1": list(
                range(
                    values["SECTOR_ID_SAVEBLOCK1_START"],
                    values["SECTOR_ID_SAVEBLOCK1_END"] + 1,
                )
            ),
            "pokemonStorage": list(
                range(
                    values["SECTOR_ID_PKMN_STORAGE_START"],
                    values["SECTOR_ID_PKMN_STORAGE_END"] + 1,
                )
            ),
            "hallOfFame": [values["SECTOR_ID_HOF_1"], values["SECTOR_ID_HOF_2"]],
            "trainerHill": [values["SECTOR_ID_TRAINER_HILL"]],
            "recordedBattle": [values["SECTOR_ID_RECORDED_BATTLE"]],
        },
    }


def _checksums(structs: dict[str, Any]) -> dict[str, Any]:
    def member_offset(type_name: str, member: str) -> int:
        for item in structs[type_name]["members"]:
            if item["name"] == member:
                return item["offset"]
        raise ContractError(f"{type_name}.{member} missing from DWARF")

    return {
        "mainSector": {
            "algorithm": "sum-le32-fold16",
            "coverage": {
                "ranges": "physical.slotLayout[*].payload",
                "wordSize": 4,
                "trailingPartialWord": "excluded",
            },
        },
        "boxPokemon": {
            "algorithm": "sum-le16-mod65536",
            "coverage": {
                "member": "BoxPokemon.secure",
                "offset": member_offset("BoxPokemon", "secure"),
                "size": 48,
            },
            "encryption": {"algorithm": "xor-le32", "key": "personality ^ otId"},
        },
        "emeraldRecordMixing": {
            "algorithm": "sum-le32-mod2^32",
            "coverage": {
                "type": "EmeraldBattleTowerRecord",
                "start": 0,
                "end": member_offset("EmeraldBattleTowerRecord", "checksum"),
            },
        },
        "rsRecordMixing": {
            "algorithm": "sum-le32-mod2^32",
            "coverage": {
                "type": "RSBattleTowerRecord",
                "start": 0,
                "end": member_offset("RSBattleTowerRecord", "checksum"),
            },
        },
        "trainerHill": {
            "algorithm": "sum-u8-mod2^32",
            "coverage": {
                "type": "TrainerHillChallenge",
                "start": structs["TrainerHillChallenge"]["size"],
                "end": "start + numFloors * sizeof(TrainerHillFloor)",
            },
        },
        "recordedBattle": {
            "algorithm": "sum-u8-mod2^32",
            "coverage": {
                "type": "RecordedBattleSave",
                "start": 0,
                "end": member_offset("RecordedBattleSave", "checksum"),
            },
        },
        "specialSectors": {
            "algorithm": "raw-copy",
            "coverage": {"start": 4, "end": structs["SaveSector"]["size"]},
            "sentinel": {
                "offset": 0,
                "size": 4,
                "identifier": "SPECIAL_SECTOR_SENTINEL",
            },
        },
    }


def _c_function(text: str, name: str) -> str:
    match = re.search(
        rf"^[^\n;]*\b{re.escape(name)}\s*\([^;]*?\)\s*\{{", text, re.MULTILINE
    )
    if not match:
        raise ContractError(f"serialized mechanics function is missing: {name}")
    start = match.start()
    brace = text.find("{", match.start(), match.end())
    depth = 0
    for index in range(brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ContractError(f"serialized mechanics function is unterminated: {name}")


def _source_evidence(tree: Path) -> dict[str, Any]:
    sources = {
        "src/save.c": (
            "CalculateChecksum",
            "TryReadSpecialSaveSector",
            "TryWriteSpecialSaveSector",
            "HandleWriteSector",
            "UpdateSaveAddresses",
            "SaveBlock3Size",
            "CopyToSaveBlock3",
            "CopyFromSaveBlock3",
        ),
        "src/pokemon.c": (
            "CalculateBoxMonChecksum",
            "CalculateBoxMonChecksumDecrypt",
            "CalculateBoxMonChecksumReencrypt",
        ),
        "src/battle_tower.c": (
            "CalcEmeraldBattleTowerChecksum",
            "CalcRubyBattleTowerChecksum",
        ),
        "src/recorded_battle.c": ("IsRecordedBattleSaveValid", "RecordedBattleToSave"),
        "src/ereader_helpers.c": ("TryWriteTrainerHill_Internal",),
    }
    evidence: dict[str, Any] = {}
    bodies: dict[str, str] = {}
    for relative, names in sources.items():
        text = (tree / relative).read_text(encoding="utf-8")
        for name in names:
            body = _c_function(text, name)
            bodies[name] = body
            evidence[name] = {
                "source": relative,
                "sha256": hashlib.sha256(body.encode()).hexdigest(),
            }
    save_text = (tree / "src/save.c").read_text(encoding="utf-8")
    layout_match = re.search(
        r"#define SAVEBLOCK_CHUNK\b.*?sSaveSlotLayout\[NUM_SECTORS_PER_SLOT\]\s*=\s*\{.*?^\};",
        save_text,
        re.MULTILINE | re.DOTALL,
    )
    if not layout_match:
        raise ContractError(
            "serialized mechanics initializer is missing: sSaveSlotLayout"
        )
    layout = layout_match.group(0)
    evidence["sSaveSlotLayout"] = {
        "source": "src/save.c",
        "sha256": hashlib.sha256(layout.encode()).hexdigest(),
    }
    required_fragments = {
        "CalculateChecksum": ("size / 4", "checksum >> 16"),
        "CalculateBoxMonChecksum": ("boxMon->secure.raw", ">> 16"),
        "CalculateBoxMonChecksumDecrypt": ("boxMon->otId ^ boxMon->personality",),
        "CalculateBoxMonChecksumReencrypt": ("boxMon->otId ^ boxMon->personality",),
        "CalcEmeraldBattleTowerChecksum": (
            "sizeof(struct EmeraldBattleTowerRecord) - 4",
        ),
        "CalcRubyBattleTowerChecksum": ("sizeof(struct RSBattleTowerRecord) - 4",),
        "IsRecordedBattleSaveValid": ("sizeof(*save) - 4", "CalcByteArraySum"),
        "RecordedBattleToSave": ("sizeof(*saveSector) - 4", "CalcByteArraySum"),
        "TryWriteTrainerHill_Internal": (
            "challenge->floors",
            "sizeof(struct TrainerHillFloor)",
            "CalcByteArraySum",
        ),
        "TryReadSpecialSaveSector": (
            "SPECIAL_SECTOR_SENTINEL",
            "SECTOR_COUNTER_OFFSET - 1",
        ),
        "TryWriteSpecialSaveSector": (
            "SPECIAL_SECTOR_SENTINEL",
            "SECTOR_COUNTER_OFFSET - 1",
        ),
        "HandleWriteSector": (
            "locations[sectorId].data",
            "locations[sectorId].size",
            "CopyFromSaveBlock3",
            "CalculateChecksum",
        ),
        "UpdateSaveAddresses": (
            "sSaveSlotLayout[i].offset",
            "sSaveSlotLayout[i].size",
            "gSaveBlock2Ptr",
            "gSaveBlock1Ptr",
            "gPokemonStoragePtr",
        ),
        "SaveBlock3Size": ("sectorId * SAVE_BLOCK_3_CHUNK_SIZE", "sizeof(gSaveblock3)"),
        "CopyToSaveBlock3": ("SaveBlock3Size", "sector->saveBlock3Chunk", "memcpy"),
        "CopyFromSaveBlock3": ("SaveBlock3Size", "sector->saveBlock3Chunk", "memcpy"),
    }
    for name, fragments in required_fragments.items():
        missing = [fragment for fragment in fragments if fragment not in bodies[name]]
        if missing:
            raise ContractError(
                f"{name}: serialized mechanics changed near {missing[0]!r}"
            )
    return dict(sorted(evidence.items()))


def _walk_layout_graph(structs: dict[str, Any], roots: Iterable[str]) -> set[str]:
    reached: set[str] = set()

    def walk_desc(desc: dict[str, Any], path: str) -> None:
        kind = desc.get("kind")
        if kind in ("struct", "union"):
            name = desc.get("name")
            if name not in structs:
                raise ContractError(f"{path}: referenced layout {name!r} is missing")
            walk_struct(name)
        elif kind == "typedef":
            walk_desc(desc["target"], f"{path}.target")
        elif kind == "array":
            if not desc.get("dimensions") or any(
                not isinstance(v, int) or v < 0 for v in desc["dimensions"]
            ):
                raise ContractError(f"{path}: array dimensions are incomplete")
            walk_desc(desc["element"], f"{path}.element")
        elif kind == "unresolved":
            raise ContractError(f"{path}: unresolved target DWARF type")
        elif kind not in ("base", "enum", "pointer", "void", "function"):
            raise ContractError(f"{path}: unsupported target DWARF kind {kind!r}")

    def walk_struct(name: str) -> None:
        if name in reached:
            return
        reached.add(name)
        layout = structs[name]
        if not isinstance(layout.get("size"), int) or not isinstance(
            layout.get("alignment"), int
        ):
            raise ContractError(f"$.structs.{name}: size/alignment missing")
        if not isinstance(layout.get("members"), list):
            raise ContractError(f"$.structs.{name}.members: missing")
        for index, member in enumerate(layout["members"]):
            if "name" not in member or "offset" not in member or "type" not in member:
                raise ContractError(f"$.structs.{name}.members[{index}]: incomplete")
            walk_desc(member["type"], f"$.structs.{name}.members[{index}].type")

    for root in roots:
        if root not in structs:
            raise ContractError(f"$.structs.{root}: missing")
        walk_struct(root)
    return reached


def _validate_measured_abi_shape(
    abi: Any,
    *,
    binding_symbols: dict[str, list[str]] | None = None,
) -> None:
    """Fail closed on the live measurement schema before purpose projection."""

    def exact_mapping(value: Any, keys: set[str], path: str) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != keys:
            raise ContractError(f"{path}: invalid keys")
        return value

    def string(value: Any, path: str) -> str:
        if not isinstance(value, str) or not value:
            raise ContractError(f"{path}: expected non-empty string")
        return value

    def uint(value: Any, maximum: int, path: str) -> int:
        if type(value) is not int or not 0 <= value <= maximum:
            raise ContractError(f"{path}: expected integer in range 0..{maximum}")
        return value

    def descriptor(value: Any, path: str) -> None:
        if not isinstance(value, dict):
            raise ContractError(f"{path}: expected type descriptor")
        kind = value.get("kind")
        schemas = {
            "array": {"kind", "dimensions", "element"},
            "base": {"kind", "size", "encoding"},
            "enum": {"kind", "name", "size"},
            "pointer": {"kind", "size", "target"},
            "struct": {"kind", "name"},
            "union": {"kind", "name"},
            "void": {"kind"},
            "function": {"kind"},
        }
        if (
            not isinstance(kind, str)
            or kind not in schemas
            or set(value) != schemas[kind]
        ):
            raise ContractError(f"{path}: invalid {kind!r} descriptor keys")
        if kind in ("enum", "struct", "union"):
            string(value["name"], f"{path}.name")
        if kind == "array":
            dimensions = value["dimensions"]
            if not isinstance(dimensions, list) or not dimensions:
                raise ContractError(f"{path}.dimensions: expected non-empty list")
            cardinality = 1
            for index, dimension in enumerate(dimensions):
                cardinality *= uint(
                    dimension, 0xFFFFFFFF, f"{path}.dimensions[{index}]"
                )
            uint(cardinality, 0xFFFFFFFF, f"{path}.cardinality")
            descriptor(value["element"], f"{path}.element")
        elif kind == "base":
            uint(value["size"], 0xFFFF, f"{path}.size")
            uint(value["encoding"], 0xFFFF, f"{path}.encoding")
        elif kind == "enum":
            uint(value["size"], 0xFFFFFFFF, f"{path}.size")
        elif kind == "pointer":
            uint(value["size"], 0xFFFFFFFF, f"{path}.size")
            descriptor(value["target"], f"{path}.target")
        elif kind in ("struct", "union") and value["name"] not in structs:
            raise ContractError(f"{path}.name: referenced layout is missing")

    exact_mapping(abi, set(MEASURED_ABI_KEYS), "$")
    if type(abi["schemaVersion"]) is not int or abi["schemaVersion"] != SCHEMA_VERSION:
        raise ContractError("$.schemaVersion: unsupported")
    string(abi["target"], "$.target")
    structs = abi["structs"]
    if not isinstance(structs, dict) or not structs:
        raise ContractError("$.structs: expected non-empty mapping")
    for name, layout in structs.items():
        string(name, "$.structs key")
        path = f"$.structs.{name}"
        exact_mapping(layout, {"kind", "size", "alignment", "members"}, path)
        if layout["kind"] not in ("struct", "union"):
            raise ContractError(f"{path}.kind: expected struct or union")
        uint(layout["size"], 0xFFFFFF, f"{path}.size")
        uint(layout["alignment"], 0xFF, f"{path}.alignment")
        members = layout["members"]
        if not isinstance(members, list):
            raise ContractError(f"{path}.members: expected list")
        for index, member in enumerate(members):
            member_path = f"{path}.members[{index}]"
            if not isinstance(member, dict):
                raise ContractError(f"{member_path}: expected mapping")
            keys = set(member)
            if keys not in (
                {"name", "offset", "type"},
                {"name", "offset", "type", "bitOffset", "bitSize"},
            ):
                raise ContractError(f"{member_path}: invalid keys")
            string(member["name"], f"{member_path}.name")
            uint(member["offset"], 0xFFFFFFFF, f"{member_path}.offset")
            descriptor(member["type"], f"{member_path}.type")
            if "bitSize" in member:
                uint(member["bitOffset"], 0xFFFFFF, f"{member_path}.bitOffset")
                uint(member["bitSize"], 0xFF, f"{member_path}.bitSize")

    reached = _walk_layout_graph(structs, ROOT_TYPES)
    if reached != set(structs):
        unexpected = sorted(set(structs) - reached)
        raise ContractError(f"$.structs: unreachable layouts {unexpected}")

    if not isinstance(abi["physical"], dict):
        raise ContractError("$.physical: expected mapping")
    if not isinstance(abi["checksums"], dict):
        raise ContractError("$.checksums: expected mapping")
    bindings = abi["publishedBindings"]
    if not isinstance(bindings, dict) or set(bindings) != PUBLISHED_BINDING_DOMAINS:
        raise ContractError("$.publishedBindings: invalid domains")
    for domain, entries in bindings.items():
        path = f"$.publishedBindings.{domain}"
        if not isinstance(entries, list) or not entries:
            raise ContractError(f"{path}: expected non-empty list")
        symbols = []
        previous: tuple[int, str] | None = None
        for index, entry in enumerate(entries):
            entry_path = f"{path}[{index}]"
            exact_mapping(entry, {"symbol", "value"}, entry_path)
            symbol = string(entry["symbol"], f"{entry_path}.symbol")
            value = entry["value"]
            if type(value) is not int or not -0x80000000 <= value <= 0xFFFFFFFF:
                raise ContractError(f"{entry_path}.value: outside 32-bit C range")
            order = (value, symbol)
            if previous is not None and order <= previous:
                raise ContractError(f"{path}: entries are not uniquely sorted")
            previous = order
            symbols.append(symbol)
            if symbol in NON_PERSISTENT_CONFIG_BINDINGS:
                raise ContractError(
                    f"{entry_path}.symbol: compile-configuration control is not a "
                    "persistent binding"
                )
        if binding_symbols is not None and symbols != binding_symbols[domain]:
            raise ContractError(f"{path}: published symbol shape changed")


def abi_evidence_values(abi: dict[str, Any]) -> list[tuple[str, int]]:
    """Return exact path-addressed linked structural ABI facts.

    Member offsets and recursive type leaves deliberately remain separate.
    Paths carry the structural kind/reference identity, while values carry
    numeric target facts.  This costs one word per fact but admits no lossy
    offset/type digest or cross-member deduplication collision.
    """
    structs = abi["structs"]
    _walk_layout_graph(structs, ROOT_TYPES)
    aliases: dict[str, str] = {}

    def visit_desc(desc: dict[str, Any], owner: str) -> None:
        kind = desc.get("kind")
        if kind in ("struct", "union"):
            visit_struct(desc["name"], owner)
        elif kind == "typedef":
            visit_desc(desc["target"], owner)
        elif kind == "array":
            visit_desc(desc["element"], owner)

    def visit_struct(name: str, owner: str) -> None:
        if name in aliases:
            return
        canonical = owner if name.startswith("anonymous@") else name
        aliases[name] = canonical
        for index, member in enumerate(structs[name]["members"]):
            visit_desc(member["type"], f"{canonical}.members[{index}]")

    for root in ROOT_TYPES:
        visit_struct(root, root)
    values: list[tuple[str, int]] = []

    def uint(value: Any, maximum: int, path: str) -> int:
        if type(value) is not int or not 0 <= value <= maximum:
            raise ContractError(f"{path}: cannot be encoded")
        return value

    def string_facts(value: Any, path: str) -> list[tuple[str, int]]:
        if not isinstance(value, str):
            raise ContractError(f"{path}: string is missing")
        encoded = value.encode("utf-8")
        uint(len(encoded), 0xFFFFFFFF, f"{path}.utf8Length")
        facts = [(f"{path}.utf8Length", len(encoded))]
        for index in range(0, len(encoded), 4):
            chunk = encoded[index : index + 4]
            facts.append(
                (
                    f"{path}.utf8Words[{index // 4}]",
                    int.from_bytes(chunk.ljust(4, b"\0"), "little"),
                )
            )
        return facts

    def type_facts(desc: dict[str, Any], path: str) -> list[tuple[str, int]]:
        """Encode a type as exact path-addressed facts, without a digest."""
        kind = desc.get("kind")
        identity = string_facts(kind, f"{path}.kind")
        if kind == "typedef":
            return type_facts(desc["target"], path)
        if kind == "array":
            facts = []
            cardinality = 1
            for index, dimension in enumerate(desc["dimensions"]):
                dimension = uint(
                    dimension,
                    0xFFFFFFFF,
                    f"{path}.array.dimensions[{index}]",
                )
                cardinality *= dimension
                facts.append((f"{path}.array.dimensions[{index}]", dimension))
            uint(cardinality, 0xFFFFFFFF, f"{path}.array.cardinality")
            facts.append((f"{path}.array.cardinality", cardinality))
            return (
                identity + facts + type_facts(desc["element"], f"{path}.array.element")
            )
        if kind == "base":
            size = uint(desc.get("size"), 0xFFFF, f"{path}.base.size")
            encoding = uint(desc.get("encoding"), 0xFFFF, f"{path}.base.encoding")
            return identity + [(f"{path}.base.sizeEncoding", (size << 16) | encoding)]
        if kind == "enum":
            size = uint(desc.get("size"), 0xFFFFFFFF, f"{path}.enum.size")
            return (
                identity
                + string_facts(desc.get("name"), f"{path}.enum.name")
                + [(f"{path}.enum.size", size)]
            )
        if kind == "pointer":
            size = uint(desc.get("size"), 0xFFFFFFFF, f"{path}.pointer.size")
            return (
                identity
                + [(f"{path}.pointer.size", size)]
                + type_facts(desc["target"], f"{path}.pointer.target")
            )
        if kind in ("struct", "union"):
            return identity + string_facts(desc.get("name"), f"{path}.{kind}.name")
        if kind in ("void", "function"):
            return identity
        raise ContractError(f"{path}: unsupported target DWARF kind {kind!r}")

    for name in sorted(aliases, key=lambda item: aliases[item]):
        layout = structs[name]
        base = f"$.structs.{aliases[name]}"
        size = uint(layout.get("size"), 0xFFFFFF, f"{base}.size")
        alignment = uint(layout.get("alignment"), 0xFF, f"{base}.alignment")
        values.extend(string_facts(aliases[name], f"{base}.name"))
        values.extend(string_facts(layout.get("kind"), f"{base}.kind"))
        values.append(
            (
                f"{base}.sizeAlignment",
                (size << 8) | alignment,
            )
        )
        for index, member in enumerate(layout["members"]):
            member_path = f"{base}.members[{index}]"
            offset = uint(member.get("offset"), 0xFFFFFFFF, f"{member_path}.offset")
            values.extend(string_facts(member.get("name"), f"{member_path}.name"))
            values.append(
                (
                    f"{member_path}.offset",
                    offset,
                )
            )
            values.extend(type_facts(member["type"], f"{member_path}.type"))
            if "bitSize" in member:
                # Accept the pre-canonical schema while regenerating an older
                # checked-in contract; new measurements only write bitOffset.
                bit_offset = member.get("bitOffset", member.get("legacyBitOffset"))
                bit_offset = uint(bit_offset, 0xFFFFFF, f"{member_path}.bitOffset")
                bit_size = uint(member.get("bitSize"), 0xFF, f"{member_path}.bitSize")
                values.append(
                    (
                        f"{member_path}.bitOffsetSize",
                        (bit_offset << 8) | bit_size,
                    )
                )
    return values


def render_abi_evidence(abi: dict[str, Any]) -> bytes:
    lines = ["/* Generated by tools/persistence/contract.py; do not edit. */"]
    for path, value in abi_evidence_values(abi):
        lines.append(f"SAVE_ABI_VALUE(0x{value:08X}u) /* {path} */")
    return ("\n".join(lines) + "\n").encode()


def _frozen_evidence(abi: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"path": path, "value": value} for path, value in abi_evidence_values(abi)]


def abi_evidence_values_for_purpose(
    contract: dict[str, Any], purpose: str
) -> list[tuple[str, int]]:
    if purpose not in ABI_PURPOSES:
        raise ContractError(f"unknown ABI purpose: {purpose}")
    purpose_evidence = contract.get("purposeAbiEvidence")
    if not isinstance(purpose_evidence, dict) or purpose not in purpose_evidence:
        raise ContractError(f"$.purposeAbiEvidence.{purpose}: missing")
    entries = purpose_evidence[purpose]
    if not isinstance(entries, list):
        raise ContractError(f"$.purposeAbiEvidence.{purpose}: invalid")
    result = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {"path", "value"}:
            raise ContractError(f"$.purposeAbiEvidence.{purpose}[{index}]: invalid")
        if not isinstance(entry["path"], str) or not isinstance(entry["value"], int):
            raise ContractError(f"$.purposeAbiEvidence.{purpose}[{index}]: invalid")
        result.append((entry["path"], entry["value"]))
    return result


def measure_tree(tree: Path, purpose: str = "normal") -> dict[str, Any]:
    tree = tree.resolve()
    with tempfile.TemporaryDirectory(prefix="save-abi-") as tmp:
        objects = _compile_units(tree, Path(tmp), purpose)
        layouts, enums = DwarfLayouts(_merge_dies(objects, tree)).collect()
        values = _extract_constants(tree, _prepare_tree(tree), enums, purpose)
    _walk_layout_graph(layouts, ROOT_TYPES)
    checksums = _checksums(layouts)
    checksums["sourceEvidence"] = _source_evidence(tree)
    physical = _physical(values, layouts)
    physical_names = (
        "sSaveSlotLayout",
        "HandleWriteSector",
        "UpdateSaveAddresses",
        "SaveBlock3Size",
        "CopyToSaveBlock3",
        "CopyFromSaveBlock3",
    )
    physical["sourceEvidence"] = {
        name: checksums["sourceEvidence"][name] for name in physical_names
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "target": "arm-none-eabi/armv4t/apcs-gnu",
        "structs": layouts,
        "physical": physical,
        "checksums": checksums,
        "publishedBindings": _bindings(values),
    }


def seed_from_commit(repo: Path, baseline: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="save-contract-baseline-") as tmp:
        snapshot = Path(tmp)
        sha = export_baseline(repo, baseline, snapshot)
        anchor_source = repo / "tools/persistence/abi_anchor.c"
        if not anchor_source.exists():
            raise ContractError("task ABI anchor is missing")
        destination = snapshot / "tools/persistence/abi_anchor.c"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(anchor_source, destination)
        measurements = {
            purpose: measure_tree(snapshot, purpose) for purpose in ABI_PURPOSES
        }
        measured = measurements["normal"]
        invariant = {key: value for key, value in measured.items() if key != "structs"}
        for purpose, purpose_measurement in measurements.items():
            compare(
                invariant,
                {
                    key: value
                    for key, value in purpose_measurement.items()
                    if key != "structs"
                },
                f"$.purposeInvariant.{purpose}",
            )
        purpose_evidence = {
            purpose: _frozen_evidence(value) for purpose, value in measurements.items()
        }
    return {"baselineCommit": sha, **measured, "purposeAbiEvidence": purpose_evidence}


def validate_contract(contract: dict[str, Any]) -> None:
    if not isinstance(contract, dict):
        raise ContractError("$: expected contract mapping")
    allowed_keys = MEASURED_ABI_KEYS | CONTRACT_METADATA_KEYS
    required_keys = MEASURED_ABI_KEYS | {"baselineCommit", "purposeAbiEvidence"}
    if not required_keys <= set(contract) or not set(contract) <= allowed_keys:
        raise ContractError("$: invalid contract keys")
    measured = {key: contract[key] for key in MEASURED_ABI_KEYS}
    _validate_measured_abi_shape(measured)
    if contract.get("schemaVersion") != SCHEMA_VERSION:
        raise ContractError("$.schemaVersion: unsupported")
    baseline = contract.get("baselineCommit")
    if not isinstance(baseline, str) or not re.fullmatch(r"[0-9a-f]{40}", baseline):
        raise ContractError("$.baselineCommit: expected full commit SHA")
    if not contract.get("structs"):
        raise ContractError("$.structs: empty")
    if not contract.get("publishedBindings"):
        raise ContractError("$.publishedBindings: empty")
    purpose_budgets = contract.get("purposeBudgets")
    if purpose_budgets is not None:
        _validate_purpose_budgets(purpose_budgets)
    _project_compatible_tail_extension(contract)
    for name in ROOT_TYPES:
        if name not in contract["structs"]:
            raise ContractError(f"$.structs.{name}: missing")
    _walk_layout_graph(contract["structs"], ROOT_TYPES)
    if set(contract.get("purposeAbiEvidence", {})) != set(ABI_PURPOSES):
        raise ContractError(f"$.purposeAbiEvidence: expected {list(ABI_PURPOSES)}")
    for purpose in ABI_PURPOSES:
        values = abi_evidence_values_for_purpose(contract, purpose)
        if not values:
            raise ContractError(f"$.purposeAbiEvidence.{purpose}: empty")
        if len({path for path, _ in values}) != len(values):
            raise ContractError(f"$.purposeAbiEvidence.{purpose}: duplicate path")
    compare(
        abi_evidence_values(contract),
        abi_evidence_values_for_purpose(contract, "normal"),
        "$.purposeAbiEvidence.normal",
    )
    checksum_evidence = contract.get("checksums", {}).get("sourceEvidence")
    if not isinstance(checksum_evidence, dict) or not checksum_evidence:
        raise ContractError("$.checksums.sourceEvidence: missing")
    for name, record in checksum_evidence.items():
        if not isinstance(record, dict) or set(record) != {"source", "sha256"}:
            raise ContractError(f"$.checksums.sourceEvidence.{name}: invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", record.get("sha256", "")):
            raise ContractError(f"$.checksums.sourceEvidence.{name}.sha256: invalid")
    for domain, entries in contract["publishedBindings"].items():
        if not entries:
            raise ContractError(f"$.publishedBindings.{domain}: empty")
        symbols = [entry["symbol"] for entry in entries]
        if len(symbols) != len(set(symbols)):
            raise ContractError(f"$.publishedBindings.{domain}: duplicate symbol")
    _verify_checksum_vectors()


def validate_abi(
    contract: dict[str, Any], actual: dict[str, Any], purpose: str
) -> None:
    validate_contract(contract)
    if purpose not in ABI_PURPOSES:
        raise ContractError(f"unknown ABI purpose: {purpose}")
    binding_symbols = {
        domain: [entry["symbol"] for entry in entries]
        for domain, entries in contract["publishedBindings"].items()
    }
    _validate_measured_abi_shape(actual, binding_symbols=binding_symbols)
    projected = {
        key: value
        for key, value in _project_compatible_tail_extension(contract).items()
        if key not in CONTRACT_METADATA_KEYS
    }
    actual_projected = dict(actual)
    if purpose != "normal":
        projected.pop("structs")
        actual_projected.pop("structs")
    compare(projected, actual_projected)
    compare(
        projected_abi_evidence_values_for_purpose(contract, purpose),
        abi_evidence_values(actual),
        f"$.purposeAbiEvidence.{purpose}",
    )


def _tail_extension_metadata(contract: dict[str, Any]) -> dict[str, int] | None:
    metadata = contract.get("compatibleTailExtension")
    if metadata is None:
        return None
    expected = {
        "baseBitmapBytes": 79,
        "baseSaveBlock1Size": 15648,
        "baseSector4PayloadSize": 3744,
        "currentBitmapBytes": 103,
        "currentSaveBlock1Size": 15672,
        "currentSector4PayloadSize": 3768,
        "memberIndex": 84,
        "memberOffset": 15568,
    }
    if metadata != expected:
        raise ContractError("$.compatibleTailExtension: unsupported evolution")
    return metadata


def _project_compatible_tail_extension(contract: dict[str, Any]) -> dict[str, Any]:
    """Project the one reviewed SaveBlock1 append while retaining frozen evidence."""

    metadata = _tail_extension_metadata(contract)
    if metadata is None:
        return contract
    projected = copy.deepcopy(contract)
    layout = projected["structs"]["SaveBlock1"]
    index = metadata["memberIndex"]
    if layout.get("size") != metadata["baseSaveBlock1Size"]:
        raise ContractError("$.compatibleTailExtension: base SaveBlock1 size drifted")
    members = layout.get("members")
    if not isinstance(members, list) or index != len(members) - 1:
        raise ContractError("$.compatibleTailExtension: trainer bitmap is not the tail")
    member = members[index]
    expected_member = {
        "name": "trainerDefeated",
        "offset": metadata["memberOffset"],
        "type": {
            "dimensions": [metadata["baseBitmapBytes"]],
            "element": {"encoding": 8, "kind": "base", "size": 1},
            "kind": "array",
        },
    }
    if member != expected_member:
        raise ContractError("$.compatibleTailExtension: frozen tail member drifted")
    slots = projected["physical"]["slotLayout"]
    sector = next((item for item in slots if item.get("sectorId") == 4), None)
    expected_payload = {
        "offset": 11904,
        "size": metadata["baseSector4PayloadSize"],
        "structure": "SaveBlock1",
    }
    if sector is None or sector.get("payload") != expected_payload:
        raise ContractError("$.compatibleTailExtension: sector 4 base payload drifted")
    layout["size"] = metadata["currentSaveBlock1Size"]
    member["type"]["dimensions"] = [metadata["currentBitmapBytes"]]
    sector["payload"]["size"] = metadata["currentSector4PayloadSize"]
    return projected


def projected_abi_evidence_values_for_purpose(
    contract: dict[str, Any], purpose: str
) -> list[tuple[str, int]]:
    evidence = abi_evidence_values_for_purpose(contract, purpose)
    metadata = _tail_extension_metadata(contract)
    if metadata is None:
        return evidence
    replacements = {
        "$.structs.SaveBlock1.sizeAlignment": (
            metadata["baseSaveBlock1Size"] << 8 | 4,
            metadata["currentSaveBlock1Size"] << 8 | 4,
        ),
        "$.structs.SaveBlock1.members[84].type.array.dimensions[0]": (
            metadata["baseBitmapBytes"],
            metadata["currentBitmapBytes"],
        ),
        "$.structs.SaveBlock1.members[84].type.array.cardinality": (
            metadata["baseBitmapBytes"],
            metadata["currentBitmapBytes"],
        ),
    }
    projected = []
    seen = set()
    for path, value in evidence:
        replacement = replacements.get(path)
        if replacement is not None:
            if value != replacement[0]:
                raise ContractError(
                    f"$.compatibleTailExtension: frozen evidence drifted at {path}"
                )
            value = replacement[1]
            seen.add(path)
        projected.append((path, value))
    if seen != set(replacements):
        raise ContractError("$.compatibleTailExtension: frozen evidence is incomplete")
    return projected


def _validate_purpose_budgets(value: Any) -> None:
    path = "$.purposeBudgets"
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "limits",
        "baselines",
    }:
        raise ContractError(f"{path}: invalid metadata shape")
    if value["schemaVersion"] != 1:
        raise ContractError(f"{path}.schemaVersion: unsupported")
    expected_limits = {
        "romBytes": 33554432,
        "ewramBytes": 262144,
        "iwramBytes": 32768,
        "releaseHeadroomBytes": 2708917,
    }
    if value["limits"] != expected_limits:
        raise ContractError(f"{path}.limits: published limits changed")
    baselines = value["baselines"]
    names = {"normal", "debug", "release", "test-runner", "headless-test"}
    if not isinstance(baselines, dict) or set(baselines) != names:
        raise ContractError(f"{path}.baselines: expected {sorted(names)}")
    for name, record in baselines.items():
        record_path = f"{path}.baselines.{name}"
        if not isinstance(record, dict) or set(record) != {
            "artifact",
            "romBytes",
            "ewramBytes",
            "iwramBytes",
        }:
            raise ContractError(f"{record_path}: invalid baseline shape")
        if not isinstance(record["artifact"], str) or not record["artifact"]:
            raise ContractError(f"{record_path}.artifact: expected nonempty string")
        for field in ("romBytes", "ewramBytes", "iwramBytes"):
            if (
                not isinstance(record[field], int)
                or isinstance(record[field], bool)
                or record[field] < 0
            ):
                raise ContractError(
                    f"{record_path}.{field}: expected nonnegative integer"
                )


def _verify_checksum_vectors() -> None:
    data = bytes(range(48))
    words = [
        int.from_bytes(data[index : index + 4], "little") for index in range(0, 16, 4)
    ]
    total = sum(words)
    if ((total >> 16) + total) & 0xFFFF != 0x4038:
        raise ContractError("checksum mechanics: main-sector fixed vector failed")
    halfwords = [
        int.from_bytes(data[index : index + 2], "little") for index in range(0, 48, 2)
    ]
    if sum(halfwords) & 0xFFFF != 0x4228:
        raise ContractError("checksum mechanics: BoxPokemon fixed vector failed")
    if sum(data) & 0xFFFFFFFF != 0x468:
        raise ContractError("checksum mechanics: byte-sum fixed vector failed")
    encrypted = int.from_bytes(data[:4], "little") ^ int.from_bytes(data[4:8], "little")
    if encrypted.to_bytes(4, "little") != b"\x04\x04\x04\x04":
        raise ContractError("encryption mechanics: BoxPokemon fixed vector failed")


PURPOSE_ARTIFACTS = {
    "normal": ("pokemon-openworld.gba", "pokemon-openworld.elf", []),
    "debug": (
        "pokemon-openworld-debug.gba",
        "pokemon-openworld-debug.elf",
        ["DEBUG=1"],
    ),
    "release": (
        "pokemon-openworld-release.gba",
        "pokemon-openworld-release.elf",
        ["RELEASE=1"],
    ),
    "test-runner": ("pokemon-openworld-test.elf", "pokemon-openworld-test.elf", []),
    "headless-test": (
        "pokemon-openworld-test-headless.elf",
        "pokemon-openworld-test-headless.elf",
        [],
    ),
}


def _parse_elf_sections(text: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r"^\s*\[\s*\d+\]\s+(?P<name>\S+)\s+(?P<type>\S+)\s+"
        r"(?P<address>[0-9a-fA-F]+)\s+(?P<offset>[0-9a-fA-F]+)\s+"
        r"(?P<size>[0-9a-fA-F]+)\s+\S+\s+(?P<flags>\S*)",
        re.MULTILINE,
    )
    sections = [
        {
            "name": m.group("name"),
            "type": m.group("type"),
            "address": int(m.group("address"), 16),
            "size": int(m.group("size"), 16),
            "flags": m.group("flags"),
        }
        for m in pattern.finditer(text)
    ]
    if not sections:
        raise ContractError("ELF section table is empty or unreadable")
    return sections


def _measure_elf_capacity(tree: Path, elf: Path) -> dict[str, int]:
    sections = _parse_elf_sections(
        _run(["arm-none-eabi-readelf", "-SW", str(elf)], tree).decode(errors="replace")
    )

    def range_bytes(origin: int, limit: int, *, loadable: bool = False) -> int:
        candidates = [
            item
            for item in sections
            if "A" in item["flags"]
            and origin <= item["address"] < origin + limit
            and (not loadable or item["type"] != "NOBITS")
        ]
        if not candidates:
            raise ContractError(f"ELF has no allocatable sections at 0x{origin:08x}")
        end = max(item["address"] + item["size"] for item in candidates)
        if end > origin + limit:
            raise ContractError(f"ELF exceeds memory ending at 0x{origin + limit:08x}")
        return end - origin

    return {
        "romBytes": range_bytes(0x08000000, 33554432, loadable=True),
        "ewramBytes": range_bytes(0x02000000, 262144),
        "iwramBytes": range_bytes(0x03000000, 32768),
    }


def seed_budgets(
    repo: Path,
    baseline: str,
    *,
    rom_max: int,
    ewram_max: int,
    iwram_max: int,
    release_headroom: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="save-budget-baseline-") as tmp:
        tree = Path(tmp)
        sha = export_baseline(repo, baseline, tree)
        if sha != baseline:
            raise ContractError(
                f"budget baseline resolved to {sha}, expected {baseline}"
            )
        build_env = dict(os.environ, GITHUB_ACTION="1")
        records = {}
        for purpose, (artifact, elf_name, flags) in PURPOSE_ARTIFACTS.items():
            if purpose == "headless-test":
                # The frozen baseline creates this only inside `make check`; do
                # the non-emulator copy/patch portion explicitly so seeding does
                # not run tests and still measures the exact baseline artifact.
                source = tree / PURPOSE_ARTIFACTS["test-runner"][1]
                destination = tree / elf_name
                if not source.is_file():
                    raise ContractError(
                        "baseline test-runner ELF was not built before headless copy"
                    )
                shutil.copyfile(source, destination)
                _run(
                    [
                        str(tree / "tools/patchelf/patchelf"),
                        str(destination),
                        "gTestRunnerHeadless",
                        r"\x01",
                        "gTestRunnerSkipIsFail",
                        r"\x00",
                    ],
                    tree,
                    env=build_env,
                )
            else:
                _run(["make", "-s", "-j2", *flags, artifact], tree, env=build_env)
            usage = _measure_elf_capacity(tree, tree / elf_name)
            records[purpose] = {"artifact": artifact, **usage}
    return {
        "schemaVersion": 1,
        "limits": {
            "romBytes": rom_max,
            "ewramBytes": ewram_max,
            "iwramBytes": iwram_max,
            "releaseHeadroomBytes": release_headroom,
        },
        "baselines": records,
    }


def _report_usage(report: dict[str, Any], purpose: str) -> tuple[str, dict[str, int]]:
    if "purposeBudget" in report:
        block = report["purposeBudget"]
        actual_purpose, usage = block.get("purpose"), block.get("usage")
        artifact = block.get("baseline", {}).get("artifact", "")
    else:
        actual_purpose, usage = report.get("purpose"), report.get("usage")
        artifact = Path(report.get("artifact", "")).name
    if actual_purpose != purpose or not isinstance(usage, dict):
        raise ContractError(f"$.reports.{purpose}: wrong purpose or missing usage")
    expected_artifact = PURPOSE_ARTIFACTS[purpose][0]
    if Path(artifact).name != expected_artifact:
        raise ContractError(
            f"$.reports.{purpose}.artifact: expected {expected_artifact}"
        )
    if set(usage) != {"romBytes", "ewramBytes", "iwramBytes"}:
        raise ContractError(f"$.reports.{purpose}.usage: invalid")
    return artifact, usage


def validate_budgets(contract: dict[str, Any], reports_dir: Path) -> None:
    budgets = contract.get("purposeBudgets")
    _validate_purpose_budgets(budgets)
    limits = budgets["limits"]
    expected_files = {f"{purpose}.json" for purpose in PURPOSE_ARTIFACTS}
    actual_files = {path.name for path in reports_dir.glob("*.json")}
    if actual_files != expected_files:
        raise ContractError(
            f"$.reports: expected exactly {sorted(expected_files)}, got {sorted(actual_files)}"
        )
    for purpose in PURPOSE_ARTIFACTS:
        report = load_json(reports_dir / f"{purpose}.json")
        _, usage = _report_usage(report, purpose)
        for field in ("romBytes", "ewramBytes", "iwramBytes"):
            value = usage[field]
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ContractError(f"$.reports.{purpose}.usage.{field}: invalid")
            if value > limits[field]:
                raise ContractError(f"{purpose} {field} exceeds reviewed limit")
        if (
            purpose == "release"
            and limits["romBytes"] - usage["romBytes"] < limits["releaseHeadroomBytes"]
        ):
            raise ContractError("release ROM headroom below reviewed floor")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    measure = sub.add_parser("measure-abi")
    measure.add_argument("--tree", type=Path, required=True)
    measure.add_argument("--output", type=Path, required=True)
    measure.add_argument("--purpose", choices=ABI_PURPOSES, default="normal")
    seed = sub.add_parser("seed-save-contract")
    seed.add_argument("--baseline", default=BASELINE_SHA)
    seed.add_argument("--output", type=Path, required=True)
    seed_budget = sub.add_parser("seed-budgets")
    seed_budget.add_argument("--baseline", required=True)
    seed_budget.add_argument("--contract", type=Path, required=True)
    seed_budget.add_argument("--rom-max", type=int, required=True)
    seed_budget.add_argument("--ewram-max", type=int, required=True)
    seed_budget.add_argument("--iwram-max", type=int, required=True)
    seed_budget.add_argument("--release-rom-headroom-min", type=int, required=True)
    validate_budget = sub.add_parser("validate-budgets")
    validate_budget.add_argument("--contract", type=Path, required=True)
    validate_budget.add_argument("--reports", type=Path, required=True)
    generate_evidence = sub.add_parser("generate-abi-evidence")
    generate_evidence.add_argument("--abi", type=Path, required=True)
    generate_evidence.add_argument("--output", type=Path, required=True)
    validate = sub.add_parser("validate-contract")
    validate.add_argument("--contract", type=Path, required=True)
    check = sub.add_parser("validate")
    check.add_argument("--contract", type=Path, required=True)
    check.add_argument("--abi", type=Path, required=True)
    check.add_argument("--purpose", choices=ABI_PURPOSES, default="normal")
    args = parser.parse_args(argv)
    try:
        if args.command == "measure-abi":
            write_json(args.output, measure_tree(args.tree, args.purpose))
            print(f"PASS: wrote {args.output} for {args.purpose}")
        elif args.command == "seed-save-contract":
            value = seed_from_commit(Path.cwd(), args.baseline)
            if args.output.exists():
                existing = load_json(args.output)
                if "purposeBudgets" in existing:
                    value["purposeBudgets"] = existing["purposeBudgets"]
            validate_contract(value)
            write_json(args.output, value)
            print(f"PASS: wrote {args.output} from {value['baselineCommit']}")
        elif args.command == "seed-budgets":
            contract = load_json(args.contract)
            if contract.get("baselineCommit") != args.baseline:
                raise ContractError("--baseline differs from contract baselineCommit")
            contract["purposeBudgets"] = seed_budgets(
                Path.cwd(),
                args.baseline,
                rom_max=args.rom_max,
                ewram_max=args.ewram_max,
                iwram_max=args.iwram_max,
                release_headroom=args.release_rom_headroom_min,
            )
            validate_contract(contract)
            write_json(args.contract, contract)
            print(f"PASS: seeded five purpose budgets from {args.baseline}")
        elif args.command == "validate-budgets":
            validate_budgets(load_json(args.contract), args.reports)
            print("PASS: all five purpose budgets")
        elif args.command == "generate-abi-evidence":
            abi = load_json(args.abi)
            data = render_abi_evidence(abi)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            if not args.output.exists() or args.output.read_bytes() != data:
                args.output.write_bytes(data)
            print(
                f"PASS: wrote {len(abi_evidence_values(abi))} linked ABI values to {args.output}"
            )
        elif args.command == "validate-contract":
            validate_contract(load_json(args.contract))
            print(f"PASS: {args.contract}")
        else:
            expected = load_json(args.contract)
            actual = load_json(args.abi)
            validate_abi(expected, actual, args.purpose)
            print(f"PASS: live ARM ABI matches frozen contract for {args.purpose}")
        return 0
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
