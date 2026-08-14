#include "global.h"
#include "wild_encounter.h"
#include "constants/items.h"
#include "test/test.h"

static u16 FindJohtoHeader(u16 map)
{
    u16 headerId = HEADER_NONE;

    EXPECT(TryFindWildEncounterHeader(MAP_GROUP(map), MAP_NUM(map), &headerId));
    return headerId;
}

static struct WildEncounterProfileView ResolveAuthoredProfile(
    u16 map,
    enum WildPokemonArea area,
    enum TimeOfDay timeOfDay,
    u8 fishingRod,
    enum WorldTier tier)
{
    struct WildEncounterProfileView view = {0};
    u16 headerId = FindJohtoHeader(map);

    EXPECT(TryResolveWildEncounterProfile(headerId, area, timeOfDay, fishingRod, tier, &view));
    EXPECT_EQ(view.source, WILD_ENCOUNTER_PROFILE_AUTHORED);
    EXPECT(IsWildEncounterProfileViewValid(&view));
    return view;
}

static void ExpectAuthoredLevels(
    const struct WildEncounterProfileView *view,
    u8 expectedMin,
    u8 expectedMax)
{
    u32 totalWeight = 0;
    u16 i;

    EXPECT(view->encounterRate > 0);
    EXPECT(view->entryCount > 0);
    for (i = 0; i < view->entryCount; i++)
    {
        struct WildEncounterAuthoredEntry entry;

        EXPECT(TryGetWildEncounterProfileEntry(view, i, &entry));
        EXPECT_NE(entry.species, SPECIES_NONE);
        EXPECT(entry.weight > 0);
        EXPECT(entry.minLevel >= expectedMin);
        EXPECT(entry.maxLevel <= expectedMax);
        EXPECT(entry.minLevel <= entry.maxLevel);
        totalWeight += entry.weight;
    }
    EXPECT_EQ(totalWeight, view->totalWeight);
}

static void ExpectNoOrdinaryHeader(u16 map)
{
    u16 unchanged = 0x1234;

    EXPECT(!TryFindWildEncounterHeader(MAP_GROUP(map), MAP_NUM(map), &unchanged));
    EXPECT_EQ(unchanged, 0x1234);
}

TEST("Johto authored methods resolve through the public encounter profile API")
{
    static const struct
    {
        enum WildPokemonArea area;
        u8 fishingRod;
    } sMethods[] =
    {
        {WILD_AREA_LAND, WILD_ENCOUNTER_FISHING_ROD_NONE},
        {WILD_AREA_WATER, WILD_ENCOUNTER_FISHING_ROD_NONE},
        {WILD_AREA_ROCKS, WILD_ENCOUNTER_FISHING_ROD_NONE},
        {WILD_AREA_FISHING, OLD_ROD},
        {WILD_AREA_FISHING, GOOD_ROD},
        {WILD_AREA_FISHING, SUPER_ROD},
    };
    u16 i;

    for (i = 0; i < ARRAY_COUNT(sMethods); i++)
    {
        struct WildEncounterProfileView view = ResolveAuthoredProfile(
            MAP_ROUTE32,
            sMethods[i].area,
            TIME_DAY,
            sMethods[i].fishingRod,
            WORLD_TIER_0);

        EXPECT_EQ(view.area, sMethods[i].area);
        EXPECT_EQ(view.fishingRod, sMethods[i].fishingRod);
        ExpectAuthoredLevels(&view, 4, 8);
    }
}

TEST("Johto authored populations dispatch day and night profiles")
{
    struct WildEncounterProfileView day = ResolveAuthoredProfile(
        MAP_ROUTE29,
        WILD_AREA_LAND,
        TIME_DAY,
        WILD_ENCOUNTER_FISHING_ROD_NONE,
        WORLD_TIER_0);
    struct WildEncounterProfileView night = ResolveAuthoredProfile(
        MAP_ROUTE29,
        WILD_AREA_LAND,
        TIME_NIGHT,
        WILD_ENCOUNTER_FISHING_ROD_NONE,
        WORLD_TIER_0);
    struct WildEncounterAuthoredEntry dayEntry;
    struct WildEncounterAuthoredEntry nightEntry;

    ExpectAuthoredLevels(&day, 4, 8);
    ExpectAuthoredLevels(&night, 4, 8);
    EXPECT(TryGetWildEncounterProfileEntry(&day, 0, &dayEntry));
    EXPECT(TryGetWildEncounterProfileEntry(&night, 0, &nightEntry));
    EXPECT_EQ(dayEntry.species, SPECIES_PIDGEY);
    EXPECT_EQ(nightEntry.species, SPECIES_HOOTHOOT);
}

