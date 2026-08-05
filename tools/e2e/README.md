# Headless E2E playthroughs

`make e2e-core` runs the fast local smoke suite. `make e2e-extended` runs
heavy, niche, and historical regressions. The extended suite currently plays
from Quickstart through receiving the Pokédex. `make e2e-integrity` proves the
three-region residency contract described below. There is no aggregate E2E
target; each suite runs independently.

On Debian or Ubuntu, install the ROM build prerequisites first:

```sh
sudo apt install build-essential binutils-arm-none-eabi gcc-arm-none-eabi \
  libnewlib-arm-none-eabi libpng-dev python3-venv
```

Prepare the canonical debug ROM and symbols separately before running any suite:

```sh
make -j"$(nproc)" -O DEBUG=1 \
  pokemon-openworld-debug.gba pokemon-openworld-debug.sym
```

The E2E suite targets never compile or publish a ROM. They require those two
files in the repository root and fail with a preparation command if either is
missing. Run the Integrity suite with:

```sh
make e2e-integrity
```

Integrity uses the generated manifest to structurally initialize every
registered Hoenn, mainland Kanto, and Sevii map. That is the meaning of
**resident**: the map and its required header, layout, tileset, events, scripts,
connections, section metadata, codecs, and callbacks are present and can be
initialized. Representative full loads also prove **field-ready**: normal map
scripts and events run, the expected map is active, scripts settle, and player
control returns. Structural loads suppress story scripts and events only during
the exhaustive sweep; representative loads restore them.

These checks do not implement or promise travel between regions, Fly routing,
story progression, or a complete playable story in Kanto or Sevii. Failed runs
write per-map screenshots, states, and logs under
`test-results/e2e/integrity/`.

Tests are pytest files under `tools/e2e/tests/<suite>/`. Each test receives a
fresh `game` fixture with frame/input controls, memory and symbol access,
story flag and variable helpers, and coordinate-aware overworld movement. The
fixture copies the ROM and starts one pinned SkyEmu v5 process, so saves and RAM
cannot leak between tests.

The Pokédex journey follows the gender-dependent opening route selected by
Quickstart, disables random wild encounters through the debug ROM flag, and
uses the battle debug menu's Instant Win only after proving that the Route 103
rival battle started. Its milestone assertions cover the clock, rival
introduction, Birch rescue, starter and first battle, Route 103 victory, and
final Pokédex story state.

The first run creates the ignored `build/e2e-venv` and downloads the
digest-checked emulator into `build/e2e-tools`. Each test gives SkyEmu isolated
XDG settings that keep its HTTP mode truly headless. Failed tests write
screenshots, states, and logs below `test-results/e2e/<suite>/`.

The SkyEmu v5 Linux archive and extracted executable are both checked against
the fixed SHA-256 digests in `install_skyemu.py` before installation.
