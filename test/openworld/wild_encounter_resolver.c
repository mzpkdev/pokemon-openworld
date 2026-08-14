#include "global.h"
#include "random.h"
#include "wild_encounter.h"
#include "constants/items.h"
#include "test/test.h"

static u16 FindHeader(u16 map)
{
    u16 headerId = HEADER_NONE;

    EXPECT(TryFindWildEncounterHeader(MAP_GROUP(map), MAP_NUM(map), &headerId));
    return headerId;
}

TEST("Authored encounter profiles resolve by header method condition and tier")
{
    struct WildEncounterProfileView view;
    struct WildEncounterAuthoredEntry entry;
    u16 headerId = FindHeader(MAP_ROUTE101);

    EXPECT(TryResolveWildEncounterProfile(headerId, WILD_AREA_LAND, TIME_MORNING, WILD_ENCOUNTER_FISHING_ROD_NONE, WORLD_TIER_0, &view));
    EXPECT_EQ(view.source, WILD_ENCOUNTER_PROFILE_AUTHORED);
    EXPECT_EQ(view.encounterRate, 20);
    EXPECT_EQ(view.entryCount, 3);
    EXPECT_EQ(view.totalWeight, 100);
    EXPECT(TryGetWildEncounterProfileEntry(&view, 0, &entry));
    EXPECT_EQ(entry.species, SPECIES_WURMPLE);
    EXPECT_EQ(entry.weight, 45);
    EXPECT_EQ(entry.minLevel, 2);
    EXPECT_EQ(entry.maxLevel, 3);

    EXPECT(TryResolveWildEncounterProfile(headerId, WILD_AREA_LAND, TIME_MORNING, WILD_ENCOUNTER_FISHING_ROD_NONE, WORLD_TIER_3, &view));
    EXPECT(TryGetWildEncounterProfileEntry(&view, 0, &entry));
    EXPECT_EQ(entry.minLevel, 20);
    EXPECT_EQ(entry.maxLevel, 24);
}

TEST("Complete and floor authored band policies are explicit")
{
    static const struct WildEncounterAuthoredEntry sEntries[] =
    {
        {SPECIES_RATTATA, 100, 4, 8},
    };
    static const struct WildEncounterAuthoredBand sCompleteBands[] =
    {
        {WORLD_TIER_0, 1, 100, sEntries},
        {WORLD_TIER_1, 1, 100, sEntries},
        {WORLD_TIER_2, 1, 100, sEntries},
        {WORLD_TIER_3, 1, 100, sEntries},
    };
    static const struct WildEncounterAuthoredBand sFloorBands[] =
    {
        {WORLD_TIER_0, 1, 100, sEntries},
        {WORLD_TIER_2, 1, 100, sEntries},
    };
    struct WildEncounterAuthoredProfile profile =
    {
        .missingBandPolicy = WILD_ENCOUNTER_MISSING_BAND_COMPLETE,
        .bandCount = ARRAY_COUNT(sCompleteBands),
        .bands = sCompleteBands,
    };
    const struct WildEncounterAuthoredBand *band = (void *)1;

    EXPECT(TryResolveWildEncounterAuthoredBand(&profile, WORLD_TIER_2, &band));
    EXPECT_EQ(band->tier, WORLD_TIER_2);
    EXPECT(TryResolveWildEncounterAuthoredBand(&profile, WORLD_TIER_1, &band));
    EXPECT_EQ(band->tier, WORLD_TIER_1);

    profile.missingBandPolicy = WILD_ENCOUNTER_MISSING_BAND_FLOOR;
    profile.bandCount = ARRAY_COUNT(sFloorBands);
    profile.bands = sFloorBands;
    EXPECT(TryResolveWildEncounterAuthoredBand(&profile, WORLD_TIER_1, &band));
    EXPECT_EQ(band->tier, WORLD_TIER_0);
    EXPECT(TryResolveWildEncounterAuthoredBand(&profile, WORLD_TIER_3, &band));
    EXPECT_EQ(band->tier, WORLD_TIER_2);
}

