# Bounded Probe retrieval

This package is an experimental, read-only wrapper around the standalone Probe CLI.
It does not install or expose Probe MCP, Agent, LSP, editing, delegation, shell, or model
provider features.

The frozen benchmark is a no-go for adoption. Exact billed-token telemetry was unavailable,
and the most favorable uncached-input proxy improved by only 15.2% while total input,
output, tool rounds, and latency increased. See `benchmark/report.md`. Keep the helper
disabled by default.

## Install

Linux x86_64 is the only reviewed target. From the active worktree root, run:

```sh
python3 -m tools.probe_retrieval.bootstrap
```

The explicit bootstrap downloads Probe `v0.6.0-rc331` into
`.cache/probe/v0.6.0-rc331/x86_64-unknown-linux-musl/`. It verifies the repository-recorded
archive SHA-256 before extraction. The wrapper also verifies the extracted executable's
SHA-256 before every execution. The cache is ignored and is not part of normal setup,
builds, tests, CI, or agent startup.

To install the same archive without network access, download it separately and pass
`--archive PATH`. The checksum remains mandatory.

The reviewed archive is
`probe-v0.6.0-rc331-x86_64-unknown-linux-musl.tar.gz` from the upstream
[`v0.6.0-rc331` release](https://github.com/probelabs/probe/releases/tag/v0.6.0-rc331).
Its SHA-256 is `404a10ca8f1e28cdae13855883d632b79be1d85a692eb35db33627268629fee4`.
The archive ships an Apache License 2.0 file with SHA-256
`793b7448f5beb1535d9197bd3d2fd2f167c22322e3457465eec50159d96d7858`.
This evidence applies to the standalone artifact, not the npm package.

## Use

The wrapper accepts repository-relative paths and emits compact, stable JSON:

```sh
python3 -m tools.probe_retrieval.cli search 'checkpoint OR heal' --language c --path src
python3 -m tools.probe_retrieval.cli symbols tools/content_port/worktree.py
python3 -m tools.probe_retrieval.cli extract tools/content_port/worktree.py --symbol repository_root
python3 -m tools.probe_retrieval.cli extract tools/content_port/worktree.py --start-line 51 --end-line 59
```

Search, symbol listing, and symbol extraction report `"retrieval":"ast"`. A bounded line
range reports `"retrieval":"text_fallback"`. The wrapper rejects absolute paths, parent
traversal, symlink escapes, ignored output, unsupported formats, oversized files, and
whole-file extraction. It applies fixed process, raw-output, result, code-byte, token,
source-size, and serialized-response limits.

Repository searches receive a fixed 30-second Probe budget. The wrapper allows two more
seconds only for the child process to flush bounded output and exit. Callers cannot raise
either limit. The complete serialized response remains capped at 32 KiB, Probe code
content at 20 KiB, raw child output at 1 MiB, and individual source files at 512 KiB.

The repository-scale integration test defines a cold run as the first fresh Probe process
for a query and a warm run as an immediate second fresh process, with operating-system
filesystem caches left intact. Probe session caching is not enabled in either run. Run it
after the explicit bootstrap with `make probe-retrieval-integration-test`.

Use `rg` for exact text. Use `rg` and bounded file reads for `.inc`, `.s`, `.json`,
generated data, oversized files, and all other unsupported formats. Directory search is
limited to one requested AST language, but it is not a claim of semantic coverage for the
whole repository.

## Upgrade policy

An upgrade needs a reviewed immutable release asset, updated archive and executable
checksums, updated compatibility fixtures, license evidence for that artifact, and a new
paired benchmark. Do not replace the pinned version with `@latest`, `npx`, an npm
postinstall, or the upstream provider dependency graph.
