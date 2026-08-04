# RFC: Multi-region world foundation

- Status: Approved
- Scope: Hoenn, Kanto, Sevii Islands, and planned Johto support
- Base engine: Emerald
- Implementation RFC: [PKMN-World donor adaptation](./pkmn-world-donor-adaptation.md)
- Implementation gate: The linked implementation RFC must be approved before code work begins.

## Summary

Build one Emerald-based ROM in which every regional map, layout, tileset, event table, and region-map definition is resident and structurally loadable. Prove full field-ready behavior on representative maps; story and event state fixtures for exhaustive full loads remain outside this foundation. Use a 16-bit map-section identity throughout the world engine, while keeping the Pokémon met-location field byte-sized and mapping detailed map sections onto a smaller provenance vocabulary.

This separates two concepts that the inherited engine conflates:

- `MapSectionId` identifies geography used by maps, region maps, Fly data, encounter displays, scripts, and world logic.
- `MetLocationCode` records a compact provenance label inside a Pokémon.

The world receives full fidelity and room for additional regions. Pokémon storage, save-sector allocation, TV/Gabby/Ty records, record-mixing packets, and link packet sizes remain unchanged. Byte-sized persisted locations cross explicit compact codecs, so exact display naming may be coarser for a small number of later locations.

Original-game trading is not part of this RFC. The design preserves a clean boundary for future per-generation codecs without making link protocols a dependency of the world foundation.

## Motivation

`pokemon-openworld` already contains the Hoenn and Kanto/Sevii map directories and the mixed Emerald/FRLG runtime map-format support. The default Emerald generator filters non-Hoenn maps and FRLG layouts out, leaving map constants whose generated group pointers are null. A later warp to one of those constants can compile and then crash during map loading.

Johto adds a second constraint. The current three-region registry has 209 real map sections, numbered 0–208, and fits in one byte. The `PKMN-World` reference reaches 266 sections after adding Johto, so a byte-sized world section can no longer represent every location.

The inherited type also aliases map sections and Pokémon met locations even though their requirements differ. The world needs an extensible geographic identifier. Pokémon store provenance inside a tightly packed, encrypted record and reserve values `0xFD`–`0xFF` for special origins. Expanding that record would affect PC storage, save sectors, trades, recorded battles, mystery events, and tools.

The foundation should remove the world limit without turning a map-loading project into a Pokémon-format and link-protocol migration.

## Goals

- Build Hoenn, Kanto, and Sevii into the sole product ROM, `pokemon-openworld.gba`, and remain structurally ready for Johto.
- Make every registered map and layout structurally loadable, and make representative regional maps fully field-ready, even before player-facing travel exists.
- Support more than 256 world map sections.
- Preserve distinct region identity without deriving it only from numeric ranges.
- Keep `BoxPokemon`, party records, Pokémon storage, and save-sector allocation unchanged.
- Replace scattered layout booleans with explicit layout traits and tileset-local metatile-attribute formats.
- Preserve stable, append-only identifiers once the new registry is established.
- Fail generation or linking when a map, layout, tileset, callback, event, script, or provenance mapping is incomplete.

## Non-goals

- Story integration or progression reconciliation.
- Player-facing inter-region warps.
- Cross-region Fly behavior.
- Badge, flag, party, or active-region switching systems.
- Original Gen I, II, or III trade protocols.
- Exact Pokémon met-location names for every world section.
- Save migration for an expanded Pokémon binary format.
- A nonstandard ROM larger than 32 MiB.

These are sequencing exclusions, not permanent product prohibitions. Later work is expected to add the inter-region warps and travel behavior after this resident-world foundation is stable.

## Proposed architecture

### Unified product build

Make the sole `pokemon-openworld` product an `ALL_REGIONS` build while retaining Emerald as the engine base:

- `GAME_VERSION=EMERALD`
- `IS_FRLG=0`
- `ALL_REGIONS=1`
- `MAP_VERSION=allregions`
- `FILE_NAME=pokemon-openworld`

These values define the only supported ROM product and are not user-selectable game variants. Pass `ALL_REGIONS` through C and assembly. Do not expose FireRed or LeafGreen ROM targets. `mapjson` may retain its `emerald` and `firered` data dialects only as isolated generator fixtures for upstream comparison, format validation, and debugging; those fixtures must not link or publish retail ROM artifacts.

`tools/mapjson` must treat `allregions` as Emerald-default data interpretation without filtering by region or layout version. It must emit every registered map header, event table, connection table, group pointer, and layout pointer.

