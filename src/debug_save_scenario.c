#include "global.h"

#ifdef DEBUG

#include "battle_tower.h"
#include "battle_setup.h"
#include "apprentice.h"
#include "clock.h"
#include "daycare.h"
#include "debug_save_scenario.h"
#include "dewford_trend.h"
#include "event_data.h"
#include "event_object_movement.h"
#include "field_player_avatar.h"
#include "heal_location.h"
#include "item.h"
#include "link.h"
#include "lilycove_lady.h"
#include "lottery_corner.h"
#include "main.h"
#include "new_game.h"
#include "overworld.h"
#include "pokemon.h"
#include "pokemon_storage_system.h"
#include "random.h"
#include "script_pokemon_util.h"
#include "string_util.h"
#include "trade.h"
#include "constants/battle_frontier.h"
#include "constants/characters.h"
#include "constants/flags.h"
#include "constants/items.h"
#include "constants/opponents.h"
#include "constants/pokemon.h"
#include "constants/species.h"

struct DebugSaveScenarioRequest gSaveScenarioRequest;
struct DebugSaveScenarioResult gSaveScenarioResult;

static const u8 sDeterministicPlayerName[] = _("E2E");

STATIC_ASSERT(sizeof(struct DebugSaveScenarioRequest) == 36, DebugSaveScenarioRequestSize);
STATIC_ASSERT(offsetof(struct DebugSaveScenarioRequest, status) == 21, DebugSaveScenarioRequestStatusOffset);
STATIC_ASSERT(offsetof(struct DebugSaveScenarioRequest, rngSeed) == 24, DebugSaveScenarioRequestSeedOffset);
STATIC_ASSERT(sizeof(struct DebugSaveScenarioResult) == 36, DebugSaveScenarioResultSize);
STATIC_ASSERT(offsetof(struct DebugSaveScenarioResult, status) == 21, DebugSaveScenarioResultStatusOffset);
STATIC_ASSERT(offsetof(struct DebugSaveScenarioResult, rngSeed) == 24, DebugSaveScenarioResultSeedOffset);

static bool32 IsFieldReady(void);

static u16 HashPlayerName(const u8 *name)
{
    u16 hash = 0x811C;

    while (*name != EOS)
        hash = (hash ^ *name++) * 257;
    return hash;
}

static void InitDeterministicIdentity(const struct DebugSaveScenarioRequest *request)
{
    // These are the same services used by startup/new-game initialization.
    SeedRng(request->rngSeed);
    SeedRng2(request->rngSeed ^ 0x9E3779B9);
    gMain.vblankCounter2 = request->rngSeed;
    SetTrainerId(request->playerTrainerId, gSaveBlock2Ptr->playerTrainerId);
    memset(gSaveBlock2Ptr->playerName, 0, sizeof(gSaveBlock2Ptr->playerName));
    StringCopy_PlayerName(gSaveBlock2Ptr->playerName, sDeterministicPlayerName);
    // Quickstart uses the same direct new-game selection field.
    gSaveBlock2Ptr->playerGender = MALE;
    // The avatar was spawned before the fixture request, so keep its runtime
    // identity in sync with the deterministic save identity.  SaveObjectEvents
    // persists this live graphics ID through its normal serialization path.
    gPlayerAvatar.gender = MALE;
    ObjectEventSetGraphicsId(&gObjectEvents[gPlayerAvatar.objectEventId],
                             GetPlayerAvatarGraphicsIdByCurrentState());
}

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

static bool32 IsValidSpecies(enum Species species)
{
    return species != SPECIES_NONE
        && species < NUM_SPECIES
        && IsSpeciesEnabled(species);
}

static bool32 HasEmptyPcSlot(void)
{
    u32 boxId, boxPosition;

    for (boxId = 0; boxId < TOTAL_BOXES_COUNT; boxId++)
    {
        for (boxPosition = 0; boxPosition < IN_BOX_COUNT; boxPosition++)
        {
            if (GetBoxMonData(GetBoxedMonPtr(boxId, boxPosition), MON_DATA_SPECIES) == SPECIES_NONE)
                return TRUE;
        }
    }
    return FALSE;
}

static void Publish(enum DebugSaveScenarioStatus status, enum DebugSaveScenarioError error)
{
    gSaveScenarioResult.error = error;
    gSaveScenarioRequest.status = status;
    gSaveScenarioResult.status = status;
}

