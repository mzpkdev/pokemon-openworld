#include "global.h"
#include "event_data.h"
#include "safari_zone.h"
#include "test/test.h"
#include "constants/maps.h"
#include "constants/safari_zone.h"
#include "constants/vars.h"

TEST("Safari facilities select independent session rules at entry")
{
    static const struct
    {
        u8 facility;
        u16 stepLimit;
        bool32 usesKantoRules;
        bool32 publishesFanClubShow;
        u16 sceneVar;
        u16 normalScene;
        u16 midBattleScene;
        u16 entranceMap;
        u8 x;
        u8 y;
    } cases[] =
    {
        {SAFARI_ZONE_FACILITY_HOENN_ROUTE_121, SAFARI_ZONE_HOENN_STEP_LIMIT, FALSE, TRUE, VAR_SAFARI_ZONE_STATE, 1, 1, MAP_ROUTE121_SAFARI_ZONE_ENTRANCE, 2, 5},
        {SAFARI_ZONE_FACILITY_KANTO_FUCHSIA, SAFARI_ZONE_KANTO_STEP_LIMIT, TRUE, FALSE, VAR_MAP_SCENE_FUCHSIA_CITY_SAFARI_ZONE_ENTRANCE, 1, 3, MAP_FUCHSIA_CITY_SAFARI_ZONE_ENTRANCE, 4, 1},
    };

    for (u32 i = 0; i < ARRAY_COUNT(cases); i++)
    {
        struct SafariZoneExitSpec exitSpec;

        ResetSafariZoneFlag();
        EXPECT(EnterSafariModeForFacility(cases[i].facility));
        EXPECT(GetSafariZoneFlag());
        EXPECT_EQ(GetSafariZoneFacility(), cases[i].facility);
        EXPECT_EQ(GetSafariZoneStepLimit(), cases[i].stepLimit);
        EXPECT_EQ(gSafariZoneStepCounter, cases[i].stepLimit);
        EXPECT_EQ(gNumSafariBalls, 30);
        EXPECT_EQ(SafariZoneUsesKantoRules(), cases[i].usesKantoRules);
        EXPECT_EQ(SafariZonePublishesFanClubShow(), cases[i].publishesFanClubShow);
        EXPECT(GetSafariZoneExitSpec(cases[i].facility, &exitSpec));
        EXPECT_EQ(exitSpec.sceneVar, cases[i].sceneVar);
        EXPECT_EQ(exitSpec.normalScene, cases[i].normalScene);
        EXPECT_EQ(exitSpec.midBattleScene, cases[i].midBattleScene);
        EXPECT_EQ(exitSpec.entranceMap, cases[i].entranceMap);
        EXPECT_EQ(exitSpec.x, cases[i].x);
        EXPECT_EQ(exitSpec.y, cases[i].y);
        ResetSafariZoneFlag();
        EXPECT(!GetSafariZoneFlag());
        EXPECT_EQ(GetSafariZoneFacility(), SAFARI_ZONE_FACILITY_NONE);
        EXPECT_EQ(gSafariZoneStepCounter, 0);
        EXPECT_EQ(gNumSafariBalls, 0);
    }
}

TEST("Unknown Safari facility fails closed and clears an active session")
{
    struct SafariZoneExitSpec exitSpec;

    EXPECT(EnterSafariModeForFacility(SAFARI_ZONE_FACILITY_KANTO_FUCHSIA));
    EXPECT(!EnterSafariModeForFacility(0xFF));
    EXPECT(!GetSafariZoneFlag());
    EXPECT_EQ(GetSafariZoneFacility(), SAFARI_ZONE_FACILITY_NONE);
    EXPECT_EQ(GetSafariZoneStepLimit(), 0);
    EXPECT(!SafariZoneUsesKantoRules());
    EXPECT(!SafariZonePublishesFanClubShow());
    EXPECT(!GetSafariZoneExitSpec(SAFARI_ZONE_FACILITY_NONE, &exitSpec));
    EXPECT(!GetSafariZoneExitSpec(0xFF, &exitSpec));
    EXPECT(!GetSafariZoneExitSpec(SAFARI_ZONE_FACILITY_HOENN_ROUTE_121, NULL));
    EXPECT_EQ(gSafariZoneStepCounter, 0);
    EXPECT_EQ(gNumSafariBalls, 0);

    SetSafariZoneFlag();
    EXPECT(!GetSafariZoneFlag());
    ResetSafariZoneFlag();
}

TEST("Invalid South Safari sessions have a fail-closed Hoenn exit decision")
{
    struct SafariZoneExitSpec exitSpec;

    EXPECT(!GetSafariZoneExitSpec(SAFARI_ZONE_FACILITY_NONE, &exitSpec));
    EXPECT(GetSafariZoneExitSpec(SAFARI_ZONE_FACILITY_HOENN_ROUTE_121, &exitSpec));
    EXPECT_EQ(exitSpec.sceneVar, VAR_SAFARI_ZONE_STATE);
    EXPECT_EQ(exitSpec.normalScene, 1);
    EXPECT_EQ(exitSpec.entranceMap, MAP_ROUTE121_SAFARI_ZONE_ENTRANCE);
    EXPECT_EQ(exitSpec.x, 2);
    EXPECT_EQ(exitSpec.y, 5);
}

TEST("Safari session reset clears both admitted facility identities")
{
    static const struct
    {
        u8 facility;
        u16 stepLimit;
    } cases[] =
    {
        {SAFARI_ZONE_FACILITY_HOENN_ROUTE_121, SAFARI_ZONE_HOENN_STEP_LIMIT},
        {SAFARI_ZONE_FACILITY_KANTO_FUCHSIA, SAFARI_ZONE_KANTO_STEP_LIMIT},
    };

    for (u32 i = 0; i < ARRAY_COUNT(cases); i++)
    {
        EXPECT(EnterSafariModeForFacility(cases[i].facility));
        gSafariZoneStepCounter = cases[i].stepLimit;
        ResetSafariZoneFlag();
        EXPECT(!GetSafariZoneFlag());
        EXPECT_EQ(GetSafariZoneFacility(), SAFARI_ZONE_FACILITY_NONE);
        EXPECT_EQ(gSafariZoneStepCounter, 0);
        EXPECT_EQ(gNumSafariBalls, 0);
    }
}
