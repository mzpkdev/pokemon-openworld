#ifndef GUARD_FOUNDATION_MAP_LOAD_H
#define GUARD_FOUNDATION_MAP_LOAD_H

#ifdef DEBUG

enum FoundationLoadStatus
{
    FOUNDATION_LOAD_IDLE,
    FOUNDATION_LOAD_PENDING,
    FOUNDATION_LOAD_RUNNING,
    FOUNDATION_LOAD_SUCCESS,
    FOUNDATION_LOAD_ERROR,
};

enum FoundationLoadPhase
{
    FOUNDATION_LOAD_PHASE_NONE,
    FOUNDATION_LOAD_PHASE_VALIDATE,
    FOUNDATION_LOAD_PHASE_PREPARE,
    FOUNDATION_LOAD_PHASE_WARP,
    FOUNDATION_LOAD_PHASE_MAP_DATA,
    FOUNDATION_LOAD_PHASE_RESET,
    FOUNDATION_LOAD_PHASE_RESUME,
    FOUNDATION_LOAD_PHASE_EVENTS,
    FOUNDATION_LOAD_PHASE_GRAPHICS,
    FOUNDATION_LOAD_PHASE_CALLBACK,
    FOUNDATION_LOAD_PHASE_FIELD_READY,
};

enum FoundationLoadError
{
    FOUNDATION_LOAD_ERROR_NONE,
    FOUNDATION_LOAD_ERROR_MAP_GROUP,
    FOUNDATION_LOAD_ERROR_MAP_GROUP_UNAVAILABLE,
    FOUNDATION_LOAD_ERROR_MAP_NUM,
    FOUNDATION_LOAD_ERROR_MAP_HEADER,
    FOUNDATION_LOAD_ERROR_MAP_LAYOUT,
    FOUNDATION_LOAD_ERROR_COORDINATES,
    FOUNDATION_LOAD_ERROR_FLAGS,
    FOUNDATION_LOAD_ERROR_NOT_READY,
};

struct FoundationMapLoadRequest
{
    u32 requestId;
    u16 mapGroup;
    u16 mapNum;
    s16 x;
    s16 y;
    u8 suppressScripts;
    u8 suppressEvents;
    u8 status;
    u8 reserved;
};

struct FoundationMapLoadResult
{
    u32 requestId;
    u16 mapGroup;
    u16 mapNum;
    u8 status;
    u8 phase;
    u16 error;
};

extern volatile struct FoundationMapLoadRequest gFoundationMapLoadRequest;
extern volatile struct FoundationMapLoadResult gFoundationMapLoadResult;

void FoundationMapLoad_Update(void);
void FoundationMapLoad_ReportPhase(enum FoundationLoadPhase phase);
void FoundationMapLoad_Complete(void);
bool32 FoundationMapLoad_ShouldSuppressScripts(void);
bool32 FoundationMapLoad_ShouldSuppressEvents(void);

#endif // DEBUG

#endif // GUARD_FOUNDATION_MAP_LOAD_H
