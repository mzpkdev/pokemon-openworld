from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tools.content_port.donors import (
    authenticated_donor_snapshot,
    authenticate_donor,
    records_digest,
    source_tree_records,
)
from tools.content_port.errors import ContentPortError
from tools.content_port.model import DonorPin


class DonorTests(unittest.TestCase):
    def make_checkout(self, root: Path) -> DonorPin:
        subprocess.run(("git", "init", "-q", str(root)), check=True)
        (root / "z.txt").write_bytes(b"last")
        (root / "a.txt").write_bytes(b"first")
        subprocess.run(("git", "-C", str(root), "add", "a.txt", "z.txt"), check=True)
        subprocess.run(
            (
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ),
            check=True,
        )
        head = subprocess.run(
            ("git", "-C", str(root), "rev-parse", "HEAD"),
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        records = source_tree_records(root)
        return DonorPin(
            "fixture",
            "example/donor",
            head,
            records_digest(records),
            len(records),
            root,
        )

    def test_authenticates_commit_digest_and_file_count(self):
        with tempfile.TemporaryDirectory() as directory:
            pin = self.make_checkout(Path(directory))
            evidence = authenticate_donor(pin)
            self.assertEqual(evidence.commit, pin.commit)
            self.assertEqual(evidence.tree_digest, pin.tree_digest)
            self.assertEqual(evidence.file_count, 2)

    def test_commit_digest_and_count_mutations_fail_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            pin = self.make_checkout(Path(directory))
            mutations = (
                (replace(pin, commit="0" * 40), "does not match pin"),
                (replace(pin, tree_digest="0" * 64), "digest mismatch"),
                (replace(pin, file_count=pin.file_count + 1), "file count drift"),
            )
            for changed, message in mutations:
                with self.subTest(message=message):
                    with self.assertRaisesRegex(ContentPortError, message):
                        authenticate_donor(changed)

    def test_checkout_without_git_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "file").write_text("x", encoding="utf-8")
            pin = DonorPin("fixture", "example/donor", "0" * 40, "0" * 64, 1, root)
            with self.assertRaisesRegex(ContentPortError, "cannot authenticate"):
                authenticate_donor(pin, require_git=True)

    def test_stale_gitfile_falls_back_only_when_git_identity_is_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "file").write_text("authenticated bytes", encoding="utf-8")
            records = source_tree_records(root)
            pin = DonorPin(
                "fixture",
                "example/donor",
                "a" * 40,
                records_digest(records),
                len(records),
                root,
            )
            (root / ".git").write_text(
                "gitdir: ../../missing/modules/fixture\n", encoding="utf-8"
            )

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                evidence = authenticate_donor(pin, require_git=False)
                with self.assertRaisesRegex(ContentPortError, "cannot authenticate"):
                    authenticate_donor(pin, require_git=True)
                with self.assertRaisesRegex(ContentPortError, "digest mismatch"):
                    authenticate_donor(
                        replace(pin, tree_digest="0" * 64), require_git=False
                    )

            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(evidence.tree_digest, pin.tree_digest)
            self.assertEqual(evidence.file_count, pin.file_count)

    def test_generic_tree_includes_artifacts_unless_pin_explicitly_excludes_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pin = self.make_checkout(root)
            artifact = root / "pokemonworld.elf"
            artifact.write_bytes(b"generated output")
            self.assertIn(
                "pokemonworld.elf",
                {record["path"] for record in source_tree_records(root)},
            )
            with self.assertRaisesRegex(ContentPortError, "digest mismatch"):
                authenticate_donor(pin)
            evidence = authenticate_donor(
                replace(pin, excluded_paths=("pokemonworld.elf",))
            )
            self.assertEqual(evidence.tree_digest, pin.tree_digest)

    def test_output_directories_are_included_unless_explicitly_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pin = self.make_checkout(root)
            artifacts = ("build/unauthenticated.bin", "test-results/result.json")
            for relative in artifacts:
                path = root / relative
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(relative.encode())
            records = {record["path"] for record in source_tree_records(root)}
            self.assertTrue(set(artifacts).issubset(records))
            with self.assertRaisesRegex(ContentPortError, "digest mismatch"):
                authenticate_donor(pin)
            evidence = authenticate_donor(replace(pin, excluded_paths=artifacts))
            self.assertEqual(evidence.tree_digest, pin.tree_digest)
            self.assertEqual(evidence.file_count, pin.file_count)

    def test_excluded_paths_are_safe_exact_relative_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_checkout(root)
            for exclusions in (
                ("../outside",),
                ("/absolute",),
                ("nested//file",),
                ("windows\\path",),
                ("a.txt", "a.txt"),
            ):
                with (
                    self.subTest(exclusions=exclusions),
                    self.assertRaisesRegex(ContentPortError, "excluded path"),
                ):
                    source_tree_records(root, excluded_paths=exclusions)

    def test_authenticated_snapshot_is_a_private_byte_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pin = self.make_checkout(root)
            with authenticated_donor_snapshot((pin,)) as (snapshot,):
                source = root / "a.txt"
                copied = snapshot.root / "a.txt"
                self.assertFalse(os.path.samefile(source, copied))
                source.write_bytes(b"transient mutation")
                self.assertEqual(copied.read_bytes(), b"first")

    def test_authenticated_snapshot_mutation_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            pin = self.make_checkout(Path(directory))
            with self.assertRaisesRegex(
                ContentPortError, "snapshot changed during desired-state rendering"
            ):
                with authenticated_donor_snapshot((pin,)) as (snapshot,):
                    (snapshot.root / "a.txt").write_bytes(b"mutation")


if __name__ == "__main__":
    unittest.main()
