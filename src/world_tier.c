#include "global.h"
#include "regional_fact.h"
#include "world_tier.h"

struct WorldTierFact
{
    enum RegionalFact fact;
    u16 weight;
};

struct WorldTierThreshold
{
    u16 score;
    enum WorldTier tier;
};

// Released entries retain their position and meaning; new facts append here.
static const struct WorldTierFact sWorldTierFacts[] =
{
    {REGIONAL_FACT_HOENN_STONE_BADGE,   1},
    {REGIONAL_FACT_KANTO_CASCADE_BADGE, 1},
    {REGIONAL_FACT_JOHTO_HIVE_BADGE,    1},
};

// Thresholds are ascending. New tiers append without changing released bands.
static const struct WorldTierThreshold sWorldTierThresholds[] =
{
    {0, WORLD_TIER_0},
    {1, WORLD_TIER_1},
    {2, WORLD_TIER_2},
    {3, WORLD_TIER_3},
};

enum WorldTier WorldTier_Get(void)
{
    u16 score = 0;
    enum WorldTier tier = WORLD_TIER_0;

    for (u32 i = 0; i < ARRAY_COUNT(sWorldTierFacts); i++)
    {
        if (RegionalFact_Get(sWorldTierFacts[i].fact))
            score += sWorldTierFacts[i].weight;
    }

    for (u32 i = 0; i < ARRAY_COUNT(sWorldTierThresholds); i++)
    {
        if (score < sWorldTierThresholds[i].score)
            break;
        tier = sWorldTierThresholds[i].tier;
    }

    return tier;
}
