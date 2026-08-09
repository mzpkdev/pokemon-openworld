from __future__ import annotations

import unittest

from tools.content_port import (
    CapabilityDecision,
    CapabilityState,
    ContentPortError,
    ResourceKey,
)


class ModelTests(unittest.TestCase):
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