### Resident regional assets

The unified build links both Emerald and FRLG asset families:

- tileset headers;
- graphics and palettes;
- metatiles and attributes;
- tileset animation callbacks;
- regional door graphics and animation tables;
- regional object-event graphics, picture tables, graphics info, and pointer tables;
- referenced event and script entry points.

Do not convert FRLG map data into Emerald format. One `MapLayoutFormat` selects layout-wide primary counts, palette counts, borders, doors, and escalators. Metatile attribute width belongs to each primary or secondary `Tileset`, because a Johto layout may mix Emerald-format `u16` and FRLG-format `u32` attribute blobs. Johto receives an explicit layout format for the FRLG-sized resource regime demonstrated by the donor.

### World identity types

Introduce deliberately separate types:

- `RegionId`: explicit region identity.
- `MapSectionId`: a `u16` world-geography identifier.
- `SavedLocationCode`: a `u8` compact location stored in fixed save and record-mixing structures.
- `MetLocationCode`: a `u8` Pokémon-provenance identifier.

Do not retain the name `mapsec_u8_t` for a widened value. APIs should communicate their actual domain and storage width.

Map-section IDs have explicit numeric values and are append-only. Freeze all existing values before migration; array order must not assign persistent IDs. `MAPSEC_INVALID` is fixed at `0xFFFF`; `MAPSEC_NONE` may remain only as a compatibility alias during migration. Dynamic and non-geographic sections have explicit metadata kinds and may use `REGION_NONE` or context-derived region resolution. A generated metadata registry associates each geographic `MapSectionId` with its region, display name, region-map presentation, and other properties. Region membership must come from metadata rather than relying only on contiguous numeric ranges.

### Serialized map header

Widen `MapHeader.regionMapSectionId` to `MapSectionId` and define the serialized map header as an explicit 32-byte record:

- emit the section with `.2byte`;
- emit explicit trailing padding;
- align every header and pointer table to four bytes;
- add compile-time assertions for field offsets and total structure size;
- add generator tests that compare the C layout with the assembly schema.

The explicit 32-byte record avoids relying on implicit padding after the 29 bytes of meaningful widened fields. This prevents unaligned ARM7TDMI word loads from rotating pointer data and corrupting map initialization.

### Pokémon provenance mapping

Keep the encrypted Pokémon field and all public Pokémon record sizes unchanged. `MetLocationCode` remains one byte with `0xFD`–`0xFF` reserved for the existing special origins.

Generate a total mapping from `MapSectionId` to `MetLocationCode`:

- preserve existing provenance codes `0` through `208` exactly unless a separately approved save migration changes them;
- allocate remaining ordinary codes to high-value Johto locations, prioritizing cities, routes, and catchable landmarks;
- map overflow interiors and minor locations to a meaningful parent city, route, cave, or landmark;
- use a deliberate generic distant-location code only when no honest parent exists;
- forbid implicit casts and silent truncation.

A separate met-location display registry owns the name associated with each code. Pokémon summaries do not index the complete world map-section table directly.

Generation must fail if a catchable or hatchable map lacks an explicit provenance mapping. Aliases are reviewed data, not fallback behavior.

### Other compact serialized locations

TV show variants and `GabbyAndTyData` store byte-sized map sections inside `SaveBlock1`, and TV records cross fixed record-mixing packets. Keep those layouts unchanged and convert only through generated `MapSectionId` to `SavedLocationCode` encode/decode functions. Preserve current values `0` through `208` exactly; later locations use reviewed display aliases.

Mechanically inventory every byte-sized map-section use before widening. Classify it as world identity, saved-location code, Pokémon provenance, map group/number, or unrelated data. Retain size and offset assertions for every fixed save, packet, and link structure. A C typedef alone is not domain enforcement, so direct casts and assignments across these domains are forbidden.

### Compatibility boundary

Internal Pokémon records must not become an assumed network protocol. Future trade work should define explicit Gen I, Gen II, Gen III, and `pokemon-openworld` wire codecs that convert at the boundary.

This RFC implements none of those codecs. Keeping Pokémon storage byte-compatible reduces their future cost, especially for original Gen III, but does not claim that the expansion's species, move, item, or repurposed fields are already retail-compatible.

## Data invariants

The generator and build must enforce these invariants:

