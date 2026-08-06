import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MAPJSON = ROOT / "tools/mapjson/mapjson"
FORMAT = "named-warp-v1"
FIXTURE_MAPS = ("LittlerootTown", "OldaleTown")


def recompute_registry_identity(fixture: Path) -> bytes:
    groups = json.loads((fixture / "data/maps/map_groups.json").read_text())
    sections = json.loads(
        (fixture / "src/data/region_map/region_map_sections.json").read_text()
    )
    presentations = {
        section["id"]: section["region_map_type"]
        for section in sections["map_sections"]
    }
    identity = 0xCBF29CE484222325

    def add(value: object) -> None:
        nonlocal identity
        encoded = str(value).encode()
        for byte in len(encoded).to_bytes(8, "little") + encoded:
            identity ^= byte
            identity = (identity * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF

    add(FORMAT)
    for group_name in groups["group_order"]:
        add("group")
        add(group_name)
        for registry_name in groups[group_name]:
            map_data = json.loads(
                (fixture / "data/maps" / registry_name / "map.json").read_text()
            )
            section_id = map_data["region_map_section"]
            add("map")
            add(registry_name)
            add(map_data["name"])
            add(map_data.get("id", ""))
            add(map_data.get("region", "<default>"))
            add(map_data["map_type"])
            add(section_id)
            add(presentations[section_id])
            warps = map_data.get("warp_events", [])
            add(len(warps))
            for warp in warps:
                add(warp["x"])
                add(warp["y"])
                add(warp["elevation"])
                add(warp["dest_map"])
                add(warp["dest_warp_id"])
    return identity.to_bytes(8, "little")


class DebugNamedWarpIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(["make", "-C", "tools/mapjson", "all"], cwd=ROOT, check=True)

    def make_fixture(self, fixture: Path) -> None:
        groups = {
            "group_order": ["gMapGroup_IdentityFixture"],
            "gMapGroup_IdentityFixture": list(FIXTURE_MAPS),
        }
        groups_path = fixture / "data/maps/map_groups.json"
        groups_path.parent.mkdir(parents=True)
        groups_path.write_text(json.dumps(groups))
        for map_name in FIXTURE_MAPS:
            destination = fixture / "data/maps" / map_name / "map.json"
            destination.parent.mkdir(parents=True)
            shutil.copy2(ROOT / "data/maps" / map_name / "map.json", destination)

        required = fixture / "tools/mapjson/required_map_defines.json"
        required.parent.mkdir(parents=True)
        required.write_text('{"required_maps": [], "required_layouts": []}\n')
        sections = fixture / "src/data/region_map/region_map_sections.json"
        sections.parent.mkdir(parents=True)
        shutil.copy2(ROOT / "src/data/region_map/region_map_sections.json", sections)

    def generate(self, fixture: Path, map_names: tuple[str, ...]) -> dict[str, bytes]:
        (fixture / "out/data/maps").mkdir(parents=True, exist_ok=True)
        (fixture / "out/include/constants").mkdir(parents=True, exist_ok=True)
        command = [
            str(MAPJSON),
            "groups",
            "allregions",
            "data/maps/map_groups.json",
            *(f"data/maps/{name}/map.json" for name in map_names),
            "out/data/maps",
            "out/include/constants",
        ]
        result = subprocess.run(command, cwd=fixture, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return {
            path.relative_to(fixture / "out").as_posix(): path.read_bytes()
            for path in sorted((fixture / "out").rglob("*"))
            if path.is_file()
        }

    def generated_identity(self, fixture: Path) -> bytes:
        header = (fixture / "out/src/data/debug_map_names.h").read_text()
        match = re.search(r"DEBUG_NAMED_WARP_REGISTRY_IDENTITY \{ ([^}]*) \}", header)
        self.assertIsNotNone(match)
        return bytes(int(value.strip(), 16) for value in match.group(1).split(","))

    def test_identity_rejects_changed_identity_covered_fixture_input(self) -> None:
        with tempfile.TemporaryDirectory(prefix="named-warp-identity-") as directory:
            fixture = Path(directory)
            self.make_fixture(fixture)
            self.generate(fixture, FIXTURE_MAPS)
            prior = self.generated_identity(fixture)
            self.assertEqual(prior, recompute_registry_identity(fixture))

            map_path = fixture / "data/maps/LittlerootTown/map.json"
            map_data = json.loads(map_path.read_text())
            map_data["warp_events"][0]["x"] += 1
            map_path.write_text(json.dumps(map_data))
            self.generate(fixture, FIXTURE_MAPS)
            changed = self.generated_identity(fixture)

            self.assertNotEqual(changed, prior)
            self.assertEqual(changed, recompute_registry_identity(fixture))

    def test_output_is_deterministic_for_reversed_paths_and_working_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="named-warp-determinism-") as directory:
            parent = Path(directory)
            first = parent / "first-cwd"
            second = parent / "alternate-cwd"
            self.make_fixture(first)
            self.make_fixture(second)

            first_output = self.generate(first, FIXTURE_MAPS)
            second_output = self.generate(second, tuple(reversed(FIXTURE_MAPS)))

            self.assertEqual(second_output, first_output)
            self.assertEqual(
                self.generated_identity(second), recompute_registry_identity(second)
            )


if __name__ == "__main__":
    unittest.main()
