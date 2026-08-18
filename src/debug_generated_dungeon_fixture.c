#include "global.h"

#ifdef DEBUG

#include "debug_generated_dungeon_fixture.h"
#include "field_screen_effect.h"
#include "generated_dungeon.h"
#include "main.h"
#include "overworld.h"
#include "constants/maps.h"

#define FIXTURE_WIDTH 20
#define FIXTURE_HEIGHT 20
#define FIXTURE_FLOOR_METATILE 0x201

volatile struct DebugGeneratedDungeonFixtureRequest gDebugGeneratedDungeonFixtureRequest;
volatile struct DebugGeneratedDungeonFixtureResult gDebugGeneratedDungeonFixtureResult;

STATIC_ASSERT(sizeof(struct DebugGeneratedDungeonFixtureRequest) == 12, DebugGeneratedDungeonFixtureRequestSize);
STATIC_ASSERT(offsetof(struct DebugGeneratedDungeonFixtureRequest, status) == 8, DebugGeneratedDungeonFixtureRequestStatusOffset);
STATIC_ASSERT(sizeof(struct DebugGeneratedDungeonFixtureResult) == 16, DebugGeneratedDungeonFixtureResultSize);
STATIC_ASSERT(offsetof(struct DebugGeneratedDungeonFixtureResult, status) == 15, DebugGeneratedDungeonFixtureResultStatusOffset);

static bool8 sActive;
static struct DebugGeneratedDungeonFixtureRequest sRequest;

static bool32 TranslateCell(const struct GeneratedDungeonProvider *provider, u16 cell, u16 *metatile)
{
    if (provider == NULL || metatile == NULL || cell != 0)
        return FALSE;
    *metatile = FIXTURE_FLOOR_METATILE;
    return TRUE;
}

static bool32 CanMove(const struct GeneratedDungeonProvider *provider, const struct GeneratedDungeonWorkspace *workspace, struct GeneratedDungeonPoint from, struct GeneratedDungeonPoint to)
{
    return provider != NULL && workspace != NULL
        && from.x < workspace->width && from.y < workspace->height
        && to.x < workspace->width && to.y < workspace->height;
}

static bool32 Generate(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonRngStreams *rng, u8 attempt, struct GeneratedDungeonWorkspace *workspace)
{
    u16 x;
    u16 y;

    if (provider == NULL || rng == NULL || attempt != 0
     || !GeneratedDungeonWorkspace_SetDimensions(workspace, FIXTURE_WIDTH, FIXTURE_HEIGHT)
     || !GeneratedDungeonWorkspace_SetObjectCount(workspace, 0)
     || !GeneratedDungeonWorkspace_SetSpawn(workspace, 10, 10)
     || !GeneratedDungeonWorkspace_SetOriginEndpoint(workspace, 10, 15)
     || !GeneratedDungeonWorkspace_SetDestinationEndpoint(workspace, 10, 4))
        return FALSE;

    for (y = 0; y < FIXTURE_HEIGHT; y++)
        for (x = 0; x < FIXTURE_WIDTH; x++)
            if (!GeneratedDungeonWorkspace_SetCell(workspace, x, y, 0))
                return FALSE;
    return TRUE;
}

static bool32 Fallback(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonWorkspace *workspace)
{
    struct GeneratedDungeonRngStreams rng = {0};

    return Generate(provider, &rng, 0, workspace);
}

static const struct GeneratedDungeonProvider sProvider =
{
    .providerId = DEBUG_GENERATED_DUNGEON_FIXTURE_PROVIDER_ID,
    .generationVersion = DEBUG_GENERATED_DUNGEON_FIXTURE_GENERATION_VERSION,
    .mapGroup = MAP_GROUP(MAP_ROUTE101),
    .mapNum = MAP_NUM(MAP_ROUTE101),
    .maxWorkspaceCells = FIXTURE_WIDTH * FIXTURE_HEIGHT,
    .maxGeneratedObjects = 0,
    .translateCell = TranslateCell,
    .canMove = CanMove,
    .generate = Generate,
    .fallback = Fallback,
};

static bool32 IsReady(void)
{
    return gSaveBlock1Ptr != NULL
        && gSaveBlock2Ptr != NULL
        && gMain.callback1 == CB1_Overworld
        && gMain.callback2 == CB2_Overworld
        && gMain.state == 0
        && !gMain.inBattle
        && !gLinkTransferringData;
}

