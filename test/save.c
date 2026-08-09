#include "global.h"
#include "battle_tower.h"
#include "pokemon_storage_system.h"
#include "save.h"
#include "test/test.h"

// If you would like to ensure save compatibility, update the values below with those for your hack. You can find these through the debug menu.
// Please note that this simple check is not 100% foolproof, but should be able to catch most unintended shifts.
#define T_SAVEBLOCK1_SIZE 15568
#define T_SAVEBLOCK2_SIZE 3884
#define T_SAVEBLOCK3_SIZE 4
#define T_POKEMONSTORAGE_SIZE 34144

TEST("SaveBlock1 is backwards compatible")
{
    EXPECT_EQ(sizeof(struct SaveBlock1), T_SAVEBLOCK1_SIZE);
}

TEST("SaveBlock2 is backwards compatible")
{
    EXPECT_EQ(sizeof(struct SaveBlock2), T_SAVEBLOCK2_SIZE);
}

TEST("SaveBlock3 is backwards compatible")
{
    EXPECT_EQ(sizeof(struct SaveBlock3), T_SAVEBLOCK3_SIZE);
}

TEST("PokemonStorage is backwards compatible")
{
    EXPECT_EQ(sizeof(struct PokemonStorage), T_POKEMONSTORAGE_SIZE);
}

TEST("Save sector physical layout matches the frozen contract")
{
    EXPECT_EQ(sizeof(struct SaveSector), 4096);
    EXPECT_EQ(offsetof(struct SaveSector, data), 0);
    EXPECT_EQ(offsetof(struct SaveSector, saveBlock3Chunk), 3968);
    EXPECT_EQ(offsetof(struct SaveSector, id), 4084);
    EXPECT_EQ(offsetof(struct SaveSector, checksum), 4086);
    EXPECT_EQ(offsetof(struct SaveSector, signature), 4088);
    EXPECT_EQ(offsetof(struct SaveSector, counter), 4092);
    EXPECT_EQ(SAVE_BLOCK_3_CHUNK_SIZE * NUM_SECTORS_PER_SLOT, 1624);
}

TEST("Record mixing checksums cover the frozen byte ranges")
{
    struct EmeraldBattleTowerRecord emerald = {0};
    struct RSBattleTowerRecord ruby = {0};
    u8 *emeraldBytes = (u8 *)&emerald;
    u8 *rubyBytes = (u8 *)&ruby;

    for (u32 i = 0; i < offsetof(struct EmeraldBattleTowerRecord, checksum); i++)
        emeraldBytes[i] = i;
    for (u32 i = 0; i < offsetof(struct RSBattleTowerRecord, checksum); i++)
        rubyBytes[i] = i;

    CalcEmeraldBattleTowerChecksum(&emerald);
    CalcRubyBattleTowerChecksum(&ruby);
    EXPECT_EQ(emerald.checksum, 0x9C6227D4);
    EXPECT_EQ(ruby.checksum, 0xB48C6430);
}

#undef T_SAVEBLOCK1_SIZE
#undef T_SAVEBLOCK2_SIZE
#undef T_SAVEBLOCK3_SIZE
#undef T_POKEMONSTORAGE_SIZE
