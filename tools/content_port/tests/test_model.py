from __future__ import annotations

import unittest

from tools.content_port import (
    CapabilityDecision,
    CapabilityState,
    ContentPortError,
    ResourceKey,
)
from tools.content_port.model import MapAllocation, PersistentBindingRef


class ModelTests(unittest.TestCase):
    def test_persistent_binding_reference_is_symbolic_and_validated(self):
        reference = PersistentBindingRef("berryTrees", "BERRY_TREE_ROUTE_29_ORAN_1")
        self.assertEqual(reference.domain, "berryTrees")
        self.assertEqual(reference.symbol, "BERRY_TREE_ROUTE_29_ORAN_1")
        with self.assertRaisesRegex(ContentPortError, "binding domain"):
            PersistentBindingRef("", "BERRY_TREE_ROUTE_29_ORAN_1")

    def test_map_allocation_is_immutable_and_validated(self):
        fields = {
            "name": "TestMap",
            "map_id": "MAP_TEST",
            "batch": "fixture",
            "materialization": "residency",
            "target_group": "gMapGroup_Test",
            "target_group_id": 4,
            "target_member": 0,
            "layout": "LAYOUT_TEST",
            "target_layout_index": 12,
            "section": "MAPSEC_TEST",
            "target_section": 9,
        }
        allocation = MapAllocation(**fields)
        self.assertEqual(allocation.map_slot, ("gMapGroup_Test", 4, 0))
        with self.assertRaises((AttributeError, TypeError)):
            allocation.target_member = 1  # type: ignore[misc]
        with self.assertRaisesRegex(ContentPortError, "unknown materialization"):
            MapAllocation(**(fields | {"materialization": "implicit"}))
        with self.assertRaisesRegex(ContentPortError, "non-negative integer"):
            MapAllocation(**(fields | {"target_section": True}))

    def test_capability_states_are_exact_and_unknown_values_fail(self):
        self.assertEqual(
            CapabilityState.parse("enabled", "$.state"), CapabilityState.ENABLED
        )
        self.assertEqual(
            {state.value for state in CapabilityState},
            {"enabled", "disabled", "deferred", "story-owned", "unsupported"},
        )
        with self.assertRaisesRegex(
            ContentPortError, r"\$\.state: unknown capability state"
        ):
            CapabilityState.parse("implicit", "$.state")

    def test_resource_identity_is_immutable_and_validated(self):
        key = ResourceKey("map", "TestMap")
        with self.assertRaises((AttributeError, TypeError)):
            key.name = "Other"  # type: ignore[misc]
        for domain, name in (("", "TestMap"), ("map", " spaced ")):
            with self.subTest(domain=domain, name=name):
                with self.assertRaises(ContentPortError):
                    ResourceKey(domain, name)

    def test_capability_dependencies_are_immutable_and_unique(self):
        key = ResourceKey("asset", "tiles")
        decision = CapabilityDecision(
            "TestMap", "spatial", CapabilityState.ENABLED, (key,)
        )
        self.assertEqual(decision.dependencies, (key,))
        with self.assertRaisesRegex(ContentPortError, "immutable tuple"):
            CapabilityDecision(
                "TestMap",
                "spatial",
                CapabilityState.ENABLED,
                [key],  # type: ignore[arg-type]
            )
        with self.assertRaisesRegex(ContentPortError, "duplicate resource identity"):
            CapabilityDecision(
                "TestMap", "spatial", CapabilityState.ENABLED, (key, key)
            )


if __name__ == "__main__":
    unittest.main()
