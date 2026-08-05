#include "global.h"
#include "fieldmap.h"
#include "test/test.h"
#include "constants/metatile_behaviors.h"

TEST("Map layout formats expose exact Emerald, FRLG, and Johto traits")
{
    const struct MapLayoutFormatTraits *emerald = GetMapLayoutFormatTraits(MAP_LAYOUT_FORMAT_EMERALD);
    const struct MapLayoutFormatTraits *frlg = GetMapLayoutFormatTraits(MAP_LAYOUT_FORMAT_FRLG);
    const struct MapLayoutFormatTraits *johto = GetMapLayoutFormatTraits(MAP_LAYOUT_FORMAT_JOHTO);

    EXPECT_EQ(emerald->primaryTileCount, 512);
    EXPECT_EQ(emerald->primaryMetatileCount, 512);
    EXPECT_EQ(emerald->primaryPaletteCount, 6);
    EXPECT_EQ(emerald->borderFormat, BORDER_EMERALD);
    EXPECT_EQ(emerald->doorFormat, DOOR_EMERALD);
    EXPECT_EQ(emerald->escalatorFormat, ESCALATOR_EMERALD);
    EXPECT_EQ(emerald->shopPaletteFormat, SHOP_PALETTE_EMERALD);

    EXPECT_EQ(frlg->primaryTileCount, 640);
    EXPECT_EQ(frlg->primaryMetatileCount, 640);
    EXPECT_EQ(frlg->primaryPaletteCount, 7);
    EXPECT_EQ(frlg->borderFormat, BORDER_FRLG);
    EXPECT_EQ(frlg->doorFormat, DOOR_FRLG);
    EXPECT_EQ(frlg->escalatorFormat, ESCALATOR_FRLG);
    EXPECT_EQ(frlg->shopPaletteFormat, SHOP_PALETTE_FRLG);

    EXPECT_EQ(johto->primaryTileCount, 640);
    EXPECT_EQ(johto->primaryMetatileCount, 640);
    EXPECT_EQ(johto->primaryPaletteCount, 7);
    EXPECT_EQ(johto->borderFormat, BORDER_EMERALD);
    EXPECT_EQ(johto->doorFormat, DOOR_FRLG);
    EXPECT_EQ(johto->escalatorFormat, ESCALATOR_EMERALD);
    EXPECT_EQ(johto->shopPaletteFormat, SHOP_PALETTE_EMERALD);
}

TEST("Metatile decoding follows the selected primary or secondary tileset width")
{
    static const u16 primaryAttributes[] = {0x0034};
    static const u32 secondaryAttributes[] = {0x00000155};
    static const struct Tileset primary =
    {
        .flags = TILESET_FLAGS(FALSE, METATILE_ATTRIBUTES_EMERALD_U16),
        .metatileAttributes = primaryAttributes,
    };
    static const struct Tileset secondary =
    {
        .flags = TILESET_FLAGS(TRUE, METATILE_ATTRIBUTES_FRLG_U32),
        .metatileAttributes = secondaryAttributes,
    };
    static const struct MapLayout layout =
    {
        .primaryTileset = &primary,
        .secondaryTileset = &secondary,
        .format = MAP_LAYOUT_FORMAT_JOHTO,
    };
    const struct MapLayout *savedLayout = gMapHeader.mapLayout;

    gMapHeader.mapLayout = &layout;
    EXPECT_EQ(GetAttributeByMetatileIdAndMapLayout(0, METATILE_ATTRIBUTE_BEHAVIOR), 0x34);
    EXPECT_EQ(GetAttributeByMetatileIdAndMapLayout(640, METATILE_ATTRIBUTE_BEHAVIOR), 0x155);
    gMapHeader.mapLayout = savedLayout;
}

TEST("Metatile decoding also supports u32 primary and u16 secondary tilesets")
{
    static const u32 primaryAttributes[] = {0x00000155};
    static const u16 secondaryAttributes[] = {0x0034};
    static const struct Tileset primary =
    {
        .flags = TILESET_FLAGS(FALSE, METATILE_ATTRIBUTES_FRLG_U32),
        .metatileAttributes = primaryAttributes,
    };
    static const struct Tileset secondary =
    {
        .flags = TILESET_FLAGS(TRUE, METATILE_ATTRIBUTES_EMERALD_U16),
        .metatileAttributes = secondaryAttributes,
    };
    static const struct MapLayout layout =
    {
        .primaryTileset = &primary,
        .secondaryTileset = &secondary,
        .format = MAP_LAYOUT_FORMAT_JOHTO,
    };
    const struct MapLayout *savedLayout = gMapHeader.mapLayout;

    gMapHeader.mapLayout = &layout;
    EXPECT_EQ(GetAttributeByMetatileIdAndMapLayout(0, METATILE_ATTRIBUTE_BEHAVIOR), 0x155);
    EXPECT_EQ(GetAttributeByMetatileIdAndMapLayout(640, METATILE_ATTRIBUTE_BEHAVIOR), 0x34);
    gMapHeader.mapLayout = savedLayout;
}

