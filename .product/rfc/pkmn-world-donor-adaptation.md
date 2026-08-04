# RFC: PKMN-World donor adaptation

- Status: Approved
- Implements: [Multi-region world foundation](./multi-region-world-foundation.md)
- Donor: `.references/PKMN-World`
- Scope: Build and load foundations for Hoenn, Kanto, Sevii Islands, and later Johto

## Summary

Use PKMN-World as an implementation donor, not as an architectural authority. Port the behavior that has already proved a unified Emerald-based ROM can generate, link, and load maps from multiple regional data sets. Put that behavior behind the types, binary contracts, generated metadata, and validation rules approved in the foundation RFC.

The donor supplies four especially valuable lessons:

1. an `ALL_REGIONS` generator mode that includes maps and layouts without changing the Emerald engine identity;
2. resident Emerald and FRLG tileset families;
3. a widened map-section field with four-byte alignment restored at every generated header and pointer table;
4. runtime handling for Emerald, FRLG, and Johto layout conventions, including tileset-local metatile attribute widths.

The donor implementation is not copied wholesale. Its global generator state, misleading widened `mapsec_u8_t` name, boolean layout-mode combinations, range-derived region logic, always-on Johto assets, and generic met-location fallback are replaced. The resulting code should read as native `pokemon-openworld` architecture, with PKMN-World retained as evidence and a source of narrowly reviewed code fragments.

## Decision

Implement the approved multi-region foundation through donor-guided adaptation:

- reproduce PKMN-World's `ALL_REGIONS` build and generator behavior;
- reproduce its header-width and alignment corrections;
- reuse its asset-residency and map-format findings;
- introduce explicit build-mode and layout-format models instead of donor booleans;
- introduce clean `RegionId`, `MapSectionId`, `SavedLocationCode`, and `MetLocationCode` types;
- generate region and provenance metadata from reviewed source data;
- preserve fixed save and record-mixing layouts through explicit compact-location codecs;
- preserve the single Emerald-engine `pokemon-openworld` product identity and the existing Pokémon binary layout;
- port changes in small, independently buildable slices rather than cherry-picking donor commits.

This RFC is the implementation contract. When donor behavior conflicts with it, this RFC wins.

## Donor boundary

### Reuse by behavior

The following donor behavior is in scope:

- Makefile propagation of `ALL_REGIONS` into C and assembly;
- selection of an `allregions` map-generation mode while `GAME_VERSION` remains Emerald and `IS_FRLG` remains false;
- inclusion of all registered regional maps and layouts;
- four-byte alignment of generated `MapHeader` records, map-group tables, and the top-level map-group pointer table;
- two-byte emission of map-section identity;
- linkage of Emerald and FRLG tileset headers, graphics, palettes, metatiles, attributes, animations, and referenced callbacks;
- runtime interpretation of the three layout conventions demonstrated by the donor;
- direct-load and structural validation patterns useful for proving maps can initialize.

Code may be translated or locally copied only after reviewing the entire containing function and its data contract. Every copied fragment must use local names and local types and must not carry unrelated PKMN-World story or state machinery with it.

### Do not import

The following donor systems are outside this RFC:

- story, progression, badges, and regional quest flags;
- production travel warps, Fly integration, and active-region switching;
- party replacement or region-specific party storage;
- donor save-block additions unrelated to map loading;
- donor test doors or player-facing shortcuts;
- Johto content itself;
- link, trade, or original-generation compatibility code.

Do not cherry-pick broad donor commits. They mix infrastructure with product behavior and make it difficult to prove which ABI and save changes are required. Port one contract at a time.

## Build-mode contract

There is one ROM product and one legal product tuple:

```make
override GAME_VERSION := EMERALD
override IS_FRLG := 0
override ALL_REGIONS := 1
override MAP_VERSION := allregions
override FILE_NAME := pokemon-openworld
```

Normal, debug, release, test, and headless targets vary instrumentation or optimization only. They must not change the engine, resident world, map registry, or output basename. Make must reject attempts to select FireRed, LeafGreen, a retail map filter, `ALL_REGIONS=0`, or another product name. FireRed and LeafGreen engine/configuration source may remain for upstream compatibility, but no Makefile target, CI matrix entry, or published artifact may build those ROMs.

