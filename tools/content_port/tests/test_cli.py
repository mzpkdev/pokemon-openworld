from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
from typing import Iterator, Mapping
import unittest
from contextlib import contextmanager, redirect_stderr
from dataclasses import dataclass
from unittest.mock import patch

from tools.content_port.cli import _bundle_current_state, check_port, main, parser
from tools.content_port.donors import records_digest, source_tree_records
from tools.content_port.errors import ContentPortError
from tools.content_port.model import DonorPin
from tools.content_port.ownership import (
    OwnershipManifest,
    OwnershipUnit,
    content_sha256,
)
from tools.content_port.update import canonical_bytes, validate_assets
from tools.content_port.transaction import (
    canonical_bundle_digest,
    guard_active,
    recover_transaction,
)


def git(repo: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=False
    )
    if process.returncode:
        raise AssertionError(process.stderr)
    return process.stdout


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode()


@dataclass(frozen=True)
class CheckDescriptor:
    assets: Mapping[str, object]
    donors: tuple[DonorPin, ...]
    donors_by_role: Mapping[str, DonorPin]


@contextmanager
def passthrough_donor_snapshot(
    pins: tuple[DonorPin, ...],
) -> Iterator[tuple[DonorPin, ...]]:
    yield pins


class TransactionRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        git(root, "init", "-q", "-b", "task/test")
        git(root, "config", "user.name", "Content Port Test")
        git(root, "config", "user.email", "content-port@example.invalid")
        (root / "alpha.txt").write_bytes(b"alpha\n")
        (root / "unrelated.txt").write_bytes(b"outside transaction\n")
        self.ownership = root / "tools/content_port/ports/fixture/ownership.json"
        self.ownership.parent.mkdir(parents=True)
        self.baseline_manifest = canonical(
            {
                "schemaVersion": 1,
                "port": "fixture",
                "units": [
                    {
                        "kind": "file",
                        "path": "alpha.txt",
                        "sha256": hashlib.sha256(b"alpha\n").hexdigest(),
                    }
                ],
            }
        )
        self.ownership.write_bytes(self.baseline_manifest)
        git(
            root,
            "add",
            "alpha.txt",
            "unrelated.txt",
            self.ownership.relative_to(root).as_posix(),
        )
        git(root, "commit", "-q", "-m", "fixture")
        self.head = git(root, "rev-parse", "HEAD").strip()
        self.ref = git(root, "symbolic-ref", "HEAD").strip()

    def bundle(
        self,
        *,
        binary: bool = False,
        install_manifest: bool = True,
        matching_manifest: bool = True,
    ) -> Path:
        original = (self.root / "alpha.txt").read_bytes()
        desired = b"beta\x00binary\n" if binary else b"beta\n"
        manifest = {
            "schemaVersion": 1,
            "port": "fixture",
            "units": [
                {
                    "kind": "file",
                    "path": "alpha.txt",
                    "sha256": hashlib.sha256(desired).hexdigest(),
                },
                {
                    "kind": "file",
                    "path": "created.bin",
                    "sha256": hashlib.sha256(b"\x00\xffnew\n").hexdigest(),
                },
            ],
        }
        (self.root / "alpha.txt").write_bytes(desired)
        (self.root / "created.bin").write_bytes(b"\x00\xffnew\n")
        patch_manifest = manifest
        if not matching_manifest:
            patch_manifest = {
                "schemaVersion": 1,
                "port": "fixture",
                "units": [manifest["units"][0]],
            }
        self.ownership.write_bytes(canonical(patch_manifest))
        git(self.root, "add", "-N", "created.bin")
        paths = ["alpha.txt", "created.bin"]
        if install_manifest:
            paths.append(self.ownership.relative_to(self.root).as_posix())
        patch = subprocess.run(
            [
                "git",
                "diff",
                "--binary",
                "--full-index",
                "--no-ext-diff",
                "--no-color",
                "HEAD",
                "--",
                *paths,
            ],
            cwd=self.root,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout
        (self.root / "alpha.txt").write_bytes(original)
        (self.root / "created.bin").unlink()
        self.ownership.write_bytes(self.baseline_manifest)
        git(self.root, "reset", "-q")
        self.assert_clean()

        bundle = self.root.parent / "bundle"
        bundle.mkdir()
        (bundle / "desired.patch").write_bytes(patch)
        (bundle / "ownership.json").write_bytes(canonical(manifest))
        report = {
            "schemaVersion": 1,
            "port": "fixture",
            "baseCommit": self.head,
            "patchSha256": hashlib.sha256(patch).hexdigest(),
            "ownedUnitCount": 2,
        }
        (bundle / "report.json").write_bytes(canonical(report))
        return bundle

    def assert_clean(self) -> None:
        assert git(self.root, "status", "--porcelain=v1") == ""


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        self.fixture = TransactionRepository(self.repo)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_parser_exposes_every_contract_command(self) -> None:
        help_text = parser().format_help()
        for command in (
            "check",
            "bundle",
            "apply",
            "resume",
            "recover",
            "donor-update",
            "migration-finalize",
            "transaction-check",
        ):
            self.assertIn(command, help_text)

    def test_bundle_keeps_compiler_desired_state_separate_from_preimage(self) -> None:
        desired_unit = OwnershipUnit("file", "new.txt", content_sha256(b"new\n"))
        desired = OwnershipManifest("fixture", (desired_unit,))
        payloads = {desired_unit.identity: b"new\n"}
        report = {"inventory": {"maps": 1}}
        output = self.repo.parent / "output"
        descriptor = object()
        revision = git(self.repo, "rev-parse", "HEAD").strip()
        with (
            patch("tools.content_port.cli.check_port", return_value=report) as check,
            patch(
                "tools.content_port.descriptor.load_port", return_value=descriptor
            ) as load,
            patch(
                "tools.content_port.materialize.derive_desired_state",
                return_value=(desired, payloads),
            ) as derive,
            patch(
                "tools.content_port.bundle.build_bundle",
                return_value=SimpleNamespace(sha256="a" * 64),
            ) as build,
        ):
            digest = _bundle_current_state(
                self.repo, "fixture", self.repo.parent, output
            )

        self.assertEqual(digest, "a" * 64)
        source = check.call_args.args[0]
        self.assertNotEqual(source, self.repo)
        self.assertFalse(source.exists())
        self.assertEqual(
            load.call_args.args[0],
            source / "tools/content_port/ports/fixture",
        )
        derive.assert_called_once_with(descriptor, source)
        build.assert_called_once_with(
            self.repo,
            output,
            desired,
            payloads,
            {"contract": report},
            revision=revision,
        )

    def test_bundle_keeps_captured_base_when_branch_advances_during_derivation(
        self,
    ) -> None:
        desired = OwnershipManifest("fixture", ())
        report = {"inventory": {"maps": 1}}
        descriptor = object()
        revision = git(self.repo, "rev-parse", "HEAD").strip()
        source_roots: list[Path] = []

        def derive(_descriptor: object, source: Path):
            source_roots.append(source)
            self.assertEqual(git(source, "rev-parse", "HEAD").strip(), revision)
            (self.repo / "advance.txt").write_bytes(b"advance\n")
            git(self.repo, "add", "advance.txt")
            git(self.repo, "commit", "-q", "-m", "advance branch")
            return desired, {}

        with (
            patch("tools.content_port.cli.check_port", return_value=report),
            patch("tools.content_port.descriptor.load_port", return_value=descriptor),
            patch(
                "tools.content_port.materialize.derive_desired_state",
                side_effect=derive,
            ),
            patch(
                "tools.content_port.bundle.build_bundle",
                return_value=SimpleNamespace(sha256="b" * 64),
            ) as build,
        ):
            self.assertEqual(
                _bundle_current_state(
                    self.repo, "fixture", self.repo.parent, self.repo.parent / "output"
                ),
                "b" * 64,
            )

        self.assertNotEqual(git(self.repo, "rev-parse", "HEAD").strip(), revision)
        self.assertEqual(len(source_roots), 1)
        self.assertNotEqual(source_roots[0], self.repo)
        self.assertFalse(source_roots[0].exists())
        self.assertEqual(build.call_args.kwargs["revision"], revision)

    def test_bundle_derivation_ignores_transient_caller_edit_and_restore(self) -> None:
        target = self.repo / "target.txt"
        target.write_bytes(b"stable\n")
        git(self.repo, "add", "target.txt")
        git(self.repo, "commit", "-q", "-m", "target input")
        revision = git(self.repo, "rev-parse", "HEAD").strip()
        desired = OwnershipManifest("fixture", ())

        def derive(_descriptor: object, source: Path):
            target.write_bytes(b"transient\n")
            self.assertEqual((source / "target.txt").read_bytes(), b"stable\n")
            target.write_bytes(b"stable\n")
            return desired, {}

        with (
            patch("tools.content_port.cli.check_port", return_value={}),
            patch("tools.content_port.descriptor.load_port", return_value=object()),
            patch(
                "tools.content_port.materialize.derive_desired_state",
                side_effect=derive,
            ),
            patch(
                "tools.content_port.bundle.build_bundle",
                return_value=SimpleNamespace(sha256="c" * 64),
            ) as build,
        ):
            self.assertEqual(
                _bundle_current_state(
                    self.repo, "fixture", self.repo.parent, self.repo.parent / "output"
                ),
                "c" * 64,
            )

        self.assertEqual(target.read_bytes(), b"stable\n")
        self.assertEqual(git(self.repo, "status", "--porcelain=v1"), "")
        self.assertEqual(build.call_args.kwargs["revision"], revision)

    def test_apply_stages_binary_bundle_without_moving_head_or_ref(self) -> None:
        bundle = self.fixture.bundle(binary=True)
        digest = canonical_bundle_digest(bundle)
        self.assertEqual(
            main(
                [
                    "apply",
                    "--repo",
                    str(self.repo),
                    "--bundle",
                    str(bundle),
                    "--sha256",
                    digest,
                ]
            ),
            0,
        )
        self.assertEqual((self.repo / "alpha.txt").read_bytes(), b"beta\x00binary\n")
        self.assertEqual((self.repo / "created.bin").read_bytes(), b"\x00\xffnew\n")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").strip(), self.fixture.head)
        self.assertEqual(
            git(self.repo, "symbolic-ref", "HEAD").strip(), self.fixture.ref
        )
        self.assertFalse(guard_active(self.repo))
        self.assertIn("alpha.txt", git(self.repo, "diff", "--cached", "--name-only"))

    def test_apply_rejects_dirty_non_task_and_corrupt_bundle(self) -> None:
        bundle = self.fixture.bundle()
        digest = canonical_bundle_digest(bundle)
        (self.repo / "dirty").write_text("dirty")
        error = io.StringIO()
        with redirect_stderr(error):
            self.assertEqual(
                main(
                    [
                        "apply",
                        "--repo",
                        str(self.repo),
                        "--bundle",
                        str(bundle),
                        "--sha256",
                        digest,
                    ]
                ),
                2,
            )
        self.assertIn("clean index and working tree", error.getvalue())
        (self.repo / "dirty").unlink()

        git(self.repo, "branch", "-m", "main")
        error = io.StringIO()
        with redirect_stderr(error):
            self.assertEqual(
                main(
                    [
                        "apply",
                        "--repo",
                        str(self.repo),
                        "--bundle",
                        str(bundle),
                        "--sha256",
                        digest,
                    ]
                ),
                2,
            )
        self.assertIn("task/* branch", error.getvalue())
        git(self.repo, "branch", "-m", "task/test")

        (bundle / "desired.patch").write_bytes(
            (bundle / "desired.patch").read_bytes() + b"corrupt"
        )
        error = io.StringIO()
        with redirect_stderr(error):
            self.assertEqual(
                main(
                    [
                        "apply",
                        "--repo",
                        str(self.repo),
                        "--bundle",
                        str(bundle),
                        "--sha256",
                        digest,
                    ]
                ),
                2,
            )
        self.assertIn("patch", error.getvalue())

    def test_recover_restores_exact_preimage_and_index(self) -> None:
        bundle = self.fixture.bundle()
        digest = canonical_bundle_digest(bundle)
        transaction = None
        from tools.content_port.transaction import ApplyTransaction

        transaction = ApplyTransaction.create(self.repo, bundle, digest)
        transaction.write_and_fsync_preimage()
        transaction.acquire_guard()
        transaction.apply_unit(transaction.units[0])
        transaction.record_completed(transaction.units[0])
        self.assertTrue(guard_active(self.repo))
        recover_transaction(self.repo)
        self.fixture.assert_clean()
        self.assertEqual((self.repo / "alpha.txt").read_bytes(), b"alpha\n")
        self.assertFalse((self.repo / "created.bin").exists())
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").strip(), self.fixture.head)

    def test_transaction_check_refuses_active_guard(self) -> None:
        bundle = self.fixture.bundle()
        digest = canonical_bundle_digest(bundle)
        from tools.content_port.transaction import ApplyTransaction

        transaction = ApplyTransaction.create(self.repo, bundle, digest)
        transaction.write_and_fsync_preimage()
        transaction.acquire_guard()
        error = io.StringIO()
        with redirect_stderr(error):
            self.assertEqual(main(["transaction-check", "--repo", str(self.repo)]), 2)
        self.assertIn("active content-port apply transaction", error.getvalue())
        recover_transaction(self.repo)

    def test_apply_rechecks_checked_ownership_before_touching_tree(self) -> None:
        bundle = self.fixture.bundle()

        (self.repo / "alpha.txt").write_bytes(b"unreviewed drift\n")
        git(self.repo, "add", "alpha.txt")
        git(self.repo, "commit", "-q", "-m", "drift")
        current = git(self.repo, "rev-parse", "HEAD").strip()
        report = json.loads((bundle / "report.json").read_text())
        report["baseCommit"] = current
        (bundle / "report.json").write_bytes(canonical(report))
        digest = canonical_bundle_digest(bundle)

        error = io.StringIO()
        with redirect_stderr(error):
            self.assertEqual(
                main(
                    [
                        "apply",
                        "--repo",
                        str(self.repo),
                        "--bundle",
                        str(bundle),
                        "--sha256",
                        digest,
                    ]
                ),
                2,
            )
        self.assertIn("unexpected edit to generated unit", error.getvalue())
        self.assertFalse(guard_active(self.repo))

    def test_apply_rejects_bundle_that_omits_its_manifest_update(self) -> None:
        bundle = self.fixture.bundle(install_manifest=False)
        digest = canonical_bundle_digest(bundle)
        error = io.StringIO()
        with redirect_stderr(error):
            self.assertEqual(
                main(
                    [
                        "apply",
                        "--repo",
                        str(self.repo),
                        "--bundle",
                        str(bundle),
                        "--sha256",
                        digest,
                    ]
                ),
                2,
            )
        self.assertIn("does not install its ownership.json", error.getvalue())
        self.fixture.assert_clean()
        self.assertFalse(guard_active(self.repo))

    def test_apply_rejects_patch_with_a_different_manifest(self) -> None:
        bundle = self.fixture.bundle(matching_manifest=False)
        digest = canonical_bundle_digest(bundle)
        error = io.StringIO()
        with redirect_stderr(error):
            self.assertEqual(
                main(
                    [
                        "apply",
                        "--repo",
                        str(self.repo),
                        "--bundle",
                        str(bundle),
                        "--sha256",
                        digest,
                    ]
                ),
                2,
            )
        self.assertIn("differs from the bundle", error.getvalue())
        self.fixture.assert_clean()
        self.assertFalse(guard_active(self.repo))

    def test_check_runs_real_source_validation_and_meaningful_compare(self) -> None:
        donor = DonorPin("donor", "example/donor", "a" * 40, "b" * 64, 1, self.repo)
        descriptor = CheckDescriptor(
            assets={"schemaVersion": 1, "permissionRecords": {}, "assets": ()},
            donors=(donor,),
            donors_by_role={"mechanical": donor, "content": donor},
        )

        class Contract:
            def to_report(self) -> dict[str, object]:
                return {
                    "inventory": {"maps": 1},
                    "closure": {
                        "maps": ["Map"],
                        "layouts": [],
                        "groups": [],
                        "sections": [],
                        "tilesets": [],
                        "deferred_edges": [],
                        "symbols": ["Map_Script"],
                    },
                    "evidence": {
                        "graphDigest": "c" * 64,
                        "attributeFormats": {"fixture": {"format": "U16"}},
                        "inputs": [
                            {"path": "map.json", "bytes": 1, "sha256": "d" * 64}
                        ],
                    },
                }

        expected = {
            "schemaVersion": 1,
            "producer": "legacy",
            "inventory": {"maps": 1},
            "closure": {
                "maps": ["Map"],
                "layouts": [],
                "groups": [],
                "sections": [],
                "tilesets": [],
                "deferred_edges": [],
                "symbols": ["Map_Script"],
            },
            "evidence": {
                "attributeFormats": {"fixture": {"format": "U16"}},
                "inputs": [{"path": "map.json", "bytes": 1, "sha256": "d" * 64}],
                "donors": {
                    "mechanical": {
                        "commit": donor.commit,
                        "sourceTreeDigest": donor.tree_digest,
                        "fileCount": donor.file_count,
                    },
                    "content": {
                        "commit": donor.commit,
                        "sourceTreeDigest": donor.tree_digest,
                        "fileCount": donor.file_count,
                    },
                },
            },
        }
        comparison = self.repo / "expected.json"
        comparison.write_bytes(canonical(expected))
        with (
            patch(
                "tools.content_port.descriptor.load_port",
                return_value=descriptor,
            ),
            patch(
                "tools.content_port.donors.authenticated_donor_snapshot",
                side_effect=passthrough_donor_snapshot,
            ),
            patch(
                "tools.content_port.sources.validate_port_sources",
                return_value=Contract(),
            ) as validate,
        ):
            check_port(self.repo, "fixture", self.repo, compare_report=comparison)
        validate.assert_called_once()

        expected["closure"]["maps"] = ["Mutated"]
        comparison.write_bytes(canonical(expected))
        with (
            patch(
                "tools.content_port.descriptor.load_port",
                return_value=descriptor,
            ),
            patch(
                "tools.content_port.donors.authenticated_donor_snapshot",
                side_effect=passthrough_donor_snapshot,
            ),
            patch(
                "tools.content_port.sources.validate_port_sources",
                return_value=Contract(),
            ),
        ):
            with self.assertRaisesRegex(ContentPortError, "closure field maps"):
                check_port(self.repo, "fixture", self.repo, compare_report=comparison)

        for field, mutated in (
            ("symbols", ["Mutated_Script"]),
            ("attributeFormats", {"fixture": {"format": "U32"}}),
            ("inputs", [{"path": "map.json", "bytes": 2, "sha256": "d" * 64}]),
        ):
            expected["closure"]["maps"] = ["Map"]
            if field == "symbols":
                expected["closure"][field] = mutated
            else:
                expected["closure"]["symbols"] = ["Map_Script"]
                expected["evidence"][field] = mutated
            comparison.write_bytes(canonical(expected))
            with (
                patch(
                    "tools.content_port.descriptor.load_port",
                    return_value=descriptor,
                ),
                patch(
                    "tools.content_port.donors.authenticated_donor_snapshot",
                    side_effect=passthrough_donor_snapshot,
                ),
                patch(
                    "tools.content_port.sources.validate_port_sources",
                    return_value=Contract(),
                ),
            ):
                with self.assertRaisesRegex(ContentPortError, field):
                    check_port(
                        self.repo, "fixture", self.repo, compare_report=comparison
                    )
            if field != "symbols":
                expected["evidence"][field] = Contract().to_report()["evidence"][field]

    def test_check_uses_immutable_donor_snapshot_during_validation(self) -> None:
        donor_root = self.repo.parent / "donor"
        donor_root.mkdir()
        git(donor_root, "init", "-q")
        git(donor_root, "config", "user.name", "Content Port Test")
        git(donor_root, "config", "user.email", "content-port@example.invalid")
        donor_file = donor_root / "source.txt"
        donor_file.write_bytes(b"stable\n")
        git(donor_root, "add", "source.txt")
        git(donor_root, "commit", "-q", "-m", "donor")
        records = source_tree_records(donor_root)
        donor = DonorPin(
            "donor",
            "example/donor",
            git(donor_root, "rev-parse", "HEAD").strip(),
            records_digest(records),
            len(records),
            donor_root,
        )
        descriptor = CheckDescriptor(
            assets={"schemaVersion": 1, "permissionRecords": {}, "assets": ()},
            donors=(donor,),
            donors_by_role={"content": donor},
        )

        class Contract:
            def to_report(self) -> dict[str, object]:
                return {"evidence": {"inputs": []}}

        def validate(snapshot_descriptor: CheckDescriptor, _repo: Path) -> Contract:
            snapshot = snapshot_descriptor.donors_by_role["content"]
            self.assertFalse(os.path.samefile(snapshot.root, donor.root))
            donor_file.write_bytes(b"transient\n")
            try:
                self.assertEqual(
                    (snapshot.root / "source.txt").read_bytes(), b"stable\n"
                )
            finally:
                donor_file.write_bytes(b"stable\n")
            return Contract()

        with (
            patch("tools.content_port.descriptor.load_port", return_value=descriptor),
            patch(
                "tools.content_port.sources.validate_port_sources",
                side_effect=validate,
            ),
        ):
            report = check_port(self.repo, "fixture", donor_root)

        self.assertEqual(
            report["evidence"]["donors"],
            {
                "content": {
                    "commit": donor.commit,
                    "sourceTreeDigest": donor.tree_digest,
                    "fileCount": donor.file_count,
                }
            },
        )
        self.assertEqual(git(donor_root, "status", "--porcelain=v1"), "")

    def test_check_propagates_source_drift(self) -> None:
        descriptor = CheckDescriptor(
            assets={"schemaVersion": 1, "permissionRecords": {}, "assets": ()},
            donors=(),
            donors_by_role={},
        )
        with (
            patch(
                "tools.content_port.descriptor.load_port",
                return_value=descriptor,
            ),
            patch(
                "tools.content_port.donors.authenticated_donor_snapshot",
                side_effect=passthrough_donor_snapshot,
            ),
            patch(
                "tools.content_port.sources.validate_port_sources",
                side_effect=ContentPortError("source preimage drift"),
            ),
        ):
            with self.assertRaisesRegex(ContentPortError, "source preimage drift"):
                check_port(self.repo, "fixture", self.repo)

    def test_check_rejects_loadable_unknown_asset_permission(self) -> None:
        evidence = self.repo / "permission.txt"
        evidence.write_text("fixture permission\n")
        permission_record = {
            "decision": "reviewed",
            "path": "permission.txt",
            "permission": "unknown",
            "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        }
        permission_digest = hashlib.sha256(
            canonical_bytes(permission_record)
        ).hexdigest()
        asset = {
            "key": "fixture-art",
            "source": "content",
            "donor": "content",
            "sourcePath": "asset.bin",
            "semanticTarget": "graphics/fixture/asset.bin",
            "sourceSha256": "a" * 64,
            "targetSha256": "a" * 64,
            "conversionCommand": ("copy-bytes",),
            "permission": "unknown",
            "permissionEvidence": permission_digest,
            "capability": "environment-assets",
            "supportState": "enabled",
        }
        policy = {
            "schemaVersion": 1,
            "permissionRecords": {permission_digest: permission_record},
            "assets": (asset,),
        }
        validate_assets(
            policy,
            evidence_root=self.repo,
            require_redistributable=False,
        )
        descriptor = CheckDescriptor(assets=policy, donors=(), donors_by_role={})
        with (
            patch(
                "tools.content_port.descriptor.load_port",
                return_value=descriptor,
            ),
            patch("tools.content_port.donors.authenticated_donor_snapshot") as snapshot,
            patch("tools.content_port.sources.validate_port_sources"),
            self.assertRaisesRegex(ContentPortError, "permission is unknown"),
        ):
            check_port(self.repo, "fixture", self.repo)
        snapshot.assert_not_called()


if __name__ == "__main__":
    unittest.main()
