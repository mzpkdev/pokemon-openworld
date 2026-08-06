#ifndef GUARD_tilesets_H
#define GUARD_tilesets_H

extern const u32 gTilesetTiles_General[];
extern const u16 gTilesetPalettes_General[][16];

extern const struct Tileset *const gTilesetPointer_SecretBase;
extern const struct Tileset *const gTilesetPointer_SecretBaseRedCave;

extern const struct Tileset gTileset_Building;
extern const struct Tileset gTileset_BuildingFrlg;
extern const struct Tileset gTileset_BrendansMaysHouse;
extern const struct Tileset gTileset_GenericBuilding1;
extern const struct Tileset gTileset_General;
extern const struct Tileset gTileset_Petalburg;
extern const struct Tileset gTileset_Rustboro;
extern const struct Tileset gTileset_Fallarbor;
extern const struct Tileset gTileset_Mauville;
extern const struct Tileset gTileset_Slateport;
extern const struct Tileset gTileset_Dewford;
extern const struct Tileset gTileset_Lilycove;
extern const struct Tileset gTileset_Mossdeep;
extern const struct Tileset gTileset_Sootopolis;
extern const struct Tileset gTileset_EverGrande;
extern const struct Tileset gTileset_Pacifidlog;
extern const struct Tileset gTileset_PetalburgGym;
extern const struct Tileset gTileset_PokemonCenter;
extern const struct Tileset gTileset_InsideShip;
extern const struct Tileset gTileset_Fallarbor;
extern const struct Tileset gTileset_Shop;
extern const struct Tileset gTileset_Dewford;
extern const struct Tileset gTileset_BattleFrontier;
extern const struct Tileset gTileset_BattleFrontierOutsideWest;
extern const struct Tileset gTileset_BattleFrontierOutsideEast;
extern const struct Tileset gTileset_BattleArena;
extern const struct Tileset gTileset_BattleDome;
extern const struct Tileset gTileset_BattlePalace;
extern const struct Tileset gTileset_Slateport;
extern const struct Tileset gTileset_Mauville;
extern const struct Tileset gTileset_BattleFrontierOutsideWest;
extern const struct Tileset gTileset_BattleTent;
extern const struct Tileset gTileset_TrainerHill;
extern const struct Tileset gTileset_General_Frlg;
extern const struct Tileset gTileset_PalletTown;
extern const struct Tileset gTileset_ViridianCity;
extern const struct Tileset gTileset_PewterCity;
extern const struct Tileset gTileset_SaffronCity;
extern const struct Tileset gTileset_CeruleanCity;
extern const struct Tileset gTileset_LavenderTown;
extern const struct Tileset gTileset_VermilionCity;
extern const struct Tileset gTileset_CeladonCity;
extern const struct Tileset gTileset_FuchsiaCity;
extern const struct Tileset gTileset_CinnabarIsland;
extern const struct Tileset gTileset_SeviiIslands123;
extern const struct Tileset gTileset_SeviiIslands45;
extern const struct Tileset gTileset_SeviiIslands67;
extern const struct Tileset gTileset_DepartmentStore;
extern const struct Tileset gTileset_PokemonCenterFrlg;
extern const struct Tileset gTileset_SilphCo;
extern const struct Tileset gTileset_SSAnne;
extern const struct Tileset gTileset_SeaCottage;
extern const struct Tileset gTileset_TrainerTower;

// JOHTO IMPORT BEGIN: externs
#if HAS_JOHTO_TILESETS
extern const struct Tileset gTileset_Johto_General;
extern const struct Tileset gTileset_Johto_Building;
extern const struct Tileset gTileset_Johto_NorthEast;
extern const struct Tileset gTileset_NewBarkTown;
extern const struct Tileset gTileset_CherrygroveCity;
extern const struct Tileset gTileset_Kanto_PokemonCenter;
extern const struct Tileset gTileset_JohtoMart;
extern const struct Tileset gTileset_House_Lab;
extern const struct Tileset gTileset_PlayersHouse;
extern const struct Tileset gTileset_Gate_Standard;
extern const struct Tileset gTileset_EcruteakTheater;
extern const struct Tileset gTileset_PowerPlant_GeneratorRoom;
extern const struct Tileset gTileset_Route32;
extern const struct Tileset gTileset_RuinsOfAlphWriting;
extern const struct Tileset gTileset_RuinsOfAlph_B1F;
extern const struct Tileset gTileset_RuinsOfAlph_Outside;
extern const struct Tileset gTileset_TrainerSchool;
extern const struct Tileset gTileset_VioletCity;
extern const struct Tileset gTileset_Johto_South;
extern const struct Tileset gTileset_AzaleaTown;
extern const struct Tileset gTileset_AzaleaTown_Gym;
extern const struct Tileset gTileset_Barn;
extern const struct Tileset gTileset_Cafe;
extern const struct Tileset gTileset_Cave_Default;
extern const struct Tileset gTileset_Cave_Gray;
extern const struct Tileset gTileset_Ecruteak_City;
extern const struct Tileset gTileset_Goldenrod;
extern const struct Tileset gTileset_GoldenrodCity_TrainStation;
extern const struct Tileset gTileset_GoldenrodDepartmentStore;
extern const struct Tileset gTileset_GoldenrodGameCorner;
extern const struct Tileset gTileset_GoldenrodUndergroundRocket;
extern const struct Tileset gTileset_GoldenrodUndergroundTunnel;
extern const struct Tileset gTileset_Goldenrod_Underground_Storage;
extern const struct Tileset gTileset_IlexForest;
extern const struct Tileset gTileset_JohtoBikeShop;
extern const struct Tileset gTileset_KurtsHouse;
extern const struct Tileset gTileset_NationalPark;
extern const struct Tileset gTileset_JohtoPokemonDayCare;
extern const struct Tileset gTileset_ShopRooftop;
extern const struct Tileset gTileset_BellchimeTrail;
extern const struct Tileset gTileset_BurnedTower;
extern const struct Tileset gTileset_CianwoodCity;
extern const struct Tileset gTileset_CianwoodCity_Gym;
extern const struct Tileset gTileset_EcruteakCity_Gym;
extern const struct Tileset gTileset_Johto_NorthWest;
extern const struct Tileset gTileset_Lighthouse;
extern const struct Tileset gTileset_OlivineCity;
extern const struct Tileset gTileset_PortIndoor;
extern const struct Tileset gTileset_Route38_Farmland;
extern const struct Tileset gTileset_WhirlIslands;
#endif // HAS_JOHTO_TILESETS
// JOHTO IMPORT END: externs

#endif //GUARD_tilesets_H
