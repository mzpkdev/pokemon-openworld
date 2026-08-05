#ifdef DEBUG

#include "global.h"
#include "integrity_map_load.h"
#include "field_screen_effect.h"
#include "load_save.h"
#include "main.h"
#include "overworld.h"
#include "constants/maps.h"
#include "data/map_group_count.h"

extern const struct MapHeader *const *const gMapGroups[];

volatile struct IntegrityMapLoadRequest gIntegrityMapLoadRequest;
volatile struct IntegrityMapLoadResult gIntegrityMapLoadResult;

STATIC_ASSERT(sizeof(struct IntegrityMapLoadRequest) == 16, IntegrityMapLoadRequestSize);
STATIC_ASSERT(offsetof(struct IntegrityMapLoadRequest, status) == 14, IntegrityMapLoadRequestStatusOffset);
STATIC_ASSERT(sizeof(struct IntegrityMapLoadResult) == 12, IntegrityMapLoadResultSize);
STATIC_ASSERT(offsetof(struct IntegrityMapLoadResult, status) == 8, IntegrityMapLoadResultStatusOffset);

static bool8 sIntegrityMapLoadActive;
static bool8 sSuppressScripts;
static bool8 sSuppressEvents;
static struct IntegrityMapLoadRequest sRequest;

static bool32 IntegrityMapLoad_IsReady(void)
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

static void PublishResult(u8 status, enum IntegrityLoadPhase phase, enum IntegrityLoadError error)
{
    // Status is the commit field. Keep it last so a paused host never observes
    // a terminal result paired with stale payload fields.
    gIntegrityMapLoadResult.requestId = sRequest.requestId;
    gIntegrityMapLoadResult.mapGroup = sRequest.mapGroup;
    gIntegrityMapLoadResult.mapNum = sRequest.mapNum;
    gIntegrityMapLoadResult.phase = phase;
    gIntegrityMapLoadResult.error = error;
    gIntegrityMapLoadResult.status = status;
}

static enum IntegrityLoadError ValidateRequest(const struct IntegrityMapLoadRequest *request)
{
    const struct MapHeader *mapHeader;
    const struct MapLayout *mapLayout;

    if (request->mapGroup >= MAP_GROUPS_COUNT)
        return INTEGRITY_LOAD_ERROR_MAP_GROUP;
    if (gMapGroups[request->mapGroup] == NULL)
        return INTEGRITY_LOAD_ERROR_MAP_GROUP_UNAVAILABLE;
    if (request->mapNum >= MAP_GROUP_COUNT[request->mapGroup])
        return INTEGRITY_LOAD_ERROR_MAP_NUM;

    mapHeader = gMapGroups[request->mapGroup][request->mapNum];
    if (mapHeader == NULL)
        return INTEGRITY_LOAD_ERROR_MAP_HEADER;
    mapLayout = mapHeader->mapLayout;
    if (mapLayout == NULL || mapLayout->width <= 0 || mapLayout->height <= 0)
        return INTEGRITY_LOAD_ERROR_MAP_LAYOUT;
    if (!((request->x == -1 && request->y == -1)
       || (request->x >= 0 && request->y >= 0
        && request->x < mapLayout->width && request->y < mapLayout->height
        && request->x <= 127 && request->y <= 127)))
        return INTEGRITY_LOAD_ERROR_COORDINATES;
    if (request->suppressScripts > TRUE || request->suppressEvents > TRUE || request->reserved != 0)
        return INTEGRITY_LOAD_ERROR_FLAGS;
    if (!IntegrityMapLoad_IsReady())
        return INTEGRITY_LOAD_ERROR_NOT_READY;

    return INTEGRITY_LOAD_ERROR_NONE;
}

void IntegrityMapLoad_Update(void)
{
    struct IntegrityMapLoadRequest request;
    enum IntegrityLoadError error;

    if (sIntegrityMapLoadActive
     || gIntegrityMapLoadRequest.status != INTEGRITY_LOAD_PENDING)
        return;

    // The host commits status last while the emulator is paused. Snapshot the
    // payload once, then acknowledge it before changing any map state.
    request.requestId = gIntegrityMapLoadRequest.requestId;
    request.mapGroup = gIntegrityMapLoadRequest.mapGroup;
    request.mapNum = gIntegrityMapLoadRequest.mapNum;
    request.x = gIntegrityMapLoadRequest.x;
    request.y = gIntegrityMapLoadRequest.y;
    request.suppressScripts = gIntegrityMapLoadRequest.suppressScripts;
    request.suppressEvents = gIntegrityMapLoadRequest.suppressEvents;
    request.status = gIntegrityMapLoadRequest.status;
    request.reserved = gIntegrityMapLoadRequest.reserved;

    sRequest = request;
    error = ValidateRequest(&sRequest);
    if (error != INTEGRITY_LOAD_ERROR_NONE)
    {
        PublishResult(INTEGRITY_LOAD_ERROR, INTEGRITY_LOAD_PHASE_VALIDATE, error);
        gIntegrityMapLoadRequest.status = INTEGRITY_LOAD_ERROR;
        return;
    }

    PublishResult(INTEGRITY_LOAD_RUNNING, INTEGRITY_LOAD_PHASE_PREPARE, INTEGRITY_LOAD_ERROR_NONE);
    gIntegrityMapLoadRequest.status = INTEGRITY_LOAD_RUNNING;
    sSuppressScripts = request.suppressScripts;
    sSuppressEvents = request.suppressEvents;
    sIntegrityMapLoadActive = TRUE;

    SetWarpDestination(request.mapGroup, request.mapNum, WARP_ID_NONE, request.x, request.y);
    IntegrityMapLoad_ReportPhase(INTEGRITY_LOAD_PHASE_WARP);
    WarpIntoMap();
    gFieldCallback = FieldCB_WarpExitFadeFromBlack;
    gFieldCallback2 = NULL;
    SetMainCallback2(CB2_LoadMap);
}

void IntegrityMapLoad_ReportPhase(enum IntegrityLoadPhase phase)
{
    if (sIntegrityMapLoadActive)
        gIntegrityMapLoadResult.phase = phase;
}

void IntegrityMapLoad_Complete(void)
{
    if (!sIntegrityMapLoadActive)
        return;

    IntegrityMapLoad_ReportPhase(INTEGRITY_LOAD_PHASE_FIELD_READY);
    PublishResult(INTEGRITY_LOAD_SUCCESS, INTEGRITY_LOAD_PHASE_FIELD_READY, INTEGRITY_LOAD_ERROR_NONE);
    gIntegrityMapLoadRequest.status = INTEGRITY_LOAD_SUCCESS;
    sSuppressScripts = FALSE;
    sSuppressEvents = FALSE;
    sIntegrityMapLoadActive = FALSE;
}

bool32 IntegrityMapLoad_ShouldSuppressScripts(void)
{
    return sIntegrityMapLoadActive && sSuppressScripts;
}

bool32 IntegrityMapLoad_ShouldSuppressEvents(void)
{
    return sIntegrityMapLoadActive && sSuppressEvents;
}

#endif // DEBUG
