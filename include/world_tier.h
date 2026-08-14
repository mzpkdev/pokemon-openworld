#ifndef GUARD_WORLD_TIER_H
#define GUARD_WORLD_TIER_H

#include "global.h"

enum WorldTier
{
    WORLD_TIER_0,
    WORLD_TIER_1,
    WORLD_TIER_2,
    WORLD_TIER_3,
    WORLD_TIER_COUNT,
    WORLD_TIER_MAX = WORLD_TIER_3,
};

enum WorldTier WorldTier_Get(void);

#endif // GUARD_WORLD_TIER_H