TEST("Authored weighted selection honors every boundary")
{
    static const struct WildEncounterAuthoredEntry sEntries[] =
    {
        {SPECIES_RATTATA, 30, 4, 8},
        {SPECIES_PIDGEY, 70, 4, 8},
    };
    const struct WildEncounterProfileView view =
    {
        .source = WILD_ENCOUNTER_PROFILE_AUTHORED,
        .area = WILD_AREA_LAND,
        .fishingRod = WILD_ENCOUNTER_FISHING_ROD_NONE,
        .encounterRate = 1,
        .entryCount = ARRAY_COUNT(sEntries),
        .totalWeight = 100,
        .authoredEntries = sEntries,
    };
    struct WildEncounterAuthoredEntry entry = {SPECIES_NONE};

    EXPECT(TrySelectWildEncounterProfileEntry(&view, 0, &entry));
    EXPECT_EQ(entry.species, SPECIES_RATTATA);
    EXPECT(TrySelectWildEncounterProfileEntry(&view, 29, &entry));
    EXPECT_EQ(entry.species, SPECIES_RATTATA);
    EXPECT(TrySelectWildEncounterProfileEntry(&view, 30, &entry));
    EXPECT_EQ(entry.species, SPECIES_PIDGEY);
    EXPECT(TrySelectWildEncounterProfileEntry(&view, 99, &entry));
    EXPECT_EQ(entry.species, SPECIES_PIDGEY);
    entry.species = SPECIES_ZUBAT;
    EXPECT(!TrySelectWildEncounterProfileEntry(&view, 100, &entry));
    EXPECT_EQ(entry.species, SPECIES_ZUBAT);
}

TEST("Authored levels are inclusive and Lure caps one above maximum")
{
    static const struct WildEncounterAuthoredEntry sEntries[] =
    {
        {SPECIES_RATTATA, 50, 10, 14},
        {SPECIES_RATTATA, 50, 12, 17},
    };
    const struct WildEncounterAuthoredEntry capped = {SPECIES_RATTATA, 100, 100, 100};
    const struct WildEncounterProfileView view =
    {
        .source = WILD_ENCOUNTER_PROFILE_AUTHORED,
        .area = WILD_AREA_LAND,
        .fishingRod = WILD_ENCOUNTER_FISHING_ROD_NONE,
        .encounterRate = 1,
        .entryCount = ARRAY_COUNT(sEntries),
        .totalWeight = 100,
        .authoredEntries = sEntries,
    };
    const struct WildEncounterProfileView cappedView =
    {
        .source = WILD_ENCOUNTER_PROFILE_AUTHORED,
        .area = WILD_AREA_LAND,
        .fishingRod = WILD_ENCOUNTER_FISHING_ROD_NONE,
        .encounterRate = 1,
        .entryCount = 1,
        .totalWeight = 100,
        .authoredEntries = &capped,
    };
    u8 level = 0;

    EXPECT(TrySelectWildEncounterLevel(&view, &sEntries[0], 0, FALSE, &level));
    EXPECT_EQ(level, 10);
    EXPECT(TrySelectWildEncounterLevel(&view, &sEntries[0], 4, FALSE, &level));
    EXPECT_EQ(level, 14);
    level = 77;
    EXPECT(!TrySelectWildEncounterLevel(&view, &sEntries[0], 5, FALSE, &level));
    EXPECT_EQ(level, 77);
    EXPECT(TrySelectWildEncounterLevel(&view, &sEntries[0], 0, TRUE, &level));
    EXPECT_EQ(level, 18);
    EXPECT(TrySelectWildEncounterLevel(&cappedView, &capped, 0, TRUE, &level));
    EXPECT_EQ(level, 100);
}

