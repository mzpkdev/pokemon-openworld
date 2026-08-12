#include "global.h"
#include "event_data.h"
#include "overworld.h"
#include "rtc.h"
#include "wild_encounter.h"
#include "test/test.h"

TEST("Resident wild registry enumerates exact counted headers")
{
    const struct WildPokemonHeader *header = (void *)1;
    u16 count = GetWildEncounterHeaderCount();

    EXPECT(count > 0);
    EXPECT(TryGetWildEncounterHeader(0, &header));
    EXPECT(header != NULL);
    EXPECT(TryGetWildEncounterHeader(count - 1, &header));

    header = (void *)1;
    EXPECT(!TryGetWildEncounterHeader(count, &header));
    EXPECT_EQ(header, (void *)1);
    EXPECT_EQ(GetWildEncounterHeader(count), NULL);
    EXPECT(!TryGetWildEncounterHeader(0, NULL));
}

TEST("Resident wild registry resolves maps and fails without output mutation")
{
    const struct WildPokemonHeader *header;
    u16 route39Id = HEADER_NONE;
    u16 unresolved = 0x1234;

    EXPECT(TryFindWildEncounterHeader(MAP_GROUP(MAP_ROUTE39), MAP_NUM(MAP_ROUTE39), &route39Id));
    EXPECT_NE(route39Id, HEADER_NONE);
    EXPECT(TryGetWildEncounterHeader(route39Id, &header));
    EXPECT_EQ(header->mapGroup, MAP_GROUP(MAP_ROUTE39));
    EXPECT_EQ(header->mapNum, MAP_NUM(MAP_ROUTE39));

    EXPECT(!TryFindWildEncounterHeader(MAP_GROUP(MAP_UNDEFINED), MAP_NUM(MAP_UNDEFINED), &unresolved));
    EXPECT_EQ(unresolved, 0x1234);
    EXPECT(!TryFindWildEncounterHeader(0xFF, 0xFF, &unresolved));
    EXPECT_EQ(unresolved, 0x1234);
    EXPECT(!TryFindWildEncounterHeader(MAP_GROUP(MAP_ROUTE39), MAP_NUM(MAP_ROUTE39), NULL));
}

TEST("Altering Cave variants resolve inside the counted registry")
{
    u8 savedMapGroup = gSaveBlock1Ptr->location.mapGroup;
    u8 savedMapNum = gSaveBlock1Ptr->location.mapNum;
    u16 savedVariant = VarGet(VAR_ALTERING_CAVE_WILD_SET);
    u16 canonicalId;
    u16 finalVariantId;
    u16 invalidVariantId;

    gSaveBlock1Ptr->location.mapGroup = MAP_GROUP(MAP_ALTERING_CAVE);
    gSaveBlock1Ptr->location.mapNum = MAP_NUM(MAP_ALTERING_CAVE);
    VarSet(VAR_ALTERING_CAVE_WILD_SET, 0);
    EXPECT(TryGetCurrentWildEncounterHeader(&canonicalId));
    VarSet(VAR_ALTERING_CAVE_WILD_SET, NUM_ALTERING_CAVE_TABLES - 1);
    EXPECT(TryGetCurrentWildEncounterHeader(&finalVariantId));
    EXPECT_EQ(finalVariantId, canonicalId + NUM_ALTERING_CAVE_TABLES - 1);
    EXPECT(finalVariantId < GetWildEncounterHeaderCount());
    EXPECT_EQ(GetWildEncounterHeader(finalVariantId)->mapGroup, MAP_GROUP(MAP_ALTERING_CAVE));
    EXPECT_EQ(GetWildEncounterHeader(finalVariantId)->mapNum, MAP_NUM(MAP_ALTERING_CAVE));

    VarSet(VAR_ALTERING_CAVE_WILD_SET, NUM_ALTERING_CAVE_TABLES);
    EXPECT(TryGetCurrentWildEncounterHeader(&invalidVariantId));
    EXPECT_EQ(invalidVariantId, canonicalId);

    VarSet(VAR_ALTERING_CAVE_WILD_SET, savedVariant);
    gSaveBlock1Ptr->location.mapGroup = savedMapGroup;
    gSaveBlock1Ptr->location.mapNum = savedMapNum;
}

