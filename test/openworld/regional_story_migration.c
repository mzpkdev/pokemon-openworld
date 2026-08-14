#include "global.h"
#include "event_data.h"
#include "regional_fact.h"
#include "regional_story_migration.h"
#include "reload_save.h"
#include "save.h"
#include "test/test.h"
#include "title_screen.h"
#include "overworld.h"

struct MigrationCase
{
    u8 signature;
    u8 version;
    enum RegionalStoryMigrationResult result;
    u8 expectedSignature;
    u8 expectedVersion;
};

static void SetMarker(u8 signature, u8 version)
{
    gSaveBlock1Ptr->unused_9C2[0] = signature;
    gSaveBlock1Ptr->unused_9C2[1] = version;
}

static void ExpectOnlyFastShipTerminalFlagChanged(const u8 *originalFlags)
{
    u8 expectedFlags[sizeof(gSaveBlock1Ptr->flags)];

    memcpy(expectedFlags, originalFlags, sizeof(expectedFlags));
    expectedFlags[FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED / 8]
        |= 1 << (FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED & 7);
    EXPECT_EQ(memcmp(expectedFlags, gSaveBlock1Ptr->flags, sizeof(expectedFlags)), 0);
}

TEST("Regional story migrations classify historical current and invalid saves")
{
    static const struct MigrationCase cases[] =
    {
        {0, 0, REGIONAL_STORY_MIGRATION_APPLIED, REGIONAL_STORY_MIGRATION_SIGNATURE, REGIONAL_STORY_MIGRATION_VERSION},
        {REGIONAL_STORY_MIGRATION_SIGNATURE, REGIONAL_STORY_MIGRATION_VERSION, REGIONAL_STORY_MIGRATION_CURRENT, REGIONAL_STORY_MIGRATION_SIGNATURE, REGIONAL_STORY_MIGRATION_VERSION},
        {REGIONAL_STORY_MIGRATION_SIGNATURE, 0, REGIONAL_STORY_MIGRATION_INVALID, REGIONAL_STORY_MIGRATION_SIGNATURE, 0},
        {REGIONAL_STORY_MIGRATION_SIGNATURE, REGIONAL_STORY_MIGRATION_VERSION + 1, REGIONAL_STORY_MIGRATION_INVALID, REGIONAL_STORY_MIGRATION_SIGNATURE, REGIONAL_STORY_MIGRATION_VERSION + 1},
        {0x52, REGIONAL_STORY_MIGRATION_VERSION, REGIONAL_STORY_MIGRATION_INVALID, 0x52, REGIONAL_STORY_MIGRATION_VERSION},
        {0, REGIONAL_STORY_MIGRATION_VERSION, REGIONAL_STORY_MIGRATION_INVALID, 0, REGIONAL_STORY_MIGRATION_VERSION},
        {0xFF, 0xFF, REGIONAL_STORY_MIGRATION_INVALID, 0xFF, 0xFF},
    };

    for (u32 i = 0; i < ARRAY_COUNT(cases); i++)
    {
        SetMarker(cases[i].signature, cases[i].version);
        EXPECT_EQ(RegionalStoryMigration_Apply(), cases[i].result);
        EXPECT_EQ(gSaveBlock1Ptr->unused_9C2[0], cases[i].expectedSignature);
        EXPECT_EQ(gSaveBlock1Ptr->unused_9C2[1], cases[i].expectedVersion);
    }
}

TEST("Invalid regional story versions preserve save state")
{
    u8 originalFlags[sizeof(gSaveBlock1Ptr->flags)];
    u16 originalVars[ARRAY_COUNT(gSaveBlock1Ptr->vars)];

    InitEventData();
    FlagSet(FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE);
    FlagSet(FLAG_BADGE01_GET);
    VarSet(VAR_SAFARI_ZONE_STATE, 0xA55A);
    memcpy(originalFlags, gSaveBlock1Ptr->flags, sizeof(originalFlags));
    memcpy(originalVars, gSaveBlock1Ptr->vars, sizeof(originalVars));
    SetMarker(REGIONAL_STORY_MIGRATION_SIGNATURE, REGIONAL_STORY_MIGRATION_VERSION + 1);

    EXPECT_EQ(RegionalStoryMigration_Apply(), REGIONAL_STORY_MIGRATION_INVALID);
    EXPECT_EQ(memcmp(originalFlags, gSaveBlock1Ptr->flags, sizeof(originalFlags)), 0);
    EXPECT_EQ(memcmp(originalVars, gSaveBlock1Ptr->vars, sizeof(originalVars)), 0);
    EXPECT_EQ(gSaveBlock1Ptr->unused_9C2[0], REGIONAL_STORY_MIGRATION_SIGNATURE);
    EXPECT_EQ(gSaveBlock1Ptr->unused_9C2[1], REGIONAL_STORY_MIGRATION_VERSION + 1);
}

