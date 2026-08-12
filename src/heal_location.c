#include "global.h"
#include "event_data.h"
#include "heal_location.h"
#include "constants/event_objects.h"
#include "constants/heal_locations.h"
#include "constants/maps.h"

enum CheckpointRecoveryMode
{
    CHECKPOINT_RECOVERY_DIRECT,
    CHECKPOINT_RECOVERY_HEALER,
};

struct Checkpoint
{
    struct HealLocation healLocation;
    s8 respawnMapGroup;
    s8 respawnMapNum;
    u16 respawnX;
    u16 respawnY;
    u8 healerNpcLocalId;
    u8 recoveryMode;
};

#include "data/heal_locations.h"

u32 GetHealLocationIndexByMap(u16 mapGroup, u16 mapNum)
{
    u32 i;

    for (i = 0; i < ARRAY_COUNT(sCheckpoints); i++)
    {
        const struct HealLocation *location = &sCheckpoints[i].healLocation;

        if (location->mapGroup == mapGroup && location->mapNum == mapNum)
            return i + 1;
    }
    return HEAL_LOCATION_NONE;
}

const struct HealLocation *GetHealLocationByMap(u16 mapGroup, u16 mapNum)
{
    u32 index = GetHealLocationIndexByMap(mapGroup, mapNum);

    if (index == HEAL_LOCATION_NONE)
        return NULL;
    else
        return &sCheckpoints[index - 1].healLocation;
}

u32 GetHealLocationIndexByWarpData(struct WarpData *warp)
{
    u32 i;
    for (i = 0; i < ARRAY_COUNT(sCheckpoints); i++)
    {
        const struct HealLocation *location = &sCheckpoints[i].healLocation;

        if (location->mapGroup == warp->mapGroup
        && location->mapNum == warp->mapNum
        && location->x == warp->x
        && location->y == warp->y)
            return i + 1;
    }
    return HEAL_LOCATION_NONE;
}

const struct HealLocation *GetHealLocation(u32 index)
{
    if (index == HEAL_LOCATION_NONE)
        return NULL;
    else if (index > ARRAY_COUNT(sCheckpoints))
        return NULL;
    else
        return &sCheckpoints[index - 1].healLocation;
}

static bool32 IsLastHealLocation(u32 healLocation)
{
    const struct HealLocation *loc = GetHealLocation(healLocation);
    const struct WarpData *warpData = &gSaveBlock1Ptr->lastHealLocation;

    return warpData->mapGroup == loc->mapGroup
        && warpData->mapNum == loc->mapNum
        && warpData->warpId == WARP_ID_NONE
        && warpData->x == loc->x
        && warpData->y == loc->y;
}

bool32 IsLastHealLocationPlayerHouse()
{
    if (IsLastHealLocation(HEAL_LOCATION_LITTLEROOT_TOWN_MAYS_HOUSE)
        || IsLastHealLocation(HEAL_LOCATION_LITTLEROOT_TOWN_MAYS_HOUSE_2F)
        || IsLastHealLocation(HEAL_LOCATION_LITTLEROOT_TOWN_BRENDANS_HOUSE)
        || IsLastHealLocation(HEAL_LOCATION_LITTLEROOT_TOWN_BRENDANS_HOUSE_2F)
        || IsLastHealLocation(HEAL_LOCATION_PALLET_TOWN))
        return TRUE;

    return FALSE;
}

u32 GetHealNpcLocalId(u32 healLocationId)
{
    if (healLocationId == HEAL_LOCATION_NONE || healLocationId >= NUM_HEAL_LOCATIONS)
        return LOCALID_NONE;

    return sCheckpoints[healLocationId - 1].healerNpcLocalId;
}

void SetWhiteoutRespawnWarpAndHealerNPC(struct WarpData *warp)
{
    u32 healLocationId = GetHealLocationIndexByWarpData(&gSaveBlock1Ptr->lastHealLocation);
    const struct Checkpoint *checkpoint;

    if (healLocationId == HEAL_LOCATION_NONE)
    {
        *(warp) = gSaveBlock1Ptr->lastHealLocation;
        return;
    }

    checkpoint = &sCheckpoints[healLocationId - 1];
    if (checkpoint->recoveryMode == CHECKPOINT_RECOVERY_DIRECT)
    {
        *(warp) = gSaveBlock1Ptr->lastHealLocation;
        return;
    }

    warp->mapGroup = checkpoint->respawnMapGroup;
    warp->mapNum = checkpoint->respawnMapNum;
    warp->warpId = WARP_ID_NONE;
    warp->x = checkpoint->respawnX;
    warp->y = checkpoint->respawnY;
    gSpecialVar_LastTalked = checkpoint->healerNpcLocalId;
    gSpecialVar_0x800B = checkpoint->healerNpcLocalId;
}
