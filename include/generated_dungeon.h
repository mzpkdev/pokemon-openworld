#ifndef GUARD_GENERATED_DUNGEON_H
#define GUARD_GENERATED_DUNGEON_H

#include "global.h"
#include "random.h"

#define GENERATED_DUNGEON_MAX_CELLS 4096
#define GENERATED_DUNGEON_MAX_ATTEMPTS 8
#define GENERATED_DUNGEON_MAX_OBJECTS OBJECT_EVENTS_COUNT
#define GENERATED_DUNGEON_PROGRESS_BITS 64
#define GENERATED_DUNGEON_WORKSPACE_MAX_BYTES 17920

// These values are persisted meanings. Append new domains; do not renumber them.
enum GeneratedDungeonRngDomain
{
    GENERATED_DUNGEON_RNG_TOPOLOGY,
    GENERATED_DUNGEON_RNG_ENDPOINTS,
    GENERATED_DUNGEON_RNG_OBSTRUCTIONS,
    GENERATED_DUNGEON_RNG_TRAINERS,
    GENERATED_DUNGEON_RNG_OPTIONAL_OBJECTS,
    GENERATED_DUNGEON_RNG_DOMAIN_COUNT,
};

struct GeneratedDungeonWorkspace;
struct GeneratedDungeonProvider;

struct GeneratedDungeonPoint
{
    u16 x;
    u16 y;
};

// The runtime never interprets a semantic cell as a metatile or movement rule.
// Those meanings belong to the provider and are stable for its generation version.
typedef bool32 (*GeneratedDungeonTranslateCellCallback)(const struct GeneratedDungeonProvider *provider, u16 semanticCell, u16 *metatile);
typedef bool32 (*GeneratedDungeonCanMoveCallback)(const struct GeneratedDungeonProvider *provider, const struct GeneratedDungeonWorkspace *workspace, struct GeneratedDungeonPoint from, struct GeneratedDungeonPoint to);

struct GeneratedDungeonRngStreams
{
    rng_value_t values[GENERATED_DUNGEON_RNG_DOMAIN_COUNT];
};

typedef bool32 (*GeneratedDungeonGenerateCallback)(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonRngStreams *rng, u8 attempt, struct GeneratedDungeonWorkspace *workspace);
typedef bool32 (*GeneratedDungeonFallbackCallback)(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonWorkspace *workspace);

struct GeneratedDungeonObject
{
    struct ObjectEventTemplate template;
    bool8 blocksMovement;
};

// providerId and generationVersion identify a saved run, not a registry slot.
struct GeneratedDungeonProvider
{
    u16 providerId;
    u16 generationVersion;
    u8 mapGroup;
    u8 mapNum;
    u16 maxWorkspaceCells;
    u8 maxGeneratedObjects;
    GeneratedDungeonTranslateCellCallback translateCell;
    GeneratedDungeonCanMoveCallback canMove;
    GeneratedDungeonGenerateCallback generate;
    GeneratedDungeonFallbackCallback fallback;
};

struct GeneratedDungeonWorkspace
{
    u16 width;
    u16 height;
    u8 objectCount;
    struct GeneratedDungeonPoint spawn;
    struct GeneratedDungeonPoint originEndpoint;
    struct GeneratedDungeonPoint destinationEndpoint;
    struct GeneratedDungeonObject objects[GENERATED_DUNGEON_MAX_OBJECTS];
    u16 cells[GENERATED_DUNGEON_MAX_CELLS];
    u8 reached[(GENERATED_DUNGEON_MAX_CELLS + 7) / 8];
    u16 queue[GENERATED_DUNGEON_MAX_CELLS];
};

// A lifecycle caller supplies the exact interior map view. Nothing is written
// until generation, translation, object validation, and directed reachability
// have all succeeded.
struct GeneratedDungeonPublication
{
    u16 *map;
    u16 mapWidth;
    u16 mapHeight;
    u16 mapStride;
    struct ObjectEventTemplate *templates;
    u8 templateCapacity;
};

enum GeneratedDungeonGenerationResult
{
    GENERATED_DUNGEON_GENERATION_FAILED,
    GENERATED_DUNGEON_GENERATION_SUCCEEDED,
    GENERATED_DUNGEON_GENERATION_FALLBACK,
};

bool32 GeneratedDungeon_ValidateRegistry(const struct GeneratedDungeonProvider *providers, u16 count);
bool32 GeneratedDungeon_FindProviderByMap(u8 mapGroup, u8 mapNum, const struct GeneratedDungeonProvider **provider);
bool32 GeneratedDungeon_FindProviderById(u16 providerId, u16 generationVersion, const struct GeneratedDungeonProvider **provider);

rng_value_t GeneratedDungeon_DeriveStream(u16 providerId, u16 generationVersion, u32 seed, enum GeneratedDungeonRngDomain domain, u8 attempt);
void GeneratedDungeon_DeriveStreams(const struct GeneratedDungeonProvider *provider, u32 seed, u8 attempt, struct GeneratedDungeonRngStreams *rng);

void GeneratedDungeonWorkspace_Reset(struct GeneratedDungeonWorkspace *workspace);
bool32 GeneratedDungeonWorkspace_SetDimensions(struct GeneratedDungeonWorkspace *workspace, u16 width, u16 height);
bool32 GeneratedDungeonWorkspace_SetCell(struct GeneratedDungeonWorkspace *workspace, u16 x, u16 y, u16 cell);
bool32 GeneratedDungeonWorkspace_GetCell(const struct GeneratedDungeonWorkspace *workspace, u16 x, u16 y, u16 *cell);
bool32 GeneratedDungeonWorkspace_SetObjectCount(struct GeneratedDungeonWorkspace *workspace, u8 objectCount);
bool32 GeneratedDungeonWorkspace_SetSpawn(struct GeneratedDungeonWorkspace *workspace, u16 x, u16 y);
bool32 GeneratedDungeonWorkspace_SetOriginEndpoint(struct GeneratedDungeonWorkspace *workspace, u16 x, u16 y);
bool32 GeneratedDungeonWorkspace_SetDestinationEndpoint(struct GeneratedDungeonWorkspace *workspace, u16 x, u16 y);
bool32 GeneratedDungeonWorkspace_SetObject(struct GeneratedDungeonWorkspace *workspace, u8 index, const struct ObjectEventTemplate *template, bool8 blocksMovement);
bool32 GeneratedDungeonWorkspace_IsValid(const struct GeneratedDungeonProvider *provider, const struct GeneratedDungeonWorkspace *workspace);
bool32 GeneratedDungeonWorkspace_HasReachableEndpoints(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonWorkspace *workspace);

enum GeneratedDungeonGenerationResult GeneratedDungeon_Generate(const struct GeneratedDungeonProvider *provider, u32 seed, struct GeneratedDungeonWorkspace *workspace);
enum GeneratedDungeonGenerationResult GeneratedDungeon_GenerateAndPublish(const struct GeneratedDungeonProvider *provider, u32 seed, struct GeneratedDungeonWorkspace *workspace, const struct GeneratedDungeonPublication *publication);

bool32 GeneratedDungeonProgress_TryGet(u64 progress, u8 bit, bool32 *set);
bool32 GeneratedDungeonProgress_TrySet(u64 *progress, u8 bit);
bool32 GeneratedDungeonProgress_TryClear(u64 *progress, u8 bit);

#if TESTING
bool32 GeneratedDungeon_TestSetRegistry(const struct GeneratedDungeonProvider *providers, u16 count);
void GeneratedDungeon_TestResetRegistry(void);
#endif

#endif // GUARD_GENERATED_DUNGEON_H
