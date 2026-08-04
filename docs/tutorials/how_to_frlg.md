# How to use FireRed/LeafGreen

FireRed and LeafGreen engine data remains in the repository for compatibility and
future upstream integrations, but Pokémon OpenWorld's Makefile builds Emerald
only. `firered` and `leafgreen` are intentionally not build targets.

## Porymap adjustments
For Porymap to work with FRLG maps you need to adjust a few settings (`Options > Project Settings`):
-  in the `General` tab change the base game version to `pokefirered`

![porymap_general](./img/frlg/porymap_general.png)

- in the `Identifiers` tab change the following attributes:
  - define_tiles_primary: `NUM_TILES_IN_PRIMARY_FRLG`
  - define_metatiles_primary: `NUM_METATILES_IN_PRIMARY_FRLG`
  - define_pals_primary: `NUM_PALS_IN_PRIMARY_FRLG`
  - define_mask_behavior: `METATILE_ATTR_BEHAVIOR_MASK_FRLG`
  - define_mask_layer: `METATILE_ATTR_LAYER_MASK_FRLG`

![porymap_identifier](./img/frlg/porymap_identifier.png)

## How to add maps
For maps to be included in the build process they need to have a custom attribute `region` with the value `REGION_KANTO` or `REGION_HOENN` for their respective games. 

If you create a new map, the `region` will not be there, and must be added manually in the `map.json` or through Porymap.

**Examples:**

map.json:
```
{
  "id": "MAP_PALLET_TOWN",
  "name": "PalletTown_Frlg",
  "layout": "LAYOUT_PALLET_TOWN",
  "music": "MUS_RG_PALLET",
  "region": "REGION_KANTO",
  ...
```
Porymap:

![porymap_region_attribute](./img/frlg/porymap_region_attribute.png)

If a map does not have the `region` attribute, the compiler will default to what game you compile, and the map you created gets included in that game.

Additionally, maps must have a `layout_version` that you manually include in `layouts.json`.
```
    {
      "id": "LAYOUT_ONE_ISLAND_KINDLE_ROAD_EMBER_SPA",
      "name": "OneIsland_KindleRoad_EmberSpa_Layout",
      "width": 27,
      "height": 39,
      "primary_tileset": "gTileset_General_Frlg",
      "secondary_tileset": "gTileset_MtEmber",
      "border_filepath": "data/layouts/OneIsland_KindleRoad_EmberSpa_Frlg/border.bin",
      "blockdata_filepath": "data/layouts/OneIsland_KindleRoad_EmberSpa_Frlg/map.bin",
      "border_height": 2,
      "border_width": 2,
      "layout_version": "frlg"
    },
```

Similarly to the `region` attribute, if a map in `layouts.json` does not have a `layout_version`, it will default to the game being compiled.

Lastly, you cannot properly access map inside a vanilla map group from a different game. If you create a new map in a Fire Red map group (such as `gMapGroup_TownsAndRoutes_Frlg`), you cannot warp or connect to it from an Emerald map in game, and vice versa. It is recommended to either put them in existing, fitting map groups, or create a new map group. 

## Migrating FRLG tilesets
To migrate tilesets that have been previously created for pokefirered you can use [this script](/migration_scripts/frlg_metatile_behavior_converter.py).<br>
Instructions are in the script.
