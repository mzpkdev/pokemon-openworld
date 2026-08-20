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

static struct WildEncounterProfileView ResolveProfile(
    u16 map,
    enum WildPokemonArea area,
    enum TimeOfDay timeOfDay,
    u8 fishingRod)
{
    struct WildEncounterProfileView view = {0};

    EXPECT(TryResolveWildEncounterProfile(
        FindHeader(map), area, timeOfDay, fishingRod, &view));
    EXPECT(IsWildEncounterProfileViewValid(&view));
    return view;
}

TEST("Standard profiles expose authoritative raw slots for every ordinary method")
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
    u16 headerId = FindHeader(MAP_ROUTE32);
    u16 method;

    for (method = 0; method < ARRAY_COUNT(sMethods); method++)
    {
        const struct WildPokemonInfo *source = GetWildEncounterInfoAtTime(
            headerId, TIME_DAY, sMethods[method].area);
        struct WildEncounterProfileView view = ResolveProfile(
            MAP_ROUTE32, sMethods[method].area, TIME_DAY, sMethods[method].fishingRod);
        u16 index;

        EXPECT(source != NULL);
        EXPECT_EQ(view.context.headerId, headerId);
        EXPECT_EQ(view.context.area, sMethods[method].area);
        EXPECT_EQ(view.context.timeOfDay, TIME_DAY);
        EXPECT_EQ(view.context.fishingRod, sMethods[method].fishingRod);
        EXPECT_EQ(view.encounterRate, source->encounterRate);
        EXPECT(view.entries == source->wildPokemon);
        EXPECT(view.entryCount > 0);
        EXPECT(view.totalWeight > 0);
        for (index = 0; index < view.entryCount; index++)
        {
            struct WildEncounterSlot entry;
            const struct WildPokemon *raw = &source->wildPokemon[view.legacyStartIndex + index];

            EXPECT(TryGetWildEncounterProfileEntry(&view, index, &entry));
            EXPECT_EQ(entry.species, raw->species);
            EXPECT_EQ(entry.minLevel, min(raw->minLevel, raw->maxLevel));
            EXPECT_EQ(entry.maxLevel, max(raw->minLevel, raw->maxLevel));
            EXPECT(entry.weight > 0);
        }
    }
}

TEST("Raw standard slot selection and level rolls preserve their boundaries")
{
    struct WildEncounterProfileView view = ResolveProfile(
        MAP_ROUTE32, WILD_AREA_LAND, TIME_DAY, WILD_ENCOUNTER_FISHING_ROD_NONE);
    struct WildEncounterSlot first;
    struct WildEncounterSlot last;
    struct WildEncounterSlot selected = {SPECIES_NONE};
    u8 level = 0;
    u8 highest = 0;
    u16 index;

    EXPECT(TryGetWildEncounterProfileEntry(&view, 0, &first));
    EXPECT(TryGetWildEncounterProfileEntry(&view, view.entryCount - 1, &last));
    EXPECT(TrySelectWildEncounterProfileEntry(&view, 0, &selected));
    EXPECT_EQ(selected.species, first.species);
    EXPECT(TrySelectWildEncounterProfileEntry(&view, view.totalWeight - 1, &selected));
    EXPECT_EQ(selected.species, last.species);
    selected.species = SPECIES_ZUBAT;
    EXPECT(!TrySelectWildEncounterProfileEntry(&view, view.totalWeight, &selected));
    EXPECT_EQ(selected.species, SPECIES_ZUBAT);

    EXPECT(TrySelectWildEncounterLevel(&view, &first, 0, FALSE, &level));
    EXPECT_EQ(level, first.minLevel);
    EXPECT(TrySelectWildEncounterLevel(
        &view, &first, first.maxLevel - first.minLevel, FALSE, &level));
    EXPECT_EQ(level, first.maxLevel);
    for (index = 0; index < view.entryCount; index++)
    {
        struct WildEncounterSlot entry;

        EXPECT(TryGetWildEncounterProfileEntry(&view, index, &entry));
        highest = max(highest, entry.maxLevel);
    }
    EXPECT(TrySelectWildEncounterLevel(&view, &first, 0, TRUE, &level));
    EXPECT_EQ(level, min((u16)MAX_LEVEL, highest + 1));
}

