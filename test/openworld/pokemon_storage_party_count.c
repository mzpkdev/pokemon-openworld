#include "global.h"
#include "pokemon.h"
#include "pokemon_storage_system.h"
#include "test/test.h"

static void CreatePartyMon(u32 slot, enum Species species)
{
    CreateMon(&gParties[B_TRAINER_PLAYER][slot], species, 5, 0, OTID_STRUCT_PLAYER_ID);
}

TEST("PC deposit compacts the party and immediately refreshes its count")
{
    ZeroPlayerPartyMons();
    CreatePartyMon(0, SPECIES_BULBASAUR);
    CreatePartyMon(1, SPECIES_CHARMANDER);
    CreatePartyMon(2, SPECIES_SQUIRTLE);
    CalculatePlayerPartyCount();

    ZeroMonData(&gParties[B_TRAINER_PLAYER][1]);
    PokemonStorageSystem_TestFinalizePartyChange(TRUE);

    EXPECT_EQ(gPartiesCount[B_TRAINER_PLAYER], 2);
    EXPECT_EQ(GetMonData(&gParties[B_TRAINER_PLAYER][0], MON_DATA_SPECIES), SPECIES_BULBASAUR);
    EXPECT_EQ(GetMonData(&gParties[B_TRAINER_PLAYER][1], MON_DATA_SPECIES), SPECIES_SQUIRTLE);
    EXPECT_EQ(GetMonData(&gParties[B_TRAINER_PLAYER][2], MON_DATA_SPECIES), SPECIES_NONE);
}

TEST("PC withdrawal immediately refreshes the party count after placement")
{
    ZeroPlayerPartyMons();
    CreatePartyMon(0, SPECIES_BULBASAUR);
    CreatePartyMon(1, SPECIES_CHARMANDER);
    CalculatePlayerPartyCount();

    CreatePartyMon(2, SPECIES_SQUIRTLE);
    PokemonStorageSystem_TestFinalizePartyChange(FALSE);

    EXPECT_EQ(gPartiesCount[B_TRAINER_PLAYER], 3);
    EXPECT_EQ(GetMonData(&gParties[B_TRAINER_PLAYER][2], MON_DATA_SPECIES), SPECIES_SQUIRTLE);
}
