#ifndef GUARD_PERSISTENT_IDS_H
#define GUARD_PERSISTENT_IDS_H

#include "global.h"

#define PERSISTENT_TRAINER_COUNT 858

extern const u16 gTrainerDefeatFlagById[PERSISTENT_TRAINER_COUNT];
bool32 PersistentId_GetTrainerDefeatFlag(u16 trainerId, u16 *flag);

#endif // GUARD_PERSISTENT_IDS_H
