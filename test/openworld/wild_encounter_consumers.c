#include "global.h"
#include "battle.h"
#include "dexnav.h"
#include "event_data.h"
#include "event_object_movement.h"
#include "main.h"
#include "match_call.h"
#include "overworld.h"
#include "pokedex_area_screen.h"
#include "pokemon.h"
#include "random.h"
#include "script.h"
#include "task.h"
#include "trainer_rating.h"
#include "tv.h"
#include "wild_encounter.h"
#include "wild_encounter_ow.h"
#include "constants/game_stat.h"
#include "constants/maps.h"
#include "constants/metatile_behaviors.h"
#include "test/test.h"

static const u16 sTrainerRatingBadgeFacts[] =
{
    FLAG_REGIONAL_FACT_HOENN_STONE_BADGE,
    FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE,
    FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE,
    FLAG_REGIONAL_FACT_HOENN_KNUCKLE_BADGE,
    FLAG_REGIONAL_FACT_KANTO_BOULDER_BADGE,
    FLAG_REGIONAL_FACT_JOHTO_ZEPHYR_BADGE,
    FLAG_REGIONAL_FACT_HOENN_DYNAMO_BADGE,
    FLAG_REGIONAL_FACT_KANTO_MARSH_BADGE,
    FLAG_REGIONAL_FACT_HOENN_HEAT_BADGE,
    FLAG_REGIONAL_FACT_KANTO_RAINBOW_BADGE,
    FLAG_REGIONAL_FACT_JOHTO_PLAIN_BADGE,
    FLAG_REGIONAL_FACT_HOENN_BALANCE_BADGE,
    FLAG_REGIONAL_FACT_KANTO_SOUL_BADGE,
    FLAG_REGIONAL_FACT_JOHTO_FOG_BADGE,
    FLAG_REGIONAL_FACT_HOENN_FEATHER_BADGE,
    FLAG_REGIONAL_FACT_KANTO_THUNDER_BADGE,
    FLAG_REGIONAL_FACT_JOHTO_STORM_BADGE,
    FLAG_REGIONAL_FACT_HOENN_MIND_BADGE,
    FLAG_REGIONAL_FACT_HOENN_RAIN_BADGE,
    FLAG_REGIONAL_FACT_KANTO_VOLCANO_BADGE,
    FLAG_REGIONAL_FACT_JOHTO_RISING_BADGE,
};

struct EncounterConsumerState
{
    struct MapHeader mapHeader;
    struct ObjectEvent objectEvents[OBJECT_EVENTS_COUNT];
    struct PlayerAvatar playerAvatar;
    struct Pokemon enemyParty[PARTY_SIZE];
    rng_value_t rng;
    MainCallback savedCallback;
    u32 battleTypeFlags;
    u32 totalBattles;
    u32 wildBattles;
    u32 fishingEncounters;
    u16 dailyWilds;
    u16 repelSteps;
    u16 specialResult;
    bool8 ratingFacts[ARRAY_COUNT(sTrainerRatingBadgeFacts)];
    bool8 storyFact;
    bool8 isFishingEncounter;
    bool8 isSurfingEncounter;
    bool8 fieldControlsLocked;
    u8 chainFishingStreak;
    u8 mapGroup;
    u8 mapNum;
};

