#include "global.h"

#ifdef DEBUG

#include "battle.h"
#include "battle_setup.h"
#include "debug.h"
#include "debug_trainer_battle_scenario.h"
#include "event_object_movement.h"
#include "field_player_avatar.h"
#include "main.h"
#include "overworld.h"
#include "persistent_ids.h"
#include "pokemon.h"
#include "script.h"
#include "trainer_registry.h"
#include "trainer_rematch_registry.h"
#include "trainer_see.h"
#include "constants/battle.h"
#include "constants/opponents.h"

volatile struct DebugTrainerBattleScenarioRequest gTrainerBattleScenarioRequest;
volatile struct DebugTrainerBattleScenarioResult gTrainerBattleScenarioResult;

static bool8 sScenarioActive;
static bool8 sSawBattle;
static u32 sActiveRequestId;

STATIC_ASSERT(sizeof(struct DebugTrainerBattleScenarioRequest) == 12, DebugTrainerBattleScenarioRequestSize);
STATIC_ASSERT(offsetof(struct DebugTrainerBattleScenarioRequest, status) == 7, DebugTrainerBattleScenarioRequestStatusOffset);
STATIC_ASSERT(sizeof(struct DebugTrainerBattleScenarioResult) == 64, DebugTrainerBattleScenarioResultSize);
STATIC_ASSERT(offsetof(struct DebugTrainerBattleScenarioResult, status) == 63, DebugTrainerBattleScenarioResultStatusOffset);

static bool32 IsFieldReady(void)
{
    return gSaveBlock1Ptr != NULL
        && gSaveBlock2Ptr != NULL
        && gMain.callback1 == CB1_Overworld
        && gMain.callback2 == CB2_Overworld
        && gMain.state == 0
        && !gMain.inBattle
        && !gLinkTransferringData;
}

static void PublishTerminal(
    enum DebugTrainerBattleScenarioStatus status,
    enum DebugTrainerBattleScenarioPhase phase,
    enum DebugTrainerBattleScenarioError error)
{
    gTrainerBattleScenarioResult.error = error;
    gTrainerBattleScenarioResult.phase = phase;
    gTrainerBattleScenarioRequest.status = status;
    // This is the result commit byte. Keep it as the final published write.
    gTrainerBattleScenarioResult.status = status;
    sScenarioActive = FALSE;
}

static void InitResult(const struct DebugTrainerBattleScenarioRequest *request)
{
    u32 i;

    gTrainerBattleScenarioResult.requestId = request->requestId;
    gTrainerBattleScenarioResult.battleTypeFlags = 0;
    gTrainerBattleScenarioResult.endCallback = 0;
    gTrainerBattleScenarioResult.trainerId = request->trainerId;
    gTrainerBattleScenarioResult.opponentA = TRAINER_NONE;
    gTrainerBattleScenarioResult.opponentB = TRAINER_NONE;
    gTrainerBattleScenarioResult.defeatId = 0;
    gTrainerBattleScenarioResult.rematchIndex = 0;
    for (i = 0; i < PARTY_SIZE; i++)
    {
        gTrainerBattleScenarioResult.rematchStages[i] = TRAINER_REMATCH_STAGE_SKIP;
        gTrainerBattleScenarioResult.partySpecies[i] = SPECIES_NONE;
        gTrainerBattleScenarioResult.partyLevels[i] = 0;
    }
    gTrainerBattleScenarioResult.error = DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_NONE;
    gTrainerBattleScenarioResult.phase = DEBUG_TRAINER_BATTLE_SCENARIO_PHASE_VALIDATE;
    gTrainerBattleScenarioResult.partySize = 0;
    gTrainerBattleScenarioResult.difficulty = 0;
    gTrainerBattleScenarioResult.defeatStorage = 0;
    gTrainerBattleScenarioResult.defeatBit = 0;
    gTrainerBattleScenarioResult.rematchKind = TRAINER_REMATCH_BINDING_INVALID;
    gTrainerBattleScenarioResult.battleOutcome = 0;
    gTrainerBattleScenarioResult.isDebugBattle = gIsDebugBattle;
    gTrainerBattleScenarioResult.defeatedBefore = FALSE;
    gTrainerBattleScenarioResult.defeatedAfter = FALSE;
    gTrainerBattleScenarioResult.status = DEBUG_TRAINER_BATTLE_SCENARIO_RUNNING;
}

static enum DebugTrainerBattleScenarioError ValidateRequest(
    const struct DebugTrainerBattleScenarioRequest *request,
    struct ResolvedOrdinaryTrainer *resolved,
    struct TrainerDefeatBinding *defeatBinding,
    struct TrainerRematchBinding *rematchBinding)
{
    bool32 defeated;

