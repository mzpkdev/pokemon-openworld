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
#include "tv.h"
#include "wild_encounter.h"
#include "wild_encounter_ow.h"
#include "world_tier.h"
#include "constants/game_stat.h"
#include "constants/maps.h"
#include "constants/metatile_behaviors.h"
#include "test/test.h"

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
    bool8 stoneBadge;
    bool8 cascadeBadge;
    bool8 hiveBadge;
    bool8 isFishingEncounter;
    bool8 isSurfingEncounter;
    bool8 fieldControlsLocked;
    u8 chainFishingStreak;
    u8 mapGroup;
    u8 mapNum;
};

static const enum Species sRoute32LandSpecies[] =
{
    SPECIES_MAREEP,
    SPECIES_WOOPER,
    SPECIES_EKANS,
    SPECIES_PIDGEY,
    SPECIES_BELLSPROUT,
    SPECIES_ZUBAT,
    SPECIES_GASTLY,
};

static const enum Species sRoute32WaterSpecies[] =
{
    SPECIES_TENTACOOL,
    SPECIES_QUAGSIRE,
    SPECIES_TENTACRUEL,
};

static const enum Species sRoute32RockSpecies[] =
{
    SPECIES_PINECO,
    SPECIES_EXEGGCUTE,
    SPECIES_EKANS,
};

static void SaveEncounterConsumerState(struct EncounterConsumerState *state)
{
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
    state->stoneBadge = FlagGet(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE);
    state->cascadeBadge = FlagGet(FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE);
    state->hiveBadge = FlagGet(FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE);
    state->isFishingEncounter = gIsFishingEncounter;
    state->isSurfingEncounter = gIsSurfingEncounter;
    state->fieldControlsLocked = ArePlayerFieldControlsLocked();
    state->chainFishingStreak = gChainFishingDexNavStreak;
    state->mapGroup = gSaveBlock1Ptr->location.mapGroup;
    state->mapNum = gSaveBlock1Ptr->location.mapNum;
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

static void RestoreFlag(u16 flag, bool8 value)
{
    if (value)
        FlagSet(flag);
    else
        FlagClear(flag);
}

static void RestoreEncounterConsumerState(const struct EncounterConsumerState *state)
{
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
    RestoreFlag(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE, state->stoneBadge);
    RestoreFlag(FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE, state->cascadeBadge);
    RestoreFlag(FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE, state->hiveBadge);
    gIsFishingEncounter = state->isFishingEncounter;
    gIsSurfingEncounter = state->isSurfingEncounter;
    gChainFishingDexNavStreak = state->chainFishingStreak;
    gSaveBlock1Ptr->location.mapGroup = state->mapGroup;
    gSaveBlock1Ptr->location.mapNum = state->mapNum;
    // FishingWildEncounter only writes the private angler species. Attempt
    // counters are updated by RecordFishingAttemptForTV, which this route does not call.
    SetPokemonAnglerSpecies(SPECIES_NONE);
}

static void LoadMap(u16 map)
{
    gSaveBlock1Ptr->location.mapGroup = MAP_GROUP(map);
    gSaveBlock1Ptr->location.mapNum = MAP_NUM(map);
    gMapHeader = *Overworld_GetMapHeaderByGroupAndId(MAP_GROUP(map), MAP_NUM(map));
}

static void SetWorldTierOne(bool8 enabled)
{
    FlagClear(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE);
    FlagClear(FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE);
    FlagClear(FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE);
    if (enabled)
        FlagSet(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE);
}

static bool32 SpeciesIsOneOf(enum Species species, const enum Species *expected, u16 count)
{
    u16 i;

    for (i = 0; i < count; i++)
    {
        if (species == expected[i])
            return TRUE;
    }
    return FALSE;
}

static void PrepareJohtoConsumerMap(u16 map)
{
    EstablishEncounterConsumerFixture();
    LoadMap(map);
    VarSet(VAR_REPEL_STEP_COUNT, 0);
    gIsFishingEncounter = FALSE;
    gIsSurfingEncounter = FALSE;
    gSpecialVar_Result = FALSE;
}

TEST("Standard wild encounters consume Route 101's resolved world tier")
{
    struct EncounterConsumerState saved;
    enum Species tier0Species;
    enum Species tier1Species;
    enum WorldTier tier0;
    enum WorldTier tier1;
    bool8 tier0Generated;
    bool8 tier1Generated;
    u8 tier0Level;
    u8 tier1Level;

    EstablishEncounterConsumerFixture();
    SaveEncounterConsumerState(&saved);
    LoadMap(MAP_ROUTE101);

    SetWorldTierOne(FALSE);
    tier0 = WorldTier_Get();
    SeedRng(1234);
    tier0Generated = StandardWildEncounter_Debug();
    tier0Species = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
    tier0Level = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);
    RestoreEncounterConsumerState(&saved);
    LoadMap(MAP_ROUTE101);

    SetWorldTierOne(TRUE);
    tier1 = WorldTier_Get();
    SeedRng(1234);
    tier1Generated = StandardWildEncounter_Debug();
    tier1Species = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
    tier1Level = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);

    RestoreEncounterConsumerState(&saved);

    EXPECT_EQ(tier0, WORLD_TIER_0);
    EXPECT_EQ(tier1, WORLD_TIER_1);
    EXPECT(tier0Generated);
    EXPECT(tier1Generated);
    EXPECT_EQ(tier0Species, SPECIES_WURMPLE);
    EXPECT_EQ(tier1Species, SPECIES_WURMPLE);
    EXPECT(tier0Level >= 2 && tier0Level <= 3);
    EXPECT(tier1Level >= 10 && tier1Level <= 14);
}

