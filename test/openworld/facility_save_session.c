#include "global.h"
#include "overworld.h"
#include "save.h"
#include "save_location.h"
#include "test/test.h"
#include "constants/battle_frontier.h"

TEST("Field save serializes an active paused facility session as paused")
{
    struct FacilitySaveStatusState original =
    {
        .challengeStatus = CHALLENGE_STATUS_SAVING,
        .challengeStatusVar = 0xFF,
    };
    struct FacilitySaveStatusState state = original;

    EXPECT_EQ(
        GetSerializedFacilityChallengeStatus(SAVE_NORMAL, CHALLENGE_STATUS_SAVING, TRUE),
        CHALLENGE_STATUS_PAUSED
    );
    EXPECT_EQ(
        GetSerializedFacilityChallengeStatus(SAVE_OVERWRITE_DIFFERENT_FILE, CHALLENGE_STATUS_SAVING, TRUE),
        CHALLENGE_STATUS_PAUSED
    );
    EXPECT_EQ(
        GetSerializedFacilityChallengeStatus(SAVE_LINK, CHALLENGE_STATUS_SAVING, TRUE),
        CHALLENGE_STATUS_SAVING
    );
    EXPECT_EQ(
        GetSerializedFacilityChallengeStatus(SAVE_NORMAL, CHALLENGE_STATUS_SAVING, FALSE),
        CHALLENGE_STATUS_SAVING
    );
    PrepareFacilitySaveStatus(SAVE_NORMAL, TRUE, &state);
    EXPECT_EQ(state.challengeStatus, CHALLENGE_STATUS_PAUSED);
    EXPECT_EQ(state.challengeStatusVar, 0);
    RestoreFacilitySaveStatus(&state, &original);
    EXPECT_EQ(state.challengeStatus, CHALLENGE_STATUS_SAVING);
    EXPECT_EQ(state.challengeStatusVar, 0xFF);
}

TEST("Continue normalizes only a paused Tower session away from its lobby")
{
    EXPECT_EQ(
        GetFacilityChallengeStatusOnContinue(
            SAVE_STATUS_OK,
            CHALLENGE_STATUS_PAUSED,
            FRONTIER_FACILITY_TOWER,
            0
        ),
        CHALLENGE_STATUS_SAVING
    );
    EXPECT_EQ(
        GetFacilityChallengeStatusOnContinue(
            SAVE_STATUS_OK,
            CHALLENGE_STATUS_PAUSED,
            FRONTIER_FACILITY_TOWER,
            LOBBY_SAVEWARP
        ),
        CHALLENGE_STATUS_PAUSED
    );
    EXPECT_EQ(
        GetFacilityChallengeStatusOnContinue(
            SAVE_STATUS_OK,
            CHALLENGE_STATUS_PAUSED,
            FRONTIER_FACILITY_PIKE,
            0
        ),
        CHALLENGE_STATUS_PAUSED
    );
    EXPECT_EQ(
        GetFacilityChallengeStatusOnContinue(
            SAVE_STATUS_OK,
            CHALLENGE_STATUS_PAUSED,
            FRONTIER_FACILITY_PYRAMID,
            0
        ),
        CHALLENGE_STATUS_PAUSED
    );
}
