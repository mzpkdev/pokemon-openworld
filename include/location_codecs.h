#ifndef GUARD_LOCATION_CODECS_H
#define GUARD_LOCATION_CODECS_H

#include "global.h"
#include "regions.h"

#define SAVED_LOCATION_INVALID ((SavedLocationCode)0xFF)
#define MET_LOCATION_INVALID ((MetLocationCode)0xFC)

SavedLocationCode EncodeSavedLocation(MapSectionId section);
MapSectionId DecodeSavedLocation(SavedLocationCode code);
MetLocationCode EncodeMetLocation(MapSectionId section);
MapSectionId DecodeMetLocation(MetLocationCode code);

SavedLocationCode EncodeSavedLocationWithRegistry(MapSectionId section, const struct MapSectionRegistry *registry);
MapSectionId DecodeSavedLocationWithRegistry(SavedLocationCode code, const struct MapSectionRegistry *registry);
MetLocationCode EncodeMetLocationWithRegistry(MapSectionId section, const struct MapSectionRegistry *registry);
MapSectionId DecodeMetLocationWithRegistry(MetLocationCode code, const struct MapSectionRegistry *registry);

extern const SavedLocationCode gMapSectionToSavedLocation[MAPSEC_COUNT];
extern const MetLocationCode gMapSectionToMetLocation[MAPSEC_COUNT];
extern const MapSectionId gSavedLocationToMapSection[256];
extern const MapSectionId gMetLocationToMapSection[256];

#endif // GUARD_LOCATION_CODECS_H