TEST("Fishing encounters consume Vermilion's resolved old rod world tier")
{
    struct EncounterConsumerState saved;
    enum WorldTier tier0;
    enum WorldTier tier1;
    enum Species tier0Species;
    enum Species tier1Species;
    u8 tier0Level;
    u8 tier1Level;

    EstablishEncounterConsumerFixture();
    SaveEncounterConsumerState(&saved);
    LoadMap(MAP_VERMILION_CITY);

    SetWorldTierOne(FALSE);
    tier0 = WorldTier_Get();
    SeedRng(1234);
    FishingWildEncounter(OLD_ROD);
    tier0Species = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
    tier0Level = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);
    RestoreEncounterConsumerState(&saved);
    LoadMap(MAP_VERMILION_CITY);

    SetWorldTierOne(TRUE);
    tier1 = WorldTier_Get();
    SeedRng(1234);
    FishingWildEncounter(OLD_ROD);
    tier1Species = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
    tier1Level = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);

    RestoreEncounterConsumerState(&saved);

    EXPECT_EQ(tier0, WORLD_TIER_0);
    EXPECT_EQ(tier1, WORLD_TIER_1);
    EXPECT_EQ(tier0Species, SPECIES_MAGIKARP);
    EXPECT_EQ(tier1Species, SPECIES_MAGIKARP);
    EXPECT(tier0Level >= 4 && tier0Level <= 8);
    EXPECT(tier1Level >= 10 && tier1Level <= 14);
}

TEST("Fishing availability consumes Johto's resolved standard profile")
{
    struct EncounterConsumerState saved;

    EstablishEncounterConsumerFixture();
    SaveEncounterConsumerState(&saved);

    LoadMap(MAP_ROUTE32);
    EXPECT(DoesCurrentMapHaveFishingMons());

    LoadMap(MAP_NATIONAL_PARK_BUG_CONTEST);
    EXPECT(!DoesCurrentMapHaveFishingMons());

    RestoreEncounterConsumerState(&saved);
}

