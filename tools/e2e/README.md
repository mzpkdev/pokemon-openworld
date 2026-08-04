# Headless E2E playthroughs

`make e2e-core` runs the fast local smoke suite. `make e2e-extended` runs
heavy, niche, and historical regressions; an empty extended suite succeeds with
an explicit `0 tests` message. There is no aggregate E2E target.

On Debian or Ubuntu, install the ROM build prerequisites first:

```sh
sudo apt install build-essential binutils-arm-none-eabi gcc-arm-none-eabi \
  libnewlib-arm-none-eabi libpng-dev python3-venv
```

Tests are pytest files under `tools/e2e/tests/<suite>/`. Each test receives a
fresh `game` fixture with `press`, `step`, `read`, `read_u32`, `callback_is`, and
`wait_for_callback` helpers. The fixture copies the ROM and starts one pinned
SkyEmu v5 process, so saves and RAM cannot leak between tests.

The first run creates the ignored `build/e2e-venv` and downloads the
digest-checked emulator into `build/e2e-tools`. Each test gives SkyEmu isolated
XDG settings that keep its HTTP mode truly headless. Failed tests write
screenshots, states, and logs below `test-results/e2e/<suite>/`.

The SkyEmu v5 Linux archive and extracted executable are both checked against
the fixed SHA-256 digests in `install_skyemu.py` before installation.
