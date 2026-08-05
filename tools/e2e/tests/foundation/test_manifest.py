import json
from pathlib import Path

import pytest

from tools.e2e.tests.foundation.manifest import (
    foundation_manifest_path,
    load_manifest_maps,
    load_representatives,
)


def write_manifest(tmp_path, document):
    path = tmp_path / "foundation-manifest.json"
    path.write_text(json.dumps(document))
    return path


def test_manifest_map_contract(tmp_path):
    path = write_manifest(
        tmp_path,
        {
            "schemaVersion": 1,
            "maps": [
                {
                    "name": "LittlerootTown",
                    "id": "MAP_LITTLEROOT_TOWN",
                    "group": 0,
                    "number": 9,
                    "region": "REGION_HOENN",
                    "layoutId": "LAYOUT_LITTLEROOT_TOWN",
                    "mapScripts": "LittlerootTown_MapScripts",
                }
            ],
        },
    )

    [entry] = load_manifest_maps(path)

    assert entry.name == "LittlerootTown"
    assert entry.map_id == (0, 9)
    assert entry.region == "REGION_HOENN"


def test_manifest_path_honors_environment_override(monkeypatch, tmp_path):
    expected = tmp_path / "custom-manifest.json"
    monkeypatch.setenv("FOUNDATION_MANIFEST", str(expected))

    assert foundation_manifest_path() == expected


def test_manifest_map_contract_accepts_schema_2(tmp_path):
    path = write_manifest(
        tmp_path,
        {
            "schemaVersion": 2,
            "maps": [
                {
                    "name": "PalletTown_Frlg",
                    "group": 37,
                    "number": 0,
                    "region": "REGION_KANTO",
                    "mapLayout": "PalletTown_Layout",
                }
            ],
        },
    )

    [entry] = load_manifest_maps(path)

    assert entry.map_id == (37, 0)


def test_manifest_accepts_common_group_and_number_aliases(tmp_path):
    path = write_manifest(
        tmp_path,
        {
            "schemaVersion": 1,
            "maps": [
                {
                    "name": "PalletTown_Frlg",
                    "mapGroup": 37,
                    "mapNum": 0,
                    "region": "REGION_KANTO",
                }
            ],
        },
    )

    [entry] = load_manifest_maps(path)

    assert entry.map_id == (37, 0)


@pytest.mark.parametrize("field", ["name", "group", "number", "region"])
def test_manifest_rejects_missing_required_map_field(tmp_path, field):
    entry = {
        "name": "LittlerootTown",
        "group": 0,
        "number": 9,
        "region": "REGION_HOENN",
    }
    del entry[field]
    path = write_manifest(tmp_path, {"schemaVersion": 1, "maps": [entry]})

    with pytest.raises(ValueError, match=rf"missing required field '{field}'"):
        load_manifest_maps(path)


def test_manifest_rejects_duplicate_map_ids(tmp_path):
    path = write_manifest(
        tmp_path,
        {
            "schemaVersion": 1,
            "maps": [
                {"name": "First", "group": 1, "number": 2, "region": "REGION_HOENN"},
                {"name": "Second", "group": 1, "number": 2, "region": "REGION_KANTO"},
            ],
        },
    )

    with pytest.raises(ValueError, match=r"repeats map id \(1, 2\)"):
        load_manifest_maps(path)


def test_representatives_include_four_island_completed_scene_seed():
    path = Path(__file__).with_name("maps.json")

    representatives = load_representatives(path)
    four_island = next(
        entry for entry in representatives if entry.name == "FourIsland_Frlg"
    )

    assert four_island.seed_vars == ((0x4086, 1),)