TEST("Johto walking Surf and Rock Smash consume their standard methods")
{
    struct EncounterConsumerState saved;
    enum Species species;
    bool8 generated = FALSE;
    u16 i;
    u8 level;

    EstablishEncounterConsumerFixture();
    SaveEncounterConsumerState(&saved);

    PrepareJohtoConsumerMap(MAP_ROUTE32);
    SeedRng(0x1234);
    for (i = 0; i < 512 && !generated; i++)
        generated = StandardWildEncounter(MB_TALL_GRASS, MB_TALL_GRASS);
    species = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
    level = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);
    EXPECT(generated);
    EXPECT(SpeciesIsOneOf(species, sRoute32LandSpecies, ARRAY_COUNT(sRoute32LandSpecies)));
    EXPECT(level >= 5 && level <= 7);
    EXPECT(!gIsSurfingEncounter);

    RestoreEncounterConsumerState(&saved);
    PrepareJohtoConsumerMap(MAP_ROUTE32);
    SeedRng(0x2345);
    generated = FALSE;
    for (i = 0; i < 512 && !generated; i++)
        generated = StandardWildEncounter(MB_POND_WATER, MB_POND_WATER);
    species = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
    level = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);
    EXPECT(generated);
    EXPECT(SpeciesIsOneOf(species, sRoute32WaterSpecies, ARRAY_COUNT(sRoute32WaterSpecies)));
    EXPECT(level >= 15 && level <= 24);
    EXPECT(gIsSurfingEncounter);

    RestoreEncounterConsumerState(&saved);
    PrepareJohtoConsumerMap(MAP_ROUTE32);
    SeedRng(0x3456);
    for (i = 0; i < 64 && !gSpecialVar_Result; i++)
        RockSmashWildEncounter();
    species = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
    level = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);
    EXPECT(gSpecialVar_Result);
    EXPECT(SpeciesIsOneOf(species, sRoute32RockSpecies, ARRAY_COUNT(sRoute32RockSpecies)));
    EXPECT_EQ(level, 10);

    RestoreEncounterConsumerState(&saved);
}

TEST("Johto Sweet Scent consumes standard land and water methods")
{
    struct EncounterConsumerState saved;
    enum Species species;
    u8 level;

    EstablishEncounterConsumerFixture();
    SaveEncounterConsumerState(&saved);

    PrepareJohtoConsumerMap(MAP_ROUTE32);
    SeedRng(0x4567);
    EXPECT(SweetScentWildEncounterForTesting(WILD_AREA_LAND));
    species = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
    level = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);
    EXPECT(SpeciesIsOneOf(species, sRoute32LandSpecies, ARRAY_COUNT(sRoute32LandSpecies)));
    EXPECT(level >= 5 && level <= 7);

    RestoreEncounterConsumerState(&saved);
    PrepareJohtoConsumerMap(MAP_ROUTE32);
    SeedRng(0x5678);
    EXPECT(SweetScentWildEncounterForTesting(WILD_AREA_WATER));
    species = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
    level = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);
    EXPECT(SpeciesIsOneOf(species, sRoute32WaterSpecies, ARRAY_COUNT(sRoute32WaterSpecies)));
    EXPECT(level >= 15 && level <= 24);

    RestoreEncounterConsumerState(&saved);
}

TEST("Johto fishing consumes each standard rod group")
{
    static const struct
    {
        u8 rod;
        enum Species species[3];
        u8 speciesCount;
        u8 levels[3];
        u8 levelCount;
    } sCases[] =
    {
        {OLD_ROD,   {SPECIES_MAGIKARP, SPECIES_TENTACOOL},                  2, {10},         1},
        {GOOD_ROD,  {SPECIES_TENTACOOL, SPECIES_MAGIKARP, SPECIES_QWILFISH}, 3, {20},         1},
        {SUPER_ROD, {SPECIES_MAGIKARP, SPECIES_QWILFISH, SPECIES_TENTACOOL}, 3, {10, 20, 40}, 3},
    };
    struct EncounterConsumerState saved;
    u16 i;

    EstablishEncounterConsumerFixture();
    SaveEncounterConsumerState(&saved);

    for (i = 0; i < ARRAY_COUNT(sCases); i++)
    {
        enum Species species;
        bool32 levelMatches = FALSE;
        u16 j;
        u8 level;

        RestoreEncounterConsumerState(&saved);
        PrepareJohtoConsumerMap(MAP_ROUTE32);
        SeedRng(0x6000 + i);
        FishingWildEncounter(sCases[i].rod);
        species = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
        level = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);
        for (j = 0; j < sCases[i].levelCount; j++)
        {
            if (level == sCases[i].levels[j])
                levelMatches = TRUE;
        }

        EXPECT(gIsFishingEncounter);
        EXPECT(SpeciesIsOneOf(species, sCases[i].species, sCases[i].speciesCount));
        EXPECT(levelMatches);
    }

    RestoreEncounterConsumerState(&saved);
}

