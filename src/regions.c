#include "global.h"
#include "region_map.h"
#include "regions.h"

bool8 IsValidMapSectionIdInRegistry(MapSectionId section, const struct MapSectionRegistry *registry)
{
    return registry != NULL
        && registry->metadata != NULL
        && section < registry->sectionCount
        && registry->metadata[section].kind != MAP_SECTION_KIND_RESERVED
        && registry->metadata[section].kind != MAP_SECTION_KIND_INVALID;
}

bool8 TryGetRegionForSectionIdInRegistry(MapSectionId section, RegionId *region, const struct MapSectionRegistry *registry)
{
    if (!IsValidMapSectionIdInRegistry(section, registry) || region == NULL)
        return FALSE;

    *region = registry->metadata[section].region;
    return *region != REGION_NONE;
}

enum MapSectionKind GetMapSectionKindInRegistry(MapSectionId section, const struct MapSectionRegistry *registry)
{
    if (registry == NULL || registry->metadata == NULL || section >= registry->sectionCount)
        return MAP_SECTION_KIND_INVALID;
    return registry->metadata[section].kind;
}

bool8 IsValidMapSectionId(MapSectionId section)
{
    return IsValidMapSectionIdInRegistry(section, &gMapSectionRegistry);
}

bool8 TryGetRegionForSectionId(MapSectionId section, RegionId *region)
{
    return TryGetRegionForSectionIdInRegistry(section, region, &gMapSectionRegistry);
}

enum MapSectionKind GetMapSectionKind(MapSectionId section)
{
    return GetMapSectionKindInRegistry(section, &gMapSectionRegistry);
}

enum KantoSubRegion GetKantoSubregion(MapSectionId section)
{
    if (!IsValidMapSectionId(section) || gMapSectionMetadata[section].region != REGION_KANTO)
        return KANTO_SUBREGION_KANTO;

    switch (gMapSectionMetadata[section].regionMapType)
    {
    case REGION_MAP_SEVII123:
        return KANTO_SUBREGION_SEVII123;
    case REGION_MAP_SEVII45:
        return KANTO_SUBREGION_SEVII45;
    case REGION_MAP_SEVII67:
        return KANTO_SUBREGION_SEVII67;
    case REGION_MAP_KANTO:
    default:
        return KANTO_SUBREGION_KANTO;
    }
}
