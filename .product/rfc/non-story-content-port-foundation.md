# RFC: Non-story regional content-port foundation

- Status: Approved
- Scope: Hoenn, Kanto, Sevii, Johto, and later regional content in the sole `pokemon-openworld` ROM
- Depends on: [Multi-region world integrity](./multi-region-world-integrity.md)
- Extends: [PKMN-World donor adaptation](./pkmn-world-donor-adaptation.md)
- Content authority: pinned HnS evidence, except reviewed PKMN-World fallbacks
- Product authority: reviewed `pokemon-openworld` source and generated registries

## Summary

Build one content-port path for every resident region. Regional maps, actors,
trainers, encounters, pickups, services, facilities, presentation, and assets
enter the same Emerald-engine runtime through reviewed data, stable identifiers,
shared services, and fail-closed generation. A region may supply different data;
it must not acquire a parallel engine.

The immediate proof target is the remaining non-story Johto content. A porter
should be able to add pinned donor data, declare adaptations and ownership,
resolve validation errors, review deterministic output, and run the required
tests without changing shared engine code. Story quests, cutscenes, villain
progression, Gym sequencing, and narrative gates remain separate product work.

This RFC turns that target into an architectural contract. It does not approve
wholesale donor import, a second Johto runtime, donor compatibility shims, or a
generic content language layered over pokeemerald-expansion.

## Motivation

The resident-world foundation is already unified. One Emerald-engine ROM links
Hoenn, Kanto, Sevii, and Johto maps; world sections use explicit region metadata;
mixed map and tileset formats use runtime traits; and structural E2E loads prove
that registered maps initialize.

The remaining content path is not unified. The current Johto importer is a
structural-residency tool:

- it authenticates pinned HnS and PKMN-World donors;
- it freezes the complete Johto map, layout, group, section, and tileset closure;
- it materializes geometry, connections, warps, static tileset assets, and world
  identity;
- it deliberately reduces 238 of 254 maps to spatial shells;
- it preserves gameplay only on the earlier 16-map baseline;
- it couples encounters and gameplay globals behind profile-wide switches;
- it contains Johto-specific allocations, batches, symbol adaptations, and exact
  shape assumptions in Python;
- it writes multiple owned outputs sequentially, so a late failure can leave a
  mixed tree even though each individual file replacement is atomic.

HnS contains substantial non-story Johto content, including ordinary NPCs,
trainers, day/night encounters, pickups, shops, healing, trades, Route 34
daycare, Safari maps and mechanics, League mechanics, music, and environmental
assets. That content is interleaved with story flags, variables, movements,
specials, and map mutations. Event-kind stripping is too coarse, while wholesale
script restoration would import story and donor assumptions together.

PKMN-World proves that much of this content can run through native expansion
systems. It also demonstrates designs that do not belong here: persisted and
volatile active-region state, automatic party boxing, regional save banks,
compatibility opcodes that erase behavior, global Safari scratch flags, numeric
range-derived region logic, and hard-coded region branches in shared services.

More hard-coded Johto adaptations would make the next import faster and every
later change worse. A new generic content framework would create a second engine
and make ordinary expansion work harder. The correct boundary is narrower:
retain expansion-native content formats, add reviewed ownership and adaptation
metadata, generate stable shared registries, and make unsupported states fail
before linking.

## Goals

- Use one import and validation path for all regional content.
- Keep ordinary map JSON, event scripts, trainer data, encounter JSON, graphics,
  audio, and other expansion-native formats as the product data shape. Each file
  is either hand-authored input or importer-rendered output, never both.
- Make donor pins, provenance, ownership, adaptations, and unsupported behavior
  explicit and reviewable.
- Activate content independently by map and capability rather than by one global
  region profile.
- Give trainers, flags, variables, visited locations, pickups, trades, services,
  and facilities stable persisted identities that do not move when counts or
  array order change.
- Make importer output deterministic, convergent, and transactionally promoted.
- Derive runtime region context from the loaded map and explicit world state.
- Represent regional differences as data consumed by shared services.
- Reject missing bindings, duplicate ownership, stale generated output, invalid
  references, and implicit regional fallbacks.