TEST("Invalid layout and metatile attribute formats fail closed")
{
    static const u32 attributes[] = {0xFFFFFFFF};
    static const struct Tileset invalidTileset =
    {
        .flags = TILESET_FLAGS(FALSE, METATILE_ATTRIBUTE_FORMAT_COUNT),
        .metatileAttributes = attributes,
    };
    static const struct MapLayout invalidLayout =
    {
        .primaryTileset = &invalidTileset,
        .secondaryTileset = &invalidTileset,
        .format = MAP_LAYOUT_FORMAT_INVALID,
    };
    const struct MapLayoutFormatTraits *traits = GetMapLayoutFormatTraits(MAP_LAYOUT_FORMAT_INVALID);
    const struct MapLayout *savedLayout = gMapHeader.mapLayout;
    const struct BackupMapLayout savedBackupLayout = gBackupMapLayout;

    EXPECT_EQ(traits->primaryTileCount, 0);
    EXPECT_EQ(traits->primaryMetatileCount, 0);
    EXPECT_EQ(traits->primaryPaletteCount, 0);
    EXPECT_EQ(traits->borderFormat, BORDER_INVALID);
    EXPECT_EQ(traits->doorFormat, DOOR_INVALID);
    EXPECT_EQ(traits->escalatorFormat, ESCALATOR_INVALID);
    EXPECT_EQ(traits->shopPaletteFormat, SHOP_PALETTE_INVALID);
    EXPECT_EQ(GetTilesetAttributeFormat(&invalidTileset), METATILE_ATTRIBUTES_INVALID);
    EXPECT_EQ(GetMetatileAttribute(&invalidTileset, 0), MB_INVALID);
    EXPECT_EQ(ExtractMetatileAttribute(0xFFFFFFFF, METATILE_ATTRIBUTE_BEHAVIOR, METATILE_ATTRIBUTES_INVALID), MB_INVALID);
    EXPECT_EQ(ExtractMetatileAttribute(0xFFFFFFFF, METATILE_ATTRIBUTES_ALL, METATILE_ATTRIBUTES_INVALID), MB_INVALID);
    EXPECT_EQ(ExtractMetatileAttribute(0xFFFFFFFF, METATILE_ATTRIBUTE_LAYER_TYPE, METATILE_ATTRIBUTES_INVALID), METATILE_LAYER_TYPE_NORMAL);

    gMapHeader.mapLayout = &invalidLayout;
    gBackupMapLayout.width = 0;
    gBackupMapLayout.height = 0;
    gBackupMapLayout.map = NULL;
    EXPECT_EQ(GetAttributeByMetatileIdAndMapLayout(0, METATILE_ATTRIBUTE_BEHAVIOR), MB_INVALID);
    EXPECT_EQ(MapGridGetCollisionAt(0, 0), 1);
    EXPECT_EQ(MapGridGetElevationAt(0, 0), ELEVATION_TRANSITION);
    gBackupMapLayout = savedBackupLayout;
    gMapHeader.mapLayout = savedLayout;
}

TEST("Tileset and palette loaders reject invalid layouts before using tileset data")
{
    static const struct Tileset inaccessibleTileset =
    {
        .tiles = (const u32 *)1,
        .palettes = (const u16 (*)[16])1,
    };
    static const struct MapLayout invalidLayout =
    {
        .primaryTileset = &inaccessibleTileset,
        .secondaryTileset = &inaccessibleTileset,
        .format = MAP_LAYOUT_FORMAT_INVALID,
    };

    // These must all return before dereferencing either tileset or deriving a
    // secondary offset from the invalid format's zero-valued traits.
    CopyPrimaryTilesetToVram(&invalidLayout);
    CopySecondaryTilesetToVram(&invalidLayout);
    CopySecondaryTilesetToVramUsingHeap(&invalidLayout);
    CopyMapTilesetsToVram(&invalidLayout);
    LoadSecondaryTilesetPalette(&invalidLayout, FALSE);
    LoadMapTilesetPalettes(&invalidLayout);

    // NULL is invalid for the same reason and must also be a no-op.
    CopyPrimaryTilesetToVram(NULL);
    CopySecondaryTilesetToVram(NULL);
    CopySecondaryTilesetToVramUsingHeap(NULL);
    CopyMapTilesetsToVram(NULL);
    LoadSecondaryTilesetPalette(NULL, FALSE);
    LoadMapTilesetPalettes(NULL);
}
