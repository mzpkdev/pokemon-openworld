#include "global.h"
#include "event_object_movement.h"
#include "field_screen_effect.h"
#include "generated_dungeon.h"
#include "generated_dungeon_persistence.h"
#include "generated_ocean.h"
#include "overworld.h"
#include "random.h"
#include "surf_edge_exits.h"
#include "constants/event_object_movement.h"
#include "constants/event_objects.h"
#include "constants/maps.h"
#include "constants/metatile_labels.h"
#include "constants/trainer_types.h"

#define GENERATED_OCEAN_WIDTH 62
#define GENERATED_OCEAN_HEIGHT 24
#define GENERATED_OCEAN_SPAWN_X 2
#define GENERATED_OCEAN_ORIGIN_X 1
#define GENERATED_OCEAN_DESTINATION_X (GENERATED_OCEAN_WIDTH - 2)
#define GENERATED_OCEAN_ENDPOINT_Y (GENERATED_OCEAN_HEIGHT / 2)
#define GENERATED_OCEAN_TRAINER_COUNT 4
#define GENERATED_OCEAN_TRAINER_LOCAL_ID_BASE 1
#define GENERATED_OCEAN_TRAINER_SIGHT_RANGE 3
#define GENERATED_OCEAN_OBJECT_COUNT GENERATED_OCEAN_TRAINER_COUNT

enum GeneratedOceanCell
{
    GENERATED_OCEAN_CELL_CALM_WATER,
    GENERATED_OCEAN_CELL_ROUGH_WATER,
    GENERATED_OCEAN_CELL_IMPASSABLE_WATER,
};

extern const u8 Route40_EventScript_Elaine[];
extern const u8 Route40_EventScript_Simon[];
extern const u8 Route40_EventScript_Paula[];
extern const u8 Route40_EventScript_Randall[];

static bool8 sInitialized;

static const u8 *const sTrainerScripts[GENERATED_OCEAN_TRAINER_COUNT] =
{
    Route40_EventScript_Elaine,
    Route40_EventScript_Simon,
    Route40_EventScript_Paula,
    Route40_EventScript_Randall,
};

static const u16 sTrainerGraphics[GENERATED_OCEAN_TRAINER_COUNT] =
{
    OBJ_EVENT_GFX_SWIMMER_F_WATER,
    OBJ_EVENT_GFX_SWIMMER_M_WATER,
    OBJ_EVENT_GFX_SWIMMER_F_WATER,
    OBJ_EVENT_GFX_SWIMMER_M_WATER,
};

static bool32 TranslateCell(const struct GeneratedDungeonProvider *provider, u16 cell, u16 *metatile)
{
    if (provider == NULL || metatile == NULL)
        return FALSE;

    switch (cell)
    {
    case GENERATED_OCEAN_CELL_CALM_WATER:
        *metatile = METATILE_General_CalmWater;
        return TRUE;
    case GENERATED_OCEAN_CELL_ROUGH_WATER:
        *metatile = METATILE_General_RoughWater;
        return TRUE;
    case GENERATED_OCEAN_CELL_IMPASSABLE_WATER:
        // Collision is map-cell data, so preserve the ocean tile's visual and
        // behavior while making the generated reef unenterable to the engine.
        *metatile = METATILE_General_RoughWater | MAPGRID_IMPASSABLE;
        return TRUE;
    default:
        return FALSE;
    }
}

static bool32 CanMove(const struct GeneratedDungeonProvider *provider, const struct GeneratedDungeonWorkspace *workspace, struct GeneratedDungeonPoint from, struct GeneratedDungeonPoint to)
{
    u16 fromCell;
    u16 toCell;

    if (provider == NULL
     || !GeneratedDungeonWorkspace_GetCell(workspace, from.x, from.y, &fromCell)
     || !GeneratedDungeonWorkspace_GetCell(workspace, to.x, to.y, &toCell)
     || fromCell > GENERATED_OCEAN_CELL_IMPASSABLE_WATER
     || toCell > GENERATED_OCEAN_CELL_IMPASSABLE_WATER
     || fromCell == GENERATED_OCEAN_CELL_IMPASSABLE_WATER
     || toCell == GENERATED_OCEAN_CELL_IMPASSABLE_WATER)
        return FALSE;

    return (from.x == to.x && (from.y + 1 == to.y || to.y + 1 == from.y))
        || (from.y == to.y && (from.x + 1 == to.x || to.x + 1 == from.x));
}