`ALL_REGIONS` must be passed to the C preprocessor and assembler. It is a content-selection capability, not a fourth retail game version. Code that implements battle, save, script, or field behavior must continue to see Emerald unless this RFC explicitly introduces a narrower format property.

The generator must not reproduce PKMN-World's mutable global `allRegions` flag followed by rewriting `version` to `emerald`. Represent the choice explicitly:

```cpp
enum class MapBuildMode {
    Emerald,
    FireRed,
    Ruby,
    AllRegions,
};

struct MapBuildPolicy {
    MapBuildMode mode;
    DataDialect defaultDialect;
    RegionFilter regionFilter;
    LayoutFilter layoutFilter;
};
```

`AllRegions` is the only product-generation mode. It uses Emerald as the default dialect for data that omits an explicit region or layout format, but its region and layout filters include every registered entry. `Emerald`, `FireRed`, and `Ruby` remain tool-only dialect fixtures; they may generate isolated comparison data but cannot select a ROM build. Helpers should answer questions such as `IncludesRegion`, `IncludesLayout`, and `DefaultRegion`; callers must not infer these policies by comparing strings.

Generation order remains deterministic. Existing IDs must not change merely because the build mode changes. New maps, layouts, regions, and sections append explicit identifiers.

The final ROM output is singular, but generator fixtures remain isolated. Product objects carry an `allregions` policy stamp and must never reuse objects produced before the unified policy. Generated maps, layouts, constants, manifests, and other filter-dependent files are written under a mode-specific generated root rather than back into shared reviewed source paths. Generation occurs in a temporary sibling tree and is promoted only after success. Switching diagnostic fixtures between `emerald`, `firered`, and `allregions` must never reuse generated output whose mode stamp differs.

`map_data_rules.mk` must key every per-map and aggregate output on the selected mode. The current pattern hard-codes per-map header generation to Emerald and allows aggregate generation to rewrite reviewed `heal_locations.json`; both behaviors must be removed. Reviewed JSON is input-only. A generation test runs modes in alternating order and proves byte-for-byte deterministic output for each mode.

## Generator adaptation

`tools/mapjson/mapjson.cpp` is the main donor seam. Adapt it in these stages:

1. Parse `allregions` into `MapBuildMode::AllRegions`.
2. Default missing region annotations to Hoenn only because the policy's data dialect is Emerald.
3. Disable retail region and layout filtering for the unified policy.
4. Emit all registered map headers, events, scripts, connections, group entries, and layouts.
5. Emit explicit layout-format metadata for every layout.
6. Emit the fixed map-header schema defined below.
7. Align each record and pointer table explicitly.
8. Generate region, saved-location, and Pokémon-provenance registries from reviewed inputs.
9. Fail on unresolved references, duplicate IDs, incomplete metadata, or unstable ordering.

PKMN-World is evidence for inclusive generation and alignment, not for fail-closed validation. Its generator still skips some layouts when border inputs are absent. Silent skipping must not be copied; the validation below is new local architecture.

The generator must reject, rather than emit, any of these states:

- a map constant with no group entry;
- a group slot required by a constant with a null pointer;
- a map header with an absent layout, event, script, or connection symbol when one is declared;
- a layout with no recognized format;
- a tileset whose declared header, graphics, metatile, attribute, palette, animation, or callback reference is absent from its reviewed registry;
- a geographic map section with no region metadata;
- any map section with no section kind;
- a map section with no explicit provenance decision;
- a section ID greater than the storage range of `MapSectionId`;
- a map group or map number outside the signed `s8` `WarpData` range, currently `0` through `127`.

The current acceptance baseline is 935 grouped maps, 75 group slots, and 785 layout slots, with the four known unused-house directories excluded. These numbers are regression sentinels, not permanent limits. Johto import must update the expected registry deliberately.

## Serialized `MapHeader` contract

Widening `regionMapSectionId` changes the assembly record. Implicit compiler or assembler padding is forbidden. The canonical record is exactly 32 bytes and four-byte aligned:

