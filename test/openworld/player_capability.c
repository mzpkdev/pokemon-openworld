#include "global.h"
#include "event_data.h"
#include "field_move.h"
#include "player_capability.h"
#include "regional_fact.h"
#include "test/test.h"
#include "constants/field_move.h"

struct CapabilityCase
{
    enum PlayerCapability capability;
    enum FieldMove fieldMove;
    u16 legacyFlag;
};

struct FactGrant
{
    enum RegionalFact fact;
    u16 flag;
    enum PlayerCapability capability;
    enum FieldMove fieldMove;
};

static const struct CapabilityCase sCapabilityCases[] =
{
    {PLAYER_CAPABILITY_CUT,        FIELD_MOVE_CUT,        FLAG_BADGE01_GET},
    {PLAYER_CAPABILITY_FLASH,      FIELD_MOVE_FLASH,      FLAG_BADGE02_GET},
    {PLAYER_CAPABILITY_ROCK_SMASH, FIELD_MOVE_ROCK_SMASH, FLAG_BADGE03_GET},
    {PLAYER_CAPABILITY_STRENGTH,   FIELD_MOVE_STRENGTH,   FLAG_BADGE04_GET},
    {PLAYER_CAPABILITY_SURF,       FIELD_MOVE_SURF,       FLAG_BADGE05_GET},
    {PLAYER_CAPABILITY_FLY,        FIELD_MOVE_FLY,        FLAG_BADGE06_GET},
    {PLAYER_CAPABILITY_DIVE,       FIELD_MOVE_DIVE,       FLAG_BADGE07_GET},
    {PLAYER_CAPABILITY_WATERFALL,  FIELD_MOVE_WATERFALL,  FLAG_BADGE08_GET},
};

static const struct FactGrant sFactGrants[] =
{
    {REGIONAL_FACT_HOENN_STONE_BADGE,     FLAG_REGIONAL_FACT_HOENN_STONE_BADGE,     PLAYER_CAPABILITY_CUT,        FIELD_MOVE_CUT},
    {REGIONAL_FACT_KANTO_CASCADE_BADGE,   FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE,   PLAYER_CAPABILITY_CUT,        FIELD_MOVE_CUT},
    {REGIONAL_FACT_JOHTO_HIVE_BADGE,      FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE,      PLAYER_CAPABILITY_CUT,        FIELD_MOVE_CUT},
    {REGIONAL_FACT_HOENN_KNUCKLE_BADGE,   FLAG_REGIONAL_FACT_HOENN_KNUCKLE_BADGE,   PLAYER_CAPABILITY_FLASH,      FIELD_MOVE_FLASH},
    {REGIONAL_FACT_KANTO_BOULDER_BADGE,   FLAG_REGIONAL_FACT_KANTO_BOULDER_BADGE,   PLAYER_CAPABILITY_FLASH,      FIELD_MOVE_FLASH},
    {REGIONAL_FACT_JOHTO_ZEPHYR_BADGE,    FLAG_REGIONAL_FACT_JOHTO_ZEPHYR_BADGE,    PLAYER_CAPABILITY_FLASH,      FIELD_MOVE_FLASH},
    {REGIONAL_FACT_HOENN_DYNAMO_BADGE,    FLAG_REGIONAL_FACT_HOENN_DYNAMO_BADGE,    PLAYER_CAPABILITY_ROCK_SMASH, FIELD_MOVE_ROCK_SMASH},
    {REGIONAL_FACT_KANTO_MARSH_BADGE,     FLAG_REGIONAL_FACT_KANTO_MARSH_BADGE,     PLAYER_CAPABILITY_ROCK_SMASH, FIELD_MOVE_ROCK_SMASH},
    {REGIONAL_FACT_HOENN_HEAT_BADGE,      FLAG_REGIONAL_FACT_HOENN_HEAT_BADGE,      PLAYER_CAPABILITY_STRENGTH,   FIELD_MOVE_STRENGTH},
    {REGIONAL_FACT_KANTO_RAINBOW_BADGE,   FLAG_REGIONAL_FACT_KANTO_RAINBOW_BADGE,   PLAYER_CAPABILITY_STRENGTH,   FIELD_MOVE_STRENGTH},
    {REGIONAL_FACT_JOHTO_PLAIN_BADGE,     FLAG_REGIONAL_FACT_JOHTO_PLAIN_BADGE,     PLAYER_CAPABILITY_STRENGTH,   FIELD_MOVE_STRENGTH},
    {REGIONAL_FACT_HOENN_BALANCE_BADGE,   FLAG_REGIONAL_FACT_HOENN_BALANCE_BADGE,   PLAYER_CAPABILITY_SURF,       FIELD_MOVE_SURF},
    {REGIONAL_FACT_KANTO_SOUL_BADGE,      FLAG_REGIONAL_FACT_KANTO_SOUL_BADGE,      PLAYER_CAPABILITY_SURF,       FIELD_MOVE_SURF},
    {REGIONAL_FACT_JOHTO_FOG_BADGE,       FLAG_REGIONAL_FACT_JOHTO_FOG_BADGE,       PLAYER_CAPABILITY_SURF,       FIELD_MOVE_SURF},
    {REGIONAL_FACT_HOENN_FEATHER_BADGE,   FLAG_REGIONAL_FACT_HOENN_FEATHER_BADGE,   PLAYER_CAPABILITY_FLY,        FIELD_MOVE_FLY},
    {REGIONAL_FACT_KANTO_THUNDER_BADGE,   FLAG_REGIONAL_FACT_KANTO_THUNDER_BADGE,   PLAYER_CAPABILITY_FLY,        FIELD_MOVE_FLY},
    {REGIONAL_FACT_JOHTO_STORM_BADGE,     FLAG_REGIONAL_FACT_JOHTO_STORM_BADGE,     PLAYER_CAPABILITY_FLY,        FIELD_MOVE_FLY},
    {REGIONAL_FACT_HOENN_MIND_BADGE,      FLAG_REGIONAL_FACT_HOENN_MIND_BADGE,      PLAYER_CAPABILITY_DIVE,       FIELD_MOVE_DIVE},
    {REGIONAL_FACT_HOENN_RAIN_BADGE,      FLAG_REGIONAL_FACT_HOENN_RAIN_BADGE,      PLAYER_CAPABILITY_WATERFALL,  FIELD_MOVE_WATERFALL},
    {REGIONAL_FACT_KANTO_VOLCANO_BADGE,   FLAG_REGIONAL_FACT_KANTO_VOLCANO_BADGE,   PLAYER_CAPABILITY_WATERFALL,  FIELD_MOVE_WATERFALL},
    {REGIONAL_FACT_JOHTO_RISING_BADGE,    FLAG_REGIONAL_FACT_JOHTO_RISING_BADGE,    PLAYER_CAPABILITY_WATERFALL,  FIELD_MOVE_WATERFALL},
};

