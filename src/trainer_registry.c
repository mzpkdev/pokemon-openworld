#include "global.h"
#include "data.h"
#include "persistent_ids.h"
#include "strings.h"
#include "trainer_registry.h"

extern const struct Trainer gTrainers[DIFFICULTY_COUNT][TRAINERS_COUNT];

static bool32 HasPublishedOrdinaryIdentity(u16 trainerId, u16 trainerCount)
{
    struct TrainerDefeatBinding binding;

    return trainerId != TRAINER_NONE
        && trainerId < trainerCount
        && trainerId < TRAINERS_COUNT
        && PersistentId_GetTrainerDefeatBinding(trainerId, &binding);
}

static const struct Trainer *GetTrainerAtDifficulty(
    const struct Trainer *trainers,
    u16 trainerCount,
    u16 trainerId,
    enum DifficultyLevel requestedDifficulty,
    enum DifficultyLevel *resolvedDifficulty)
{
    const struct Trainer *trainer;

    if (requestedDifficulty < DIFFICULTY_MIN || requestedDifficulty >= DIFFICULTY_COUNT)
        return NULL;

    trainer = &trainers[requestedDifficulty * trainerCount + trainerId];
    if (requestedDifficulty != DIFFICULTY_NORMAL
     && (!trainer->isRegistered || (trainer->party == NULL && trainer->overrideTrainer == TRAINER_NONE)))
    {
        requestedDifficulty = DIFFICULTY_NORMAL;
        trainer = &trainers[DIFFICULTY_NORMAL * trainerCount + trainerId];
    }

    if (!trainer->isRegistered)
        return NULL;

    *resolvedDifficulty = requestedDifficulty;
    return trainer;
}

static bool32 ResolveCandidate(
    const struct Trainer *trainers,
    u16 trainerCount,
    u16 trainerId,
    enum DifficultyLevel difficulty,
    struct ResolvedOrdinaryTrainer *candidate)
{
    const struct Trainer *source;
    const struct Trainer *partySource;
    enum DifficultyLevel ignoredDifficulty;
    u16 overrideId;
    u16 traversed = 0;

    source = GetTrainerAtDifficulty(trainers, trainerCount, trainerId, difficulty, &candidate->difficulty);
    if (source == NULL)
        return FALSE;

    candidate->trainer = *source;
    partySource = source;
    overrideId = source->overrideTrainer;
    while (overrideId != TRAINER_NONE)
    {
        if (++traversed >= trainerCount || !HasPublishedOrdinaryIdentity(overrideId, trainerCount))
            return FALSE;
        partySource = GetTrainerAtDifficulty(trainers, trainerCount, overrideId, difficulty, &ignoredDifficulty);
        if (partySource == NULL)
            return FALSE;
        overrideId = partySource->overrideTrainer;
    }

    if (source->overrideTrainer != TRAINER_NONE)
    {
        candidate->trainer.party = partySource->party;
        candidate->trainer.poolSize = partySource->poolSize;
        if (candidate->trainer.partySize == 0)
            candidate->trainer.partySize = partySource->partySize;
    }

    if (candidate->trainer.party == NULL
     || candidate->trainer.partySize == 0
     || candidate->trainer.partySize > PARTY_SIZE)
    {
        return FALSE;
    }

    return TRUE;
}

static bool32 ResolveFromTable(
    const struct Trainer *trainers,
    u16 trainerCount,
    u16 trainerId,
    enum DifficultyLevel difficulty,
    struct ResolvedOrdinaryTrainer *resolved)
{
    struct ResolvedOrdinaryTrainer normal;
    struct ResolvedOrdinaryTrainer candidate;
    const struct Trainer *requested;

    if (trainers == NULL
     || resolved == NULL
     || difficulty < DIFFICULTY_MIN
     || difficulty >= DIFFICULTY_COUNT
     || !HasPublishedOrdinaryIdentity(trainerId, trainerCount)
     || !ResolveCandidate(trainers, trainerCount, trainerId, DIFFICULTY_NORMAL, &normal))
    {
        return FALSE;
    }

    if (difficulty == DIFFICULTY_NORMAL)
    {
        *resolved = normal;
        return TRUE;
    }

    requested = &trainers[difficulty * trainerCount + trainerId];
    if (!requested->isRegistered || (requested->party == NULL && requested->overrideTrainer == TRAINER_NONE))
    {
        *resolved = normal;
        return TRUE;
    }
    if (!ResolveCandidate(trainers, trainerCount, trainerId, difficulty, &candidate))
        return FALSE;

    *resolved = candidate;
    return TRUE;
}

bool32 TryResolveOrdinaryTrainerAtDifficulty(
    u16 trainerId,
    enum DifficultyLevel difficulty,
    struct ResolvedOrdinaryTrainer *resolved)
{
    return ResolveFromTable(&gTrainers[0][0], TRAINERS_COUNT, trainerId, difficulty, resolved);
}

bool32 TryResolveOrdinaryTrainer(u16 trainerId, struct ResolvedOrdinaryTrainer *resolved)
{
    return TryResolveOrdinaryTrainerAtDifficulty(trainerId, GetCurrentDifficultyLevel(), resolved);
}

bool32 IsOrdinaryTrainerBattleNamespace(u32 battleTypeFlags)
{
    if (!(battleTypeFlags & BATTLE_TYPE_TRAINER))
        return FALSE;

    return !(battleTypeFlags & (BATTLE_TYPE_LINK
                              | BATTLE_TYPE_FRONTIER
                              | BATTLE_TYPE_TRAINER_HILL
                              | BATTLE_TYPE_SECRET_BASE
                              | BATTLE_TYPE_EREADER_TRAINER));
}