TEST("Johto DexNav and local species queries retain vanilla standard rows")
{
    struct EncounterConsumerState saved;
    enum Species species;
    bool8 isWater;
    u8 tier0Level;
    u8 tier3Level;

    EstablishEncounterConsumerFixture();
    SaveEncounterConsumerState(&saved);
    PrepareJohtoConsumerMap(MAP_ROUTE32);

    SetWorldTierOne(FALSE);
    SeedRng(0x6789);
    tier0Level = DexNav_GetEncounterLevelFromMapDataForTesting(SPECIES_TENTACOOL, ENCOUNTER_TYPE_WATER);
    FlagSet(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE);
    FlagSet(FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE);
    FlagSet(FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE);
    SeedRng(0x6789);
    tier3Level = DexNav_GetEncounterLevelFromMapDataForTesting(SPECIES_TENTACOOL, ENCOUNTER_TYPE_WATER);
    EXPECT_EQ(tier3Level, tier0Level);
    EXPECT(tier0Level >= 15 && tier0Level <= 19);

    SeedRng(0x789A);
    species = GetLocalWildMon(&isWater);
    EXPECT(SpeciesIsOneOf(species, isWater ? sRoute32WaterSpecies : sRoute32LandSpecies,
        isWater ? ARRAY_COUNT(sRoute32WaterSpecies) : ARRAY_COUNT(sRoute32LandSpecies)));
    SeedRng(0x89AB);
    species = GetLocalWaterMon();
    EXPECT(SpeciesIsOneOf(species, sRoute32WaterSpecies, ARRAY_COUNT(sRoute32WaterSpecies)));

    RestoreEncounterConsumerState(&saved);
}

TEST("Johto Pokedex Match Call and visible encounters consume standard profiles")
{
    static const enum Species sRoute29Species[] =
    {
        SPECIES_PIDGEY,
        SPECIES_SENTRET,
        SPECIES_HOPPIP,
        SPECIES_RATTATA,
        SPECIES_HOOTHOOT,
        SPECIES_SPINARAK,
        SPECIES_ZUBAT,
    };
    struct EncounterConsumerState saved;
    enum Species species;
    u8 level;

    EstablishEncounterConsumerFixture();
    SaveEncounterConsumerState(&saved);

    EXPECT(PokedexArea_MapHasSpeciesForTesting(MAP_GROUP(MAP_ROUTE32), MAP_NUM(MAP_ROUTE32), TIME_DAY, SPECIES_MAREEP));
    EXPECT(PokedexArea_MapHasSpeciesForTesting(MAP_GROUP(MAP_ROUTE32), MAP_NUM(MAP_ROUTE32), TIME_DAY, SPECIES_QWILFISH));
    EXPECT(PokedexArea_MapHasSpeciesForTesting(MAP_GROUP(MAP_ROUTE32), MAP_NUM(MAP_ROUTE32), TIME_DAY, SPECIES_PINECO));
    EXPECT(!PokedexArea_MapHasSpeciesForTesting(MAP_GROUP(MAP_ROUTE32), MAP_NUM(MAP_ROUTE32), TIME_DAY, SPECIES_MEWTWO));

    SeedRng(0x9ABC);
    species = MatchCall_SelectSpeciesFromLocationForTesting(MAP_GROUP(MAP_ROUTE29), MAP_NUM(MAP_ROUTE29));
    EXPECT(SpeciesIsOneOf(species, sRoute29Species, ARRAY_COUNT(sRoute29Species)));

    PrepareJohtoConsumerMap(MAP_ROUTE32);
    EXPECT(OWE_CheckCurrentWildMonHeaderForTesting(FALSE));
    EXPECT(OWE_CheckCurrentWildMonHeaderForTesting(TRUE));
    SeedRng(0xABCD);
    EXPECT(OWE_GenerateCurrentWildMonForTesting(FALSE));
    species = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
    level = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);
    EXPECT(SpeciesIsOneOf(species, sRoute32LandSpecies, ARRAY_COUNT(sRoute32LandSpecies)));
    EXPECT(level >= 5 && level <= 7);
    SeedRng(0xBCDE);
    EXPECT(OWE_GenerateCurrentWildMonForTesting(TRUE));
    species = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
    level = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);
    EXPECT(SpeciesIsOneOf(species, sRoute32WaterSpecies, ARRAY_COUNT(sRoute32WaterSpecies)));
    EXPECT(level >= 15 && level <= 24);

    LoadMap(MAP_NATIONAL_PARK_BUG_CONTEST);
    EXPECT(!OWE_CheckCurrentWildMonHeaderForTesting(FALSE));
    EXPECT(!OWE_CheckCurrentWildMonHeaderForTesting(TRUE));

    RestoreEncounterConsumerState(&saved);
}