    if (request->abiVersion != DEBUG_TRAINER_BATTLE_SCENARIO_ABI_VERSION
     || request->requestId == 0
     || request->reserved != 0
     || request->trainerId == TRAINER_NONE
     || request->trainerId >= TRAINERS_COUNT)
        return DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_REQUEST;
    if (!IsFieldReady() || CalculatePlayerPartyCount() == 0 || gIsDebugBattle)
        return DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_NOT_READY;
    if (!PersistentId_GetTrainerDefeated(request->trainerId, &defeated))
        return DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_PERSISTENCE_BINDING;
    if (defeated)
        return DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_ALREADY_DEFEATED;
    if (!TryResolveOrdinaryTrainer(request->trainerId, resolved))
        return DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_RESOLVE;
    if (!PersistentId_GetTrainerDefeatBinding(request->trainerId, defeatBinding))
        return DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_PERSISTENCE_BINDING;
    *rematchBinding = TrainerRematch_GetBinding(request->trainerId);
    if (rematchBinding->kind == TRAINER_REMATCH_BINDING_INVALID)
        return DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_REMATCH_BINDING;
    if (!BattleSetup_TryPreflightOrdinaryBattle(
            request->trainerId,
            TRAINER_NONE,
            TRAINER_NONE,
            BATTLE_TYPE_TRAINER))
        return DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_PREFLIGHT;
    return DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_NONE;
}

static void StartScenario(const struct DebugTrainerBattleScenarioRequest *request)
{
    struct ResolvedOrdinaryTrainer resolved;
    struct TrainerDefeatBinding defeatBinding;
    struct TrainerRematchBinding rematchBinding;
    enum DebugTrainerBattleScenarioError error;

    InitResult(request);
    gTrainerBattleScenarioRequest.status = DEBUG_TRAINER_BATTLE_SCENARIO_RUNNING;
    error = ValidateRequest(request, &resolved, &defeatBinding, &rematchBinding);
    if (error != DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_NONE)
    {
        PublishTerminal(
            DEBUG_TRAINER_BATTLE_SCENARIO_ERROR,
            DEBUG_TRAINER_BATTLE_SCENARIO_PHASE_VALIDATE,
            error);
        return;
    }

    gTrainerBattleScenarioResult.defeatId = defeatBinding.id;
    gTrainerBattleScenarioResult.defeatStorage = defeatBinding.storage;
    gTrainerBattleScenarioResult.defeatBit = defeatBinding.bit;
    gTrainerBattleScenarioResult.rematchKind = rematchBinding.kind;
    gTrainerBattleScenarioResult.rematchIndex = rematchBinding.index;
    if (rematchBinding.kind == TRAINER_REMATCH_BINDING_CHAIN)
    {
        u32 stage;

        for (stage = 0; stage < TRAINER_REMATCH_STAGE_COUNT; stage++)
        {
            u16 resolvedTrainerId;

            if (TrainerRematch_TryResolveStage(request->trainerId, stage, &resolvedTrainerId))
                gTrainerBattleScenarioResult.rematchStages[stage] = resolvedTrainerId;
        }
    }
    gTrainerBattleScenarioResult.difficulty = resolved.difficulty;
    gTrainerBattleScenarioResult.defeatedBefore = FALSE;
    gTrainerBattleScenarioResult.phase = DEBUG_TRAINER_BATTLE_SCENARIO_PHASE_START;

    InitTrainerBattleParameter();
    TRAINER_BATTLE_PARAM.opponentA = request->trainerId;
    TRAINER_BATTLE_PARAM.opponentB = TRAINER_NONE;
    gPartnerTrainerId = TRAINER_NONE;
    gNoOfApproachingTrainers = 0;

    sScenarioActive = TRUE;
    sSawBattle = FALSE;
    sActiveRequestId = request->requestId;
    LockPlayerFieldControls();
    FreezeObjectEvents();
    StopPlayerAvatar();
    BattleSetup_StartTrainerBattle();
}

