#include "global.h"
#include "battle_setup.h"
#include "trainer_rematch_registry.h"
#include "constants/opponents.h"
#include "constants/rematches.h"

#include "data/trainer_rematches/frlg.inc.c"

static struct TrainerRematchBinding GetMatchCallBinding(u16 trainerId)
{
    u32 i;
    u32 stage;

    for (i = 0; i < REMATCH_TABLE_ENTRIES; i++)
    {
        for (stage = 0; stage < REMATCHES_COUNT; stage++)
        {
            u16 candidate = gRematchTable[i].trainerIds[stage];

            if (candidate == 0)
                break;
            if (candidate == trainerId)
            {
                return (struct TrainerRematchBinding)
                {
                    .kind = TRAINER_REMATCH_BINDING_MATCH_CALL,
                    .index = i,
                };
            }
        }
    }

    return (struct TrainerRematchBinding) { .kind = TRAINER_REMATCH_BINDING_INVALID };
}

struct TrainerRematchBinding TrainerRematch_GetBinding(u16 trainerId)
{
    struct TrainerRematchBinding binding;

    if (trainerId == TRAINER_NONE || trainerId >= TRAINERS_COUNT)
        return (struct TrainerRematchBinding) { .kind = TRAINER_REMATCH_BINDING_INVALID };

    if (trainerId < TRAINERS_COUNT_EMERALD)
        return GetMatchCallBinding(trainerId);

    binding = sTrainerRematchBindings_FRLG[trainerId];
    if (binding.kind == TRAINER_REMATCH_BINDING_CHAIN)
    {
        if (binding.index >= FRLG_TRAINER_REMATCH_CHAIN_COUNT)
            binding.kind = TRAINER_REMATCH_BINDING_INVALID;
    }
    else if (binding.kind != TRAINER_REMATCH_BINDING_NONE)
    {
        binding.kind = TRAINER_REMATCH_BINDING_INVALID;
    }

    return binding;
}

bool32 TrainerRematch_TryResolveStage(u16 trainerId, u8 stage, u16 *resolvedTrainerId)
{
    struct TrainerRematchBinding binding;
    u16 candidate;

    if (resolvedTrainerId == NULL || stage >= TRAINER_REMATCH_STAGE_COUNT)
        return FALSE;

    binding = TrainerRematch_GetBinding(trainerId);
    if (binding.kind != TRAINER_REMATCH_BINDING_VS_SEEKER)
        return FALSE;

    candidate = sTrainerRematchChains_FRLG[binding.index].trainerIds[stage];
    if (candidate == 0)
        return FALSE;

    while (candidate == TRAINER_REMATCH_STAGE_SKIP)
    {
        if (stage == 0)
            return FALSE;
        candidate = sTrainerRematchChains_FRLG[binding.index].trainerIds[--stage];
        if (candidate == 0)
            return FALSE;
    }

    if (candidate < TRAINERS_COUNT_EMERALD || candidate >= TRAINERS_COUNT)
        return FALSE;

    *resolvedTrainerId = candidate;
    return TRUE;
}
