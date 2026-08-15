import unittest
from pathlib import Path

from tools.agent.output import CONTEXT_LIMIT, render_json
from tools.agent.query import run_query


ROOT = Path(__file__).resolve().parents[3]


class QueryTests(unittest.TestCase):
    def test_map_query_returns_compact_record_and_authority(self):
        result = run_query(ROOT, "map", "MAP_NEW_BARK_TOWN")
        self.assertEqual(result["status"], "ok")
        item = result["items"][0]
        self.assertEqual(item["source"], "data/maps/NewBarkTown/map.json")
        self.assertEqual(item["record"]["id"], "MAP_NEW_BARK_TOWN")
        self.assertIn("warp_events_count", item["record"])
        self.assertNotIn("warp_events", item["record"])

    def test_trainer_query_reports_source_line(self):
        result = run_query(ROOT, "trainer", "TRAINER_FRLG_YOUNGSTER_BEN")
        item = result["items"][0]
        self.assertEqual(item["key"], "TRAINER_FRLG_YOUNGSTER_BEN")
        self.assertEqual(item["source"], "src/data/trainers_frlg.party")
        self.assertEqual(item["location"]["line"], 1)
        self.assertEqual(item["record"]["Name"], "BEN")

    def test_persistence_query_does_not_dump_ledger(self):
        result = run_query(ROOT, "persistence", "TRAINER_FRLG_YOUNGSTER_BEN")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(
            any(
                item["record"].get("symbol") == "TRAINER_FRLG_YOUNGSTER_BEN"
                for item in result["items"]
            )
        )
        rendered = render_json(result, CONTEXT_LIMIT)
        self.assertLessEqual(len(rendered.encode()), CONTEXT_LIMIT)

    def test_content_port_query_reports_unit_location(self):
        key = "data/layouts/AzaleaTown/border.bin"
        result = run_query(ROOT, "content-port", key)
        self.assertEqual(result["status"], "ok")
        item = next(
            item for item in result["items"] if item["record"].get("path") == key
        )
        self.assertEqual(
            item["source"], "tools/content_port/ports/johto/ownership.json"
        )
        self.assertGreater(item["location"]["line"], 0)

    def test_missing_query_has_stable_envelope(self):
        result = run_query(ROOT, "map", "definitely-not-a-map")
        self.assertEqual(result["status"], "not-found")
        self.assertEqual(
            set(result),
            {
                "schemaVersion",
                "status",
                "summary",
                "inputs",
                "items",
                "impacts",
                "checks",
                "diagnostics",
                "logs",
                "truncated",
            },
        )


if __name__ == "__main__":
    unittest.main()