| Offset | Field | Encoding |
| ---: | --- | --- |
| `0x00` | `mapLayout` | pointer, 4 bytes |
| `0x04` | `events` | pointer, 4 bytes |
| `0x08` | `scripts` | pointer, 4 bytes |
| `0x0C` | `connections` | pointer, 4 bytes |
| `0x10` | `music` | `u16` |
| `0x12` | `mapLayoutId` | `u16` |
| `0x14` | `regionMapSectionId` | `MapSectionId`, encoded with `.2byte` |
| `0x16` | `cave` | `u8` |
| `0x17` | `weather` | `u8` |
| `0x18` | `mapType` | `u8` |
| `0x19` | `floorNum` | `s8` |
| `0x1A` | `filler` | `u8` |
| `0x1B` | flags | packed `u8` |
| `0x1C` | `battleType` | `u8` |
| `0x1D` | trailing padding | 3 explicit zero bytes |

Generated assembly must place `.balign 4` or the assembler-equivalent `.align 2` before every header include, every map-group pointer array, and the top-level `gMapGroups` table. It must emit three trailing zero bytes, not rely on the next record's alignment to supply them.

This is a correctness requirement on ARM7TDMI. A widened field leaves 29 meaningful bytes. Without explicit record padding and alignment, a following header can begin on an odd address. Word loads from misaligned pointer fields rotate data, producing invalid layouts, tileset callbacks, and map-load hangs.

C must assert the same ABI:

```c
STATIC_ASSERT(sizeof(struct MapHeader) == 0x20, MapHeader_size);
STATIC_ASSERT(_Alignof(struct MapHeader) == 4, MapHeader_alignment);
STATIC_ASSERT(offsetof(struct MapHeader, regionMapSectionId) == 0x14,
              MapHeader_regionMapSectionId_offset);
STATIC_ASSERT(offsetof(struct MapHeader, battleType) == 0x1C,
              MapHeader_battleType_offset);
```

Add assertions for every pointer and scalar field, not only the two shown. A generator test must parse or assemble one fixture and compare its offsets and total stride with the C schema. Consecutive headers are part of the test because a single isolated aligned header does not expose stride bugs.

## Layout-format model

PKMN-World reveals that Johto is not simply an Emerald or FRLG layout. Its generator emits both `isFrlg` and `isJohto`. Runtime code checks `isFrlg || isJohto` for FRLG-sized primary resources. More importantly, its later field-map code stores `hasFrlgAttributes` on each `Tileset`, because a Johto layout may borrow a Kanto tileset and primary and secondary tilesets may use different attribute widths. That behavior is useful evidence, but donor booleans still permit invalid states and spread format knowledge through field code.

Replace the booleans with one closed format value stored explicitly as a byte:

```c
enum MapLayoutFormatValue {
    MAP_LAYOUT_FORMAT_EMERALD,
    MAP_LAYOUT_FORMAT_FRLG,
    MAP_LAYOUT_FORMAT_JOHTO,
};

typedef u8 MapLayoutFormat;
```

The generator emits exactly one value per layout. Runtime code obtains properties through a trait table or narrow helpers:

```c
struct MapLayoutFormatTraits {
    u16 primaryTileCount;
    u16 primaryMetatileCount;
    u8 primaryPaletteCount;
    u8 borderFormat;
    u8 doorFormat;
    u8 escalatorFormat;
    u8 shopPaletteFormat;
};
```

The initial layout traits preserve resource-count and field-presentation behavior:

- Emerald: Emerald primary counts, palettes, borders, doors, and escalators;
- FRLG: FRLG primary counts, palettes, borders, doors, and escalators;
- Johto: 640 primary tiles, 640 primary metatiles, 7 primary palettes, Emerald borders, FRLG door behavior, Emerald escalators, and Emerald shop-menu palette behavior.

Metatile attribute encoding belongs to each tileset, not the layout:

```c
enum MetatileAttributeFormatValue {
    METATILE_ATTRIBUTES_EMERALD_U16,
    METATILE_ATTRIBUTES_FRLG_U32,
};

typedef u8 MetatileAttributeFormat;

// Existing byte at offset 0x01 becomes an explicit flags byte.
#define TILESET_FLAG_SECONDARY          (1 << 0)
#define TILESET_ATTRIBUTE_FORMAT_SHIFT  1
#define TILESET_ATTRIBUTE_FORMAT_MASK   (3 << TILESET_ATTRIBUTE_FORMAT_SHIFT)

struct Tileset {
    // offset 0x00: existing compression/palette bits
    u8 flags; // offset 0x01: secondary plus MetatileAttributeFormat bits
    // remaining fields retain their current offsets
};
```

