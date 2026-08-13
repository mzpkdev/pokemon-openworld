#include "global.h"

#ifdef DEBUG

#include "debug_field_move_probe.h"
#include "field_move.h"
#include "constants/field_move.h"

struct DebugFieldMoveProbeRequest gFieldMoveProbeRequest;
struct DebugFieldMoveProbeResult gFieldMoveProbeResult;

STATIC_ASSERT(sizeof(struct DebugFieldMoveProbeRequest) == 8, DebugFieldMoveProbeRequestSize);
STATIC_ASSERT(sizeof(struct DebugFieldMoveProbeResult) == 8, DebugFieldMoveProbeResultSize);

void DebugFieldMoveProbe_Update(void)
{
    struct DebugFieldMoveProbeRequest request;

    if (gFieldMoveProbeRequest.status != DEBUG_FIELD_MOVE_PROBE_PENDING)
        return;

    request = gFieldMoveProbeRequest;
    gFieldMoveProbeResult = (struct DebugFieldMoveProbeResult)
    {
        .requestId = request.requestId,
        .fieldMove = request.fieldMove,
        .status = DEBUG_FIELD_MOVE_PROBE_ERROR,
    };

    if (request.reserved != 0 || request.fieldMove >= FIELD_MOVES_COUNT)
    {
        gFieldMoveProbeRequest.status = DEBUG_FIELD_MOVE_PROBE_ERROR;
        return;
    }

    gFieldMoveProbeResult.unlocked = IsFieldMoveUnlocked(request.fieldMove);
    gFieldMoveProbeRequest.status = DEBUG_FIELD_MOVE_PROBE_SUCCESS;
    gFieldMoveProbeResult.status = DEBUG_FIELD_MOVE_PROBE_SUCCESS;
}

#endif // DEBUG
