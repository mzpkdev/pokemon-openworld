#include "global.h"
#include "battle.h"
#include "battle_setup.h"
#include "event_data.h"
#include "main.h"
#include "overworld.h"
#include "persistent_ids.h"
#include "script.h"
#include "task.h"
#include "trainer_see.h"
#include "constants/battle.h"
#include "constants/battle_setup.h"
#include "constants/battle_pyramid.h"
#include "constants/game_stat.h"
#include "constants/opponents.h"
#include "test/test.h"

#define TRAINER_RED_TEST  1
#define TRAINER_LEAF_TEST 2

bool8 TrainerSee_TestTrySetUpTwoTrainersBattle(const u8 *trainerScriptA, const u8 *trainerScriptB);
u8 TrainerSee_TestPreflightSightTrainerBattle(const u8 *trainerBattlePtr, bool8 inTrainerHill, u8 pyramidLocation);
bool32 BattleUtil_TestAreMultiPartiesFullTeamsForBattle(u32 battleTypeFlags, u16 opponentA, u16 opponentB);

struct LaunchSnapshot
{
    TrainerBattleParameter parameters;
    struct Pokemon parties[MAX_BATTLE_TRAINERS][PARTY_SIZE];
    MainCallback savedCallback;
    u32 battleTypeFlags;
    u32 totalBattles;
    u32 trainerBattles;
    u16 rematchStepCounter;
    u8 trainerRematches[MAX_REMATCH_ENTRIES];
    u32 rematchPrefixCanary;
    struct ObjectEvent rematchSuffixCanary;
    bool8 fieldControlsLocked;
    u8 activeTasks;
    u8 approachingTrainers;
    bool32 calvinDefeated;
    bool32 samuelDefeated;
};

static u8 CountActiveTasks(void)
{
    u8 count = 0;

    for (u32 i = 0; i < NUM_TASKS; i++)
        count += gTasks[i].isActive;
    return count;
}

static void TakeLaunchSnapshot(struct LaunchSnapshot *snapshot)
{
    snapshot->parameters = gTrainerBattleParameter;
    memcpy(snapshot->parties, gParties, sizeof(snapshot->parties));
    snapshot->savedCallback = gMain.savedCallback;
    snapshot->battleTypeFlags = gBattleTypeFlags;
    snapshot->totalBattles = GetGameStat(GAME_STAT_TOTAL_BATTLES);
    snapshot->trainerBattles = GetGameStat(GAME_STAT_TRAINER_BATTLES);
    snapshot->rematchStepCounter = gSaveBlock1Ptr->trainerRematchStepCounter;
    memcpy(snapshot->trainerRematches, gSaveBlock1Ptr->trainerRematches, sizeof(snapshot->trainerRematches));
    snapshot->rematchPrefixCanary = gSaveBlock1Ptr->dailySeed;
    snapshot->rematchSuffixCanary = gSaveBlock1Ptr->objectEvents[0];
    snapshot->fieldControlsLocked = ArePlayerFieldControlsLocked();
    snapshot->activeTasks = CountActiveTasks();
    snapshot->approachingTrainers = gNoOfApproachingTrainers;
    EXPECT(PersistentId_GetTrainerDefeated(TRAINER_FRLG_YOUNGSTER_CALVIN, &snapshot->calvinDefeated));
    EXPECT(PersistentId_GetTrainerDefeated(TRAINER_YOUNGSTER_SAMUEL_JOHTO, &snapshot->samuelDefeated));
}

