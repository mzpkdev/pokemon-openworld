#include "global.h"
#include "location_codecs.h"
#include "region_map.h"
#include "regions.h"
#include "generated/map_section_metadata.h"

#include "data/map_section_metadata.inc.c"

const struct MapSectionRegistry gMapSectionRegistry =
{
    .metadata = gMapSectionMetadata,
    .sectionToSavedLocation = gMapSectionToSavedLocation,
    .sectionToMetLocation = gMapSectionToMetLocation,
    .savedLocationToSection = gSavedLocationToMapSection,
    .metLocationToSection = gMetLocationToMapSection,
    .sectionCount = MAPSEC_COUNT,
};

STATIC_ASSERT(GENERATED_MAP_SECTION_COUNT == MAPSEC_COUNT, GeneratedMapSectionCountMismatch);
STATIC_ASSERT(sizeof(SavedLocationCode) == 1, SavedLocationCodeMustBeByteSized);
STATIC_ASSERT(sizeof(MetLocationCode) == 1, MetLocationCodeMustBeByteSized);
STATIC_ASSERT(SAVED_LOCATION_INVALID == 0xFF, SavedLocationInvalidEncoding);
STATIC_ASSERT(MET_LOCATION_INVALID == 0xFC, MetLocationInvalidEncoding);

SavedLocationCode EncodeSavedLocationWithRegistry(MapSectionId section, const struct MapSectionRegistry *registry)
{
    if (!IsValidMapSectionIdInRegistry(section, registry) || registry->sectionToSavedLocation == NULL)
        return SAVED_LOCATION_INVALID;
    return registry->sectionToSavedLocation[section];
}

MapSectionId DecodeSavedLocationWithRegistry(SavedLocationCode code, const struct MapSectionRegistry *registry)
{
    if (registry == NULL || registry->savedLocationToSection == NULL)
        return MAPSEC_INVALID;
    return registry->savedLocationToSection[code];
}

MetLocationCode EncodeMetLocationWithRegistry(MapSectionId section, const struct MapSectionRegistry *registry)
{
    if (!IsValidMapSectionIdInRegistry(section, registry) || registry->sectionToMetLocation == NULL)
        return MET_LOCATION_INVALID;
    return registry->sectionToMetLocation[section];
}

MapSectionId DecodeMetLocationWithRegistry(MetLocationCode code, const struct MapSectionRegistry *registry)
{
    if (registry == NULL || registry->metLocationToSection == NULL)
        return MAPSEC_INVALID;
    return registry->metLocationToSection[code];
}

SavedLocationCode EncodeSavedLocation(MapSectionId section)
{
    return EncodeSavedLocationWithRegistry(section, &gMapSectionRegistry);
}

MapSectionId DecodeSavedLocation(SavedLocationCode code)
{
    return DecodeSavedLocationWithRegistry(code, &gMapSectionRegistry);
}

MetLocationCode EncodeMetLocation(MapSectionId section)
{
    return EncodeMetLocationWithRegistry(section, &gMapSectionRegistry);
}

MapSectionId DecodeMetLocation(MetLocationCode code)
{
    return DecodeMetLocationWithRegistry(code, &gMapSectionRegistry);
}
