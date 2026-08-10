from __future__ import annotations

import unittest

from tools.content_port.closure import close_source_graph, dependency_closure
from tools.content_port.errors import ContentPortError
from tools.content_port.model import ResourceKey
from tools.content_port.sources import Provenance, SourceEdge, SourceGraph


class ClosureTests(unittest.TestCase):
    def test_transitive_cycles_are_deterministic(self) -> None:
        a, b, c = (ResourceKey("map", name) for name in "ABC")
        result = dependency_closure([a], {a: [b], b: [c], c: [a]}, {a, b, c})
        self.assertEqual(result, (a, b, c))

    def test_disabled_dependency_reports_chain_and_source(self) -> None:
        a = ResourceKey("map", "A")
        b = ResourceKey("trainer", "B")
        edge = SourceEdge(
            a, b, Provenance("data/maps/A/map.json", "/object_events/0/trainer")
        )
        graph = SourceGraph({a: Provenance("a"), b: Provenance("b")}, (edge,))
        with self.assertRaisesRegex(
            ContentPortError, r"map:A.*object_events/0/trainer.*trainer:B"
        ):
            close_source_graph(graph, [a], {a})


if __name__ == "__main__":
    unittest.main()
