#ifndef GUARD_PLAYER_CAPABILITY_H
#define GUARD_PLAYER_CAPABILITY_H

#include "global.h"

enum PlayerCapability
{
    PLAYER_CAPABILITY_CUT,
    PLAYER_CAPABILITY_COUNT,
};

bool32 PlayerHasCapability(enum PlayerCapability capability);

#endif // GUARD_PLAYER_CAPABILITY_H
