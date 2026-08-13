#include "global.h"
#include "fieldmap.h"
#include "tileset_anims.h"
#include "tilesets.h"
#include "test/test.h"

extern const u16 *const gTilesetAnims_General_Water[];
extern const u16 *const gTilesetAnims_General_SandWaterEdge[];
extern const u16 *const gTilesetAnims_Rustboro_WindyWater[];
extern const u16 *const gTilesetAnims_Lavaridge_Cave_Lava[];

struct ExpectedJohtoTransfer
{
    enum TilesetAnimTestJohtoAsset asset;
    const u8 *frameSequence;
    u8 frameCount;
    u8 period;
    u8 phase;
    u8 sourceTileOffset;
    u16 destinationTileOffset;
    u8 tileCount;
};

static const struct Tileset sNoAnimationTileset = {0};
static const u8 sLinearFrames4[] = {0, 1, 2, 3};
static const u8 sLinearFrames5[] = {0, 1, 2, 3, 4};
static const u8 sLinearFrames8[] = {0, 1, 2, 3, 4, 5, 6, 7};
static const u8 sNationalParkRedFrames[] = {0, 1, 2, 1};
static const u8 sNationalParkYellowFrames[] = {2, 1, 0, 1};
static const u8 sAzaleaGymFrames[] = {0, 1, 2, 1};

static void SetLayout(struct MapLayout *layout, const struct Tileset *primary, const struct Tileset *secondary, MapLayoutFormat format)
{
    *layout = (struct MapLayout)
    {
        .primaryTileset = primary,
        .secondaryTileset = secondary,
        .format = format,
    };
    gMapHeader.mapLayout = layout;
}

static void ExpectTransfer(u8 index, const u16 *src, u16 destinationTile, u16 tileCount)
{
    struct TilesetAnimTestTransfer transfer;

    TilesetAnimTest_GetTransfer(index, &transfer);
    if (transfer.src != src)
        Test_ExitWithResult(TEST_RESULT_FAIL, __LINE__, "%s:%d: transfer %d source expected %p, got %p", gTestRunnerState.test->filename, __LINE__, index, src, transfer.src);
    EXPECT_EQ(transfer.dest, (u16 *)(BG_VRAM + TILE_OFFSET_4BPP(destinationTile)));
    EXPECT_EQ(transfer.size, tileCount * TILE_SIZE_4BPP);
}

static void ExpectTransferGeometry(u8 index, u16 destinationTile, u16 tileCount)
{
    struct TilesetAnimTestTransfer transfer;

    TilesetAnimTest_GetTransfer(index, &transfer);
    EXPECT_NE(transfer.src, NULL);
    EXPECT_EQ(transfer.dest, (u16 *)(BG_VRAM + TILE_OFFSET_4BPP(destinationTile)));
    EXPECT_EQ(transfer.size, tileCount * TILE_SIZE_4BPP);
}

static void CheckJohtoPrimaryVariant(
    const struct Tileset *tileset,
    enum TilesetAnimTestJohtoAsset flower,
    enum TilesetAnimTestJohtoAsset sand,
    enum TilesetAnimTestJohtoAsset water)
{
    struct MapLayout layout;
    struct TilesetAnimTestState state;
    u16 tick;

    SetLayout(&layout, tileset, &sNoAnimationTileset, MAP_LAYOUT_FORMAT_JOHTO);
    InitTilesetAnimations();
    TilesetAnimTest_GetState(&state);
    EXPECT_EQ(state.primaryCounter, 0);
    EXPECT_EQ(state.primaryCounterMax, 256);
    EXPECT_NE(state.primaryCallback, NULL);