The tileset declaration macro or generator derives the format bits from the attribute blob and validates bytes per metatile. It must be impossible to declare a `u16` blob as FRLG or a `u32` blob as Emerald without a generation or compile-time failure. Attribute lookup selects the primary or secondary tileset first, then decodes through `GetTilesetAttributeFormat(tileset)`. A single layout may therefore use one width for its primary tileset and another for its secondary tileset. Donor National Park and Route 28 layouts are regression fixtures for opposite mixtures.

Audit `src/fieldmap.c`, `src/field_door.c`, `src/fldeff_escalator.c`, shop/door animation users, border drawing, metatile decoding, and palette loading. Replace direct `isFrlg` and `isJohto` branching with helpers that name the property being selected. A caller decoding attributes must receive a tileset, not a layout.

Serialize `MapLayout.format` as a `MapLayoutFormat` byte at offset `0x18`, followed by `borderWidth` at `0x19`, `borderHeight` at `0x1A`, and explicit padding at `0x1B`; `sizeof(struct MapLayout)` remains `0x1C` with four-byte alignment. The `Tileset` flags byte remains at `0x01`; `sizeof(struct Tileset)` remains `0x18` with four-byte alignment. Store every layout, border, door, escalator, shop-palette, and tileset-format discriminator as explicit `u8` data, not a compiler-sized enum. Assert all C and assembly offsets, sizes, alignments, and strides. Unknown values are generator errors and debug-build runtime assertions.

## Asset residency

Adapt the donor's effective `IS_FRLG || ALL_REGIONS` asset guards in:

- `src/data/tilesets/headers.h`;
- `src/data/tilesets/metatiles.h`;
- the relevant tileset graphics, palette, and animation include sources;
- `src/field_door.c`, including both regional door graphics tables and animation data;
- FRLG object-event graphics, picture tables, graphics info, and pointer tables;
- callback and script translation units referenced by resident maps.

Hoenn and FRLG asset families are both resident in every `pokemon-openworld` product build. Johto assets, when imported, are guarded by `ALL_REGIONS` or a dedicated content capability; they must not be unconditionally linked as in parts of the donor. Compatibility branches involving `IS_FRLG` may remain in source for upstream integration, but they are not separate product configurations.

Prefer named capability macros at the data boundary:

```c
#define HAS_HOENN_TILESETS (!IS_FRLG || ALL_REGIONS)
#define HAS_FRLG_TILESETS  (IS_FRLG || ALL_REGIONS)
#define HAS_JOHTO_TILESETS (ALL_REGIONS && HAS_JOHTO_CONTENT)
```

These macros select content only. Runtime layout interpretation must use `MapLayoutFormat`, not build macros. A single ROM contains several formats at once.

The generator validates declared registry references but does not claim to resolve C or assembly symbols. The assembler and linker must resolve every referenced graphics, animation, callback, and script symbol. A post-link validator then checks that pointer-table entries and callbacks fall inside expected ROM ranges and are resident in the selected artifact. A map being present in `gMapGroups` is insufficient if its callback was removed by a retail-version guard.

## World identity and region metadata

Do not copy the donor's widened `mapsec_u8_t`. Introduce honest domain types:

```c
typedef u8 RegionId;
typedef u16 MapSectionId;
typedef u8 SavedLocationCode;
typedef u8 MetLocationCode;
```

`MapSectionId` is used by world geography, map headers, region maps, landmarks, map previews, Fly data, Pokenav, Pokedex-area displays, popups, and scripts that identify a world section. Update API signatures, locals, arrays, and return types. An old `u8` parameter such as a map-preview section argument must not survive behind an implicit conversion.

Region membership is generated metadata, not a numeric-range test:

```c
enum MapSectionKindValue {
    MAP_SECTION_GEOGRAPHIC,
    MAP_SECTION_DYNAMIC,
    MAP_SECTION_NON_GEOGRAPHIC,
    MAP_SECTION_ALIAS,
    MAP_SECTION_RESERVED,
};

typedef u8 MapSectionKind;
#define REGION_NONE ((RegionId)0xFF)

struct MapSectionMetadata {
    MapSectionKind kind;
    RegionId region;
    u8 regionMapType;
    u8 presentationFlags;
    u8 subregion;
};

extern const struct MapSectionMetadata gMapSectionMetadata[MAPSEC_COUNT];
```