- Prove the foundation with three orthogonal non-story Johto slices before bulk
  content import begins.

## Non-goals

- Johto story, quest sequencing, cutscenes, villain state, Gym progression, or
  narrative gates.
- A player-facing region selector or separate regional campaigns.
- Region-specific party storage or automatic party replacement.
- A second event VM, script language, map engine, encounter engine, or save
  system.
- Automatic semantic translation of arbitrary donor scripts.
- Wholesale cherry-picks from HnS or PKMN-World.
- Preserving donor bugs, placeholders, compatibility no-ops, or internal numeric
  identifiers.
- Redistributing donor assets without reviewed provenance and permission.
- A universal plugin or strategy system for content that plain data and one
  resolver can represent.
- A complete save-migration framework before a real schema change requires one.

## Foundation invariants

### One product and one runtime

There is one supported product identity:

```text
GAME_VERSION = EMERALD
IS_FRLG = 0
ALL_REGIONS = 1
MAP_VERSION = allregions
FILE_NAME = pokemon-openworld
```

Regional content cannot introduce another product target, link graph, script
runtime, save layout, or published ROM. Normal, debug, optimized release,
test-runner, and headless-test artifacts may differ in optimization or
instrumentation only. E2E consumes the canonical debug ROM and symbols; it is not
another ROM build purpose. None of these differences changes resident content or
regional behavior.

### One shared implementation per behavior

Healing, shopping, trainer battles, encounters, pickups, trades, daycare, Fly,
Safari, League completion, map interactions, field-move permission, and audio
routing each have one shared implementation. Regional records may select data or
policy through typed inputs. They may not select another implementation through
`IS_FRLG`, `REGION_JOHTO`, a donor opcode, or a copied regional script frontend.

A shared implementation may branch on a property it owns, such as layout format,
tileset attribute width, facility type, battle format, or granted capability. It
must not branch on region when the real question is one of those properties.

### Map-derived region context

The current geographic region comes from the loaded map section's generated
metadata. Do not add a persisted or volatile `activeRegion` authority merely to
choose ordinary content behavior. Travel across a map boundary changes derived
region context naturally.

Explicit persisted state is allowed for facts that survive location changes,
such as discovered destinations, trainer defeat, facility sessions, League
completion, or granted capabilities. Such state must name the fact, not mirror
the current map's region.

### One authority per domain

Each authored decision has one owner:

- the authored allocation lock owns numeric map, layout, group, and section
  placement;
- the authored persistent-ID ledger owns saved identities and assigned values;
- hand-authored expansion-native inputs own local product content that the
  importer never replaces;
- importer-rendered expansion-native outputs are derived state and are never
  edited directly;
- the port descriptor owns donor pins, provenance, capability policy, adaptation
  decisions, semantic symbol references, and unsupported outcomes, but owns no
  numeric allocation;
- generated registries and output are derived evidence, never editable authority;
- HnS and PKMN-World checkouts are immutable evidence, never runtime inputs.

Every path and generated section has exactly one ownership class. Local semantic
adaptations to importer-rendered content are authored in the descriptor or an
explicit hand-authored overlay input consumed by the renderer. An overlay cannot
claim a path or section already owned as rendered output. If maintainers promote
a rendered file to hand ownership, the ownership manifest first relinquishes the
entire path; later donor updates compare and report but never overwrite it.

Repeated inventories, ignored manifest fields, copied numeric tables, and
hand-maintained summaries are forbidden when they can derive from an existing
authority.

### Fail closed

There is no default-to-Hoenn behavior for missing Johto data, no zero-valued flag
placeholder, no silent trainer collision, no null tileset callback accepted as
successful import, and no generic met-location fallback for a catchable map.

Every incomplete capability is declared as disabled, deferred, story-owned, or
unsupported. Absence never means success.

## Content boundary

### In-scope non-story capabilities

The port descriptor classifies each map and resource independently across these
capabilities:

1. spatial data: layouts, map headers, connections, warps, collision, and static
   presentation;
2. ambient actors: placement, graphics, movement, visibility, and ordinary
   dialogue;