    // Two extra ticks prove that the counter wraps before dispatch and that the
    // first post-wrap flower is frame zero again.
    for (tick = 1; tick <= 258; tick++)
    {
        u16 timer = tick % 256;
        u8 count = 0;

        UpdateTilesetAnimations();
        if (timer % 8 == 0)
            ExpectTransfer(count++, TilesetAnimTest_GetJohtoRawFrame(sand, sLinearFrames8[(timer / 8) % ARRAY_COUNT(sLinearFrames8)]), 416, 18);
        if (timer % 16 == 2)
            ExpectTransfer(count++, TilesetAnimTest_GetJohtoRawFrame(flower, sLinearFrames5[(timer / 16) % ARRAY_COUNT(sLinearFrames5)]), 508, 4);
        if (timer % 16 == 3)
            ExpectTransfer(count++, TilesetAnimTest_GetJohtoRawFrame(water, sLinearFrames8[(timer / 16) % ARRAY_COUNT(sLinearFrames8)]) + 34 * TILE_SIZE_4BPP / sizeof(u16), 450, 12);
        EXPECT_EQ(TilesetAnimTest_GetTransferCount(), count);
    }
}

static void CheckJohtoSecondary(
    void (*init)(void),
    const struct ExpectedJohtoTransfer *expected,
    u8 expectedCount,
    u16 counterMax)
{
    struct MapLayout layout;
    struct TilesetAnimTestState state;
    u16 tick;

    SetLayout(&layout, &sNoAnimationTileset, &sNoAnimationTileset, MAP_LAYOUT_FORMAT_JOHTO);
    InitTilesetAnimations();
    init();
    TilesetAnimTest_GetState(&state);
    EXPECT_EQ(state.secondaryCounter, 0);
    EXPECT_EQ(state.secondaryCounterMax, counterMax);
    EXPECT_NE(state.secondaryCallback, NULL);

    // Run a complete scheduler cycle and enough of the next cycle to exercise
    // every phase after wrap. Each callback's production transfer list fixes
    // slot ordering when several transfers coincide.
    for (tick = 1; tick <= counterMax + 16; tick++)
    {
        u16 timer = tick % counterMax;
        u8 queued = 0;
        u8 i;

        UpdateTilesetAnimations();
        for (i = 0; i < expectedCount; i++)
        {
            const struct ExpectedJohtoTransfer *transfer = &expected[i];
            if (timer % transfer->period == transfer->phase)
            {
                u8 frame = (timer / transfer->period) % transfer->frameCount;
                const u16 *src = TilesetAnimTest_GetJohtoRawFrame(transfer->asset, transfer->frameSequence[frame])
                               + transfer->sourceTileOffset * TILE_SIZE_4BPP / sizeof(u16);
                ExpectTransfer(queued++, src, 640 + transfer->destinationTileOffset, transfer->tileCount);
            }
        }
        EXPECT_EQ(TilesetAnimTest_GetTransferCount(), queued);
    }
}

TEST("Johto primary scheduler executes every variant's complete traces and wrap")
{
    const struct MapLayout *savedLayout = gMapHeader.mapLayout;

    CheckJohtoPrimaryVariant(&gTileset_Johto_General,
        TILESET_ANIM_TEST_JOHTO_GENERAL_FLOWER,
        TILESET_ANIM_TEST_JOHTO_GENERAL_SAND,
        TILESET_ANIM_TEST_JOHTO_GENERAL_WATER);
    CheckJohtoPrimaryVariant(&gTileset_Johto_NorthEast,
        TILESET_ANIM_TEST_JOHTO_NORTH_EAST_FLOWER,
        TILESET_ANIM_TEST_JOHTO_NORTH_EAST_SAND,
        TILESET_ANIM_TEST_JOHTO_NORTH_EAST_WATER);
    CheckJohtoPrimaryVariant(&gTileset_Johto_South,
        TILESET_ANIM_TEST_JOHTO_SOUTH_FLOWER,
        TILESET_ANIM_TEST_JOHTO_SOUTH_SAND,
        TILESET_ANIM_TEST_JOHTO_SOUTH_WATER);
    CheckJohtoPrimaryVariant(&gTileset_Johto_NorthWest,
        TILESET_ANIM_TEST_JOHTO_NORTH_WEST_FLOWER,
        TILESET_ANIM_TEST_JOHTO_NORTH_WEST_SAND,
        TILESET_ANIM_TEST_JOHTO_NORTH_WEST_WATER);
    gMapHeader.mapLayout = savedLayout;
}

