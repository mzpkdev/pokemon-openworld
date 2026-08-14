#ifndef GUARD_REGIONAL_STORY_MIGRATION_H
#define GUARD_REGIONAL_STORY_MIGRATION_H

#include "global.h"

#define REGIONAL_STORY_MIGRATION_SIGNATURE 0x53
#define REGIONAL_STORY_MIGRATION_VERSION   2

enum RegionalStoryMigrationResult
{
    REGIONAL_STORY_MIGRATION_CURRENT,
    REGIONAL_STORY_MIGRATION_APPLIED,
    REGIONAL_STORY_MIGRATION_INVALID,
};

enum RegionalStoryMigrationResult RegionalStoryMigration_Apply(void);
u8 RegionalStoryMigration_AdjustLoadStatus(u8 saveStatus);
void RegionalStoryMigration_InitializeNewSave(void);

#endif // GUARD_REGIONAL_STORY_MIGRATION_H
