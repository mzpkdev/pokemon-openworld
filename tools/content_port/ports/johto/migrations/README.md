# Donor migrations

`donor-update` writes a candidate report to
`build/content-port/johto/donor-migration.json`. It does not change a pin or grant
authority to the proposed tree.

Review every path, authority-field change, asset hash, conversion command, and
permission decision. Set every `reviewerDisposition` to `accepted` or `adapted`,
record the tests, and set `decision` to `reviewed`. Finalize it with:

```sh
python3 -m tools.content_port migration-finalize --repo . \
  --candidate build/content-port/johto/donor-migration.json \
  --port-dir tools/content_port/ports/johto
```

Finalization writes the record under its canonical SHA-256 filename and emits
`build/content-port/johto/donor-port-update.json` with the exact proposed donor
record. Apply that proposal to `port.json` only after review, then commit it with
the record and asset-policy changes. `blocked` and `unknown` assets cannot be
finalized or bundled.

The committed pin is authoritative only when its exact source and target commits
match the reviewed record. Publication remains a normal reviewed Git commit;
the content-port tool never moves a branch or creates a commit.
