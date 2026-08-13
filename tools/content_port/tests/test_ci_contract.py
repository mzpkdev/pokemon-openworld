from __future__ import annotations

from pathlib import Path
import json
import re
import unittest


WORKFLOW = Path(".github/workflows/ci.yml")
MAKEFILE = Path("Makefile")
PROJECT = Path("tools/content_port/project.json")


class CiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.makefile = MAKEFILE.read_text(encoding="utf-8")
        cls.project = PROJECT.read_text(encoding="utf-8")
        cls.project_value = json.loads(cls.project)

    def test_dedicated_job_has_stable_identity_and_runtime_budget(self) -> None:
        self.assertRegex(
            self.workflow,
            (
                r"(?m)^  donor-contracts:\n"
                r"    name: Donor Contracts\n"
                r"    runs-on: ubuntu-latest\n"
                r"    timeout-minutes: 30$"
            ),
        )

    def test_donor_contracts_install_canonical_build_dependencies(self) -> None:
        donor_job = self.workflow.split("  donor-contracts:\n", 1)[1].split(
            "  bundle-preflight:\n", 1
        )[0]
        setup = "      - name: Set up build dependencies\n        uses: ./.github/actions/setup-build\n"
        self.assertEqual(donor_job.count(setup), 1)
        self.assertLess(
            donor_job.index("uses: actions/checkout@"), donor_job.index(setup)
        )
        self.assertLess(
            donor_job.index(setup), donor_job.index("Checkout HnS content authority")
        )
        self.assertNotIn("git clean", donor_job)
        self.assertNotIn("git reset", donor_job)

    def test_mechanics_job_has_bounded_runtime_budget(self) -> None:
        self.assertRegex(
            self.workflow,
            (
                r"(?m)^  test:\n"
                r"    name: Signed Bundle / Validate \(Mechanics\)\n"
                r"    needs: \[build, bundle-preflight\]\n"
                r"    runs-on: ubuntu-latest\n"
                r"    timeout-minutes: 30$"
            ),
        )

    def test_both_public_donors_are_exactly_pinned_without_credentials(self) -> None:
        for repository, revision, directory in (
            (
                "https://github.com/PokemonHnS-Development/pokemonHnS.git",
                "751823abaf677020bcd72c45fe3e7cb2b8a576e4",
                "pokemonHnS",
            ),
            (
                "https://github.com/evilchinesefood/PKMN-World.git",
                "d40affe26e58a20f445daad84af5e45be812e69f",
                "PKMN-World",
            ),
        ):
            checkout = (
                f'git -C "$CONTENT_PORT_DONOR_ROOT/{directory}" remote add origin '
                f"\\\n            {repository}"
            )
            self.assertEqual(self.workflow.count(checkout), 2)
            self.assertEqual(self.workflow.count(f"--no-tags origin {revision}"), 2)

    def test_candidate_donors_stay_outside_the_candidate_worktree(self) -> None:
        donor_root = "CONTENT_PORT_DONOR_ROOT: ${{ runner.temp }}/content-port-donors"
        self.assertEqual(self.workflow.count(donor_root), 6)
        self.assertNotIn("path: .references/", self.workflow)
        self.assertNotIn("--donor-root .references", self.workflow)
        self.assertIn(
            "python3 -m tools.content_port candidate --port johto \\\n"
            '            --donor-root "$CONTENT_PORT_DONOR_ROOT"',
            self.workflow,
        )
        build_job = self.workflow.split("  build:\n", 1)[1].split("  e2e:\n", 1)[0]
        self.assertNotIn("--compare-report", build_job)

    def test_required_mode_commands_and_failure_artifact_are_pinned(self) -> None:
        required_fragments = (
            'CONTENT_PORT_REQUIRE_DONORS: "1"',
            "CONTENT_PORT_DONOR_ROOT: ${{ runner.temp }}/content-port-donors",
            "make content-port-transaction-check",
            "-s tools/content_port/tests -p 'test_*.py' -q",
            "grep -Eq 'skipped=[1-9][0-9]*'",
            "Donor Contracts requires zero skipped tests.",
            "python3 -m tools.content_port check --port johto",
            '--donor-root "$CONTENT_PORT_DONOR_ROOT"',
            "--write-report build/content-port/donor-contract.json",
            "if: failure()",
            "name: donor-contract-failure-evidence",
            "build/content-port/donor-contract.json",
            "-s tools/persistence/tests -p 'test_*.py' -q",
            "build/content-port/persistence.log",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.workflow)
        self.assertNotIn("-s tools/content_port/tests/donor", self.workflow)

    def test_legacy_importer_is_not_a_ci_authority(self) -> None:
        self.assertNotIn("tools/johto_import", self.workflow)
        self.assertIn("make content-port-test", self.workflow)

    def test_transaction_guard_is_first_prerequisite(self) -> None:
        target_patterns = (
            r"^all: content-port-transaction-check ",
            r"^check: content-port-transaction-check ",
            r"^content-port-check: content-port-transaction-check$",
            r"^content-port-bundle: content-port-transaction-check$",
            r"^content-port-bundle-artifacts: content-port-transaction-check$",
            r"^content-port-test: content-port-transaction-check$",
            r"^e2e-core: content-port-transaction-check ",
            r"^e2e-extended: content-port-transaction-check ",
            r"^e2e-integrity: content-port-transaction-check ",
            r"^integrity-check: content-port-transaction-check ",
            r"^integrity-check-all-purposes: content-port-transaction-check$",
            r"^rom: content-port-transaction-check ",
            r"^generated: content-port-transaction-check ",
        )
        for pattern in target_patterns:
            with self.subTest(pattern=pattern):
                self.assertRegex(self.makefile, re.compile(pattern, re.MULTILINE))
        self.assertIn(
            "python3 -m tools.content_port transaction-check --repo .",
            self.makefile,
        )
        self.assertIn(
            "if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then",
            self.makefile,
        )

    def test_file_rules_keep_guard_out_of_automatic_prerequisite_variables(
        self,
    ) -> None:
        guarded_file_rules = (
            "$(AUTO_GEN_TARGETS): | content-port-transaction-check",
            "$(OBJS) $(TEST_OBJS): | content-port-transaction-check",
            "$(ROM): $(ELF) | content-port-transaction-check",
            "$(SYM): $(ELF) | content-port-transaction-check",
        )
        for fragment in guarded_file_rules:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.makefile)
        self.assertNotRegex(
            self.makefile,
            re.compile(
                r"^\$\((?:ROM|SYM)\): content-port-transaction-check", re.MULTILINE
            ),
        )

    def test_signed_bundle_jobs_gate_and_reuse_prepared_artifacts(self) -> None:
        required_fragments = (
            "name: Signed Bundle / Preflight",
            "needs: [format, lint, donor-contracts]",
            "name: Signed Bundle / Prepare Artifacts",
            "needs: [format, lint]",
            'make CONTENT_PORT_BUILD_JOBS="$(nproc)" content-port-bundle-artifacts',
            "name: content-port-validation-artifacts",
            "python3 -m tools.content_port candidate --port johto",
            "python3 -m tools.content_port artifact-manifest",
            "name: Signed Bundle / Validate (Mechanics)",
            "python3 -m tools.content_port run-ci-validator --id mechanics",
            "name: Signed Bundle / Validate (E2E ${{ matrix.name }})",
            "fail-fast: true",
            "python3 -m tools.content_port run-ci-validator --id ${{ matrix.target }}",
            "name: Signed Bundle / Validate (ROM Integrity)",
            "name: Signed Bundle / Attest",
            "needs: [test, e2e, integrity]",
            'expected=\'["mechanics","rom-integrity","e2e-core","e2e-extended","e2e-integrity"]\'',
            "python3 -m tools.content_port finalize-ci-bundle",
            "--receipts build/content-port/receipts",
            "--preflight-receipt build/content-port/preflight/preflight-receipt.json",
            "pattern: content-port-receipt-*",
            "build/content-port/signed-bundle.sha256",
            "name: signed-bundle-ci-attestation",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.workflow)
        self.assertIn("build/e2e-wheelhouse", self.workflow)
        self.assertNotIn("build/e2e-venv", self.workflow)
        self.assertIn("--no-index", self.makefile)
        self.assertIn("--require-hashes --only-binary=:all:", self.makefile)
        self.assertNotIn("artifacts_sha256=", self.workflow)
        self.assertNotIn(
            "sha256sum content-port-validation-artifacts.tar", self.workflow
        )
        for artifact in (
            '"tools/mgba/mgba-rom-test"',
            '"tools/mgba-rom-test-hydra/mgba-rom-test-hydra"',
            '"tools/patchelf/patchelf"',
            '"build/generated"',
            '"build/save-contract"',
        ):
            self.assertIn(artifact, self.project)

        header = "include/constants/region_map_sections.h"
        self.assertIn(header, self.project_value["artifacts"])
        self.assertIn(
            f"AUTO_GEN_TARGETS += {header}",
            Path("json_data_rules.mk").read_text(encoding="utf-8"),
        )

        archive = self.workflow.split(
            "      - name: Pack prepared validation artifacts\n", 1
        )[1].split("      - name: Upload prepared validation artifacts\n", 1)[0]
        self.assertIn(header, archive)
        self.assertIn("tools/patchelf/patchelf", archive)
        self.assertNotIn("donor-contract.json", archive)
        self.assertNotIn("preflight-receipt.json", archive)

    def test_preflight_evidence_joins_artifacts_at_each_validation_boundary(
        self,
    ) -> None:
        jobs = {
            "test": ("  build:\n", "needs: [build, bundle-preflight]"),
            "e2e": ("  integrity:\n", "needs: [build, bundle-preflight]"),
            "integrity": ("  bundle-attest:\n", "needs: [build, bundle-preflight]"),
            "bundle-attest": (None, "needs: [test, e2e, integrity]"),
        }
        download = (
            "          pattern: content-port-preflight-*\n"
            "          path: build/content-port/preflight\n"
            "          merge-multiple: true"
        )
        for job, (next_job, dependency) in jobs.items():
            with self.subTest(job=job):
                body = self.workflow.split(f"  {job}:\n", 1)[1]
                if next_job is not None:
                    body = body.split(next_job, 1)[0]
                self.assertIn(dependency, body)
                self.assertEqual(body.count(download), 1)

        build_job = self.workflow.split("  build:\n", 1)[1].split("  e2e:\n", 1)[0]
        self.assertNotIn("content-port-preflight-*", build_job)
        self.assertNotIn("build/content-port/preflight", build_job)

    def test_validator_transport_archive_stays_outside_checkout(self) -> None:
        self.assertEqual(
            self.workflow.count("path: ${{ runner.temp }}/content-port-validation"),
            4,
        )
        self.assertEqual(
            self.workflow.count(
                'tar -xf "${RUNNER_TEMP}/content-port-validation/'
                'content-port-validation-artifacts.tar"'
            ),
            4,
        )
        self.assertNotIn("tar -xf content-port-validation-artifacts.tar", self.workflow)

    def test_e2e_validators_isolate_generated_runtime_under_results(self) -> None:
        validators = {
            item["id"]: item["command"] for item in self.project_value["validators"]
        }
        for validator_id in ("e2e-core", "e2e-extended", "e2e-integrity"):
            with self.subTest(validator_id=validator_id):
                self.assertIn("E2E_RESULTS={results}", validators[validator_id])
                self.assertIn("E2E_VENV={results}/venv", validators[validator_id])
                self.assertIn(
                    "E2E_PYTEST_CACHE={results}/pytest-cache",
                    validators[validator_id],
                )
        self.assertIn("E2E_VENV ?= $(BUILD_DIR)/e2e-venv", self.makefile)
        self.assertIn("E2E_PYTEST_CACHE ?= $(E2E_RESULTS)/pytest-cache", self.makefile)
        self.assertIn("--no-cache-dir", self.makefile)

        e2e_job = self.workflow.split("  e2e:\n", 1)[1].split("  integrity:\n", 1)[0]
        validator = "      - name: Run canonical E2E validator\n"
        before_validator = e2e_job.split(validator, 1)[0]
        self.assertNotIn("Generate and validate Integrity manifest", e2e_job)
        self.assertNotIn("integrity-manifest.json", before_validator)
        self.assertNotIn("make -C tools/mapjson", before_validator)

    def test_e2e_failure_upload_matches_validator_results(self) -> None:
        evidence_root = (
            "build/content-port/results/${{ matrix.target }}/${{ matrix.suite }}/**/"
        )
        for suffix in ("*.log", "*.png", "*.sav", "*.state", "capture-errors.txt"):
            with self.subTest(suffix=suffix):
                self.assertIn(evidence_root + suffix, self.workflow)
        self.assertNotIn("path: test-results/e2e/${{ matrix.suite }}/", self.workflow)


if __name__ == "__main__":
    unittest.main()
