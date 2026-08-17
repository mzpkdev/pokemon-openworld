#include "global.h"
#include "wild_encounter.h"
#include "constants/items.h"
#include "test/test.h"

struct ExpectedStandardEntry
{
    enum Species species;
    u8 weight;
    u8 minLevel;
    u8 maxLevel;
};

static u16 FindJohtoHeader(u16 map)
{
    u16 headerId = HEADER_NONE;

    EXPECT(TryFindWildEncounterHeader(MAP_GROUP(map), MAP_NUM(map), &headerId));
    return headerId;
}

static struct WildEncounterProfileView ResolveStandardProfile(
    u16 map,
    enum WildPokemonArea area,
    enum TimeOfDay timeOfDay,
    u8 fishingRod,
    enum WorldTier tier)
{
    struct WildEncounterProfileView view = {0};
    u16 headerId = FindJohtoHeader(map);

    EXPECT(TryResolveWildEncounterProfile(headerId, area, timeOfDay, fishingRod, tier, &view));
    EXPECT_EQ(view.source, WILD_ENCOUNTER_PROFILE_LEGACY);
    EXPECT(IsWildEncounterProfileViewValid(&view));
    return view;
}

static void ExpectProfilesEqual(
    const struct WildEncounterProfileView *actual,
    const struct WildEncounterProfileView *expected)
{
    u16 i;

    EXPECT_EQ(actual->source, expected->source);
    EXPECT_EQ(actual->area, expected->area);
    EXPECT_EQ(actual->fishingRod, expected->fishingRod);
    EXPECT_EQ(actual->encounterRate, expected->encounterRate);
    EXPECT_EQ(actual->entryCount, expected->entryCount);
    EXPECT_EQ(actual->totalWeight, expected->totalWeight);
    for (i = 0; i < expected->entryCount; i++)
    {
        struct WildEncounterAuthoredEntry actualEntry;
        struct WildEncounterAuthoredEntry expectedEntry;

        EXPECT(TryGetWildEncounterProfileEntry(actual, i, &actualEntry));
        EXPECT(TryGetWildEncounterProfileEntry(expected, i, &expectedEntry));
        EXPECT_EQ(actualEntry.species, expectedEntry.species);
        EXPECT_EQ(actualEntry.weight, expectedEntry.weight);
        EXPECT_EQ(actualEntry.minLevel, expectedEntry.minLevel);
        EXPECT_EQ(actualEntry.maxLevel, expectedEntry.maxLevel);
    }
}

static void ExpectExactStandardRow(
    u16 map,
    enum WildPokemonArea area,
    enum TimeOfDay timeOfDay,
    u8 fishingRod,
    enum WorldTier tier)
{
    const struct WildPokemonInfo *standardInfo;
    struct WildEncounterProfileView view = ResolveStandardProfile(map, area, timeOfDay, fishingRod, tier);
    u16 headerId = FindJohtoHeader(map);
    u16 i;

    standardInfo = GetWildEncounterInfoAtTime(headerId, timeOfDay, area);
    EXPECT(standardInfo != NULL);
    EXPECT_EQ(view.encounterRate, standardInfo->encounterRate);
    EXPECT(view.legacyEntries == standardInfo->wildPokemon);
    for (i = 0; i < view.entryCount; i++)
    {
        const struct WildPokemon *standardEntry = &standardInfo->wildPokemon[view.legacyStartIndex + i];
        struct WildEncounterAuthoredEntry entry;

        EXPECT(TryGetWildEncounterProfileEntry(&view, i, &entry));
        EXPECT_EQ(entry.species, standardEntry->species);
        EXPECT_EQ(entry.minLevel, min(standardEntry->minLevel, standardEntry->maxLevel));
        EXPECT_EQ(entry.maxLevel, max(standardEntry->minLevel, standardEntry->maxLevel));
    }
}

static void ExpectEntries(
    const struct WildEncounterProfileView *view,
    const struct ExpectedStandardEntry *expected,
    u16 count)
{
    u16 i;

    EXPECT_EQ(view->entryCount, count);
    for (i = 0; i < count; i++)
    {
        struct WildEncounterAuthoredEntry entry;

        EXPECT(TryGetWildEncounterProfileEntry(view, i, &entry));
        EXPECT_EQ(entry.species, expected[i].species);
        EXPECT_EQ(entry.weight, expected[i].weight);
        EXPECT_EQ(entry.minLevel, expected[i].minLevel);
        EXPECT_EQ(entry.maxLevel, expected[i].maxLevel);
    }
}

