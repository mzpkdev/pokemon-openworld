#ifndef GUARD_TILESET_ANIMS_H
#define GUARD_TILESET_ANIMS_H

void InitTilesetAnimations(void);
void InitSecondaryTilesetAnimation(void);
void UpdateTilesetAnimations(void);
void TransferTilesetAnimsBuffer(void);

void InitTilesetAnim_General(void);
void InitTilesetAnim_Petalburg(void);
void InitTilesetAnim_Rustboro(void);
void InitTilesetAnim_Dewford(void);
void InitTilesetAnim_Slateport(void);
void InitTilesetAnim_Mauville(void);
void InitTilesetAnim_Lavaridge(void);
void InitTilesetAnim_Fallarbor(void);
void InitTilesetAnim_Fortree(void);
void InitTilesetAnim_Lilycove(void);
void InitTilesetAnim_Mossdeep(void);
void InitTilesetAnim_EverGrande(void);
void InitTilesetAnim_Pacifidlog(void);
void InitTilesetAnim_Sootopolis(void);
void InitTilesetAnim_BattleFrontierOutsideWest(void);
void InitTilesetAnim_BattleFrontierOutsideEast(void);
void InitTilesetAnim_Building(void);
void InitTilesetAnim_Cave(void);
void InitTilesetAnim_BikeShop(void);
void InitTilesetAnim_Underwater(void);
void InitTilesetAnim_SootopolisGym(void);
void InitTilesetAnim_MauvilleGym(void);
void InitTilesetAnim_EliteFour(void);
void InitTilesetAnim_BattleDome(void);
void InitTilesetAnim_BattlePyramid(void);

// Johto
void InitTilesetAnim_JohtoGeneral(void);
void InitTilesetAnim_NationalPark(void);
void InitTilesetAnim_EcruteakTheater(void);
void InitTilesetAnim_AzaleaTown_Gym(void);
void InitTilesetAnim_BlackthornGym(void);

// FRLG
void InitTilesetAnim_General_Frlg(void);
void InitTilesetAnim_CeladonCity(void);
void InitTilesetAnim_VermilionGym(void);
void InitTilesetAnim_CeladonGym(void);
void InitTilesetAnim_SilphCo(void);
void InitTilesetAnim_MtEmber(void);

#if TESTING
enum TilesetAnimTestJohtoAsset
{
    TILESET_ANIM_TEST_JOHTO_GENERAL_FLOWER,
    TILESET_ANIM_TEST_JOHTO_GENERAL_SAND,
    TILESET_ANIM_TEST_JOHTO_GENERAL_WATER,
    TILESET_ANIM_TEST_JOHTO_NORTH_EAST_FLOWER,
    TILESET_ANIM_TEST_JOHTO_NORTH_EAST_SAND,
    TILESET_ANIM_TEST_JOHTO_NORTH_EAST_WATER,
    TILESET_ANIM_TEST_JOHTO_SOUTH_FLOWER,
    TILESET_ANIM_TEST_JOHTO_SOUTH_SAND,
    TILESET_ANIM_TEST_JOHTO_SOUTH_WATER,
    TILESET_ANIM_TEST_JOHTO_NORTH_WEST_FLOWER,
    TILESET_ANIM_TEST_JOHTO_NORTH_WEST_SAND,
    TILESET_ANIM_TEST_JOHTO_NORTH_WEST_WATER,
    TILESET_ANIM_TEST_NATIONAL_PARK_LARGE,
    TILESET_ANIM_TEST_NATIONAL_PARK_SMALL,
    TILESET_ANIM_TEST_NATIONAL_PARK_RED,
    TILESET_ANIM_TEST_NATIONAL_PARK_YELLOW,
    TILESET_ANIM_TEST_ECRUTEAK_THEATER,
    TILESET_ANIM_TEST_AZALEA_GYM,
    TILESET_ANIM_TEST_BLACKTHORN_GYM,
};

struct TilesetAnimTestTransfer
{
    const u16 *src;
    u16 *dest;
    u16 size;
};

struct TilesetAnimTestState
{
    u16 primaryCounter;
    u16 primaryCounterMax;
    u16 secondaryCounter;
    u16 secondaryCounterMax;
    const void *primaryCallback;
    const void *secondaryCallback;
};

u8 TilesetAnimTest_GetTransferCount(void);
void TilesetAnimTest_GetTransfer(u8 index, struct TilesetAnimTestTransfer *transfer);
void TilesetAnimTest_GetState(struct TilesetAnimTestState *state);
const u16 *TilesetAnimTest_GetJohtoRawFrame(enum TilesetAnimTestJohtoAsset asset, u8 frameNumber);
#endif

#endif // GUARD_TILESET_ANIMS_H