TEST("Six Island Altering Cave uses its independent variant selector")
{
    u8 savedMapGroup = gSaveBlock1Ptr->location.mapGroup;
    u8 savedMapNum = gSaveBlock1Ptr->location.mapNum;
    u16 savedHoennVariant = VarGet(VAR_ALTERING_CAVE_WILD_SET);
    u16 savedFrlgVariant = VarGet(VAR_ALTERING_CAVE_WILD_SET_FRLG);
    u16 canonicalId;
    u16 variantId;

    gSaveBlock1Ptr->location.mapGroup = MAP_GROUP(MAP_SIX_ISLAND_ALTERING_CAVE);
    gSaveBlock1Ptr->location.mapNum = MAP_NUM(MAP_SIX_ISLAND_ALTERING_CAVE);
    VarSet(VAR_ALTERING_CAVE_WILD_SET, NUM_ALTERING_CAVE_TABLES - 1);
    VarSet(VAR_ALTERING_CAVE_WILD_SET_FRLG, 0);
    EXPECT(TryGetCurrentWildEncounterHeader(&canonicalId));
    VarSet(VAR_ALTERING_CAVE_WILD_SET_FRLG, NUM_ALTERING_CAVE_TABLES - 1);
    EXPECT(TryGetCurrentWildEncounterHeader(&variantId));
    EXPECT_EQ(variantId, canonicalId + NUM_ALTERING_CAVE_TABLES - 1);
    EXPECT_EQ(GetWildEncounterHeader(variantId)->mapGroup, MAP_GROUP(MAP_SIX_ISLAND_ALTERING_CAVE));
    EXPECT_EQ(GetWildEncounterHeader(variantId)->mapNum, MAP_NUM(MAP_SIX_ISLAND_ALTERING_CAVE));

    VarSet(VAR_ALTERING_CAVE_WILD_SET_FRLG, NUM_ALTERING_CAVE_TABLES);
    EXPECT(TryGetCurrentWildEncounterHeader(&variantId));
    EXPECT_EQ(variantId, canonicalId);

    VarSet(VAR_ALTERING_CAVE_WILD_SET, savedHoennVariant);
    VarSet(VAR_ALTERING_CAVE_WILD_SET_FRLG, savedFrlgVariant);
    gSaveBlock1Ptr->location.mapGroup = savedMapGroup;
    gSaveBlock1Ptr->location.mapNum = savedMapNum;
}

TEST("Current-map wild resolution uses the same fail-closed registry")
{
    u8 savedMapGroup = gSaveBlock1Ptr->location.mapGroup;
    u8 savedMapNum = gSaveBlock1Ptr->location.mapNum;
    u16 headerId = 0x1234;

    gSaveBlock1Ptr->location.mapGroup = MAP_GROUP(MAP_ROUTE39);
    gSaveBlock1Ptr->location.mapNum = MAP_NUM(MAP_ROUTE39);
    EXPECT(TryGetCurrentWildEncounterHeader(&headerId));
    EXPECT_EQ(GetWildEncounterHeader(headerId)->mapGroup, MAP_GROUP(MAP_ROUTE39));

    gSaveBlock1Ptr->location.mapGroup = 0xFF;
    gSaveBlock1Ptr->location.mapNum = 0xFF;
    headerId = 0x1234;
    EXPECT(!TryGetCurrentWildEncounterHeader(&headerId));
    EXPECT_EQ(headerId, 0x1234);
    EXPECT_EQ(GetCurrentMapWildMonHeaderId(), HEADER_NONE);
    EXPECT(!TryGetCurrentWildEncounterHeader(NULL));

    gSaveBlock1Ptr->location.mapGroup = savedMapGroup;
    gSaveBlock1Ptr->location.mapNum = savedMapNum;
}

TEST("Resident wild method resolver preserves Route 39 all-minute policy")
{
    const struct WildPokemonInfo *dayInfo;
    const struct WildPokemonInfo *nightInfo;
    const struct WildPokemonInfo *unchanged = (void *)1;
    const struct WildEncounterTypes *unchangedTypes = (void *)1;
    u16 route39Id;
    u16 savedOverride = SetTimeOfDay(0);

    EXPECT(TryFindWildEncounterHeader(MAP_GROUP(MAP_ROUTE39), MAP_NUM(MAP_ROUTE39), &route39Id));
    SetTimeOfDay(6);
    EXPECT(TryGetWildEncounterInfo(route39Id, WILD_AREA_LAND, &dayInfo));
    SetTimeOfDay(18);
    EXPECT(TryGetWildEncounterInfo(route39Id, WILD_AREA_LAND, &nightInfo));
    EXPECT_NE(dayInfo, nightInfo);
    EXPECT_EQ(dayInfo->wildPokemon[0].species, SPECIES_PONYTA);
    EXPECT_EQ(nightInfo->wildPokemon[0].species, SPECIES_MEOWTH);

    EXPECT(!TryGetWildEncounterInfo(GetWildEncounterHeaderCount(), WILD_AREA_LAND, &unchanged));
    EXPECT_EQ(unchanged, (void *)1);
    EXPECT(!TryGetWildEncounterInfo(route39Id, WILD_AREA_HIDDEN, &unchanged));
    EXPECT_EQ(unchanged, (void *)1);
    EXPECT(!TryGetWildEncounterInfo(route39Id, WILD_AREA_LAND, NULL));
    EXPECT(!TryGetWildEncounterTypes(route39Id, TIMES_OF_DAY_COUNT, &unchangedTypes));
    EXPECT_EQ(unchangedTypes, (void *)1);
    EXPECT_EQ(GetWildEncounterInfoAtTime(route39Id, TIME_DAY, WILD_AREA_HIDDEN), NULL);
    SetTimeOfDay(savedOverride);
}
