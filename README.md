# Pokémon OpenWorld

Pokémon OpenWorld is a new Game Boy Advance ROM hack built on
[RHH's `pokeemerald-expansion`](https://github.com/rh-hideout/pokeemerald-expansion),
which in turn is based on [pret's `pokeemerald`](https://github.com/pret/pokeemerald).
The project uses the expansion engine as its technical foundation while developing
its own world, content, and gameplay direction.

This repository contains the source code and tooling needed to build its sole
product: one Emerald-engine `pokemon-openworld` ROM with Hoenn, mainland Kanto,
Sevii, and Johto resident. It does not expose FireRed, LeafGreen, or separate
region-specific product ROMs. You may only use ROM images in accordance with
the laws that apply to you.

## Releases

Once this release workflow is present on `main`, GitHub Releases publish the
normal `pokemon-openworld.gba` ROM together with its map and symbol files, plus
`pokemon-openworld-debug.gba` without its debug symbols. Successful `main`
builds then produce public prerelease snapshots tagged
`build-<12-lowercase-hex>`, where the suffix is the start of the immutable
source commit SHA.

A maintainer can promote a snapshot to a stable release by manually running the
`Release` workflow with the snapshot's required `source` tag in
`build-<12-lowercase-hex>` form. Promotion reuses the snapshot's verified files
byte for byte and publishes the stable release as latest; it does not rebuild or
retarget either tag.

Only snapshots created under this four-asset release contract are eligible for
stable promotion. Legacy snapshots containing only the normal ROM, map, and
symbol files remain immutable and cannot be promoted; the workflow does not
reconstruct or repair them from expired CI artifacts.

The workflow assigns the first stable release `v0.0.0`. After that it calculates
the next version from Conventional Commits since the highest reachable stable:
a breaking change bumps the major version, otherwise a `feat` bumps the minor
version, and all other changes bump the patch version. Rerunning promotion for a
snapshot already released as stable reuses that stable version.

Snapshot notes cover the source commit, while stable notes cover the commits
since the highest earlier published stable release whose SemVer tag is reachable
from the promoted source. Both are generated from Conventional Commit messages
and link the published files back to their source commit and CI origin.

## Build and setup

See [INSTALL.md](INSTALL.md) for supported development environments. The sole
normal product build emits `pokemon-openworld.gba`, `pokemon-openworld.map`, and
`pokemon-openworld.sym`:

```sh
make -j"$(nproc)" -O emerald syms
```

GitHub releases contain those three normal-build files plus
`pokemon-openworld-debug.gba`. The canonical emulator input for E2E remains the
isolated debug pair (the debug `.sym` is a CI artifact, not a release asset):

```sh
make -j"$(nproc)" -O DEBUG=1 \
  pokemon-openworld-debug.gba pokemon-openworld-debug.sym
```

Validate deterministic generation, manifest/schema integrity, linked pointers,
ABI sentinels, and the ROM/EWRAM/IWRAM capacity contract with:

```sh
python3 -m unittest discover -s tools/mapjson/tests -p 'test_*.py'
python3 -m unittest discover -s tools/persistence/tests -p 'test_*.py'
make save-contract-check
make integrity-check
make -j"$(nproc)" -O integrity-check-all-purposes
make e2e-integrity
```

`make save-contract-check` measures the current ARM ABI and compares it with the
frozen contract. `make integrity-check` writes the current normal, debug, or
release linked-artifact report to `build/integrity/<purpose>.json`.
`make integrity-check-all-purposes` replaces
`build/integrity/purposes/` with exactly five reports: `normal.json`,
`debug.json`, `release.json`, `test-runner.json`, and `headless-test.json`. Each
records the save-contract digest and capacity evidence, and all five validate
their own purpose-specific linked target-compiler ABI table. The Integrity E2E
suite writes failure evidence under `test-results/e2e/integrity/`. See
[the E2E guide](tools/e2e/README.md) for the exact residency contract.

## Content ports

Content ports use public donor checkouts and an authored policy. Prepare the
current Johto authorities at their pinned commits without storing credentials:

```sh
git clone --no-checkout https://github.com/PokemonHnS-Development/pokemonHnS \
  .references/pokemonHnS
git -C .references/pokemonHnS checkout \
  751823abaf677020bcd72c45fe3e7cb2b8a576e4
git clone --no-checkout https://github.com/evilchinesefood/PKMN-World \
  .references/PKMN-World
git -C .references/PKMN-World checkout \
  d40affe26e58a20f445daad84af5e45be812e69f
make content-port-test
make content-port-check
```

`make content-port-bundle` authenticates both trees and writes the deterministic
Johto bundle under `build/content-port/johto/`. Review its patch, ownership
manifest, report, and printed SHA-256 before applying it:

```sh
content_port_bundle_sha256="$(make -s content-port-bundle)"
[[ "$content_port_bundle_sha256" =~ ^[0-9a-f]{64}$ ]] || exit 1
python3 -m tools.content_port apply --repo . \
  --bundle build/content-port/johto \
  --sha256 "${content_port_bundle_sha256:?}"
```

An interrupted apply leaves an active transaction guard. Every build, test,
integrity, and content-port target refuses that mixed tree until one of these
commands verifies the transaction and clears it:

```sh
python3 -m tools.content_port resume --repo .
python3 -m tools.content_port recover --repo .
```

To propose a donor pin, run `donor-update` with the donor key (`content` or
`mechanical`), proposed revision, and
`--output build/content-port/johto/donor-migration.json`. Review every field-level
authority change, asset hash, conversion command, license or permission, and
capability state. Only `redistributable` assets pass. Commit the content-addressed
reviewed migration with its matching policy change. After setting its decision
and dispositions, run `migration-finalize --candidate
build/content-port/johto/donor-migration.json --port-dir
tools/content_port/ports/johto`; it writes the canonical reviewed record and an
exact `donor-port-update.json` proposal without editing `port.json`. The tool
never moves a branch or creates a commit; only the resulting reviewed Git commit
publishes generated output.

The five baseline-usage records are reproducibly measured from the frozen commit
in an exported clean tree (never from the current worktree) with:

```sh
python3 tools/persistence/contract.py seed-budgets \
  --baseline b47a41e9e4635cc40a8003249f9425578e257e1e \
  --contract tools/integrity/save_contract.json \
  --rom-max 33554432 --ewram-max 262144 --iwram-max 32768 \
  --release-rom-headroom-min 2708917
```

Here, **resident** means every registered Hoenn, mainland Kanto, Sevii, and Johto map
has complete structural data and can initialize. **Field-ready** is the stronger
representative-map proof that normal scripts/events run and player control is
restored. Johto is a load-critical spatial shell: its imported NPCs, dialogue,
trainers, encounters, trades, services, items, HM/key-item gates, daycare,
healing, League gameplay, progression, Fly routing, and region switching are not
part of this milestone. HnS is the Johto content authority; exactly 14 maps absent
from its pinned tree use the bounded PKMN-World fallback recorded by the importer.
No residency claim promises inter-region travel or finished regional stories.

## Project reference

- [Engine capabilities](FEATURES.md) — inherited capabilities available to the
  project; inclusion does not mean every capability is enabled or used in-game.
- [Credits](CREDITS.md) — upstream contributors, asset creators, and other source
  acknowledgements retained by this fork.
- [Installation and maintenance](INSTALL.md) — toolchain setup, builds, and a
  cautious workflow for incorporating upstream engine updates.

## Upstream attribution

Pokémon OpenWorld's imported base (commit `b67210fdf9`) identifies itself as an
untagged `pokeemerald-expansion` 1.16.4 development snapshot, after the 1.16.3
release. Please preserve the RHH and pret attribution, the repository's license
notices, and the individual credits in [CREDITS.md](CREDITS.md) when
redistributing derived work.
