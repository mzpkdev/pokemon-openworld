#ifndef GUARD_DEBUG_TRAINER_BATTLE_SCENARIO_H
#define GUARD_DEBUG_TRAINER_BATTLE_SCENARIO_H

#ifdef DEBUG

#define DEBUG_TRAINER_BATTLE_SCENARIO_ABI_VERSION 1

enum DebugTrainerBattleScenarioStatus
{
    DEBUG_TRAINER_BATTLE_SCENARIO_IDLE,
    DEBUG_TRAINER_BATTLE_SCENARIO_PENDING,
    DEBUG_TRAINER_BATTLE_SCENARIO_RUNNING,
    DEBUG_TRAINER_BATTLE_SCENARIO_SUCCESS,
    DEBUG_TRAINER_BATTLE_SCENARIO_ERROR,
};

enum DebugTrainerBattleScenarioPhase
{
    DEBUG_TRAINER_BATTLE_SCENARIO_PHASE_NONE,
    DEBUG_TRAINER_BATTLE_SCENARIO_PHASE_VALIDATE,
    DEBUG_TRAINER_BATTLE_SCENARIO_PHASE_START,
    DEBUG_TRAINER_BATTLE_SCENARIO_PHASE_BATTLE_READY,
    DEBUG_TRAINER_BATTLE_SCENARIO_PHASE_POST_BATTLE,
    DEBUG_TRAINER_BATTLE_SCENARIO_PHASE_FIELD_READY,
};

enum DebugTrainerBattleScenarioError
{
    DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_NONE,
    DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_NOT_READY,
    DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_REQUEST,
    DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_ALREADY_DEFEATED,
    DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_RESOLVE,
    DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_PERSISTENCE_BINDING,
    DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_REMATCH_BINDING,
    DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_PREFLIGHT,
    DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_CONFIGURATION,
    DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_OUTCOME,
    DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_PERSISTENCE,
};

struct DebugTrainerBattleScenarioRequest
{
    u32 requestId;
    u16 trainerId;
    u8 abiVersion;
    u8 status;
    u32 reserved;
};

struct DebugTrainerBattleScenarioResult
{
    u32 requestId;
    u32 battleTypeFlags;
    u32 endCallback;
    u16 trainerId;
    u16 opponentA;
    u16 opponentB;
    u16 defeatId;
    u16 rematchIndex;
    u16 rematchStages[PARTY_SIZE];
    u16 partySpecies[PARTY_SIZE];
    u8 partyLevels[PARTY_SIZE];
    u8 error;
    u8 phase;
    u8 partySize;
    u8 difficulty;
    u8 defeatStorage;
    u8 defeatBit;
    u8 rematchKind;
    u8 battleOutcome;
    u8 isDebugBattle;
    u8 defeatedBefore;
    u8 defeatedAfter;
    u8 status;
};

extern volatile struct DebugTrainerBattleScenarioRequest gTrainerBattleScenarioRequest;
extern volatile struct DebugTrainerBattleScenarioResult gTrainerBattleScenarioResult;

void DebugTrainerBattleScenario_Update(void);

#endif // DEBUG

#endif // GUARD_DEBUG_TRAINER_BATTLE_SCENARIO_H