static bool32 IsEndpoint(u16 x, u16 y)
{
    return y == GENERATED_OCEAN_ENDPOINT_Y
        && (x == GENERATED_OCEAN_SPAWN_X
         || x == GENERATED_OCEAN_ORIGIN_X
         || x == GENERATED_OCEAN_DESTINATION_X);
}

static bool32 IsOccupiedByPreviousObject(const struct GeneratedDungeonWorkspace *workspace, u8 objectCount, u16 x, u16 y)
{
    u8 i;

    for (i = 0; i < objectCount; i++)
    {
        if (workspace->objects[i].template.x == x && workspace->objects[i].template.y == y)
            return TRUE;
    }
    return FALSE;
}

static bool32 FindObjectPosition(struct GeneratedDungeonWorkspace *workspace, rng_value_t *rng, u8 objectCount, u16 *x, u16 *y)
{
    u8 tries;

    if (workspace == NULL || rng == NULL || x == NULL || y == NULL)
        return FALSE;

    for (tries = 0; tries < 64; tries++)
    {
        u16 candidateX = 4 + LocalRandom(rng) % (GENERATED_OCEAN_WIDTH - 8);
        u16 candidateY = 1 + LocalRandom(rng) % (GENERATED_OCEAN_HEIGHT - 2);
        u16 cell;

        if (!IsEndpoint(candidateX, candidateY)
         // Keep the only guaranteed endpoint lane outside every trainer's
         // ordinary line-of-sight range, while leaving the swimmers as real
         // encounters elsewhere in the generated ocean.
         && (candidateY + GENERATED_OCEAN_TRAINER_SIGHT_RANGE < GENERATED_OCEAN_ENDPOINT_Y
          || candidateY > GENERATED_OCEAN_ENDPOINT_Y + GENERATED_OCEAN_TRAINER_SIGHT_RANGE)
         && GeneratedDungeonWorkspace_GetCell(workspace, candidateX, candidateY, &cell)
         && cell != GENERATED_OCEAN_CELL_IMPASSABLE_WATER
         && !IsOccupiedByPreviousObject(workspace, objectCount, candidateX, candidateY))
        {
            *x = candidateX;
            *y = candidateY;
            return TRUE;
        }
    }
    return FALSE;
}

static bool32 SetObject(struct GeneratedDungeonWorkspace *workspace, u8 index, u8 localId, u16 graphicsId, u8 movementType, u16 trainerType, u16 trainerRange, const u8 *script, bool8 blocksMovement, u16 x, u16 y)
{
    struct ObjectEventTemplate object = {0};

    object.localId = localId;
    object.graphicsId = graphicsId;
    object.kind = OBJ_KIND_NORMAL;
    object.x = x;
    object.y = y;
    object.elevation = 0;
    object.movementType = movementType;
    object.trainerType = trainerType;
    object.trainerRange_berryTreeId = trainerRange;
    object.script = script;
    return GeneratedDungeonWorkspace_SetObject(workspace, index, &object, blocksMovement);
}