static void SaveEncounterConsumerState(struct EncounterConsumerState *state)
{
    u16 index;

    state->mapHeader = gMapHeader;
    memcpy(state->objectEvents, gObjectEvents, sizeof(state->objectEvents));
    state->playerAvatar = gPlayerAvatar;
    memcpy(state->enemyParty, gParties[B_TRAINER_OPPONENT_A], sizeof(state->enemyParty));
    state->rng = gRngValue;
    state->savedCallback = gMain.savedCallback;
    state->battleTypeFlags = gBattleTypeFlags;
    state->totalBattles = GetGameStat(GAME_STAT_TOTAL_BATTLES);
    state->wildBattles = GetGameStat(GAME_STAT_WILD_BATTLES);
    state->fishingEncounters = GetGameStat(GAME_STAT_FISHING_ENCOUNTERS);
    state->dailyWilds = VarGet(VAR_DAILY_WILDS);
    state->repelSteps = VarGet(VAR_REPEL_STEP_COUNT);
    state->specialResult = gSpecialVar_Result;
    for (index = 0; index < ARRAY_COUNT(sTrainerRatingBadgeFacts); index++)
        state->ratingFacts[index] = FlagGet(sTrainerRatingBadgeFacts[index]);
    state->storyFact = FlagGet(FLAG_REGIONAL_FACT_SEVII_DETOUR_FINISHED);
    state->isFishingEncounter = gIsFishingEncounter;
    state->isSurfingEncounter = gIsSurfingEncounter;
    state->fieldControlsLocked = ArePlayerFieldControlsLocked();
    state->chainFishingStreak = gChainFishingDexNavStreak;
    state->mapGroup = gSaveBlock1Ptr->location.mapGroup;
    state->mapNum = gSaveBlock1Ptr->location.mapNum;
}

static void RestoreFlag(u16 flag, bool8 value)
{
    if (value)
        FlagSet(flag);
    else
        FlagClear(flag);
}

static void RestoreEncounterConsumerState(const struct EncounterConsumerState *state)
{
    u16 index;

    UnfreezeObjectEvents();
    ResetTasks();
    if (state->fieldControlsLocked)
        LockPlayerFieldControls();
    else
        UnlockPlayerFieldControls();
    gMapHeader = state->mapHeader;
    memcpy(gObjectEvents, state->objectEvents, sizeof(state->objectEvents));
    gPlayerAvatar = state->playerAvatar;
    memcpy(gParties[B_TRAINER_OPPONENT_A], state->enemyParty, sizeof(state->enemyParty));
    gRngValue = state->rng;
    gMain.savedCallback = state->savedCallback;
    gBattleTypeFlags = state->battleTypeFlags;
    SetGameStat(GAME_STAT_TOTAL_BATTLES, state->totalBattles);
    SetGameStat(GAME_STAT_WILD_BATTLES, state->wildBattles);
    SetGameStat(GAME_STAT_FISHING_ENCOUNTERS, state->fishingEncounters);
    VarSet(VAR_DAILY_WILDS, state->dailyWilds);
    VarSet(VAR_REPEL_STEP_COUNT, state->repelSteps);
    gSpecialVar_Result = state->specialResult;
    for (index = 0; index < ARRAY_COUNT(sTrainerRatingBadgeFacts); index++)
        RestoreFlag(sTrainerRatingBadgeFacts[index], state->ratingFacts[index]);
    RestoreFlag(FLAG_REGIONAL_FACT_SEVII_DETOUR_FINISHED, state->storyFact);
    gIsFishingEncounter = state->isFishingEncounter;
    gIsSurfingEncounter = state->isSurfingEncounter;
    gChainFishingDexNavStreak = state->chainFishingStreak;
    gSaveBlock1Ptr->location.mapGroup = state->mapGroup;
    gSaveBlock1Ptr->location.mapNum = state->mapNum;
    SetPokemonAnglerSpecies(SPECIES_NONE);
}

static void EstablishEncounterConsumerFixture(void)
{
    UnfreezeObjectEvents();
    ResetTasks();
    UnlockPlayerFieldControls();
    memset(gObjectEvents, 0, sizeof(gObjectEvents));
    memset(&gPlayerAvatar, 0, sizeof(gPlayerAvatar));
    SetPokemonAnglerSpecies(SPECIES_NONE);
}

static void LoadMap(u16 map)
{
    gSaveBlock1Ptr->location.mapGroup = MAP_GROUP(map);
    gSaveBlock1Ptr->location.mapNum = MAP_NUM(map);
    gMapHeader = *Overworld_GetMapHeaderByGroupAndId(MAP_GROUP(map), MAP_NUM(map));
}

