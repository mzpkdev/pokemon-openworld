from pathlib import Path

import pytest

from tools.start_profiles.verify_artifacts import (
    EXPECTED_PROFILES,
    ROM_BASE,
    StartProfileContractError,
    verify_artifacts,
)


def _variant(root: Path, name: str, *, debug: bool) -> tuple[Path, Path]:
    rom = bytearray(64)
    rom[8:16] = bytes(
        (1, 0, 0, int(debug), 3, 8 if debug else 0, 7 if debug else 0, 0)
    )
    rom[24 : 24 + len(EXPECTED_PROFILES)] = EXPECTED_PROFILES
    rom_path = root / f"{name}.gba"
    sym_path = root / f"{name}.sym"
    rom_path.write_bytes(rom)
    lines = [
        f"{ROM_BASE + 8:08x} g .rodata 00000008 gNewGameStartProductionContract",
        f"{ROM_BASE + 24:08x} g .rodata 0000000c gNewGameStartProfiles",
    ]
    if debug:
        lines.append("02001000 g .bss 00000008 gDebugNewGameStartProfileRequest")
    sym_path.write_text("\n".join(lines) + "\n")
    return rom_path, sym_path


def test_normal_and_debug_linked_contracts(tmp_path: Path) -> None:
    normal = _variant(tmp_path, "normal", debug=False)
    debug = _variant(tmp_path, "debug", debug=True)
    verify_artifacts(*normal, *debug)


def test_hoenn_default_mutation_is_rejected(tmp_path: Path) -> None:
    normal = _variant(tmp_path, "normal", debug=False)
    debug = _variant(tmp_path, "debug", debug=True)
    mutated = bytearray(normal[0].read_bytes())
    mutated[10] = 1
    normal[0].write_bytes(mutated)
    with pytest.raises(StartProfileContractError, match="expected"):
        verify_artifacts(*normal, *debug)


def test_hoenn_truck_retains_gender_owned_checkpoint_policy() -> None:
    scripts = Path("data/maps/InsideOfTruck/scripts.inc").read_text()
    male = scripts.index("InsideOfTruck_EventScript_SetIntroFlagsMale::")
    female = scripts.index("InsideOfTruck_EventScript_SetIntroFlagsFemale::")
    assert "setrespawn HEAL_LOCATION_LITTLEROOT_TOWN_BRENDANS_HOUSE_2F" in scripts[
        male:female
    ]
    assert "setrespawn HEAL_LOCATION_LITTLEROOT_TOWN_MAYS_HOUSE_2F" in scripts[
        female:
    ]
