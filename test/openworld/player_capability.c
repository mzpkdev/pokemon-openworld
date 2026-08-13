#include "global.h"
#include "event_data.h"
#include "field_move.h"
#include "player_capability.h"
#include "regional_fact.h"
#include "test/test.h"
#include "constants/field_move.h"

static void ClearCutFacts(void)
{
    FlagClear(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE);
    FlagClear(FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE);
    FlagClear(FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE);
    FlagClear(FLAG_REGIONAL_FACT_SEVII_DETOUR_FINISHED);
    FlagClear(FLAG_BADGE01_GET);
    FlagClear(FLAG_BADGE02_GET);
    FlagClear(FLAG_BADGE03_GET);
}

TEST("Regional facts expose distinct fail-closed public queries")
{
    ClearCutFacts();

    EXPECT(!RegionalFact_Get(REGIONAL_FACT_HOENN_STONE_BADGE));
    EXPECT(!RegionalFact_Get(REGIONAL_FACT_KANTO_CASCADE_BADGE));
    EXPECT(!RegionalFact_Get(REGIONAL_FACT_JOHTO_HIVE_BADGE));
    EXPECT(!RegionalFact_Get(REGIONAL_FACT_SEVII_DETOUR_FINISHED));
    EXPECT(!RegionalFact_Get(REGIONAL_FACT_COUNT));
    EXPECT(!RegionalFact_Get((enum RegionalFact)0xFFFF));

    FlagSet(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE);
    EXPECT(RegionalFact_Get(REGIONAL_FACT_HOENN_STONE_BADGE));
    EXPECT(!RegionalFact_Get(REGIONAL_FACT_KANTO_CASCADE_BADGE));
    EXPECT(!RegionalFact_Get(REGIONAL_FACT_JOHTO_HIVE_BADGE));
    EXPECT(!RegionalFact_Get(REGIONAL_FACT_SEVII_DETOUR_FINISHED));

    ClearCutFacts();
    FlagSet(FLAG_REGIONAL_FACT_SEVII_DETOUR_FINISHED);
    EXPECT(RegionalFact_Get(REGIONAL_FACT_SEVII_DETOUR_FINISHED));
    EXPECT(!RegionalFact_Get(REGIONAL_FACT_HOENN_STONE_BADGE));
}

TEST("Every exact regional fact independently grants Cut through one resolver")
{
    static const u16 factFlags[] =
    {
        FLAG_REGIONAL_FACT_HOENN_STONE_BADGE,
        FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE,
        FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE,
    };

    for (u32 i = 0; i < ARRAY_COUNT(factFlags); i++)
    {
        ClearCutFacts();
        FlagSet(factFlags[i]);
        EXPECT(PlayerHasCapability(PLAYER_CAPABILITY_CUT));
        EXPECT(IsFieldMoveUnlocked(FIELD_MOVE_CUT));
    }
}

TEST("Cut preserves slot 1 compatibility and rejects unrelated state")
{
    ClearCutFacts();
    EXPECT(!PlayerHasCapability(PLAYER_CAPABILITY_CUT));
    EXPECT(!IsFieldMoveUnlocked(FIELD_MOVE_CUT));

    FlagSet(FLAG_BADGE01_GET);
    EXPECT(PlayerHasCapability(PLAYER_CAPABILITY_CUT));
    EXPECT(IsFieldMoveUnlocked(FIELD_MOVE_CUT));

    ClearCutFacts();
    FlagSet(FLAG_BADGE02_GET);
    EXPECT(!PlayerHasCapability(PLAYER_CAPABILITY_CUT));
    EXPECT(!IsFieldMoveUnlocked(FIELD_MOVE_CUT));

    FlagSet(FLAG_BADGE03_GET);
    EXPECT(!PlayerHasCapability(PLAYER_CAPABILITY_CUT));
    EXPECT(!IsFieldMoveUnlocked(FIELD_MOVE_CUT));
    EXPECT(!PlayerHasCapability(PLAYER_CAPABILITY_COUNT));
    EXPECT(!PlayerHasCapability((enum PlayerCapability)0xFFFF));
}

TEST("Regional fact and capability queries are pure")
{
    u8 originalFlags[sizeof(gSaveBlock1Ptr->flags)];

    ClearCutFacts();
    FlagSet(FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE);
    FlagSet(FLAG_BADGE02_GET);
    memcpy(originalFlags, gSaveBlock1Ptr->flags, sizeof(originalFlags));

    EXPECT(RegionalFact_Get(REGIONAL_FACT_KANTO_CASCADE_BADGE));
    EXPECT(PlayerHasCapability(PLAYER_CAPABILITY_CUT));
    EXPECT(IsFieldMoveUnlocked(FIELD_MOVE_CUT));
    EXPECT_EQ(memcmp(originalFlags, gSaveBlock1Ptr->flags, sizeof(originalFlags)), 0);
}
