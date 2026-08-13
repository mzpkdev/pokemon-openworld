#include "global.h"
#include "battle.h"
#include "egg_hatch.h"
#include "event_data.h"
#include "location_codecs.h"
#include "overworld.h"
#include "pokemon.h"
#include "test/test.h"
#include "constants/daycare.h"

TEST("Pokemon provenance preserves compact codes, special origins, and hatch locations")
{
    struct Pokemon mon;
    MetLocationCode metLocation;
    bool8 isEgg = TRUE;

    CreateMon(&mon, SPECIES_WOBBUFFET, 5, 0, OTID_STRUCT_PLAYER_ID);

    metLocation = EncodeMetLocation(MAPSEC_LITTLEROOT_TOWN);
    SetMonData(&mon, MON_DATA_MET_LOCATION, &metLocation);
    EXPECT_EQ(GetMonData(&mon, MON_DATA_MET_LOCATION), metLocation);
    EXPECT_EQ(DecodeMetLocation(metLocation), MAPSEC_LITTLEROOT_TOWN);

    metLocation = EncodeMetLocation(MAPSEC_JOHTO_VICTORY_ROAD);
    SetMonData(&mon, MON_DATA_MET_LOCATION, &metLocation);
    EXPECT_EQ(GetMonData(&mon, MON_DATA_MET_LOCATION), EncodeMetLocation(MAPSEC_VICTORY_ROAD));
    EXPECT_EQ(DecodeMetLocation(metLocation), MAPSEC_VICTORY_ROAD);

    metLocation = METLOC_SPECIAL_EGG;
    SetMonData(&mon, MON_DATA_MET_LOCATION, &metLocation);
    EXPECT_EQ(GetMonData(&mon, MON_DATA_MET_LOCATION), METLOC_SPECIAL_EGG);
    EXPECT_EQ(DecodeMetLocation(metLocation), MAPSEC_INVALID);

    metLocation = METLOC_IN_GAME_TRADE;
    SetMonData(&mon, MON_DATA_MET_LOCATION, &metLocation);
    EXPECT_EQ(GetMonData(&mon, MON_DATA_MET_LOCATION), METLOC_IN_GAME_TRADE);
    EXPECT_EQ(DecodeMetLocation(metLocation), MAPSEC_INVALID);

    metLocation = METLOC_FATEFUL_ENCOUNTER;
    SetMonData(&mon, MON_DATA_MET_LOCATION, &metLocation);
    EXPECT_EQ(GetMonData(&mon, MON_DATA_MET_LOCATION), METLOC_FATEFUL_ENCOUNTER);
    EXPECT_EQ(DecodeMetLocation(metLocation), MAPSEC_INVALID);

    CreateMon(&gParties[B_TRAINER_PLAYER][0], SPECIES_TOGEPI, EGG_HATCH_LEVEL, 0, OTID_STRUCT_PLAYER_ID);
    SetMonData(&gParties[B_TRAINER_PLAYER][0], MON_DATA_IS_EGG, &isEgg);
    gSpecialVar_0x8004 = 0;
    ScriptHatchMon();
    EXPECT_EQ(GetMonData(&gParties[B_TRAINER_PLAYER][0], MON_DATA_MET_LOCATION),
              EncodeMetLocation(GetCurrentRegionMapSectionId()));
}