TEST("Trainer Rating projection follows anchors, monotonicity, and the cap")
{
    struct WildEncounterProfileView view = ResolveProfile(
        MAP_ROUTE101, WILD_AREA_LAND, TIME_MORNING, WILD_ENCOUNTER_FISHING_ROD_NONE);
    struct WildEncounterSlotOutcome atZero = {0};
    struct WildEncounterSlotOutcome atEight = {0};
    struct WildEncounterSlotOutcome atSixteen = {0};
    struct WildEncounterSlotOutcome atCap = {0};
    struct WildEncounterSlotOutcome aboveCap = {0};

    EXPECT(ProjectWildSlotOutcome(SPECIES_WURMPLE, 2, 0, &view.context, &atZero));
    EXPECT(ProjectWildSlotOutcome(SPECIES_WURMPLE, 2, 8, &view.context, &atEight));
    EXPECT(ProjectWildSlotOutcome(SPECIES_WURMPLE, 2, 16, &view.context, &atSixteen));
    EXPECT(ProjectWildSlotOutcome(SPECIES_WURMPLE, 2, 80, &view.context, &atCap));
    EXPECT(ProjectWildSlotOutcome(SPECIES_WURMPLE, 2, UINT16_MAX, &view.context, &aboveCap));
    EXPECT_EQ(atZero.species, SPECIES_WURMPLE);
    EXPECT_EQ(atEight.species, SPECIES_WURMPLE);
    EXPECT_EQ(atSixteen.species, SPECIES_WURMPLE);
    EXPECT_EQ(atZero.level, 4);
    EXPECT_EQ(atEight.level, 7);
    EXPECT_EQ(atSixteen.level, 11);
    EXPECT(atZero.level <= atEight.level);
    EXPECT(atEight.level <= atSixteen.level);
    EXPECT_EQ(atCap.level, aboveCap.level);
    EXPECT(atCap.level >= atSixteen.level && atCap.level <= MAX_LEVEL);
}

TEST("Effective-slot helpers preserve projection and use only eligible weight")
{
    struct WildEncounterProfileView view = ResolveProfile(
        MAP_ROUTE32, WILD_AREA_WATER, TIME_DAY, WILD_ENCOUNTER_FISHING_ROD_NONE);
    struct WildEncounterSlot entry;
    struct WildEncounterSlot selected = {SPECIES_NONE};
    struct WildEncounterSlotOutcome direct;
    struct WildEncounterSlotOutcome throughProfile;
    u16 eligibleWeight;

    EXPECT(TryGetWildEncounterProfileEntry(&view, 0, &entry));
    EXPECT(ProjectWildSlotOutcome(
        entry.species, entry.minLevel, 8, &view.context, &direct));
    EXPECT(TryProjectWildEncounterProfileEntry(
        &view, 0, entry.minLevel, 8, &throughProfile));
    EXPECT_EQ(throughProfile.species, direct.species);
    EXPECT_EQ(throughProfile.level, direct.level);
    EXPECT(!TryProjectWildEncounterProfileEntry(
        &view, 0, entry.minLevel - 1, 8, &throughProfile));

    eligibleWeight = GetWildEncounterProfileEligibleWeight(&view, 8);
    EXPECT(eligibleWeight > 0 && eligibleWeight <= view.totalWeight);
    EXPECT(IsWildEncounterProfileEntryEligible(&view, 0, 8));
    EXPECT(TrySelectWildEncounterEligibleEntry(&view, 8, 0, &selected));
    EXPECT_NE(selected.species, SPECIES_NONE);
    selected.species = SPECIES_ZUBAT;
    EXPECT(!TrySelectWildEncounterEligibleEntry(&view, 8, eligibleWeight, &selected));
    EXPECT_EQ(selected.species, SPECIES_ZUBAT);
}

TEST("Resolver failures preserve outputs and all profile queries consume no RNG")
{
    struct WildEncounterProfileView view = {.entryCount = 0x1234};
    struct WildEncounterSlotOutcome outcome = {SPECIES_ZUBAT, 77};
    struct WildEncounterProfileView resolved;
    u16 headerId = FindHeader(MAP_ROUTE101);
    u16 expectedRandom;
    u16 actualRandom;

    EXPECT(!TryResolveWildEncounterProfile(
        GetWildEncounterHeaderCount(), WILD_AREA_LAND, TIME_MORNING,
        WILD_ENCOUNTER_FISHING_ROD_NONE, &view));
    EXPECT_EQ(view.entryCount, 0x1234);
    EXPECT(!TryResolveWildEncounterProfile(
        headerId, WILD_AREA_LAND, TIME_MORNING, OLD_ROD, &view));
    EXPECT_EQ(view.entryCount, 0x1234);
    EXPECT(!TryResolveWildEncounterProfile(
        headerId, WILD_AREA_HIDDEN, TIME_MORNING, WILD_ENCOUNTER_FISHING_ROD_NONE, &view));
    EXPECT_EQ(view.entryCount, 0x1234);
    EXPECT(!ProjectWildSlotOutcome(
        SPECIES_NONE, 1, 0, &view.context, &outcome));
    EXPECT_EQ(outcome.species, SPECIES_ZUBAT);
    EXPECT_EQ(outcome.level, 77);

    SeedRng(1234);
    expectedRandom = Random();
    SeedRng(1234);
    EXPECT(TryResolveWildEncounterProfile(
        headerId, WILD_AREA_LAND, TIME_MORNING, WILD_ENCOUNTER_FISHING_ROD_NONE, &resolved));
    EXPECT(IsWildEncounterProfileViewValid(&resolved));
    actualRandom = Random();
    EXPECT_EQ(actualRandom, expectedRandom);
}
