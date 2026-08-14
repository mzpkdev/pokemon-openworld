#include "global.h"
#include "landmark.h"
#include "location_codecs.h"
#include "overworld.h"
#include "region_map.h"
#include "regions.h"
#include "test/test.h"
#include "constants/characters.h"
#include "constants/maps.h"
#include "constants/region_map_sections.h"

#define SYNTHETIC_SECTION_COUNT 301

static EWRAM_DATA struct MapSectionMetadata sSyntheticMetadata[SYNTHETIC_SECTION_COUNT];
static EWRAM_DATA SavedLocationCode sSyntheticSectionToSaved[SYNTHETIC_SECTION_COUNT];
static EWRAM_DATA MetLocationCode sSyntheticSectionToMet[SYNTHETIC_SECTION_COUNT];
static EWRAM_DATA MapSectionId sSyntheticSavedToSection[256];
static EWRAM_DATA MapSectionId sSyntheticMetToSection[256];

static const MapSectionId sSyntheticSections[] = {253, 254, 255, 256, 300};
static const RegionId sSyntheticRegions[] = {REGION_HOENN, REGION_KANTO, REGION_HOENN, REGION_KANTO, REGION_HOENN};
static const enum MapSectionKind sSyntheticKinds[] = {
    MAP_SECTION_KIND_GEOGRAPHIC,
    MAP_SECTION_KIND_SPECIAL,
    MAP_SECTION_KIND_GEOGRAPHIC,
    MAP_SECTION_KIND_SPECIAL,
    MAP_SECTION_KIND_GEOGRAPHIC,
};

static void InitSyntheticRegistry(struct MapSectionRegistry *registry)
{
    u32 i;

    for (i = 0; i < SYNTHETIC_SECTION_COUNT; i++)
    {
        sSyntheticMetadata[i].region = REGION_NONE;
        sSyntheticMetadata[i].kind = MAP_SECTION_KIND_RESERVED;
        sSyntheticMetadata[i].regionMapType = 0xFF;
        sSyntheticSectionToSaved[i] = SAVED_LOCATION_INVALID;
        sSyntheticSectionToMet[i] = MET_LOCATION_INVALID;
    }
    for (i = 0; i < 256; i++)
    {
        sSyntheticSavedToSection[i] = MAPSEC_INVALID;
        sSyntheticMetToSection[i] = MAPSEC_INVALID;
    }
    for (i = 0; i < ARRAY_COUNT(sSyntheticSections); i++)
    {
        MapSectionId section = sSyntheticSections[i];
        SavedLocationCode savedCode = 10 + i;
        MetLocationCode metCode = 20 + i;

        sSyntheticMetadata[section].region = sSyntheticRegions[i];
        sSyntheticMetadata[section].kind = sSyntheticKinds[i];
        sSyntheticMetadata[section].regionMapType = REGION_MAP_HOENN;
        sSyntheticSectionToSaved[section] = savedCode;
        sSyntheticSectionToMet[section] = metCode;
        sSyntheticSavedToSection[savedCode] = section;
        sSyntheticMetToSection[metCode] = section;
    }

    *registry = (struct MapSectionRegistry) {
        .metadata = sSyntheticMetadata,
        .sectionToSavedLocation = sSyntheticSectionToSaved,
        .sectionToMetLocation = sSyntheticSectionToMet,
        .savedLocationToSection = sSyntheticSavedToSection,
        .metLocationToSection = sSyntheticMetToSection,
        .sectionCount = SYNTHETIC_SECTION_COUNT,
    };
}

TEST("World geography APIs preserve map section IDs wider than a byte")
{
    const MapSectionId wideSection = 0x100;

    EXPECT_EQ(sizeof(MapSectionId), sizeof(u16));
    EXPECT_EQ(CorrectSpecialMapSecId(wideSection), wideSection);
    EXPECT(!IsEventIslandMapSecId(wideSection));
    EXPECT(GetLandmarkName(wideSection, 0, 0) == NULL);
}

TEST("Map names reject invalid section IDs without indexing region map data")
{
    u8 name[5];

    GetMapName(name, MAPSEC_INVALID, 4);
    EXPECT_EQ(name[0], CHAR_SPACE);
    EXPECT_EQ(name[1], CHAR_SPACE);
    EXPECT_EQ(name[2], CHAR_SPACE);
    EXPECT_EQ(name[3], CHAR_SPACE);
    EXPECT_EQ(name[4], EOS);
}