Accessors such as `GetMapSectionKind`, `TryGetRegionForSectionId`, `GetRegionMapType`, and `GetKantoSubregion` read this table. Geographic entries require a real region. Dynamic, non-geographic, alias, and reserved entries may use `REGION_NONE` or a documented context resolver. Numeric section ranges may remain an ordering convention, but never the authority. At roughly five bytes per current section, this costs about 1.3 KiB and removes an architectural dependency on contiguity.

Each reviewed map-section record contains an explicit numeric `value`; JSON array order is presentation only. Before changing the generator, check in a frozen constant-to-number manifest for every existing map section and provenance code. Generation compares the reviewed source with this compatibility manifest and fails on any unapproved change. Values are append-only, and removing a location reserves its value rather than renumbering later entries.

`MAPSEC_INVALID` is the fixed `MapSectionId` sentinel `0xFFFF`, not an enum member after the generated array. `MAPSEC_NONE` may remain temporarily as an alias to `MAPSEC_INVALID` for migration compatibility. `MAPSEC_COUNT` is generated from the highest dense table index and never doubles as invalid identity. `MAPSEC_DYNAMIC`, `MAPSEC_SECRET_BASE`, `MAPSEC_SPECIAL_AREA`, and other synthetic sections receive explicit metadata kinds such as geographic, dynamic, non-geographic, or alias. Their region is optional or context-derived; they must not be assigned a dishonest fixed region merely to fill a table cell.

Generation fails on duplicate values, gaps not marked reserved, changes to frozen values, sentinel collisions, or metadata count mismatches. Ordering-dependent callers in region-map, Pokedex-area, summary, landmark, and similar code must use validity and kind accessors rather than comparing an arbitrary value with `MAPSEC_INVALID`.

## Compact serialized locations

The world-to-`u16` migration crosses more persisted boundaries than Pokémon provenance. `TVShow` variants and `GabbyAndTyData` store `mapsec_u8_t` fields in `SaveBlock1`; TV records are also copied into fixed record-mixing packets. These layouts stay byte-sized.

Introduce `SavedLocationCode` plus explicit boundary functions:

```c
SavedLocationCode EncodeSavedLocation(MapSectionId section);
MapSectionId DecodeSavedLocation(SavedLocationCode code);
```

The generated mapping preserves existing section values `0` through `208` exactly. Later sections use reviewed canonical aliases where the serialized feature only needs a displayable location. Reads decode before world or map-name APIs; writes encode before assignment to TV, Gabby/Ty, record-mixing, or any other fixed field. Direct assignment between `MapSectionId` and `SavedLocationCode` is forbidden.

Saved-location and Pokémon-provenance accessors may share one reviewed canonical-alias source for ordinary locations, but they emit domain-specific tables and enforce different reserved-value rules. Do not collapse the public types or their boundary functions merely because most current numeric mappings match.

Before widening, mechanically inventory every `mapsec_u8_t`, every save-block field, every record-mixing packet, and every link payload. Classify each use as world identity, compact saved location, Pokémon provenance, map group/number, or unrelated byte. Add size and offset assertions for every retained serialized structure. If a boundary cannot tolerate aliases, it requires an explicit feature policy or a separate RFC rather than a hidden truncation.

## Pokémon provenance

Pokémon storage remains byte-compatible. `MetLocationCode` keeps ordinary values below the reserved `0xFD` through `0xFF` special origins. No `BoxPokemon`, party, PC, save-sector, or trade packet structure changes in this RFC.

Generate two reviewed tables:

```c
extern const MetLocationCode gMapSectionToMetLocation[MAPSEC_COUNT];
extern const MapSectionId gMetLocationToMapSection[MET_LOCATION_ORDINARY_COUNT];
```

The forward table is total because eggs may hatch on any loadable map, including maps with no encounters. The reverse table selects the representative world section whose existing name is shown for each ordinary provenance code. This avoids duplicating name strings and gives aliases a canonical display target.

Mapping policy is:

1. preserve existing provenance codes `0` through `208` exactly unless a separately approved save migration changes them;
2. allocate remaining codes to Johto cities, routes, caves, and other high-value provenance labels;
3. alias overflow interiors and minor landmarks to a reviewed parent city, route, cave, or island;
4. use a generic distant-location code only as an explicit reviewed entry when no truthful parent exists;
5. reject casts, truncation, `min` clamps, and implicit fallback.