TEST("Johto secondary callbacks execute all seven transfer traces and wrap")
{
    static const struct ExpectedJohtoTransfer nationalPark[] =
    {
        {TILESET_ANIM_TEST_NATIONAL_PARK_LARGE, sLinearFrames4, ARRAY_COUNT(sLinearFrames4), 10, 0, 0, 88, 8},
        {TILESET_ANIM_TEST_NATIONAL_PARK_SMALL, sLinearFrames5, ARRAY_COUNT(sLinearFrames5), 12, 1, 0, 104, 8},
        {TILESET_ANIM_TEST_NATIONAL_PARK_RED, sNationalParkRedFrames, ARRAY_COUNT(sNationalParkRedFrames), 16, 2, 0, 96, 4},
        {TILESET_ANIM_TEST_NATIONAL_PARK_YELLOW, sNationalParkYellowFrames, ARRAY_COUNT(sNationalParkYellowFrames), 16, 12, 0, 100, 4},
    };
    static const struct ExpectedJohtoTransfer ecruteak[] =
    {
        {TILESET_ANIM_TEST_ECRUTEAK_THEATER, sLinearFrames5, ARRAY_COUNT(sLinearFrames5), 10, 0, 0, 104, 4},
    };
    static const struct ExpectedJohtoTransfer azalea[] =
    {
        {TILESET_ANIM_TEST_AZALEA_GYM, sAzaleaGymFrames, ARRAY_COUNT(sAzaleaGymFrames), 10, 0, 0, 99, 4},
    };
    static const struct ExpectedJohtoTransfer blackthorn[] =
    {
        {TILESET_ANIM_TEST_BLACKTHORN_GYM, sLinearFrames4, ARRAY_COUNT(sLinearFrames4), 16, 1, 0, 321, 4},
    };
    const struct MapLayout *savedLayout = gMapHeader.mapLayout;

    CheckJohtoSecondary(InitTilesetAnim_NationalPark, nationalPark, ARRAY_COUNT(nationalPark), 960);
    CheckJohtoSecondary(InitTilesetAnim_EcruteakTheater, ecruteak, ARRAY_COUNT(ecruteak), 960);
    CheckJohtoSecondary(InitTilesetAnim_AzaleaTown_Gym, azalea, ARRAY_COUNT(azalea), 960);
    CheckJohtoSecondary(InitTilesetAnim_BlackthornGym, blackthorn, ARRAY_COUNT(blackthorn), 160);
    gMapHeader.mapLayout = savedLayout;
}

