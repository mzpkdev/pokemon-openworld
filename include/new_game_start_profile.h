#ifndef GUARD_NEW_GAME_START_PROFILE_H
#define GUARD_NEW_GAME_START_PROFILE_H

#define NEW_GAME_START_PROFILE_ABI_VERSION 1

enum NewGameStartProfileId
{
    NEW_GAME_START_PROFILE_HOENN,
    NEW_GAME_START_PROFILE_KANTO,
    NEW_GAME_START_PROFILE_JOHTO,
    NEW_GAME_START_PROFILE_COUNT,
};

enum NewGameStartOnboarding
{
    NEW_GAME_START_ONBOARDING_TRUCK,
    NEW_GAME_START_ONBOARDING_FIELD,
};

struct NewGameStartProfile
{
    u8 checkpointId;
    u8 facingDirection;
    u8 onboarding;
    u8 reserved;
};

struct NewGameStartProductionContract
{
    u16 abiVersion;
    u8 defaultProfile;
    u8 selectorAvailable;
    u8 profileCount;
    u8 requestSize;
    u8 requestStatusOffset;
    u8 reserved;
};

extern const struct NewGameStartProfile gNewGameStartProfiles[NEW_GAME_START_PROFILE_COUNT];
extern const struct NewGameStartProductionContract gNewGameStartProductionContract;

enum NewGameStartProfileId NewGameStartProfile_ConsumeSelection(void);
void NewGameStartProfile_Apply(enum NewGameStartProfileId profileId);
bool32 NewGameStartProfile_UsesTruckOnboarding(enum NewGameStartProfileId profileId);

#ifdef DEBUG

enum DebugNewGameStartProfileStatus
{
    DEBUG_NEW_GAME_START_PROFILE_IDLE,
    DEBUG_NEW_GAME_START_PROFILE_PENDING,
    DEBUG_NEW_GAME_START_PROFILE_ACCEPTED,
    DEBUG_NEW_GAME_START_PROFILE_ERROR,
};

struct DebugNewGameStartProfileRequest
{
    u32 requestId;
    u16 abiVersion;
    u8 profileId;
    u8 status;
};

extern volatile struct DebugNewGameStartProfileRequest gDebugNewGameStartProfileRequest;

#endif // DEBUG

#endif // GUARD_NEW_GAME_START_PROFILE_H
