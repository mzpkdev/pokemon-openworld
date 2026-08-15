"""Tests for trainer placement geometry and object-capacity gates."""

from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace
from pathlib import Path

from tools.content_port.errors import ContentPortError
from tools.content_port.trainer_geometry import (
    ACTIVE_OBJECT_LIMIT,
    STATIC_OBJECT_LIMIT,
    AuthenticatedMapGeometry,
    ConnectionTransform,
    CrossMapCloneTrainerGeometry,
    Direction,
    OrdinaryTrainerGeometry,
    PreservedObjectGeometry,
    ReviewedCoordinateAdaptation,
    SightGeometry,
    SightMode,
    validate_trainer_geometry,
    validate_trainer_geometry_census,
)


def _rectangle(width: int, height: int) -> frozenset[tuple[int, int]]:
    return frozenset((x, y) for y in range(height) for x in range(width))


def _fixed(
    direction: Direction = Direction.RIGHT, sight_range: int = 3
) -> SightGeometry:
    return SightGeometry(SightMode.FIXED, frozenset({direction}), sight_range)


def _trainer(
    placement: str = "RouteTest/3/TrainerA",
    object_index: int = 3,
    local_id: int = 2,
    coordinate: tuple[int, int] = (4, 4),
) -> OrdinaryTrainerGeometry:
    return OrdinaryTrainerGeometry(
        placement,
        object_index,
        local_id,
        coordinate[0],
        coordinate[1],
        coordinate[0],
        coordinate[1],
        frozenset({coordinate}),
        _fixed(),
    )


def _geometry() -> AuthenticatedMapGeometry:
    objects = (
        PreservedObjectGeometry(1, 20, 18, frozenset({(20, 18)})),
        _trainer(),
        _trainer("RouteTest/8/TrainerB", 8, 3, (14, 12)),
    )
    return AuthenticatedMapGeometry(
        name="RouteTest",
        width=24,
        height=20,
        objects=objects,
        passable_tiles=_rectangle(24, 20),
        entry_components=(frozenset({(0, 0)}), frozenset({(23, 19)})),
    )


