#include "global.h"
#include "event_object_movement.h"
#include "field_player_avatar.h"
#include "field_screen_effect.h"
#include "fieldmap.h"
#include "generated_ocean.h"
#include "metatile_behavior.h"
#include "overworld.h"
#include "surf_edge_exits.h"
#include "constants/maps.h"

#include "data/surf_edge_exits.inc.c"

u16 SurfEdgeExit_EncodeMap(u8 mapGroup, u8 mapNum)
{
    return ((u16)mapGroup << 8) | mapNum;
}

static bool8 IsExactMapEdge(const struct SurfEdgeExitAttempt *attempt)
{
    if (attempt->localX < 0
     || attempt->localX >= attempt->mapWidth
     || attempt->localY < 0
     || attempt->localY >= attempt->mapHeight)
        return FALSE;

    switch (attempt->direction)
    {
    case DIR_SOUTH:
        return attempt->localY == attempt->mapHeight - 1;
    case DIR_NORTH:
        return attempt->localY == 0;
    case DIR_WEST:
        return attempt->localX == 0;
    case DIR_EAST:
        return attempt->localX == attempt->mapWidth - 1;
    default:
        return FALSE;
    }
}

const struct SurfEdgeExit *SurfEdgeExit_Select(
    const struct SurfEdgeExitAttempt *attempt,
    const struct SurfEdgeExit *exits,
    u16 exitCount)
{
    u16 i;

    if (attempt->collision != COLLISION_IMPASSABLE
     || !(attempt->playerAvatarFlags & PLAYER_AVATAR_FLAG_SURFING)
     || attempt->direction <= DIR_NONE
     || attempt->direction >= CARDINAL_DIRECTION_COUNT
     || attempt->mapWidth <= 0
     || attempt->mapHeight <= 0
     || !IsExactMapEdge(attempt)
     || !MetatileBehavior_IsSurfableWaterOrUnderwater(attempt->currentMetatileBehavior)
     || attempt->attemptedBorder != CONNECTION_INVALID)
        return NULL;

    for (i = 0; i < exitCount; i++)
    {
        if (exits[i].sourceMap == attempt->sourceMap
         && exits[i].exitEdge == attempt->direction)
            return &exits[i];
    }

    return NULL;
}

u8 SurfEdgeRouteProfile_Select(u16 sourceMap, u8 exitEdge)
{
    u16 i;

    for (i = 0; i < gSurfEdgeRouteProfileCount; i++)
    {
        if (gSurfEdgeRouteProfiles[i].sourceMap == sourceMap
         && gSurfEdgeRouteProfiles[i].exitEdge == exitEdge)
            return gSurfEdgeRouteProfiles[i].profile;
    }

    return SURF_EDGE_ROUTE_PROFILE_NONE;
}

bool8 TryStartSurfEdgeExit(enum Direction direction, enum Collision collision)
{
    struct ObjectEvent *playerObjEvent = &gObjectEvents[gPlayerAvatar.objectEventId];
    struct SurfEdgeExitAttempt attempt;
    const struct SurfEdgeExit *exit;
    s16 attemptedX = playerObjEvent->currentCoords.x;
    s16 attemptedY = playerObjEvent->currentCoords.y;

    MoveCoords(direction, &attemptedX, &attemptedY);
    attempt.sourceMap = SurfEdgeExit_EncodeMap(
        gSaveBlock1Ptr->location.mapGroup,
        gSaveBlock1Ptr->location.mapNum);
    attempt.localX = playerObjEvent->currentCoords.x - MAP_OFFSET;
    attempt.localY = playerObjEvent->currentCoords.y - MAP_OFFSET;
    attempt.mapWidth = gMapHeader.mapLayout->width;
    attempt.mapHeight = gMapHeader.mapLayout->height;
    attempt.direction = direction;
    attempt.collision = collision;
    attempt.attemptedBorder = GetMapBorderIdAt(attemptedX, attemptedY);
    attempt.playerAvatarFlags = gPlayerAvatar.flags;
    attempt.currentMetatileBehavior = MapGridGetMetatileBehaviorAt(
        playerObjEvent->currentCoords.x,
        playerObjEvent->currentCoords.y);

    exit = SurfEdgeExit_Select(&attempt, gSurfEdgeExits, gSurfEdgeExitCount);
    if (exit == NULL)
        return FALSE;

    if (SurfEdgeRouteProfile_Select(exit->sourceMap, exit->exitEdge)
        == SURF_EDGE_ROUTE_PROFILE_GENERATED_OCEAN)
        return GeneratedOcean_TryBegin(exit);

    StoreInitialPlayerAvatarState();
    SetWarpDestination(
        MAP_GROUP(exit->targetMap),
        MAP_NUM(exit->targetMap),
        WARP_ID_NONE,
        exit->targetX,
        exit->targetY);
    SetInitialPlayerAvatarStateFacingOverride(exit->targetFacing);
    DoWarp();
    return TRUE;
}
