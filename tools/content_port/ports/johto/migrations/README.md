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

Each donor record authors an immutable `genesis` identity for its initial
published pin. Every migration records the digest of the currently published
migration as `predecessor`; the first migration uses `null`. Descriptor loading
walks that content-addressed chain backwards, requires every target to equal the
next record's source, and requires the first source to equal `genesis`. A current
pin with no migration must equal `genesis`. Consequently, installing a valid
reviewed record whose source is merely some resolvable donor commit cannot skip
the previously published chain.

The donor checkout used for finalization and CI must resolve both the source and
target commits. Finalization checks out both commits in disposable worktrees,
recomputes every added, removed, and changed path with blob hashes, recomputes
all authority-field and asset impacts, reruns the required command evidence, and
rejects any omitted or fabricated report entry. CI therefore uses full public
donor history instead of a single-commit shallow checkout.

Every migration embeds the canonical authority references, asset recipe, and
donor exclusions used to produce its evidence. Historical records are always
recomputed from that immutable snapshot; later edits to `adaptations.json` or
`assets.json` cannot redefine old evidence. The separate proposed-target check
still loads the current policy and materializes it against the proposed pin.

Asset `permissionEvidence` names an exact record in `assets.json`. Each record
must have a `reviewed` decision, an explicit permission, a safe repository path,
and the SHA-256 of that file's exact bytes. Loading, checking, migration review,
and bundle creation all resolve and hash the evidence again. Missing, changed,
unreviewed, blocked, or unknown evidence fails closed.

The committed pin is authoritative only when its exact target matches the head
record and the complete predecessor chain reaches the authored genesis identity.
Publication remains a normal reviewed Git commit; the content-port tool never
moves a branch or creates a commit.
