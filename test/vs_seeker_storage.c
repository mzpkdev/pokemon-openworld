#include "global.h"
#include "battle_setup.h"
#include "script.h"
#include "vs_seeker.h"
#include "constants/opponents.h"
#include "test/test.h"

#if FREE_MATCH_CALL == FALSE
enum
{
    VS_STORAGE_START = offsetof(struct SaveBlock1, trainerRematchStepCounter),
    VS_STORAGE_END = offsetof(struct SaveBlock1, objectEvents),
    VS_STORAGE_AND_CANARY_SIZE = VS_STORAGE_END - VS_STORAGE_START,
};

STATIC_ASSERT(VS_STORAGE_AND_CANARY_SIZE == sizeof(gSaveBlock1Ptr->trainerRematchStepCounter)
                                             + MAX_REMATCH_ENTRIES + 2,
              VsSeekerStorageCanarySize);
#endif // FREE_MATCH_CALL

TEST("Disabled Vs Seeker public paths preserve Match Call storage and canaries")
{
#if FREE_MATCH_CALL == FALSE
    u8 snapshot[VS_STORAGE_AND_CANARY_SIZE];
    u8 *storageAndCanaries = (u8 *)gSaveBlock1Ptr + VS_STORAGE_START;
    const u8 scriptArgs[] =
    {
        TRAINER_FRLG_YOUNGSTER_BEN & 0xFF,
        TRAINER_FRLG_YOUNGSTER_BEN >> 8,
    };
    struct ScriptContext scriptContext = { .scriptPtr = scriptArgs };

    memset(storageAndCanaries, 0xA5, VS_STORAGE_AND_CANARY_SIZE);
    TRAINER_BATTLE_PARAM.opponentA = TRAINER_FRLG_YOUNGSTER_BEN;
    memcpy(snapshot, storageAndCanaries, sizeof(snapshot));

    EXPECT(!UpdateVsSeekerStepCounter());
    MapResetTrainerRematches(0, 0);
    Task_InitVsSeekerAndCheckForTrainersOnScreen(0);
    ClearRematchMovementByTrainerId();
    EXPECT_EQ(GetRematchTrainerIdVSSeeker(TRAINER_FRLG_YOUNGSTER_BEN), 0);
    EXPECT(!IsVsSeekerEnabled());
    NativeVsSeekerRematchId(&scriptContext);

    EXPECT_EQ(memcmp(storageAndCanaries, snapshot, sizeof(snapshot)), 0);
#endif // FREE_MATCH_CALL
}