static void ExpectNoOrdinaryHeader(u16 map)
{
    u16 unchanged = 0x1234;

    EXPECT(!TryFindWildEncounterHeader(MAP_GROUP(map), MAP_NUM(map), &unchanged));
    EXPECT_EQ(unchanged, 0x1234);
}

TEST("Johto standard methods preserve every row through the public profile API")
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
        ExpectExactStandardRow(
            MAP_ROUTE32,
            sMethods[i].area,
            TIME_DAY,
            sMethods[i].fishingRod,
            WORLD_TIER_0);
    }
}

TEST("Johto standard rows retain ordered duplicate slots weights and vanilla levels")
{
    static const struct ExpectedStandardEntry sExpected[] =
    {
        {SPECIES_MAREEP,     20, 5, 7},
        {SPECIES_MAREEP,     20, 5, 7},
        {SPECIES_MAREEP,     10, 5, 7},
        {SPECIES_WOOPER,     10, 7, 7},
        {SPECIES_WOOPER,     10, 7, 7},
        {SPECIES_WOOPER,     10, 7, 7},
        {SPECIES_EKANS,       5, 6, 6},
        {SPECIES_EKANS,       5, 6, 6},
        {SPECIES_PIDGEY,      4, 7, 7},
        {SPECIES_BELLSPROUT,  4, 7, 7},
        {SPECIES_PIDGEY,      1, 7, 7},
        {SPECIES_BELLSPROUT,  1, 7, 7},
    };
    struct WildEncounterProfileView view = ResolveStandardProfile(
        MAP_ROUTE32,
        WILD_AREA_LAND,
        TIME_DAY,
        WILD_ENCOUNTER_FISHING_ROD_NONE,
        WORLD_TIER_2);

    EXPECT_EQ(view.encounterRate, 20);
    EXPECT_EQ(view.totalWeight, 100);
    ExpectEntries(&view, sExpected, ARRAY_COUNT(sExpected));
}

TEST("Johto standard populations dispatch distinct day and night rows")
{
    struct WildEncounterProfileView day = ResolveStandardProfile(
        MAP_ROUTE29,
        WILD_AREA_LAND,
        TIME_DAY,
        WILD_ENCOUNTER_FISHING_ROD_NONE,
        WORLD_TIER_0);
    struct WildEncounterProfileView night = ResolveStandardProfile(
        MAP_ROUTE29,
        WILD_AREA_LAND,
        TIME_NIGHT,
        WILD_ENCOUNTER_FISHING_ROD_NONE,
        WORLD_TIER_0);
    struct WildEncounterAuthoredEntry dayEntry;
    struct WildEncounterAuthoredEntry nightEntry;

    EXPECT(TryGetWildEncounterProfileEntry(&day, 0, &dayEntry));
    EXPECT(TryGetWildEncounterProfileEntry(&night, 0, &nightEntry));
    EXPECT_EQ(dayEntry.species, SPECIES_PIDGEY);
    EXPECT_EQ(dayEntry.minLevel, 2);
    EXPECT_EQ(dayEntry.maxLevel, 3);
    EXPECT_EQ(nightEntry.species, SPECIES_HOOTHOOT);
    EXPECT_EQ(nightEntry.minLevel, 2);
    EXPECT_EQ(nightEntry.maxLevel, 3);
}

