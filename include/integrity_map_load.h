#ifndef GUARD_INTEGRITY_MAP_LOAD_H
#define GUARD_INTEGRITY_MAP_LOAD_H

#ifdef DEBUG

enum IntegrityLoadStatus
{
    INTEGRITY_LOAD_IDLE,
    INTEGRITY_LOAD_PENDING,
    INTEGRITY_LOAD_RUNNING,
    INTEGRITY_LOAD_SUCCESS,
    INTEGRITY_LOAD_ERROR,
};

enum IntegrityLoadPhase
{
    INTEGRITY_LOAD_PHASE_NONE,
    INTEGRITY_LOAD_PHASE_VALIDATE,
    INTEGRITY_LOAD_PHASE_PREPARE,
    INTEGRITY_LOAD_PHASE_WARP,
    INTEGRITY_LOAD_PHASE_MAP_DATA,
    INTEGRITY_LOAD_PHASE_RESET,
    INTEGRITY_LOAD_PHASE_RESUME,
    INTEGRITY_LOAD_PHASE_EVENTS,
    INTEGRITY_LOAD_PHASE_GRAPHICS,
    INTEGRITY_LOAD_PHASE_CALLBACK,
    INTEGRITY_LOAD_PHASE_FIELD_READY,
};

enum IntegrityLoadError
{
    INTEGRITY_LOAD_ERROR_NONE,
    INTEGRITY_LOAD_ERROR_MAP_GROUP,
    INTEGRITY_LOAD_ERROR_MAP_GROUP_UNAVAILABLE,
    INTEGRITY_LOAD_ERROR_MAP_NUM,
    INTEGRITY_LOAD_ERROR_MAP_HEADER,
    INTEGRITY_LOAD_ERROR_MAP_LAYOUT,
    INTEGRITY_LOAD_ERROR_COORDINATES,
    INTEGRITY_LOAD_ERROR_FLAGS,
    INTEGRITY_LOAD_ERROR_NOT_READY,
};

struct IntegrityMapLoadRequest
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

struct IntegrityMapLoadResult
{
    u32 requestId;
    u16 mapGroup;
    u16 mapNum;
    u8 status;
    u8 phase;
    u16 error;
};

extern volatile struct IntegrityMapLoadRequest gIntegrityMapLoadRequest;
extern volatile struct IntegrityMapLoadResult gIntegrityMapLoadResult;

void IntegrityMapLoad_Update(void);
void IntegrityMapLoad_ReportPhase(enum IntegrityLoadPhase phase);
void IntegrityMapLoad_Complete(void);
bool32 IntegrityMapLoad_ShouldSuppressScripts(void);
bool32 IntegrityMapLoad_ShouldSuppressEvents(void);

#endif // DEBUG

#endif // GUARD_INTEGRITY_MAP_LOAD_H