TEST("Reload continues only supported regional story saves")
{
    EXPECT(IsSaveStatusContinuable(SAVE_STATUS_OK));
    EXPECT(IsSaveStatusContinuable(SAVE_STATUS_ERROR));
    EXPECT(!IsSaveStatusContinuable(SAVE_STATUS_UNSUPPORTED));
    EXPECT(!IsSaveStatusContinuable(SAVE_STATUS_CORRUPT));
    EXPECT(!IsSaveStatusContinuable(SAVE_STATUS_EMPTY));
    EXPECT_EQ(GetReloadSaveCallback(SAVE_STATUS_OK), CB2_ContinueSavedGame);
    EXPECT_EQ(GetReloadSaveCallback(SAVE_STATUS_ERROR), CB2_ContinueSavedGame);
    EXPECT_EQ(GetReloadSaveCallback(SAVE_STATUS_UNSUPPORTED), CB2_InitTitleScreen);
    EXPECT_EQ(GetReloadSaveCallback(SAVE_STATUS_CORRUPT), CB2_ContinueSavedGame);
    EXPECT_EQ(GetReloadSaveCallback(SAVE_STATUS_EMPTY), CB2_ContinueSavedGame);
}

TEST("Recovered saves apply regional story migration before Continue eligibility")
{
    static const struct MigrationCase cases[] =
    {
        {0, 0, REGIONAL_STORY_MIGRATION_APPLIED, REGIONAL_STORY_MIGRATION_SIGNATURE, REGIONAL_STORY_MIGRATION_VERSION},
        {REGIONAL_STORY_MIGRATION_SIGNATURE, REGIONAL_STORY_MIGRATION_VERSION, REGIONAL_STORY_MIGRATION_CURRENT, REGIONAL_STORY_MIGRATION_SIGNATURE, REGIONAL_STORY_MIGRATION_VERSION},
        {REGIONAL_STORY_MIGRATION_SIGNATURE, REGIONAL_STORY_MIGRATION_VERSION + 1, REGIONAL_STORY_MIGRATION_INVALID, REGIONAL_STORY_MIGRATION_SIGNATURE, REGIONAL_STORY_MIGRATION_VERSION + 1},
    };

    for (u32 i = 0; i < ARRAY_COUNT(cases); i++)
    {
        u8 expectedStatus = cases[i].result == REGIONAL_STORY_MIGRATION_INVALID
                          ? SAVE_STATUS_UNSUPPORTED
                          : SAVE_STATUS_ERROR;

        SetMarker(cases[i].signature, cases[i].version);
        EXPECT_EQ(RegionalStoryMigration_AdjustLoadStatus(SAVE_STATUS_ERROR), expectedStatus);
        EXPECT_EQ(gSaveBlock1Ptr->unused_9C2[0], cases[i].expectedSignature);
        EXPECT_EQ(gSaveBlock1Ptr->unused_9C2[1], cases[i].expectedVersion);
        EXPECT_EQ(IsSaveStatusContinuable(expectedStatus), expectedStatus == SAVE_STATUS_ERROR);
        EXPECT_EQ(
            GetReloadSaveCallback(expectedStatus),
            expectedStatus == SAVE_STATUS_ERROR ? CB2_ContinueSavedGame : CB2_InitTitleScreen
        );
    }
}

TEST("Every regional story migration is ordered and idempotent")
{
    InitEventData();
    SetMarker(0, 0);

    EXPECT_EQ(RegionalStoryMigration_Apply(), REGIONAL_STORY_MIGRATION_APPLIED);
    EXPECT(FlagGet(FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED));
    EXPECT_EQ(gSaveBlock1Ptr->unused_9C2[0], REGIONAL_STORY_MIGRATION_SIGNATURE);
    EXPECT_EQ(gSaveBlock1Ptr->unused_9C2[1], REGIONAL_STORY_MIGRATION_VERSION);
    EXPECT_EQ(RegionalStoryMigration_Apply(), REGIONAL_STORY_MIGRATION_CURRENT);
    EXPECT_EQ(gSaveBlock1Ptr->unused_9C2[0], REGIONAL_STORY_MIGRATION_SIGNATURE);
    EXPECT_EQ(gSaveBlock1Ptr->unused_9C2[1], REGIONAL_STORY_MIGRATION_VERSION);
}

TEST("Historical migration preserves regional fact and variable isolation")
{
    u8 originalFlags[sizeof(gSaveBlock1Ptr->flags)];
    u16 originalVars[ARRAY_COUNT(gSaveBlock1Ptr->vars)];

    InitEventData();
    FlagSet(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE);
    FlagSet(FLAG_REGIONAL_FACT_SEVII_DETOUR_FINISHED);
    VarSet(VAR_SAFARI_ZONE_STATE, 0x1111);
    VarSet(VAR_MAP_SCENE_CERULEAN_CITY_RIVAL, 0x2222);
    VarSet(VAR_MAP_SCENE_ONE_ISLAND_HARBOR, 0x3333);
    VarSet(VAR_CHERRYGROVE_CITY_STATE, 0x4444);
    memcpy(originalFlags, gSaveBlock1Ptr->flags, sizeof(originalFlags));
    memcpy(originalVars, gSaveBlock1Ptr->vars, sizeof(originalVars));
    SetMarker(0, 0);

    EXPECT_EQ(RegionalStoryMigration_Apply(), REGIONAL_STORY_MIGRATION_APPLIED);
    ExpectOnlyFastShipTerminalFlagChanged(originalFlags);
    EXPECT_EQ(memcmp(originalVars, gSaveBlock1Ptr->vars, sizeof(originalVars)), 0);
    EXPECT(RegionalFact_Get(REGIONAL_FACT_HOENN_STONE_BADGE));
    EXPECT(RegionalFact_Get(REGIONAL_FACT_SEVII_DETOUR_FINISHED));
    EXPECT(!RegionalFact_Get(REGIONAL_FACT_KANTO_CASCADE_BADGE));
    EXPECT(!RegionalFact_Get(REGIONAL_FACT_JOHTO_HIVE_BADGE));
}

