from __future__ import annotations

from pathlib import Path
import re
import unittest


WORKFLOW = Path(".github/workflows/ci.yml")
MAKEFILE = Path("Makefile")


class CiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.makefile = MAKEFILE.read_text(encoding="utf-8")

    def test_dedicated_job_has_stable_required_check_name(self) -> None:
        self.assertRegex(
            self.workflow,
            r"(?m)^  donor-contracts:\n    name: Donor Contracts$",
        )

    def test_both_public_donors_are_exactly_pinned_without_credentials(self) -> None:
        for repository, revision, path in (
            (
                "PokemonHnS-Development/pokemonHnS",
                "751823abaf677020bcd72c45fe3e7cb2b8a576e4",
                ".references/pokemonHnS",
            ),
            (
                "evilchinesefood/PKMN-World",
                "d40affe26e58a20f445daad84af5e45be812e69f",
                ".references/PKMN-World",
            ),
        ):
            checkout = re.compile(
                rf"repository: {re.escape(repository)}\n"
                rf"          ref: {revision}\n"
                rf"          path: {re.escape(path)}\n"
                r"          persist-credentials: false\n"
                r"          fetch-depth: 0"
            )
            self.assertRegex(self.workflow, checkout)

    def test_required_mode_commands_and_failure_artifact_are_pinned(self) -> None:
        required_fragments = (
            'CONTENT_PORT_REQUIRE_DONORS: "1"',
            "make content-port-transaction-check",
            "-s tools/content_port/tests/donor -p 'test_*.py' -q",
            "test_check_rejects_loadable_unknown_asset_permission",
            "python3 -m tools.content_port check --port johto",
            "--donor-root .references",
            "--write-report build/content-port/donor-contract.json",
            "if: failure()",
            "name: donor-contract-failure-evidence",
            "build/content-port/donor-contract.json",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.workflow)

    def test_legacy_importer_is_not_a_ci_authority(self) -> None:
        self.assertNotIn("tools/johto_import", self.workflow)
        self.assertIn("make content-port-test", self.workflow)

    def test_transaction_guard_is_first_prerequisite(self) -> None:
        target_patterns = (
            r"^all: content-port-transaction-check ",
            r"^check: content-port-transaction-check ",
            r"^content-port-check: content-port-transaction-check$",
            r"^content-port-bundle: content-port-transaction-check$",
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


if __name__ == "__main__":
    unittest.main()