static void ExpectLaunchSnapshot(const struct LaunchSnapshot *snapshot)
{
    bool32 defeated;

    EXPECT_EQ(memcmp(&gTrainerBattleParameter, &snapshot->parameters, sizeof(snapshot->parameters)), 0);
    EXPECT_EQ(memcmp(gParties, snapshot->parties, sizeof(snapshot->parties)), 0);
    EXPECT_EQ(gMain.savedCallback, snapshot->savedCallback);
    EXPECT_EQ(gBattleTypeFlags, snapshot->battleTypeFlags);
    EXPECT_EQ(GetGameStat(GAME_STAT_TOTAL_BATTLES), snapshot->totalBattles);
    EXPECT_EQ(GetGameStat(GAME_STAT_TRAINER_BATTLES), snapshot->trainerBattles);
    EXPECT_EQ(gSaveBlock1Ptr->trainerRematchStepCounter, snapshot->rematchStepCounter);
    EXPECT_EQ(memcmp(gSaveBlock1Ptr->trainerRematches, snapshot->trainerRematches, sizeof(snapshot->trainerRematches)), 0);
    EXPECT_EQ(gSaveBlock1Ptr->dailySeed, snapshot->rematchPrefixCanary);
    EXPECT_EQ(memcmp(&gSaveBlock1Ptr->objectEvents[0], &snapshot->rematchSuffixCanary, sizeof(snapshot->rematchSuffixCanary)), 0);
    EXPECT_EQ(ArePlayerFieldControlsLocked(), snapshot->fieldControlsLocked);
    EXPECT_EQ(CountActiveTasks(), snapshot->activeTasks);
    EXPECT_EQ(gNoOfApproachingTrainers, snapshot->approachingTrainers);
    EXPECT(PersistentId_GetTrainerDefeated(TRAINER_FRLG_YOUNGSTER_CALVIN, &defeated));
    EXPECT_EQ(defeated, snapshot->calvinDefeated);
    EXPECT(PersistentId_GetTrainerDefeated(TRAINER_YOUNGSTER_SAMUEL_JOHTO, &defeated));
    EXPECT_EQ(defeated, snapshot->samuelDefeated);
}

TEST("Ordinary battle preflight rejects invalid opponents and illegal topology")
{
    const u32 single = BATTLE_TYPE_TRAINER;
    const u32 two = BATTLE_TYPE_TRAINER | BATTLE_TYPE_DOUBLE | BATTLE_TYPE_TWO_OPPONENTS;

    EXPECT(!BattleSetup_TryPreflightOrdinaryBattle(TRAINER_NONE, TRAINER_NONE, TRAINER_NONE, single));
    EXPECT(!BattleSetup_TryPreflightOrdinaryBattle(TRAINERS_COUNT, TRAINER_NONE, TRAINER_NONE, single));
    EXPECT(!BattleSetup_TryPreflightOrdinaryBattle(TRAINER_RED_TEST, TRAINER_NONE, TRAINER_NONE, two));
    EXPECT(!BattleSetup_TryPreflightOrdinaryBattle(TRAINER_RED_TEST, 0xFFFF, TRAINER_NONE, two));
    EXPECT(!BattleSetup_TryPreflightOrdinaryBattle(TRAINER_RED_TEST, TRAINER_LEAF_TEST, TRAINER_NONE, single));
}

TEST("Ordinary battle preflight accepts complete one two and partner topologies")
{
    EXPECT(BattleSetup_TryPreflightOrdinaryBattle(
        TRAINER_YOUNGSTER_SAMUEL_JOHTO,
        TRAINER_NONE,
        TRAINER_NONE,
        BATTLE_TYPE_TRAINER));
    EXPECT(BattleSetup_TryPreflightOrdinaryBattle(
        TRAINER_RED_TEST,
        TRAINER_NONE,
        TRAINER_NONE,
        BATTLE_TYPE_TRAINER));
    EXPECT(BattleSetup_TryPreflightOrdinaryBattle(
        TRAINER_RED_TEST,
        TRAINER_LEAF_TEST,
        TRAINER_NONE,
        BATTLE_TYPE_TRAINER | BATTLE_TYPE_DOUBLE | BATTLE_TYPE_TWO_OPPONENTS));
    EXPECT(BattleSetup_TryPreflightOrdinaryBattle(
        TRAINER_RED_TEST,
        0xFFFF,
        TRAINER_PARTNER(PARTNER_STEVEN),
        BATTLE_TYPE_TRAINER | BATTLE_TYPE_DOUBLE | BATTLE_TYPE_MULTI | BATTLE_TYPE_INGAME_PARTNER));
}

