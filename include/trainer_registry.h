#ifndef GUARD_TRAINER_REGISTRY_H
#define GUARD_TRAINER_REGISTRY_H

#include "data.h"

struct ResolvedOrdinaryTrainer
{
    struct Trainer trainer;
    enum DifficultyLevel difficulty;
};

bool32 TryResolveOrdinaryTrainer(u16 trainerId, struct ResolvedOrdinaryTrainer *resolved);
bool32 TryResolveOrdinaryTrainerAtDifficulty(u16 trainerId, enum DifficultyLevel difficulty, struct ResolvedOrdinaryTrainer *resolved);
bool32 IsOrdinaryTrainerBattleNamespace(u32 battleTypeFlags);

const struct Trainer *GetPartnerTrainerStructFromId(u16 trainerId);
const struct Trainer *GetTrainerStructFromId(u16 trainerId);
enum DifficultyLevel GetResolvedTrainerDifficultyLevel(u16 trainerId);

enum TrainerClassID GetTrainerClassFromId(u16 trainerId);
const u8 *GetTrainerClassNameFromId(u16 trainerId);
const u8 *GetTrainerNameFromId(u16 trainerId);
enum TrainerPicID GetTrainerPicFromId(u16 trainerId);
struct StartingStatuses GetTrainerStartingStatusFromId(u16 trainerId);
enum TrainerBattleType GetTrainerBattleType(u16 trainerId);
u8 GetTrainerPartySizeFromId(u16 trainerId);
bool32 DoesTrainerHaveMugshot(u16 trainerId);
u8 GetTrainerMugshotColorFromId(u16 trainerId);
const u16 *GetTrainerItemsFromId(u16 trainerId);
const struct TrainerMon *GetTrainerPartyFromId(u16 trainerId);
u64 GetTrainerAIFlagsFromId(u16 trainerId);

#if TESTING
bool32 TrainerRegistry_TestResolve(
    const struct Trainer *trainers,
    u16 trainerCount,
    u16 trainerId,
    enum DifficultyLevel difficulty,
    struct ResolvedOrdinaryTrainer *resolved);
#endif

#endif // GUARD_TRAINER_REGISTRY_H
