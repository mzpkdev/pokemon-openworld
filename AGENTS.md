# Repository instructions

## Commands

Run Make from the repository root. Add `-j"$(nproc)" -O` to compiled targets when you want parallel, grouped output.

### Build artifacts

- `make normal-artifacts` builds the normal `.gba`, `.map`, and `.sym` files.
- `make debug-artifacts` builds the debug `.gba`, `.map`, and `.sym` files used by PR checks and E2E tests.
- `make snapshot-artifacts` builds both variants and stages the exact four publishable files under `build/snapshot/`. Set `SNAPSHOT_DIR=<path>` to use another staging directory.
- `make release` builds the optimized release-purpose ROM. This variant is audited but is not part of the published snapshot inventory.

### Focused checks

- `make product-check` runs the required Pokemon OpenWorld-owned C test tier.
- `make check` runs the complete C suite, including inherited RH-Hideout coverage.
- `make integrity-check` builds and audits the normal ROM.
- `make debug-check` builds and audits the debug ROM.
- `make release-check` builds and audits the optimized release-purpose ROM.
- `make integrity-check-rom-purposes` audits normal, debug, and release-purpose ROMs.
- `make audit-prebuilt-debug` audits debug artifacts under `build/debug-prebuilt/`.
- `make audit-prebuilt-artifacts` audits normal artifacts under `build/prebuilt/` and debug artifacts under `build/debug-prebuilt/`. Override `PREBUILT_NORMAL_DIR`, `PREBUILT_DEBUG_DIR`, or `PREBUILT_REPORT_DIR` when needed.

### End-to-end checks

- `make e2e-core` runs the short runtime suite.
- `make e2e-integrity` runs the sampled regional integrity suite.
- `make e2e-integrity-full` runs the full regional sweep.
- `make e2e-extended` runs the optional extended suite.

The E2E targets build fresh debug artifacts locally. `E2E_PREBUILT_DEBUG=1` is reserved for CI jobs that downloaded artifacts produced for the same commit.

### Source and policy checks

- `make format-check` checks Python formatting; `make format` applies it.
- `make lint-check` checks Python lint; `make lint` applies safe fixes.
- `make content-port-transaction-check` rejects unfinished content-port transactions.
- `make content-port-ownership-check` validates imported-content ownership.
- `make content-port-test` runs content-port unit tests.
- `make content-port-check` validates policy and authenticates the configured donors.
- `make content-port-bundle` builds the configured donor-backed content bundle.
- `make wild-encounter-test` runs wild-encounter generator tests.

## Product-owned C tests

Place Pokemon OpenWorld-owned C tests under `test/openworld/`. Do not add them to inherited RHH test directories or root test files unless an upstream test must change for compatibility.

Use `make product-check` for the required product test tier. Keep Pokemon OpenWorld-owned C tests under `test/openworld/`; `make check` remains the explicit complete local suite.
