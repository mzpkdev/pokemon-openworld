# Pokémon OpenWorld

Pokémon OpenWorld is a new Game Boy Advance ROM hack built on
[RHH's `pokeemerald-expansion`](https://github.com/rh-hideout/pokeemerald-expansion),
which in turn is based on [pret's `pokeemerald`](https://github.com/pret/pokeemerald).
The project uses the expansion engine as its technical foundation while developing
its own world, content, and gameplay direction.

This repository contains the source code and tooling needed to build the ROM
locally. You may only use ROM images in accordance with the laws that apply to
you.

## Build and setup

See [INSTALL.md](INSTALL.md) for supported development environments and build
commands. A standard build produces `pokemon-openworld.gba`:

```console
make
```

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
