# Headless E2E playthroughs

`make e2e-core` runs the fast local smoke suite. `make e2e-extended` runs
heavy, niche, and historical regressions. The extended suite currently plays
from Quickstart through receiving the Pokédex. `make e2e-integrity` proves the
four-region residency contract described below. There is no aggregate E2E
target; each suite runs independently.

On Debian or Ubuntu, install the ROM build prerequisites first:

```sh
sudo apt install build-essential binutils-arm-none-eabi gcc-arm-none-eabi \
  libnewlib-arm-none-eabi libpng-dev python3-venv
```

Each suite first refreshes the canonical debug ROM and symbols through the
ordinary debug Make dependency graph. You can still build them explicitly:

```sh
make -j"$(nproc)" -O DEBUG=1 \
  pokemon-openworld-debug.gba pokemon-openworld-debug.sym
```

The suite targets never publish a ROM. They verify that those two files exist
after the dependency-graph build and fail with a preparation command if the
build did not produce them. CI alone uses its same-commit debug artifact from
the required build job instead of rebuilding it in every E2E matrix job. Run
the Integrity suite with:

```sh
make e2e-integrity
```

Integrity uses the generated manifest to structurally initialize every
registered Hoenn, mainland Kanto, Sevii, and Johto map. That is the meaning of
**resident**: the map and its required header, layout, tileset, events, scripts,
connections, section metadata, codecs, and callbacks are present and can be
initialized. Representative full loads also prove **field-ready**: normal map
scripts and events run, the expected map is active, scripts settle, and player
control returns. Structural loads suppress story scripts and events only during
the exhaustive sweep; representative loads restore them.

Pull-request CI limits the structural sweep to every exterior map with a
Pokémon Center entrance across Hoenn, Kanto, Johto, and the seven Sevii
Islands, plus the three starting towns. Local `make e2e-integrity` keeps the
exhaustive sweep by default; set `E2E_MAP_SWEEP=frontages` to match CI.

Johto residency is deliberately non-gameplay: imported scripts and gameplay
events are empty, while load-critical layouts, tilesets, sections, headers, and
internal spatial edges remain. It does not provide NPCs, dialogue, trainers,
encounters, trades, services, items, HM/key-item gates, daycare, healing, League
gameplay, progression, Fly routing, or region switching. HnS supplies Johto
content except for the importer-enforced 14-map PKMN-World fallback whose maps
are absent from the pinned HnS authority. These checks do not promise travel
between regions or a complete playable regional story. Failed runs
write per-map screenshots, states, and logs under
`test-results/e2e/integrity/`.

Save-lifecycle regressions use only the canonical debug ROM and symbol pair.
They drive the real start-menu Save action, wait for the 128 KiB battery image
to change and become a complete checksum-valid flash save, terminate the old
SkyEmu process, prove it exited, and cold-start a new process with fresh RAM and
XDG configuration against the same copied ROM and `game.sav`. Process shutdown
is not treated as a save flush and does not require the battery file to change.

`fixtures/hoenn_continue.json` binds the historical Continue fixture to its
SHA-256 and source commit. Its expectations were obtained by direct parsing of
the fixture already committed at that source revision, before this build could
interpret it. The regression asserts those semantics in RAM before resaving,
in the rewritten battery image, and again after a cold restart.

`fixtures/hoenn_populated.json` was generated from a clean `135b32ca92`
source export with the manifest-recorded DEBUG instrumentation patch. The
generator uses normal game services to create a party Pokémon, boxed Pokémon,
compatible daycare pair and pending egg, in-game trade, bag reward, checkpoint,
paused Battle Tower challenge, and defeated trainer, then drives the field
Start-menu Save twice to replace both rotating flash slots and exclude stale
pre-scenario Quickstart entropy. Its manifest records the instrumentation, ROM, and save
digests plus independently decoded Pokémon provenance and representative state.
From a clean repository with the normal E2E dependencies installed, reproduce
the complete export → checked overlay → historical build → gameplay → Save
pipeline with one command:

```sh
build/e2e-venv/bin/python -m tools.e2e.generate_populated_fixture \
  --source-tree . \
  --skyemu build/e2e-tools/SkyEmu-v5 \
  --output tools/e2e/fixtures/hoenn_populated.json
```

The generator rejects any change to the tracked instrumentation overlay or the
resulting historical ROM before launching the emulator. It then verifies the
complete save digest, captured raw SaveBlock ranges, and decoded meanings
against the immutable, hand-reviewed `fixtures/hoenn_populated_oracle.json`;
the generator never derives or rewrites that oracle. The save and manifest are
staged, reparsed, and published only after every validation succeeds, so a
failed reproduction cannot leave the tracked fixture pair inconsistent.

The fresh-save regression constructs equivalent representative state through
the shipped DEBUG request/result hook, asserts it in RAM and the flash image,
and proves it survives a cold restart. The hook's status byte is committed last
so the game cannot consume a partially written request.

Tests are pytest files under `tools/e2e/tests/<suite>/`. Each test receives a
fresh `game` fixture with frame/input controls, memory and symbol access,
story flag and variable helpers, and coordinate-aware overworld movement. The
fixture copies the ROM and starts one pinned SkyEmu v5 process, so saves and RAM
cannot leak between tests.

`fixtures/regional_cut_oracle.json` records the Cut result produced by an
instrumented `135b32ca92` ROM for four checksum-valid variants of the reviewed
historical Continue fixture: neither legacy badge slot, slot 1, slot 2, and
both. Tests derive those variants instead of tracking opaque binary copies. The
manifest binds the base save, minimal DEBUG probe overlay, and historical ROM
by SHA-256. Reproduce it with:

```sh
build/e2e-venv/bin/python -m tools.e2e.generate_cut_oracle \
  --source-tree . --skyemu build/e2e-tools/SkyEmu-v5
```

For intentional review, pass `--candidate-output`; the generator marks that
capture unreviewed and never overwrites the oracle.

The Pokédex journey follows the gender-dependent opening route selected by
Quickstart, disables random wild encounters through the debug ROM flag, and
uses the battle debug menu's Instant Win only after proving that the Route 103
rival battle started. Its milestone assertions cover the clock, rival
introduction, Birch rescue, starter and first battle, Route 103 victory, and
final Pokédex story state.

The first run creates the ignored `build/e2e-venv` and downloads the
digest-checked emulator into `build/e2e-tools`. Each test gives SkyEmu isolated
XDG settings that keep its HTTP mode truly headless. Failed tests write
`game.sav`, `screen.png`, `game.state`, and `skyemu.log` below
`test-results/e2e/<suite>/`, for both ordinary and fixture-backed sessions. If
an emulator endpoint prevents one artifact from being captured,
`capture-errors.txt` records that failure without suppressing the remaining
evidence.

The SkyEmu v5 Linux archive and extracted executable are both checked against
the fixed SHA-256 digests in `install_skyemu.py` before installation.
