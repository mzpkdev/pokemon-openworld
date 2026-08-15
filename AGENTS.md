# Repository instructions

## Commands

Run Make from the repository root. Add `-j"$(nproc)" -O` to compiled targets when you want parallel, grouped output.

### Choosing checks efficiently

Keep the existing build tree: Make's dependency graph is the fastest way to reuse generated files, host tools, and objects. Do not run `make clean` unless investigating a stale-output bug. Do not use `make -n` or `make -q` to inspect these targets: parsing can perform setup work, recursive `$(MAKE)` recipes still run under `-n`, and `-q` reports ordinary out-of-date targets as failure. Inspect the recipe directly or use the focused Make contract tests instead.

While iterating, run the narrowest test that owns the changed behavior, then run its Make target before handoff:

- For one Python unittest module or test, use `python3 -m unittest <dotted.module>[.<Class>.<test>] -v`. For pytest-based tests, use `python3 -m pytest <path>[::<test>] -q`.
- For Python changes, run the focused test first, then `make format-check lint-check`.
- For workflow changes, run `actionlint <changed-workflow-files>`. Also run `.github/release/release.py self-test` when changing release workflows or helpers.
- For Makefile command orchestration, run the focused tests in `tools.mapjson.tests.test_make_isolation`, then the smallest artifact or check target affected by the change.
- For Pokemon OpenWorld mechanics C changes, start with `make -j"$(nproc)" -O product-check`.
- For ROM, linker, generated-data, or shared-header changes, start with `make -j"$(nproc)" -O debug-check`, which matches the PR build purpose. Add `integrity-check` when normal-build behavior can differ and `release-check` only when release flags, optimization, capacity, or release-only behavior can differ.
- Run E2E only for behavior that needs emulator evidence. Start with `e2e-core`; add the sampled or full integrity suite only when regional traversal or integrity coverage requires it.
- Always run `git diff --check` before committing. Documentation-only changes normally need no ROM build.

Escalate to `make check` only when shared or inherited engine behavior may be affected, and to `make integrity-check-rom-purposes` only when the change can differ across normal, debug, and release purposes. Record any intentionally skipped expensive check in the PR description.

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
- `make agent-test` runs the bounded agent-interface contract tests.

## Product-owned C tests

Place Pokemon OpenWorld-owned C tests under `test/openworld/`. Do not add them to inherited RHH test directories or root test files unless an upstream test must change for compatibility.

Use `make product-check` for the required product test tier. Keep Pokemon OpenWorld-owned C tests under `test/openworld/`; `make check` remains the explicit complete local suite.

## Bounded agent interface

Use `python3 -m tools.agent context` for compact changed-path classification and check recommendations. The default compares the staged, unstaged, untracked, and renamed working tree to `HEAD`; use `--base <revision>` or repeated `--path <path>` arguments to select another input set. Semantic `--impact` flags only add coverage.

Use `python3 -m tools.agent query <map|trainer|persistence|content-port> <key>` to retrieve matching records with their authoritative source paths and locations. Use `python3 -m tools.agent check <check-id>` to run a reviewed check. `python-unittest` and `python-pytest` require `--selector`; `actionlint` requires one or more exact `--workflow` paths. Add `--text` to any command for concise text instead of JSON.

The machine-readable check registry at `tools/agent/registry.json` is the routing authority. It preserves the iteration, required handoff, and conditional escalation boundaries above. Check logs and metadata are retained under ignored `build/agent-logs/`.
