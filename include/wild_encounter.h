#ifndef GUARD_WILD_ENCOUNTER_H
#define GUARD_WILD_ENCOUNTER_H

#include "rtc.h"
#include "constants/wild_encounter.h"
#include "wild_encounter_ow.h"
#include "wild_encounter_time_policy.h"
#include "world_tier.h"

#define HEADER_NONE 0xFFFF

enum WildPokemonArea {
    WILD_AREA_LAND,
    WILD_AREA_WATER,
    WILD_AREA_ROCKS,
    WILD_AREA_FISHING,
    WILD_AREA_HIDDEN
};

struct WildPokemon
{
    u8 minLevel;
    u8 maxLevel;
    enum Species species;
};

struct WildPokemonInfo
{
    u8 encounterRate;
    const struct WildPokemon *wildPokemon;
};

struct WildEncounterTypes
{
    const struct WildPokemonInfo *landMonsInfo;
    const struct WildPokemonInfo *waterMonsInfo;
    const struct WildPokemonInfo *rockSmashMonsInfo;
    const struct WildPokemonInfo *fishingMonsInfo;
    const struct WildPokemonInfo *hiddenMonsInfo;
};

struct WildPokemonHeader
{
    u8 mapGroup;
    u8 mapNum;
    const struct WildEncounterTypes encounterTypes[TIMES_OF_DAY_COUNT];
};

#define WILD_ENCOUNTER_FISHING_ROD_NONE 0xFF

enum WildEncounterMissingBandPolicy
{
    WILD_ENCOUNTER_MISSING_BAND_COMPLETE,
    WILD_ENCOUNTER_MISSING_BAND_FLOOR,
};

struct WildEncounterAuthoredEntry
{
    enum Species species;
    u16 weight;
    u8 minLevel;
    u8 maxLevel;
};

struct WildEncounterAuthoredBand
{
    enum WorldTier tier;
    u16 entryCount;
    u16 totalWeight;
    const struct WildEncounterAuthoredEntry *entries;
};

struct WildEncounterAuthoredProfile
{
    u16 headerId;
    enum WildPokemonArea area;
    enum TimeOfDay timeOfDay;
    u8 fishingRod;
    enum WildEncounterMissingBandPolicy missingBandPolicy;
    u16 bandCount;
    const struct WildEncounterAuthoredBand *bands;
};

enum WildEncounterProfileSource
{
    WILD_ENCOUNTER_PROFILE_AUTHORED,
    WILD_ENCOUNTER_PROFILE_LEGACY,
};

struct WildEncounterProfileView
{
    enum WildEncounterProfileSource source;
    enum WildPokemonArea area;
    u8 fishingRod;
    u8 encounterRate;
    u16 entryCount;
    u16 totalWeight;
    u16 legacyStartIndex;
    const struct WildEncounterAuthoredEntry *authoredEntries;
    const struct WildPokemon *legacyEntries;
};

// Parallel to gWildMonHeaders so WildPokemonHeader keeps its existing ABI.
struct WildEncounterTimePolicy
{
    u16 dayStartMinutes;
    u16 nightStartMinutes;
    u8 dayTime;
    u8 nightTime;
};


extern const struct WildPokemonHeader gBattlePikeWildMonHeaders[];
extern const struct WildPokemonHeader gBattlePyramidWildMonHeaders[];
extern const struct WildPokemon gWildFeebas;
extern bool8 gIsFishingEncounter;
extern bool8 gIsSurfingEncounter;
extern u8 gChainFishingDexNavStreak;

u8 ChooseWildMonLevel(const struct WildPokemon *wildPokemon, u8 wildMonIndex, enum WildPokemonArea area);
void DisableWildEncounters(bool8 disabled);
bool8 StandardWildEncounter(u16 curMetatileBehavior, u16 prevMetatileBehavior);
bool8 SweetScentWildEncounter(void);
bool8 DoesCurrentMapHaveFishingMons(void);
void FishingWildEncounter(u8 rod);
u16 GetLocalWildMon(bool8 *isWaterMon);
u16 GetLocalWaterMon(void);
bool8 UpdateRepelCounter(void);
bool8 IsWildLevelAllowedByRepel(u8 wildLevel);
bool8 IsAbilityAllowingEncounter(u8 level);
bool8 TryDoDoubleWildBattle(void);
bool8 StandardWildEncounter_Debug(void);
u32 CalculateChainFishingShinyRolls(void);
void CreateWildMon(enum Species species, u8 level);
bool8 TryGenerateWildMon(const struct WildPokemonInfo *wildMonInfo, enum WildPokemonArea area, u8 flags);
bool8 SetUpMassOutbreakEncounter(u8 flags);
bool8 DoMassOutbreakEncounterTest(void);
bool8 AreLegendariesInSootopolisPreventingEncounters(void);
u16 GetCurrentMapWildMonHeaderId(void);
u16 GetWildEncounterHeaderCount(void);
const struct WildPokemonHeader *GetWildEncounterHeader(u16 headerId);
const struct WildPokemonInfo *GetWildEncounterInfo(u16 headerId, enum WildPokemonArea area);
const struct WildPokemonInfo *GetWildEncounterInfoAtTime(u16 headerId, enum TimeOfDay timeOfDay, enum WildPokemonArea area);
bool32 TryGetWildEncounterHeader(u16 headerId, const struct WildPokemonHeader **header);
bool32 TryFindWildEncounterHeader(u8 mapGroup, u8 mapNum, u16 *headerId);
bool32 TryGetCurrentWildEncounterHeader(u16 *headerId);
bool32 TryGetWildEncounterTypes(u16 headerId, enum TimeOfDay timeOfDay, const struct WildEncounterTypes **types);
enum TimeOfDay ResolveWildEncounterDisplayTime(u16 headerId, enum TimeOfDay displayTime);
bool32 TryGetWildEncounterInfo(u16 headerId, enum WildPokemonArea area, const struct WildPokemonInfo **info);
bool32 TryResolveWildEncounterProfile(u16 headerId, enum WildPokemonArea area, enum TimeOfDay timeOfDay, u8 fishingRod, enum WorldTier tier, struct WildEncounterProfileView *view);
bool32 TryResolveWildEncounterAuthoredBand(const struct WildEncounterAuthoredProfile *profile, enum WorldTier tier, const struct WildEncounterAuthoredBand **band);
bool32 TryGetWildEncounterProfileEntry(const struct WildEncounterProfileView *view, u16 index, struct WildEncounterAuthoredEntry *entry);
bool32 TrySelectWildEncounterProfileEntry(const struct WildEncounterProfileView *view, u16 weightedRoll, struct WildEncounterAuthoredEntry *entry);
bool32 TrySelectWildEncounterLevel(const struct WildEncounterProfileView *view, const struct WildEncounterAuthoredEntry *entry, u16 rangeRoll, bool32 lureActive, u8 *level);
bool8 CheckFeebasAtCoords(s16 x, s16 y);
u32 ChooseWildMonIndex_Land(void);
u32 ChooseWildMonIndex_Water(void);
u32 ChooseWildMonIndex_Rocks(void);
u32 ChooseHiddenMonIndex(void);
bool32 MapHasNoEncounterData(void);
enum TimeOfDay GetTimeOfDayForEncounters(u32 headerId, enum WildPokemonArea area);

u8 GetLandEncounterSlotForMatchCall(void);
u8 GetWaterEncounterSlotForMatchCall(void);

#endif // GUARD_WILD_ENCOUNTER_H