static enum DebugSaveScenarioError ValidateRequest(const struct DebugSaveScenarioRequest *request)
{
    if (!IsFieldReady())
        return DEBUG_SAVE_SCENARIO_ERROR_NOT_READY;
    if (request->abiVersion != DEBUG_SAVE_SCENARIO_ABI_VERSION
     || request->reserved != 0
     || request->requestId == 0
     || request->rngSeed == 0
     || request->playerTrainerId == 0
     || !IsValidSpecies(request->partySpecies)
     || !IsValidSpecies(request->boxSpecies)
     || !IsValidSpecies(request->daycareSpecies1)
     || !IsValidSpecies(request->daycareSpecies2)
     || !IsValidSpecies(request->tradeSpecies)
     || request->level == 0
     || request->level > MAX_LEVEL)
        return DEBUG_SAVE_SCENARIO_ERROR_REQUEST;
    if (CalculatePlayerPartyCount() > PARTY_SIZE - 2)
        return DEBUG_SAVE_SCENARIO_ERROR_PARTY;
    if (!HasEmptyPcSlot())
        return DEBUG_SAVE_SCENARIO_ERROR_BOX;
    if (CountPokemonInDaycare(&gSaveBlock1Ptr->daycare) != 0
     || FlagGet(FLAG_PENDING_DAYCARE_EGG))
        return DEBUG_SAVE_SCENARIO_ERROR_DAYCARE;
    if (request->facilityId != FRONTIER_FACILITY_TOWER
     || request->facilityLevelMode >= FRONTIER_LVL_MODE_COUNT
     || gSaveBlock2Ptr->frontier.challengeStatus != 0)
        return DEBUG_SAVE_SCENARIO_ERROR_FACILITY;
    if (Debug_GetInGameTradeRequestedSpecies(request->tradeSpecies) == SPECIES_NONE)
        return DEBUG_SAVE_SCENARIO_ERROR_TRADE;
    if (request->rewardItem == ITEM_NONE
     || request->rewardItem >= ITEMS_COUNT
     || !CheckBagHasSpace(request->rewardItem, 1))
        return DEBUG_SAVE_SCENARIO_ERROR_REWARD;
    if (request->checkpointId > 0xFF || GetHealLocation(request->checkpointId) == NULL)
        return DEBUG_SAVE_SCENARIO_ERROR_CHECKPOINT;
    if (request->trainerId == 0 || request->trainerId >= TRAINERS_COUNT
     || HasTrainerBeenFought(request->trainerId))
        return DEBUG_SAVE_SCENARIO_ERROR_TRAINER;
    return DEBUG_SAVE_SCENARIO_ERROR_NONE;
}

