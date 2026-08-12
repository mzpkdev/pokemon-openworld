#include "global.h"
#include "event_data.h"
#include "regional_fact.h"

bool32 RegionalFact_Get(enum RegionalFact fact)
{
    switch (fact)
    {
    case REGIONAL_FACT_HOENN_STONE_BADGE:
        return FlagGet(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE);
    case REGIONAL_FACT_KANTO_CASCADE_BADGE:
        return FlagGet(FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE);
    case REGIONAL_FACT_JOHTO_HIVE_BADGE:
        return FlagGet(FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE);
    default:
        return FALSE;
    }
}