3. interactions: signs, bookshelves, computers, televisions, environmental
   objects, and other background events;
4. trainers: presentation, parties, battle format, AI, rewards, defeat state,
   and rematch variants;
5. encounters: land, water, fishing, rock-smash, time variants, rates, levels,
   slots, and provenance;
6. pickups and rewards: visible items, hidden items, gifts, TMs, and explicit
   bag-full or duplicate behavior;
7. shops and services: inventory, price policy, availability, and shared UI;
8. healing and checkpoints: service, checkpoint discovery, whiteout destination,
   and healer presentation;
9. trades: requested species, offered Pokémon data, completion state, and shared
   trade scene;
10. facilities: daycare, Safari, League challenges, and other bounded sessions;
11. travel and presentation: region map, discovered destinations, Fly landing,
    and gateway metadata;
12. environment and assets: music, weather, palettes, tileset animations, object
    graphics, and source metadata.

Capability activation is dependency-closed. Enabling a trainer pulls in its
party, species, moves, items, presentation, script entry, dialogue, defeat state,
and referenced assets. It does not activate unrelated story on the same map.

### Story-owned behavior

The following behavior remains disabled unless separately designed and approved:

- quest and chapter sequencing;
- rival or villain progression;
- Gym eligibility, badge awards, and narrative aftermath;
- scripted takeovers and restored-world variants;
- cutscenes and coordinated movement sequences;
- story-gated rail, ferry, radio, underground, or other world transitions;
- legendary events and world-reset bundles;
- region-entry campaign initialization;
- donor challenge, randomizer, or difficulty modes.

An ordinary content record may depend on a generic capability such as `CAN_SURF`
or `LEAGUE_JOHTO_CLEARED`. This RFC does not decide how story grants it.

### Semantic classification

Raw event type is insufficient to separate story from content. Object events can
be trainers, pickups, nurses, ambient creatures, quest actors, or cutscene
participants. Scripts can mix dialogue, rewards, story state, and movements.

Every imported event or script entry receives one reviewed top-level
classification:

- `ambient`;
- `trainer`;
- `pickup`;
- `reward`;
- `service`;
- `facility`;
- `environmental`;
- `story`;
- `unsupported`.

The classification points at expansion-native source and records declared
dependencies. It is not a replacement script language. The importer also walks
every reachable command and allowlists each state read, state write, special,
movement, warp, callback, and other side effect against the activated capability.
Recognized story effects are rejected just as unknown effects are. A mixed donor
entry must be extracted into a new expansion-native entry containing only its
approved capability closure, or remain story-owned. Unknown or unowned side
effects stop the import until the descriptor classifies or adapts them.

## Donor authority and provenance

### Authority order

For the current Johto port:

1. reviewed local `pokemon-openworld` adaptations are final where this RFC allows
   a product decision;
2. pinned HnS is the content authority for maps and resources it contains;
3. pinned PKMN-World may supply content only for an exact descriptor allowlist of
   maps or fields proven absent from the pinned HnS tree;
4. unsupported or conflicting donor behavior remains explicit rather than being
   guessed from a third source.

PKMN-World mechanics may inform a new local implementation but do not become
content merely because the donors disagree. A content conflict resolves to HnS,
a reviewed local adaptation, or unsupported. Validation proves that every
PKMN-World-derived content field is allowlisted and absent from HnS.

Authority is recorded per field or asset when a file mixes sources. A file-level
label is insufficient when geometry comes from one donor, mechanical evidence
comes from another, and the product adaptation is local.

### Adaptation records

Every donor divergence records:

- source repository and pinned commit;
- source path and semantic identity;
- target path or symbol;
- source and target hashes where applicable;
- owning capability;
- adaptation reason;
- transformation or selected replacement;
- authority decision;
- support state;
- tests that cover the decision.

Unclassified divergence is an error. An adaptation cannot silently erase
behavior. Donor compatibility commands that return fixed failure values, skip
party mutations, omit shiny state, or dead-end a request must be marked
unsupported or replaced by a reviewed native behavior.

### Asset provenance

Every imported graphic, palette, map asset, sound, song, voicegroup, or converted
binary records its source, license or permission status, content hash, and
conversion command. Technical compatibility does not grant redistribution
permission. Unapproved assets remain blocked and cannot enter release artifacts.