- Every registered map belongs to exactly one generated group entry.
- Every generated group and layout pointer required by a constant is non-null.
- Map group and map number values remain within the signed `s8` `WarpData` domain, currently `0` through `127`.
- Every map header references an existing layout and valid tilesets.
- Every tileset animation callback resolves inside the ROM.
- Every geographic `MapSectionId` has region metadata.
- Every section has an explicit geographic, dynamic, non-geographic, alias, or reserved kind.
- Every fixed serialized location crosses a reviewed compact codec.
- Every catchable or hatchable map has an explicit `MetLocationCode` mapping.
- Special met-location codes never collide with ordinary provenance codes.
- Serialized map-header offsets and size match the C definition.
- Existing identifiers are never reordered after release.

## Validation

### Build-time validation

- Clean-generate all unified map outputs.
- Assert the current 935 grouped maps are emitted and the four known unused-house directories remain the only current exclusions.
- Assert all 75 current group slots and 785 current layout slots are valid; update expected counts when Johto is imported.
- Build the normal, debug, and release ROMs, the test-runner and headless-test ELFs, and the debug-only `pokemon-openworld-e2e` ROM; all use the same Emerald engine and unified world. FireRed, LeafGreen, and Virtual Console ROM products are not supported targets.
- Preserve the rendered `CI / Build`, `CI / E2E (Core)`, `CI / E2E (Extended)`, and `Metadata / Lint` check identities. Keep `Build` on `make emerald syms` and verify that its release-authority `pokemon-openworld` artifact contains exactly `pokemon-openworld.gba`, `.map`, and `.sym`.
- Add `Foundation` as a third entry in the existing fail-fast-disabled E2E matrix, invoking `make e2e-foundation` and producing the required `CI / E2E (Foundation)` context. It follows the existing suite-scoped failure-evidence policy: upload `test-results/e2e/foundation/` under `if: failure()`, warn when no evidence files exist, retain them for three days, and publish no E2E ROM artifact.
- Add a separate required `CI / Foundation` check for non-emulator gates. The repository ruleset stores job names rather than rendered workflow/job labels, so require the exact contexts `Build`, `E2E (Core)`, `E2E (Extended)`, `E2E (Foundation)`, `Foundation`, and `Lint`. The Foundation job runs generator/schema checks, collision-safe debug and optimized release-mode builds, `make check`, and per-ROM capacity validation. Copy each mode's outputs to separate evidence staging before another mode can overwrite a root-level filename.
- Upload the non-emulator measurements, logs, and test ELFs under a non-release artifact name from a step guarded by `if: ${{ always() }}` and an explicit missing-files policy. Never stage `-release`, `-test`, `-test-headless`, or `-e2e` outputs under `release/`.
- Publish ROM, EWRAM, and IWRAM usage for each build.
- Fail when the linked ROM exceeds 32 MiB.

### Runtime validation

Extend the existing `tools/e2e` SkyEmu fixture with a test-only direct map-load hook rather than adding production travel warps or a second emulator harness. Propagate `E2E=1` into C, and into assembly only if the hook needs it. Expose a symbol-addressable request/result structure with a monotonically increasing request ID and explicit idle, pending, running, success, and error states. The host writes the payload while paused, commits it by setting `pending` last, resumes, and accepts only a terminal result that echoes the request ID and requested map. The ROM validates map-group, map-number, and coordinate bounds before entering the ordinary warp and map-load path; reports the failing initialization phase and error code; and the host enforces a timeout. The hook and its symbols must be absent from normal, release, and published artifacts.

Add an independently invocable `make e2e-foundation` suite. First sweep every registered map through header, layout, border, tileset, palette, metatile, and callback initialization with story scripts and events suppressed. Run the manifest-driven sweep in one SkyEmu process with per-map diagnostics, but reload a reviewed clean state and reset tasks, callbacks, scripts, suppression flags, request state, and transient save/RAM effects before every entry. A failed reset aborts the sweep. Restore ordinary script and event behavior before representative full loads. Then fully load and settle representative maps from:

- Hoenn;
- mainland Kanto;
- Sevii 1–3;
- Sevii 4–5;
- Sevii 6–7;
- Johto after import;
- at least one interior and one cave for every resident layout format.

For each representative full load, assert the map group and number, layout pointer, primary and secondary tilesets, section metadata, animation callback, player coordinates, script/event completion state, restored player control, and absence of a soft reset or exception. Emulator survival alone is insufficient.

Add focused tests for:

- map-section values above 255;
- map-section values 253 through 255, which collide with special Pokémon origins if treated as provenance bytes;
- map-header alignment at consecutive generated records;
- compact TV, Gabby/Ty, and record-mixing location aliases with unchanged structure sizes;
- provenance aliases and special codes;
- catching and hatching on both exactly represented and aliased sections;
- Pokémon save/load stability with unchanged record sizes;
- title screen, new game, and Hoenn save/continue regression.

The existing `e2e-core` Quickstart-to-overworld smoke and `e2e-extended` Quickstart-to-Pokédex journey retain their meanings and required `CI / E2E (Core)` and `CI / E2E (Extended)` contexts. `e2e-foundation` supplies direct-load proof under `CI / E2E (Foundation)`. All three suites remain independently invocable matrix targets; this RFC does not introduce an aggregate E2E target.

## Capacity policy

The existing baseline uses 26,514,756 bytes, or 79.02% of a 32 MiB ROM, leaving 7,039,676 bytes before unified regional assets are enabled. Build and measure a current-byte-ABI Hoenn/Kanto/Sevii feasibility ROM before widening world IDs. Capacity failure stops the migration until residency or asset duplication is corrected.

If it exceeds capacity, remove duplicate or unreachable graphics, audio, and story assets before considering changes to map identity or runtime formats. A 64 MiB ROM, dynamic bank-switching layer, or second map engine is outside this RFC.

## Delivery sequence

1. Isolate build and generated outputs by mode; add deterministic generation and the `e2e-foundation` direct-load infrastructure.
2. Build and measure a current-byte-ABI Hoenn/Kanto/Sevii `ALL_REGIONS` feasibility ROM with every guarded asset family resident.
3. Atomically widen the C and generated map-header schemas while adding explicit IDs, the fixed sentinel, metadata, saved-location codecs, and provenance codecs.
4. Add fail-closed generation, exhaustive structural map loads, representative full loads, and serialized-boundary regressions.
5. Import Johto data against these contracts as a separate change.
6. Add story, travel, Fly, and trade features independently after the world foundation is stable.

Each step must leave the default `make emerald syms` candidate path buildable. No step may introduce production access to unfinished regions merely to test them.

## Risks

- A partial map-section widening can leave C and generated assembly with different offsets.
- Existing byte-sized TV, Gabby/Ty, and record-mixing locations can silently truncate without explicit codecs.
- A missing FRLG or Johto asset can link indirectly and fail only when a representative map loads.
- Shared generated files and object directories can contaminate builds when modes alternate.
- Layout-wide attribute encoding can misread Johto layouts that mix Emerald-format and FRLG-format tilesets.
- Provenance aliases may surprise players if parent mappings are chosen poorly.
- ID reordering can break scripts, saves, encounters, tools, and later compatibility work.
- The unified asset set may exceed the remaining 32 MiB ROM capacity.
- Treating internal Pokémon structs as future wire packets would recreate the coupling this RFC removes.

## Considered alternatives

### PKMN-World's widened map sections with byte met-location fallback

The reference proves that 16-bit sections and aligned headers work, but some overflow Pokémon locations collapse to a generic special area. This RFC keeps the useful widening and alignment while replacing implicit fallback with a reviewed, generated provenance mapping.

### Nine-bit Pokémon met locations

This represents all currently planned sections exactly without enlarging Pokémon records, but consumes the final obvious spare Pokémon bit and creates new encrypted-record semantics. It adds migration and compatibility work for exact names on roughly a dozen overflow locations, so it is deferred unless product requirements demand that precision.

### Full 16-bit Pokémon met locations

This gives one unlimited identifier everywhere, but enlarges encrypted Pokémon substructures, exceeds current PC save-sector capacity, changes trade and replay payloads, and creates a broad migration project. The cost is disproportionate to the world-loading requirement.

### Region-local IDs or an extension side table

Composite region/local IDs are scalable but force most geography APIs and scripts to handle pairs. A side table preserves the old header but creates two competing location authorities. A single global `u16 MapSectionId` is simpler and sufficient.

## Decision

Adopt a full-fidelity 16-bit world map-section architecture, explicit fixed IDs and section kinds, a fixed aligned map-header schema, per-tileset attribute formats, and generated region metadata in the sole Emerald-base `pokemon-openworld` product. Preserve fixed byte-sized TV, record-mixing, and Pokémon layouts through explicit reviewed codecs. Keep story, travel, Fly, and original-game trading outside the foundation.
