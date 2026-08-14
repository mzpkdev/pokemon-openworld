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

static const struct RegionalStoryMigration sRegionalStoryMigrations[] =
{
    {0, 1, MigrateUnversionedSave},
    {1, 2, MigrateFastShipTerminalDefault},
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
