#ifndef GUARD_REGIONS_H
#define GUARD_REGIONS_H

#include "global.h"
#include "constants/regions.h"

enum MapSectionKind
{
    MAP_SECTION_KIND_GEOGRAPHIC,
    MAP_SECTION_KIND_SPECIAL,
    MAP_SECTION_KIND_RESERVED,
    MAP_SECTION_KIND_INVALID = 0xFF,
};

struct MapSectionMetadata
{
    RegionId region;
    u8 kind;
    u8 regionMapType;
    u8 reserved;
};

struct MapSectionRegistry
{
    const struct MapSectionMetadata *metadata;
    const SavedLocationCode *sectionToSavedLocation;
    const MetLocationCode *sectionToMetLocation;
    const MapSectionId *savedLocationToSection;
    const MapSectionId *metLocationToSection;
    u32 sectionCount;
};

#define REGION_NONE ((RegionId)0xFF)

bool8 IsValidMapSectionId(MapSectionId section);
bool8 TryGetRegionForSectionId(MapSectionId section, RegionId *region);
enum MapSectionKind GetMapSectionKind(MapSectionId section);
enum KantoSubRegion GetKantoSubregion(MapSectionId section);

bool8 IsValidMapSectionIdInRegistry(MapSectionId section, const struct MapSectionRegistry *registry);
bool8 TryGetRegionForSectionIdInRegistry(MapSectionId section, RegionId *region, const struct MapSectionRegistry *registry);
enum MapSectionKind GetMapSectionKindInRegistry(MapSectionId section, const struct MapSectionRegistry *registry);

extern const struct MapSectionMetadata gMapSectionMetadata[MAPSEC_COUNT];
extern const struct MapSectionRegistry gMapSectionRegistry;

static inline RegionId GetRegionForSectionId(MapSectionId section)
{
    RegionId region;
    if (!TryGetRegionForSectionId(section, &region))
        return REGION_NONE;
    return region;
}

static inline RegionId GetCurrentRegion(void)
{
    return GetRegionForSectionId(gMapHeader.regionMapSectionId);
}

#endif // GUARD_REGIONS_H
