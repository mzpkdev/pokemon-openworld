# Probe retrieval benchmark report

Status: experimental, gate unavailable.

The frozen corpus has ten tasks at revision
`2098e29b46e843d3b91bf90f73cbd9bf5979010f`. It covers C mechanics, Python content-port
work, map JSON and generated includes, script includes, assembly, trainers, persistence,
authority, test selection, and a negative sibling-worktree request.

No paired model benchmark is reported in this change. The task execution interface did
not provide comparable billed and cached token telemetry for controlled with-helper and
without-helper runs. Running unmetered trials would not establish the issue's adoption
gate and could produce a false go decision.

The helper therefore remains experimental and disabled by default. Adoption requires a
paired run for every corpus task with the same model, reasoning setting, prompt, worktree
revision, and cache condition. Each run must record billed input and output tokens, cached
tokens, tool rounds, wall latency, correctness, required evidence, and failures or
abandonment.

The gate passes only if aggregate billed tokens fall by at least 20 percent, correctness
and required evidence do not regress, and failed or abandoned runs do not increase
materially. Any later Probe version requires new compatibility fixtures and a repeated
benchmark.
