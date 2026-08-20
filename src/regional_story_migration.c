#include "global.h"
#include "event_data.h"
#include "regional_story_migration.h"
#include "save.h"
#include "constants/flags.h"

struct RegionalStoryMigration
{
    u8 fromVersion;
    u8 toVersion;
    bool32 (*apply)(void);
};

enum HistoricalRegionalStoryFlag
{
    // These FRLG flags retain their raw saved identifiers from
    // constants/flags_frlg.h. The all-regions facade otherwise replaces their
    // inactive-build symbols with zero.
    HISTORICAL_FLAG_GOT_HM01 = 0x237,
    HISTORICAL_FLAG_RESCUED_MR_FUJI = 0x23C,
    HISTORICAL_FLAG_GOT_MASTER_BALL_FROM_SILPH = 0x250,
    HISTORICAL_FLAG_RESCUED_LOSTELLE = 0x2A3,
    HISTORICAL_FLAG_RECOVERED_SAPPHIRE = 0x2DC,
    HISTORICAL_FLAG_GOT_RUBY = 0x2DD,
};

static bool32 MigrateUnversionedSave(void)
{
    // The legacy mechanics grants are intentionally ambiguous. Regional facts
    // and variables already retain their serialized values; do not infer any
    // new regional story meaning from the legacy badge slots.
    return TRUE;
}

static bool32 MigrateFastShipTerminalDefault(void)
{
    FlagSet(FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED);
    return TRUE;
}

static bool32 MigrateExactRegionalStoryFacts(void)
{
    // Each source flag is set by the same event script immediately before its
    // regional fact. Generic badge slots remain intentionally unmapped.
    static const struct
    {
        u16 historicalFlag;
        u16 regionalFactFlag;
    } facts[] =
    {
        {HISTORICAL_FLAG_GOT_HM01,          FLAG_REGIONAL_FACT_KANTO_SS_ANNE_CUT_RECEIVED},
        {HISTORICAL_FLAG_RESCUED_MR_FUJI,   FLAG_REGIONAL_FACT_KANTO_MR_FUJI_RESCUED},
        {HISTORICAL_FLAG_GOT_MASTER_BALL_FROM_SILPH, FLAG_REGIONAL_FACT_KANTO_SILPH_SAVED},
        {FLAG_DELIVERED_DEVON_GOODS,        FLAG_REGIONAL_FACT_HOENN_DEVON_GOODS_DELIVERED},
        {FLAG_RECEIVED_HM_SURF,             FLAG_REGIONAL_FACT_HOENN_SURF_RECEIVED},
        {FLAG_RECEIVED_DEVON_SCOPE,         FLAG_REGIONAL_FACT_HOENN_DEVON_SCOPE_RECEIVED},
        {FLAG_RECEIVED_HM_DIVE,             FLAG_REGIONAL_FACT_HOENN_DIVE_RECEIVED},
        {FLAG_DEFEATED_WALLY_VICTORY_ROAD,  FLAG_REGIONAL_FACT_HOENN_WALLY_VICTORY_ROAD_DEFEATED},
        {FLAG_RECEIVED_HM_WATERFALL,        FLAG_REGIONAL_FACT_HOENN_WATERFALL_RECEIVED},
        {HISTORICAL_FLAG_RESCUED_LOSTELLE,  FLAG_REGIONAL_FACT_SEVII_LOSTELLE_RESCUED},
        {HISTORICAL_FLAG_GOT_RUBY,          FLAG_REGIONAL_FACT_SEVII_RUBY_RECOVERED},
        {HISTORICAL_FLAG_RECOVERED_SAPPHIRE, FLAG_REGIONAL_FACT_SEVII_SAPPHIRE_RECOVERED},
    };

    for (u32 i = 0; i < ARRAY_COUNT(facts); i++)
    {
        if (FlagGet(facts[i].historicalFlag))
            FlagSet(facts[i].regionalFactFlag);
    }

    // The Space Center's completion scene persistently commits both values
    // before it sets its transient defeated flag, which is cleared later.
    if (VarGet(VAR_MOSSDEEP_CITY_STATE) == 3
     && VarGet(VAR_MOSSDEEP_SPACE_CENTER_STATE) == 3)
        FlagSet(FLAG_REGIONAL_FACT_HOENN_SPACE_CENTER_SAVED);

    // FLAG_DEFEATED_CHAMP is cleared after the Hall of Fame and
    // FLAG_IS_CHAMPION does not distinguish the Kanto and Hoenn stories, so
    // neither can truthfully backfill KANTO_CHAMPION_CROWNED.
    return TRUE;
}

static const struct RegionalStoryMigration sRegionalStoryMigrations[] =
{
    {0, 1, MigrateUnversionedSave},
    {1, 2, MigrateFastShipTerminalDefault},
    {2, 3, MigrateExactRegionalStoryFacts},
};

static u8 *MigrationMarker(void)
{
    // This is the frozen two-byte reserve at SaveBlock1 offset 0x9C2. Keeping
    // the existing member preserves the physical save ABI and its authority.
    return gSaveBlock1Ptr->unused_9C2;
}

static void StampCurrentMigrationMarker(void)
{
    u8 *marker = MigrationMarker();

    marker[0] = REGIONAL_STORY_MIGRATION_SIGNATURE;
    marker[1] = REGIONAL_STORY_MIGRATION_VERSION;
}

void RegionalStoryMigration_InitializeNewSave(void)
{
    StampCurrentMigrationMarker();
    FlagSet(FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED);
}

enum RegionalStoryMigrationResult RegionalStoryMigration_Apply(void)
{
    u8 *marker = MigrationMarker();
    u8 version;
    bool32 applied = FALSE;

    if (marker[0] == 0 && marker[1] == 0)
    {
        version = 0;
    }
    else
    {
        if (marker[0] != REGIONAL_STORY_MIGRATION_SIGNATURE
         || marker[1] == 0
         || marker[1] > REGIONAL_STORY_MIGRATION_VERSION)
            return REGIONAL_STORY_MIGRATION_INVALID;
        version = marker[1];
    }

    while (version < REGIONAL_STORY_MIGRATION_VERSION)
    {
        const struct RegionalStoryMigration *migration = NULL;

        for (u32 i = 0; i < ARRAY_COUNT(sRegionalStoryMigrations); i++)
        {
            if (sRegionalStoryMigrations[i].fromVersion == version)
            {
                migration = &sRegionalStoryMigrations[i];
                break;
            }
        }
        if (migration == NULL
         || migration->toVersion <= version
         || migration->toVersion > REGIONAL_STORY_MIGRATION_VERSION
         || !migration->apply())
            return REGIONAL_STORY_MIGRATION_INVALID;

        version = migration->toVersion;
        applied = TRUE;
    }

    if (applied)
        StampCurrentMigrationMarker();

    return applied ? REGIONAL_STORY_MIGRATION_APPLIED : REGIONAL_STORY_MIGRATION_CURRENT;
}

u8 RegionalStoryMigration_AdjustLoadStatus(u8 saveStatus)
{
    if (saveStatus != SAVE_STATUS_OK && saveStatus != SAVE_STATUS_ERROR)
        return saveStatus;
    if (RegionalStoryMigration_Apply() == REGIONAL_STORY_MIGRATION_INVALID)
        return SAVE_STATUS_UNSUPPORTED;
    return saveStatus;
}
