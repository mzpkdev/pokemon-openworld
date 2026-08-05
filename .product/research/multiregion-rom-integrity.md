# Multi-region ROM integrity: Hoenn, Kanto, and Sevii Islands

- Status: Superseded as an implementation recommendation
- Superseded by: [Approved multi-region world integrity](../rfc/multi-region-world-integrity.md) and [approved PKMN-World donor adaptation](../rfc/pkmn-world-donor-adaptation.md)
- Evidence status: retained as historical research; later RFCs own architectural decisions

> Do not implement the recommendation below. It predates the approved Johto-ready `u16` world contract and is retained only as evidence.

## Scope

This research covers the build and runtime-data integrity required to place Hoenn, Kanto, and the Sevii Islands in one standard `.gba` ROM. It deliberately excludes story integration, player-facing travel warps, badge/flag reconciliation, and region-specific progression.

The codebases inspected were:

- `pokemon-openworld` at `b67210fdf98032e48c7e6bb8e64ab1891f552fb0`
- the workspace reference `.references/pokecrossroads`
- the workspace reference `.references/PKMN-World` (the directory is case-sensitive)

The conclusion is straightforward: keep Emerald as the base game, introduce an explicit `ALL_REGIONS` build mode, make both Emerald and FRLG map assets resident, and retain the fork's existing per-layout runtime dispatch. Do not introduce a second map engine, ROM bank swapping, or a persisted “current region” abstraction for this integrity.

## Historical recommendation (superseded)

Implement an Emerald-base unified build with these properties:

1. `GAME_VERSION=EMERALD` remains the engine and ABI base.
2. `ALL_REGIONS=1` selects a new `MAP_VERSION=allregions` generator mode.
3. `mapjson` emits every Hoenn and Kanto/Sevii map, map group, event table, connection table, and layout instead of replacing non-Hoenn entries with null pointers.
4. Both Emerald and FRLG tileset headers, graphics, palettes, metatiles, attributes, and animation callbacks are linked into the ROM.
5. Each `MapLayout.isFrlg` value continues to select the correct border, tile, palette, and metatile-attribute format at runtime.
6. Existing numeric IDs remain stable and append-only.
7. `mapsec_u8_t` and the current save layout remain unchanged.

This is the smallest architecture that supports all requested landmasses without dragging story and progression systems into the same change.

## What is already present

`pokemon-openworld` already contains almost all of the source data needed for this integrity.

| Registry | Current fork | `pokecrossroads` | `PKMN-World` |
| --- | ---: | ---: | ---: |
| Hoenn map directories | 518 | 518 legacy/default entries | 519 |
| Kanto/Sevii map directories | 421 | 421 | 422 |
| Johto map directories | 0 | 0 | 92 |
| Map groups | 75 | 75 | 101 |
| Grouped map entries | 935 | 935 | 1,191 |
| Registered layouts | 785 | 785 | 1,041 |
| Map sections | 209 | 209 | 266 |

The current fork and `pokecrossroads` have identical map-directory sets and layout-directory sets. Their `data/maps/map_groups.json`, `src/regions.c`, and `include/regions.h` are also identical. In other words, the import is already in the tree; the default build is filtering most of it out. The four ungrouped directories are explicitly unused houses: `Route19_UnusedHouse_Frlg`, `Route23_UnusedHouse`, `Route6_UnusedHouse_Frlg`, and `SevenIsland_UnusedHouse`.

The current maximum group count and maps-per-group fit the existing byte-sized map identifiers. The 209 map sections occupy indices 0–208, so they also fit `mapsec_u8_t` while leaving the special met-location values at `0xFD`–`0xFF` untouched.

The runtime already understands both layout formats:

- `struct MapLayout` carries `isFrlg`, `borderWidth`, and `borderHeight`.
- `src/fieldmap.c` branches on `isFrlg` for border behavior, tile/palette counts, and FRLG 32-bit versus Emerald 16-bit metatile attributes.
- Other mixed-format consumers, including field doors, escalators, and shops, already use the same runtime distinction.
- `mapjson` already emits `isFrlg` from each layout's `layout_version`.
- `src/region_map.c` already contains Kanto and the Sevii 1–3, 4–5, and 6–7 region maps.
- `src/regions.c` already classifies Sevii subregions under Kanto.

