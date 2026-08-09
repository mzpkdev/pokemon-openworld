from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tools.content_port.faults import InjectedFault
from tools.content_port.errors import ContentPortError
from tools.content_port.tests.test_cli import TransactionRepository, git
from tools.content_port.transaction import (
    ApplyTransaction,
    apply_bundle,
    canonical_bundle_digest,
    guard_active,
    recover_transaction,
    resume_transaction,
    transaction_paths,
)


class FaultInjectionTests(unittest.TestCase):
    def _fixture(
        self,
    ) -> tuple[
        tempfile.TemporaryDirectory[str], Path, TransactionRepository, Path, str
    ]:
        temporary = tempfile.TemporaryDirectory()
        repo = Path(temporary.name) / "repo"
        repo.mkdir()
        fixture = TransactionRepository(repo)
        bundle = fixture.bundle(binary=True)
        return temporary, repo, fixture, bundle, canonical_bundle_digest(bundle)

    def test_every_apply_write_is_exactly_recoverable(self) -> None:
        for checkpoint in ("after-apply:alpha.txt", "after-apply:created.bin"):
            with self.subTest(checkpoint=checkpoint):
                temporary, repo, fixture, bundle, digest = self._fixture()
                try:
                    with patch.dict(
                        os.environ,
                        {
                            "CONTENT_PORT_FAULT_AT": checkpoint,
                            "CONTENT_PORT_FAULT_ACTION": "raise",
                        },
                        clear=False,
                    ):
                        with self.assertRaises(InjectedFault):
                            apply_bundle(repo, bundle, digest)
                    self.assertTrue(guard_active(repo))
                    self.assertEqual(
                        git(repo, "rev-parse", "HEAD").strip(), fixture.head
                    )
                    recover_transaction(repo)
                    fixture.assert_clean()
                    self.assertEqual((repo / "alpha.txt").read_bytes(), b"alpha\n")
                    self.assertFalse((repo / "created.bin").exists())
                finally:
                    temporary.cleanup()

    def test_every_apply_write_is_exactly_resumable(self) -> None:
        for checkpoint in ("after-apply:alpha.txt", "after-index:alpha.txt"):
            with self.subTest(checkpoint=checkpoint):
                temporary, repo, fixture, bundle, digest = self._fixture()
                try:
                    with patch.dict(
                        os.environ,
                        {
                            "CONTENT_PORT_FAULT_AT": checkpoint,
                            "CONTENT_PORT_FAULT_ACTION": "raise",
                        },
                        clear=False,
                    ):
                        with self.assertRaises(InjectedFault):
                            apply_bundle(repo, bundle, digest)
                    resume_transaction(repo)
                    self.assertFalse(guard_active(repo))
                    self.assertEqual(
                        (repo / "alpha.txt").read_bytes(), b"beta\x00binary\n"
                    )
                    self.assertEqual(
                        (repo / "created.bin").read_bytes(), b"\x00\xffnew\n"
                    )
                    self.assertEqual(
                        git(repo, "rev-parse", "HEAD").strip(), fixture.head
                    )
                finally:
                    temporary.cleanup()

    def test_guard_exists_at_journal_and_guard_checkpoints(self) -> None:
        for checkpoint in ("after-journal-fsync", "after-guard-create"):
            with self.subTest(checkpoint=checkpoint):
                temporary, repo, fixture, bundle, digest = self._fixture()
                try:
                    with patch.dict(
                        os.environ,
                        {
                            "CONTENT_PORT_FAULT_AT": checkpoint,
                            "CONTENT_PORT_FAULT_ACTION": "raise",
                        },
                        clear=False,
                    ):
                        with self.assertRaises(InjectedFault):
                            apply_bundle(repo, bundle, digest)
                    self.assertTrue(guard_active(repo))
                    fixture.assert_clean()
                    recover_transaction(repo)
                finally:
                    temporary.cleanup()

    def test_recovery_itself_can_resume_after_each_path(self) -> None:
        temporary, repo, fixture, bundle, digest = self._fixture()
        try:
            with patch.dict(
                os.environ,
                {
                    "CONTENT_PORT_FAULT_AT": "after-apply:created.bin",
                    "CONTENT_PORT_FAULT_ACTION": "raise",
                },
                clear=False,
            ):
                with self.assertRaises(InjectedFault):
                    apply_bundle(repo, bundle, digest)
            with patch.dict(
                os.environ,
                {
                    "CONTENT_PORT_FAULT_AT": "after-recover:created.bin",
                    "CONTENT_PORT_FAULT_ACTION": "raise",
                },
                clear=False,
            ):
                with self.assertRaises(InjectedFault):
                    recover_transaction(repo)
            self.assertTrue(guard_active(repo))
            recover_transaction(repo)
            fixture.assert_clean()
            self.assertEqual(git(repo, "rev-parse", "HEAD").strip(), fixture.head)
        finally:
            temporary.cleanup()

    def test_corrupt_journal_cannot_resume(self) -> None:
        temporary, repo, fixture, bundle, digest = self._fixture()
        try:
            with patch.dict(
                os.environ,
                {
                    "CONTENT_PORT_FAULT_AT": "after-index:alpha.txt",
                    "CONTENT_PORT_FAULT_ACTION": "raise",
                },
                clear=False,
            ):
                with self.assertRaises(InjectedFault):
                    apply_bundle(repo, bundle, digest)
            _, _, journal = transaction_paths(repo)
            journal.write_text(
                journal.read_text().replace('"completed":[]', '"completed":["fake"]')
            )
            with self.assertRaisesRegex(ContentPortError, "journal checksum mismatch"):
                resume_transaction(repo)
        finally:
            temporary.cleanup()

    def test_fault_after_guard_removal_exposes_only_complete_result(self) -> None:
        temporary, repo, fixture, bundle, digest = self._fixture()
        try:
            with patch.dict(
                os.environ,
                {
                    "CONTENT_PORT_FAULT_AT": "after-guard-remove",
                    "CONTENT_PORT_FAULT_ACTION": "raise",
                },
                clear=False,
            ):
                with self.assertRaises(InjectedFault):
                    apply_bundle(repo, bundle, digest)
            self.assertFalse(guard_active(repo))
            self.assertEqual((repo / "alpha.txt").read_bytes(), b"beta\x00binary\n")
            self.assertEqual(git(repo, "rev-parse", "HEAD").strip(), fixture.head)
        finally:
            temporary.cleanup()

    def test_creation_lock_blocks_a_race_and_is_recoverable_before_journal(
        self,
    ) -> None:
        temporary, repo, fixture, bundle, digest = self._fixture()
        try:
            ApplyTransaction.create(repo, bundle, digest)
            self.assertTrue(guard_active(repo))
            with self.assertRaisesRegex(ContentPortError, "active|being created"):
                ApplyTransaction.create(repo, bundle, digest)
            recover_transaction(repo)
            self.assertFalse(guard_active(repo))
            fixture.assert_clean()
        finally:
            temporary.cleanup()

    def test_resume_refuses_an_unowned_edit_while_guarded(self) -> None:
        temporary, repo, fixture, bundle, digest = self._fixture()
        try:
            with patch.dict(
                os.environ,
                {
                    "CONTENT_PORT_FAULT_AT": "after-index:alpha.txt",
                    "CONTENT_PORT_FAULT_ACTION": "raise",
                },
                clear=False,
            ):
                with self.assertRaises(InjectedFault):
                    apply_bundle(repo, bundle, digest)
            (repo / "unrelated.txt").write_bytes(b"tampered\n")
            with self.assertRaisesRegex(ContentPortError, "outside the transaction"):
                resume_transaction(repo)
            self.assertTrue(guard_active(repo))
        finally:
            temporary.cleanup()

    def test_recover_repairs_a_crash_during_atomic_guard_publication(self) -> None:
        temporary, repo, fixture, bundle, digest = self._fixture()
        try:
            transaction = ApplyTransaction.create(repo, bundle, digest)
            transaction.write_and_fsync_preimage()
            _, guard, _ = transaction_paths(repo)
            guard.write_bytes(b"")
            recover_transaction(repo)
            self.assertFalse(guard_active(repo))
            fixture.assert_clean()
        finally:
            temporary.cleanup()

    def test_bundle_swap_after_snapshot_cannot_change_applied_bytes(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        repo = Path(temporary.name) / "repo"
        repo.mkdir()
        fixture = TransactionRepository(repo)
        reviewed = fixture.bundle(binary=False)
        digest = canonical_bundle_digest(reviewed)
        try:
            text_bundle = reviewed.parent / "text-bundle"
            reviewed.rename(text_bundle)
            binary_bundle = fixture.bundle(binary=True)
            binary_saved = binary_bundle.parent / "binary-bundle"
            binary_bundle.rename(binary_saved)
            text_bundle.rename(reviewed)

            from tools.content_port.bundle import verify_bundle as real_verify

            def verify_then_swap(snapshot: Path) -> str:
                result = real_verify(snapshot)
                for name in ("desired.patch", "ownership.json", "report.json"):
                    shutil.copyfile(binary_saved / name, reviewed / name)
                return result

            with patch(
                "tools.content_port.bundle.verify_bundle", side_effect=verify_then_swap
            ):
                apply_bundle(repo, reviewed, digest)
            self.assertEqual((repo / "alpha.txt").read_bytes(), b"beta\n")
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
