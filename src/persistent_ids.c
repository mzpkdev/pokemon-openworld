#include "global.h"
#include "persistent_ids.h"

#include "data/persistence/trainer_defeat_flags.inc.c"

bool32 PersistentId_GetTrainerDefeatFlag(u16 trainerId, u16 *flag)
{
    if (trainerId >= PERSISTENT_TRAINER_COUNT || flag == NULL)
        return FALSE;
    *flag = gTrainerDefeatFlagById[trainerId];
    return TRUE;
}