TEST("Multi party sizing keeps explicit trainer namespaces out of the ordinary registry")
{
    static const u32 explicitNamespaces[] =
    {
        BATTLE_TYPE_FRONTIER,
        BATTLE_TYPE_TRAINER_HILL,
        BATTLE_TYPE_SECRET_BASE,
        BATTLE_TYPE_EREADER_TRAINER,
        BATTLE_TYPE_LINK,
    };

    for (u32 i = 0; i < ARRAY_COUNT(explicitNamespaces); i++)
    {
        EXPECT(BattleUtil_TestAreMultiPartiesFullTeamsForBattle(
            BATTLE_TYPE_TRAINER | explicitNamespaces[i],
            TRAINER_NONE,
            TRAINER_NONE));
        EXPECT(gSpecialVar_Result);
    }

    EXPECT(!BattleUtil_TestAreMultiPartiesFullTeamsForBattle(
        BATTLE_TYPE_TRAINER,
        TRAINER_NONE,
        TRAINER_NONE));
    EXPECT(!gSpecialVar_Result);
    EXPECT(BattleUtil_TestAreMultiPartiesFullTeamsForBattle(
        BATTLE_TYPE_TRAINER,
        TRAINER_RED_TEST,
        TRAINER_NONE));
    EXPECT(gSpecialVar_Result);
    EXPECT(!BattleUtil_TestAreMultiPartiesFullTeamsForBattle(
        BATTLE_TYPE_TRAINER | BATTLE_TYPE_TOWER_LINK_MULTI,
        TRAINER_LINK_OPPONENT,
        TRAINER_NONE));
    EXPECT(!gSpecialVar_Result);
}

TEST("Invalid trainer script preflight leaves battle globals unchanged")
{
    TrainerBattleParameter original = gTrainerBattleParameter;
    TrainerBattleParameter before;
    TrainerBattleParameter invalid = {0};
    u32 originalBattleTypeFlags = gBattleTypeFlags;
    u32 battleTypeFlags = 0xA5A5A5A5;

    memset(gTrainerBattleParameter.data, 0x5A, sizeof(gTrainerBattleParameter));
    before = gTrainerBattleParameter;
    gBattleTypeFlags = battleTypeFlags;
    invalid.params.opponentA = TRAINERS_COUNT;

    EXPECT(!BattleSetup_TryPreflightTrainerBattleData(invalid.data));
    EXPECT(!BattleSetup_TryLoadTrainerBattle(invalid.data));
    EXPECT_EQ(memcmp(&gTrainerBattleParameter, &before, sizeof(before)), 0);
    EXPECT_EQ(gBattleTypeFlags, battleTypeFlags);

    gTrainerBattleParameter = original;
    gBattleTypeFlags = originalBattleTypeFlags;
}

TEST("Scripted two-opponent battles validate an active follower before loading globals")
{
    TrainerBattleParameter battle = {0};
    struct LaunchSnapshot snapshot;

    battle.params.mode = TRAINER_BATTLE_TWO_TRAINERS_NO_INTRO;
    battle.params.opponentA = TRAINER_RED_TEST;
    battle.params.opponentB = TRAINER_LEAF_TEST;
    TakeLaunchSnapshot(&snapshot);
    EXPECT(!BattleSetup_TestTryLoadTrainerBattleWithFollower(
        battle.data,
        TRAINER_PARTNER(PARTNER_COUNT)));
    ExpectLaunchSnapshot(&snapshot);

    EXPECT(BattleSetup_TestTryLoadTrainerBattleWithFollower(
        battle.data,
        TRAINER_PARTNER(PARTNER_STEVEN)));
}

TEST("Invalid direct battle launches preserve every observable mutation boundary")
{
    static const struct
    {
        u16 opponentA;
        u16 opponentB;
        u8 approachingTrainers;
    } invalid[] =
    {
        {TRAINERS_COUNT, TRAINER_NONE, 1},
        {TRAINER_RED_TEST, TRAINER_NONE, 2},
        {TRAINER_RED_TEST, TRAINERS_COUNT, 2},
    };

    for (u32 i = 0; i < ARRAY_COUNT(invalid); i++)
    {
        struct LaunchSnapshot snapshot;

        TRAINER_BATTLE_PARAM.opponentA = invalid[i].opponentA;
        TRAINER_BATTLE_PARAM.opponentB = invalid[i].opponentB;
        gNoOfApproachingTrainers = invalid[i].approachingTrainers;
        TakeLaunchSnapshot(&snapshot);
        BattleSetup_StartTrainerBattle();
        ExpectLaunchSnapshot(&snapshot);
    }
}

