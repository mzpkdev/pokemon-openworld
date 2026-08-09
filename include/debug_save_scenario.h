#ifndef GUARD_DEBUG_SAVE_SCENARIO_H
#define GUARD_DEBUG_SAVE_SCENARIO_H

#ifdef DEBUG

#define DEBUG_SAVE_SCENARIO_ABI_VERSION 2

enum DebugSaveScenarioStatus
{
    DEBUG_SAVE_SCENARIO_IDLE,
    DEBUG_SAVE_SCENARIO_PENDING,
    DEBUG_SAVE_SCENARIO_RUNNING,
    DEBUG_SAVE_SCENARIO_SUCCESS,
    DEBUG_SAVE_SCENARIO_ERROR,
};

enum DebugSaveScenarioError
{
    DEBUG_SAVE_SCENARIO_ERROR_NONE,
    DEBUG_SAVE_SCENARIO_ERROR_NOT_READY,
    DEBUG_SAVE_SCENARIO_ERROR_REQUEST,
    DEBUG_SAVE_SCENARIO_ERROR_PARTY,
    DEBUG_SAVE_SCENARIO_ERROR_BOX,
    DEBUG_SAVE_SCENARIO_ERROR_DAYCARE,
    DEBUG_SAVE_SCENARIO_ERROR_FACILITY,
    DEBUG_SAVE_SCENARIO_ERROR_TRADE,
    DEBUG_SAVE_SCENARIO_ERROR_REWARD,
    DEBUG_SAVE_SCENARIO_ERROR_CHECKPOINT,
    DEBUG_SAVE_SCENARIO_ERROR_TRAINER,
};

struct DebugSaveScenarioRequest
{
    u32 requestId;
    u16 partySpecies;
    u16 boxSpecies;
    u16 daycareSpecies1;
    u16 daycareSpecies2;
    u16 tradeSpecies;
    u16 rewardItem;
    u16 checkpointId;
    u8 level;
    u8 facilityId;
    u8 facilityLevelMode;
    u8 status;
    u16 trainerId;
    u32 rngSeed;
    u32 playerTrainerId;
    u16 abiVersion;
    u16 reserved;
};

struct DebugSaveScenarioResult
{
    u32 requestId;
    u16 error;
    u16 partyIndex;
    u16 boxIndex;
    u16 daycareEggSpecies;
    u16 tradedPartyIndex;
    u16 rewardItem;
    u16 checkpointId;
    u8 facilityId;
    u8 facilityChallengeStatus;
    u8 facilityPaused;
    u8 status;
    u16 trainerFlag;
    u32 rngSeed;
    u32 playerTrainerId;
    u16 abiVersion;
    u16 playerNameHash;
};

extern struct DebugSaveScenarioRequest gSaveScenarioRequest;
extern struct DebugSaveScenarioResult gSaveScenarioResult;

void DebugSaveScenario_Update(void);
void DebugSaveScenario_ApplyEncryptionKey(u32 encryptionKey);

#endif // DEBUG

#endif // GUARD_DEBUG_SAVE_SCENARIO_H
