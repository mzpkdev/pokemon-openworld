#ifdef DEBUG

#include "global.h"
#include "foundation_map_load.h"
#include "field_screen_effect.h"
#include "load_save.h"
#include "main.h"
#include "overworld.h"
#include "constants/maps.h"
#include "data/map_group_count.h"

extern const struct MapHeader *const *const gMapGroups[];

volatile struct FoundationMapLoadRequest gFoundationMapLoadRequest;
volatile struct FoundationMapLoadResult gFoundationMapLoadResult;

STATIC_ASSERT(sizeof(struct FoundationMapLoadRequest) == 16, FoundationMapLoadRequestSize);
STATIC_ASSERT(offsetof(struct FoundationMapLoadRequest, status) == 14, FoundationMapLoadRequestStatusOffset);
STATIC_ASSERT(sizeof(struct FoundationMapLoadResult) == 12, FoundationMapLoadResultSize);
STATIC_ASSERT(offsetof(struct FoundationMapLoadResult, status) == 8, FoundationMapLoadResultStatusOffset);

static bool8 sFoundationMapLoadActive;
static bool8 sSuppressScripts;
static bool8 sSuppressEvents;
static struct FoundationMapLoadRequest sRequest;

static bool32 FoundationMapLoad_IsReady(void)
{
    // Only replace callbacks from the settled, local overworld. In particular,
    // CB2_OverworldBasic is also used during battle transitions and is not a
    // safe map-load boundary.
    return gSaveBlock1Ptr != NULL
        && gSaveBlock2Ptr != NULL
        && gMain.callback1 == CB1_Overworld
        && gMain.callback2 == CB2_Overworld
        && gMain.state == 0
        && !gMain.inBattle
        && !gLinkTransferringData;
}

static void PublishResult(u8 status, enum FoundationLoadPhase phase, enum FoundationLoadError error)
{
    // Status is the commit field. Keep it last so a paused host never observes
    // a terminal result paired with stale payload fields.
    gFoundationMapLoadResult.requestId = sRequest.requestId;
    gFoundationMapLoadResult.mapGroup = sRequest.mapGroup;
    gFoundationMapLoadResult.mapNum = sRequest.mapNum;
    gFoundationMapLoadResult.phase = phase;
    gFoundationMapLoadResult.error = error;
    gFoundationMapLoadResult.status = status;
}

static enum FoundationLoadError ValidateRequest(const struct FoundationMapLoadRequest *request)
{
    const struct MapHeader *mapHeader;
    const struct MapLayout *mapLayout;

    if (request->mapGroup >= MAP_GROUPS_COUNT)
        return FOUNDATION_LOAD_ERROR_MAP_GROUP;
    if (gMapGroups[request->mapGroup] == NULL)
        return FOUNDATION_LOAD_ERROR_MAP_GROUP_UNAVAILABLE;
    if (request->mapNum >= MAP_GROUP_COUNT[request->mapGroup])
        return FOUNDATION_LOAD_ERROR_MAP_NUM;

    mapHeader = gMapGroups[request->mapGroup][request->mapNum];
    if (mapHeader == NULL)
        return FOUNDATION_LOAD_ERROR_MAP_HEADER;
    mapLayout = mapHeader->mapLayout;
    if (mapLayout == NULL || mapLayout->width <= 0 || mapLayout->height <= 0)
        return FOUNDATION_LOAD_ERROR_MAP_LAYOUT;
    if (!((request->x == -1 && request->y == -1)
       || (request->x >= 0 && request->y >= 0
        && request->x < mapLayout->width && request->y < mapLayout->height
        && request->x <= 127 && request->y <= 127)))
        return FOUNDATION_LOAD_ERROR_COORDINATES;
    if (request->suppressScripts > TRUE || request->suppressEvents > TRUE || request->reserved != 0)
        return FOUNDATION_LOAD_ERROR_FLAGS;
    if (!FoundationMapLoad_IsReady())
        return FOUNDATION_LOAD_ERROR_NOT_READY;

    return FOUNDATION_LOAD_ERROR_NONE;
}

void FoundationMapLoad_Update(void)
{
    struct FoundationMapLoadRequest request;
    enum FoundationLoadError error;

    if (sFoundationMapLoadActive
     || gFoundationMapLoadRequest.status != FOUNDATION_LOAD_PENDING)
        return;

    // The host commits status last while the emulator is paused. Snapshot the
    // payload once, then acknowledge it before changing any map state.
    request.requestId = gFoundationMapLoadRequest.requestId;
    request.mapGroup = gFoundationMapLoadRequest.mapGroup;
    request.mapNum = gFoundationMapLoadRequest.mapNum;
    request.x = gFoundationMapLoadRequest.x;
    request.y = gFoundationMapLoadRequest.y;
    request.suppressScripts = gFoundationMapLoadRequest.suppressScripts;
    request.suppressEvents = gFoundationMapLoadRequest.suppressEvents;
    request.status = gFoundationMapLoadRequest.status;
    request.reserved = gFoundationMapLoadRequest.reserved;

    sRequest = request;
    error = ValidateRequest(&sRequest);
    if (error != FOUNDATION_LOAD_ERROR_NONE)
    {
        PublishResult(FOUNDATION_LOAD_ERROR, FOUNDATION_LOAD_PHASE_VALIDATE, error);
        gFoundationMapLoadRequest.status = FOUNDATION_LOAD_ERROR;
        return;
    }

    PublishResult(FOUNDATION_LOAD_RUNNING, FOUNDATION_LOAD_PHASE_PREPARE, FOUNDATION_LOAD_ERROR_NONE);
    gFoundationMapLoadRequest.status = FOUNDATION_LOAD_RUNNING;
    sSuppressScripts = request.suppressScripts;
    sSuppressEvents = request.suppressEvents;
    sFoundationMapLoadActive = TRUE;

    SetWarpDestination(request.mapGroup, request.mapNum, WARP_ID_NONE, request.x, request.y);
    FoundationMapLoad_ReportPhase(FOUNDATION_LOAD_PHASE_WARP);
    WarpIntoMap();
    gFieldCallback = FieldCB_WarpExitFadeFromBlack;
    gFieldCallback2 = NULL;
    SetMainCallback2(CB2_LoadMap);
}

void FoundationMapLoad_ReportPhase(enum FoundationLoadPhase phase)
{
    if (sFoundationMapLoadActive)
        gFoundationMapLoadResult.phase = phase;
}

void FoundationMapLoad_Complete(void)
{
    if (!sFoundationMapLoadActive)
        return;

    FoundationMapLoad_ReportPhase(FOUNDATION_LOAD_PHASE_FIELD_READY);
    PublishResult(FOUNDATION_LOAD_SUCCESS, FOUNDATION_LOAD_PHASE_FIELD_READY, FOUNDATION_LOAD_ERROR_NONE);
    gFoundationMapLoadRequest.status = FOUNDATION_LOAD_SUCCESS;
    sSuppressScripts = FALSE;
    sSuppressEvents = FALSE;
    sFoundationMapLoadActive = FALSE;
}

bool32 FoundationMapLoad_ShouldSuppressScripts(void)
{
    return sFoundationMapLoadActive && sSuppressScripts;
}

bool32 FoundationMapLoad_ShouldSuppressEvents(void)
{
    return sFoundationMapLoadActive && sSuppressEvents;
}

#endif // DEBUG
