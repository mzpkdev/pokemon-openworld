#ifndef GUARD_DEBUG_FIELD_MOVE_PROBE_H
#define GUARD_DEBUG_FIELD_MOVE_PROBE_H

#ifdef DEBUG

enum DebugFieldMoveProbeStatus
{
    DEBUG_FIELD_MOVE_PROBE_IDLE,
    DEBUG_FIELD_MOVE_PROBE_PENDING,
    DEBUG_FIELD_MOVE_PROBE_SUCCESS,
    DEBUG_FIELD_MOVE_PROBE_ERROR,
};

struct DebugFieldMoveProbeRequest
{
    u32 requestId;
    u16 fieldMove;
    u8 status;
    u8 reserved;
};

struct DebugFieldMoveProbeResult
{
    u32 requestId;
    u16 fieldMove;
    u8 unlocked;
    u8 status;
};

extern struct DebugFieldMoveProbeRequest gFieldMoveProbeRequest;
extern struct DebugFieldMoveProbeResult gFieldMoveProbeResult;

void DebugFieldMoveProbe_Update(void);

#endif // DEBUG

#endif // GUARD_DEBUG_FIELD_MOVE_PROBE_H