TEST("Reviewed Johto method fallbacks are exact day rows copied to night")
{
    static const struct
    {
        u16 map;
        enum WildPokemonArea area;
        u8 fishingRod;
    } sFallbacks[] =
    {
        {MAP_RUINS_OF_ALPH_OUTSIDE, WILD_AREA_ROCKS, WILD_ENCOUNTER_FISHING_ROD_NONE},
        {MAP_CIANWOOD_CITY, WILD_AREA_ROCKS, WILD_ENCOUNTER_FISHING_ROD_NONE},
        {MAP_MT_SILVER_MOUNTAIN_SIDE, WILD_AREA_FISHING, SUPER_ROD},
        {MAP_ROUTE26, WILD_AREA_ROCKS, WILD_ENCOUNTER_FISHING_ROD_NONE},
        {MAP_ROUTE26NORTH, WILD_AREA_ROCKS, WILD_ENCOUNTER_FISHING_ROD_NONE},
    };
    u16 i;

    for (i = 0; i < ARRAY_COUNT(sFallbacks); i++)
    {
        struct WildEncounterProfileView day = ResolveStandardProfile(
            sFallbacks[i].map,
            sFallbacks[i].area,
            TIME_DAY,
            sFallbacks[i].fishingRod,
            WORLD_TIER_0);
        struct WildEncounterProfileView night = ResolveStandardProfile(
            sFallbacks[i].map,
            sFallbacks[i].area,
            TIME_NIGHT,
            sFallbacks[i].fishingRod,
            WORLD_TIER_3);

        ExpectProfilesEqual(&night, &day);
    }
}

TEST("Johto standard profiles are invariant across all existing world tiers")
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
    u16 method;

    for (method = 0; method < ARRAY_COUNT(sMethods); method++)
    {
        struct WildEncounterProfileView tier0 = ResolveStandardProfile(
            MAP_ROUTE32,
            sMethods[method].area,
            TIME_DAY,
            sMethods[method].fishingRod,
            WORLD_TIER_0);
        u16 tier;

        for (tier = WORLD_TIER_1; tier < WORLD_TIER_COUNT; tier++)
        {
            struct WildEncounterProfileView other = ResolveStandardProfile(
                MAP_ROUTE32,
                sMethods[method].area,
                TIME_DAY,
                sMethods[method].fishingRod,
                (enum WorldTier)tier);

            ExpectProfilesEqual(&other, &tier0);
        }
    }
}

TEST("Five Johto alias maps retain distinct targets and nine exact standard profiles")
{
    static const struct
    {
        u16 targetMap;
        u16 sourceMap;
        enum TimeOfDay timeOfDay;
    } sAliasProfiles[] =
    {
        {MAP_LAKE_OF_RAGE_LOW_TIDE, MAP_LAKE_OF_RAGE, TIME_MORNING},
        {MAP_ROUTE26NORTH, MAP_ROUTE26, TIME_DAY},
        {MAP_ROUTE26NORTH, MAP_ROUTE26, TIME_NIGHT},
        {MAP_JOHTO_VICTORY_ROAD_1F, MAP_VICTORY_ROAD_1F, TIME_DAY},
        {MAP_JOHTO_VICTORY_ROAD_1F, MAP_VICTORY_ROAD_1F, TIME_NIGHT},
        {MAP_JOHTO_VICTORY_ROAD_B1F, MAP_VICTORY_ROAD_B1F, TIME_DAY},
        {MAP_JOHTO_VICTORY_ROAD_B1F, MAP_VICTORY_ROAD_B1F, TIME_NIGHT},
        {MAP_JOHTO_VICTORY_ROAD_B2F, MAP_VICTORY_ROAD_B2F, TIME_DAY},
        {MAP_JOHTO_VICTORY_ROAD_B2F, MAP_VICTORY_ROAD_B2F, TIME_NIGHT},
    };
    static const u16 sAliasTargets[] =
    {
        MAP_LAKE_OF_RAGE_LOW_TIDE,
        MAP_ROUTE26NORTH,
        MAP_JOHTO_VICTORY_ROAD_1F,
        MAP_JOHTO_VICTORY_ROAD_B1F,
        MAP_JOHTO_VICTORY_ROAD_B2F,
    };
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

    for (i = 0; i < ARRAY_COUNT(sAliasTargets); i++)
    {
        u16 targetHeader = FindJohtoHeader(sAliasTargets[i]);
        u16 j;

        for (j = i + 1; j < ARRAY_COUNT(sAliasTargets); j++)
            EXPECT_NE(targetHeader, FindJohtoHeader(sAliasTargets[j]));
    }

    for (i = 0; i < ARRAY_COUNT(sAliasProfiles); i++)
    {
        u16 targetHeader = FindJohtoHeader(sAliasProfiles[i].targetMap);
        u16 sourceHeader = FindJohtoHeader(sAliasProfiles[i].sourceMap);
        u16 resolvedMethodCount = 0;
        u16 method;

        EXPECT_NE(targetHeader, sourceHeader);
        for (method = 0; method < ARRAY_COUNT(sMethods); method++)
        {
            const struct WildPokemonInfo *standardInfo = GetWildEncounterInfoAtTime(
                targetHeader,
                sAliasProfiles[i].timeOfDay,
                sMethods[method].area);

            if (standardInfo != NULL && standardInfo->wildPokemon != NULL && standardInfo->encounterRate != 0)
            {
                resolvedMethodCount++;
                ExpectExactStandardRow(
                    sAliasProfiles[i].targetMap,
                    sMethods[method].area,
                    sAliasProfiles[i].timeOfDay,
                    sMethods[method].fishingRod,
                    WORLD_TIER_3);
            }
        }
        EXPECT(resolvedMethodCount > 0);
    }
}