TEST("Reviewed synthetic wide sections cross world and compact registry APIs")
{
    struct MapSectionRegistry registry;
    u32 i;

    InitSyntheticRegistry(&registry);
    for (i = 0; i < ARRAY_COUNT(sSyntheticSections); i++)
    {
        MapSectionId section = sSyntheticSections[i];
        RegionId region = REGION_NONE;
        SavedLocationCode savedCode = 10 + i;
        MetLocationCode metCode = 20 + i;

        EXPECT(IsValidMapSectionIdInRegistry(section, &registry));
        EXPECT(TryGetRegionForSectionIdInRegistry(section, &region, &registry));
        EXPECT_EQ(region, sSyntheticRegions[i]);
        EXPECT_EQ(GetMapSectionKindInRegistry(section, &registry), sSyntheticKinds[i]);
        EXPECT_EQ(EncodeSavedLocationWithRegistry(section, &registry), savedCode);
        EXPECT_EQ(DecodeSavedLocationWithRegistry(savedCode, &registry), section);
        EXPECT_EQ(EncodeMetLocationWithRegistry(section, &registry), metCode);
        EXPECT_EQ(DecodeMetLocationWithRegistry(metCode, &registry), section);
    }

    EXPECT(!IsValidMapSectionIdInRegistry(252, &registry));
    EXPECT_EQ(GetMapSectionKindInRegistry(301, &registry), MAP_SECTION_KIND_INVALID);
    EXPECT_EQ(EncodeSavedLocationWithRegistry(252, &registry), SAVED_LOCATION_INVALID);
    EXPECT_EQ(EncodeMetLocationWithRegistry(252, &registry), MET_LOCATION_INVALID);
}

TEST("Published compact locations and reviewed wide identities round trip canonically")
{
    MapSectionId section;

    for (section = 0; section <= MAPSEC_TRAINER_HILL; section++)
    {
        EXPECT_EQ(EncodeSavedLocation(section), section);
        EXPECT_EQ(DecodeSavedLocation(EncodeSavedLocation(section)), section);
        EXPECT_EQ(EncodeMetLocation(section), section);
        EXPECT_EQ(DecodeMetLocation(EncodeMetLocation(section)), section);
    }

    EXPECT_EQ(EncodeSavedLocation(MAPSEC_NEW_BARK_TOWN), 209);
    EXPECT_EQ(DecodeSavedLocation(209), MAPSEC_NEW_BARK_TOWN);
    EXPECT_EQ(EncodeMetLocation(MAPSEC_MT_MORTAR), 251);
    EXPECT_EQ(DecodeMetLocation(251), MAPSEC_MT_MORTAR);
}

TEST("Johto Victory Road uses the canonical Victory Road compact identity")
{
    EXPECT_EQ(EncodeSavedLocation(MAPSEC_JOHTO_VICTORY_ROAD), EncodeSavedLocation(MAPSEC_VICTORY_ROAD));
    EXPECT_EQ(EncodeSavedLocation(MAPSEC_JOHTO_VICTORY_ROAD), 70);
    EXPECT_EQ(DecodeSavedLocation(EncodeSavedLocation(MAPSEC_JOHTO_VICTORY_ROAD)), MAPSEC_VICTORY_ROAD);
    EXPECT_EQ(EncodeMetLocation(MAPSEC_JOHTO_VICTORY_ROAD), EncodeMetLocation(MAPSEC_VICTORY_ROAD));
    EXPECT_EQ(EncodeMetLocation(MAPSEC_JOHTO_VICTORY_ROAD), 70);
    EXPECT_EQ(DecodeMetLocation(EncodeMetLocation(MAPSEC_JOHTO_VICTORY_ROAD)), MAPSEC_VICTORY_ROAD);
}

TEST("Invalid compact codes and special met origins have no map section owner")
{
    EXPECT_EQ(DecodeSavedLocation(SAVED_LOCATION_INVALID), MAPSEC_INVALID);
    EXPECT_EQ(DecodeMetLocation(MET_LOCATION_INVALID), MAPSEC_INVALID);
    EXPECT_EQ(DecodeMetLocation(METLOC_SPECIAL_EGG), MAPSEC_INVALID);
    EXPECT_EQ(DecodeMetLocation(METLOC_IN_GAME_TRADE), MAPSEC_INVALID);
    EXPECT_EQ(DecodeMetLocation(METLOC_FATEFUL_ENCOUNTER), MAPSEC_INVALID);
}

TEST("Current region follows the loaded map header")
{
    struct MapHeader savedHeader = gMapHeader;
    u8 savedMapGroup = gSaveBlock1Ptr->location.mapGroup;
    u8 savedMapNum = gSaveBlock1Ptr->location.mapNum;

    gMapHeader = *Overworld_GetMapHeaderByGroupAndId(
        MAP_GROUP(MAP_VERMILION_CITY_PORT_INSIDE),
        MAP_NUM(MAP_VERMILION_CITY_PORT_INSIDE));
    EXPECT_EQ(GetCurrentRegion(), REGION_KANTO);

    // Save location changes do not act as a region setter. The next loaded
    // header is the sole authority consumed by GetCurrentRegion.
    gSaveBlock1Ptr->location.mapGroup = MAP_GROUP(MAP_ROUTE39);
    gSaveBlock1Ptr->location.mapNum = MAP_NUM(MAP_ROUTE39);
    EXPECT_EQ(GetCurrentRegion(), REGION_KANTO);

    gMapHeader = *Overworld_GetMapHeaderByGroupAndId(
        MAP_GROUP(MAP_ROUTE39),
        MAP_NUM(MAP_ROUTE39));
    EXPECT_EQ(GetCurrentRegion(), REGION_JOHTO);

    gSaveBlock1Ptr->location.mapGroup = savedMapGroup;
    gSaveBlock1Ptr->location.mapNum = savedMapNum;
    gMapHeader = savedHeader;
}