const struct Trainer *GetPartnerTrainerStructFromId(u16 trainerId)
{
    enum DifficultyLevel difficulty;
    u16 partnerId;

    if (!IsPartnerTrainerId(trainerId))
        return NULL;
    partnerId = trainerId - TRAINER_PARTNER(PARTNER_NONE);
    if (partnerId >= PARTNER_COUNT)
        return NULL;
    difficulty = GetCurrentDifficultyLevel();
    if (difficulty < DIFFICULTY_MIN || difficulty >= DIFFICULTY_COUNT)
        return NULL;
    difficulty = GetBattlePartnerDifficultyLevel(trainerId);
    return &gBattlePartners[difficulty][partnerId];
}

const struct Trainer *GetTrainerStructFromId(u16 trainerId)
{
    struct ResolvedOrdinaryTrainer resolved;

    if (gIsDebugBattle)
        return GetDebugAiTrainer();
    if (IsPartnerTrainerId(trainerId))
        return GetPartnerTrainerStructFromId(trainerId);
    if (!TryResolveOrdinaryTrainer(trainerId, &resolved))
        return NULL;

    return &gTrainers[resolved.difficulty][trainerId];
}

enum DifficultyLevel GetResolvedTrainerDifficultyLevel(u16 trainerId)
{
    struct ResolvedOrdinaryTrainer resolved;

    if (!TryResolveOrdinaryTrainer(trainerId, &resolved))
        return DIFFICULTY_NORMAL;
    return resolved.difficulty;
}

enum TrainerClassID GetTrainerClassFromId(u16 trainerId)
{
    const struct Trainer *trainer = GetTrainerStructFromId(trainerId);

    return trainer == NULL ? TRAINER_CLASS_PKMN_TRAINER_1 : trainer->trainerClass;
}

const u8 *GetTrainerClassNameFromId(u16 trainerId)
{
    const struct Trainer *trainer = GetTrainerStructFromId(trainerId);

    if (trainer == NULL || trainer->trainerClass >= TRAINER_CLASS_COUNT)
        return gText_EmptyString2;
    return gTrainerClasses[trainer->trainerClass].name;
}

const u8 *GetTrainerNameFromId(u16 trainerId)
{
    const struct Trainer *trainer = GetTrainerStructFromId(trainerId);

    return trainer == NULL ? gText_EmptyString2 : trainer->trainerName;
}

enum TrainerPicID GetTrainerPicFromId(u16 trainerId)
{
    const struct Trainer *trainer = GetTrainerStructFromId(trainerId);

    return trainer == NULL ? TRAINER_PIC_NONE : trainer->trainerPic;
}

struct StartingStatuses GetTrainerStartingStatusFromId(u16 trainerId)
{
    const struct Trainer *trainer = GetTrainerStructFromId(trainerId);

    if (trainer == NULL)
        return (struct StartingStatuses){0};
    return trainer->startingStatus;
}

enum TrainerBattleType GetTrainerBattleType(u16 trainerId)
{
    const struct Trainer *trainer = GetTrainerStructFromId(trainerId);

    return trainer == NULL ? TRAINER_BATTLE_TYPE_SINGLES : trainer->battleType;
}

u8 GetTrainerPartySizeFromId(u16 trainerId)
{
    struct ResolvedOrdinaryTrainer resolved;
    const struct Trainer *partner;

    if (IsPartnerTrainerId(trainerId))
    {
        partner = GetPartnerTrainerStructFromId(trainerId);
        return partner == NULL ? 0 : partner->partySize;
    }
    if (!TryResolveOrdinaryTrainer(trainerId, &resolved))
        return 0;
    return resolved.trainer.partySize;
}

bool32 DoesTrainerHaveMugshot(u16 trainerId)
{
    return GetTrainerMugshotColorFromId(trainerId) != 0;
}

u8 GetTrainerMugshotColorFromId(u16 trainerId)
{
    const struct Trainer *trainer = GetTrainerStructFromId(trainerId);

    return trainer == NULL ? 0 : trainer->mugshotColor;
}

const u16 *GetTrainerItemsFromId(u16 trainerId)
{
    const struct Trainer *trainer = GetTrainerStructFromId(trainerId);

    return trainer == NULL ? NULL : trainer->items;
}

const struct TrainerMon *GetTrainerPartyFromId(u16 trainerId)
{
    struct ResolvedOrdinaryTrainer resolved;
    const struct Trainer *partner;

    if (IsPartnerTrainerId(trainerId))
    {
        partner = GetPartnerTrainerStructFromId(trainerId);
        return partner == NULL ? NULL : partner->party;
    }
    if (!TryResolveOrdinaryTrainer(trainerId, &resolved))
        return NULL;
    return resolved.trainer.party;
}

u64 GetTrainerAIFlagsFromId(u16 trainerId)
{
    const struct Trainer *trainer = GetTrainerStructFromId(trainerId);

    return trainer == NULL ? 0 : trainer->aiFlags;
}

#if TESTING
bool32 TrainerRegistry_TestResolve(
    const struct Trainer *trainers,
    u16 trainerCount,
    u16 trainerId,
    enum DifficultyLevel difficulty,
    struct ResolvedOrdinaryTrainer *resolved)
{
    return ResolveFromTable(trainers, trainerCount, trainerId, difficulty, resolved);
}
#endif
