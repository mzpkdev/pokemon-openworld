#include "global.h"
#include "event_data.h"
#include "trainer_rating.h"
#include "test/test.h"

static const u16 sTrainerRatingBadgeFacts[] =
{
    FLAG_REGIONAL_FACT_HOENN_STONE_BADGE,
    FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE,
    FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE,
    FLAG_REGIONAL_FACT_HOENN_KNUCKLE_BADGE,
    FLAG_REGIONAL_FACT_KANTO_BOULDER_BADGE,
    FLAG_REGIONAL_FACT_JOHTO_ZEPHYR_BADGE,
    FLAG_REGIONAL_FACT_HOENN_DYNAMO_BADGE,
    FLAG_REGIONAL_FACT_KANTO_MARSH_BADGE,
    FLAG_REGIONAL_FACT_HOENN_HEAT_BADGE,
    FLAG_REGIONAL_FACT_KANTO_RAINBOW_BADGE,
    FLAG_REGIONAL_FACT_JOHTO_PLAIN_BADGE,
    FLAG_REGIONAL_FACT_HOENN_BALANCE_BADGE,
    FLAG_REGIONAL_FACT_KANTO_SOUL_BADGE,
    FLAG_REGIONAL_FACT_JOHTO_FOG_BADGE,
    FLAG_REGIONAL_FACT_HOENN_FEATHER_BADGE,
    FLAG_REGIONAL_FACT_KANTO_THUNDER_BADGE,
    FLAG_REGIONAL_FACT_JOHTO_STORM_BADGE,
    FLAG_REGIONAL_FACT_HOENN_MIND_BADGE,
    FLAG_REGIONAL_FACT_HOENN_RAIN_BADGE,
    FLAG_REGIONAL_FACT_KANTO_VOLCANO_BADGE,
    FLAG_REGIONAL_FACT_JOHTO_RISING_BADGE,
};

static const u16 sLegacyBadgeFlags[] =
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

static void ClearTrainerRatingFacts(void)
{
    for (u32 i = 0; i < ARRAY_COUNT(sTrainerRatingBadgeFacts); i++)
        FlagClear(sTrainerRatingBadgeFacts[i]);
    for (u32 i = 0; i < ARRAY_COUNT(sLegacyBadgeFlags); i++)
        FlagClear(sLegacyBadgeFlags[i]);
    FlagClear(FLAG_REGIONAL_FACT_SEVII_DETOUR_FINISHED);
}

TEST("Trainer Rating badge formula is defined through its 32-badge ceiling")
{
    EXPECT_EQ(TrainerRating_CalculateBadge(0), 0);
    EXPECT_EQ(TrainerRating_CalculateBadge(8), 24);
    EXPECT_EQ(TrainerRating_CalculateBadge(16), 40);
    EXPECT_EQ(TrainerRating_CalculateBadge(24), 48);
    EXPECT_EQ(TrainerRating_CalculateBadge(32), 56);
    EXPECT_EQ(TrainerRating_CalculateBadge(255), 56);
}

TEST("Trainer Rating counts every reviewed regional badge fact exactly once")
{
    ClearTrainerRatingFacts();

    EXPECT_EQ(TrainerRating_GetBadge(), 0);
    for (u32 i = 0; i < ARRAY_COUNT(sTrainerRatingBadgeFacts); i++)
    {
        FlagSet(sTrainerRatingBadgeFacts[i]);
        EXPECT_EQ(TrainerRating_GetBadge(), TrainerRating_CalculateBadge(i + 1));
    }

    EXPECT_EQ(TrainerRating_GetBadge(), 45);
}

TEST("Trainer Rating ignores ambiguous generic badges and keeps Kanto progress singular")
{
    ClearTrainerRatingFacts();
    for (u32 i = 0; i < ARRAY_COUNT(sLegacyBadgeFlags); i++)
        FlagSet(sLegacyBadgeFlags[i]);

    EXPECT_EQ(TrainerRating_GetBadge(), 0);
    EXPECT_EQ(TrainerRating_GetStory(), 0);
    EXPECT_EQ(TrainerRating_Get(), 0);

    FlagSet(FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE);
    EXPECT_EQ(TrainerRating_GetBadge(), 3);
    EXPECT_EQ(TrainerRating_GetStory(), 0);
    EXPECT_EQ(TrainerRating_Get(), 3);

    FlagSet(FLAG_REGIONAL_FACT_SEVII_DETOUR_FINISHED);
    EXPECT_EQ(TrainerRating_GetBadge(), 3);
    EXPECT_EQ(TrainerRating_GetStory(), 1);
    EXPECT_EQ(TrainerRating_Get(), 4);

    for (u32 i = 0; i < ARRAY_COUNT(sLegacyBadgeFlags); i++)
        EXPECT(FlagGet(sLegacyBadgeFlags[i]));
}

TEST("Trainer Rating queries are idempotent and do not mutate save state")
{
    bool8 badgeStates[ARRAY_COUNT(sTrainerRatingBadgeFacts)];
    bool8 legacyBadgeStates[ARRAY_COUNT(sLegacyBadgeFlags)];

    ClearTrainerRatingFacts();
    FlagSet(FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE);
    FlagSet(FLAG_REGIONAL_FACT_JOHTO_FOG_BADGE);
    FlagSet(FLAG_REGIONAL_FACT_SEVII_DETOUR_FINISHED);
    for (u32 i = 0; i < ARRAY_COUNT(sTrainerRatingBadgeFacts); i++)
        badgeStates[i] = FlagGet(sTrainerRatingBadgeFacts[i]);
    for (u32 i = 0; i < ARRAY_COUNT(sLegacyBadgeFlags); i++)
        legacyBadgeStates[i] = FlagGet(sLegacyBadgeFlags[i]);

    EXPECT_EQ(TrainerRating_GetBadge(), 6);
    EXPECT_EQ(TrainerRating_GetStory(), 1);
    EXPECT_EQ(TrainerRating_Get(), 7);
    EXPECT_EQ(TrainerRating_GetBadge(), 6);
    EXPECT_EQ(TrainerRating_GetStory(), 1);
    EXPECT_EQ(TrainerRating_Get(), 7);

    for (u32 i = 0; i < ARRAY_COUNT(sTrainerRatingBadgeFacts); i++)
        EXPECT_EQ(FlagGet(sTrainerRatingBadgeFacts[i]), badgeStates[i]);
    for (u32 i = 0; i < ARRAY_COUNT(sLegacyBadgeFlags); i++)
        EXPECT_EQ(FlagGet(sLegacyBadgeFlags[i]), legacyBadgeStates[i]);
    EXPECT(FlagGet(FLAG_REGIONAL_FACT_SEVII_DETOUR_FINISHED));
}