class TrainerGeometryTests(unittest.TestCase):
    def test_production_inventory_freezes_203_placement_membership_and_order(
        self,
    ) -> None:
        document = json.loads(
            Path(
                "tools/content_port/ports/johto/trainer_classification.json"
            ).read_text(encoding="utf-8")
        )
        placements = tuple(
            event["identity"]
            for map_row in document["maps"]
            for event in map_row["events"]
            if event["admitted"]
        )

        self.assertEqual(len(placements), 203)
        self.assertEqual(
            hashlib.sha256(
                json.dumps(placements, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "bd509a7c08a67ef66ca056bd3a1a6559d9221403c7d1bda926005eb673150f4e",
        )
        self.assertIn("Route26/1/Route26_EventScript_Jake", placements)
        self.assertIn("Route26/2/Route26_EventScript_Joyce", placements)
        self.assertIn("SSAqua_RoomNW/1/SSAqua_RoomNW_EventScript_Edward", placements)
        self.assertIn("SSAqua_RoomNW/2/SSAqua_RoomNW_EventScript_Corey", placements)

    def test_valid_geometry_returns_capacity_census(self) -> None:
        census = validate_trainer_geometry(_geometry())

        self.assertEqual(census.static_objects, 3)
        self.assertEqual(census.peak_active_objects, 5)
        self.assertEqual(census.reachable_tiles, 477)
        self.assertEqual(census.sight_tiles, 6)
        self.assertEqual(
            census.placements,
            ("RouteTest/3/TrainerA", "RouteTest/8/TrainerB"),
        )

    def test_full_output_order_derives_local_ids(self) -> None:
        objects = list(_geometry().objects)
        objects[1] = replace(objects[1], local_id=3)
        geometry = replace(_geometry(), objects=tuple(objects))
        with self.assertRaisesRegex(ContentPortError, "full object order"):
            validate_trainer_geometry(geometry)

    def test_rejects_noncanonical_donor_order(self) -> None:
        objects = (_geometry().objects[0], *_geometry().objects[:0:-1])
        objects = tuple(
            replace(obj, local_id=index) for index, obj in enumerate(objects, 1)
        )
        with self.assertRaisesRegex(ContentPortError, "canonical donor object order"):
            validate_trainer_geometry(replace(_geometry(), objects=objects))

    def test_rejects_preserved_object_overlap(self) -> None:
        objects = list(_geometry().objects)
        objects[0] = replace(
            objects[0], x=4, y=4, movement_envelope=frozenset({(4, 4)})
        )
        with self.assertRaisesRegex(ContentPortError, "duplicate object occupancy"):
            validate_trainer_geometry(replace(_geometry(), objects=tuple(objects)))

    def test_movement_envelope_is_not_simultaneous_occupancy(self) -> None:
        objects = list(_geometry().objects)
        objects[1] = replace(
            objects[1], movement_envelope=frozenset({(4, 4), (5, 4), (6, 4)})
        )
        census = validate_trainer_geometry(replace(_geometry(), objects=tuple(objects)))
        self.assertGreater(census.sight_tiles, 0)

    def test_preserved_occupancy_blocks_reachability(self) -> None:
        geometry = AuthenticatedMapGeometry(
            "Hall",
            5,
            1,
            (
                PreservedObjectGeometry(1, 2, 0, frozenset({(2, 0)})),
                replace(
                    _trainer(local_id=2, coordinate=(4, 0)),
                    sight=_fixed(Direction.LEFT),
                ),
            ),
            _rectangle(5, 1),
            (frozenset({(0, 0)}),),
        )
        with self.assertRaisesRegex(ContentPortError, "unreachable from map entries"):
            validate_trainer_geometry(geometry)

    def test_rejects_layout_bounds_violation(self) -> None:
        objects = list(_geometry().objects)
        objects[1] = replace(
            objects[1], source_x=24, x=24, movement_envelope=frozenset({(24, 4)})
        )
        with self.assertRaisesRegex(ContentPortError, "outside the 24x20 layout"):
            validate_trainer_geometry(replace(_geometry(), objects=tuple(objects)))

    def test_rejects_static_object_overflow(self) -> None:
        objects = tuple(
            PreservedObjectGeometry(
                index + 1,
                index % 24,
                index // 24,
                frozenset({(index % 24, index // 24)}),
            )
            for index in range(STATIC_OBJECT_LIMIT + 1)
        )
        with self.assertRaisesRegex(ContentPortError, "65 static objects exceed"):
            validate_trainer_geometry(replace(_geometry(), objects=objects))

    def test_movement_envelopes_drive_active_spawn_overflow(self) -> None:
        objects = tuple(
            PreservedObjectGeometry(
                index + 1, index, 18, frozenset({(index, 18), (index, 1)})
            )
            for index in range(15)
        )
        geometry = replace(_geometry(), objects=objects)
        with self.assertRaisesRegex(
            ContentPortError,
            f"requires 17 active objects.*{ACTIVE_OBJECT_LIMIT}-object limit",
        ):
            validate_trainer_geometry(geometry)

    def test_rejects_impassable_trainer_occupancy(self) -> None:
        geometry = replace(
            _geometry(), passable_tiles=_geometry().passable_tiles - {(4, 4)}
        )
        with self.assertRaisesRegex(ContentPortError, "occupies an impassable tile"):
            validate_trainer_geometry(geometry)

    def test_sight_rays_truncate_at_collision(self) -> None:
        geometry = replace(
            _geometry(), passable_tiles=_geometry().passable_tiles - {(6, 4)}
        )
        census = validate_trainer_geometry(geometry)
        self.assertEqual(census.sight_tiles, 4)

    def test_rejects_missing_interaction_tile(self) -> None:
        blocked = {(3, 4), (5, 4), (4, 3), (4, 5)}
        geometry = replace(
            _geometry(), passable_tiles=_geometry().passable_tiles - blocked
        )
        with self.assertRaisesRegex(ContentPortError, "no passable interaction tile"):
            validate_trainer_geometry(geometry)

    def test_rejects_route_that_requires_rock_climb(self) -> None:
        passable = frozenset({(x, 0) for x in range(8)} | {(4, 1), (5, 1)})
        trainer = replace(_trainer(local_id=1, coordinate=(4, 1)), sight=_fixed())
        geometry = AuthenticatedMapGeometry(
            "RouteClimb",
            8,
            2,
            (trainer,),
            passable,
            (frozenset({(0, 0)}),),
            frozenset({(3, 0)}),
        )
        with self.assertRaisesRegex(ContentPortError, "without Rock Climb"):
            validate_trainer_geometry(geometry)

    def test_validates_fixed_look_around_and_see_all_direction_sets(self) -> None:
        objects = list(_geometry().objects)
        for sight in (
            SightGeometry(
                SightMode.FIXED, frozenset({Direction.UP, Direction.DOWN}), 3
            ),
            SightGeometry(SightMode.LOOK_AROUND, frozenset({Direction.UP}), 3),
            SightGeometry(
                SightMode.SEE_ALL, frozenset({Direction.UP, Direction.DOWN}), 3
            ),
        ):
            objects[1] = replace(objects[1], sight=sight)
            with (
                self.subTest(mode=sight.mode),
                self.assertRaisesRegex(ContentPortError, "sight requires"),
            ):
                validate_trainer_geometry(replace(_geometry(), objects=tuple(objects)))

    def test_accepts_reviewed_state_resolved_coordinates(self) -> None:
        adaptation = ReviewedCoordinateAdaptation(
            "Edward after Stanly", (4, -5), (2, 6)
        )
        trainer = replace(
            _trainer("SSAqua_RoomNW/1/Edward", 1, 1, (2, 6)),
            source_x=4,
            source_y=-5,
            adaptation=adaptation.key,
        )
        geometry = replace(
            _geometry(),
            name="SSAqua_RoomNW",
            objects=(trainer,),
            reviewed_adaptations=frozenset({adaptation}),
        )
        self.assertEqual(validate_trainer_geometry(geometry).static_objects, 1)

    def test_rejects_unreviewed_or_stale_coordinate_adaptation(self) -> None:
        trainer = replace(_trainer(local_id=1), source_y=-5)
        geometry = replace(_geometry(), objects=(trainer,))
        with self.assertRaisesRegex(ContentPortError, "lacks reviewed adaptation"):
            validate_trainer_geometry(geometry)

        stale = ReviewedCoordinateAdaptation("unused", (1, 1), (2, 2))
        with self.assertRaisesRegex(ContentPortError, "stale coordinate adaptation"):
            validate_trainer_geometry(
                replace(
                    _geometry(),
                    reviewed_adaptations=frozenset({stale}),
                )
            )

    def test_accepts_only_proven_connection_clone_transform(self) -> None:
        connection = ConnectionTransform("Route26", "Route26North", 0, -30, 39, 30)
        clone = CrossMapCloneTrainerGeometry(
            "Route26/1/Jake",
            1,
            1,
            16,
            -10,
            frozenset({(16, -10)}),
            "Route26North",
            2,
            "Route26North/1/Jake",
            16,
            20,
            connection,
        )
        geometry = AuthenticatedMapGeometry(
            "Route26",
            39,
            81,
            (clone,),
            _rectangle(39, 81),
            (frozenset({(0, 0)}),),
            connections=frozenset({connection}),
        )
        census = validate_trainer_geometry(geometry)
        self.assertEqual(census.placements, ("Route26/1/Jake",))

        bad = replace(clone, y=-9, movement_envelope=frozenset({(16, -9)}))
        with self.assertRaisesRegex(
            ContentPortError, "differs from connection transform"
        ):
            validate_trainer_geometry(replace(geometry, objects=(bad,)))
        with self.assertRaisesRegex(ContentPortError, "unproven connection clone"):
            validate_trainer_geometry(replace(geometry, connections=frozenset()))

    def test_exact_cover_census_rejects_missing_placement(self) -> None:
        geometries = {"RouteTest": _geometry()}
        expected = (
            "RouteTest/3/TrainerA",
            "RouteTest/8/TrainerB",
            "RouteTest/9/TrainerC",
        )
        with self.assertRaisesRegex(ContentPortError, "missing placement"):
            validate_trainer_geometry_census(geometries, expected)

    def test_exact_cover_census_rejects_noncanonical_placement_order(self) -> None:
        expected = tuple(reversed(validate_trainer_geometry(_geometry()).placements))
        with self.assertRaisesRegex(ContentPortError, "canonical order"):
            validate_trainer_geometry_census({"RouteTest": _geometry()}, expected)

    def test_clone_census_binds_exact_target_placement_identity(self) -> None:
        connection = ConnectionTransform("Route26", "Route26North", 0, -30, 39, 30)
        clone = CrossMapCloneTrainerGeometry(
            "Route26/1/Jake",
            1,
            1,
            16,
            -10,
            frozenset({(16, -10)}),
            "Route26North",
            1,
            "Route26North/1/Jake",
            16,
            20,
            connection,
        )
        source = AuthenticatedMapGeometry(
            "Route26",
            39,
            81,
            (clone,),
            _rectangle(39, 81),
            (frozenset({(0, 0)}),),
            connections=frozenset({connection}),
        )
        target_trainer = _trainer("Route26North/1/Jake", 1, 1, (16, 20))
        target = AuthenticatedMapGeometry(
            "Route26North",
            39,
            30,
            (target_trainer,),
            _rectangle(39, 30),
            (frozenset({(0, 0)}),),
        )
        expected = ("Route26/1/Jake", "Route26North/1/Jake")
        validate_trainer_geometry_census(
            {"Route26": source, "Route26North": target}, expected
        )

        wrong_identity = replace(target_trainer, placement="Route26North/5/Joyce")
        with self.assertRaisesRegex(ContentPortError, "does not resolve"):
            validate_trainer_geometry_census(
                {
                    "Route26": source,
                    "Route26North": replace(target, objects=(wrong_identity,)),
                },
                ("Route26/1/Jake", "Route26North/5/Joyce"),
            )

        moving_target = replace(
            target_trainer, movement_envelope=frozenset({(16, 20), (17, 20)})
        )
        with self.assertRaisesRegex(
            ContentPortError, "clone movement envelope differs"
        ):
            validate_trainer_geometry_census(
                {
                    "Route26": source,
                    "Route26North": replace(target, objects=(moving_target,)),
                },
                expected,
            )


if __name__ == "__main__":
    unittest.main()
