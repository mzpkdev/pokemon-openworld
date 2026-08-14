from __future__ import annotations

import unittest

from tools.content_port.errors import ContentPortError
from tools.content_port.world_graph import (
    WorldEdge,
    WorldPolicy,
    validate_world_graph,
    with_dynamic_warps,
    with_script_warps,
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

    def test_dynamic_options_are_distinct_directional_reachability_edges(self) -> None:
        base = world_graph_from_maps(
            {
                "SHIP": map_doc(
                    "SHIP",
                    warps=[{"dest_map": "MAP_DYNAMIC", "dest_warp_id": "DYNAMIC"}],
                ),
                "A": map_doc("A"),
                "B": map_doc("B", region="kanto"),
            }
        )

        def option(target, arming_source):
            return WorldEdge(
                "SHIP",
                target,
                "dynamic-warp",
                0,
                x=8,
                y=9,
                arming_source=arming_source,
                arming_entry=f"{arming_source}_Travel",
                arming_label=f"{arming_source}_Travel",
                arming_index=0,
                immediate_target="SHIP",
                immediate_command="warp",
                immediate_index=0,
                immediate_x=29,
                immediate_y=3,
            )

        a_edge = option("A", "B")
        b_edge = option("B", "A")
        self.assertNotEqual(a_edge.key, b_edge.key)
        graph = with_dynamic_warps(base, (a_edge, b_edge))
        with self.assertRaisesRegex(ContentPortError, "declared gateway"):
            validate_world_graph(
                graph,
                WorldPolicy(
                    dynamic_warps={"SHIP:warp:0": "DYNAMIC"},
                    roots=frozenset({"SHIP"}),
                ),
            )
        validate_world_graph(
            graph,
            WorldPolicy(
                dynamic_warps={"SHIP:warp:0": "DYNAMIC"},
                inter_region_gateways=frozenset({b_edge.key}),
                roots=frozenset({"SHIP"}),
            ),
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

    def test_script_warps_are_directional_gateway_and_reachability_edges(self) -> None:
        graph = with_script_warps(
            world_graph_from_maps(
                {
                    "A": map_doc("A", region="kanto"),
                    "B": map_doc("B", region="johto"),
                }
            ),
            (
                WorldEdge(
                    "A",
                    "B",
                    "script-warp",
                    0,
                    script_entry="A_Travel",
                    script_label="A_Travel",
                    command="warp",
                    x=2,
                    y=3,
                ),
                WorldEdge(
                    "B",
                    "A",
                    "script-warp",
                    0,
                    script_entry="B_Travel",
                    script_label="B_Travel",
                    command="warp",
                    x=4,
                    y=5,
                ),
            ),
        )
        a_to_b = "A:script-warp:A_Travel:A_Travel:0"
        b_to_a = "B:script-warp:B_Travel:B_Travel:0"
        with self.assertRaisesRegex(ContentPortError, "declared gateway"):
            validate_world_graph(
                graph,
                WorldPolicy(
                    inter_region_gateways=frozenset({a_to_b}),
                    roots=frozenset({"A"}),
                ),
            )
        validate_world_graph(
            graph,
            WorldPolicy(
                inter_region_gateways=frozenset({a_to_b, b_to_a}),
                roots=frozenset({"A"}),
            ),
        )


if __name__ == "__main__":
    unittest.main()
