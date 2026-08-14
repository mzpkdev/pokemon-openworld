#include "global.h"
#include "battle.h"
#include "dexnav.h"
#include "event_data.h"
#include "event_object_movement.h"
#include "main.h"
#include "overworld.h"
#include "pokemon.h"
#include "random.h"
#include "script.h"
#include "task.h"
#include "wild_encounter.h"
#include "world_tier.h"
#include "constants/game_stat.h"
#include "constants/maps.h"
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
    bool8 stoneBadge;
    bool8 cascadeBadge;
    bool8 hiveBadge;
    bool8 isFishingEncounter;
    bool8 fieldControlsLocked;
    u8 chainFishingStreak;
    u8 mapGroup;
    u8 mapNum;
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
    state->stoneBadge = FlagGet(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE);
    state->cascadeBadge = FlagGet(FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE);
    state->hiveBadge = FlagGet(FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE);
    state->isFishingEncounter = gIsFishingEncounter;
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
    RestoreFlag(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE, state->stoneBadge);
    RestoreFlag(FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE, state->cascadeBadge);
    RestoreFlag(FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE, state->hiveBadge);
    gIsFishingEncounter = state->isFishingEncounter;
    gChainFishingDexNavStreak = state->chainFishingStreak;
    gSaveBlock1Ptr->location.mapGroup = state->mapGroup;
    gSaveBlock1Ptr->location.mapNum = state->mapNum;
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

TEST("Standard wild encounters consume Route 101's resolved world tier")
{
    struct EncounterConsumerState saved;
    enum Species tier0Species;
    enum Species tier1Species;
    u8 tier0Level;
    u8 tier1Level;

    SaveEncounterConsumerState(&saved);
    LoadMap(MAP_ROUTE101);

    SetWorldTierOne(FALSE);
    EXPECT_EQ(WorldTier_Get(), WORLD_TIER_0);
    SeedRng(1234);
    EXPECT(StandardWildEncounter_Debug());
    tier0Species = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
    tier0Level = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);
    ResetTasks();

    SetWorldTierOne(TRUE);
    EXPECT_EQ(WorldTier_Get(), WORLD_TIER_1);
    SeedRng(1234);
    EXPECT(StandardWildEncounter_Debug());
    tier1Species = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
    tier1Level = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);

    EXPECT_EQ(tier0Species, SPECIES_WURMPLE);
    EXPECT_EQ(tier1Species, SPECIES_WURMPLE);
    EXPECT(tier0Level >= 2 && tier0Level <= 3);
    EXPECT(tier1Level >= 10 && tier1Level <= 14);
    RestoreEncounterConsumerState(&saved);
}

TEST("Fishing encounters consume Vermilion's resolved old rod world tier")
{
    struct EncounterConsumerState saved;
    u8 tier0Level;
    u8 tier1Level;

    SaveEncounterConsumerState(&saved);
    LoadMap(MAP_VERMILION_CITY);

    SetWorldTierOne(FALSE);
    EXPECT_EQ(WorldTier_Get(), WORLD_TIER_0);
    SeedRng(1234);
    FishingWildEncounter(OLD_ROD);
    EXPECT_EQ(GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES), SPECIES_MAGIKARP);
    tier0Level = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);
    ResetTasks();

    SetWorldTierOne(TRUE);
    EXPECT_EQ(WorldTier_Get(), WORLD_TIER_1);
    SeedRng(1234);
    FishingWildEncounter(OLD_ROD);
    EXPECT_EQ(GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES), SPECIES_MAGIKARP);
    tier1Level = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);

    EXPECT(tier0Level >= 4 && tier0Level <= 8);
    EXPECT(tier1Level >= 10 && tier1Level <= 14);
    RestoreEncounterConsumerState(&saved);
}

TEST("Resolved legacy generation is exactly compatible with direct generation")
{
    struct EncounterConsumerState saved;
    struct WildEncounterProfileView profile;
    const struct WildPokemonInfo *legacyInfo;
    enum Species directSpecies;
    u32 directPersonality;
    u16 directNextRandom;
    u8 directLevel;
    u16 headerId = HEADER_NONE;
    enum TimeOfDay timeOfDay;

    SaveEncounterConsumerState(&saved);
    EXPECT(TryFindWildEncounterHeader(MAP_GROUP(MAP_ROUTE102), MAP_NUM(MAP_ROUTE102), &headerId));
    timeOfDay = GetTimeOfDayForEncounters(headerId, WILD_AREA_LAND);
    legacyInfo = GetWildEncounterInfoAtTime(headerId, timeOfDay, WILD_AREA_LAND);
    EXPECT(legacyInfo != NULL);
    EXPECT(TryResolveWildEncounterProfile(headerId, WILD_AREA_LAND, timeOfDay,
        WILD_ENCOUNTER_FISHING_ROD_NONE, WORLD_TIER_0, &profile));
    EXPECT_EQ(profile.source, WILD_ENCOUNTER_PROFILE_LEGACY);

    SeedRng(5678);
    EXPECT(TryGenerateWildMon(legacyInfo, WILD_AREA_LAND, 0));
    directSpecies = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES);
    directLevel = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL);
    directPersonality = GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_PERSONALITY);
    directNextRandom = Random();

    SeedRng(5678);
    EXPECT(TryGenerateWildMonFromProfile(&profile, 0));
    EXPECT_EQ(GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_SPECIES), directSpecies);
    EXPECT_EQ(GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_LEVEL), directLevel);
    EXPECT_EQ(GetMonData(&gParties[B_TRAINER_OPPONENT_A][0], MON_DATA_PERSONALITY), directPersonality);
    EXPECT_EQ(Random(), directNextRandom);
    RestoreEncounterConsumerState(&saved);
}

TEST("DexNav encounter levels consume Vermilion's resolved water world tier")
{
    struct EncounterConsumerState saved;
    u8 tier0Level;
    u8 tier1Level;

    SaveEncounterConsumerState(&saved);
    LoadMap(MAP_VERMILION_CITY);

    SetWorldTierOne(FALSE);
    EXPECT_EQ(WorldTier_Get(), WORLD_TIER_0);
    SeedRng(9012);
    tier0Level = DexNav_GetEncounterLevelFromMapDataForTesting(SPECIES_TENTACOOL, ENCOUNTER_TYPE_WATER);

    SetWorldTierOne(TRUE);
    EXPECT_EQ(WorldTier_Get(), WORLD_TIER_1);
    SeedRng(9012);
    tier1Level = DexNav_GetEncounterLevelFromMapDataForTesting(SPECIES_TENTACOOL, ENCOUNTER_TYPE_WATER);

    EXPECT(tier0Level >= 4 && tier0Level <= 8);
    EXPECT(tier1Level >= 10 && tier1Level <= 14);
    RestoreEncounterConsumerState(&saved);
}
