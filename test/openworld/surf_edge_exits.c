#include "global.h"
#include "overworld.h"
#include "surf_edge_exits.h"
#include "test/test.h"
#include "constants/maps.h"
#include "constants/metatile_behaviors.h"

static const struct SurfEdgeExit sExits[] =
{
    {
        .sourceMap = 0x1234,
        .targetMap = 0x5678,
        .targetX = 200,
        .targetY = 201,
        .exitEdge = DIR_NORTH,
        .targetFacing = DIR_SOUTH,
    },
    {
        .sourceMap = 0x1234,
        .targetMap = 0x5678,
        .targetX = 20,
        .targetY = 21,
        .exitEdge = DIR_SOUTH,
        .targetFacing = DIR_NORTH,
    },
    {
        .sourceMap = 0x1234,
        .targetMap = 0x5678,
        .targetX = 30,
        .targetY = 31,
        .exitEdge = DIR_WEST,
        .targetFacing = DIR_EAST,
    },
    {
        .sourceMap = 0x1234,
        .targetMap = 0x5678,
        .targetX = 40,
        .targetY = 41,
        .exitEdge = DIR_EAST,
        .targetFacing = DIR_WEST,
    },
};

static struct SurfEdgeExitAttempt MakeAttempt(enum Direction direction)
{
    struct SurfEdgeExitAttempt attempt =
    {
        .sourceMap = 0x1234,
        .localX = 5,
        .localY = 4,
        .mapWidth = 10,
        .mapHeight = 8,
        .direction = direction,
        .collision = COLLISION_IMPASSABLE,
        .attemptedBorder = CONNECTION_INVALID,
        .playerAvatarFlags = PLAYER_AVATAR_FLAG_SURFING,
        .currentMetatileBehavior = MB_OCEAN_WATER,
    };

    switch (direction)
    {
    case DIR_SOUTH:
        attempt.localY = attempt.mapHeight - 1;
        break;
    case DIR_NORTH:
        attempt.localY = 0;
        break;
    case DIR_WEST:
        attempt.localX = 0;
        break;
    case DIR_EAST:
        attempt.localX = attempt.mapWidth - 1;
        break;
    default:
        break;
    }
    return attempt;
}

TEST("Surf edge exits select every cardinal edge from its exact final tile")
{
    static const enum Direction directions[] = {DIR_SOUTH, DIR_NORTH, DIR_WEST, DIR_EAST};

    for (u32 i = 0; i < ARRAY_COUNT(directions); i++)
    {
        struct SurfEdgeExitAttempt attempt = MakeAttempt(directions[i]);
        const struct SurfEdgeExit *exit = SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits));

        EXPECT_NE(exit, NULL);
        EXPECT_EQ(exit->exitEdge, directions[i]);
    }
}

TEST("Surf edge exits reject inward tiles and malformed map dimensions")
{
    struct SurfEdgeExitAttempt attempt = MakeAttempt(DIR_NORTH);

    attempt.localY++;
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);
    attempt = MakeAttempt(DIR_SOUTH);
    attempt.localY--;
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);
    attempt = MakeAttempt(DIR_WEST);
    attempt.localX++;
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);
    attempt = MakeAttempt(DIR_EAST);
    attempt.localX--;
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);

    attempt = MakeAttempt(DIR_NORTH);
    attempt.mapWidth = 0;
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);
    attempt = MakeAttempt(DIR_NORTH);
    attempt.mapHeight = 0;
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);

    attempt = MakeAttempt(DIR_NORTH);
    attempt.localX = -1;
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);
    attempt.localX = attempt.mapWidth;
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);
}

TEST("Surf edge exits require surfing water and the ordinary impassable map border")
{
    struct SurfEdgeExitAttempt attempt = MakeAttempt(DIR_NORTH);

    attempt.playerAvatarFlags = PLAYER_AVATAR_FLAG_ON_FOOT;
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);

    attempt = MakeAttempt(DIR_NORTH);
    attempt.currentMetatileBehavior = MB_NORMAL;
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);

    for (enum Collision collision = COLLISION_NONE; collision <= COLLISION_SIDEWAYS_STAIRS_TO_LEFT; collision++)
    {
        attempt = MakeAttempt(DIR_NORTH);
        attempt.collision = collision;
        if (collision == COLLISION_IMPASSABLE)
            EXPECT_NE(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);
        else
            EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);
    }

    attempt = MakeAttempt(DIR_NORTH);
    attempt.attemptedBorder = CONNECTION_NORTH;
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);
    attempt.attemptedBorder = CONNECTION_NONE;
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);
}

