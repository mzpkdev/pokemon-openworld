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

static struct WildEncounterProfileView ResolveStandardProfile(
    u16 map,
    enum WildPokemonArea area,
    enum TimeOfDay timeOfDay,
    u8 fishingRod)
{
    struct WildEncounterProfileView view = {0};

    EXPECT(TryResolveWildEncounterProfile(
        FindJohtoHeader(map), area, timeOfDay, fishingRod, &view));
    EXPECT(IsWildEncounterProfileViewValid(&view));
    return view;
}

static void ExpectProfilesEqual(
    const struct WildEncounterProfileView *actual,
    const struct WildEncounterProfileView *expected)
{
    u16 index;

    EXPECT_EQ(actual->area, expected->area);
    EXPECT_EQ(actual->fishingRod, expected->fishingRod);
    EXPECT_EQ(actual->encounterRate, expected->encounterRate);
    EXPECT_EQ(actual->entryCount, expected->entryCount);
    EXPECT_EQ(actual->totalWeight, expected->totalWeight);
    for (index = 0; index < expected->entryCount; index++)
    {
        struct WildEncounterSlot actualEntry;
        struct WildEncounterSlot expectedEntry;

        EXPECT(TryGetWildEncounterProfileEntry(actual, index, &actualEntry));
        EXPECT(TryGetWildEncounterProfileEntry(expected, index, &expectedEntry));
        EXPECT_EQ(actualEntry.species, expectedEntry.species);
        EXPECT_EQ(actualEntry.weight, expectedEntry.weight);
        EXPECT_EQ(actualEntry.minLevel, expectedEntry.minLevel);
        EXPECT_EQ(actualEntry.maxLevel, expectedEntry.maxLevel);
    }
}

TEST("Johto standard methods preserve every raw row through the public profile API")
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
    u16 headerId = FindJohtoHeader(MAP_ROUTE32);
    u16 method;

    for (method = 0; method < ARRAY_COUNT(sMethods); method++)
    {
        const struct WildPokemonInfo *source = GetWildEncounterInfoAtTime(
            headerId, TIME_DAY, sMethods[method].area);
        struct WildEncounterProfileView view = ResolveStandardProfile(
            MAP_ROUTE32, sMethods[method].area, TIME_DAY, sMethods[method].fishingRod);
        u16 index;

        EXPECT(source != NULL);
        EXPECT(view.entries == source->wildPokemon);
        EXPECT_EQ(view.encounterRate, source->encounterRate);
        for (index = 0; index < view.entryCount; index++)
        {
            struct WildEncounterSlot entry;
            const struct WildPokemon *raw = &source->wildPokemon[view.legacyStartIndex + index];

            EXPECT(TryGetWildEncounterProfileEntry(&view, index, &entry));
            EXPECT_EQ(entry.species, raw->species);
            EXPECT_EQ(entry.minLevel, min(raw->minLevel, raw->maxLevel));
            EXPECT_EQ(entry.maxLevel, max(raw->minLevel, raw->maxLevel));
        }
    }
}

TEST("Route 32 retains duplicate weighted slots and Route 29 dispatches day and night")
{
    struct WildEncounterProfileView route32 = ResolveStandardProfile(
        MAP_ROUTE32, WILD_AREA_LAND, TIME_DAY, WILD_ENCOUNTER_FISHING_ROD_NONE);
    struct WildEncounterProfileView day = ResolveStandardProfile(
        MAP_ROUTE29, WILD_AREA_LAND, TIME_DAY, WILD_ENCOUNTER_FISHING_ROD_NONE);
    struct WildEncounterProfileView night = ResolveStandardProfile(
        MAP_ROUTE29, WILD_AREA_LAND, TIME_NIGHT, WILD_ENCOUNTER_FISHING_ROD_NONE);
    struct WildEncounterSlot entry0;
    struct WildEncounterSlot entry1;
    struct WildEncounterSlot dayEntry;
    struct WildEncounterSlot nightEntry;

    EXPECT_EQ(route32.encounterRate, 20);
    EXPECT_EQ(route32.totalWeight, 100);
    EXPECT(TryGetWildEncounterProfileEntry(&route32, 0, &entry0));
    EXPECT(TryGetWildEncounterProfileEntry(&route32, 1, &entry1));
    EXPECT_EQ(entry0.species, SPECIES_MAREEP);
    EXPECT_EQ(entry1.species, SPECIES_MAREEP);
    EXPECT_EQ(entry0.weight, 20);
    EXPECT_EQ(entry1.weight, 20);
    EXPECT_EQ(entry0.minLevel, 5);
    EXPECT_EQ(entry0.maxLevel, 7);
    EXPECT(TryGetWildEncounterProfileEntry(&day, 0, &dayEntry));
    EXPECT(TryGetWildEncounterProfileEntry(&night, 0, &nightEntry));
    EXPECT_EQ(dayEntry.species, SPECIES_PIDGEY);
    EXPECT_EQ(nightEntry.species, SPECIES_HOOTHOOT);
    EXPECT_EQ(dayEntry.minLevel, 2);
    EXPECT_EQ(nightEntry.minLevel, 2);
}

TEST("Reviewed Johto fallbacks preserve exact raw day and night rows")
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
    u16 index;

    for (index = 0; index < ARRAY_COUNT(sFallbacks); index++)
    {
        struct WildEncounterProfileView day = ResolveStandardProfile(
            sFallbacks[index].map, sFallbacks[index].area, TIME_DAY, sFallbacks[index].fishingRod);
        struct WildEncounterProfileView night = ResolveStandardProfile(
            sFallbacks[index].map, sFallbacks[index].area, TIME_NIGHT, sFallbacks[index].fishingRod);

        ExpectProfilesEqual(&night, &day);
    }
}

TEST("Johto aliases remain distinct ordinary headers and special encounters remain excluded")
{
    static const u16 sAliasMaps[] =
    {
        MAP_LAKE_OF_RAGE_LOW_TIDE,
        MAP_ROUTE26NORTH,
        MAP_JOHTO_VICTORY_ROAD_1F,
        MAP_JOHTO_VICTORY_ROAD_B1F,
        MAP_JOHTO_VICTORY_ROAD_B2F,
    };
    static const u16 sSpecialMaps[] =
    {
        MAP_NATIONAL_PARK_BUG_CONTEST,
        MAP_SAFARI_ZONE1,
        MAP_TIN_TOWER_ROOF_DAY,
        MAP_WHIRL_ISLANDS_LUGIA_CHAMBER,
        MAP_EMBEDDED_TOWER,
        MAP_DRAGONS_DEN_SHRINE,
    };
    u16 index;

    for (index = 0; index < ARRAY_COUNT(sAliasMaps); index++)
    {
        u16 other;

        for (other = index + 1; other < ARRAY_COUNT(sAliasMaps); other++)
            EXPECT_NE(FindJohtoHeader(sAliasMaps[index]), FindJohtoHeader(sAliasMaps[other]));
    }
    for (index = 0; index < ARRAY_COUNT(sSpecialMaps); index++)
    {
        u16 headerId = 0x1234;

        EXPECT(!TryFindWildEncounterHeader(
            MAP_GROUP(sSpecialMaps[index]), MAP_NUM(sSpecialMaps[index]), &headerId));
        EXPECT_EQ(headerId, 0x1234);
    }
}