static void ExpectResolvedLegacyGenerationParity(u16 map, u16 seed)
{
    struct EncounterConsumerState saved;
    struct WildEncounterProfileView profile = {0};
    const struct WildPokemonInfo *legacyInfo;
    enum Species directSpecies = SPECIES_NONE;
    enum Species routedSpecies = SPECIES_NONE;
    u32 directPersonality = 0;
    u32 routedPersonality = 0;
    u16 directNextRandom = 0;
    u16 routedNextRandom = 0;
    u8 directLevel = 0;
    u8 routedLevel = 0;
    u16 headerId = HEADER_NONE;
    enum TimeOfDay timeOfDay;
    bool32 found;
    bool32 resolved = FALSE;
    bool8 directGenerated = FALSE;
    bool8 routedGenerated = FALSE;

    EstablishEncounterConsumerFixture();
    SaveEncounterConsumerState(&saved);
    LoadMap(map);
    found = TryFindWildEncounterHeader(MAP_GROUP(map), MAP_NUM(map), &headerId);
    if (found)
    {
        timeOfDay = GetTimeOfDayForEncounters(headerId, WILD_AREA_LAND);
        legacyInfo = GetWildEncounterInfoAtTime(headerId, timeOfDay, WILD_AREA_LAND);
        if (legacyInfo != NULL)
        {
            resolved = TryResolveWildEncounterProfile(headerId, WILD_AREA_LAND, timeOfDay,
                WILD_ENCOUNTER_FISHING_ROD_NONE, WORLD_TIER_0, &profile);
            if (resolved)
            {
                SeedRng(seed);
                directGenerated = TryGenerateWildMon(legacyInfo, WILD_AREA_LAND, 0);
                directSpecies = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
                directLevel = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);
                directPersonality = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_PERSONALITY);
                directNextRandom = Random();

                SeedRng(seed);
                routedGenerated = TryGenerateWildMonFromProfile(&profile, 0);
                routedSpecies = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
                routedLevel = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);
                routedPersonality = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_PERSONALITY);
                routedNextRandom = Random();
            }
        }
    }
    RestoreEncounterConsumerState(&saved);

    EXPECT(found);
    EXPECT(resolved);
    EXPECT_EQ(profile.source, WILD_ENCOUNTER_PROFILE_LEGACY);
    EXPECT(directGenerated);
    EXPECT(routedGenerated);
    EXPECT_EQ(routedSpecies, directSpecies);
    EXPECT_EQ(routedLevel, directLevel);
    EXPECT_EQ(routedPersonality, directPersonality);
    EXPECT_EQ(routedNextRandom, directNextRandom);
}

TEST("Resolved legacy generation preserves fixed-seed RNG parity in Johto and Hoenn")
{
    ExpectResolvedLegacyGenerationParity(MAP_ROUTE32, 5678);
    ExpectResolvedLegacyGenerationParity(MAP_ROUTE102, 9012);
}

TEST("DexNav encounter levels consume Vermilion's resolved water world tier")
{
    struct EncounterConsumerState saved;
    enum WorldTier tier0;
    enum WorldTier tier1;
    u8 tier0Level;
    u8 tier1Level;

    EstablishEncounterConsumerFixture();
    SaveEncounterConsumerState(&saved);
    LoadMap(MAP_VERMILION_CITY);

    SetWorldTierOne(FALSE);
    tier0 = WorldTier_Get();
    SeedRng(9012);
    tier0Level = DexNav_GetEncounterLevelFromMapDataForTesting(SPECIES_TENTACOOL, ENCOUNTER_TYPE_WATER);

    SetWorldTierOne(TRUE);
    tier1 = WorldTier_Get();
    SeedRng(9012);
    tier1Level = DexNav_GetEncounterLevelFromMapDataForTesting(SPECIES_TENTACOOL, ENCOUNTER_TYPE_WATER);

    RestoreEncounterConsumerState(&saved);

    EXPECT_EQ(tier0, WORLD_TIER_0);
    EXPECT_EQ(tier1, WORLD_TIER_1);
    EXPECT(tier0Level >= 4 && tier0Level <= 8);
    EXPECT(tier1Level >= 10 && tier1Level <= 14);
}