TEST("Surf edge exits reject noncardinal directions registry misses and an empty registry")
{
    struct SurfEdgeExitAttempt attempt = MakeAttempt(DIR_NORTH);

    attempt.sourceMap = 0x9999;
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);

    attempt = MakeAttempt(DIR_NORTH);
    attempt.direction = DIR_EAST;
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);

    attempt = MakeAttempt(DIR_NONE);
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);
    attempt = MakeAttempt(DIR_NORTHEAST);
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits)), NULL);

    attempt = MakeAttempt(DIR_NORTH);
    EXPECT_EQ(SurfEdgeExit_Select(&attempt, NULL, 0), NULL);
}

TEST("Surf edge exit map encoding and destination coordinates preserve all bits")
{
    const struct WarpData savedDestination = Test_GetWarpDestination();
    struct SurfEdgeExitAttempt attempt = MakeAttempt(DIR_NORTH);
    const struct SurfEdgeExit *exit = SurfEdgeExit_Select(&attempt, sExits, ARRAY_COUNT(sExits));
    struct WarpData destination;

    EXPECT_EQ(SurfEdgeExit_EncodeMap(0x12, 0x34), 0x1234);
    EXPECT_NE(exit, NULL);
    EXPECT_EQ(exit->targetX, 200);
    EXPECT_EQ(exit->targetY, 201);

    SetWarpDestination(0x12, 0x34, WARP_ID_NONE, exit->targetX, exit->targetY);
    destination = Test_GetWarpDestination();
    EXPECT_EQ((u8)destination.mapGroup, 0x12);
    EXPECT_EQ((u8)destination.mapNum, 0x34);
    EXPECT_EQ(destination.warpId, WARP_ID_NONE);
    EXPECT_EQ(destination.x, 200);
    EXPECT_EQ(destination.y, 201);

    SetWarpDestination(0x12, 0x34, WARP_ID_NONE, -1, -1);
    destination = Test_GetWarpDestination();
    EXPECT_EQ(destination.x, -1);
    EXPECT_EQ(destination.y, -1);

    SetWarpDestination(
        savedDestination.mapGroup,
        savedDestination.mapNum,
        savedDestination.warpId,
        savedDestination.x,
        savedDestination.y);
}

TEST("Surf edge route profiles select only their normalized source edge")
{
    const u16 route19 = SurfEdgeExit_EncodeMap(MAP_GROUP(MAP_ROUTE19), MAP_NUM(MAP_ROUTE19));

    EXPECT_EQ(
        SurfEdgeRouteProfile_Select(route19, DIR_SOUTH),
        SURF_EDGE_ROUTE_PROFILE_GENERATED_OCEAN
    );
    EXPECT_EQ(
        SurfEdgeRouteProfile_Select(route19, DIR_NORTH),
        SURF_EDGE_ROUTE_PROFILE_NONE
    );
}

TEST("Surf edge exit arrival facing is cardinal one shot and resettable")
{
    static const enum Direction directions[] = {DIR_SOUTH, DIR_NORTH, DIR_WEST, DIR_EAST};

    for (u32 i = 0; i < ARRAY_COUNT(directions); i++)
    {
        ResetInitialPlayerAvatarState();
        SetInitialPlayerAvatarStateFacingOverride(directions[i]);
        EXPECT_EQ(Test_ConsumeInitialPlayerAvatarStateFacingOverride(DIR_WEST), directions[i]);
        EXPECT_EQ(Test_ConsumeInitialPlayerAvatarStateFacingOverride(DIR_WEST), DIR_WEST);
    }

    SetInitialPlayerAvatarStateFacingOverride(DIR_EAST);
    ResetInitialPlayerAvatarState();
    EXPECT_EQ(Test_ConsumeInitialPlayerAvatarStateFacingOverride(DIR_NORTH), DIR_NORTH);

    SetInitialPlayerAvatarStateFacingOverride(DIR_NORTHEAST);
    EXPECT_EQ(Test_ConsumeInitialPlayerAvatarStateFacingOverride(DIR_SOUTH), DIR_SOUTH);
}