static bool32 SetTerrain(struct GeneratedDungeonWorkspace *workspace, struct GeneratedDungeonRngStreams *rng)
{
    u16 impassableCount = 0;
    u16 x;
    u16 y;

    for (y = 0; y < GENERATED_OCEAN_HEIGHT; y++)
    {
        for (x = 0; x < GENERATED_OCEAN_WIDTH; x++)
        {
            u16 roll = LocalRandom(&rng->values[GENERATED_DUNGEON_RNG_TOPOLOGY]);
            u16 cell = (roll & 7) == 0
                ? GENERATED_OCEAN_CELL_IMPASSABLE_WATER
                : (roll & 3) == 0
                    ? GENERATED_OCEAN_CELL_ROUGH_WATER
                    : GENERATED_OCEAN_CELL_CALM_WATER;

            if (y == GENERATED_OCEAN_ENDPOINT_Y || IsEndpoint(x, y))
                cell = GENERATED_OCEAN_CELL_CALM_WATER;
            else if (cell == GENERATED_OCEAN_CELL_IMPASSABLE_WATER)
                impassableCount++;
            if (!GeneratedDungeonWorkspace_SetCell(workspace, x, y, cell))
                return FALSE;
        }
    }

    // A generated run always contains terrain that changes routing, even for
    // an unusually sparse deterministic stream. The central calm lane keeps
    // both recorded departures reachable.
    if (impassableCount == 0
     && !GeneratedDungeonWorkspace_SetCell(workspace, 10, GENERATED_OCEAN_ENDPOINT_Y - 2,
                                           GENERATED_OCEAN_CELL_IMPASSABLE_WATER))
        return FALSE;
    return TRUE;
}

static bool32 SetGeneratedObjects(struct GeneratedDungeonWorkspace *workspace, struct GeneratedDungeonRngStreams *rng)
{
    u8 i;
    u8 trainerOrder[GENERATED_OCEAN_TRAINER_COUNT] = {0, 1, 2, 3};

    for (i = 0; i < GENERATED_OCEAN_TRAINER_COUNT; i++)
    {
        u8 swapIndex = i + LocalRandom(&rng->values[GENERATED_DUNGEON_RNG_TRAINERS]) % (GENERATED_OCEAN_TRAINER_COUNT - i);
        u8 trainerIndex;
        u16 x;
        u16 y;
        u8 temp = trainerOrder[i];

        trainerOrder[i] = trainerOrder[swapIndex];
        trainerOrder[swapIndex] = temp;
        trainerIndex = trainerOrder[i];
        if (!FindObjectPosition(workspace, &rng->values[GENERATED_DUNGEON_RNG_TRAINERS], i, &x, &y)
         || !SetObject(workspace, i, GENERATED_OCEAN_TRAINER_LOCAL_ID_BASE + i,
                       sTrainerGraphics[trainerIndex], MOVEMENT_TYPE_LOOK_AROUND,
                       TRAINER_TYPE_NORMAL, GENERATED_OCEAN_TRAINER_SIGHT_RANGE,
                       sTrainerScripts[trainerIndex], TRUE, x, y))
            return FALSE;
    }
    return TRUE;
}

static bool32 Generate(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonRngStreams *rng, u8 attempt, struct GeneratedDungeonWorkspace *workspace)
{
    (void)provider;
    (void)attempt;

    return rng != NULL
        && GeneratedDungeonWorkspace_SetDimensions(workspace, GENERATED_OCEAN_WIDTH, GENERATED_OCEAN_HEIGHT)
        && GeneratedDungeonWorkspace_SetObjectCount(workspace, GENERATED_OCEAN_OBJECT_COUNT)
        && SetTerrain(workspace, rng)
        && GeneratedDungeonWorkspace_SetSpawn(workspace, GENERATED_OCEAN_SPAWN_X, GENERATED_OCEAN_ENDPOINT_Y)
        && GeneratedDungeonWorkspace_SetOriginEndpoint(workspace, GENERATED_OCEAN_ORIGIN_X, GENERATED_OCEAN_ENDPOINT_Y)
        && GeneratedDungeonWorkspace_SetDestinationEndpoint(workspace, GENERATED_OCEAN_DESTINATION_X, GENERATED_OCEAN_ENDPOINT_Y)
        && SetGeneratedObjects(workspace, rng);
}