void DebugSaveScenario_Update(void)
{
    struct DebugSaveScenarioRequest request;
    struct Pokemon boxMon;
    enum DebugSaveScenarioError error;
    enum Species requestedTradeSpecies;
    u16 rewardCount;
    u8 partyIndex;
    u8 tradeIndex;

    if (gSaveScenarioRequest.status != DEBUG_SAVE_SCENARIO_PENDING)
        return;

    request = gSaveScenarioRequest;
    gSaveScenarioResult = (struct DebugSaveScenarioResult)
    {
        .requestId = request.requestId,
        .partyIndex = 0xFFFF,
        .boxIndex = 0xFFFF,
        .tradedPartyIndex = 0xFFFF,
        .facilityId = request.facilityId,
        .rngSeed = request.rngSeed,
        .playerTrainerId = request.playerTrainerId,
        .abiVersion = request.abiVersion,
        .status = DEBUG_SAVE_SCENARIO_RUNNING,
    };
    gSaveScenarioRequest.status = DEBUG_SAVE_SCENARIO_RUNNING;

    error = ValidateRequest(&request);
    if (error != DEBUG_SAVE_SCENARIO_ERROR_NONE)
    {
        Publish(DEBUG_SAVE_SCENARIO_ERROR, error);
        return;
    }

    InitDeterministicIdentity(&request);
    if (GetTrainerId(gSaveBlock2Ptr->playerTrainerId) != request.playerTrainerId)
    {
        Publish(DEBUG_SAVE_SCENARIO_ERROR, DEBUG_SAVE_SCENARIO_ERROR_REQUEST);
        return;
    }
    gSaveScenarioResult.playerNameHash = HashPlayerName(gSaveBlock2Ptr->playerName);
    // Replay the RNG/identity-dependent portion of NewGameInitData now that
    // its canonical seed and player identity are fixed.
    InitDewfordTrend();
    ResetLotteryCorner();
    UpdateDailySeed();
    Debug_InitLilycoveLadyDeterministically();
    ResetAllApprenticeData();
    {
        rng_value_t saveRng = LocalRandomSeed(request.rngSeed);
        LocalRandom32(&saveRng); // canonical save-block pointer-offset draw
        DebugSaveScenario_ApplyEncryptionKey(LocalRandom32(&saveRng));
    }

    partyIndex = CalculatePlayerPartyCount();
    if (ScriptGiveMon(request.partySpecies, request.level, ITEM_NONE) != MON_GIVEN_TO_PARTY
     || GetMonData(&gParties[B_TRAINER_PLAYER][partyIndex], MON_DATA_SPECIES) != request.partySpecies)
    {
        Publish(DEBUG_SAVE_SCENARIO_ERROR, DEBUG_SAVE_SCENARIO_ERROR_PARTY);
        return;
    }
    gSaveScenarioResult.partyIndex = partyIndex;

    CreateRandomMon(&boxMon, request.boxSpecies, request.level);
    if (CopyMonToPC(&boxMon) != MON_GIVEN_TO_PC)
    {
        Publish(DEBUG_SAVE_SCENARIO_ERROR, DEBUG_SAVE_SCENARIO_ERROR_BOX);
        return;
    }
    gSaveScenarioResult.boxIndex = gSpecialVar_MonBoxId * IN_BOX_COUNT + gSpecialVar_MonBoxPos;
    if (GetBoxMonData(GetBoxedMonPtr(gSpecialVar_MonBoxId, gSpecialVar_MonBoxPos), MON_DATA_SPECIES)
        != request.boxSpecies)
    {
        Publish(DEBUG_SAVE_SCENARIO_ERROR, DEBUG_SAVE_SCENARIO_ERROR_BOX);
        return;
    }

    partyIndex = CalculatePlayerPartyCount();
    if (ScriptGiveMon(request.daycareSpecies1, request.level, ITEM_NONE) != MON_GIVEN_TO_PARTY)
    {
        Publish(DEBUG_SAVE_SCENARIO_ERROR, DEBUG_SAVE_SCENARIO_ERROR_DAYCARE);
        return;
    }
    StorePokemonInDaycare(&gParties[B_TRAINER_PLAYER][partyIndex], &gSaveBlock1Ptr->daycare.mons[0]);
    partyIndex = CalculatePlayerPartyCount();
    if (ScriptGiveMon(request.daycareSpecies2, request.level, ITEM_NONE) != MON_GIVEN_TO_PARTY)
    {
        Publish(DEBUG_SAVE_SCENARIO_ERROR, DEBUG_SAVE_SCENARIO_ERROR_DAYCARE);
        return;
    }
    StorePokemonInDaycare(&gParties[B_TRAINER_PLAYER][partyIndex], &gSaveBlock1Ptr->daycare.mons[1]);
    if (GetDaycareCompatibilityScore(&gSaveBlock1Ptr->daycare) == PARENTS_INCOMPATIBLE)
    {
        Publish(DEBUG_SAVE_SCENARIO_ERROR, DEBUG_SAVE_SCENARIO_ERROR_DAYCARE);
        return;
    }
    // The normal egg path uses this field as its local entropy seed.
    gMain.vblankCounter2 = request.rngSeed;
    TriggerPendingDaycareEgg();
    gSaveScenarioResult.daycareEggSpecies = Debug_GetPendingDaycareEggSpecies();
    if (!FlagGet(FLAG_PENDING_DAYCARE_EGG)
     || gSaveScenarioResult.daycareEggSpecies == SPECIES_NONE)
    {
        Publish(DEBUG_SAVE_SCENARIO_ERROR, DEBUG_SAVE_SCENARIO_ERROR_DAYCARE);
        return;
    }

    requestedTradeSpecies = Debug_GetInGameTradeRequestedSpecies(request.tradeSpecies);
    tradeIndex = CalculatePlayerPartyCount();
    if (ScriptGiveMon(requestedTradeSpecies, request.level, ITEM_NONE) != MON_GIVEN_TO_PARTY
     || !Debug_ExecuteInGameTrade(tradeIndex, request.tradeSpecies)
     || GetMonData(&gParties[B_TRAINER_PLAYER][tradeIndex], MON_DATA_MET_LOCATION) != METLOC_IN_GAME_TRADE)
    {
        Publish(DEBUG_SAVE_SCENARIO_ERROR, DEBUG_SAVE_SCENARIO_ERROR_TRADE);
        return;
    }
    gSaveScenarioResult.tradedPartyIndex = tradeIndex;

    rewardCount = CountTotalItemQuantityInBag(request.rewardItem);
    if (!AddBagItem(request.rewardItem, 1)
     || CountTotalItemQuantityInBag(request.rewardItem) != rewardCount + 1)
    {
        Publish(DEBUG_SAVE_SCENARIO_ERROR, DEBUG_SAVE_SCENARIO_ERROR_REWARD);
        return;
    }
    gSaveScenarioResult.rewardItem = request.rewardItem;

    SetLastHealLocationWarp(request.checkpointId);
    if (GetHealLocationIndexByWarpData(&gSaveBlock1Ptr->lastHealLocation) != request.checkpointId)
    {
        Publish(DEBUG_SAVE_SCENARIO_ERROR, DEBUG_SAVE_SCENARIO_ERROR_CHECKPOINT);
        return;
    }
    gSaveScenarioResult.checkpointId = request.checkpointId;

    SetTrainerFlag(request.trainerId);
    if (!HasTrainerBeenFought(request.trainerId))
    {
        Publish(DEBUG_SAVE_SCENARIO_ERROR, DEBUG_SAVE_SCENARIO_ERROR_TRAINER);
        return;
    }
    gSaveScenarioResult.trainerFlag = request.trainerId;

    if (!Debug_StartAndPauseTowerChallenge(request.facilityLevelMode))
    {
        Publish(DEBUG_SAVE_SCENARIO_ERROR, DEBUG_SAVE_SCENARIO_ERROR_FACILITY);
        return;
    }
    gSaveScenarioResult.facilityChallengeStatus = gSaveBlock2Ptr->frontier.challengeStatus;
    gSaveScenarioResult.facilityPaused = gSaveBlock2Ptr->frontier.challengePaused;

    Publish(DEBUG_SAVE_SCENARIO_SUCCESS, DEBUG_SAVE_SCENARIO_ERROR_NONE);
}

#endif // DEBUG
