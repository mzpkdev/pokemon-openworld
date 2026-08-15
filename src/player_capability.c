#include "global.h"
#include "event_data.h"
#include "player_capability.h"
#include "regional_fact.h"

#ifdef DEBUG
#include "item.h"
#include "constants/items.h"
#endif

#ifdef DEBUG

static bool32 DebugFieldKitIsAvailable(void)
{
#define REQUIRE_DEBUG_HM(move) \
    if (!CheckBagHasItem(CAT(ITEM_HM_, move), 1)) \
        return FALSE;

    FOREACH_HM(REQUIRE_DEBUG_HM)
#undef REQUIRE_DEBUG_HM
    return TRUE;
}

#endif // DEBUG

bool32 PlayerHasCapability(enum PlayerCapability capability)
{
#ifdef DEBUG
    if (capability < PLAYER_CAPABILITY_COUNT && DebugFieldKitIsAvailable())
        return TRUE;
#endif

    switch (capability)
    {
    case PLAYER_CAPABILITY_CUT:
        return RegionalFact_Get(REGIONAL_FACT_HOENN_STONE_BADGE)
            || RegionalFact_Get(REGIONAL_FACT_KANTO_CASCADE_BADGE)
            || RegionalFact_Get(REGIONAL_FACT_JOHTO_HIVE_BADGE)
            || FlagGet(FLAG_BADGE01_GET);
    case PLAYER_CAPABILITY_FLASH:
        return RegionalFact_Get(REGIONAL_FACT_HOENN_KNUCKLE_BADGE)
            || RegionalFact_Get(REGIONAL_FACT_KANTO_BOULDER_BADGE)
            || RegionalFact_Get(REGIONAL_FACT_JOHTO_ZEPHYR_BADGE)
            || FlagGet(FLAG_BADGE02_GET);
    case PLAYER_CAPABILITY_ROCK_SMASH:
        return RegionalFact_Get(REGIONAL_FACT_HOENN_DYNAMO_BADGE)
            || RegionalFact_Get(REGIONAL_FACT_KANTO_MARSH_BADGE)
            || FlagGet(FLAG_BADGE03_GET);
    case PLAYER_CAPABILITY_STRENGTH:
        return RegionalFact_Get(REGIONAL_FACT_HOENN_HEAT_BADGE)
            || RegionalFact_Get(REGIONAL_FACT_KANTO_RAINBOW_BADGE)
            || RegionalFact_Get(REGIONAL_FACT_JOHTO_PLAIN_BADGE)
            || FlagGet(FLAG_BADGE04_GET);
    case PLAYER_CAPABILITY_SURF:
        return RegionalFact_Get(REGIONAL_FACT_HOENN_BALANCE_BADGE)
            || RegionalFact_Get(REGIONAL_FACT_KANTO_SOUL_BADGE)
            || RegionalFact_Get(REGIONAL_FACT_JOHTO_FOG_BADGE)
            || FlagGet(FLAG_BADGE05_GET);
    case PLAYER_CAPABILITY_FLY:
        return RegionalFact_Get(REGIONAL_FACT_HOENN_FEATHER_BADGE)
            || RegionalFact_Get(REGIONAL_FACT_KANTO_THUNDER_BADGE)
            || RegionalFact_Get(REGIONAL_FACT_JOHTO_STORM_BADGE)
            || FlagGet(FLAG_BADGE06_GET);
    case PLAYER_CAPABILITY_DIVE:
        return RegionalFact_Get(REGIONAL_FACT_HOENN_MIND_BADGE)
            || FlagGet(FLAG_BADGE07_GET);
    case PLAYER_CAPABILITY_WATERFALL:
        return RegionalFact_Get(REGIONAL_FACT_HOENN_RAIN_BADGE)
            || RegionalFact_Get(REGIONAL_FACT_KANTO_VOLCANO_BADGE)
            || RegionalFact_Get(REGIONAL_FACT_JOHTO_RISING_BADGE)
            || FlagGet(FLAG_BADGE08_GET);
    default:
        return FALSE;
    }
}