## Stable identity and persistence

### Symbolic identity and numeric binding

Content uses stable semantic names. An authored persistent-ID ledger assigns the
numeric values required by the GBA runtime and serialized records; generated
registries bind code and data to that ledger. The ledger implementation must
first sync to the current `main` commit it will merge onto, inventory every
persisted value and published binding present there, and prove that the seeded
ledger matches that exact baseline. Those assignments freeze when the ledger
implementation merges to `main` and cannot move until a separately approved
breaking-save RFC defines and tests the migration.

The ledger covers at least:

- trainer IDs and defeat flags;
- event flags and variables;
- progression capabilities and badge facts;
- visited and Fly destinations;
- pickup and reward claim state;
- trade completion state;
- checkpoint and heal-location identity;
- daycare, Safari, and League state;
- saved-location and met-location codecs.

Bindings do not derive from item count, trainer count, array order, region-local
offset arithmetic, or the end of another range. Generation rejects duplicate
symbols, duplicate values, changed published bindings, sentinel collisions,
storage overflow, and references to unallocated state.

### Save contract

Before new persistent content lands, record the current `main` schema as the
compatibility baseline and pin sizes, offsets, checksums, and existing numeric
bindings in a checked artifact. At minimum, this includes save blocks, Pokémon
storage, party and box records, trainer state, event data, TV and record-mixing
packets, daycare deposits, and facility session state.

Representative pre-foundation saves must load, continue, and preserve their
meaning under the new ledger. This RFC does not authorize rejecting them. A later
incompatible change must provide a tested migration unless a separately approved
breaking-save RFC explicitly authorizes rejection and describes player impact.

Map sections above compact saved-location or Pokémon provenance ranges use
reviewed generated codecs. Every gameplay-relevant section has an explicit
mapping. Direct casts, truncation, and generic distant-location fallback are
forbidden.

## Import architecture

### Generic engine and declarative port descriptor

The importer separates mechanism from Johto policy.

The region-neutral engine owns:

- donor authentication;
- descriptor parsing and schema validation;
- dependency-closure calculation;
- stable binding lookup;
- source normalization;
- staged desired-state rendering;
- ownership and stale-output reconciliation;
- cross-domain validation;
- deterministic reporting;
- recoverable publication.

The Johto port descriptor owns:

- pinned donors and authority order;
- allocation-lock reference;
- per-map capability policy;
- field-level provenance and fallbacks;
- semantic event classifications;
- semantic symbol references and adaptations;
- reviewed exclusions and deferred content;
- asset permission state;
- expected inventory and digest sentinels.

The engine contains no Johto map names, region-specific batches, fixed rival
counts, berry counts, flag tuples, fallback lists, or donor-specific commands.

### Per-map and per-capability activation

Content activation is independent and composable. A descriptor may enable Route
34 geometry, trainers, encounters, pickups, and daycare while keeping story
actors disabled. Enabling encounters does not implicitly enable flags, berries,
trainers, or menus across all Johto maps.

The engine calculates the full closure before writing. A dependency on disabled
or unsupported content produces a report naming the source record and missing
capability. It never activates the dependency silently.

### Desired-state ownership and publication

The importer renders the complete owned result into a clean disposable worktree.
An ownership manifest lists every emitted file, generated section, registry
record, and content hash. Preflight compares every previously owned hash, rejects
overlapping hand ownership, and calculates stale removals before rendering.
Validation and required builds run only against the complete staged worktree.

The importer never updates a branch ref or copies a partially rendered set into
the caller's worktree. It emits one deterministic patch bundle plus the ownership
manifest from the valid staged result. Normal uberepo and Git workflow applies
that bundle to a clean task worktree, repeats the ownership preflight, runs the
required checks, and records the result as one reviewed commit. The commit is the
publication boundary; an uncommitted working tree is never accepted as published
product state.

Fault-injection tests stop after every render, validation, bundle-construction,
and application step. Every interruption before the normal commit leaves the
task branch at the old complete tree and a detectable, recoverable staging or
working-tree state. No mixed owned state may be committed or consumed by CI.
Reapplication:

- replaces changed importer-owned output;
- removes stale importer-owned output absent from the new desired state;
- preserves locally owned content;
- rejects unexpected edits to generated output;
- produces byte-identical output for the same inputs.

The importer must not treat existing checked-in generated output as another
authority. It is compared evidence and replaceable derived state.

## Shared runtime boundaries

Regional data plugs into existing or deliberately unified expansion services.
The preferred shape is a small immutable record plus one shared resolver, not a
regional frontend or function-pointer framework.

Required shared domains are:

- trainer registry and battle launch;
- encounter registry and time selector;
- actor and interaction dispatch based on behavior and map traits;
- pickup and reward transaction handling;
- shop inventory and availability;
- healing service and checkpoint registration;
- in-game trade registry and scene;
- daycare facility identity and persistent deposits;
- region-map presentation and Fly destinations;
- named progression capabilities and field-move permission;
- typed Safari sessions with central cleanup;
- League challenge state and Hall-of-Fame commit;
- environmental, music, and tileset-callback registries.

Where a current Emerald or FRLG path selects behavior globally, the migration
must identify the real property and move that selection to reviewed data. Dormant
upstream compatibility branches may remain when they cannot affect the sole
product. Source-name suffixes such as `_FRLG` may remain when they describe asset
or format provenance rather than another runtime.

## Forbidden implementations

The following changes violate this RFC:

- a second full-content Johto importer or competing manifest;
- hard-coded `JOHTO_*` allocation tuples in the generic importer;
- `if (GetCurrentRegion() == REGION_JOHTO)` in a shared service when a typed
  property or capability expresses the behavior;
- a persisted current-region mirror used for ordinary runtime dispatch;
- automatic party boxing or region-local parties;
- region-local copies of trainers, encounters, marts, healing, Fly, daycare,
  Safari, League, audio, or interaction engines;
- donor script opcodes implemented as behavior-erasing no-ops;
- one global content switch that activates unrelated categories;
- a new abstract dialogue or world-definition language duplicating expansion
  source formats;
- editable generated registries or checked output treated as authored truth;
- per-file direct publication that can leave a mixed desired state;
- implicit Hoenn, Kanto, or generic fallbacks for incomplete Johto metadata;
- asset import without provenance and permission state;
- a framework created for a hypothetical regional difference not exercised by
  at least two concrete content cases.

## Validation contract

### Import-time validation

The importer fails on:

- donor pin or tree-digest drift;
- duplicate or missing authority;
- unclassified donor divergence;
- conflicting ownership;
- missing capability dependency;
- unsupported script command, special, callback, movement, or side effect;
- unstable or colliding numeric binding;
- invalid map, warp, layout, tileset, trainer, item, move, species, music, or
  graphics reference;
- incomplete encounter tables or missing time policy;
- catchable or hatchable locations without provenance codecs;
- missing checkpoint, Fly landing, or visited-state bindings;
- unresolved tileset animation or callback dependencies;
- missing asset permission metadata;
- stale importer-owned output;
- nondeterministic generation.

### World-graph validation

The generated world graph checks destination maps and warp indexes, connection
reciprocity, reviewed one-way edges, deferred exits, unreachable shells, and
declared inter-region gateways. Dynamic script warps carry explicit validation
metadata rather than bypassing the graph.

### Runtime validation

The canonical debug ROM exercises imported content through ordinary runtime
paths. Tests cover persistence, failure cases, and restored player control rather
than checking only that a map survived initialization.

Unexpected mechanics-test assumptions count as failures in this repository.
Donor-dependent tests run in protected CI with authenticated fixtures; a skipped
donor contract test is a failure.

## Proof slices

Bulk non-story Johto import cannot begin until three orthogonal slices pass.

### Slice 1: Goldenrod service cluster

Port Route 34, Goldenrod City, Route 35, National Park, the Goldenrod Pokémon
Center, Department Store, and Route 34 Day Care. This slice covers:

