#ifndef GUARD_SURF_EDGE_EXITS_H
#define GUARD_SURF_EDGE_EXITS_H

struct __attribute__((packed, aligned(2))) SurfEdgeExit
{
    u16 sourceMap;
    u16 targetMap;
    s16 targetX;
    s16 targetY;
    u8 exitEdge;
    u8 targetFacing;
};

enum SurfEdgeRouteProfileId
{
    SURF_EDGE_ROUTE_PROFILE_NONE,
    SURF_EDGE_ROUTE_PROFILE_GENERATED_OCEAN,
};

struct __attribute__((packed, aligned(2))) SurfEdgeRouteProfile
{
    u16 sourceMap;
    u8 exitEdge;
    u8 profile;
};

struct SurfEdgeExitAttempt
{
    u16 sourceMap;
    s16 localX;
    s16 localY;
    s32 mapWidth;
    s32 mapHeight;
    enum Direction direction;
    enum Collision collision;
    enum Connection attemptedBorder;
    u8 playerAvatarFlags;
    u8 currentMetatileBehavior;
};

STATIC_ASSERT(sizeof(struct SurfEdgeExit) == 10, SurfEdgeExitSize);
STATIC_ASSERT(_Alignof(struct SurfEdgeExit) == 2, SurfEdgeExitAlignment);
STATIC_ASSERT(__builtin_offsetof(struct SurfEdgeExit, sourceMap) == 0, SurfEdgeExitSourceMapOffset);
STATIC_ASSERT(__builtin_offsetof(struct SurfEdgeExit, targetMap) == 2, SurfEdgeExitTargetMapOffset);
STATIC_ASSERT(__builtin_offsetof(struct SurfEdgeExit, targetX) == 4, SurfEdgeExitTargetXOffset);
STATIC_ASSERT(__builtin_offsetof(struct SurfEdgeExit, targetY) == 6, SurfEdgeExitTargetYOffset);
STATIC_ASSERT(__builtin_offsetof(struct SurfEdgeExit, exitEdge) == 8, SurfEdgeExitEdgeOffset);
STATIC_ASSERT(__builtin_offsetof(struct SurfEdgeExit, targetFacing) == 9, SurfEdgeExitTargetFacingOffset);
STATIC_ASSERT(sizeof(struct SurfEdgeRouteProfile) == 4, SurfEdgeRouteProfileSize);
STATIC_ASSERT(_Alignof(struct SurfEdgeRouteProfile) == 2, SurfEdgeRouteProfileAlignment);
STATIC_ASSERT(__builtin_offsetof(struct SurfEdgeRouteProfile, sourceMap) == 0, SurfEdgeRouteProfileSourceMapOffset);
STATIC_ASSERT(__builtin_offsetof(struct SurfEdgeRouteProfile, exitEdge) == 2, SurfEdgeRouteProfileEdgeOffset);
STATIC_ASSERT(__builtin_offsetof(struct SurfEdgeRouteProfile, profile) == 3, SurfEdgeRouteProfileProfileOffset);

extern const struct SurfEdgeExit gSurfEdgeExits[];
extern const u16 gSurfEdgeExitCount;
extern const struct SurfEdgeRouteProfile gSurfEdgeRouteProfiles[];
extern const u16 gSurfEdgeRouteProfileCount;

u16 SurfEdgeExit_EncodeMap(u8 mapGroup, u8 mapNum);
const struct SurfEdgeExit *SurfEdgeExit_Select(
    const struct SurfEdgeExitAttempt *attempt,
    const struct SurfEdgeExit *exits,
    u16 exitCount);
u8 SurfEdgeRouteProfile_Select(u16 sourceMap, u8 exitEdge);
bool8 TryStartSurfEdgeExit(enum Direction direction, enum Collision collision);

#endif // GUARD_SURF_EDGE_EXITS_H