static void SetTrainerRatingBadgeCount(u16 count)
{
    u16 index;

    for (index = 0; index < ARRAY_COUNT(sTrainerRatingBadgeFacts); index++)
        RestoreFlag(sTrainerRatingBadgeFacts[index], index < count);
    FlagClear(FLAG_REGIONAL_FACT_SEVII_DETOUR_FINISHED);
}

static void PrepareMap(u16 map)
{
    EstablishEncounterConsumerFixture();
    LoadMap(map);
    VarSet(VAR_REPEL_STEP_COUNT, 0);
    gIsFishingEncounter = FALSE;
    gIsSurfingEncounter = FALSE;
    gSpecialVar_Result = FALSE;
    SetTrainerRatingBadgeCount(0);
}

static bool8 TrySelectExpectedMatchCallProfileSpecies(
    const struct WildEncounterProfileView *profile,
    u16 trainerRating,
    bool8 rollVanillaLevel,
    enum Species *species)
{
    struct WildEncounterSlot entry;
    struct WildEncounterSlotOutcome outcome;
    u16 eligibleWeight = GetWildEncounterProfileEligibleWeight(profile, trainerRating);
    u8 vanillaLevel;

    if (eligibleWeight == 0
     || !TrySelectWildEncounterEligibleEntry(
         profile, trainerRating, Random() % eligibleWeight, &entry))
        return FALSE;
    vanillaLevel = entry.minLevel;
    if (rollVanillaLevel)
        vanillaLevel += Random() % (entry.maxLevel - entry.minLevel + 1);
    if (!ProjectWildSlotOutcome(
        entry.species, vanillaLevel, trainerRating, &profile->context, &outcome))
        return FALSE;
    *species = outcome.species;
    return TRUE;
}

static enum Species SelectExpectedMatchCallSpecies(u16 map, bool8 rollVanillaLevel)
{
    enum Species species[2];
    struct WildEncounterProfileView profile;
    enum Species selectedSpecies;
    enum TimeOfDay timeOfDay;
    u16 headerId;
    u16 trainerRating;
    u8 numSpecies = 0;

    if (!TryFindWildEncounterHeader(MAP_GROUP(map), MAP_NUM(map), &headerId))
        return SPECIES_NONE;

    trainerRating = TrainerRating_Get();
    timeOfDay = GetTimeOfDayForEncounters(headerId, WILD_AREA_LAND);
    if (TryResolveWildEncounterProfile(
        headerId, WILD_AREA_LAND, timeOfDay, WILD_ENCOUNTER_FISHING_ROD_NONE, &profile)
     && TrySelectExpectedMatchCallProfileSpecies(
         &profile, trainerRating, rollVanillaLevel, &selectedSpecies))
        species[numSpecies++] = selectedSpecies;

    timeOfDay = GetTimeOfDayForEncounters(headerId, WILD_AREA_WATER);
    if (TryResolveWildEncounterProfile(
        headerId, WILD_AREA_WATER, timeOfDay, WILD_ENCOUNTER_FISHING_ROD_NONE, &profile)
     && TrySelectExpectedMatchCallProfileSpecies(
         &profile, trainerRating, rollVanillaLevel, &selectedSpecies))
        species[numSpecies++] = selectedSpecies;

    if (numSpecies == 0)
        return SPECIES_NONE;
    return species[Random() % numSpecies];
}

TEST("Walking and fishing project the same source profile from Trainer Rating")
{
    struct EncounterConsumerState saved;
    u8 walkingLow;
    u8 walkingHigh;
    u8 fishingLow;
    u8 fishingHigh;

    EstablishEncounterConsumerFixture();
    SaveEncounterConsumerState(&saved);

    PrepareMap(MAP_ROUTE101);
    EXPECT_EQ(TrainerRating_Get(), 0);
    SeedRng(1234);
    EXPECT(StandardWildEncounter_Debug());
    walkingLow = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);

    PrepareMap(MAP_ROUTE101);
    SetTrainerRatingBadgeCount(8);
    EXPECT_EQ(TrainerRating_Get(), 24);
    SeedRng(1234);
    EXPECT(StandardWildEncounter_Debug());
    walkingHigh = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);

    PrepareMap(MAP_VERMILION_CITY);
    SeedRng(4321);
    FishingWildEncounter(OLD_ROD);
    fishingLow = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);

    PrepareMap(MAP_VERMILION_CITY);
    SetTrainerRatingBadgeCount(8);
    SeedRng(4321);
    FishingWildEncounter(OLD_ROD);
    fishingHigh = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);

    EXPECT(walkingLow >= 1 && walkingLow <= MAX_LEVEL);
    EXPECT(walkingHigh >= walkingLow && walkingHigh <= MAX_LEVEL);
    EXPECT(fishingLow >= 1 && fishingLow <= MAX_LEVEL);
    EXPECT(fishingHigh >= fishingLow && fishingHigh <= MAX_LEVEL);
    RestoreEncounterConsumerState(&saved);
}

