from __future__ import annotations

import os
from pathlib import Path
import hashlib
import json
import unittest

from tools.content_port.descriptor import load_port
from tools.content_port.donors import authenticate_donors


class PinnedDonorTests(unittest.TestCase):
    def test_real_pinned_donors_authenticate_without_skips(self) -> None:
        donor_root = Path(
            os.environ.get("CONTENT_PORT_DONOR_ROOT", ".references")
        ).resolve()
        missing = [
            str(donor_root / name)
            for name in ("pokemonHnS", "PKMN-World")
            if not (donor_root / name).is_dir()
        ]
        if missing:
            message = f"missing required donor checkouts: {', '.join(missing)}"
            if os.environ.get("CONTENT_PORT_REQUIRE_DONORS") == "1":
                self.fail(message)
            self.skipTest(message)
        descriptor = load_port(Path("tools/content_port/ports/johto"), donor_root)
        evidence = authenticate_donors(descriptor.donors)
        self.assertEqual(len(evidence), 2)

        roots = {
            "content": donor_root / "pokemonHnS",
            "mechanical": donor_root / "PKMN-World",
        }
        policy = json.loads(
            Path("tools/content_port/ports/johto/assets.json").read_text()
        )
        for asset in policy["assets"]:
            with self.subTest(asset=asset["key"]):
                source = roots[asset["donor"]] / asset["sourcePath"]
                self.assertTrue(source.is_file(), f"missing donor asset: {source}")
                self.assertEqual(
                    hashlib.sha256(source.read_bytes()).hexdigest(),
                    asset["sourceSha256"],
                )


if __name__ == "__main__":
    unittest.main()