static void Publish(u8 status, u8 error)
{
    gDebugGeneratedDungeonFixtureResult.requestId = sRequest.requestId;
    gDebugGeneratedDungeonFixtureResult.seed = sRequest.seed;
    gDebugGeneratedDungeonFixtureResult.providerId = sProvider.providerId;
    gDebugGeneratedDungeonFixtureResult.generationVersion = sProvider.generationVersion;
    gDebugGeneratedDungeonFixtureResult.mapGroup = sProvider.mapGroup;
    gDebugGeneratedDungeonFixtureResult.mapNum = sProvider.mapNum;
    gDebugGeneratedDungeonFixtureResult.error = error;
    // Status is the host-visible commit field and must be stored last.
    gDebugGeneratedDungeonFixtureResult.status = status;
}

void DebugGeneratedDungeonFixture_Init(void)
{
    GeneratedDungeon_DebugRegisterProviders(&sProvider, 1);
}

void DebugGeneratedDungeonFixture_Update(void)
{
    struct WarpData origin;
    struct DebugGeneratedDungeonFixtureRequest request;

    if (sActive)
    {
        if (gMain.callback1 == CB1_Overworld && gMain.callback2 == CB2_Overworld && gMain.state == 0)
        {
            sActive = FALSE;
            gDebugGeneratedDungeonFixtureRequest.status = DEBUG_GENERATED_DUNGEON_FIXTURE_SUCCESS;
            Publish(DEBUG_GENERATED_DUNGEON_FIXTURE_SUCCESS, DEBUG_GENERATED_DUNGEON_FIXTURE_ERROR_NONE);
        }
        return;
    }
    if (gDebugGeneratedDungeonFixtureRequest.status != DEBUG_GENERATED_DUNGEON_FIXTURE_PENDING)
        return;

    request = gDebugGeneratedDungeonFixtureRequest;
    sRequest = request;
    if (request.reserved[0] != 0 || request.reserved[1] != 0 || request.reserved[2] != 0)
    {
        gDebugGeneratedDungeonFixtureRequest.status = DEBUG_GENERATED_DUNGEON_FIXTURE_ERROR;
        Publish(DEBUG_GENERATED_DUNGEON_FIXTURE_ERROR, DEBUG_GENERATED_DUNGEON_FIXTURE_ERROR_REQUEST);
        return;
    }
    if (!IsReady())
    {
        gDebugGeneratedDungeonFixtureRequest.status = DEBUG_GENERATED_DUNGEON_FIXTURE_ERROR;
        Publish(DEBUG_GENERATED_DUNGEON_FIXTURE_ERROR, DEBUG_GENERATED_DUNGEON_FIXTURE_ERROR_NOT_READY);
        return;
    }
    origin = gSaveBlock1Ptr->location;
    origin.warpId = WARP_ID_NONE;
    origin.x = gSaveBlock1Ptr->pos.x;
    origin.y = gSaveBlock1Ptr->pos.y;
    if (!GeneratedDungeon_BeginRun(sProvider.providerId, sProvider.generationVersion, request.seed, &origin, DIR_SOUTH, &origin, DIR_SOUTH))
    {
        gDebugGeneratedDungeonFixtureRequest.status = DEBUG_GENERATED_DUNGEON_FIXTURE_ERROR;
        Publish(DEBUG_GENERATED_DUNGEON_FIXTURE_ERROR, DEBUG_GENERATED_DUNGEON_FIXTURE_ERROR_BEGIN);
        return;
    }

    gDebugGeneratedDungeonFixtureRequest.status = DEBUG_GENERATED_DUNGEON_FIXTURE_RUNNING;
    Publish(DEBUG_GENERATED_DUNGEON_FIXTURE_RUNNING, DEBUG_GENERATED_DUNGEON_FIXTURE_ERROR_NONE);
    sActive = TRUE;
    SetWarpDestination(sProvider.mapGroup, sProvider.mapNum, WARP_ID_NONE, 10, 10);
    WarpIntoMap();
    gFieldCallback = FieldCB_WarpExitFadeFromBlack;
    SetMainCallback2(CB2_LoadMap);
}

#endif // DEBUG