static bool32 CaptureBattleConfiguration(void)
{
    u32 i;

    gTrainerBattleScenarioResult.battleTypeFlags = gBattleTypeFlags;
    gTrainerBattleScenarioResult.endCallback = (u32)gMain.savedCallback;
    gTrainerBattleScenarioResult.opponentA = TRAINER_BATTLE_PARAM.opponentA;
    gTrainerBattleScenarioResult.opponentB = TRAINER_BATTLE_PARAM.opponentB;
    gTrainerBattleScenarioResult.partySize = gPartiesCount[B_TRAINER_OPPONENT_A];
    gTrainerBattleScenarioResult.isDebugBattle = gIsDebugBattle;
    for (i = 0; i < gTrainerBattleScenarioResult.partySize && i < PARTY_SIZE; i++)
    {
        gTrainerBattleScenarioResult.partySpecies[i] = GetMonData(
            &gParties[B_TRAINER_OPPONENT_A][i], MON_DATA_SPECIES);
        gTrainerBattleScenarioResult.partyLevels[i] = GetMonData(
            &gParties[B_TRAINER_OPPONENT_A][i], MON_DATA_LEVEL);
    }
    gTrainerBattleScenarioResult.phase = DEBUG_TRAINER_BATTLE_SCENARIO_PHASE_BATTLE_READY;

    return gTrainerBattleScenarioResult.requestId == sActiveRequestId
        && gTrainerBattleScenarioResult.battleTypeFlags == BATTLE_TYPE_TRAINER
        && gTrainerBattleScenarioResult.opponentA == gTrainerBattleScenarioResult.trainerId
        && gTrainerBattleScenarioResult.opponentB == TRAINER_NONE
        && gTrainerBattleScenarioResult.partySize > 0
        && gTrainerBattleScenarioResult.partySize <= PARTY_SIZE
        && !gTrainerBattleScenarioResult.isDebugBattle;
}

static void FinishScenario(void)
{
    bool32 defeated;

    gTrainerBattleScenarioResult.phase = DEBUG_TRAINER_BATTLE_SCENARIO_PHASE_POST_BATTLE;
    gTrainerBattleScenarioResult.battleOutcome = gBattleOutcome;
    if (gBattleOutcome != B_OUTCOME_WON)
    {
        PublishTerminal(
            DEBUG_TRAINER_BATTLE_SCENARIO_ERROR,
            DEBUG_TRAINER_BATTLE_SCENARIO_PHASE_FIELD_READY,
            DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_OUTCOME);
        return;
    }
    if (!PersistentId_GetTrainerDefeated(gTrainerBattleScenarioResult.trainerId, &defeated)
     || !defeated)
    {
        PublishTerminal(
            DEBUG_TRAINER_BATTLE_SCENARIO_ERROR,
            DEBUG_TRAINER_BATTLE_SCENARIO_PHASE_FIELD_READY,
            DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_PERSISTENCE);
        return;
    }
    gTrainerBattleScenarioResult.defeatedAfter = TRUE;
    PublishTerminal(
        DEBUG_TRAINER_BATTLE_SCENARIO_SUCCESS,
        DEBUG_TRAINER_BATTLE_SCENARIO_PHASE_FIELD_READY,
        DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_NONE);
}

void DebugTrainerBattleScenario_Update(void)
{
    struct DebugTrainerBattleScenarioRequest request;

    if (!sScenarioActive)
    {
        if (gTrainerBattleScenarioRequest.status > DEBUG_TRAINER_BATTLE_SCENARIO_ERROR)
        {
            request.requestId = gTrainerBattleScenarioRequest.requestId;
            request.trainerId = gTrainerBattleScenarioRequest.trainerId;
            request.abiVersion = gTrainerBattleScenarioRequest.abiVersion;
            request.status = gTrainerBattleScenarioRequest.status;
            request.reserved = gTrainerBattleScenarioRequest.reserved;
            InitResult(&request);
            PublishTerminal(
                DEBUG_TRAINER_BATTLE_SCENARIO_ERROR,
                DEBUG_TRAINER_BATTLE_SCENARIO_PHASE_VALIDATE,
                DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_REQUEST);
            return;
        }
        if (gTrainerBattleScenarioRequest.status != DEBUG_TRAINER_BATTLE_SCENARIO_PENDING)
            return;
        request.requestId = gTrainerBattleScenarioRequest.requestId;
        request.trainerId = gTrainerBattleScenarioRequest.trainerId;
        request.abiVersion = gTrainerBattleScenarioRequest.abiVersion;
        request.status = gTrainerBattleScenarioRequest.status;
        request.reserved = gTrainerBattleScenarioRequest.reserved;
        StartScenario(&request);
        return;
    }

    if (gMain.inBattle && !sSawBattle)
    {
        sSawBattle = TRUE;
        if (!CaptureBattleConfiguration())
            PublishTerminal(
                DEBUG_TRAINER_BATTLE_SCENARIO_ERROR,
                DEBUG_TRAINER_BATTLE_SCENARIO_PHASE_BATTLE_READY,
                DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_CONFIGURATION);
        return;
    }

    if (sSawBattle && IsFieldReady())
        FinishScenario();
}

#endif // DEBUG
