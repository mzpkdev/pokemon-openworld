#include "global.h"
#include "new_game_start_profile.h"
#include "overworld.h"
#include "constants/heal_locations.h"
#include "constants/maps.h"

#ifdef DEBUG
#include <stddef.h>
#endif

#ifdef DEBUG
#define START_PROFILE_SELECTOR_AVAILABLE TRUE
#define START_PROFILE_REQUEST_SIZE sizeof(struct DebugNewGameStartProfileRequest)
#define START_PROFILE_REQUEST_STATUS_OFFSET offsetof(struct DebugNewGameStartProfileRequest, status)
#else
#define START_PROFILE_SELECTOR_AVAILABLE FALSE
#define START_PROFILE_REQUEST_SIZE 0
#define START_PROFILE_REQUEST_STATUS_OFFSET 0
#endif

const struct NewGameStartProfile gNewGameStartProfiles[NEW_GAME_START_PROFILE_COUNT] =
{
    [NEW_GAME_START_PROFILE_HOENN] =
    {
        .checkpointId = HEAL_LOCATION_NONE,
        .facingDirection = DIR_SOUTH,
        .onboarding = NEW_GAME_START_ONBOARDING_TRUCK,
    },
    [NEW_GAME_START_PROFILE_KANTO] =
    {
        .checkpointId = HEAL_LOCATION_PALLET_TOWN,
        .facingDirection = DIR_SOUTH,
        .onboarding = NEW_GAME_START_ONBOARDING_FIELD,
    },
    [NEW_GAME_START_PROFILE_JOHTO] =
    {
        .checkpointId = HEAL_LOCATION_OLIVINE_CITY,
        .facingDirection = DIR_SOUTH,
        .onboarding = NEW_GAME_START_ONBOARDING_FIELD,
    },
};

const struct NewGameStartProductionContract gNewGameStartProductionContract =
{
    .abiVersion = NEW_GAME_START_PROFILE_ABI_VERSION,
    .defaultProfile = NEW_GAME_START_PROFILE_HOENN,
    .selectorAvailable = START_PROFILE_SELECTOR_AVAILABLE,
    .profileCount = NEW_GAME_START_PROFILE_COUNT,
    .requestSize = START_PROFILE_REQUEST_SIZE,
    .requestStatusOffset = START_PROFILE_REQUEST_STATUS_OFFSET,
};

#ifdef DEBUG

volatile struct DebugNewGameStartProfileRequest gDebugNewGameStartProfileRequest;

STATIC_ASSERT(sizeof(struct DebugNewGameStartProfileRequest) == 8, DebugNewGameStartProfileRequestSize);
STATIC_ASSERT(offsetof(struct DebugNewGameStartProfileRequest, status) == 7, DebugNewGameStartProfileRequestStatusOffset);

#endif

static enum NewGameStartProfileId SanitizeProfile(enum NewGameStartProfileId profileId)
{
    if (profileId >= NEW_GAME_START_PROFILE_COUNT)
        return NEW_GAME_START_PROFILE_HOENN;
    return profileId;
}

enum NewGameStartProfileId NewGameStartProfile_ConsumeSelection(void)
{
#ifdef DEBUG
    struct DebugNewGameStartProfileRequest request;

    if (gDebugNewGameStartProfileRequest.status != DEBUG_NEW_GAME_START_PROFILE_PENDING)
        return NEW_GAME_START_PROFILE_HOENN;

    request.requestId = gDebugNewGameStartProfileRequest.requestId;
    request.abiVersion = gDebugNewGameStartProfileRequest.abiVersion;
    request.profileId = gDebugNewGameStartProfileRequest.profileId;
    request.status = gDebugNewGameStartProfileRequest.status;
    if (request.requestId == 0
     || request.abiVersion != NEW_GAME_START_PROFILE_ABI_VERSION
     || request.profileId >= NEW_GAME_START_PROFILE_COUNT)
    {
        gDebugNewGameStartProfileRequest.status = DEBUG_NEW_GAME_START_PROFILE_ERROR;
        return NEW_GAME_START_PROFILE_HOENN;
    }

    gDebugNewGameStartProfileRequest.status = DEBUG_NEW_GAME_START_PROFILE_ACCEPTED;
    return request.profileId;
#else
    return NEW_GAME_START_PROFILE_HOENN;
#endif
}

void NewGameStartProfile_Apply(enum NewGameStartProfileId profileId)
{
    const struct NewGameStartProfile *profile;

    profileId = SanitizeProfile(profileId);
    profile = &gNewGameStartProfiles[profileId];
    if (profile->onboarding == NEW_GAME_START_ONBOARDING_TRUCK)
        SetWarpDestination(MAP_GROUP(MAP_INSIDE_OF_TRUCK), MAP_NUM(MAP_INSIDE_OF_TRUCK), WARP_ID_NONE, -1, -1);
    else
    {
        SetWarpDestinationToHealLocation(profile->checkpointId);
        SetLastHealLocationWarp(profile->checkpointId);
    }
    WarpIntoMap();
    SetInitialPlayerAvatarStateDirection(profile->facingDirection);
}

bool32 NewGameStartProfile_UsesTruckOnboarding(enum NewGameStartProfileId profileId)
{
    profileId = SanitizeProfile(profileId);
    return gNewGameStartProfiles[profileId].onboarding == NEW_GAME_START_ONBOARDING_TRUCK;
}

#undef START_PROFILE_SELECTOR_AVAILABLE
#undef START_PROFILE_REQUEST_SIZE
#undef START_PROFILE_REQUEST_STATUS_OFFSET