That existing runtime dispatch is the right seam. The unified build only needs to make all referenced data resident and all table entries valid.

## Why the current ROM cannot load Kanto safely

The default Makefile uses `MAP_VERSION ?= emerald`. In `tools/mapjson/mapjson.cpp`, Emerald mode rejects every map whose `region` is not `REGION_HOENN` and every layout whose `layout_version` is not `emerald`.

The generated baseline demonstrates the mismatch:

- Only 518 map-header includes are emitted from 939 map directories.
- Kanto/Sevii map constants still exist in `include/constants/map_groups.h`.
- Their corresponding generated group-table entries are null.

This creates a false sense that Kanto is imported. A later warp can compile because `MAP_PALLET_TOWN` exists, then dereference a null `gMapGroups[group]` entry during map load and flatline.

Tilesets have the same problem. `src/data/tilesets/headers.h` and `metatiles.h` select one asset family with `#if !IS_FRLG ... #else ...`. FRLG graphics in `graphics.h` are likewise guarded. An Emerald build therefore cannot satisfy the FRLG layouts even if map generation is forced to include them.

`pokecrossroads` solves this by removing the guards and compiling both sets unconditionally. That proves the shape works, but an explicit `ALL_REGIONS` gate is cleaner: it preserves ordinary Emerald/FRLG modes for upstream comparison, debug isolation, and smaller builds.

## Lessons from `PKMN-World`

`PKMN-World` has the most deliberate implementation:

- `ALL_REGIONS ?= 1` is passed to C and assembly.
- Unified builds select `MAP_VERSION := allregions`.
- `mapjson` accepts `allregions`, keeps Emerald defaults for legacy map JSON, and suppresses region/layout filtering.
- FRLG assets and scripts are included when `IS_FRLG || ALL_REGIONS`.

That build architecture should be copied conceptually.

Its map-section widening should not be copied. `PKMN-World` includes Johto and reaches 266 map sections, so it widens `mapsec_u8_t`, changes the serialized `MapHeader` field to two bytes, and adds alignment around 29-byte map headers and group tables. The alignment is essential there—unaligned pointer loads can crash—but the entire change is unnecessary for this fork's 209 sections. Widening now would expand the save/header ABI blast radius for no benefit.

`PKMN-World` also contains region switching, flags, save changes, party handling, story glue, and test warps. Those solve a later product problem. They are not prerequisites for keeping three regions resident in one ROM.

## Proposed implementation slices

### 1. Add a first-class unified build mode

Add `ALL_REGIONS ?= 1` or an explicit unified build target. When enabled:

- retain `GAME_VERSION=EMERALD` and `IS_FRLG=0`;
- set `MAP_VERSION=allregions`;
- pass `-DALL_REGIONS=1` to C and `--defsym ALL_REGIONS=1` to assembly;
- keep ordinary `emerald` and `firered` generator modes available.

Using `IS_FRLG` as the unified switch is wrong because it selects engine-wide compile-time behavior. `ALL_REGIONS` means data residency; `MapLayout.isFrlg` means per-map data interpretation.

### 2. Make generation complete and deterministic

Teach `tools/mapjson` that `allregions` uses Emerald as the default for legacy entries but filters neither region nor layout version. Generate:

- every valid map header and layout;
- every map event and connection table;
- all 75 group tables with real pointers for their registered members;
- all 785 layout pointer slots.

Add generator/build assertions so a defined map constant cannot silently point through a null group. Also assert:

- group count and maps-per-group remain within byte-sized limits;
- map-section count remains below the reserved met-location range;
- every referenced layout, tileset, callback, script, and event symbol resolves.

### 3. Link both tileset families

Change the tileset data guards so the unified build includes both families:

- Emerald primary and secondary tileset headers;
- FRLG/Kanto/Sevii primary and secondary tileset headers;
- both graphics/palette sets;
- both metatile and attribute formats;
- FRLG tileset animation callbacks used by imported layouts.

Do not normalize FRLG data into Emerald format. The fork already has correct runtime format selection, and converting hundreds of layouts adds risk without reducing engine complexity.

### 4. Preserve IDs and keep progression out

Treat map group numbers, map numbers, layout IDs, and map-section IDs as persistent interfaces. Do not reorder them during cleanup. Scripts, saves, wild encounters, fly data, and external test tooling refer to those numbers.

