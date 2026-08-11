#ifndef GUARD_TRAINER_REMATCH_REGISTRY_H
#define GUARD_TRAINER_REMATCH_REGISTRY_H

#include "global.h"

#define TRAINER_REMATCH_STAGE_COUNT 6
#define TRAINER_REMATCH_STAGE_SKIP  0xFFFF

enum TrainerRematchBindingKind
{
    TRAINER_REMATCH_BINDING_INVALID,
    TRAINER_REMATCH_BINDING_NONE,
    TRAINER_REMATCH_BINDING_MATCH_CALL,
    TRAINER_REMATCH_BINDING_CHAIN,
    TRAINER_REMATCH_BINDING_VS_SEEKER = TRAINER_REMATCH_BINDING_CHAIN,
};

struct TrainerRematchChain
{
    u16 trainerIds[TRAINER_REMATCH_STAGE_COUNT];
};

struct TrainerRematchBinding
{
    u8 kind;
    u16 index;
};

struct TrainerRematchBinding TrainerRematch_GetBinding(u16 trainerId);
bool32 TrainerRematch_TryResolveStage(u16 trainerId, u8 stage, u16 *resolvedTrainerId);

#endif // GUARD_TRAINER_REMATCH_REGISTRY_H
