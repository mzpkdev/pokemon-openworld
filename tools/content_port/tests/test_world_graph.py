from __future__ import annotations

import unittest

from tools.content_port.errors import ContentPortError
from tools.content_port.world_graph import (
    WorldPolicy,
    validate_world_graph,
    world_graph_from_maps,
)


def map_doc(name, connections=(), warps=(), region="johto"):
    return {
        "id": f"MAP_{name}",
        "region": region,
        "connections": list(connections),
        "warp_events": list(warps),
    }


class WorldGraphTests(unittest.TestCase):
    def test_reciprocal_connections_and_warp_bounds(self) -> None:
        graph = world_graph_from_maps(
            {
                "A": map_doc(
                    "A",
                    [{"map": "MAP_B", "direction": "right", "offset": -2}],
                    [{"dest_map": "MAP_B", "dest_warp_id": "0"}],
                ),
                "B": map_doc(
                    "B",
                    [{"map": "MAP_A", "direction": "left", "offset": 2}],
                    [{"dest_map": "MAP_A", "dest_warp_id": "0"}],
                ),
            }
        )
        validate_world_graph(graph, WorldPolicy(roots=frozenset({"A"})))

    def test_one_way_and_deferred_edges_require_exact_review(self) -> None:
        graph = world_graph_from_maps(
            {
                "A": map_doc(
                    "A",
                    [{"map": "MAP_B", "direction": "right", "offset": 0}],
                    [{"dest_map": "MAP_FUTURE", "dest_warp_id": "0"}],
                ),
                "B": map_doc("B"),
            }
        )
        policy = WorldPolicy(
            reviewed_one_way=frozenset({"A:connection:0"}),
            deferred_exits=frozenset({"A:warp:0"}),
            roots=frozenset({"A"}),
        )
        validate_world_graph(graph, policy)

    def test_dynamic_warp_needs_metadata(self) -> None:
        graph = world_graph_from_maps(
            {
                "A": map_doc(
                    "A",
                    warps=[{"dest_map": "MAP_A", "dest_warp_id": "WARP_ID_DYNAMIC"}],
                )
            }
        )
        with self.assertRaisesRegex(ContentPortError, "dynamic warp lacks"):
            validate_world_graph(graph, WorldPolicy())
        validate_world_graph(
            graph, WorldPolicy(dynamic_warps={"A:warp:0": "saved-warp"})
        )

    def test_inter_region_gateway_and_reachability(self) -> None:
        graph = world_graph_from_maps(
            {
                "A": map_doc("A", warps=[{"dest_map": "MAP_B", "dest_warp_id": 0}]),
                "B": map_doc(
                    "B",
                    warps=[{"dest_map": "MAP_A", "dest_warp_id": 0}],
                    region="kanto",
                ),
                "SHELL": map_doc("SHELL"),
            }
        )
        with self.assertRaisesRegex(ContentPortError, "declared gateway"):
            validate_world_graph(
                graph,
                WorldPolicy(
                    roots=frozenset({"A"}), unreachable_shells=frozenset({"SHELL"})
                ),
            )
        validate_world_graph(
            graph,
            WorldPolicy(
                inter_region_gateways=frozenset({"A:warp:0", "B:warp:0"}),
                roots=frozenset({"A"}),
                unreachable_shells=frozenset({"SHELL"}),
            ),
        )

    def test_destination_warp_bounds(self) -> None:
        graph = world_graph_from_maps(
            {
                "A": map_doc("A", warps=[{"dest_map": "MAP_B", "dest_warp_id": 1}]),
                "B": map_doc("B", warps=[{"dest_map": "MAP_A", "dest_warp_id": 0}]),
            }
        )
        with self.assertRaisesRegex(ContentPortError, "out of bounds"):
            validate_world_graph(graph, WorldPolicy())


if __name__ == "__main__":
    unittest.main()
