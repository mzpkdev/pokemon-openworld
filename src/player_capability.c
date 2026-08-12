#include "global.h"
#include "event_data.h"
#include "player_capability.h"
#include "regional_fact.h"

bool32 PlayerHasCapability(enum PlayerCapability capability)
{
    switch (capability)
    {
    case PLAYER_CAPABILITY_CUT:
        return RegionalFact_Get(REGIONAL_FACT_HOENN_STONE_BADGE)
            || RegionalFact_Get(REGIONAL_FACT_KANTO_CASCADE_BADGE)
            || RegionalFact_Get(REGIONAL_FACT_JOHTO_HIVE_BADGE)
            || FlagGet(FLAG_BADGE01_GET);
    default:
        return FALSE;
    }
}