TEST("Ordinary walking Surf Rock Smash Sweet Scent and rods use standard profiles")
{
    static const u8 sRods[] = {OLD_ROD, GOOD_ROD, SUPER_ROD};
    struct EncounterConsumerState saved;
    bool8 generated = FALSE;
    u16 index;

    EstablishEncounterConsumerFixture();
    SaveEncounterConsumerState(&saved);

    PrepareMap(MAP_ROUTE32);
    SeedRng(0x1234);
    for (index = 0; index < 512 && !generated; index++)
        generated = StandardWildEncounter(MB_TALL_GRASS, MB_TALL_GRASS);
    EXPECT(generated);
    EXPECT(!gIsSurfingEncounter);

    PrepareMap(MAP_ROUTE32);
    generated = FALSE;
    SeedRng(0x2345);
    for (index = 0; index < 512 && !generated; index++)
        generated = StandardWildEncounter(MB_POND_WATER, MB_POND_WATER);
    EXPECT(generated);
    EXPECT(gIsSurfingEncounter);

    PrepareMap(MAP_ROUTE32);
    SeedRng(0x3456);
    for (index = 0; index < 64 && !gSpecialVar_Result; index++)
        RockSmashWildEncounter();
    EXPECT(gSpecialVar_Result);

    PrepareMap(MAP_ROUTE32);
    SeedRng(0x4567);
    EXPECT(SweetScentWildEncounterForTesting(WILD_AREA_LAND));
    EXPECT(GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL) <= MAX_LEVEL);

    for (index = 0; index < ARRAY_COUNT(sRods); index++)
    {
        PrepareMap(MAP_ROUTE32);
        SeedRng(0x6000 + index);
        FishingWildEncounter(sRods[index]);
        EXPECT(gIsFishingEncounter);
        EXPECT_NE(GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES), SPECIES_NONE);
    }

    PrepareMap(MAP_ROUTE32);
    EXPECT(DoesCurrentMapHaveFishingMons());
    LoadMap(MAP_NATIONAL_PARK_BUG_CONTEST);
    EXPECT(!DoesCurrentMapHaveFishingMons());
    RestoreEncounterConsumerState(&saved);
}