The mapping source should be human-reviewable, such as a JSON object or declarative table keyed by map-section constant. Generated output owns the dense arrays. Tests cover exact mappings, aliases, catches, hatches, special origins, and section IDs above 255.

This boundary also keeps future retail trading tractable. A later trade RFC can add explicit Gen I, Gen II, Gen III, and native wire codecs without coupling those protocols to the world-section width.

The donor defect is stricter than overflow beyond `0xFF`: ordinary world sections `253` through `255` collide with the reserved egg, in-game-trade, and fateful-encounter codes. The local generator must reject every ordinary-code collision, even if the value still fits in a byte.

## File-level change map

Expected implementation surfaces are:

- `Makefile` and `map_data_rules.mk`: force the sole Emerald/all-regions product identity, isolate build and generated roots, reject retail ROM targets, and retain retail dialects only as generator fixtures;
- `tools/mapjson/mapjson.cpp`: explicit build policy, input-only reviewed JSON, inclusive registry generation, fixed header schema, format emission, alignment, validation;
- `include/gametypes.h`: clean region, map-section, and provenance types;
- `include/global.fieldmap.h`: serialized `MapHeader`, `MapLayout`, and per-tileset attribute-format contracts;
- `src/data/tilesets/headers.h` and `src/data/tilesets/metatiles.h`: unified asset residency;
- tileset graphics, palette, and animation include sources: resident regional data and callbacks;
- `src/fieldmap.c`: layout traits for counts, palettes, and borders plus tileset-local attribute decoding;
- `src/field_door.c` and `src/fldeff_escalator.c`: format-trait animation behavior;
- `include/regions.h` and `src/regions.c`: explicit region metadata API;
- `src/region_map.c` and map-name, preview, Pokenav, popup, Fly, and Pokedex-area users: `MapSectionId` audit;
- `include/global.tv.h`, `src/tv.c`, and `src/record_mixing.c`: compact saved-location boundaries without layout changes;
- generated metadata sources: explicit section values, region metadata, saved-location codecs, and provenance tables;
- host and emulator tests: schema, registry, direct-load, and save/Pokémon regressions.

Exact generated filenames may follow existing mapjson conventions. Generated data must be clearly separated from reviewed source metadata.

## Delivery plan

### Slice 0: isolated preflight and test iron

- isolate object, generated, and ROM outputs by build mode;
- stop generation from mutating reviewed JSON or shared generated trees;
- add deterministic alternating-mode generation tests;
- add the test-only direct-load harness before making map-load claims;
- record artifact-size, EWRAM, and IWRAM baselines for normal, debug, release, test, and headless `pokemon-openworld` builds.

Gate: alternating `emerald`, `firered`, and `allregions` generator fixtures cannot contaminate one another; only `allregions` can link the product ROM; and the harness can report a controlled map initialization failure.

### Slice A: current-ABI three-region feasibility

- add explicit `MapBuildMode::AllRegions` policy while section IDs still fit in `u8`;
- make Hoenn and FRLG tilesets, door graphics, object-event graphics, callbacks, and scripts resident;
- produce and measure the first Hoenn, Kanto, and Sevii unified ROM;
- sweep all current map headers through layout and tileset initialization with scripts and events suppressed;
- fully settle representative maps with normal field initialization.

Gate: the unified ROM stays at or below 32 MiB and retains the approved Johto headroom floor; every current map passes the structural load sweep; representative regional maps reach field-ready state with restored player control; and title/new-game/Hoenn continue regressions pass. Failure here stops the architecture migration until capacity or residency is corrected.

### Slice B: explicit layout and tileset formats

- replace `MapLayout.isFrlg` with the byte-sized `MapLayoutFormat` contract;
- replace layout-wide attribute decoding with byte-sized per-tileset format flags;
- convert border, counts, palettes, doors, escalators, and shop behavior to named traits;
- assert the complete `MapLayout` and `Tileset` C/assembly ABIs;
- test Emerald, FRLG, and mixed-width donor fixtures.

Gate: all `pokemon-openworld` build variants preserve current field behavior, while host-side retail-dialect fixtures, synthetic Johto traits, and mixed tilesets select the exact expected paths without linking retail ROMs.

