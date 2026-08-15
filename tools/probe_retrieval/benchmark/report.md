# Probe retrieval benchmark report

Status: no-go. Keep Probe experimental and disabled by default.

## Method

The frozen ten-task corpus ran at clean revision
`095566f823409fb8806ac8e18bb999a45d4ef450`. Every pair used Codex with `gpt-5.4`, low
reasoning, a read-only sandbox, and an ephemeral session. The task prompt was unchanged
within each pair. The condition instruction either prohibited Probe and allowed standard
bounded tools, or required the confined wrapper where its format support applied.

Pair order alternated between control-first and Probe-first. Probe session caching was
disabled. Operating-system filesystem caches and server prompt caching remained enabled
for both conditions, and the latter is reported from each `turn.completed` JSON event.

The lossless `raw-results.tar.gz` archive retains all 20 JSONL event streams, all 20
stderr logs, the complete unabridged result document, the exact runner, the answer schema,
and a SHA-256 manifest for its 43 files. The archive is 1,095,438 bytes and has SHA-256
`4b88ece933c7c066baaa7e7cc1d337b45ce8714fb9c6e4855deab60a60861fc4`.

Cold and warm wrapper smoke tests are separate from the model benchmark. They use fresh
Probe processes without Probe session caching, with the warm process started immediately
after the cold process.

## Token telemetry limitation

`codex exec --json` reported `input_tokens`, `cached_input_tokens`, `output_tokens`,
`reasoning_output_tokens`, and `cache_write_input_tokens`. It did not report billed
tokens, account cost, or a billing conversion for cached tokens. Exact billed-token
telemetry was therefore unavailable, and this report does not label any derived value as
billed usage.

For comparison, `uncached input` below is `input_tokens - cached_input_tokens`. The
required gate still fails under the most favorable possible proxy: even if cached input
and all output were treated as free, uncached input fell by only 15.2%, short of the 20%
requirement. Every reported category omitted by that proxy moved against Probe.

## Aggregate results

| Metric | Control | Probe | Probe change |
| --- | ---: | ---: | ---: |
| Input tokens | 2,366,121 | 3,918,948 | +65.6% |
| Cached input tokens | 1,953,792 | 3,569,152 | +82.7% |
| Uncached input tokens | 412,329 | 349,796 | -15.2% |
| Output tokens | 23,572 | 33,042 | +40.2% |
| Reasoning output tokens | 2,936 | 6,119 | +108.4% |
| Tool rounds | 142 | 208 | +46.5% |
| Wall latency | 562.892 s | 825.140 s | +46.6% |
| Codex execution failures | 0 | 0 | no change |
| Correct task outcomes | 9/10 | 10/10 | +1 task |

## Per-task results

| Task | Control input / cached | Probe input / cached | Control / Probe rounds | Control / Probe latency | Correctness |
| --- | ---: | ---: | ---: | ---: | --- |
| Field moves | 132,579 / 88,064 | 477,118 / 424,192 | 8 / 20 | 40.740 / 84.741 s | pass / pass |
| Bundle performance | 338,411 / 276,992 | 485,112 / 436,352 | 19 / 30 | 69.356 / 110.206 s | pass / pass |
| Encounter registry | 278,544 / 231,168 | 649,248 / 605,568 | 14 / 41 | 59.879 / 137.858 s | pass / pass |
| Aqua presentation | 282,948 / 239,232 | 619,221 / 570,240 | 20 / 31 | 71.090 / 108.278 s | fail / pass |
| Night palettes | 551,474 / 454,656 | 689,847 / 630,528 | 23 / 13 | 88.066 / 94.387 s | pass / pass |
| Trainer runtime | 318,529 / 271,872 | 434,614 / 390,912 | 22 / 27 | 71.203 / 99.679 s | pass / pass |
| Stable identities | 168,025 / 139,008 | 211,046 / 191,872 | 18 / 19 | 59.891 / 64.454 s | pass / pass |
| Content-port authority | 170,848 / 133,504 | 230,742 / 203,776 | 13 / 22 | 43.824 / 67.248 s | pass / pass |
| Check selection | 94,934 / 90,880 | 31,203 / 28,416 | 4 / 1 | 38.940 / 24.790 s | pass / pass |
| Sibling confinement | 29,829 / 28,416 | 90,797 / 87,296 | 1 / 4 | 19.903 / 33.499 s | pass / pass |

Correctness and required evidence were reviewed against the cited repository paths and
line ranges. The control Aqua answer described the Vermilion terminal's locked and
unlocked states but did not cover both S.S. Aqua berth states requested by the frozen
task. The Probe answer covered both berths. No Probe answer regressed correctness or
required evidence relative to its control.

## Gate decision

The adoption gate does not pass. Exact billed usage is unavailable, the favorable
uncached-input proxy improves by less than 20%, and total input, output, reasoning output,
tool rounds, and latency all increase materially. One narrow test-selection task improved,
but the aggregate does not support repository guidance or automatic agent adoption.

Keep the checksum-pinned bootstrap, confined wrapper, tests, corpus, and this no-go result
as an evidence-backed experimental spike. Do not enable Probe in agent startup, normal
builds, tests, or CI. Any renewed evaluation needs a reviewed Probe version or a measured
change to the wrapper invocation guidance, plus a complete rerun of the frozen corpus.