TEST("DexNav previews and overworld use the effective standard population")
{
    struct EncounterConsumerState saved;
    enum Species species;
    bool8 isWater;
    u8 dexNavLow;
    u8 dexNavHigh;

    EstablishEncounterConsumerFixture();
    SaveEncounterConsumerState(&saved);

    PrepareMap(MAP_ROUTE32);
    SeedRng(0x6789);
    dexNavLow = DexNav_GetEncounterLevelFromMapDataForTesting(
        SPECIES_TENTACOOL, ENCOUNTER_TYPE_WATER);
    SetTrainerRatingBadgeCount(8);
    SeedRng(0x6789);
    dexNavHigh = DexNav_GetEncounterLevelFromMapDataForTesting(
        SPECIES_TENTACOOL, ENCOUNTER_TYPE_WATER);
    EXPECT(dexNavLow >= 1 && dexNavLow <= MAX_LEVEL);
    EXPECT(dexNavHigh >= dexNavLow && dexNavHigh <= MAX_LEVEL);

    SetTrainerRatingBadgeCount(0);
    SeedRng(0x789A);
    species = GetLocalWildMon(&isWater);
    EXPECT_NE(species, SPECIES_NONE);
    SeedRng(0x89AB);
    EXPECT_NE(GetLocalWaterMon(), SPECIES_NONE);

    EXPECT(PokedexArea_MapHasSpeciesForTesting(
        MAP_GROUP(MAP_ROUTE32), MAP_NUM(MAP_ROUTE32), TIME_DAY, SPECIES_MAREEP));
    EXPECT(PokedexArea_MapHasSpeciesForTesting(
        MAP_GROUP(MAP_ROUTE32), MAP_NUM(MAP_ROUTE32), TIME_DAY, SPECIES_QWILFISH));
    EXPECT(PokedexArea_MapHasSpeciesForTesting(
        MAP_GROUP(MAP_ROUTE32), MAP_NUM(MAP_ROUTE32), TIME_DAY, SPECIES_PINECO));

    PrepareMap(MAP_ROUTE32);
    EXPECT(OWE_CheckCurrentWildMonHeaderForTesting(FALSE));
    EXPECT(OWE_CheckCurrentWildMonHeaderForTesting(TRUE));
    SeedRng(0xABCD);
    EXPECT(OWE_GenerateCurrentWildMonForTesting(FALSE));
    EXPECT_NE(GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES), SPECIES_NONE);
    SeedRng(0xBCDE);
    EXPECT(OWE_GenerateCurrentWildMonForTesting(TRUE));
    EXPECT_NE(GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES), SPECIES_NONE);

    LoadMap(MAP_NATIONAL_PARK_BUG_CONTEST);
    EXPECT(!OWE_CheckCurrentWildMonHeaderForTesting(FALSE));
    EXPECT(!OWE_CheckCurrentWildMonHeaderForTesting(TRUE));
    RestoreEncounterConsumerState(&saved);
}

TEST("Match Call projects a selected slot's rolled vanilla level")
{
    struct EncounterConsumerState saved;
    enum Species expectedSpecies;
    enum Species minimumLevelSpecies;
    enum Species species;
    u32 seed;
    bool8 foundDifferentOutcome = FALSE;

    EstablishEncounterConsumerFixture();
    SaveEncounterConsumerState(&saved);
    PrepareMap(MAP_SAFARI_ZONE_NORTHWEST);

    for (seed = 1; seed <= 512; seed++)
    {
        SeedRng(seed);
        expectedSpecies = SelectExpectedMatchCallSpecies(
            MAP_SAFARI_ZONE_NORTHWEST, TRUE);
        SeedRng(seed);
        minimumLevelSpecies = SelectExpectedMatchCallSpecies(
            MAP_SAFARI_ZONE_NORTHWEST, FALSE);
        if (expectedSpecies != minimumLevelSpecies)
        {
            foundDifferentOutcome = TRUE;
            break;
        }
    }

    EXPECT(foundDifferentOutcome);
    if (foundDifferentOutcome)
    {
        SeedRng(seed);
        species = MatchCall_SelectSpeciesFromLocationForTesting(
            MAP_GROUP(MAP_SAFARI_ZONE_NORTHWEST), MAP_NUM(MAP_SAFARI_ZONE_NORTHWEST));
        EXPECT_EQ(species, expectedSpecies);
    }

    RestoreEncounterConsumerState(&saved);
}