TEST("Unmigrated maps in every region remain unscaled legacy views")
{
    static const struct
    {
        u16 map;
        enum WildPokemonArea area;
    } sCases[] =
    {
        {MAP_ROUTE102, WILD_AREA_LAND},
        {MAP_ROUTE1, WILD_AREA_LAND},
        {MAP_CHERRYGROVE_CITY, WILD_AREA_WATER},
        {MAP_THREE_ISLAND_BERRY_FOREST, WILD_AREA_LAND},
    };
    u16 i;

    for (i = 0; i < ARRAY_COUNT(sCases); i++)
    {
        const struct WildPokemonInfo *legacyInfo;
        struct WildEncounterProfileView low;
        struct WildEncounterProfileView high;
        struct WildEncounterAuthoredEntry lowEntry;
        struct WildEncounterAuthoredEntry highEntry;
        u16 headerId = FindHeader(sCases[i].map);
        enum TimeOfDay timeOfDay = GetTimeOfDayForEncounters(headerId, sCases[i].area);

        legacyInfo = GetWildEncounterInfoAtTime(headerId, timeOfDay, sCases[i].area);
        EXPECT(legacyInfo != NULL);
        EXPECT(TryResolveWildEncounterProfile(headerId, sCases[i].area, timeOfDay, WILD_ENCOUNTER_FISHING_ROD_NONE, WORLD_TIER_0, &low));
        EXPECT(TryResolveWildEncounterProfile(headerId, sCases[i].area, timeOfDay, WILD_ENCOUNTER_FISHING_ROD_NONE, WORLD_TIER_3, &high));
        EXPECT_EQ(low.source, WILD_ENCOUNTER_PROFILE_LEGACY);
        EXPECT_EQ(high.source, WILD_ENCOUNTER_PROFILE_LEGACY);
        EXPECT_EQ(low.encounterRate, legacyInfo->encounterRate);
        EXPECT_EQ(low.entryCount, sCases[i].area == WILD_AREA_LAND ? NUM_LAND_MONS_ENCOUNTER_SLOTS : NUM_WATER_MONS_ENCOUNTER_SLOTS);
        EXPECT_EQ(low.totalWeight, 100);
        EXPECT(TryGetWildEncounterProfileEntry(&low, 0, &lowEntry));
        EXPECT(TryGetWildEncounterProfileEntry(&high, 0, &highEntry));
        EXPECT_EQ(lowEntry.weight, sCases[i].area == WILD_AREA_LAND ? 20 : 60);
        EXPECT_EQ(lowEntry.species, legacyInfo->wildPokemon[0].species);
        EXPECT_EQ(lowEntry.minLevel, min(legacyInfo->wildPokemon[0].minLevel, legacyInfo->wildPokemon[0].maxLevel));
        EXPECT_EQ(lowEntry.maxLevel, max(legacyInfo->wildPokemon[0].minLevel, legacyInfo->wildPokemon[0].maxLevel));
        EXPECT_EQ(highEntry.species, lowEntry.species);
        EXPECT_EQ(highEntry.minLevel, lowEntry.minLevel);
        EXPECT_EQ(highEntry.maxLevel, lowEntry.maxLevel);
    }
}

TEST("Route 39 authored profiles follow its resolved day and night condition")
{
    struct WildEncounterProfileView day;
    struct WildEncounterProfileView night;
    struct WildEncounterAuthoredEntry entry;
    u16 headerId = FindHeader(MAP_ROUTE39);

    EXPECT(TryResolveWildEncounterProfile(headerId, WILD_AREA_LAND, TIME_DAY, WILD_ENCOUNTER_FISHING_ROD_NONE, WORLD_TIER_1, &day));
    EXPECT(TryResolveWildEncounterProfile(headerId, WILD_AREA_LAND, TIME_NIGHT, WILD_ENCOUNTER_FISHING_ROD_NONE, WORLD_TIER_1, &night));
    EXPECT_EQ(day.source, WILD_ENCOUNTER_PROFILE_AUTHORED);
    EXPECT_EQ(night.source, WILD_ENCOUNTER_PROFILE_AUTHORED);
    EXPECT(TryGetWildEncounterProfileEntry(&day, 0, &entry));
    EXPECT_EQ(entry.species, SPECIES_PONYTA);
    EXPECT_EQ(entry.minLevel, 10);
    EXPECT(TryGetWildEncounterProfileEntry(&night, 0, &entry));
    EXPECT_EQ(entry.species, SPECIES_MEOWTH);
    EXPECT_EQ(entry.minLevel, 10);
}

