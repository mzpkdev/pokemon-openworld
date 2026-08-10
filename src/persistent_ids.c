#include "global.h"
#include "event_data.h"
#include "persistent_ids.h"

#include "data/persistence/trainer_defeat_flags.inc.c"
#include "data/persistence/trainer_defeat_bindings.inc.c"

#define TRAINER_DEFEAT_DEBUG_FLAG_FIRST 0x8FE
#define TRAINER_DEFEAT_DEBUG_FLAG_LAST  0x8FF

static bool32 IsPersistentFlag(u16 id)
{
    if (id <= TEMP_FLAGS_END || id >= DAILY_FLAGS_START)
        return FALSE;
    if (id >= TRAINER_DEFEAT_DEBUG_FLAG_FIRST && id <= TRAINER_DEFEAT_DEBUG_FLAG_LAST)
        return FALSE;
    return GetFlagPointer(id) != NULL;
}

static bool32 IsPersistentVariable(u16 id)
{
    if (id <= TEMP_VARS_END || id > VARS_END)
        return FALSE;
    if ((id >= VAR_DAILY_SLOTS && id <= VAR_DAILY_ROULETTE) || id == VAR_DAILY_BP)
        return FALSE;
    return GetVarPointer(id) != NULL;
}

static bool32 ValidateTrainerDefeatBinding(const struct TrainerDefeatBinding *binding)
{
    if (binding == NULL)
        return FALSE;

    switch (binding->storage)
    {
    case TRAINER_DEFEAT_STORAGE_FLAG:
        return binding->bit == 0 && IsPersistentFlag(binding->id);
    case TRAINER_DEFEAT_STORAGE_VARIABLE_BIT:
        return binding->bit < 16 && IsPersistentVariable(binding->id);
    default:
        return FALSE;
    }
}

bool32 PersistentId_GetTrainerDefeatBinding(u16 trainerId, struct TrainerDefeatBinding *binding)
{
    struct TrainerDefeatBinding resolved;

    if (trainerId >= PERSISTENT_TRAINER_COUNT || binding == NULL)
        return FALSE;
    resolved = gTrainerDefeatBindingById[trainerId];
    if (!ValidateTrainerDefeatBinding(&resolved))
        return FALSE;
    *binding = resolved;
    return TRUE;
}

bool32 PersistentId_GetTrainerDefeatFlag(u16 trainerId, u16 *flag)
{
    struct TrainerDefeatBinding binding;

    if (flag == NULL || !PersistentId_GetTrainerDefeatBinding(trainerId, &binding))
        return FALSE;
    if (binding.storage != TRAINER_DEFEAT_STORAGE_FLAG)
        return FALSE;
    *flag = binding.id;
    return TRUE;
}

static bool32 GetTrainerDefeated(const struct TrainerDefeatBinding *binding, bool32 *defeated)
{
    if (defeated == NULL || !ValidateTrainerDefeatBinding(binding))
        return FALSE;

    switch (binding->storage)
    {
    case TRAINER_DEFEAT_STORAGE_FLAG:
        *defeated = FlagGet(binding->id);
        return TRUE;
    case TRAINER_DEFEAT_STORAGE_VARIABLE_BIT:
        *defeated = (VarGet(binding->id) & (1 << binding->bit)) != 0;
        return TRUE;
    default:
        return FALSE;
    }
}

static bool32 SetTrainerDefeated(const struct TrainerDefeatBinding *binding)
{
    if (!ValidateTrainerDefeatBinding(binding))
        return FALSE;

    switch (binding->storage)
    {
    case TRAINER_DEFEAT_STORAGE_FLAG:
        FlagSet(binding->id);
        return FlagGet(binding->id) == TRUE;
    case TRAINER_DEFEAT_STORAGE_VARIABLE_BIT:
        if (!VarSet(binding->id, VarGet(binding->id) | (1 << binding->bit)))
            return FALSE;
        return (VarGet(binding->id) & (1 << binding->bit)) != 0;
    default:
        return FALSE;
    }
}

static bool32 ClearTrainerDefeated(const struct TrainerDefeatBinding *binding)
{
    if (!ValidateTrainerDefeatBinding(binding))
        return FALSE;

    switch (binding->storage)
    {
    case TRAINER_DEFEAT_STORAGE_FLAG:
        FlagClear(binding->id);
        return FlagGet(binding->id) == FALSE;
    case TRAINER_DEFEAT_STORAGE_VARIABLE_BIT:
        if (!VarSet(binding->id, VarGet(binding->id) & ~(1 << binding->bit)))
            return FALSE;
        return (VarGet(binding->id) & (1 << binding->bit)) == 0;
    default:
        return FALSE;
    }
}

bool32 PersistentId_GetTrainerDefeated(u16 trainerId, bool32 *defeated)
{
    struct TrainerDefeatBinding binding;

    if (!PersistentId_GetTrainerDefeatBinding(trainerId, &binding))
        return FALSE;
    return GetTrainerDefeated(&binding, defeated);
}

bool32 PersistentId_SetTrainerDefeated(u16 trainerId)
{
    struct TrainerDefeatBinding binding;

    if (!PersistentId_GetTrainerDefeatBinding(trainerId, &binding))
        return FALSE;
    return SetTrainerDefeated(&binding);
}

bool32 PersistentId_ClearTrainerDefeated(u16 trainerId)
{
    struct TrainerDefeatBinding binding;

    if (!PersistentId_GetTrainerDefeatBinding(trainerId, &binding))
        return FALSE;
    return ClearTrainerDefeated(&binding);
}

#if TESTING
bool32 PersistentId_TestGetTrainerDefeated(const struct TrainerDefeatBinding *binding, bool32 *defeated)
{
    return GetTrainerDefeated(binding, defeated);
}

bool32 PersistentId_TestSetTrainerDefeated(const struct TrainerDefeatBinding *binding)
{
    return SetTrainerDefeated(binding);
}

bool32 PersistentId_TestClearTrainerDefeated(const struct TrainerDefeatBinding *binding)
{
    return ClearTrainerDefeated(binding);
}
#endif
