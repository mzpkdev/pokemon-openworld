# Headless end-to-end smoke test

`make e2e-smoke` builds `pokeemerald-e2e.gba` in its own object directory and
runs it with the repository's bundled `mgba-rom-test` binary.

The E2E build uses the real `ReadKeys` path, but replaces hardware input with a
small deterministic tape. It waits until `CB2_InitTitleScreen` has executed,
alternates SELECT press/release frames to activate Quickstart, and passes only
after `CB2_Overworld` becomes active. The ROM logs the milestone and exits via
SWI 3 with status in r0; an in-ROM frame deadline exits nonzero. Production ROM
builds compile the hook out because `E2E_TESTING` defaults to `0`.
