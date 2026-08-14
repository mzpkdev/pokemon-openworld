#include "global.h"
#include "event_data.h"
#include "test/test.h"
#include "world_tier.h"

static const u16 sWorldTierFactFlags[] =
{
    FLAG_REGIONAL_FACT_HOENN_STONE_BADGE,
    FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE,
    FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE,
};

static const u16 sAmbiguousBadgeFlags[] =
{
    FLAG_BADGE01_GET,
    FLAG_BADGE02_GET,
    FLAG_BADGE03_GET,
    FLAG_BADGE04_GET,
    FLAG_BADGE05_GET,
    FLAG_BADGE06_GET,
    FLAG_BADGE07_GET,
    FLAG_BADGE08_GET,
};

static void ClearWorldTierFlags(void)
{
    for (u32 i = 0; i < ARRAY_COUNT(sWorldTierFactFlags); i++)
        FlagClear(sWorldTierFactFlags[i]);
    for (u32 i = 0; i < ARRAY_COUNT(sAmbiguousBadgeFlags); i++)
        FlagClear(sAmbiguousBadgeFlags[i]);
}

TEST("World tier maps the three exact proof facts to tiers zero through three")
{
    for (u32 factMask = 0; factMask < (1 << ARRAY_COUNT(sWorldTierFactFlags)); factMask++)
    {
        ClearWorldTierFlags();
        for (u32 i = 0; i < ARRAY_COUNT(sWorldTierFactFlags); i++)
        {
            if (factMask & (1 << i))
                FlagSet(sWorldTierFactFlags[i]);
        }

        EXPECT_EQ(WorldTier_Get(), __builtin_popcount(factMask));
    }
}

TEST("World tier ignores every ambiguous legacy badge slot")
{
    ClearWorldTierFlags();

    for (u32 i = 0; i < ARRAY_COUNT(sAmbiguousBadgeFlags); i++)
    {
        FlagSet(sAmbiguousBadgeFlags[i]);
        EXPECT_EQ(WorldTier_Get(), WORLD_TIER_0);
    }
}

TEST("World tier is independent of proof fact acquisition order")
{
    static const u8 orders[][ARRAY_COUNT(sWorldTierFactFlags)] =
    {
        {0, 1, 2},
        {0, 2, 1},
        {1, 0, 2},
        {1, 2, 0},
        {2, 0, 1},
        {2, 1, 0},
    };

    for (u32 i = 0; i < ARRAY_COUNT(orders); i++)
    {
        ClearWorldTierFlags();
        for (u32 j = 0; j < ARRAY_COUNT(sWorldTierFactFlags); j++)
        {
            FlagSet(sWorldTierFactFlags[orders[i][j]]);
            EXPECT_EQ(WorldTier_Get(), j + 1);
        }
    }
}

TEST("World tier is capped at its released maximum")
{
    ClearWorldTierFlags();
    for (u32 i = 0; i < ARRAY_COUNT(sWorldTierFactFlags); i++)
        FlagSet(sWorldTierFactFlags[i]);

    EXPECT_EQ(WORLD_TIER_MAX, WORLD_TIER_3);
    EXPECT_EQ(WorldTier_Get(), WORLD_TIER_MAX);
}

TEST("World tier queries do not mutate progression state")
{
    bool32 factStates[ARRAY_COUNT(sWorldTierFactFlags)];
    bool32 badgeStates[ARRAY_COUNT(sAmbiguousBadgeFlags)];

    ClearWorldTierFlags();
    FlagSet(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE);
    FlagSet(FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE);
    FlagSet(FLAG_BADGE08_GET);
    for (u32 i = 0; i < ARRAY_COUNT(sWorldTierFactFlags); i++)
        factStates[i] = FlagGet(sWorldTierFactFlags[i]);
    for (u32 i = 0; i < ARRAY_COUNT(sAmbiguousBadgeFlags); i++)
        badgeStates[i] = FlagGet(sAmbiguousBadgeFlags[i]);

    EXPECT_EQ(WorldTier_Get(), WORLD_TIER_2);
    EXPECT_EQ(WorldTier_Get(), WORLD_TIER_2);

    for (u32 i = 0; i < ARRAY_COUNT(sWorldTierFactFlags); i++)
        EXPECT_EQ(FlagGet(sWorldTierFactFlags[i]), factStates[i]);
    for (u32 i = 0; i < ARRAY_COUNT(sAmbiguousBadgeFlags); i++)
        EXPECT_EQ(FlagGet(sAmbiguousBadgeFlags[i]), badgeStates[i]);
}
