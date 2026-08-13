#include "global.h"
#include "overworld.h"
#include "rtc.h"
#include "wild_encounter_time_policy.h"
#include "test/test.h"

TEST("Route 39 policy follows the public apparent-hour override")
{
    struct Time savedLocalTime = gLocalTime;
    u16 savedOverride = SetTimeOfDay(0);

    gLocalTime.hours = 5;
    gLocalTime.minutes = 59;

    SetTimeOfDay(18);
    EXPECT_EQ(GetApparentTimeOfDayMinutes(), 18 * 60);
    EXPECT_EQ(
        ResolveWildEncounterPolicyTime(
            GetApparentTimeOfDayMinutes(), 6 * 60, 18 * 60, TIME_DAY, TIME_NIGHT
        ),
        TIME_NIGHT
    );

    SetTimeOfDay(6);
    EXPECT_EQ(GetApparentTimeOfDayMinutes(), 6 * 60);
    EXPECT_EQ(
        ResolveWildEncounterPolicyTime(
            GetApparentTimeOfDayMinutes(), 6 * 60, 18 * 60, TIME_DAY, TIME_NIGHT
        ),
        TIME_DAY
    );

    SetTimeOfDay(0);
    EXPECT_EQ(GetApparentTimeOfDayMinutes(), 5 * 60 + 59);
    EXPECT_EQ(
        ResolveWildEncounterPolicyTime(
            GetApparentTimeOfDayMinutes(), 6 * 60, 18 * 60, TIME_DAY, TIME_NIGHT
        ),
        TIME_NIGHT
    );

    gLocalTime = savedLocalTime;
    SetTimeOfDay(savedOverride);
}