TEST("Historical mechanics grants do not fabricate regional story facts")
{
    static const u16 legacyBadgeFlags[] =
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

    InitEventData();
    for (u32 i = 0; i < ARRAY_COUNT(legacyBadgeFlags); i++)
        FlagSet(legacyBadgeFlags[i]);
    SetMarker(0, 0);

    EXPECT_EQ(RegionalStoryMigration_Apply(), REGIONAL_STORY_MIGRATION_APPLIED);
    for (u32 i = 0; i < REGIONAL_FACT_COUNT; i++)
        EXPECT(!RegionalFact_Get(i));
    for (u32 i = 0; i < ARRAY_COUNT(legacyBadgeFlags); i++)
        EXPECT(FlagGet(legacyBadgeFlags[i]));
}

TEST("New saves start at the current regional story version")
{
    InitEventData();
    SetMarker(0xFF, 0xFF);
    RegionalStoryMigration_InitializeNewSave();

    EXPECT(FlagGet(FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED));
    EXPECT_EQ(gSaveBlock1Ptr->unused_9C2[0], REGIONAL_STORY_MIGRATION_SIGNATURE);
    EXPECT_EQ(gSaveBlock1Ptr->unused_9C2[1], REGIONAL_STORY_MIGRATION_VERSION);
    EXPECT_EQ(RegionalStoryMigration_Apply(), REGIONAL_STORY_MIGRATION_CURRENT);
}

TEST("Unversioned and version one saves default the fast ship terminal lock")
{
    static const u8 historicalVersions[] = {0, 1};

    for (u32 i = 0; i < ARRAY_COUNT(historicalVersions); i++)
    {
        u8 originalFlags[sizeof(gSaveBlock1Ptr->flags)];
        u16 originalVars[ARRAY_COUNT(gSaveBlock1Ptr->vars)];

        InitEventData();
        FlagSet(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE);
        FlagSet(FLAG_BADGE01_GET);
        VarSet(VAR_SAFARI_ZONE_STATE, 0xA55A);
        memcpy(originalFlags, gSaveBlock1Ptr->flags, sizeof(originalFlags));
        memcpy(originalVars, gSaveBlock1Ptr->vars, sizeof(originalVars));
        if (historicalVersions[i] == 0)
            SetMarker(0, 0);
        else
            SetMarker(REGIONAL_STORY_MIGRATION_SIGNATURE, historicalVersions[i]);

        EXPECT_EQ(RegionalStoryMigration_Apply(), REGIONAL_STORY_MIGRATION_APPLIED);
        EXPECT(FlagGet(FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED));
        ExpectOnlyFastShipTerminalFlagChanged(originalFlags);
        EXPECT_EQ(memcmp(originalVars, gSaveBlock1Ptr->vars, sizeof(originalVars)), 0);
        EXPECT_EQ(gSaveBlock1Ptr->unused_9C2[0], REGIONAL_STORY_MIGRATION_SIGNATURE);
        EXPECT_EQ(gSaveBlock1Ptr->unused_9C2[1], REGIONAL_STORY_MIGRATION_VERSION);
    }
}

TEST("Current regional story saves preserve a deliberately cleared terminal lock")
{
    u8 originalFlags[sizeof(gSaveBlock1Ptr->flags)];
    u16 originalVars[ARRAY_COUNT(gSaveBlock1Ptr->vars)];

    InitEventData();
    FlagSet(FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE);
    VarSet(VAR_MAP_SCENE_CERULEAN_CITY_RIVAL, 0x1234);
    FlagClear(FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED);
    SetMarker(REGIONAL_STORY_MIGRATION_SIGNATURE, REGIONAL_STORY_MIGRATION_VERSION);
    memcpy(originalFlags, gSaveBlock1Ptr->flags, sizeof(originalFlags));
    memcpy(originalVars, gSaveBlock1Ptr->vars, sizeof(originalVars));

    EXPECT_EQ(RegionalStoryMigration_Apply(), REGIONAL_STORY_MIGRATION_CURRENT);
    EXPECT(!FlagGet(FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED));
    EXPECT_EQ(memcmp(originalFlags, gSaveBlock1Ptr->flags, sizeof(originalFlags)), 0);
    EXPECT_EQ(memcmp(originalVars, gSaveBlock1Ptr->vars, sizeof(originalVars)), 0);
}
