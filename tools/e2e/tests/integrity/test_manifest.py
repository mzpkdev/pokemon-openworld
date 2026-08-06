import json
from pathlib import Path

import pytest

from tools.e2e.tests.integrity.manifest import (
    _representative_kind,
    integrity_manifest_path,
    load_manifest_maps,
    load_representatives,
)


def map_entry(**updates):
    entry = {
        "name": "LittlerootTown",
        "id": "MAP_LITTLEROOT_TOWN",
        "group": 0,
        "number": 9,
        "region": "REGION_HOENN",
        "layoutId": "LAYOUT_LITTLEROOT_TOWN",
        "mapLayout": "LittlerootTown_Layout",
        "mapEvents": "LittlerootTown_MapEvents",
        "mapScripts": "LittlerootTown_MapScripts",
        "mapConnections": None,
        "regionMapSection": "MAPSEC_LITTLEROOT_TOWN",
        "regionMapSectionValue": 0,
        "battleType": 0,
    }
    entry.update(updates)
    return entry


def layout_entry(**updates):
    entry = {
        "id": "LAYOUT_LITTLEROOT_TOWN",
        "number": 10,
        "name": "LittlerootTown_Layout",
        "width": 20,
        "height": 20,
        "primaryTileset": "gTileset_General",
        "secondaryTileset": "gTileset_Petalburg",
        "format": "emerald",
    }
    entry.update(updates)
    return entry


def section_entry(**updates):
    entry = {
        "id": "MAPSEC_LITTLEROOT_TOWN",
        "value": 0,
        "region": "REGION_HOENN",
        "regionValue": 3,
        "kind": "geographic",
        "kindValue": 0,
        "regionMapType": "REGION_MAP_HOENN",
        "regionMapTypeValue": 0,
    }
    entry.update(updates)
    return entry


def codec_entries(**updates):
    codecs = {
        "sectionToSavedLocation": [0],
        "sectionToMetLocation": [0],
        "savedLocationToSection": [0],
        "metLocationToSection": [0],
    }
    codecs.update(updates)
    return codecs


def write_manifest(
    tmp_path,
    maps,
    *,
    layouts=None,
    metadata=None,
    codecs=None,
    schema_version=1,
):
    path = tmp_path / "integrity-manifest.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": schema_version,
                "maps": maps,
                "layouts": layouts if layouts is not None else [layout_entry()],
                "mapSectionMetadata": (
                    metadata if metadata is not None else [section_entry()]
                ),
                "codecs": codecs if codecs is not None else codec_entries(),
            }
        )
    )
    return path


def write_representatives(tmp_path, representatives):
    path = tmp_path / "maps.json"
    path.write_text(
        json.dumps({"schemaVersion": 1, "representatives": representatives})
    )
    return path


def test_manifest_map_contract_is_exact(tmp_path):
    [entry] = load_manifest_maps(write_manifest(tmp_path, [map_entry()]))

    assert entry.name == "LittlerootTown"
    assert entry.map_id == (0, 9)
    assert entry.region == "REGION_HOENN"
    assert entry.layout_id == "LAYOUT_LITTLEROOT_TOWN"
    assert entry.layout_number == 10
    assert entry.layout == "LittlerootTown_Layout"
    assert entry.events == "LittlerootTown_MapEvents"
    assert entry.scripts == "LittlerootTown_MapScripts"
    assert entry.connections is None
    assert entry.region_map_section_value == 0
    assert entry.battle_type == 0
    assert (entry.width, entry.height) == (20, 20)
    assert entry.primary_tileset == "gTileset_General"
    assert entry.secondary_tileset == "gTileset_Petalburg"
    assert entry.layout_format == "emerald"
    assert entry.section.id == "MAPSEC_LITTLEROOT_TOWN"
    assert entry.section.value == 0
    assert entry.section.region == "REGION_HOENN"
    assert entry.section.region_value == 3
    assert entry.section.kind == "geographic"
    assert entry.section.kind_value == 0
    assert entry.section.region_map_type == "REGION_MAP_HOENN"
    assert entry.section.region_map_type_value == 0
    assert entry.section.saved_location_code == 0
    assert entry.section.met_location_code == 0
    assert entry.section.saved_location_reverse_target == 0
    assert entry.section.met_location_reverse_target == 0