### Slice C: atomic world-ID and serialized-boundary migration

This slice lands as one buildable change. The C `MapHeader` must never be widened in a revision whose generated assembly still uses the old schema.

- freeze checked-in numeric manifests for all existing map sections and provenance codes, and set `MAPSEC_INVALID` to `0xFFFF`;
- add section kinds for dynamic and non-geographic identities;
- add `RegionId`, `MapSectionId`, `SavedLocationCode`, and `MetLocationCode`;
- widen the C header and generated assembly together, including padding, alignment, offsets, and stride tests;
- convert every world-geography API and data table to `MapSectionId`;
- convert every fixed save, TV, Gabby/Ty, record-mixing, and Pokémon boundary through explicit codecs;
- preserve current saved-location and provenance values `0` through `208` exactly;
- generate region metadata plus total saved-location and provenance mappings;
- add synthetic section values above 255 and collision tests before Johto content exists.

Gate: normal, debug, release, test, and headless `pokemon-openworld` builds pass; all serialized size and offset assertions remain unchanged; no audited geography-to-byte assignment or cast remains; synthetic values above 255 survive world APIs and encode through reviewed compact mappings.

### Slice D: fail-closed generation and exhaustive hardening

- reject missing borders, layouts, maps, tilesets, callbacks, scripts, metadata, and codec entries;
- enforce signed `WarpData` group and map bounds;
- run byte-for-byte determinism and stable-ID checks;
- run the all-map structural sweep and representative full field-ready loads;
- publish final ROM, EWRAM, and IWRAM budgets.

Gate: every registered Hoenn, Kanto, and Sevii map is structurally loadable, representative full loads reach field-ready state, and the final unified ROM stays at or below 32 MiB while retaining the approved headroom floor.

### Slice E: Johto import

- import Johto as a separate content change;
- classify each layout with `MAP_LAYOUT_FORMAT_JOHTO` or another proven existing format;
- add guarded assets, region metadata, and provenance decisions;
- update count sentinels and direct-load coverage.

Gate: sections above 255, mixed primary/secondary attribute widths, and all three layout formats are exercised in a real unified build. No foundation ABI redesign is permitted merely to land content unless a new RFC supersedes this one.

## Validation and acceptance

Each validation layer proves a different claim. Passing one layer must not be reported as evidence for another.

### Generator validation

- every registered map has one non-null group entry;
- every referenced layout and tileset exists;
- all current 75 group slots and 785 layout slots resolve as expected;
- all current 935 grouped maps are emitted, excluding only the four reviewed unused-house directories;
- every header address and header stride is divisible by four;
- the assembly and C `MapHeader` schemas match exactly;
- every layout has exactly one known format;
- every section has kind, region where applicable, saved-location, and provenance metadata;
- alternating build modes produce deterministic, isolated output and never modify reviewed inputs.

### Linker and artifact validation

- every callback and script reference links;
- normal, debug, release, test, and headless `pokemon-openworld` builds succeed with the same Emerald/all-regions identity;
- Makefile, CI, and release configuration expose no FireRed or LeafGreen ROM artifact;
- linked ROM size does not exceed 32 MiB and retains the approved headroom floor;
- ROM, EWRAM, and IWRAM reports are stored for comparison.

### Exhaustive structural validation

An all-map sweep loads every registered map through header, layout, border, tileset, palette, metatile, and callback initialization while suppressing story scripts and event execution. This proves structural residency, not full gameplay readiness.

### Emulator behavior validation

Representative full field-ready loads settle maps from Hoenn, mainland Kanto, Sevii 1-3, Sevii 4-5, Sevii 6-7, and later Johto with normal scripts and events. Coverage includes at least one exterior, interior, and cave for each resident layout format and each mixed tileset-attribute combination.

For each load, assert:

- expected map group and number;
- valid header and layout pointers;
- valid primary and secondary tilesets;
- recognized layout traits;
- valid region metadata and map-section value;
- valid animation callback where applicable;
- completed initialization scripts/events for the representative fixture;
- expected player coordinates and restored player control;
- no soft reset, exception, or hang through the settling window.

