# Pokémon OpenWorld

Pokémon OpenWorld is a new Game Boy Advance ROM hack built on
[RHH's `pokeemerald-expansion`](https://github.com/rh-hideout/pokeemerald-expansion),
which in turn is based on [pret's `pokeemerald`](https://github.com/pret/pokeemerald).
The project uses the expansion engine as its technical foundation while developing
its own world, content, and gameplay direction.

This repository contains the source code and tooling needed to build its sole
product: one Emerald-engine `pokemon-openworld` ROM with Hoenn, mainland Kanto,
and Sevii resident. It does not expose FireRed, LeafGreen, or separate
region-specific product ROMs. You may only use ROM images in accordance with
the laws that apply to you.

## Releases

Once this release workflow is present on `main`, GitHub Releases publish the
complete `pokemon-openworld.gba` ROM together with its map and symbol files.
Successful `main` builds then produce public prerelease snapshots tagged
`build-<12-lowercase-hex>`, where the suffix is the start of the immutable
source commit SHA.

A maintainer can promote a snapshot to a stable release by manually running the
`Release` workflow with the snapshot's required `source` tag in
`build-<12-lowercase-hex>` form. Promotion reuses the snapshot's verified files
byte for byte and publishes the stable release as latest; it does not rebuild or
retarget either tag.

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

The canonical emulator input is the isolated debug pair:

```sh
make -j"$(nproc)" -O DEBUG=1 \
  pokemon-openworld-debug.gba pokemon-openworld-debug.sym
```

Validate deterministic generation, manifest/schema integrity, linked pointers,
ABI sentinels, and the ROM/EWRAM/IWRAM capacity contract with:

```sh
python3 -m unittest discover -s tools/mapjson/tests -p 'test_*.py'
make integrity-check
make e2e-integrity
```

`make integrity-check` writes the machine-readable linked-artifact and
capacity report to `build/integrity/artifact-report.json`. The Integrity E2E
suite writes failure evidence under `test-results/e2e/integrity/`. See
[the E2E guide](tools/e2e/README.md) for the exact residency contract.

Here, **resident** means every registered Hoenn, mainland Kanto, and Sevii map
has complete structural data and can initialize. **Field-ready** is the stronger
representative-map proof that normal scripts/events run and player control is
restored. Neither term promises inter-region travel, Fly routing, story
progression, or finished Kanto/Sevii story content; those behaviors are outside
this milestone.

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
