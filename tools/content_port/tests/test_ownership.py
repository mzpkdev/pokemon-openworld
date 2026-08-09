from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.content_port.errors import ContentPortError
from tools.content_port.ownership import (
    OwnershipManifest,
    OwnershipUnit,
    canonical_json,
    content_sha256,
    reconcile_owned,
    require_exact_file_ownership,
    verify_owned_baseline,
)
from tools.content_port.renderers import RenderContext, RenderUnit, render_units


def file_unit(path: str, content: bytes) -> OwnershipUnit:
    return OwnershipUnit("file", path, content_sha256(content))


class OwnershipTests(unittest.TestCase):
    def test_owned_section_excludes_unowned_blank_separator(self) -> None:
        from tools.content_port.ownership import extract_owned_content

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "fixture.h"
            section = (
                b"// CONTENT PORT BEGIN fixture:generated\n"
                b"value\n"
                b"// CONTENT PORT END fixture:generated\n"
            )
            path.write_bytes(section + b"\nhand_owned\n")
            unit = OwnershipUnit(
                "section", "fixture.h", content_sha256(section), name="generated"
            )
            self.assertEqual(extract_owned_content(root, "fixture", unit), section)

    def test_checked_johto_manifest_matches_tree_and_asset_ledger(self) -> None:
        root = Path(__file__).resolve().parents[3]
        port = root / "tools/content_port/ports/johto"
        manifest = OwnershipManifest.load(port / "ownership.json")
        manifest.verify(root)
        assets = json.loads((port / "assets.json").read_text())["assets"]
        expected_assets = {asset["semanticTarget"] for asset in assets}
        owned_assets = {
            unit.path
            for unit in manifest.units
            if unit.kind == "file"
            and unit.path.startswith(("data/tilesets/", "data/layouts/"))
        }
        self.assertEqual(owned_assets, expected_assets)

    def test_changed_generated_file_fails_before_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owned").write_bytes(b"edited")
            old = OwnershipManifest("test", (file_unit("owned", b"expected"),))
            with self.assertRaisesRegex(ContentPortError, "unexpected edit"):
                reconcile_owned(root, old, OwnershipManifest("test", ()), {})
            self.assertEqual((root / "owned").read_bytes(), b"edited")

    def test_stale_file_is_removed_and_hand_file_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "stale").write_bytes(b"old")
            (root / "hand").write_bytes(b"keep")
            old = OwnershipManifest("test", (file_unit("stale", b"old"),))
            desired = OwnershipManifest("test", (file_unit("new", b"new"),))
            reconcile_owned(root, old, desired, {("file", "new"): b"new"})
            self.assertFalse((root / "stale").exists())
            self.assertEqual((root / "new").read_bytes(), b"new")
            self.assertEqual((root / "hand").read_bytes(), b"keep")

    def test_sections_replace_exactly_without_touching_hand_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = RenderContext("test")
            old, old_payloads = render_units(
                context, [RenderUnit("unit", "generated-section", "target.h", "old")]
            )
            desired, desired_payloads = render_units(
                context, [RenderUnit("unit", "generated-section", "target.h", "new")]
            )
            (root / "target.h").write_bytes(
                b"hand before\n" + next(iter(old_payloads.values())) + b"hand after\n"
            )
            verify_owned_baseline(root, old)
            reconcile_owned(root, old, desired, desired_payloads)
            self.assertEqual(
                (root / "target.h").read_bytes(),
                b"hand before\n"
                + next(iter(desired_payloads.values()))
                + b"hand after\n",
            )

    def test_registry_record_reconciliation_is_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = {"records": {"hand": {"value": 1}, "old": {"value": 2}}}
            (root / "registry.json").write_bytes(canonical_json(document))
            old_record = canonical_json({"value": 2})
            old = OwnershipManifest(
                "test",
                (
                    OwnershipUnit(
                        "registry-record",
                        "registry.json",
                        content_sha256(old_record),
                        registry="records",
                        key="old",
                    ),
                ),
            )
            record = {"value": 3, "alpha": True}
            desired = OwnershipManifest(
                "test",
                (
                    OwnershipUnit(
                        "registry-record",
                        "registry.json",
                        content_sha256(canonical_json(record)),
                        registry="records",
                        key="new",
                    ),
                ),
            )
            reconcile_owned(
                root,
                old,
                desired,
                {("registry-record", "registry.json", "records", "new"): record},
            )
            result = json.loads((root / "registry.json").read_text())
            self.assertEqual(result, {"records": {"hand": {"value": 1}, "new": record}})

    def test_registry_replacement_preserves_semantic_list_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = {
                "records": [
                    {"id": "last", "value": 1},
                    {"id": "owned", "value": 2},
                    {"id": "first", "value": 3},
                ]
            }
            (root / "registry.json").write_bytes(canonical_json(document))
            old_record = canonical_json(document["records"][1])
            old = OwnershipManifest(
                "test",
                (
                    OwnershipUnit(
                        "registry-record",
                        "registry.json",
                        content_sha256(old_record),
                        registry="records",
                        key="owned",
                    ),
                ),
            )
            replacement = {"id": "owned", "value": 4}
            desired = OwnershipManifest(
                "test",
                (
                    OwnershipUnit(
                        "registry-record",
                        "registry.json",
                        content_sha256(canonical_json(replacement)),
                        registry="records",
                        key="owned",
                    ),
                ),
            )
            reconcile_owned(
                root,
                old,
                desired,
                {("registry-record", "registry.json", "records", "owned"): replacement},
            )
            result = json.loads((root / "registry.json").read_text())
            self.assertEqual(
                [record["id"] for record in result["records"]],
                ["last", "owned", "first"],
            )

    def test_unchanged_registry_record_preserves_exact_file_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = b'{"records": [{"id": "owned", "value": 2}]}\n'
            path = root / "registry.json"
            path.write_bytes(original)
            record = {"id": "owned", "value": 2}
            unit = OwnershipUnit(
                "registry-record",
                "registry.json",
                content_sha256(canonical_json(record)),
                registry="records",
                key="owned",
            )
            manifest = OwnershipManifest("test", (unit,))
            reconcile_owned(
                root,
                manifest,
                manifest,
                {("registry-record", "registry.json", "records", "owned"): record},
            )
            self.assertEqual(path.read_bytes(), original)

    def test_invalid_paths_symlinks_duplicates_and_overlap_fail(self) -> None:
        digest = content_sha256(b"x")
        with self.assertRaisesRegex(ContentPortError, "unsafe owned path"):
            OwnershipUnit("file", "../escape", digest)
        with self.assertRaisesRegex(ContentPortError, "duplicate ownership"):
            OwnershipManifest("test", (OwnershipUnit("file", "x", digest),) * 2)
        with self.assertRaisesRegex(ContentPortError, "overlaps"):
            OwnershipManifest(
                "test",
                (
                    OwnershipUnit("file", "x", digest),
                    OwnershipUnit("section", "x", digest, name="part"),
                ),
            )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "outside").write_bytes(b"x")
            (root / "link").symlink_to(root / "outside")
            manifest = OwnershipManifest(
                "test", (OwnershipUnit("file", "link", digest),)
            )
            with self.assertRaisesRegex(ContentPortError, "symlink"):
                verify_owned_baseline(root, manifest)

    def test_emitted_file_inventory_requires_exact_ownership(self) -> None:
        manifest = OwnershipManifest("test", (file_unit("asset.bin", b"x"),))
        require_exact_file_ownership(manifest, ["asset.bin"], label="assets")
        with self.assertRaisesRegex(ContentPortError, "missing file ownership"):
            require_exact_file_ownership(
                manifest, ["asset.bin", "missing.bin"], label="assets"
            )
        with self.assertRaisesRegex(ContentPortError, "unexpected file ownership"):
            require_exact_file_ownership(manifest, [], label="assets")


if __name__ == "__main__":
    unittest.main()
