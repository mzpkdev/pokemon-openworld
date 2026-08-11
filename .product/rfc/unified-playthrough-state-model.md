# RFC: Unified-playthrough state model

- Status: Approved
- Scope: One continuous save across Hoenn, Kanto, Sevii, Johto, and later resident regions
- Depends on: [Non-story regional content-port foundation](./non-story-content-port-foundation.md)
- Tracking issue: [Milestone 3: Define the unified-playthrough contract](https://github.com/mzpkdev/pokemon-openworld/issues/22)
- Product authority: reviewed `pokemon-openworld` source, save contract, persistent-ID ledger, and generated registries

## Summary

`pokemon-openworld` is one game. A playthrough has one character, one save, one
party and PC, one bag, one Pokédex, one money balance, and one Emerald-expansion
runtime. Regional maps and stories coexist inside that playthrough. Crossing a
regional boundary changes the loaded geography. It does not select another
campaign or replace player state.

Persisted state belongs to one of five domains: global player state, geographic
world state, namespaced regional story facts, the persisted inputs to derived
player capabilities, or bounded facility state. Every saved fact has one named
authority and a defined lifetime. Current region is not a saved fact. The loaded
map's generated metadata is its only authority.

The foundation is proven by one ordinary Kanto-to-Johto round trip. That journey
must preserve the same mutable player state through travel, encounters, a trainer
battle, healing, PC use, whiteout, saves, and cold restarts. It replaces the
three disconnected Johto proof slices in the original content-port delivery
plan.

## Product invariants

- The sole product remains the `EMERALD`, `ALL_REGIONS` build defined by the
  approved world and content-port RFCs.
- A save owns exactly one player identity, party, PC, bag, Pokédex, money
  balance, play time, options record, and other whole-playthrough state.
- The loaded map determines current region through generated world metadata.
- Regional story facts coexist. There is no singular current campaign.
- Shared mechanics ask for named capabilities or typed properties, not a region,
  badge slot, donor dialect, or product-build branch.
- Maps, scripts, trainers, encounters, and services keep expansion-native data
  shapes and use shared runtime paths.
- Existing saves and published persistent bindings keep their meaning unless a
  separate breaking-save RFC approves and tests a migration.

## State ownership and lifetime

### Global player state

Global player state belongs to the existing save schema and whole-playthrough
services. It includes player identity, party, PC storage, bag, Pokédex, money,
play time, options, and other state whose meaning does not change with location.

Its lifetime is the save. New game initializes it once. Regional travel, regional
story entry, whiteout, checkpoint changes, and bootstrap profiles cannot replace,
copy, suspend, or bank it. A regional script may mutate global state through the
ordinary shared service that owns the mutation, such as a mart changing money
and bag contents or a PC operation changing party and box contents.

No regional subsystem may own a shadow player name, party, box collection, bag,
Pokédex, money balance, or playthrough clock.

### Geographic world state

Generated world metadata owns the region of every geographic map section. The
loaded map header owns current map and section. Current region is derived from
those authorities and lasts only until another map loads. It is never copied into
the save or maintained as a second volatile dispatch variable.

Persisted geographic facts name what survives a map change. These include the
current save location, checkpoint, visited or discovered destinations, durable
map mutations, and Pokémon provenance. The authored persistent-ID ledger and
the saved-location or met-location codecs own their physical bindings. Their
lifetimes are explicit:

- the save location changes when the game records another valid save location;
- the checkpoint changes only through a registered checkpoint or healer path;
- visited state lasts for the save unless its owning gameplay rule clears it;
- a durable world mutation lasts until its named reset rule clears it;
- a Pokémon's provenance lasts for that Pokémon record.

Map section, saved-location code, met-location code, checkpoint identity, and
visited identity remain separate domains. Direct casts and region-local offset
arithmetic are forbidden.

### Namespaced regional story facts

Regional stories use stable semantic facts under an explicit regional namespace.
Examples include a named badge, a chapter milestone, a one-time reward claim, or
a defeated story actor. The authored persistent-ID ledger owns each identity and
physical binding. The expansion event VM and ordinary script data remain the
writers.

Each fact declares its lifetime as permanent, chapter-scoped, daily, temporary,
or reset by one named rule. Region travel alone never clears or rewrites it.
Hoenn, Kanto, Sevii, and Johto facts may all be true at once. A script asks for
the exact fact it needs. It cannot ask which campaign is current and reinterpret
a shared slot.

Stable regional facts cannot derive their identities from array order, regional
badge position, the end of another range, or a product version. An ambiguous
legacy bit cannot be promoted into a regional story fact without evidence that
the old save actually established that story meaning.

### Derived player capabilities

A player capability is a semantic permission used by shared mechanics. Cut is
the first required fixture. Later mechanics add capabilities only when playable
content exercises them.

The derived-capability domain classifies the persisted regional facts and
mechanics-only grants that feed this decision. The capability result itself is
not another saved copy.

The capability resolver owns the answer. It reads named regional facts and any
published mechanics-only grants preserved from legacy saves. A capability is
derived at the point of use and lasts while its inputs remain true. The runtime
does not persist a second capability mirror merely to avoid the resolver.

Capability inputs have their own stable ledger bindings and lifetimes. A known
badge fact may grant a capability. An ambiguous legacy mechanics bit may retain
the capability without fabricating badge or story completion. Consumers cannot
inspect flat badge slots, current region, or `IS_FRLG` to decide permission.

If a future capability needs state that cannot derive safely, its RFC must name
the new saved fact, authority, lifetime, compatibility behavior, and physical
binding before implementation.

### Bounded facility state

A facility owns only the state needed for one named bounded service or session,
such as daycare deposits, Safari participation, or a League challenge. Its typed
registry and the frozen save contract own that state. Any new physical binding
comes from the persistent-ID ledger. Each facility contract states whether its
lifetime is permanent, active-session, daily, or reset by one named completion
or cancellation rule.

Facility state may refer to the global party or bag through shared APIs. It
cannot create a regional party, regional inventory, regional currency, campaign
save bank, or general-purpose alternate player state. Leaving a region does not
implicitly clear a facility unless the facility's own rule says that crossing a
validated boundary ends its session.

## State access rules

Every persisted read and write resolves through the authority for its domain.
Scripts may use generated bindings, but no script or service may invent a raw
numeric assignment. Generation and tests reject duplicate identities, moved
published bindings, invalid lifetimes, sentinel collisions, and use outside an
owner's storage domain.

Derived values are not competing authorities. Current region derives from the
loaded map. Player capabilities derive from named inputs. Display names derive
from registries. Generated output may cache or render these relationships, but
it remains replaceable evidence rather than authored truth.

A transition across a regional boundary changes only ordinary world position
and any named facts that the transition script explicitly owns. It cannot run a
generic region-entry reset over player, story, trainer, encounter, facility, or
service state.

## Location-neutral new-game bootstrap

New-game creation has two operations:

1. initialize the one global save schema and whole-playthrough defaults;
2. apply one start profile that selects the initial location, coordinates,
   facing direction, checkpoint, and optional expansion-native onboarding
   script.

The start profile is typed input to new-game setup, not saved campaign identity.
It is discarded after the initial spawn. Current region then derives from the
loaded map like every later location.

The current Hoenn start remains the sole production default and keeps its current
behavior. Milestone 5 may add Hoenn, Kanto, and Johto debug and E2E profiles that
all call the same global initialization path. Those profiles exist to test the
seam. They do not expose a player-facing origin selector and cannot skip required
global initialization.

An optional onboarding entry is an ordinary expansion-native script. The profile
cannot select another event VM, story framework, save initializer, party preset,
or region-specific runtime. A future player-facing origin feature must define
whether origin has durable gameplay meaning before it may persist anything.

## Regional stories and shared mechanics

Each regional story remains authored in expansion-native scripts with its own
stable facts. The state model does not create a generic quest graph, chapter
scheduler, or cross-campaign coordinator. Shared mechanics receive only the
facts or capabilities they need.

Regional stories may advance in any order allowed by their own gates. A Hoenn
script cannot suspend Kanto or Johto state, and a Johto script cannot make itself
the current campaign. Cross-region dialogue and reactions may read facts from
several namespaces in later work, but such reads do not create campaign
selection.

## Foundation continuity journey

Milestone 6 proves this contract with one ordinary, bidirectional journey. The
exact world closure is:

- `VermilionCity_Frlg`;
- `VermilionCity_PokemonCenter_1F_Frlg`;
- `VermilionCity_PortInside`;
- `OlivineCity_PortInside`;
- `OlivineCity_PortOutside`;
- `OlivineCity`;
- `OlivineCity_PokemonCenter`;
- `Route39`.

The journey starts with an existing character in Kanto. Before travel, the test
records player identity, party data, one boxed Pokémon, bag contents, money,
Pokédex state, representative regional story facts, checkpoint, and relevant
trainer state.

The player catches one Pokémon with the reviewed Vermilion Old Rod fixture,
travels through the Vermilion-to-Olivine gateway, and catches one Pokémon from
`gRoute39` or `gRoute39_Night` through the same region-neutral encounter
registry and existing time-selection callback. Both catches must retain their
identities and reviewed met-location provenance.

Only Sailor Eugene, `Route39_EventScript_Eugene` and `TRAINER_EUGENE`, is enabled
as the Route 39 trainer fixture. Baoba, the legendary event, Moomoo Farm,
pickups, berries, ambient actors, other trainers, and Route 39 story content stay
disabled. The player defeats Eugene through the ordinary trainer path. His
global identity and defeat state must prevent an unintended rematch before
travel, after the Johto cold restart, after the regional round trip, and after
the second cold restart.

In Olivine, the player heals through the ordinary nurse and registers the
`HEAL_LOCATION_OLIVINE_CITY` checkpoint. The player uses the shared
`EventScript_PC` path to withdraw the Pokémon boxed in Kanto and deposit the
Johto catch, saves in Johto, and cold-restarts. The test verifies global player
state, both regions' story facts, world state, checkpoint, and trainer defeat
before continuing.

The player then whites out to Olivine, returns to Kanto through ordinary
gameplay, uses a Kanto PC to withdraw the Johto catch and deposit the original
Pokémon, saves in Kanto, and cold-restarts again. The final assertions compare
the recorded player, party, PC, bag, money, Pokédex, story, checkpoint, visited,
trainer, and provenance state against each domain's declared mutations.

Every warp and connection in the closure works in both directions, including
both Pokémon Center entrances. The journey uses no test-only party swap, box
mutation, save rewrite, region setter, regional story-fact rewrite, alternate
runtime, or direct checkpoint mutation.

## Delivery milestones

### Milestone 3: unified-playthrough contract

Milestone 3 depends on the merged save-compatibility work in issue #20 and the
merged region-neutral import platform in issue #21. It lands this RFC and the
content-port amendment together. Its gate is documentary but exact: every state
domain has one authority and lifetime, bootstrap and continuity behavior are
settled, forbidden designs are recorded, and no foundation decision remains
open.

### Milestone 4: regional trainer runtime

[Milestone 4](https://github.com/mzpkdev/pokemon-openworld/issues/23) depends on
Milestone 3 and closes through its independently reviewed implementation PR. It
owns ordinary trainer identity, lookup, battle launch, defeat state, and rematch
authority. It does not own encounters, capabilities, bootstrap, checkpoints,
whiteout, travel, or bulk Johto content.

Its gate preserves every published Hoenn trainer binding, resolves all ordinary
trainers through one fail-closed registry, keeps FRLG rematch chains separate,
and proves Route 34 Samuel's defeat state through save and cold restart. Required
build, save-contract, integrity, content-port, and E2E checks must pass within
reviewed ROM and RAM budgets.

### Milestone 5: remaining shared playthrough primitives

[Milestone 5](https://github.com/mzpkdev/pokemon-openworld/issues/30) depends on
Milestone 4. It owns five bounded workstreams, each delivered through an
independently reviewable PR:

- a region-neutral wild encounter registry with exact Vermilion and Route 39
  fixtures;
- named regional facts and the Cut capability resolver;
- location-neutral bootstrap profiles;
- shared checkpoints, healing, and whiteout with Olivine as the Johto fixture;
- a round-trip Vermilion-to-Olivine gateway.

Each workstream preserves existing regional behavior and published save meaning.
Fixture parity tests pin encounter data before activation. Historical-save tests
prove that capability migration preserves mechanics without inventing story.
Bootstrap tests prove one global initializer. Checkpoint tests prove cross-region
whiteout. World-graph and E2E tests prove both gateway directions. The milestone
gate runs the required build, save-contract, integrity, and E2E checks within
reviewed budgets.

### Milestone 6: one-save Kanto-to-Johto continuity

[Milestone 6](https://github.com/mzpkdev/pokemon-openworld/issues/24) depends on
Milestone 5. It owns the exact continuity journey in this RFC and no bulk content
activation. The journey is the product gate for the unified-playthrough
foundation.

One E2E test must prove bidirectional travel, the Kanto and Johto catches, Sailor
Eugene, healing, real PC operations in both regions, whiteout, two saves, and two
cold restarts. Existing Hoenn, Kanto, and Sevii regressions remain green. Build,
save-contract, integrity, content-port, and E2E suites must pass within reviewed
ROM and RAM budgets.

Bulk non-story Johto production and story chapters remain blocked until
Milestone 6 passes.

## Runtime-gap rule

The old proof-slice rule prohibited all shared-engine changes during its three
content slices. Milestone 6 replaces that declaration gate with a runtime-gap
rule.

A shared-runtime change may enter Milestone 6 only when the exact continuity
journey exposes a concrete failure. The change must name the failing step, be
independently reviewable, preserve existing regional behavior, and remove the
shared failure through a typed property, capability, registry, or existing
ordinary runtime path. It cannot carry unrelated regional content.

A Johto-specific workaround, product-build branch, region dispatch, test-only
state mutation, or behavior-erasing donor shim does not satisfy the rule. The
shared fix lands separately before the journey resumes. If the failure requires
a save break, new runtime, or unresolved product decision, Milestone 6 stops and
requires a new RFC.

## Save compatibility

This RFC changes no save layout and assigns no numeric persistent binding.
Milestones 4 through 6 remain under the frozen save contract and authored
persistent-ID ledger.

A schema-neutral interpretation migration may land only when it is explicit,
versioned, idempotent, and covered by representative historical saves. It must
preserve the old mechanic without inventing unsupported regional story facts.
A compatible layout extension must preserve every published field and binding,
define checksum and budget effects, and prove upgrade behavior with historical
saves. Rejecting an existing save, moving a published binding, or changing its
meaning requires a separately approved breaking-save RFC and tested migration.

## Forbidden implementations

The following designs violate this RFC:

- a persisted or volatile `activeRegion` mirror used for ordinary dispatch;
- a persisted or volatile `currentCampaign`, campaign selector, or region-entry
  reset coordinator;
- regional party, PC, bag, Pokédex, money, player, or save-bank storage;
- automatic boxing, party replacement, inventory replacement, or state snapshot
  swap at a regional boundary;
- badge-slot, product-build, or current-region dispatch where a named fact,
  capability, or typed property expresses the question;
- regional copies of trainer, encounter, battle, healing, checkpoint, whiteout,
  PC, mart, field-move, event, or other shared runtime frontends;
- a bootstrap profile that skips global initialization, persists itself as
  campaign identity, or selects a second onboarding runtime;
- donor compatibility opcodes or shims that erase behavior and report success;
- a generic quest VM, campaign graph, or abstract story language layered over
  expansion-native scripts;
- test-only party, PC, save, region, story, checkpoint, or trainer mutations used
  to pass the continuity gate;
- a shared change justified by hypothetical later content rather than a failing
  milestone fixture or journey step.

## Validation and acceptance

Generation and host-side checks must prove:

- every persisted fact has one semantic identity, storage authority, and
  declared lifetime;
- current region derives only from the loaded map's generated metadata;
- independent regional facts coexist without a campaign selector;
- capability consumers resolve named capabilities and preserve ambiguous legacy
  mechanics grants without fabricating story facts;
- all start profiles use one global save initializer and the production profile
  retains the current Hoenn start;
- Milestones 4 and 5 meet their bounded test gates before Milestone 6 begins;
- the Milestone 6 journey proves the complete round trip and state witnesses;
- existing saves, published bindings, and fixed serialized layouts retain their
  meaning;
- all required repository checks pass within reviewed ROM, EWRAM, and IWRAM
  budgets.

This contract is complete when the RFC and its content-port amendment agree on
the delivery order, replacement of the three-slice gate, runtime-gap rule, and
bulk-import boundary with no unresolved foundation decision.

## Out of scope

- A player-facing region or city selector.
- Full Johto story implementation or bulk Johto content activation.
- Level scaling, campaign-order balancing, or trainer-party scaling.
- Cross-campaign dialogue and story reactions.
- Cross-region Fly, S.S. Aqua interiors, schedules, tickets, and travel story.
- A generic quest framework or general save-migration framework.

## Decision

Adopt one continuous save with five explicit state domains, map-derived region
context, coexisting regional story facts, derived player capabilities, bounded
facility state, and a location-neutral bootstrap seam. Prove the foundation with
the exact Kanto-to-Johto continuity journey after the trainer and shared-runtime
milestones land. Keep bulk Johto import behind that playable product gate.
