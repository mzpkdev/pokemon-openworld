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

static EWRAM_DATA struct SaveBlock1 sOriginalSaveBlock1;
static EWRAM_DATA struct SaveBlock2 sOriginalSaveBlock2;
static EWRAM_DATA struct SaveBlock3 sOriginalSaveBlock3;

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

TEST("Trainer Rating story sources add to badge progress without legacy badge aliases")
{
    ClearTrainerRatingFacts();
    for (u32 i = 0; i < ARRAY_COUNT(sLegacyBadgeFlags); i++)
        FlagSet(sLegacyBadgeFlags[i]);

    EXPECT_EQ(TrainerRating_GetBadge(), 0);
    EXPECT_EQ(TrainerRating_GetStory(), 0);
    EXPECT_EQ(TrainerRating_Get(), 0);

    FlagSet(FLAG_REGIONAL_FACT_SEVII_DETOUR_FINISHED);
    EXPECT_EQ(TrainerRating_GetBadge(), 0);
    EXPECT_EQ(TrainerRating_GetStory(), 1);
    EXPECT_EQ(TrainerRating_Get(), 1);
}

TEST("Trainer Rating queries are idempotent and do not mutate save state")
{
    ClearTrainerRatingFacts();
    FlagSet(FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE);
    FlagSet(FLAG_REGIONAL_FACT_JOHTO_FOG_BADGE);
    FlagSet(FLAG_REGIONAL_FACT_SEVII_DETOUR_FINISHED);
    memcpy(&sOriginalSaveBlock1, gSaveBlock1Ptr, sizeof(sOriginalSaveBlock1));
    memcpy(&sOriginalSaveBlock2, gSaveBlock2Ptr, sizeof(sOriginalSaveBlock2));
    memcpy(&sOriginalSaveBlock3, gSaveBlock3Ptr, sizeof(sOriginalSaveBlock3));

    EXPECT_EQ(TrainerRating_GetBadge(), 6);
    EXPECT_EQ(TrainerRating_GetStory(), 1);
    EXPECT_EQ(TrainerRating_Get(), 7);
    EXPECT_EQ(TrainerRating_GetBadge(), 6);
    EXPECT_EQ(TrainerRating_GetStory(), 1);
    EXPECT_EQ(TrainerRating_Get(), 7);

    EXPECT_EQ(memcmp(&sOriginalSaveBlock1, gSaveBlock1Ptr, sizeof(sOriginalSaveBlock1)), 0);
    EXPECT_EQ(memcmp(&sOriginalSaveBlock2, gSaveBlock2Ptr, sizeof(sOriginalSaveBlock2)), 0);
    EXPECT_EQ(memcmp(&sOriginalSaveBlock3, gSaveBlock3Ptr, sizeof(sOriginalSaveBlock3)), 0);
}
