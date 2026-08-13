#ifndef GUARD_REGIONAL_FACT_H
#define GUARD_REGIONAL_FACT_H

#include "global.h"

enum RegionalFact
{
    REGIONAL_FACT_HOENN_STONE_BADGE,
    REGIONAL_FACT_KANTO_CASCADE_BADGE,
    REGIONAL_FACT_JOHTO_HIVE_BADGE,
    REGIONAL_FACT_COUNT,
};

bool32 RegionalFact_Get(enum RegionalFact fact);

#endif // GUARD_REGIONAL_FACT_H
