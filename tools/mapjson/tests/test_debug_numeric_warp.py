import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEBUG_SOURCE = ROOT / "src/debug.c"
GROUPS = ROOT / "data/maps/map_groups.json"


def function_body(source: str, name: str) -> str:
    match = re.search(rf"static void {name}\(u8 taskId\)\n\{{", source)
    if match is None:
        raise AssertionError(f"missing {name}")

    start = match.end()
    depth = 1
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index]
    raise AssertionError(f"unterminated {name}")


class DebugNumericWarpTests(unittest.TestCase):
    def test_empty_group_guard_precedes_map_count_or_header_use(self) -> None:
        groups = json.loads(GROUPS.read_text(encoding="utf-8"))
        counts = [len(groups[name]) for name in groups["group_order"]]
        self.assertEqual(counts[96], 12)
        self.assertTrue(all(count > 0 for count in counts))

        body = function_body(
            DEBUG_SOURCE.read_text(encoding="utf-8"),
            "DebugAction_Util_Warp_SelectMapGroup",
        )
        guard = "if (MAP_GROUP_COUNT[gTasks[taskId].tInput] == 0)"
        rejection = "PlaySE(SE_FAILURE);\n            return;"
        accepted = "gTasks[taskId].tMapGroup = gTasks[taskId].tInput;"
        underflow = "MAP_GROUP_COUNT[gTasks[taskId].tMapGroup] - 1"
        lookup = "Overworld_GetMapHeaderByGroupAndId"

        self.assertIn(guard, body)
        self.assertIn(rejection, body)
        self.assertLess(body.index(guard), body.index(accepted))
        self.assertLess(body.index(guard), body.index(underflow))
        self.assertLess(body.index(guard), body.index(lookup))


if __name__ == "__main__":
    unittest.main()