TEST("Vermilion rods use the same world tier band without offsets")
{
    static const u8 sRods[] = {OLD_ROD, GOOD_ROD, SUPER_ROD};
    struct WildEncounterProfileView view;
    struct WildEncounterAuthoredEntry entry;
    u16 headerId = FindHeader(MAP_VERMILION_CITY);
    u16 i;

    for (i = 0; i < ARRAY_COUNT(sRods); i++)
    {
        EXPECT(TryResolveWildEncounterProfile(headerId, WILD_AREA_FISHING, TIME_MORNING, sRods[i], WORLD_TIER_2, &view));
        EXPECT_EQ(view.source, WILD_ENCOUNTER_PROFILE_AUTHORED);
        EXPECT(TryGetWildEncounterProfileEntry(&view, 0, &entry));
        EXPECT_EQ(entry.minLevel, 15);
        EXPECT_EQ(entry.maxLevel, 19);
    }
}

TEST("Malformed profile views fail closed without canary or RNG mutation")
{
    struct WildEncounterProfileView authored;
    struct WildEncounterProfileView legacy;
    struct WildEncounterProfileView malformed;
    struct WildEncounterAuthoredEntry entry = {SPECIES_ZUBAT, 77, 7, 8};
    struct WildEncounterAuthoredEntry invalidEntry;
    struct WildEncounterAuthoredEntry unrelatedEntry = {SPECIES_PIDGEY, 1, 4, 4};
    u16 authoredHeader = FindHeader(MAP_ROUTE101);
    u16 legacyHeader = FindHeader(MAP_ROUTE102);
    enum TimeOfDay legacyTime = GetTimeOfDayForEncounters(legacyHeader, WILD_AREA_LAND);
    u16 expectedRandom;
    u16 actualRandom;
    u8 level = 77;

    EXPECT(TryResolveWildEncounterProfile(authoredHeader, WILD_AREA_LAND, TIME_MORNING, WILD_ENCOUNTER_FISHING_ROD_NONE, WORLD_TIER_0, &authored));
    EXPECT(TryResolveWildEncounterProfile(legacyHeader, WILD_AREA_LAND, legacyTime, WILD_ENCOUNTER_FISHING_ROD_NONE, WORLD_TIER_0, &legacy));
    EXPECT(IsWildEncounterProfileViewValid(&authored));
    EXPECT(IsWildEncounterProfileViewValid(&legacy));

    EXPECT(!IsWildEncounterProfileViewValid(NULL));
    EXPECT(!TryGetWildEncounterProfileEntry(NULL, 0, &entry));
    EXPECT(!TrySelectWildEncounterProfileEntry(NULL, 0, &entry));
    EXPECT(!TrySelectWildEncounterLevel(NULL, &unrelatedEntry, 0, FALSE, &level));
    EXPECT(!TryGenerateWildMonFromProfile(NULL, 0));
    EXPECT_EQ(entry.species, SPECIES_ZUBAT);
    EXPECT_EQ(level, 77);

    malformed = authored;
    malformed.entryCount = 0;
    EXPECT(!IsWildEncounterProfileViewValid(&malformed));
    EXPECT(!TryGetWildEncounterProfileEntry(&malformed, 0, &entry));
    EXPECT_EQ(entry.species, SPECIES_ZUBAT);
    malformed = authored;
    malformed.totalWeight = 0;
    EXPECT(!IsWildEncounterProfileViewValid(&malformed));
    malformed = authored;
    malformed.encounterRate = 0;
    EXPECT(!IsWildEncounterProfileViewValid(&malformed));

    malformed = authored;
    malformed.legacyEntries = (void *)1;
    EXPECT(!IsWildEncounterProfileViewValid(&malformed));
    malformed = authored;
    malformed.authoredEntries = NULL;
    EXPECT(!IsWildEncounterProfileViewValid(&malformed));
    malformed = authored;
    malformed.source = (enum WildEncounterProfileSource)2;
    EXPECT(!IsWildEncounterProfileViewValid(&malformed));
    malformed = authored;
    malformed.area = WILD_AREA_HIDDEN;
    EXPECT(!IsWildEncounterProfileViewValid(&malformed));
    malformed = authored;
    malformed.fishingRod = OLD_ROD;
    EXPECT(!IsWildEncounterProfileViewValid(&malformed));

    invalidEntry = authored.authoredEntries[0];
    malformed = authored;
    malformed.entryCount = 1;
    malformed.totalWeight = invalidEntry.weight;
    malformed.authoredEntries = &invalidEntry;
    EXPECT(IsWildEncounterProfileViewValid(&malformed));
    invalidEntry.weight = 0;
    EXPECT(!IsWildEncounterProfileViewValid(&malformed));
    invalidEntry = authored.authoredEntries[0];
    malformed.totalWeight = invalidEntry.weight + 1;
    EXPECT(!IsWildEncounterProfileViewValid(&malformed));
    malformed.totalWeight = invalidEntry.weight;
    invalidEntry.maxLevel = MAX_LEVEL + 1;
    EXPECT(!IsWildEncounterProfileViewValid(&malformed));

    malformed = legacy;
    malformed.legacyStartIndex++;
    EXPECT(!IsWildEncounterProfileViewValid(&malformed));
    malformed = legacy;
    malformed.entryCount--;
    EXPECT(!IsWildEncounterProfileViewValid(&malformed));
    malformed = legacy;
    malformed.totalWeight--;
    EXPECT(!IsWildEncounterProfileViewValid(&malformed));
    malformed = legacy;
    malformed.authoredEntries = authored.authoredEntries;
    EXPECT(!IsWildEncounterProfileViewValid(&malformed));

    entry.species = SPECIES_ZUBAT;
    EXPECT(!TryGetWildEncounterProfileEntry(&authored, authored.entryCount, &entry));
    EXPECT_EQ(entry.species, SPECIES_ZUBAT);
    EXPECT(!TrySelectWildEncounterProfileEntry(&authored, authored.totalWeight, &entry));
    EXPECT_EQ(entry.species, SPECIES_ZUBAT);
    malformed = authored;
    malformed.entryCount = 0xFFFF;
    malformed.totalWeight = 1;
    EXPECT(!TryGetWildEncounterProfileEntry(&malformed, 0, &entry));
    EXPECT_EQ(entry.species, SPECIES_ZUBAT);

    EXPECT(!TrySelectWildEncounterLevel(&authored, &unrelatedEntry, 0, FALSE, &level));
    EXPECT_EQ(level, 77);

    malformed = authored;
    malformed.entryCount = 0;
    SeedRng(4321);
    expectedRandom = Random();
    SeedRng(4321);
    EXPECT(!TryGenerateWildMonFromProfile(&malformed, 0));
    actualRandom = Random();
    EXPECT_EQ(actualRandom, expectedRandom);
}