TEST("Trainer sight rejects a valid first and invalid second trainer before tasks or locks")
{
    u8 trainerScriptA[1 + sizeof(TrainerBattleParameter)] = {0};
    u8 trainerScriptB[1 + sizeof(TrainerBattleParameter)] = {0};
    TrainerBattleParameter *trainerA = (TrainerBattleParameter *)(trainerScriptA + 1);
    TrainerBattleParameter *trainerB = (TrainerBattleParameter *)(trainerScriptB + 1);
    u8 tasksBefore = CountActiveTasks();
    bool8 lockedBefore = ArePlayerFieldControlsLocked();

    trainerA->params.opponentA = TRAINER_RED_TEST;
    trainerB->params.opponentA = TRAINERS_COUNT;

    EXPECT(!TrainerSee_TestTrySetUpTwoTrainersBattle(trainerScriptA, trainerScriptB));
    EXPECT_EQ(CountActiveTasks(), tasksBefore);
    EXPECT_EQ(ArePlayerFieldControlsLocked(), lockedBefore);
    EXPECT_EQ(gNoOfApproachingTrainers, 0);
    EXPECT(!gTrainerApproachedPlayer);
}

TEST("Facility sight scripts bypass ordinary trainer payload parsing")
{
    u8 facilityScript[1 + sizeof(TrainerBattleParameter)] = {0};

    EXPECT_EQ(TrainerSee_TestPreflightSightTrainerBattle(
        facilityScript,
        TRUE,
        PYRAMID_LOCATION_NONE),
        1);
    EXPECT_EQ(TrainerSee_TestPreflightSightTrainerBattle(
        facilityScript,
        FALSE,
        PYRAMID_LOCATION_FLOOR),
        1);
    EXPECT_EQ(TrainerSee_TestPreflightSightTrainerBattle(
        facilityScript,
        FALSE,
        PYRAMID_LOCATION_NONE),
        0xFE);
}

TEST("Failed rematch target resolution preserves launch state")
{
    TrainerBattleParameter rematch = {0};
    struct LaunchSnapshot snapshot;

    rematch.params.mode = TRAINER_BATTLE_REMATCH;
    rematch.params.opponentA = TRAINER_RED_TEST;
    TakeLaunchSnapshot(&snapshot);
    EXPECT(!BattleSetup_TryLoadTrainerBattle(rematch.data));
    ExpectLaunchSnapshot(&snapshot);
}

TEST("Battle defeat wrappers support regional bitmap trainers")
{
    u8 defeatedBefore[sizeof(gSaveBlock1Ptr->trainerDefeated)];
    bool32 defeated = TRUE;
    const u16 trainerId = TRAINER_FRLG_YOUNGSTER_CALVIN;

    EXPECT(PersistentId_ClearTrainerDefeated(trainerId));
    EXPECT(!HasTrainerBeenFought(trainerId));
    SetTrainerFlag(trainerId);
    EXPECT(HasTrainerBeenFought(trainerId));
    EXPECT(PersistentId_GetTrainerDefeated(trainerId, &defeated));
    EXPECT(defeated);
    ClearTrainerFlag(trainerId);
    EXPECT(!HasTrainerBeenFought(trainerId));

    memcpy(defeatedBefore, gSaveBlock1Ptr->trainerDefeated, sizeof(defeatedBefore));
    SetTrainerFlag(TRAINERS_COUNT);
    ClearTrainerFlag(TRAINERS_COUNT);
    EXPECT(!HasTrainerBeenFought(TRAINERS_COUNT));
    EXPECT_EQ(memcmp(gSaveBlock1Ptr->trainerDefeated, defeatedBefore, sizeof(defeatedBefore)), 0);
}

TEST("Post-victory defeat path records every regional bitmap opponent")
{
    bool32 defeated = FALSE;

    EXPECT(PersistentId_ClearTrainerDefeated(TRAINER_FRLG_YOUNGSTER_CALVIN));
    EXPECT(PersistentId_ClearTrainerDefeated(TRAINER_FRLG_YOUNGSTER_BEN));
    BattleSetup_TestSetBattledTrainersFlags(
        TRAINER_FRLG_YOUNGSTER_CALVIN,
        TRAINER_FRLG_YOUNGSTER_BEN);
    EXPECT(PersistentId_GetTrainerDefeated(TRAINER_FRLG_YOUNGSTER_CALVIN, &defeated));
    EXPECT(defeated);
    EXPECT(PersistentId_GetTrainerDefeated(TRAINER_FRLG_YOUNGSTER_BEN, &defeated));
    EXPECT(defeated);
}
