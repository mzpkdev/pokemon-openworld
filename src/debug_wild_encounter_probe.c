#include "global.h"

#ifdef DEBUG

#include "debug_wild_encounter_probe.h"
#include "trainer_rating.h"
#include "wild_encounter.h"

struct DebugWildEncounterProbeRequest gWildEncounterProbeRequest;
struct DebugWildEncounterProbeResult gWildEncounterProbeResult;

STATIC_ASSERT(sizeof(struct DebugWildEncounterProbeRequest) == 12, DebugWildEncounterProbeRequestSize);
STATIC_ASSERT(offsetof(struct DebugWildEncounterProbeRequest, status) == 11, DebugWildEncounterProbeRequestStatusOffset);
STATIC_ASSERT(sizeof(struct DebugWildEncounterProbeResult) == 24, DebugWildEncounterProbeResultSize);
STATIC_ASSERT(offsetof(struct DebugWildEncounterProbeResult, trainerRating) == 18, DebugWildEncounterProbeResultTrainerRatingOffset);
STATIC_ASSERT(offsetof(struct DebugWildEncounterProbeResult, status) == 23, DebugWildEncounterProbeResultStatusOffset);

static void PublishError(const struct DebugWildEncounterProbeRequest *request, enum DebugWildEncounterProbeError error)
{
    gWildEncounterProbeResult = (struct DebugWildEncounterProbeResult)
    {
        .requestId = request->requestId,
        .entryIndex = request->entryIndex,
        .area = request->area,
        .fishingRod = request->fishingRod,
        .error = error,
    };
    gWildEncounterProbeRequest.status = DEBUG_WILD_ENCOUNTER_PROBE_ERROR;
    // Status is the host-visible commit field and must be published last.
    gWildEncounterProbeResult.status = DEBUG_WILD_ENCOUNTER_PROBE_ERROR;
}

void DebugWildEncounterProbe_Update(void)
{
    struct DebugWildEncounterProbeRequest request;
    struct WildEncounterProfileView profile;
    struct WildEncounterSlot entry;
    enum TimeOfDay timeOfDay;
    u16 trainerRating;
    u16 headerId;

    if (gWildEncounterProbeRequest.status != DEBUG_WILD_ENCOUNTER_PROBE_PENDING)
        return;

    request = gWildEncounterProbeRequest;
    if (request.reserved[0] != 0 || request.reserved[1] != 0 || request.reserved[2] != 0
     || request.area > WILD_AREA_HIDDEN
     || (request.area == WILD_AREA_FISHING && request.fishingRod > SUPER_ROD)
     || (request.area != WILD_AREA_FISHING && request.fishingRod != WILD_ENCOUNTER_FISHING_ROD_NONE))
    {
        PublishError(&request, DEBUG_WILD_ENCOUNTER_PROBE_ERROR_REQUEST);
        return;
    }

    if (!TryGetCurrentWildEncounterHeader(&headerId))
    {
        PublishError(&request, DEBUG_WILD_ENCOUNTER_PROBE_ERROR_HEADER);
        return;
    }

    trainerRating = TrainerRating_Get();
    timeOfDay = GetTimeOfDayForEncounters(headerId, request.area);
    if (!TryResolveWildEncounterProfile(headerId, request.area, timeOfDay, request.fishingRod, &profile))
    {
        PublishError(&request, DEBUG_WILD_ENCOUNTER_PROBE_ERROR_PROFILE);
        return;
    }
    if (!TryGetWildEncounterProfileEntry(&profile, request.entryIndex, &entry))
    {
        PublishError(&request, DEBUG_WILD_ENCOUNTER_PROBE_ERROR_ENTRY);
        return;
    }

    gWildEncounterProbeResult = (struct DebugWildEncounterProbeResult)
    {
        .requestId = request.requestId,
        .headerId = headerId,
        .entryIndex = request.entryIndex,
        .entryCount = profile.entryCount,
        .totalWeight = profile.totalWeight,
        .species = entry.species,
        .weight = entry.weight,
        .area = request.area,
        .fishingRod = request.fishingRod,
        .trainerRating = trainerRating,
        .minLevel = entry.minLevel,
        .maxLevel = entry.maxLevel,
        .error = DEBUG_WILD_ENCOUNTER_PROBE_ERROR_NONE,
    };
    gWildEncounterProbeRequest.status = DEBUG_WILD_ENCOUNTER_PROBE_SUCCESS;
    // Status is the host-visible commit field and must be published last.
    gWildEncounterProbeResult.status = DEBUG_WILD_ENCOUNTER_PROBE_SUCCESS;
}

#endif // DEBUG