TEST("Resolver failures preserve outputs and queries consume no RNG")
{
    struct WildEncounterProfileView view = {.entryCount = 0x1234};
    u16 headerId = FindHeader(MAP_ROUTE101);
    u16 expectedRandom;
    u16 actualRandom;

    EXPECT(!TryResolveWildEncounterProfile(GetWildEncounterHeaderCount(), WILD_AREA_LAND, TIME_MORNING, WILD_ENCOUNTER_FISHING_ROD_NONE, WORLD_TIER_0, &view));
    EXPECT_EQ(view.entryCount, 0x1234);
    EXPECT(!TryResolveWildEncounterProfile(headerId, WILD_AREA_LAND, TIME_MORNING, OLD_ROD, WORLD_TIER_0, &view));
    EXPECT_EQ(view.entryCount, 0x1234);
    EXPECT(!TryResolveWildEncounterProfile(headerId, WILD_AREA_LAND, TIME_MORNING, WILD_ENCOUNTER_FISHING_ROD_NONE, WORLD_TIER_COUNT, &view));
    EXPECT_EQ(view.entryCount, 0x1234);
    EXPECT(!TryResolveWildEncounterProfile(headerId, WILD_AREA_LAND, TIME_MORNING, WILD_ENCOUNTER_FISHING_ROD_NONE, WORLD_TIER_0, NULL));

    SeedRng(1234);
    expectedRandom = Random();
    SeedRng(1234);
    EXPECT(TryResolveWildEncounterProfile(headerId, WILD_AREA_LAND, TIME_MORNING, WILD_ENCOUNTER_FISHING_ROD_NONE, WORLD_TIER_0, &view));
    actualRandom = Random();
    EXPECT_EQ(actualRandom, expectedRandom);
}