- connected route, city, interior, and park navigation;
- ambient NPCs, dialogue, and signs;
- ordinary trainers and persistent defeat state;
- day and night encounters;
- visible and hidden items;
- an explicit shop inventory;
- healing, checkpoint registration, and whiteout;
- daycare deposit, experience, withdrawal, compatibility, and egg state;
- Johto region-map presentation and Fly;
- save, cold restart, and continue.

Story takeover, Gym progression, Radio Tower state, Underground plot, train
gating, and related actors remain disabled.

### Slice 2: traversal-heavy dungeon

Port the pinned HnS Whirl Islands bounded interior set: `WhirlIslands_1F`,
`WhirlIslands_B1F`, `WhirlIslands_B1F_Inner`, `WhirlIslands_B2F`,
`WhirlIslands_B3F`, and `WhirlIslands_Descent`. The Lugia chamber and legendary
event remain disabled through a reviewed deferred boundary edge. The dependency
closure includes the already-active Route 41 entrances and validates every return
warp without activating unrelated Route 41 content. The slice must exercise
content not covered by Goldenrod:

- cave or dungeon presentation;
- darkness or Flash where supported;
- Surf, Whirlpool, Waterfall, Strength, or another named field capability;
- movable objects or traversal puzzles;
- multi-floor warps and return paths;
- encounters and pickups;
- save and continue inside the dungeon.

The slice excludes legendary and narrative events.

### Slice 3: mixed authority and compact-code boundary

Port the HnS-owned Route 26 and Reception Gate boundary into the reviewed
PKMN-World fallback maps `JohtoVictoryRoad_1F`, `JohtoVictoryRoad_B1F`, and
`JohtoVictoryRoad_B2F`. The fallback uses `MAPSEC_JOHTO_VICTORY_ROAD` value 264,
which crosses both compact location boundaries. League and story content remain
disabled. The slice must exercise:

- field-level authority and provenance;
- explicit donor conflict resolution;
- saved-location and met-location codecs;
- catching inside Johto Victory Road through an explicit aliased met-location;
- hatching once on an exactly represented section and once on the aliased high
  section, followed by save and summary verification;
- travel across the authority boundary;
- save, cold restart, continue, and return traversal;
- explicit unsupported-content outcomes.

### No-engine-change declaration gate

Once the prerequisite shared registries exist, each proof-slice content change
may modify only:

- expansion-native map, script, trainer, encounter, item, service, registry, and
  asset inputs;
- the port descriptor, authored allocation lock, authored persistent-ID ledger,
  and reviewed adaptations;
- deterministic generated output;
- tests and fixtures for the slice.

It may not modify shared C implementations, behavior-bearing headers, assembly
macros, event opcodes, save structures, linker configuration, build identity, or
importer mechanism. A clean-tree path audit enforces the boundary.

If a slice requires a shared engine change, the foundation is incomplete. The
engine change returns to an earlier independently reviewed foundation ticket;
the slice does not carry a local workaround.

## Delivery sequence

### Phase 1: contract and persistence

1. Approve this RFC.
2. Record the save-schema baseline and critical serialized ABI.
3. Introduce the authored persistent-ID ledger, generated bindings, and collision
   checks.
4. Establish the single content-binding and provenance registry.

### Phase 2: import platform

1. Separate the region-neutral engine from the Johto port descriptor.
2. Make the allocation lock the only numeric placement authority; the descriptor
   remains the capability-activation authority.
3. Add independent capability policies and semantic classification.
4. Add dependency-closure calculation and shared binding resolution.
5. Render, validate, and promote a complete desired-state tree.
6. Run authenticated donor integration contracts in protected CI.

### Phase 3: shared content domains

Migrate trainers, encounters, actors, interactions, pickups, shops, healing,
trades, daycare, region-map/Fly, progression capabilities, Safari, League,
environmental assets, and tileset callbacks one domain at a time. Each migration
must preserve current Hoenn behavior, represent resident Kanto/Sevii behavior,
and accept Johto data without another implementation.

### Phase 4: proof slices

Land the Goldenrod service cluster, the traversal-heavy dungeon, and the mixed-
authority compact-code slice. Each passes its no-engine-change declaration gate
and real save-cycle E2E tests.

### Phase 5: bulk content production