The current region calculation from `regionMapSectionId` is sufficient for loading and region-map rendering. Do not add a saved active-region field until travel rules actually require one.

Existing FRLG event scripts can remain linked so imported map event pointers resolve, but no production warp needs to expose them. If later work strips story scripts, replace referenced entry points with explicit inert stubs; never leave dangling or null pointers.

## Validation contract

A successful link is necessary, not sufficient. The acceptance checks should be automated.

### Static and build checks

1. Clean-generate all map outputs.
2. Assert all 935 grouped maps are emitted and the four known unused-house directories remain the only intentional exclusions.
3. Assert 75 valid group table slots and 785 valid layout slots.
4. Assert representative symbols exist for Hoenn, mainland Kanto, and every Sevii tileset family.
5. Build normal, debug, and Virtual Console ROM variants.
6. Fail if the linked ROM exceeds 32 MiB; keep a visible safety margin for later story and connection work.

### Headless runtime checks

Use a test-only direct map-load hook, not a player-facing warp. For each case, load the map, settle several frames, and assert that the map group/number, layout pointer, both tileset pointers, and callbacks are valid and that the emulator remains alive:

- a Hoenn control such as Littleroot Town;
- Pallet Town for mainland Kanto;
- One Island for Sevii 1–3;
- Four or Five Island for Sevii 4–5;
- Six or Seven Island for Sevii 6–7;
- at least one interior and one cave using FRLG assets.

Then run title-screen/new-game smoke tests and a Hoenn save/continue regression. Connections, travel flow, and story state can remain out of scope.

`PKMN-World` contains Lua tests that directly load Kanto/Sevii maps, including One Island. They are useful templates, but this research did not execute that suite.

## Capacity evidence

The current baseline built successfully as a standard 32 MiB ROM:

- ROM used: 26,514,756 bytes (79.02%)
- ROM remaining: 7,039,676 bytes
- EWRAM: 226,584 bytes (86.43%)
- IWRAM: 28,376 bytes (86.60%)

A disposable copy of `PKMN-World` also built successfully with its unified all-regions mode, including Hoenn, Kanto/Sevii, and Johto:

- ROM used: 19,858,124 bytes (59.18%)
- EWRAM: 227,948 bytes (86.96%)
- IWRAM: 27,996 bytes (85.44%)

This proves the architecture can fit a conventional GBA ROM. It does not prove that this fork's merge will fit, because the forks have different feature and asset baselines. The current fork has roughly 6.7 MiB of headroom, so the real unified build must be measured immediately after enabling both asset families. If it overruns, first remove duplicate or unreachable graphics, audio, and story assets. Do not reach for a nonstandard 64 MiB ROM or a bank-switching scheme unless actual linked-size evidence forces it.

For scale, current versus `PKMN-World` all-regions object sizes were:

| Object | Current baseline | `PKMN-World` all-regions |
| --- | ---: | ---: |
| `maps.o` | 687,564 | 1,794,676 |
| `map_events.o` | 101,956 | 253,396 |
| `tilesets.o` | 713,644 | 1,883,584 |
| `event_scripts.o` | 987,293 | 1,679,869 |

These numbers are directional, not additive: `PKMN-World` also contains Johto and differs elsewhere.

## Principal risks

- **Null registry entries:** constants compile while generated map/layout pointers are null; the crash happens only on load.
- **Partial asset residency:** map tables are complete but an FRLG tileset, palette, callback, or event symbol is absent.
- **Compile-time/runtime confusion:** using `IS_FRLG` to represent a mixed ROM selects the wrong engine behavior globally.
- **ID churn:** reordering imported registries silently breaks scripts, saves, wild encounters, and test tooling.
- **Unnecessary ABI changes:** widening map sections before the count demands it creates alignment and save compatibility work.
- **ROM pressure:** the current fork is already at 79% of 32 MiB; every unified build must publish linked-size evidence.
- **False boot confidence:** reaching the title screen only validates the Emerald path. Representative direct loads are mandatory.

## Decision

Build one Emerald-based ROM with all map and tileset data resident, selected by an explicit `ALL_REGIONS` mode, while using the existing `MapLayout.isFrlg` runtime dispatch for individual maps. Keep identifiers and the save ABI stable. Treat test-only direct loads as the access mechanism until story and travel work begins.
