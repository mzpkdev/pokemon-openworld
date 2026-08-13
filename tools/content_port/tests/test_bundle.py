from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from tools.content_port.bundle import (
    _artifact_digest,
    _read_project_config,
    build_bundle,
    bundle_digest,
    finalize_ci_bundle,
    deterministic_patch,
    run_ci_validator,
    validate_asset_ownership,
    verify_artifact_manifest,
    verify_bundle,
    verify_validation_policy,
    write_artifact_manifest,
    write_preflight_receipt,
)
from tools.content_port.errors import ContentPortError
from tools.content_port.ownership import (
    OwnershipManifest,
    OwnershipUnit,
    canonical_json,
    content_sha256,
)
from tools.content_port.update import canonical_bytes
from tools.content_port.worktree import run_named_validation_commands


def run(root: Path, *command: str) -> None:
    subprocess.run(
        command, cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )


class BundleTests(unittest.TestCase):
    def test_substituted_preflight_contract_is_rejected_before_validation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_repo(root)
            marker = root / "validator-ran"
            policy = {
                "schemaVersion": 2,
                "preflightCommands": [],
                "preparationCommands": [],
                "validators": [
                    {
                        "id": "validator",
                        "command": [
                            "python3",
                            "-c",
                            "from pathlib import Path; Path('validator-ran').touch()",
                        ],
                    }
                ],
                "artifacts": ["build/artifact"],
            }
            policy_path = root / "tools/content_port/project.json"
            policy_path.parent.mkdir(parents=True)
            policy_path.write_bytes(canonical_json(policy))
            run(root, "git", "add", policy_path.relative_to(root).as_posix())
            run(root, "git", "commit", "-q", "-m", "policy")
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip()

            build = root / "build"
            candidate = build / "candidate"
            candidate.mkdir(parents=True)
            (candidate / "desired.patch").write_bytes(b"")
            (candidate / "ownership.json").write_bytes(
                canonical_json(OwnershipManifest("test", ()).to_json())
            )
            (candidate / "report.json").write_bytes(
                canonical_json(
                    {
                        "schemaVersion": 1,
                        "port": "test",
                        "baseCommit": head,
                        "patchSha256": content_sha256(b""),
                        "ownedUnitCount": 0,
                        "contract": {"proof": "candidate-authenticated"},
                    }
                )
            )
            (build / "artifact").write_bytes(b"prepared")
            artifact_manifest = build / "artifact-manifest.json"
            write_artifact_manifest(root, artifact_manifest)

            substituted_contract = build / "substituted-donor-contract.json"
            substituted_contract.write_bytes(
                canonical_json({"proof": "canonical-but-substituted"})
            )
            substituted_receipt = build / "substituted-preflight.json"
            write_preflight_receipt(root, substituted_contract, substituted_receipt)

            with self.assertRaisesRegex(
                ContentPortError,
                "donor contract does not match candidate-derived evidence",
            ):
                run_ci_validator(
                    root,
                    "validator",
                    candidate,
                    artifact_manifest,
                    substituted_receipt,
                    substituted_contract,
                    Path("build/results/validator"),
                    build / "receipts/validator.json",
                )
            self.assertFalse(marker.exists())

            output = build / "final"
            with self.assertRaisesRegex(
                ContentPortError,
                "donor contract does not match candidate-derived evidence",
            ):
                finalize_ci_bundle(
                    root,
                    candidate,
                    artifact_manifest,
                    substituted_receipt,
                    substituted_contract,
                    build / "receipts",
                    output,
                )
            self.assertFalse(output.exists())

    def test_ci_finalization_binds_candidate_and_canonical_artifact_manifest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_repo(root)
            policy = {
                "schemaVersion": 2,
                "preflightCommands": [
                    {"id": "preflight", "command": ["python3", "-c", "pass"]}
                ],
                "preparationCommands": [],
                "validators": [
                    {
                        "id": "validator",
                        "command": ["python3", "-c", "pass", "{results}"],
                    }
                ],
                "artifacts": ["build/artifact"],
            }
            policy_path = root / "tools/content_port/project.json"
            policy_path.parent.mkdir(parents=True)
            policy_path.write_bytes(canonical_json(policy))
            run(root, "git", "add", policy_path.relative_to(root).as_posix())
            run(root, "git", "commit", "-q", "-m", "policy")
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip()
            artifact = root / "build/artifact"
            artifact.parent.mkdir()
            artifact.write_bytes(b"prepared")
            artifact_manifest = root / "build/artifact-manifest.json"
            write_artifact_manifest(root, artifact_manifest)

            candidate = root / "build/candidate"
            candidate.mkdir()
            (candidate / "desired.patch").write_bytes(b"")
            desired = OwnershipManifest("test", ())
            (candidate / "ownership.json").write_bytes(
                canonical_json(desired.to_json())
            )
            donor = root / "build/donor-contract.json"
            donor.write_bytes(canonical_json({"proof": "donors"}))
            (candidate / "report.json").write_bytes(
                canonical_json(
                    {
                        "schemaVersion": 1,
                        "port": "test",
                        "baseCommit": head,
                        "patchSha256": content_sha256(b""),
                        "ownedUnitCount": 0,
                        "contract": {"proof": "donors"},
                    }
                )
            )
            preflight = root / "build/preflight.json"
            write_preflight_receipt(root, donor, preflight)
            receipts = root / "build/receipts"
            run_ci_validator(
                root,
                "validator",
                candidate,
                artifact_manifest,
                preflight,
                donor,
                Path("build/results/validator"),
                receipts / "validator.json",
            )
            finalized = finalize_ci_bundle(
                root,
                candidate,
                artifact_manifest,
                preflight,
                donor,
                receipts,
                root / "build/final",
            )

            self.assertEqual(finalized.sha256, verify_bundle(finalized.output_dir))
            report = json.loads(finalized.report.read_text())
            self.assertEqual(report["contract"], {"proof": "donors"})
            self.assertEqual(
                report["validation"]["artifacts"],
                verify_artifact_manifest(root, artifact_manifest),
            )
            receipt_path = receipts / "validator.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["status"] = "failed"
            receipt_path.write_bytes(canonical_json(receipt))
            with self.assertRaisesRegex(ContentPortError, "receipt validator"):
                finalize_ci_bundle(
                    root,
                    candidate,
                    artifact_manifest,
                    preflight,
                    donor,
                    receipts,
                    root / "build/tampered-final",
                )
            artifact.write_bytes(b"mutated")
            with self.assertRaisesRegex(ContentPortError, "canonical manifest"):
                verify_artifact_manifest(root, artifact_manifest)

    def test_ci_finalization_refuses_missing_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_repo(root)
            policy_path = root / "tools/content_port/project.json"
            policy_path.parent.mkdir(parents=True)
            policy_path.write_bytes(
                canonical_json(
                    {
                        "schemaVersion": 2,
                        "preflightCommands": [],
                        "preparationCommands": [],
                        "validators": [
                            {"id": "required", "command": ["python3", "-c", "pass"]}
                        ],
                        "artifacts": ["build/artifact"],
                    }
                )
            )
            run(root, "git", "add", policy_path.relative_to(root).as_posix())
            run(root, "git", "commit", "-q", "-m", "policy")
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip()
            (root / "build").mkdir()
            (root / "build/artifact").write_bytes(b"artifact")
            artifact_manifest = root / "build/artifact-manifest.json"
            write_artifact_manifest(root, artifact_manifest)
            donor = root / "build/donor.json"
            donor.write_bytes(canonical_json({"proof": "donors"}))
            candidate = root / "build/candidate"
            candidate.mkdir()
            (candidate / "desired.patch").write_bytes(b"")
            (candidate / "ownership.json").write_bytes(
                canonical_json(OwnershipManifest("test", ()).to_json())
            )
            (candidate / "report.json").write_bytes(
                canonical_json(
                    {
                        "schemaVersion": 1,
                        "port": "test",
                        "baseCommit": head,
                        "patchSha256": content_sha256(b""),
                        "ownedUnitCount": 0,
                        "contract": {"proof": "donors"},
                    }
                )
            )
            preflight = root / "build/preflight.json"
            write_preflight_receipt(root, donor, preflight)
            receipts = root / "build/receipts"
            receipts.mkdir()
            with self.assertRaisesRegex(ContentPortError, "receipt set"):
                finalize_ci_bundle(
                    root,
                    candidate,
                    artifact_manifest,
                    preflight,
                    donor,
                    receipts,
                    root / "build/final",
                )

    def test_artifact_digest_hashes_raw_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            roots = (base / "one", base / "two")
            for root in roots:
                environment = root / "build/e2e-venv/bin"
                environment.mkdir(parents=True)
                (environment / "pytest").write_text(
                    f"#!{root}/build/e2e-venv/bin/python\n"
                )
            self.assertNotEqual(
                _artifact_digest(roots[0], "build/e2e-venv"),
                _artifact_digest(roots[1], "build/e2e-venv"),
            )

    def test_artifact_digest_is_path_independent_for_locked_wheelhouse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            roots = (base / "one", base / "two")
            for root in roots:
                wheelhouse = root / "build/e2e-wheelhouse"
                wheelhouse.mkdir(parents=True)
                (wheelhouse / "dependency-1.0-py3-none-any.whl").write_bytes(b"wheel")
                (wheelhouse / ".requirements-v2").write_bytes(b"")
            self.assertEqual(
                _artifact_digest(roots[0], "build/e2e-wheelhouse"),
                _artifact_digest(roots[1], "build/e2e-wheelhouse"),
            )

    def test_artifact_digest_binds_normalized_modes_and_rejects_special_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact"
            artifact.write_bytes(b"same")
            artifact.chmod(0o644)
            ordinary = _artifact_digest(root, "artifact")
            artifact.chmod(0o600)
            self.assertEqual(_artifact_digest(root, "artifact"), ordinary)
            artifact.chmod(0o755)
            self.assertNotEqual(_artifact_digest(root, "artifact"), ordinary)

            fifo = root / "fifo"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ContentPortError, "unsafe"):
                _artifact_digest(root, "fifo")

    def test_validation_report_must_exactly_match_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "schemaVersion": 2,
                "preflightCommands": [
                    {"id": "preflight", "command": ["tool", "preflight"]}
                ],
                "preparationCommands": [
                    {"id": "prepare", "command": ["tool", "prepare"]}
                ],
                "validators": [
                    {"id": "one", "command": ["tool", "one"]},
                    {"id": "two", "command": ["tool", "two"]},
                ],
                "artifacts": ["build/one", "build/two"],
            }
            config_path = root / "project.json"
            config_path.write_bytes(canonical_json(config))
            policy = _read_project_config(config_path)
            valid = {
                "preflight": [
                    {
                        "id": "preflight",
                        "command": ["tool", "preflight"],
                        "status": "passed",
                    }
                ],
                "validators": [
                    {"id": "one", "command": ["tool", "one"], "status": "passed"},
                    {"id": "two", "command": ["tool", "two"], "status": "passed"},
                ],
                "artifacts": [
                    {"path": "build/one", "sha256": "0" * 64},
                    {"path": "build/two", "sha256": "1" * 64},
                ],
            }
            verify_validation_policy(valid, policy)
            mutations = (
                {**valid, "preflight": []},
                {**valid, "validators": list(reversed(valid["validators"]))},
                {
                    **valid,
                    "validators": [
                        valid["validators"][0],
                        valid["validators"][0],
                    ],
                },
                {
                    **valid,
                    "validators": [
                        valid["validators"][0],
                        {
                            "id": "two",
                            "command": ["tool", "substitute"],
                            "status": "passed",
                        },
                    ],
                },
                {**valid, "artifacts": list(reversed(valid["artifacts"]))},
                {**valid, "artifacts": [valid["artifacts"][0]]},
                {
                    **valid,
                    "artifacts": [
                        valid["artifacts"][0],
                        {"path": "build/substitute", "sha256": "1" * 64},
                    ],
                },
            )
            for mutation in mutations:
                with (
                    self.subTest(mutation=mutation),
                    self.assertRaisesRegex(ContentPortError, "(?:does|do) not match"),
                ):
                    verify_validation_policy(mutation, policy)

    def test_named_validators_run_concurrently_with_isolated_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = run_named_validation_commands(
                root,
                (
                    (
                        "first",
                        (
                            "python3",
                            "-c",
                            "import os,time; time.sleep(.15); open(os.environ['CONTENT_PORT_VALIDATOR_RESULTS'] + '/proof', 'w').write('first')",
                        ),
                    ),
                    (
                        "second",
                        (
                            "python3",
                            "-c",
                            "import os,time; time.sleep(.15); open(os.environ['CONTENT_PORT_VALIDATOR_RESULTS'] + '/proof', 'w').write('second')",
                        ),
                    ),
                ),
                root / "results",
                jobs=2,
            )

            self.assertEqual(
                [item.validator_id for item in results], ["first", "second"]
            )
            self.assertEqual((root / "results/first/proof").read_text(), "first")
            self.assertEqual((root / "results/second/proof").read_text(), "second")

    def test_named_validators_fail_fast_and_print_the_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            started = time.monotonic()
            with self.assertRaisesRegex(ContentPortError, "representative failure"):
                run_named_validation_commands(
                    root,
                    (
                        (
                            "failure",
                            (
                                "python3",
                                "-c",
                                "import sys; print('representative failure'); sys.exit(7)",
                            ),
                        ),
                        ("slow", ("python3", "-c", "import time; time.sleep(10)")),
                        (
                            "queued",
                            (
                                "python3",
                                "-c",
                                "from pathlib import Path; Path('queued').write_text('ran')",
                            ),
                        ),
                    ),
                    root / "results",
                    jobs=2,
                )
            self.assertLess(time.monotonic() - started, 3)
            self.assertFalse((root / "queued").exists())

    def test_parallel_validators_read_private_prepared_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            (root / "input").write_text("prepared")
            ready = base / "mutating"
            results = root / "results"
            commands = (
                (
                    "mutator",
                    (
                        "python3",
                        "-c",
                        (
                            "from pathlib import Path; import time; "
                            "p=Path('input'); p.write_text('mutated'); "
                            f"Path({str(ready)!r}).write_text('ready'); "
                            "time.sleep(.3); p.write_text('prepared')"
                        ),
                    ),
                ),
                (
                    "reader",
                    (
                        "python3",
                        "-c",
                        (
                            "from pathlib import Path; import os,time; "
                            f"ready=Path({str(ready)!r}); "
                            "deadline=time.time()+2; "
                            "\nwhile not ready.exists() and time.time()<deadline: time.sleep(.01)\n"
                            "Path(os.environ['CONTENT_PORT_VALIDATOR_RESULTS'], 'proof').write_text(Path('input').read_text())"
                        ),
                    ),
                ),
            )

            run_named_validation_commands(root, commands, results, jobs=2)

            self.assertEqual((results / "reader/proof").read_text(), "prepared")
            self.assertEqual((root / "input").read_text(), "prepared")

    def test_ci_validator_requires_exact_candidate_and_rejects_mutations(self) -> None:
        cases = (
            (
                "untracked source",
                "from pathlib import Path; Path('rogue-source').write_text('bad')",
            ),
            (
                "ignored artifact",
                "from pathlib import Path; Path('build/artifact').write_text('bad')",
            ),
            (
                "index",
                "import subprocess; subprocess.run(['git','update-index','--chmod=+x','base.txt'],check=True)",
            ),
            (
                "mode",
                "import os; os.chmod('base.txt', 0o755)",
            ),
        )
        for label, validator_body in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_repo(root)
                (root / ".gitignore").write_text("build/\n")
                policy_path = root / "tools/content_port/project.json"
                policy_path.parent.mkdir(parents=True)
                policy_path.write_bytes(
                    canonical_json(
                        {
                            "schemaVersion": 2,
                            "preflightCommands": [],
                            "preparationCommands": [],
                            "validators": [
                                {
                                    "id": "validator",
                                    "command": ["python3", "-c", validator_body],
                                }
                            ],
                            "artifacts": ["build/artifact"],
                        }
                    )
                )
                run(
                    root,
                    "git",
                    "add",
                    ".gitignore",
                    policy_path.relative_to(root).as_posix(),
                )
                run(root, "git", "commit", "-q", "-m", "policy")
                head = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=root, text=True
                ).strip()
                (root / "base.txt").write_text("desired\n")
                patch_bytes = deterministic_patch(root)
                run(root, "git", "restore", "base.txt")

                build = root / "build"
                candidate = build / "candidate"
                candidate.mkdir(parents=True)
                (candidate / "desired.patch").write_bytes(patch_bytes)
                ownership = OwnershipManifest("test", ())
                (candidate / "ownership.json").write_bytes(
                    canonical_json(ownership.to_json())
                )
                donor = build / "donor.json"
                donor.write_bytes(canonical_json({"proof": "donors"}))
                (candidate / "report.json").write_bytes(
                    canonical_json(
                        {
                            "schemaVersion": 1,
                            "port": "test",
                            "baseCommit": head,
                            "patchSha256": content_sha256(patch_bytes),
                            "ownedUnitCount": 0,
                            "contract": {"proof": "donors"},
                        }
                    )
                )
                (build / "artifact").write_text("prepared")
                artifact_manifest = build / "artifact-manifest.json"
                write_artifact_manifest(root, artifact_manifest)
                preflight = build / "preflight.json"
                write_preflight_receipt(root, donor, preflight)

                with self.assertRaisesRegex(ContentPortError, "exactly match"):
                    run_ci_validator(
                        root,
                        "validator",
                        candidate,
                        artifact_manifest,
                        preflight,
                        donor,
                        Path("build/results/validator"),
                        build / "receipt-before.json",
                    )

                run(root, "git", "apply", "--binary", str(candidate / "desired.patch"))
                with self.assertRaisesRegex(
                    ContentPortError, "changed repository state"
                ):
                    run_ci_validator(
                        root,
                        "validator",
                        candidate,
                        artifact_manifest,
                        preflight,
                        donor,
                        Path("build/results/validator"),
                        build / "receipt-after.json",
                    )

    def test_asset_ledger_and_ownership_are_exact(self) -> None:
        evidence_root = Path.cwd()
        evidence_digest = content_sha256((evidence_root / "CREDITS.md").read_bytes())
        permission_record = {
            "decision": "reviewed",
            "path": "CREDITS.md",
            "permission": "redistributable",
            "sha256": evidence_digest,
        }
        permission_digest = content_sha256(canonical_bytes(permission_record))
        digest = content_sha256(b"asset")
        unit = OwnershipUnit("file", "data/tilesets/test/asset.bin", digest)
        manifest = OwnershipManifest("test", (unit,))
        asset = {
            "key": unit.path,
            "source": "donor",
            "donor": "fixture",
            "sourcePath": "asset.bin",
            "semanticTarget": unit.path,
            "sourceSha256": digest,
            "targetSha256": digest,
            "conversionCommand": ["copy-bytes"],
            "permission": "redistributable",
            "license": "fixture permission",
            "permissionEvidence": permission_digest,
            "capability": "environment-assets",
            "supportState": "enabled",
        }
        policy = {
            "schemaVersion": 1,
            "permissionRecords": {permission_digest: permission_record},
            "assets": [asset],
        }
        validate_asset_ownership(manifest, policy, evidence_root=evidence_root)
        with self.assertRaisesRegex(ContentPortError, "hash differs"):
            validate_asset_ownership(
                OwnershipManifest(
                    "test",
                    (OwnershipUnit("file", unit.path, content_sha256(b"different")),),
                ),
                policy,
                evidence_root=evidence_root,
            )
        extra = OwnershipUnit(
            "file", "data/tilesets/test/unledgered.bin", content_sha256(b"extra")
        )
        with self.assertRaisesRegex(ContentPortError, "unledgered"):
            validate_asset_ownership(
                OwnershipManifest("test", (unit, extra)),
                policy,
                evidence_root=evidence_root,
            )

    def make_repo(self, root: Path) -> None:
        run(root, "git", "init", "-q")
        run(root, "git", "config", "user.name", "Content Port Test")
        run(root, "git", "config", "user.email", "content-port@example.invalid")
        (root / "base.txt").write_text("base\n")
        run(root, "git", "add", "base.txt")
        run(root, "git", "commit", "-q", "-m", "base")

    def install_manifest(self, root: Path, manifest: OwnershipManifest) -> None:
        path = root / f"tools/content_port/ports/{manifest.port}/ownership.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json(manifest.to_json()))
        run(root, "git", "add", "--all", ".")
        run(root, "git", "commit", "-q", "-m", "installed ownership")

    def apply_bundle_patch(self, root: Path, patch: Path, destination: Path) -> Path:
        run(root.parent, "git", "clone", "-q", str(root), str(destination))
        run(destination, "git", "apply", "--binary", str(patch))
        return destination

    def test_bundle_removes_stale_installed_units_of_every_kind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            self.make_repo(repo)
            stale_section = (
                b"// CONTENT PORT BEGIN test:stale\n"
                b"generated\n"
                b"// CONTENT PORT END test:stale\n"
            )
            stale_record = {"id": "stale", "value": 1}
            (repo / "stale.bin").write_bytes(b"stale\n")
            (repo / "shared.h").write_bytes(stale_section + b"hand\n")
            (repo / "registry.json").write_bytes(
                canonical_json(
                    {"records": {"hand": {"value": 2}, "stale": stale_record}}
                )
            )
            installed = OwnershipManifest(
                "test",
                (
                    OwnershipUnit("file", "stale.bin", content_sha256(b"stale\n")),
                    OwnershipUnit(
                        "section",
                        "shared.h",
                        content_sha256(stale_section),
                        name="stale",
                    ),
                    OwnershipUnit(
                        "registry-record",
                        "registry.json",
                        content_sha256(canonical_json(stale_record)),
                        registry="records",
                        key="stale",
                    ),
                ),
            )
            self.install_manifest(repo, installed)

            artifacts = build_bundle(
                repo,
                base / "bundle",
                OwnershipManifest("test", ()),
                {},
                validation_commands=[],
            )
            applied = self.apply_bundle_patch(repo, artifacts.patch, base / "applied")

            self.assertFalse((applied / "stale.bin").exists())
            self.assertEqual((applied / "shared.h").read_bytes(), b"hand\n")
            self.assertEqual(
                json.loads((applied / "registry.json").read_text()),
                {"records": {"hand": {"value": 2}}},
            )
            self.assertEqual(
                OwnershipManifest.load(
                    applied / "tools/content_port/ports/test/ownership.json"
                ),
                OwnershipManifest("test", ()),
            )

    def test_bundle_adds_desired_units_absent_from_installed_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            self.make_repo(repo)
            self.install_manifest(repo, OwnershipManifest("test", ()))
            section = (
                b"// CONTENT PORT BEGIN test:new\n"
                b"generated\n"
                b"// CONTENT PORT END test:new\n"
            )
            record = {"id": "new", "value": 3}
            desired = OwnershipManifest(
                "test",
                (
                    OwnershipUnit("file", "new.bin", content_sha256(b"new\n")),
                    OwnershipUnit(
                        "section",
                        "new.h",
                        content_sha256(section),
                        name="new",
                    ),
                    OwnershipUnit(
                        "registry-record",
                        "new.json",
                        content_sha256(canonical_json(record)),
                        registry="records",
                        key="new",
                    ),
                ),
            )
            payloads = {
                ("file", "new.bin"): b"new\n",
                ("section", "new.h", "new"): section,
                ("registry-record", "new.json", "records", "new"): record,
            }

            artifacts = build_bundle(
                repo,
                base / "bundle",
                desired,
                payloads,
                validation_commands=[],
            )
            applied = self.apply_bundle_patch(repo, artifacts.patch, base / "applied")

            self.assertEqual((applied / "new.bin").read_bytes(), b"new\n")
            self.assertEqual((applied / "new.h").read_bytes(), section)
            self.assertEqual(
                json.loads((applied / "new.json").read_text()),
                {"records": {"new": record}},
            )
            self.assertEqual(
                OwnershipManifest.load(
                    applied / "tools/content_port/ports/test/ownership.json"
                ),
                desired,
            )

    def test_bundle_refuses_to_claim_existing_unowned_units(self) -> None:
        section = (
            b"// CONTENT PORT BEGIN test:new\nhand\n// CONTENT PORT END test:new\n"
        )
        replacement_section = section.replace(b"hand", b"generated")
        cases = (
            (
                "file",
                "hand.txt",
                b"hand\n",
                OwnershipUnit("file", "hand.txt", content_sha256(b"generated\n")),
                b"generated\n",
            ),
            (
                "section",
                "hand.h",
                section,
                OwnershipUnit(
                    "section",
                    "hand.h",
                    content_sha256(replacement_section),
                    name="new",
                ),
                replacement_section,
            ),
            (
                "registry-record",
                "hand.json",
                canonical_json({"records": {"new": {"id": "new", "value": "hand"}}}),
                OwnershipUnit(
                    "registry-record",
                    "hand.json",
                    content_sha256(canonical_json({"id": "new", "value": "generated"})),
                    registry="records",
                    key="new",
                ),
                {"id": "new", "value": "generated"},
            ),
        )
        for kind, relative, preimage, unit, payload in cases:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                repo = base / "repo"
                repo.mkdir()
                self.make_repo(repo)
                (repo / relative).write_bytes(preimage)
                self.install_manifest(repo, OwnershipManifest("test", ()))

                with self.assertRaisesRegex(
                    ContentPortError, "refuses to claim unowned existing"
                ):
                    build_bundle(
                        repo,
                        base / "bundle",
                        OwnershipManifest("test", (unit,)),
                        {unit.identity: payload},
                        validation_commands=[],
                    )

                self.assertEqual((repo / relative).read_bytes(), preimage)
                self.assertFalse((base / "bundle").exists())
                self.assertEqual(
                    subprocess.check_output(["git", "status", "--porcelain"], cwd=repo),
                    b"",
                )

    def test_bundle_reads_validation_policy_from_its_fixed_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            self.make_repo(repo)
            payload = b"asset\n"
            permission_path = repo / "PERMISSION.txt"
            permission_path.write_text("reviewed fixture permission\n")
            permission_record = {
                "decision": "reviewed",
                "path": "PERMISSION.txt",
                "permission": "redistributable",
                "sha256": content_sha256(permission_path.read_bytes()),
            }
            permission_digest = content_sha256(canonical_bytes(permission_record))
            target = "data/tilesets/test/asset.bin"
            unit = OwnershipUnit("file", target, content_sha256(payload))
            policy = {
                "schemaVersion": 1,
                "permissionRecords": {permission_digest: permission_record},
                "assets": [
                    {
                        "key": target,
                        "source": "donor",
                        "donor": "fixture",
                        "sourcePath": "asset.bin",
                        "semanticTarget": target,
                        "sourceSha256": unit.sha256,
                        "targetSha256": unit.sha256,
                        "conversionCommand": ["copy-bytes"],
                        "permission": "redistributable",
                        "license": "fixture permission",
                        "permissionEvidence": permission_digest,
                        "capability": "environment-assets",
                        "supportState": "enabled",
                    }
                ],
            }
            asset_path = repo / "tools/content_port/ports/test/assets.json"
            asset_path.parent.mkdir(parents=True)
            asset_path.write_bytes(canonical_json(policy))
            self.install_manifest(repo, OwnershipManifest("test", ()))
            revision = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            policy["assets"][0]["targetSha256"] = content_sha256(b"other\n")
            asset_path.write_bytes(canonical_json(policy))
            run(repo, "git", "add", asset_path.relative_to(repo).as_posix())
            run(repo, "git", "commit", "-q", "-m", "advance policy")

            artifacts = build_bundle(
                repo,
                base / "bundle",
                OwnershipManifest("test", (unit,)),
                {unit.identity: payload},
                validation_commands=[],
                revision=revision,
            )

            report = json.loads(artifacts.report.read_text())
            self.assertEqual(report["baseCommit"], revision)

    def test_binary_bundle_is_deterministic_and_does_not_touch_caller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            self.make_repo(repo)
            binary = b"\x00\xff\x10content\x00"
            unit = OwnershipUnit("file", "generated/data.bin", content_sha256(binary))
            desired = OwnershipManifest("test", (unit,))
            payloads = {unit.identity: binary}
            first = build_bundle(
                repo,
                base / "first",
                desired,
                payloads,
                {"closureDigest": "abc"},
                validation_commands=[],
            )
            second = build_bundle(
                repo,
                base / "second",
                desired,
                payloads,
                {"closureDigest": "abc"},
                validation_commands=[],
            )
            for name in ("desired.patch", "ownership.json", "report.json"):
                self.assertEqual(
                    (first.output_dir / name).read_bytes(),
                    (second.output_dir / name).read_bytes(),
                )
            self.assertIn(b"GIT binary patch", first.patch.read_bytes())
            self.assertEqual(first.sha256, bundle_digest(first.output_dir))
            self.assertEqual(first.sha256, verify_bundle(first.output_dir))
            status = subprocess.check_output(["git", "status", "--porcelain"], cwd=repo)
            self.assertEqual(status, b"")

    def test_corrupt_patch_and_unsafe_artifacts_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            self.make_repo(repo)
            unit = OwnershipUnit("file", "new", content_sha256(b"new"))
            artifact = build_bundle(
                repo,
                base / "bundle",
                OwnershipManifest("test", (unit,)),
                {unit.identity: b"new"},
                validation_commands=[],
            )
            artifact.patch.write_bytes(b"corrupt")
            with self.assertRaisesRegex(ContentPortError, "does not match"):
                verify_bundle(artifact.output_dir)
            artifact.patch.unlink()
            artifact.patch.symlink_to(repo / "base.txt")
            with self.assertRaisesRegex(ContentPortError, "unsafe"):
                bundle_digest(artifact.output_dir)

    def test_dirty_caller_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_repo(root)
            (root / "dirty").write_text("dirty")
            with self.assertRaisesRegex(ContentPortError, "clean worktree"):
                build_bundle(
                    root,
                    root.parent / "bundle",
                    OwnershipManifest("test", ()),
                    {},
                    validation_commands=[],
                )

    def test_validation_cannot_mutate_desired_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            self.make_repo(repo)
            with self.assertRaisesRegex(
                ContentPortError, "changed the staged desired tree"
            ):
                build_bundle(
                    repo,
                    base / "bundle",
                    OwnershipManifest("test", ()),
                    {},
                    validation_commands=[
                        (
                            "python3",
                            "-c",
                            "from pathlib import Path; Path('base.txt').write_text('mutated')",
                        )
                    ],
                )

    def test_report_binds_named_validators_and_prepared_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            self.make_repo(repo)
            (repo / ".gitignore").write_text("build/\n")
            config = {
                "schemaVersion": 2,
                "preflightCommands": [
                    {
                        "id": "preflight",
                        "command": ["python3", "-c", "print('checked')"],
                    }
                ],
                "preparationCommands": [
                    {
                        "id": "prepare",
                        "command": [
                            "python3",
                            "-c",
                            "from pathlib import Path; Path('build').mkdir(); Path('build/artifact').write_text('exact')",
                        ],
                    }
                ],
                "validators": [
                    {
                        "id": "one",
                        "command": ["python3", "-c", "print('one')"],
                    },
                    {
                        "id": "two",
                        "command": ["python3", "-c", "print('two')"],
                    },
                ],
                "artifacts": ["build/artifact"],
            }
            config_path = repo / "tools/content_port/project.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_bytes(canonical_json(config))
            run(
                repo,
                "git",
                "add",
                ".gitignore",
                config_path.relative_to(repo).as_posix(),
            )
            run(repo, "git", "commit", "-q", "-m", "validation policy")

            artifact = build_bundle(
                repo,
                base / "bundle",
                OwnershipManifest("test", ()),
                {},
                validation_jobs=2,
            )

            validation = json.loads(artifact.report.read_text())["validation"]
            self.assertEqual(
                [item["id"] for item in validation["preflight"]], ["preflight"]
            )
            self.assertEqual(
                [item["id"] for item in validation["validators"]], ["one", "two"]
            )
            self.assertEqual(validation["artifacts"][0]["path"], "build/artifact")
            self.assertRegex(validation["policySha256"], r"^[0-9a-f]{64}$")
            report = json.loads(artifact.report.read_text())
            report.pop("validation")
            artifact.report.write_bytes(canonical_json(report))
            with self.assertRaisesRegex(ContentPortError, "validation report"):
                verify_bundle(artifact.output_dir)

    def test_validator_cannot_mutate_prepared_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            self.make_repo(repo)
            (repo / ".gitignore").write_text("build/\n")
            config = {
                "schemaVersion": 2,
                "preflightCommands": [],
                "preparationCommands": [
                    {
                        "id": "prepare",
                        "command": [
                            "python3",
                            "-c",
                            "from pathlib import Path; Path('build').mkdir(); Path('build/artifact').write_text('exact')",
                        ],
                    }
                ],
                "validators": [
                    {
                        "id": "mutate",
                        "command": [
                            "python3",
                            "-c",
                            "from pathlib import Path; Path('build/artifact').write_text('changed')",
                        ],
                    }
                ],
                "artifacts": ["build/artifact"],
            }
            config_path = repo / "tools/content_port/project.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_bytes(canonical_json(config))
            run(
                repo,
                "git",
                "add",
                ".gitignore",
                config_path.relative_to(repo).as_posix(),
            )
            run(repo, "git", "commit", "-q", "-m", "validation policy")

            with self.assertRaisesRegex(ContentPortError, "changed prepared artifacts"):
                build_bundle(
                    repo,
                    base / "bundle",
                    OwnershipManifest("test", ()),
                    {},
                )


if __name__ == "__main__":
    unittest.main()