After all three proof slices pass, import remaining non-story Johto content in
dependency-closed batches. Story work remains separately designed and scheduled.

## Acceptance criteria

This foundation is complete when:

- all authored decisions have one authority;
- persisted identifiers are stable, explicit, and collision-checked;
- the generic import engine contains no Johto content policy;
- capability activation is per map and category with a computed closure;
- story and unsupported behavior remain explicit;
- complete desired-state generation is deterministic and published as one
  validated, normally reviewed Git commit;
- importer-owned stale output is removed safely;
- shared runtime behavior contains no new Johto-specific implementation path;
- donor bindings and assets carry field-level provenance;
- authenticated donor tests run without skips in protected CI;
- the world graph and cross-domain references validate;
- all three proof slices pass from fresh saves and after cold restart;
- proof-slice content lands without changing shared engine or importer mechanism;
- normal, debug, and optimized release ROMs plus test-runner and headless-test
  artifacts remain within reviewed ROM, EWRAM, and IWRAM budgets;
- `make check`, `make integrity-check`, `make e2e-core`, `make e2e-extended`, and
  `make e2e-integrity` pass; every E2E suite consumes the canonical debug ROM.

## Risks

- A generic schema can become a declarative copy of pokeemerald internals. Keep
  authored expansion formats and add only metadata proven by concrete slices.
- Semantic classification requires review and cannot infer arbitrary script
  meaning safely. Unknown behavior must stop the import.
- A symbolic identity layer can still break saves if published numeric bindings
  are regenerated freely. The ledger freezes persisted assignments.
- Desired-state publication can delete hand-owned work if ownership is broad or
  path-based only. Ownership must name exact files and generated sections and
  reject unexpected edits before replacement.
- Goldenrod alone has selection bias toward ordinary services. The dungeon and
  mixed-authority slices are mandatory before claiming broad portability.
- HnS and PKMN-World disagree or omit data in places. Field-level provenance and
  explicit unsupported outcomes prevent a false unified authority.
- Donor assets may be technically usable but not redistributable. Permission is a
  release gate, not cleanup work.
- Abstracting every possible facility before a concrete second use would create
  unused framework. Shared records grow only from proven behavioral differences.

## Considered alternatives

### Extend the current Johto importer in place

Adding more Johto tuples, global switches, fixed counts, and substitutions would
port the next batch quickly. It would keep region policy in Python, preserve
duplicate authorities, and make profile transitions non-convergent. Rejected.

### Create a second full-content Johto importer

A second tool could leave structural residency untouched. It would create two
owners for the same maps, layouts, scripts, registries, and generated sections.
Ordering would become part of correctness. Rejected.

### Copy PKMN-World's regional runtime

PKMN-World demonstrates working Johto mechanics but couples them to separate
campaign state, party boxing, regional save banks, compatibility shims, and hard-
coded branches. OpenWorld is one continuous world with one party and one runtime.
Rejected.

### Translate all content into a new generic world schema

A new engine-independent schema could normalize donor differences. It would
duplicate mature expansion formats, require another compiler, and make ordinary
hack development harder. Rejected.

### Restore all HnS events and delete story later

This would mix ordinary content, story state, unsupported specials, donor bugs,
and asset questions in one change. Review could not prove what remained active.
Rejected.

### Port content manually without importer ownership

Manual ports can work for isolated maps but lose reproducibility, provenance,
closure validation, and donor-drift detection across hundreds of resources.
Rejected for bulk Johto work.

## Decision

Adopt one region-neutral content-port engine, one declarative Johto port
descriptor, explicitly partitioned hand-authored and importer-rendered
expansion-native content, stable authored identity ledgers with generated
bindings, field-level provenance, independent capability activation,
transactional desired-state publication, and shared runtime services selected by
typed data.

Use HnS as the pinned Johto content authority, PKMN-World as bounded mechanical
evidence and only the allowlisted fallback for HnS-absent content, and reviewed
local OpenWorld adaptations as final product decisions.
Prove the architecture with the Goldenrod service cluster, a traversal-heavy
dungeon, and a mixed-authority compact-code slice before bulk non-story Johto
content import begins.
