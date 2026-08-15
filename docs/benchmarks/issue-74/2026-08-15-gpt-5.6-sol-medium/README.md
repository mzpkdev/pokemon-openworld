# Issue 74 same-model benchmark

This is the frozen eight-task comparison for issue 74. Both arms used `gpt-5.6-sol` with medium reasoning. Task order alternated between baseline-first and bounded-first. The task manifest, final scores, provider JSONL events, and stderr streams are retained in this directory.

The baseline arm read repository evidence directly and ran the assigned check command. The bounded arm used only `tools.agent context`, the task's optional bounded query, and `tools.agent check`. Each check ran in a separate tool call so its admitted output could be measured independently.

## Scoring

Uncached input tokens are derived from the provider's reported `input_tokens - cached_input_tokens`. Check-output bytes count the UTF-8 bytes admitted from the completed assigned check command. Tool rounds count completed command executions, and latency is end-to-end wall time for each model run.

A task is correct when the model reports the observed check exit status, includes the expected check IDs, and cites the expected source paths. The no-regression gate compares paired tasks: every task that the baseline gets right must also be correct in the bounded arm.

## Results

| Metric | Baseline | Bounded agent | Result |
| --- | ---: | ---: | --- |
| Median uncached input tokens | 35,318.5 | 20,953.0 | 40.67% lower, pass |
| Total admitted check-output bytes | 4,893 | 11,091 | 126.67% higher, fail |
| Correct tasks | 6/8 | 6/8 | Per-task regression, fail |
| Median tool rounds | 3.5 | 2.5 | Informational |
| Median latency | 36.1315 s | 27.9815 s | Informational |

The map/travel and trainer tasks passed in the baseline arm but failed the bounded outcome criteria. The map query did not resolve the requested `MAP_VERMILION_CITY_FRLG` key to `data/maps/VermilionCity_Frlg/map.json`. The trainer task returned `src/data/trainers_frlg.party` for its queried trainer instead of the expected changed authority `src/data/trainers.party`.

The benchmark is a no-go because the check-output and no-outcome-regression gates failed. `results.json` contains the scored records and gate booleans. `runs/` contains the unmodified provider event streams used for the score.
