#ifndef GUARD_WILD_ENCOUNTER_H
#define GUARD_WILD_ENCOUNTER_H

#include "rtc.h"
#include "constants/wild_encounter.h"
#include "wild_encounter_ow.h"
#include "wild_encounter_time_policy.h"
#include "trainer_rating.h"

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

// A standard encounter slot remains the source authority. Its species, weight,
// and vanilla level range are never rewritten for Trainer Rating scaling.
struct WildEncounterSlot
{
    enum Species species;
    u16 weight;
    u8 minLevel;
    u8 maxLevel;
};

struct WildEncounterContext
{
    u16 headerId;
    enum WildPokemonArea area;
    enum TimeOfDay timeOfDay;
    u8 fishingRod;
};

struct WildEncounterSlotOutcome
{
    enum Species species;
    u8 level;
};

// Generated from src/data/wild_encounter_scaling.json. Points are indexed by
// clamped Trainer Rating and carry the already-derived anchor and retention
// fraction so ROM code never has a second hand-maintained balance curve.
struct WildEncounterScalingBalance
{
    u8 projectionCap;
    u16 maximumRating;
};

struct WildEncounterScalingAnchor
{
    u8 rating;
    u8 level;
};

struct WildEncounterScalingPoint
{
    u8 anchorLevel;
    u16 retentionNumerator;
    u16 retentionDenominator;
};

struct WildEncounterProfileOffset
{
    u16 headerId;
    enum WildPokemonArea area;
    enum TimeOfDay timeOfDay;
    u8 fishingRod;
    s8 levelOffset;
};

struct WildEncounterSpeciesMetadata
{
    enum Species species;
    u8 minimumOrdinaryWildLevel;
    enum Species predecessorSpecies;
    u8 predecessorLevel;
    bool8 hasAlternateNonLevelRoute;
};

extern const struct WildEncounterScalingBalance gWildEncounterScalingBalance;
extern const struct WildEncounterScalingAnchor gWildEncounterScalingAnchors[];
extern const u16 gWildEncounterScalingAnchorCount;
extern const struct WildEncounterScalingPoint gWildEncounterScalingPoints[];
extern const u16 gWildEncounterScalingPointCount;
extern const struct WildEncounterProfileOffset gWildEncounterProfileOffsets[];
extern const u16 gWildEncounterProfileOffsetCount;
extern const struct WildEncounterSpeciesMetadata gWildEncounterSpeciesMetadata[];
extern const u16 gWildEncounterSpeciesMetadataCount;

struct WildEncounterProfileView
{
    struct WildEncounterContext context;
    enum WildPokemonArea area;
    u8 fishingRod;
    u8 encounterRate;
    u16 entryCount;
    u16 totalWeight;
    u16 legacyStartIndex;
    const struct WildPokemon *entries;
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
void RockSmashWildEncounter(void);
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
#if TESTING
bool8 SweetScentWildEncounterForTesting(enum WildPokemonArea area);
#endif
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
bool32 IsWildEncounterProfileViewValid(const struct WildEncounterProfileView *view);
bool32 TryResolveWildEncounterProfile(u16 headerId, enum WildPokemonArea area, enum TimeOfDay timeOfDay, u8 fishingRod, struct WildEncounterProfileView *view);
bool32 TryGetWildEncounterProfileEntry(const struct WildEncounterProfileView *view, u16 index, struct WildEncounterSlot *entry);
bool32 TrySelectWildEncounterProfileEntry(const struct WildEncounterProfileView *view, u16 weightedRoll, struct WildEncounterSlot *entry);
bool32 TrySelectWildEncounterLevel(const struct WildEncounterProfileView *view, const struct WildEncounterSlot *entry, u16 rangeRoll, bool32 lureActive, u8 *level);
bool32 ProjectWildSlotOutcome(enum Species originalSpecies, u8 vanillaLevel, u16 trainerRating, const struct WildEncounterContext *context, struct WildEncounterSlotOutcome *outcome);
bool32 TryProjectWildEncounterProfileEntry(const struct WildEncounterProfileView *view, u16 index, u8 vanillaLevel, u16 trainerRating, struct WildEncounterSlotOutcome *outcome);
bool32 IsWildEncounterProfileEntryEligible(const struct WildEncounterProfileView *view, u16 index, u16 trainerRating);
u16 GetWildEncounterProfileEligibleWeight(const struct WildEncounterProfileView *view, u16 trainerRating);
bool32 TrySelectWildEncounterEligibleEntry(const struct WildEncounterProfileView *view, u16 trainerRating, u16 weightedRoll, struct WildEncounterSlot *entry);
bool8 TryGenerateWildMonFromProfile(const struct WildEncounterProfileView *profile, u8 flags);
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
