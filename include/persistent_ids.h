#ifndef GUARD_PERSISTENT_IDS_H
#define GUARD_PERSISTENT_IDS_H

#include "global.h"

#define PERSISTENT_TRAINER_COUNT 1483
#define PERSISTENT_TRAINER_FLAG_COUNT 858
#define PERSISTENT_TRAINER_BITMAP_FIRST PERSISTENT_TRAINER_FLAG_COUNT
#define PERSISTENT_TRAINER_BITMAP_BITS 625
#define PERSISTENT_TRAINER_BITMAP_BYTES 79

enum TrainerDefeatStorage
{
    TRAINER_DEFEAT_STORAGE_FLAG,
    TRAINER_DEFEAT_STORAGE_VARIABLE_BIT,
    TRAINER_DEFEAT_STORAGE_BITMAP,
};

struct TrainerDefeatBinding
{
    u16 id;
    u8 storage;
    u8 bit;
};

extern const u16 gTrainerDefeatFlagById[PERSISTENT_TRAINER_COUNT];
extern const struct TrainerDefeatBinding gTrainerDefeatBindingById[PERSISTENT_TRAINER_COUNT];

bool32 PersistentId_GetTrainerDefeatBinding(u16 trainerId, struct TrainerDefeatBinding *binding);
bool32 PersistentId_GetTrainerDefeatFlag(u16 trainerId, u16 *flag);
bool32 PersistentId_GetTrainerDefeated(u16 trainerId, bool32 *defeated);
bool32 PersistentId_SetTrainerDefeated(u16 trainerId);
bool32 PersistentId_ClearTrainerDefeated(u16 trainerId);

#if TESTING
bool32 PersistentId_TestGetTrainerDefeated(const struct TrainerDefeatBinding *binding, bool32 *defeated);
bool32 PersistentId_TestSetTrainerDefeated(const struct TrainerDefeatBinding *binding);
bool32 PersistentId_TestClearTrainerDefeated(const struct TrainerDefeatBinding *binding);
#endif

#endif // GUARD_PERSISTENT_IDS_H
