#include "global.h"
#include "battle_tower.h"
#include "daycare.h"
#include "hall_of_fame.h"
#include "pokemon.h"
#include "pokemon_storage_system.h"
#include "recorded_battle.h"
#include "save.h"
#include "trainer_hill.h"
#include "tv.h"
#include "constants/trade.h"

#define ABI_ROOT(type, name) \
    __attribute__((used)) struct type *const abi_root_##name = 0

ABI_ROOT(SaveBlock1, save_block_1);
ABI_ROOT(SaveBlock2, save_block_2);
ABI_ROOT(SaveBlock3, save_block_3);
ABI_ROOT(PokemonStorage, pokemon_storage);
ABI_ROOT(BoxPokemon, box_pokemon);
ABI_ROOT(Pokemon, party_pokemon);
ABI_ROOT(PokemonSubstruct0, pokemon_substruct_0);
ABI_ROOT(PokemonSubstruct1, pokemon_substruct_1);
ABI_ROOT(PokemonSubstruct2, pokemon_substruct_2);
ABI_ROOT(PokemonSubstruct3, pokemon_substruct_3);
ABI_ROOT(DayCare, daycare);
ABI_ROOT(BattleFrontier, battle_frontier);
ABI_ROOT(EmeraldBattleTowerRecord, emerald_battle_tower_record);
ABI_ROOT(RSBattleTowerRecord, rs_battle_tower_record);
ABI_ROOT(RecordedBattleSave, recorded_battle);
ABI_ROOT(TrainerHillSave, trainer_hill_save);
ABI_ROOT(TrainerHillChallenge, trainer_hill_challenge);
ABI_ROOT(HallofFameTeam, hall_of_fame);
ABI_ROOT(GabbyAndTyData, gabby_and_ty);
ABI_ROOT(SaveSector, save_sector);
