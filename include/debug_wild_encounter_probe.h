#ifndef GUARD_DEBUG_WILD_ENCOUNTER_PROBE_H
#define GUARD_DEBUG_WILD_ENCOUNTER_PROBE_H

#ifdef DEBUG

enum DebugWildEncounterProbeStatus
{
    DEBUG_WILD_ENCOUNTER_PROBE_IDLE,
    DEBUG_WILD_ENCOUNTER_PROBE_PENDING,
    DEBUG_WILD_ENCOUNTER_PROBE_SUCCESS,
    DEBUG_WILD_ENCOUNTER_PROBE_ERROR,
};

enum DebugWildEncounterProbeError
{
    DEBUG_WILD_ENCOUNTER_PROBE_ERROR_NONE,
    DEBUG_WILD_ENCOUNTER_PROBE_ERROR_REQUEST,
    DEBUG_WILD_ENCOUNTER_PROBE_ERROR_HEADER,
    DEBUG_WILD_ENCOUNTER_PROBE_ERROR_PROFILE,
    DEBUG_WILD_ENCOUNTER_PROBE_ERROR_ENTRY,
};

struct DebugWildEncounterProbeRequest
{
    u32 requestId;
    u16 entryIndex;
    u8 area;
    u8 fishingRod;
    u8 reserved[3];
    u8 status;
};

struct DebugWildEncounterProbeResult
{
    u32 requestId;
    u16 headerId;
    u16 entryIndex;
    u16 entryCount;
    u16 totalWeight;
    u16 species;
    u16 weight;
    u8 area;
    u8 fishingRod;
    u8 trainerRating;
    u8 reserved;
    u8 minLevel;
    u8 maxLevel;
    u8 error;
    u8 status;
};

extern struct DebugWildEncounterProbeRequest gWildEncounterProbeRequest;
extern struct DebugWildEncounterProbeResult gWildEncounterProbeResult;

void DebugWildEncounterProbe_Update(void);

#endif // DEBUG

#endif // GUARD_DEBUG_WILD_ENCOUNTER_PROBE_H