def test_manifest_path_honors_environment_override(monkeypatch, tmp_path):
    expected = tmp_path / "custom-manifest.json"
    monkeypatch.setenv("INTEGRITY_MANIFEST", str(expected))

    assert integrity_manifest_path() == expected


def test_manifest_map_contract_accepts_schema_2(tmp_path):
    path = write_manifest(tmp_path, [map_entry()], schema_version=2)
    [entry] = load_manifest_maps(path)
    assert entry.map_id == (0, 9)


def test_manifest_accepts_common_group_and_number_aliases(tmp_path):
    entry = map_entry(mapGroup=37, mapNum=0)
    del entry["group"]
    del entry["number"]
    [loaded] = load_manifest_maps(write_manifest(tmp_path, [entry]))
    assert loaded.map_id == (37, 0)


@pytest.mark.parametrize(
    "field",
    [
        "name",
        "group",
        "number",
        "region",
        "layoutId",
        "mapLayout",
        "mapEvents",
        "mapScripts",
        "mapConnections",
        "regionMapSection",
        "regionMapSectionValue",
        "battleType",
    ],
)
def test_manifest_rejects_missing_required_map_field(tmp_path, field):
    entry = map_entry()
    del entry[field]
    path = write_manifest(tmp_path, [entry])

    with pytest.raises(ValueError, match=rf"missing required field '{field}'"):
        load_manifest_maps(path)


def test_manifest_rejects_unknown_layout(tmp_path):
    path = write_manifest(tmp_path, [map_entry(layoutId="LAYOUT_MISSING")])
    with pytest.raises(ValueError, match="references unknown layout"):
        load_manifest_maps(path)


def test_manifest_rejects_layout_name_mismatch(tmp_path):
    path = write_manifest(tmp_path, [map_entry(mapLayout="Wrong_Layout")])
    with pytest.raises(ValueError, match="layout name does not match"):
        load_manifest_maps(path)


def test_manifest_rejects_map_section_id_mismatch(tmp_path):
    path = write_manifest(tmp_path, [map_entry(regionMapSection="MAPSEC_WRONG")])
    with pytest.raises(ValueError, match="map-section id does not match value"):
        load_manifest_maps(path)


def test_manifest_accepts_matching_johto_region_with_hoenn_presentation(tmp_path):
    path = write_manifest(
        tmp_path,
        [map_entry(region="REGION_JOHTO")],
        metadata=[section_entry(region="REGION_JOHTO")],
    )
    [entry] = load_manifest_maps(path)
    assert entry.region == "REGION_JOHTO"
    assert entry.section.region == "REGION_JOHTO"
    assert entry.section.region_map_type == "REGION_MAP_HOENN"


def test_manifest_keeps_non_johto_section_region_distinct_from_content_origin(
    tmp_path,
):
    path = write_manifest(
        tmp_path, [map_entry()], metadata=[section_entry(region="REGION_KANTO")]
    )
    [entry] = load_manifest_maps(path)
    assert entry.region == "REGION_HOENN"
    assert entry.section.region == "REGION_KANTO"


@pytest.mark.parametrize(
    ("map_region", "section_region"),
    [
        ("REGION_JOHTO", "REGION_HOENN"),
        ("REGION_HOENN", "REGION_JOHTO"),
    ],
)
def test_manifest_rejects_one_sided_johto_ownership(
    tmp_path, map_region, section_region
):
    path = write_manifest(
        tmp_path,
        [map_entry(region=map_region)],
        metadata=[section_entry(region=section_region)],
    )
    with pytest.raises(ValueError, match="one-sided Johto ownership"):
        load_manifest_maps(path)


def test_manifest_rejects_unordered_map_section_metadata(tmp_path):
    path = write_manifest(tmp_path, [map_entry()], metadata=[section_entry(value=1)])
    with pytest.raises(ValueError, match="must be ordered by value"):
        load_manifest_maps(path)


def test_manifest_rejects_codec_without_selected_section(tmp_path):
    path = write_manifest(
        tmp_path,
        [map_entry()],
        codecs=codec_entries(sectionToSavedLocation=[]),
    )
    with pytest.raises(ValueError, match="do not cover map section 0"):
        load_manifest_maps(path)


