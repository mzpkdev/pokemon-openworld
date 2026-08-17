#ifndef GUARD_DEBUG_GENERATED_DUNGEON_FIXTURE_H
#define GUARD_DEBUG_GENERATED_DUNGEON_FIXTURE_H

#ifdef DEBUG

#define DEBUG_GENERATED_DUNGEON_FIXTURE_PROVIDER_ID 0xD090
#define DEBUG_GENERATED_DUNGEON_FIXTURE_GENERATION_VERSION 1

enum DebugGeneratedDungeonFixtureStatus
{
    DEBUG_GENERATED_DUNGEON_FIXTURE_IDLE,
    DEBUG_GENERATED_DUNGEON_FIXTURE_PENDING,
    DEBUG_GENERATED_DUNGEON_FIXTURE_RUNNING,
    DEBUG_GENERATED_DUNGEON_FIXTURE_SUCCESS,
    DEBUG_GENERATED_DUNGEON_FIXTURE_ERROR,
};

enum DebugGeneratedDungeonFixtureError
{
    DEBUG_GENERATED_DUNGEON_FIXTURE_ERROR_NONE,
    DEBUG_GENERATED_DUNGEON_FIXTURE_ERROR_NOT_READY,
    DEBUG_GENERATED_DUNGEON_FIXTURE_ERROR_REQUEST,
    DEBUG_GENERATED_DUNGEON_FIXTURE_ERROR_BEGIN,
};

struct DebugGeneratedDungeonFixtureRequest
{
    u32 requestId;
    u32 seed;
    u8 status;
    u8 reserved[3];
};

struct DebugGeneratedDungeonFixtureResult
{
    u32 requestId;
    u32 seed;
    u16 providerId;
    u16 generationVersion;
    u8 mapGroup;
    u8 mapNum;
    u8 error;
    u8 status;
};

extern volatile struct DebugGeneratedDungeonFixtureRequest gDebugGeneratedDungeonFixtureRequest;
extern volatile struct DebugGeneratedDungeonFixtureResult gDebugGeneratedDungeonFixtureResult;

void DebugGeneratedDungeonFixture_Init(void);
void DebugGeneratedDungeonFixture_Update(void);

#endif // DEBUG

#endif // GUARD_DEBUG_GENERATED_DUNGEON_FIXTURE_H