TEST("DexNav standard selection projects its rolled slot level")
{
    struct EncounterConsumerState saved;
    struct WildEncounterProfileView profile;
    struct WildEncounterSlot entry;
    struct WildEncounterSlotOutcome expected;
    enum Species species;
    u8 level;
    u16 headerId;
    u16 trainerRating;
    u16 eligibleWeight;
    u32 seed;

    EstablishEncounterConsumerFixture();
    SaveEncounterConsumerState(&saved);
    PrepareMap(MAP_ROUTE32);
    SetTrainerRatingBadgeCount(8);

    headerId = GetCurrentMapWildMonHeaderId();
    EXPECT_NE(headerId, HEADER_NONE);
    EXPECT(TryResolveWildEncounterProfile(
        headerId,
        WILD_AREA_WATER,
        GetTimeOfDayForEncounters(headerId, WILD_AREA_WATER),
        WILD_ENCOUNTER_FISHING_ROD_NONE,
        &profile));
    trainerRating = TrainerRating_Get();
    eligibleWeight = GetWildEncounterProfileEligibleWeight(&profile, trainerRating);
    EXPECT(eligibleWeight != 0);

    for (seed = 1; seed <= 32; seed++)
    {
        u8 vanillaLevel;

        SeedRng(seed);
        EXPECT(TrySelectWildEncounterEligibleEntry(
            &profile, trainerRating, Random() % eligibleWeight, &entry));
        vanillaLevel = RandomUniform(
            RNG_DEXNAV_ENCOUNTER_LEVEL, entry.minLevel, entry.maxLevel);
        EXPECT(ProjectWildSlotOutcome(
            entry.species, vanillaLevel, trainerRating, &profile.context, &expected));

        SeedRng(seed);
        EXPECT(DexNav_TrySelectProfileOutcomeForTesting(WILD_AREA_WATER, &species, &level));
        EXPECT_EQ(species, expected.species);
        EXPECT_EQ(level, expected.level);
    }

    RestoreEncounterConsumerState(&saved);
}

TEST("Local water selection projects the rolled source level")
{
    struct EncounterConsumerState saved;
    struct WildEncounterProfileView profile;
    struct WildEncounterSlot entry;
    struct WildEncounterSlotOutcome atMinimum;
    struct WildEncounterSlotOutcome atRolledLevel;
    struct Pokemon playerParty[PARTY_SIZE];
    enum Species species;
    enum TimeOfDay timeOfDay;
    u16 headerId;
    u16 eligibleWeight;
    u32 seed;
    bool8 foundVaryingOutcome = FALSE;

    EstablishEncounterConsumerFixture();
    SaveEncounterConsumerState(&saved);
    memcpy(playerParty, gParties[B_TRAINER_PLAYER], sizeof(playerParty));
    ZeroPartyMons(gParties[B_TRAINER_PLAYER]);
    PrepareMap(MAP_SAFARI_ZONE_NORTHWEST);

    headerId = GetCurrentMapWildMonHeaderId();
    timeOfDay = GetTimeOfDayForEncounters(headerId, WILD_AREA_WATER);
    EXPECT(TryResolveWildEncounterProfile(
        headerId, WILD_AREA_WATER, timeOfDay, WILD_ENCOUNTER_FISHING_ROD_NONE, &profile));
    eligibleWeight = GetWildEncounterProfileEligibleWeight(&profile, TrainerRating_Get());
    EXPECT_NE(eligibleWeight, 0);

    for (seed = 1; seed <= 512 && !foundVaryingOutcome; seed++)
    {
        u8 vanillaLevel;

        SeedRng(seed);
        EXPECT(TrySelectWildEncounterEligibleEntry(
            &profile, TrainerRating_Get(), Random() % eligibleWeight, &entry));
        EXPECT(TrySelectWildEncounterLevel(
            &profile, &entry,
            Random() % (entry.maxLevel - entry.minLevel + 1),
            FALSE, &vanillaLevel));
        EXPECT(ProjectWildSlotOutcome(
            entry.species, entry.minLevel, TrainerRating_Get(), &profile.context, &atMinimum));
        EXPECT(ProjectWildSlotOutcome(
            entry.species, vanillaLevel, TrainerRating_Get(), &profile.context, &atRolledLevel));

        if (atMinimum.species != atRolledLevel.species)
        {
            SeedRng(seed);
            species = GetLocalWaterMon();
            EXPECT_EQ(species, atRolledLevel.species);
            foundVaryingOutcome = TRUE;
        }
    }

    EXPECT(foundVaryingOutcome);
    memcpy(gParties[B_TRAINER_PLAYER], playerParty, sizeof(playerParty));
    RestoreEncounterConsumerState(&saved);
}