static EWRAM_DATA struct SaveBlock1 sOriginalSaveBlock1;
static EWRAM_DATA struct SaveBlock2 sOriginalSaveBlock2;
static EWRAM_DATA struct SaveBlock3 sOriginalSaveBlock3;

static void ClearCapabilityFacts(void)
{
    for (u32 i = 0; i < ARRAY_COUNT(sFactGrants); i++)
        FlagClear(sFactGrants[i].flag);
    for (u32 i = 0; i < ARRAY_COUNT(sCapabilityCases); i++)
        FlagClear(sCapabilityCases[i].legacyFlag);
    FlagClear(FLAG_REGIONAL_FACT_SEVII_DETOUR_FINISHED);
    FlagClear(FLAG_UNUSED_0x035);
}

static void ExpectOnlyCapability(enum PlayerCapability expected)
{
    for (u32 i = 0; i < ARRAY_COUNT(sCapabilityCases); i++)
    {
        bool32 granted = sCapabilityCases[i].capability == expected;

        EXPECT_EQ(PlayerHasCapability(sCapabilityCases[i].capability), granted);
        EXPECT_EQ(IsFieldMoveUnlocked(sCapabilityCases[i].fieldMove), granted);
    }
}

TEST("Every exact regional fact independently grants its named capability")
{
    for (u32 i = 0; i < ARRAY_COUNT(sFactGrants); i++)
    {
        ClearCapabilityFacts();
        FlagSet(sFactGrants[i].flag);

        for (u32 j = 0; j < ARRAY_COUNT(sFactGrants); j++)
            EXPECT_EQ(RegionalFact_Get(sFactGrants[j].fact), i == j);
        EXPECT(PlayerHasCapability(sFactGrants[i].capability));
        EXPECT(IsFieldMoveUnlocked(sFactGrants[i].fieldMove));
        ExpectOnlyCapability(sFactGrants[i].capability);
    }
}

TEST("Sevii regional state stays independent of field capabilities")
{
    ClearCapabilityFacts();
    FlagSet(FLAG_REGIONAL_FACT_SEVII_DETOUR_FINISHED);

    EXPECT(RegionalFact_Get(REGIONAL_FACT_SEVII_DETOUR_FINISHED));
    for (u32 i = 0; i < ARRAY_COUNT(sFactGrants); i++)
        EXPECT(!RegionalFact_Get(sFactGrants[i].fact));
    for (u32 i = 0; i < ARRAY_COUNT(sCapabilityCases); i++)
    {
        EXPECT(!PlayerHasCapability(sCapabilityCases[i].capability));
        EXPECT(!IsFieldMoveUnlocked(sCapabilityCases[i].fieldMove));
    }
}