static bool32 Fallback(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonWorkspace *workspace)
{
    static const struct GeneratedDungeonPoint sImpassablePoints[] =
    {
        {10, 4}, {23, 6}, {38, 18}, {51, 3},
    };
    static const struct GeneratedDungeonPoint sTrainerPoints[GENERATED_OCEAN_TRAINER_COUNT] =
    {
        {13, 16}, {27, 3}, {42, 8}, {54, 19},
    };
    u16 x;
    u16 y;
    u8 i;

    (void)provider;
    if (!GeneratedDungeonWorkspace_SetDimensions(workspace, GENERATED_OCEAN_WIDTH, GENERATED_OCEAN_HEIGHT)
     || !GeneratedDungeonWorkspace_SetObjectCount(workspace, GENERATED_OCEAN_OBJECT_COUNT)
     || !GeneratedDungeonWorkspace_SetSpawn(workspace, GENERATED_OCEAN_SPAWN_X, GENERATED_OCEAN_ENDPOINT_Y)
     || !GeneratedDungeonWorkspace_SetOriginEndpoint(workspace, GENERATED_OCEAN_ORIGIN_X, GENERATED_OCEAN_ENDPOINT_Y)
     || !GeneratedDungeonWorkspace_SetDestinationEndpoint(workspace, GENERATED_OCEAN_DESTINATION_X, GENERATED_OCEAN_ENDPOINT_Y))
        return FALSE;

    for (y = 0; y < GENERATED_OCEAN_HEIGHT; y++)
        for (x = 0; x < GENERATED_OCEAN_WIDTH; x++)
            if (!GeneratedDungeonWorkspace_SetCell(workspace, x, y, GENERATED_OCEAN_CELL_CALM_WATER))
                return FALSE;

    for (i = 0; i < ARRAY_COUNT(sImpassablePoints); i++)
        if (!GeneratedDungeonWorkspace_SetCell(workspace, sImpassablePoints[i].x, sImpassablePoints[i].y,
                                               GENERATED_OCEAN_CELL_IMPASSABLE_WATER))
            return FALSE;

    for (i = 0; i < GENERATED_OCEAN_TRAINER_COUNT; i++)
    {
        if (!SetObject(workspace, i, GENERATED_OCEAN_TRAINER_LOCAL_ID_BASE + i,
                       sTrainerGraphics[i], MOVEMENT_TYPE_LOOK_AROUND,
                       TRAINER_TYPE_NORMAL, 3, sTrainerScripts[i], TRUE,
                       sTrainerPoints[i].x, sTrainerPoints[i].y))
            return FALSE;
    }
    return TRUE;
}

static const struct GeneratedDungeonProvider sProvider =
{
    .providerId = GENERATED_OCEAN_PROVIDER_ID,
    .generationVersion = GENERATED_OCEAN_GENERATION_VERSION,
    .mapGroup = MAP_GROUP(MAP_AQUA_HIDEOUT_UNUSED_RUBY_MAP2),
    .mapNum = MAP_NUM(MAP_AQUA_HIDEOUT_UNUSED_RUBY_MAP2),
    .maxWorkspaceCells = GENERATED_OCEAN_WIDTH * GENERATED_OCEAN_HEIGHT,
    .maxGeneratedObjects = GENERATED_OCEAN_OBJECT_COUNT,
    .translateCell = TranslateCell,
    .canMove = CanMove,
    .generate = Generate,
    .fallback = Fallback,
};

static bool32 GetTrainerProgressBit(u8 localId, u8 *bit)
{
    if (bit == NULL
     || localId < GENERATED_OCEAN_TRAINER_LOCAL_ID_BASE
     || localId >= GENERATED_OCEAN_TRAINER_LOCAL_ID_BASE + GENERATED_OCEAN_TRAINER_COUNT)
        return FALSE;

    *bit = localId - GENERATED_OCEAN_TRAINER_LOCAL_ID_BASE;
    return TRUE;
}

