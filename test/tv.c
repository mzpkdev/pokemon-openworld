#include "global.h"
#include "location_codecs.h"
#include "overworld.h"
#include "record_mixing.h"
#include "region_map.h"
#include "string_util.h"
#include "tv.h"
#include "test/test.h"
#include "constants/region_map_sections.h"

#define SYNTHETIC_TV_SECTION_COUNT 301
#define SYNTHETIC_TV_SECTION 300
#define SYNTHETIC_TV_LOCATION_CODE 42

static const struct MapSectionMetadata sSyntheticTvMetadata[SYNTHETIC_TV_SECTION_COUNT] =
{
    [SYNTHETIC_TV_SECTION] =
    {
        .region = REGION_HOENN,
        .kind = MAP_SECTION_KIND_GEOGRAPHIC,
        .regionMapType = REGION_MAP_HOENN,
    },
};

static const SavedLocationCode sSyntheticTvSectionToSaved[SYNTHETIC_TV_SECTION_COUNT] =
{
    [SYNTHETIC_TV_SECTION] = SYNTHETIC_TV_LOCATION_CODE,
};

static const MapSectionId sSyntheticTvSavedToSection[256] =
{
    [SYNTHETIC_TV_LOCATION_CODE] = SYNTHETIC_TV_SECTION,
};

static const struct MapSectionRegistry sSyntheticTvRegistry =
{
    .metadata = sSyntheticTvMetadata,
    .sectionToSavedLocation = sSyntheticTvSectionToSaved,
    .savedLocationToSection = sSyntheticTvSavedToSection,
    .sectionCount = SYNTHETIC_TV_SECTION_COUNT,
};

static void ExpectLocationName(SavedLocationCode code, MapSectionId section)
{
    u8 actual[32];
    u8 expected[32];

    TV_GetLocationName(actual, code, 0);
    GetMapName(expected, section, 0);
    EXPECT_EQ(StringCompare(actual, expected), 0);
}

TEST("TV show locations stay compact and decode before map-name display")
{
    TVShow show = {0};
    const MapSectionId section = MAPSEC_LITTLEROOT_TOWN;

    TV_StoreLocation(&show.smartshopperShow.shopLocation, section);

    EXPECT_EQ(sizeof(show.smartshopperShow.shopLocation), sizeof(SavedLocationCode));
    EXPECT_EQ(show.smartshopperShow.shopLocation, EncodeSavedLocation(section));
    EXPECT_EQ(TV_DecodeLocation(show.smartshopperShow.shopLocation), section);
    ExpectLocationName(show.smartshopperShow.shopLocation, section);
}

TEST("Gabby and Ty store a compact location and decode it for display")
{
    const MapSectionId section = MAPSEC_OLDALE_TOWN;

    gMapHeader.regionMapSectionId = section;
    GabbyAndTyAfterInterview();

    EXPECT_EQ(sizeof(gSaveBlock1Ptr->gabbyAndTyData.mapnum), sizeof(SavedLocationCode));
    EXPECT_EQ(gSaveBlock1Ptr->gabbyAndTyData.mapnum, EncodeSavedLocation(section));
    EXPECT_EQ(TV_DecodeLocation(gSaveBlock1Ptr->gabbyAndTyData.mapnum), section);
    ExpectLocationName(gSaveBlock1Ptr->gabbyAndTyData.mapnum, section);
}

TEST("Record-mixed TV copies preserve reviewed compact location aliases")
{
    TVShow source[2] = {0};
    TVShow copied[2] = {0};
    const MapSectionId section = MAPSEC_LITTLEROOT_TOWN;
    const SavedLocationCode wideCode = EncodeSavedLocationWithRegistry(SYNTHETIC_TV_SECTION, &sSyntheticTvRegistry);

    TV_StoreLocation(&source[0].worldOfMasters.location, section);
    source[1].breakingNews.location = wideCode;
    CopyTVShowsForRecordMixing(copied, source, ARRAY_COUNT(source));

    EXPECT_EQ(copied[0].worldOfMasters.location, EncodeSavedLocation(section));
    EXPECT_EQ(TV_DecodeLocation(copied[0].worldOfMasters.location), section);
    ExpectLocationName(copied[0].worldOfMasters.location, section);

    EXPECT(SYNTHETIC_TV_SECTION > 0xFF);
    EXPECT_EQ(sizeof(copied[1].breakingNews.location), sizeof(SavedLocationCode));
    EXPECT_EQ(copied[1].breakingNews.location, SYNTHETIC_TV_LOCATION_CODE);
    EXPECT_EQ(DecodeSavedLocationWithRegistry(copied[1].breakingNews.location, &sSyntheticTvRegistry), SYNTHETIC_TV_SECTION);
}