def test_manifest_rejects_duplicate_map_ids(tmp_path):
    second = map_entry(name="Second")
    path = write_manifest(tmp_path, [map_entry(), second])
    with pytest.raises(ValueError, match=r"repeats map id \(0, 9\)"):
        load_manifest_maps(path)


def test_representatives_include_four_island_completed_scene_seed():
    path = Path(__file__).with_name("maps.json")
    representatives = load_representatives(path)
    four_island = next(
        entry for entry in representatives if entry.name == "FourIsland_Frlg"
    )
    assert four_island.region == "sevii45"
    assert four_island.kind == "exterior"
    assert four_island.seed_vars == ((0x4086, 1),)
    new_bark = next(entry for entry in representatives if entry.name == "NewBarkTown")
    assert new_bark.region == "johto"
    assert new_bark.kind == "exterior"
    assert new_bark.seed_vars == ()


@pytest.mark.parametrize("declared_region", ["kanto", "sevii123", "sevii45", "sevii67"])
def test_representative_rejects_hoenn_map_mislabeled_as_other_geography(
    tmp_path, declared_region
):
    maps = load_manifest_maps(write_manifest(tmp_path, [map_entry()]))
    representatives = write_representatives(
        tmp_path,
        [
            {
                "name": "LittlerootTown",
                "region": declared_region,
                "kind": "exterior",
            }
        ],
    )

    with pytest.raises(
        ValueError,
        match=rf"declares region '{declared_region}'.*manifest geography is 'hoenn'",
    ):
        load_representatives(representatives, maps)


def test_representative_rejects_kind_not_supported_by_manifest_layout(tmp_path):
    maps = load_manifest_maps(write_manifest(tmp_path, [map_entry()]))
    representatives = write_representatives(
        tmp_path,
        [
            {
                "name": "LittlerootTown",
                "region": "hoenn",
                "kind": "interior",
            }
        ],
    )

    with pytest.raises(
        ValueError,
        match="declares kind 'interior'.*manifest layout is 'exterior'",
    ):
        load_representatives(representatives, maps)


@pytest.mark.parametrize(
    ("name", "primary_tileset", "secondary_tileset", "expected_kind"),
    [
        (
            "VioletCity",
            "gTileset_Johto_General",
            "gTileset_VioletCity",
            "exterior",
        ),
        (
            "SproutTower_1F",
            "gTileset_Johto_Building",
            "gTileset_PowerPlant_GeneratorRoom",
            "interior",
        ),
        (
            "RuinsOfAlph_B1F",
            "gTileset_Johto_Building",
            "gTileset_RuinsOfAlph_B1F",
            "cave",
        ),
    ],
)
def test_phase2_johto_representative_kind_is_derived_from_known_tilesets(
    tmp_path, name, primary_tileset, secondary_tileset, expected_kind
):
    maps = load_manifest_maps(
        write_manifest(
            tmp_path,
            [map_entry(name=name, region="REGION_JOHTO")],
            layouts=[
                layout_entry(
                    primaryTileset=primary_tileset,
                    secondaryTileset=secondary_tileset,
                    format="johto",
                )
            ],
            metadata=[section_entry(region="REGION_JOHTO")],
        )
    )

    assert _representative_kind(maps[0]) == expected_kind


def test_johto_representative_uses_content_region_during_hoenn_presentation(
    tmp_path,
):
    maps = load_manifest_maps(
        write_manifest(
            tmp_path,
            [map_entry(name="NewBarkTown", region="REGION_JOHTO")],
            layouts=[
                layout_entry(
                    primaryTileset="gTileset_Johto_General",
                    secondaryTileset="gTileset_NewBarkTown",
                    format="johto",
                )
            ],
            metadata=[section_entry(region="REGION_JOHTO")],
        )
    )
    representatives = write_representatives(
        tmp_path,
        [{"name": "NewBarkTown", "region": "hoenn", "kind": "exterior"}],
    )

    with pytest.raises(
        ValueError,
        match="declares region 'hoenn'.*manifest geography is 'johto'",
    ):
        load_representatives(representatives, maps)