TEST("Johto authored levels advance from world tier zero to tier three")
{
    struct WildEncounterProfileView tier0 = ResolveAuthoredProfile(
        MAP_UNION_CAVE_1F,
        WILD_AREA_LAND,
        TIME_DAY,
        WILD_ENCOUNTER_FISHING_ROD_NONE,
        WORLD_TIER_0);
    struct WildEncounterProfileView tier3 = ResolveAuthoredProfile(
        MAP_UNION_CAVE_1F,
        WILD_AREA_LAND,
        TIME_DAY,
        WILD_ENCOUNTER_FISHING_ROD_NONE,
        WORLD_TIER_3);

    ExpectAuthoredLevels(&tier0, 4, 8);
    ExpectAuthoredLevels(&tier3, 20, 24);
}

TEST("Explicit Johto fallback maps have ordinary authored populations")
{
    static const struct
    {
        u16 map;
        enum WildPokemonArea area;
    } sFallbacks[] =
    {
        {MAP_LAKE_OF_RAGE_LOW_TIDE, WILD_AREA_WATER},
        {MAP_ROUTE26NORTH, WILD_AREA_LAND},
        {MAP_JOHTO_VICTORY_ROAD_1F, WILD_AREA_LAND},
        {MAP_JOHTO_VICTORY_ROAD_B1F, WILD_AREA_LAND},
        {MAP_JOHTO_VICTORY_ROAD_B2F, WILD_AREA_LAND},
    };
    u16 i;

    for (i = 0; i < ARRAY_COUNT(sFallbacks); i++)
    {
        struct WildEncounterProfileView tier0 = ResolveAuthoredProfile(
            sFallbacks[i].map,
            sFallbacks[i].area,
            TIME_DAY,
            WILD_ENCOUNTER_FISHING_ROD_NONE,
            WORLD_TIER_0);
        struct WildEncounterProfileView tier3 = ResolveAuthoredProfile(
            sFallbacks[i].map,
            sFallbacks[i].area,
            TIME_DAY,
            WILD_ENCOUNTER_FISHING_ROD_NONE,
            WORLD_TIER_3);

        ExpectAuthoredLevels(&tier0, 4, 8);
        ExpectAuthoredLevels(&tier3, 20, 24);
    }
}

TEST("Johto special encounters remain outside ordinary wild headers")
{
    ExpectNoOrdinaryHeader(MAP_NATIONAL_PARK_BUG_CONTEST);
    ExpectNoOrdinaryHeader(MAP_SAFARI_ZONE1);
    ExpectNoOrdinaryHeader(MAP_TIN_TOWER_ROOF_DAY);
    ExpectNoOrdinaryHeader(MAP_WHIRL_ISLANDS_LUGIA_CHAMBER);
    ExpectNoOrdinaryHeader(MAP_EMBEDDED_TOWER);
    ExpectNoOrdinaryHeader(MAP_DRAGONS_DEN_SHRINE);
}

TEST("Route 39 keeps its established authored day and night proof")
{
    struct WildEncounterProfileView day = ResolveAuthoredProfile(
        MAP_ROUTE39,
        WILD_AREA_LAND,
        TIME_DAY,
        WILD_ENCOUNTER_FISHING_ROD_NONE,
        WORLD_TIER_1);
    struct WildEncounterProfileView night = ResolveAuthoredProfile(
        MAP_ROUTE39,
        WILD_AREA_LAND,
        TIME_NIGHT,
        WILD_ENCOUNTER_FISHING_ROD_NONE,
        WORLD_TIER_1);
    struct WildEncounterAuthoredEntry entry;

    ExpectAuthoredLevels(&day, 10, 14);
    ExpectAuthoredLevels(&night, 10, 14);
    EXPECT(TryGetWildEncounterProfileEntry(&day, 0, &entry));
    EXPECT_EQ(entry.species, SPECIES_PONYTA);
    EXPECT(TryGetWildEncounterProfileEntry(&night, 0, &entry));
    EXPECT_EQ(entry.species, SPECIES_MEOWTH);
}
