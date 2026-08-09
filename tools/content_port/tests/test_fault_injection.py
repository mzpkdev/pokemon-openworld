from __future__ import annotations

import gc
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from tools.content_port.bundle import BUNDLE_FILES, _publish_artifacts, build_bundle
from tools.content_port.faults import InjectedFault
from tools.content_port.errors import ContentPortError
from tools.content_port.ownership import (
    OwnershipManifest,
    OwnershipUnit,
    canonical_json,
    content_sha256,
)
from tools.content_port.tests.test_cli import TransactionRepository, git
from tools.content_port.transaction import (
    ApplyTransaction,
    apply_bundle,
    canonical_bundle_digest,
    guard_active,
    recover_transaction,
    resume_transaction,
    transaction_lifetime_lock,
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

    def test_partial_index_fault_keeps_git_commit_blocked(self) -> None:
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

            commit = subprocess.run(
                ["git", "commit", "-q", "-m", "mixed transaction state"],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(commit.returncode, 0)
            self.assertIn("cannot lock ref", commit.stderr)
            self.assertEqual(git(repo, "rev-parse", "HEAD").strip(), fixture.head)
            self.assertTrue(guard_active(repo))

            recover_transaction(repo)
            fixture.assert_clean()
            self.assertFalse(guard_active(repo))
        finally:
            temporary.cleanup()

    def test_recover_refuses_changed_owned_path_without_mutation(self) -> None:
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
            (repo / "alpha.txt").write_bytes(b"user edit\n")
            cached_before = git(repo, "diff", "--cached", "--binary")

            with self.assertRaisesRegex(
                ContentPortError, "preserve the edit elsewhere"
            ):
                recover_transaction(repo)

            self.assertEqual((repo / "alpha.txt").read_bytes(), b"user edit\n")
            self.assertEqual(git(repo, "diff", "--cached", "--binary"), cached_before)
            self.assertTrue(guard_active(repo))

            (repo / "alpha.txt").write_bytes(b"beta\x00binary\n")
            recover_transaction(repo)
            fixture.assert_clean()
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

    def test_live_creation_lock_blocks_recovery_and_a_second_creator(
        self,
    ) -> None:
        temporary, repo, fixture, bundle, digest = self._fixture()
        try:
            transaction = ApplyTransaction.create(repo, bundle, digest)
            self.assertTrue(guard_active(repo))
            with self.assertRaisesRegex(ContentPortError, "still being created"):
                recover_transaction(repo)
            with self.assertRaisesRegex(ContentPortError, "active|being created"):
                ApplyTransaction.create(repo, bundle, digest)
            del transaction
            gc.collect()
            recover_transaction(repo)
            self.assertFalse(guard_active(repo))
            fixture.assert_clean()
        finally:
            temporary.cleanup()

    def test_recovery_refuses_creation_lock_without_provable_liveness(self) -> None:
        temporary, repo, fixture, _, _ = self._fixture()
        try:
            state, _, _ = transaction_paths(repo)
            state.mkdir(parents=True, exist_ok=True)
            (state / "creation.lock").write_text(
                '{"schemaVersion":1,"transactionId":"legacy"}\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ContentPortError, "cannot be established"):
                recover_transaction(repo)
            self.assertTrue(guard_active(repo))
            fixture.assert_clean()
        finally:
            temporary.cleanup()

    def test_initial_run_refuses_head_advanced_after_create_without_writing(
        self,
    ) -> None:
        temporary, repo, fixture, bundle, digest = self._fixture()
        try:
            transaction = ApplyTransaction.create(repo, bundle, digest)
            git(repo, "commit", "--allow-empty", "-q", "-m", "external advance")
            advanced = git(repo, "rev-parse", "HEAD").strip()
            self.assertNotEqual(advanced, fixture.head)

            transaction.write_and_fsync_preimage()
            transaction.acquire_guard()
            with self.assertRaisesRegex(
                ContentPortError, "HEAD or task branch changed"
            ):
                transaction.run()

            self.assertTrue(guard_active(repo))
            self.assertEqual((repo / "alpha.txt").read_bytes(), b"alpha\n")
            self.assertFalse((repo / "created.bin").exists())

            git(repo, "update-ref", "refs/heads/task/test", fixture.head, advanced)
            recover_transaction(repo)
            fixture.assert_clean()
            self.assertFalse(guard_active(repo))
        finally:
            temporary.cleanup()

    def test_initial_run_compares_owned_preimage_before_publication(self) -> None:
        temporary, repo, fixture, bundle, digest = self._fixture()
        try:
            from tools.content_port.transaction import (
                _capture_preimages as real_capture_preimages,
            )

            def capture_then_edit(repo_root: Path, expected: object):
                captured = real_capture_preimages(repo_root, expected)  # type: ignore[arg-type]
                (repo_root / "alpha.txt").write_bytes(b"concurrent user edit\n")
                return captured

            with patch(
                "tools.content_port.transaction._capture_preimages",
                side_effect=capture_then_edit,
            ):
                transaction = ApplyTransaction.create(repo, bundle, digest)
            transaction.write_and_fsync_preimage()
            transaction.acquire_guard()

            with self.assertRaisesRegex(ContentPortError, "refusing to apply"):
                transaction.run()
            self.assertEqual(
                (repo / "alpha.txt").read_bytes(), b"concurrent user edit\n"
            )
            self.assertFalse((repo / "created.bin").exists())
            self.assertTrue(guard_active(repo))

            (repo / "alpha.txt").write_bytes(b"alpha\n")
            recover_transaction(repo)
            fixture.assert_clean()
        finally:
            temporary.cleanup()

    def test_build_read_lock_blocks_apply_until_build_finishes(self) -> None:
        temporary, repo, _, bundle, digest = self._fixture()
        completed = threading.Event()
        started = threading.Event()

        def apply() -> None:
            started.set()
            apply_bundle(repo, bundle, digest)
            completed.set()

        try:
            with transaction_lifetime_lock(repo, exclusive=False):
                worker = threading.Thread(target=apply)
                worker.start()
                self.assertTrue(started.wait(timeout=2.0))
                state, _, _ = transaction_paths(repo)
                contender = subprocess.run(
                    [
                        "python3",
                        "-c",
                        (
                            "import fcntl,os,sys; "
                            "fd=os.open(sys.argv[1],os.O_RDWR); "
                            "fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)"
                        ),
                        str(state / "lifetime.lock"),
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(contender.returncode, 0)
                self.assertFalse(completed.is_set())
            worker.join(timeout=5.0)
            self.assertFalse(worker.is_alive())
            self.assertTrue(completed.is_set())
        finally:
            temporary.cleanup()

    def test_non_dry_run_make_flags_cannot_bypass_build_lock(self) -> None:
        repo = Path(__file__).resolve().parents[3]
        commands = (
            ["make", "--no-print-directory", "content-port-transaction-check"],
            [
                "make",
                "--silent",
                "--keep-going",
                "-rR",
                "content-port-transaction-check",
            ],
        )

        for command in commands:
            with self.subTest(flags=command[1:-1]):
                process: subprocess.Popen[str] | None = None
                try:
                    with transaction_lifetime_lock(repo, exclusive=True):
                        process = subprocess.Popen(
                            command,
                            cwd=repo,
                            text=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        )
                        with self.assertRaises(subprocess.TimeoutExpired):
                            process.wait(timeout=0.25)
                    stdout, stderr = process.communicate(timeout=5.0)
                    self.assertEqual(
                        process.returncode,
                        0,
                        msg=f"stdout:\n{stdout}\nstderr:\n{stderr}",
                    )
                finally:
                    if process is not None and process.poll() is None:
                        process.terminate()
                        process.wait(timeout=5.0)

    def test_ref_cannot_move_between_identity_check_and_publication(self) -> None:
        temporary, repo, fixture, bundle, digest = self._fixture()
        try:
            tree = git(repo, "rev-parse", "HEAD^{tree}").strip()
            created = subprocess.run(
                ["git", "commit-tree", tree, "-p", fixture.head],
                cwd=repo,
                input="external advance\n",
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            transaction = ApplyTransaction.create(repo, bundle, digest)
            transaction.write_and_fsync_preimage()
            transaction.acquire_guard()
            real_apply = transaction.apply_unit
            attempts: list[subprocess.CompletedProcess[str]] = []

            def race_ref_update(unit: object) -> None:
                if not attempts:
                    attempts.append(
                        subprocess.run(
                            [
                                "git",
                                "update-ref",
                                "refs/heads/task/test",
                                created,
                                fixture.head,
                            ],
                            cwd=repo,
                            text=True,
                            capture_output=True,
                            check=False,
                        )
                    )
                real_apply(unit)  # type: ignore[arg-type]

            with patch.object(transaction, "apply_unit", side_effect=race_ref_update):
                transaction.run()

            self.assertEqual(len(attempts), 1)
            self.assertNotEqual(attempts[0].returncode, 0)
            self.assertIn("cannot lock ref", attempts[0].stderr)
            self.assertEqual(git(repo, "rev-parse", "HEAD").strip(), fixture.head)
            self.assertEqual((repo / "alpha.txt").read_bytes(), b"beta\x00binary\n")
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
            del transaction
            gc.collect()
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

    def test_bundle_publication_is_never_a_mixed_generation(self) -> None:
        old = {name: f"old:{name}\n".encode() for name in BUNDLE_FILES}
        new = {name: f"new:{name}\n".encode() for name in BUNDLE_FILES}
        checkpoints = [
            *(f"after-bundle-fsync:{name}" for name in BUNDLE_FILES),
            *(f"after-bundle-rename:{name}" for name in BUNDLE_FILES),
        ]
        for fault in checkpoints:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "bundle"
                _publish_artifacts(output, old)
                with patch.dict(
                    os.environ,
                    {
                        "CONTENT_PORT_FAULT_AT": fault,
                        "CONTENT_PORT_FAULT_ACTION": "raise",
                    },
                    clear=False,
                ):
                    with self.assertRaises(InjectedFault):
                        _publish_artifacts(output, new)
                visible = {name: (output / name).read_bytes() for name in BUNDLE_FILES}
                self.assertIn(visible, (old, new))

    def test_first_bundle_publication_is_absent_or_complete_at_every_fault(
        self,
    ) -> None:
        new = {name: f"new:{name}\n".encode() for name in BUNDLE_FILES}
        checkpoints = [
            *(f"after-bundle-fsync:{name}" for name in BUNDLE_FILES),
            *(f"after-bundle-rename:{name}" for name in BUNDLE_FILES),
        ]
        for fault in checkpoints:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "bundle"
                with patch.dict(
                    os.environ,
                    {
                        "CONTENT_PORT_FAULT_AT": fault,
                        "CONTENT_PORT_FAULT_ACTION": "raise",
                    },
                    clear=False,
                ):
                    with self.assertRaises(InjectedFault):
                        _publish_artifacts(output, new)
                if output.exists():
                    visible = {
                        name: (output / name).read_bytes() for name in BUNDLE_FILES
                    }
                    self.assertEqual(visible, new)

    def test_render_and_validation_faults_leave_repo_and_bundle_unchanged(self) -> None:
        cases = (
            ("after-render:('file', 'new.txt')", []),
            ("after-validation:0", [("python3", "-c", "pass")]),
        )
        for fault, commands in cases:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                repo = base / "repo"
                repo.mkdir()
                git(repo, "init", "-q", "-b", "task/test")
                git(repo, "config", "user.name", "Content Port Test")
                git(repo, "config", "user.email", "content-port@example.invalid")
                (repo / "base.txt").write_bytes(b"base\n")
                manifest_path = repo / "tools/content_port/ports/test/ownership.json"
                manifest_path.parent.mkdir(parents=True)
                manifest_path.write_bytes(
                    canonical_json(OwnershipManifest("test", ()).to_json())
                )
                git(repo, "add", "--all", ".")
                git(repo, "commit", "-q", "-m", "base")
                output = base / "bundle"
                old_unit = OwnershipUnit("file", "old.txt", content_sha256(b"old\n"))
                build_bundle(
                    repo,
                    output,
                    OwnershipManifest("test", (old_unit,)),
                    {old_unit.identity: b"old\n"},
                    validation_commands=[],
                )
                published = {
                    name: (output / name).read_bytes() for name in BUNDLE_FILES
                }
                new_unit = OwnershipUnit("file", "new.txt", content_sha256(b"new\n"))

                with patch.dict(
                    os.environ,
                    {
                        "CONTENT_PORT_FAULT_AT": fault,
                        "CONTENT_PORT_FAULT_ACTION": "raise",
                    },
                    clear=False,
                ):
                    with self.assertRaises(InjectedFault):
                        build_bundle(
                            repo,
                            output,
                            OwnershipManifest("test", (new_unit,)),
                            {new_unit.identity: b"new\n"},
                            validation_commands=commands,
                        )

                self.assertEqual(
                    {name: (output / name).read_bytes() for name in BUNDLE_FILES},
                    published,
                )
                self.assertEqual(git(repo, "status", "--porcelain=v1"), "")
                worktrees = git(repo, "worktree", "list", "--porcelain")
                self.assertEqual(
                    sum(
                        line.startswith("worktree ") for line in worktrees.splitlines()
                    ),
                    1,
                )


if __name__ == "__main__":
    unittest.main()