Regression coverage includes title boot, new game, existing Hoenn save/continue, TV and Gabby/Ty location display, record mixing, catching, hatching, Pokémon save/load, saved-location aliases, provenance aliases, special origins, sections `253` through `255`, and a world section greater than 255.

## Capacity policy

The current baseline is 26,514,756 bytes, 79.02% of a 32 MiB ROM, leaving 7,039,676 bytes before unified assets. PKMN-World proves a unified donor build can link, but its different content baseline is not a capacity guarantee for this fork. Capacity is therefore a Slice A feasibility gate before the world-ID migration, not a late hardening check.

Slice A must approve a numeric remaining-headroom floor before Slice B begins. The floor is at least the measured Johto-only resident asset estimate plus 25% integration contingency and 512 KiB reserved for later travel and story glue. Merely fitting below 32 MiB does not pass when the remaining space is below that floor.

Record ROM, EWRAM, and IWRAM use after each slice. If ROM capacity is exceeded, first remove duplicate, unused, or unreachable graphics, audio, and story assets. Do not weaken map identity, provenance validation, header alignment, or layout-format safety to recover space. Larger-than-32-MiB ROMs and dynamic bank switching require a separate RFC.

## Risks and controls

- **Partial type widening:** implicit `u8` APIs truncate sections. Control with a full call-site audit, warnings, and tests above 255.
- **Weak typedef separation:** C typedefs do not prevent assignment between integer domains. Control with mandatory encode/decode accessors, no direct casts, and a mechanical narrowing audit in CI.
- **Serialized-location drift:** TV, Gabby/Ty, or record mixing silently truncates world IDs or changes packet sizes. Control with compact codecs plus size and offset assertions.
- **C/assembly drift:** header fields appear valid until the next unaligned record. Control with exact offsets, explicit padding, generated fixtures, and consecutive-record tests.
- **Cross-mode contamination:** shared objects or generated includes survive a mode switch. Control with isolated mode roots, stamps, alternating-order tests, and atomic generation promotion.
- **Missing guarded assets:** maps link but crash when their tileset callback runs. Control with symbol validation and representative direct loads.
- **Format leakage:** scattered FRLG/Johto booleans recreate donor coupling, while layout-wide attribute width misreads mixed tilesets. Control with one layout enum, property-level traits, and tileset-local attribute formats.
- **Metadata drift:** reordered IDs corrupt saves and scripts. Control with explicit append-only IDs and generated duplicate/order checks.
- **Dishonest provenance aliases:** summaries show misleading locations. Control with reviewed mappings and no implicit fallback.
- **Donor scope creep:** story and save machinery enter through broad patches. Control with narrow ports and per-slice diffs.
- **ROM exhaustion:** resident assets cross 32 MiB. Control with early measurement and asset deduplication before architecture compromise.

## Considered implementation approaches

### Wholesale PKMN-World transplant

This is the shortest path to a first build, but imports unrelated story, save, region-state, and Johto assumptions. It also preserves global generator state, misleading types, boolean format combinations, numeric region ranges, and provenance fallback. The first ROM may work while the long-term contracts remain fragile. Rejected.

### Clean implementation without donor code

This produces the least inherited code, but discards hard-won evidence about generator filters, asset guards, header stride, ARM alignment, and Johto's hybrid layout convention. It would spend time rediscovering known failures and make crash diagnosis less certain. Rejected.

### Donor-guided adaptation

This uses PKMN-World to identify required behavior and proven failure points, then implements those lessons against the approved local architecture. It costs more review than a transplant and less discovery than a clean-room implementation. It gives each imported behavior an explicit contract and acceptance gate. Selected.

## Completion criteria

This RFC is complete when normal, debug, release, test, and headless `pokemon-openworld` builds share the forced Emerald/all-regions identity, fit within 32 MiB, and retain the approved headroom floor; no FireRed or LeafGreen ROM target or artifact is exposed; every registered Hoenn, Kanto, and Sevii map passes the structural load sweep; representative maps reach field-ready state; frozen map-section values and `MAPSEC_INVALID = 0xFFFF` are enforced; world section IDs safely exceed 255; TV, Gabby/Ty, record-mixing, save, and Pokémon layouts remain unchanged behind explicit codecs; mixed tileset attribute widths decode correctly; and the code exposes a documented `MAP_LAYOUT_FORMAT_JOHTO` path ready for a later Johto content import.