TEST("Every shipped legacy badge slot independently grants its named capability")
{
    for (u32 i = 0; i < ARRAY_COUNT(sCapabilityCases); i++)
    {
        ClearCapabilityFacts();
        FlagSet(sCapabilityCases[i].legacyFlag);
        ExpectOnlyCapability(sCapabilityCases[i].capability);
    }
}

TEST("Capability resolver denies absent, unrelated, and unknown state")
{
    ClearCapabilityFacts();
    for (u32 i = 0; i < ARRAY_COUNT(sCapabilityCases); i++)
    {
        EXPECT(!PlayerHasCapability(sCapabilityCases[i].capability));
        EXPECT(!IsFieldMoveUnlocked(sCapabilityCases[i].fieldMove));
    }

    FlagSet(FLAG_UNUSED_0x035);
    for (u32 i = 0; i < ARRAY_COUNT(sCapabilityCases); i++)
    {
        EXPECT(!PlayerHasCapability(sCapabilityCases[i].capability));
        EXPECT(!IsFieldMoveUnlocked(sCapabilityCases[i].fieldMove));
    }

    EXPECT(!RegionalFact_Get(REGIONAL_FACT_COUNT));
    EXPECT(!RegionalFact_Get((enum RegionalFact)0xFFFF));
    EXPECT(!PlayerHasCapability(PLAYER_CAPABILITY_COUNT));
    EXPECT(!PlayerHasCapability((enum PlayerCapability)0xFFFF));
}

TEST("Utility moves stay available and unsupported moves stay disabled")
{
    static const enum FieldMove utilityMoves[] =
    {
        FIELD_MOVE_TELEPORT,
        FIELD_MOVE_DIG,
        FIELD_MOVE_SECRET_POWER,
        FIELD_MOVE_MILK_DRINK,
        FIELD_MOVE_SOFT_BOILED,
        FIELD_MOVE_SWEET_SCENT,
    };
    static const enum FieldMove unsupportedMoves[] =
    {
        FIELD_MOVE_ROCK_CLIMB,
        FIELD_MOVE_DEFOG,
    };

    ClearCapabilityFacts();
    for (u32 i = 0; i < ARRAY_COUNT(utilityMoves); i++)
        EXPECT(IsFieldMoveUnlocked(utilityMoves[i]));
    for (u32 i = 0; i < ARRAY_COUNT(unsupportedMoves); i++)
        EXPECT(!IsFieldMoveUnlocked(unsupportedMoves[i]));
}

TEST("Regional fact, capability, and field move queries are pure")
{
    ClearCapabilityFacts();
    FlagSet(FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE);
    FlagSet(FLAG_REGIONAL_FACT_JOHTO_FOG_BADGE);
    FlagSet(FLAG_BADGE06_GET);
    FlagSet(FLAG_UNUSED_0x035);
    memcpy(&sOriginalSaveBlock1, gSaveBlock1Ptr, sizeof(sOriginalSaveBlock1));
    memcpy(&sOriginalSaveBlock2, gSaveBlock2Ptr, sizeof(sOriginalSaveBlock2));
    memcpy(&sOriginalSaveBlock3, gSaveBlock3Ptr, sizeof(sOriginalSaveBlock3));

    for (u32 i = 0; i < ARRAY_COUNT(sFactGrants); i++)
        RegionalFact_Get(sFactGrants[i].fact);
    RegionalFact_Get(REGIONAL_FACT_SEVII_DETOUR_FINISHED);
    for (u32 i = 0; i < ARRAY_COUNT(sCapabilityCases); i++)
    {
        PlayerHasCapability(sCapabilityCases[i].capability);
        IsFieldMoveUnlocked(sCapabilityCases[i].fieldMove);
    }
    IsFieldMoveUnlocked(FIELD_MOVE_TELEPORT);
    IsFieldMoveUnlocked(FIELD_MOVE_ROCK_CLIMB);
    IsFieldMoveUnlocked(FIELD_MOVE_DEFOG);

    EXPECT_EQ(memcmp(&sOriginalSaveBlock1, gSaveBlock1Ptr, sizeof(sOriginalSaveBlock1)), 0);
    EXPECT_EQ(memcmp(&sOriginalSaveBlock2, gSaveBlock2Ptr, sizeof(sOriginalSaveBlock2)), 0);
    EXPECT_EQ(memcmp(&sOriginalSaveBlock3, gSaveBlock3Ptr, sizeof(sOriginalSaveBlock3)), 0);
}