TEST("Tileset scheduler orders slots, uses a live secondary base, and reinitializes only secondary state")
{
    struct MapLayout layout;
    struct TilesetAnimTestState before;
    struct TilesetAnimTestState after;
    const struct MapLayout *savedLayout = gMapHeader.mapLayout;

    SetLayout(&layout, &gTileset_Johto_General, &gTileset_NationalPark, MAP_LAYOUT_FORMAT_JOHTO);
    InitTilesetAnimations();
    UpdateTilesetAnimations();
    UpdateTilesetAnimations();
    EXPECT_EQ(TilesetAnimTest_GetTransferCount(), 2);
    ExpectTransfer(0, TilesetAnimTest_GetJohtoRawFrame(TILESET_ANIM_TEST_JOHTO_GENERAL_FLOWER, 0), 508, 4);
    ExpectTransfer(1, TilesetAnimTest_GetJohtoRawFrame(TILESET_ANIM_TEST_NATIONAL_PARK_RED, sNationalParkRedFrames[0]), 736, 4);

    while (TRUE)
    {
        TilesetAnimTest_GetState(&before);
        if (before.primaryCounter == 8)
            break;
        UpdateTilesetAnimations();
    }
    layout.secondaryTileset = &gTileset_EcruteakTheater;
    InitSecondaryTilesetAnimation();
    TilesetAnimTest_GetState(&after);
    EXPECT_EQ(after.primaryCounter, before.primaryCounter);
    EXPECT_EQ(after.primaryCounterMax, before.primaryCounterMax);
    EXPECT_EQ(after.primaryCallback, before.primaryCallback);
    EXPECT_EQ(after.secondaryCounter, 0);
    EXPECT_EQ(after.secondaryCounterMax, 960);
    EXPECT_EQ(after.secondaryCallback, before.secondaryCallback);
    UpdateTilesetAnimations();
    TilesetAnimTest_GetState(&after);
    EXPECT_EQ(after.primaryCounter, 9);
    EXPECT_EQ(after.secondaryCounter, 1);
    for (u8 i = 1; i < 10; i++)
        UpdateTilesetAnimations();
    EXPECT_EQ(TilesetAnimTest_GetTransferCount(), 2);
    ExpectTransfer(1, TilesetAnimTest_GetJohtoRawFrame(TILESET_ANIM_TEST_ECRUTEAK_THEATER, sLinearFrames5[1]), 744, 4);

    SetLayout(&layout, &sNoAnimationTileset, &gTileset_NationalPark, MAP_LAYOUT_FORMAT_JOHTO);
    InitTilesetAnimations();
    layout.format = MAP_LAYOUT_FORMAT_EMERALD;
    for (u8 i = 0; i < 10; i++)
        UpdateTilesetAnimations();
    EXPECT_EQ(TilesetAnimTest_GetTransferCount(), 1);
    ExpectTransfer(0, TilesetAnimTest_GetJohtoRawFrame(TILESET_ANIM_TEST_NATIONAL_PARK_LARGE, sLinearFrames4[1]), 512 + 88, 8);
    gMapHeader.mapLayout = savedLayout;
}

TEST("Hoenn, Kanto, and Sevii animation traces remain executable")
{
    static const struct Tileset general = {.callback = InitTilesetAnim_General};
    static const struct Tileset rustboro = {.callback = InitTilesetAnim_Rustboro};
    static const struct Tileset lavaridge = {.callback = InitTilesetAnim_Lavaridge};
    static const struct Tileset generalFrlg = {.callback = InitTilesetAnim_General_Frlg};
    static const struct Tileset mtEmber = {.callback = InitTilesetAnim_MtEmber};
    struct MapLayout layout;
    const struct MapLayout *savedLayout = gMapHeader.mapLayout;

    SetLayout(&layout, &general, &rustboro, MAP_LAYOUT_FORMAT_EMERALD);
    InitTilesetAnimations();
    UpdateTilesetAnimations();
    EXPECT_EQ(TilesetAnimTest_GetTransferCount(), 2);
    ExpectTransfer(0, gTilesetAnims_General_Water[0], 432, 30);
    ExpectTransfer(1, gTilesetAnims_Rustboro_WindyWater[7], 512 + 132, 4);

    layout.secondaryTileset = &lavaridge;
    InitSecondaryTilesetAnimation();
    UpdateTilesetAnimations();
    EXPECT_EQ(TilesetAnimTest_GetTransferCount(), 2);
    ExpectTransfer(0, gTilesetAnims_General_SandWaterEdge[0], 464, 10);
    ExpectTransfer(1, gTilesetAnims_Lavaridge_Cave_Lava[0], 512 + 160, 4);

    SetLayout(&layout, &generalFrlg, &mtEmber, MAP_LAYOUT_FORMAT_FRLG);
    InitTilesetAnimations();
    UpdateTilesetAnimations();
    EXPECT_EQ(TilesetAnimTest_GetTransferCount(), 1);
    ExpectTransferGeometry(0, 416, 48);
    for (u8 i = 1; i < 16; i++)
        UpdateTilesetAnimations();
    EXPECT_EQ(TilesetAnimTest_GetTransferCount(), 2);
    ExpectTransferGeometry(0, 464, 18);
    ExpectTransferGeometry(1, 896, 8);
    gMapHeader.mapLayout = savedLayout;
}
