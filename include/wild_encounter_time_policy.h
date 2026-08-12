#ifndef GUARD_WILD_ENCOUNTER_TIME_POLICY_H
#define GUARD_WILD_ENCOUNTER_TIME_POLICY_H

#define WILD_ENCOUNTER_TIME_POLICY_NONE 0xFFFF
#define WILD_ENCOUNTER_MINUTES_PER_DAY 1440

static inline unsigned short ResolveApparentTimeMinutes(
    unsigned char rtcHour,
    unsigned char rtcMinute,
    unsigned short hoursOverride)
{
    if (hoursOverride)
        return hoursOverride * 60;
    return rtcHour * 60 + rtcMinute;
}

// Kept independent of project types so the exact runtime boundary resolver can be
// compiled and exercised by the host-side generator tests.
static inline unsigned char ResolveWildEncounterPolicyTime(
    unsigned short minuteOfDay,
    unsigned short dayStartMinutes,
    unsigned short nightStartMinutes,
    unsigned char dayTime,
    unsigned char nightTime)
{
    minuteOfDay %= WILD_ENCOUNTER_MINUTES_PER_DAY;
    if (minuteOfDay >= dayStartMinutes && minuteOfDay < nightStartMinutes)
        return dayTime;
    return nightTime;
}

#endif // GUARD_WILD_ENCOUNTER_TIME_POLICY_H