bool32 GeneratedOcean_Init(void)
{
    if (sInitialized)
        return TRUE;
    if (!GeneratedDungeon_RegisterProviders(&sProvider, 1))
        return FALSE;

    sInitialized = TRUE;
    return TRUE;
}

bool32 GeneratedOcean_IsActive(void)
{
    return gSaveBlock1Ptr->location.mapGroup == sProvider.mapGroup
        && gSaveBlock1Ptr->location.mapNum == sProvider.mapNum
        && GeneratedDungeon_IsActiveMap(sProvider.mapGroup, sProvider.mapNum);
}

bool32 GeneratedOcean_GetTrainerDefeated(u8 localId, bool32 *defeated)
{
    const struct GeneratedDungeonSaveRecord *record;
    u8 bit;

    if (defeated == NULL)
        return FALSE;
    *defeated = FALSE;
    if (!GeneratedOcean_IsActive() || !GetTrainerProgressBit(localId, &bit))
        return FALSE;

    record = (const struct GeneratedDungeonSaveRecord *)gSaveBlock1Ptr->generatedDungeon;
    return GeneratedDungeonProgress_TryGet(record->progress, bit, defeated);
}

bool32 GeneratedOcean_SetTrainerDefeated(u8 localId)
{
    struct GeneratedDungeonSaveRecord *record;
    u8 bit;

    if (!GeneratedOcean_IsActive() || !GetTrainerProgressBit(localId, &bit))
        return FALSE;

    record = (struct GeneratedDungeonSaveRecord *)gSaveBlock1Ptr->generatedDungeon;
    if (!GeneratedDungeonProgress_TrySet(&record->progress, bit))
        return FALSE;
    GeneratedDungeonRecordFinalize(record);
    return TRUE;
}

bool8 GeneratedOcean_TryBegin(const struct SurfEdgeExit *exit)
{
    struct WarpData origin;
    struct WarpData destination;

    if (exit == NULL
     || exit->sourceMap != SurfEdgeExit_EncodeMap(gSaveBlock1Ptr->location.mapGroup, gSaveBlock1Ptr->location.mapNum)
     || exit->exitEdge <= DIR_NONE
     || exit->exitEdge >= CARDINAL_DIRECTION_COUNT)
        return FALSE;

    origin = gSaveBlock1Ptr->location;
    origin.warpId = WARP_ID_NONE;
    origin.x = gSaveBlock1Ptr->pos.x;
    origin.y = gSaveBlock1Ptr->pos.y;
    destination.mapGroup = MAP_GROUP(exit->targetMap);
    destination.mapNum = MAP_NUM(exit->targetMap);
    destination.warpId = WARP_ID_NONE;
    destination.x = exit->targetX;
    destination.y = exit->targetY;
    if (!GeneratedDungeon_BeginRun(sProvider.providerId, sProvider.generationVersion, Random32(),
                                   &origin, GetOppositeDirection(exit->exitEdge),
                                   &destination, exit->targetFacing))
        return FALSE;

    StoreInitialPlayerAvatarState();
    SetWarpDestination(sProvider.mapGroup, sProvider.mapNum, WARP_ID_NONE,
                       GENERATED_OCEAN_SPAWN_X, GENERATED_OCEAN_ENDPOINT_Y);
    SetInitialPlayerAvatarStateFacingOverride(exit->exitEdge);
    DoWarp();
    return TRUE;
}

static bool32 Depart(bool32 toDestination)
{
    if (!GeneratedOcean_IsActive())
        return FALSE;

    StoreInitialPlayerAvatarState();
    if (!(toDestination ? GeneratedDungeon_DepartToDestination() : GeneratedDungeon_DepartToOrigin()))
        return FALSE;
    DoWarp();
    return TRUE;
}

void GeneratedOcean_DepartToOrigin(void)
{
    (void)Depart(FALSE);
}

void GeneratedOcean_DepartToDestination(void)
{
    (void)Depart(TRUE);
}