TEST("Route 39 keeps its exact standard day and night authority")
{
    static const struct ExpectedStandardEntry sDay[] =
    {
        {SPECIES_PONYTA,    20, 21, 21},
        {SPECIES_RATICATE,  20, 21, 21},
        {SPECIES_MAGNEMITE, 10, 21, 21},
        {SPECIES_DODUO,     10, 21, 21},
        {SPECIES_PONYTA,    10, 21, 21},
        {SPECIES_RATICATE,  10, 21, 21},
        {SPECIES_MAGNEMITE,  5, 21, 21},
        {SPECIES_DODUO,      5, 21, 21},
        {SPECIES_MILTANK,    4, 21, 21},
        {SPECIES_TAUROS,     4, 21, 21},
        {SPECIES_MILTANK,    1, 21, 21},
        {SPECIES_TAUROS,     1, 21, 21},
    };
    static const struct ExpectedStandardEntry sNight[] =
    {
        {SPECIES_MEOWTH,    20, 18, 21},
        {SPECIES_RATICATE,  20, 21, 21},
        {SPECIES_MAGNEMITE, 10, 20, 20},
        {SPECIES_NOCTOWL,   10, 20, 20},
        {SPECIES_MEOWTH,    10, 18, 21},
        {SPECIES_RATICATE,  10, 21, 21},
        {SPECIES_MAGNEMITE,  5, 20, 20},
        {SPECIES_MEOWTH,     5, 18, 21},
        {SPECIES_NOCTOWL,    4, 20, 20},
        {SPECIES_NOCTOWL,    4, 20, 20},
        {SPECIES_NOCTOWL,    1, 20, 20},
        {SPECIES_NOCTOWL,    1, 20, 20},
    };
    struct WildEncounterProfileView day = ResolveStandardProfile(
        MAP_ROUTE39,
        WILD_AREA_LAND,
        TIME_DAY,
        WILD_ENCOUNTER_FISHING_ROD_NONE,
        WORLD_TIER_0);
    struct WildEncounterProfileView night = ResolveStandardProfile(
        MAP_ROUTE39,
        WILD_AREA_LAND,
        TIME_NIGHT,
        WILD_ENCOUNTER_FISHING_ROD_NONE,
        WORLD_TIER_3);

    EXPECT_EQ(day.encounterRate, 20);
    EXPECT_EQ(night.encounterRate, 20);
    ExpectEntries(&day, sDay, ARRAY_COUNT(sDay));
    ExpectEntries(&night, sNight, ARRAY_COUNT(sNight));
}

TEST("Johto special encounters remain outside ordinary wild lookup")
{
    ExpectNoOrdinaryHeader(MAP_NATIONAL_PARK_BUG_CONTEST);
    ExpectNoOrdinaryHeader(MAP_SAFARI_ZONE1);
    ExpectNoOrdinaryHeader(MAP_TIN_TOWER_ROOF_DAY);
    ExpectNoOrdinaryHeader(MAP_WHIRL_ISLANDS_LUGIA_CHAMBER);
    ExpectNoOrdinaryHeader(MAP_EMBEDDED_TOWER);
    ExpectNoOrdinaryHeader(MAP_DRAGONS_DEN_SHRINE);
}
