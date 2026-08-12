#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import struct


ROM_BASE = 0x08000000
CONTRACT_SYMBOL = "gNewGameStartProductionContract"
PROFILES_SYMBOL = "gNewGameStartProfiles"
REQUEST_SYMBOL = "gDebugNewGameStartProfileRequest"
EXPECTED_PROFILES = bytes((0, 1, 0, 0, 23, 1, 1, 0, 43, 1, 1, 0))


class StartProfileContractError(ValueError):
    pass


def parse_symbols(path: Path) -> dict[str, int]:
    symbols: dict[str, int] = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        fields = line.split()
        if len(fields) < 4 or len(fields[0]) != 8:
            raise StartProfileContractError(f"{path}:{number}: malformed symbol line")
        try:
            address = int(fields[0], 16)
        except ValueError as error:
            raise StartProfileContractError(
                f"{path}:{number}: malformed symbol address"
            ) from error
        if fields[1] == "g" or fields[-1] not in symbols:
            symbols[fields[-1]] = address
    return symbols


def read_rom_symbol(rom: bytes, symbols: dict[str, int], name: str, size: int) -> bytes:
    try:
        address = symbols[name]
    except KeyError as error:
        raise StartProfileContractError(f"linked symbols do not define {name}") from error
    offset = (address & ~1) - ROM_BASE
    if offset < 0 or offset + size > len(rom):
        raise StartProfileContractError(f"{name} points outside the ROM artifact")
    return rom[offset : offset + size]


def verify_variant(rom_path: Path, sym_path: Path, *, debug: bool) -> None:
    rom = rom_path.read_bytes()
    symbols = parse_symbols(sym_path)
    contract = read_rom_symbol(rom, symbols, CONTRACT_SYMBOL, 8)
    abi, default, selector, count, request_size, status_offset, reserved = struct.unpack(
        "<H6B", contract
    )
    expected = (1, 0, int(debug), 3, 8 if debug else 0, 7 if debug else 0, 0)
    actual = (abi, default, selector, count, request_size, status_offset, reserved)
    if actual != expected:
        raise StartProfileContractError(
            f"{rom_path}: start-profile contract {actual!r}, expected {expected!r}"
        )
    profiles = read_rom_symbol(rom, symbols, PROFILES_SYMBOL, len(EXPECTED_PROFILES))
    if profiles != EXPECTED_PROFILES:
        raise StartProfileContractError(
            f"{rom_path}: linked start profiles {profiles.hex()}, "
            f"expected {EXPECTED_PROFILES.hex()}"
        )
    has_request = REQUEST_SYMBOL in symbols
    if has_request != debug:
        expectation = "present" if debug else "absent"
        raise StartProfileContractError(
            f"{sym_path}: {REQUEST_SYMBOL} must be {expectation}"
        )


def verify_artifacts(
    normal_rom: Path, normal_sym: Path, debug_rom: Path, debug_sym: Path
) -> None:
    verify_variant(normal_rom, normal_sym, debug=False)
    verify_variant(debug_rom, debug_sym, debug=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--normal-rom", type=Path, required=True)
    parser.add_argument("--normal-sym", type=Path, required=True)
    parser.add_argument("--debug-rom", type=Path, required=True)
    parser.add_argument("--debug-sym", type=Path, required=True)
    args = parser.parse_args()
    try:
        verify_artifacts(
            args.normal_rom, args.normal_sym, args.debug_rom, args.debug_sym
        )
    except (OSError, StartProfileContractError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
