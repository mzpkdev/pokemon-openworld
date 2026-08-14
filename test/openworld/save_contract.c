#include "global.h"
#include "battle_tower.h"
#include "save.h"
#include "test/test.h"

TEST("Save sector physical layout matches the frozen contract")
{
    EXPECT_EQ(sizeof(struct SaveBlock1), 15648);
    EXPECT_EQ(offsetof(struct SaveBlock1, trainerDefeated), 0x3CD0);
    EXPECT_EQ(sizeof(gSaveBlock1Ptr->trainerDefeated), 79);
    EXPECT_EQ(sizeof(struct SaveBlock1) - offsetof(struct SaveBlock1, trainerDefeated), 80);
    EXPECT_EQ(sizeof(struct SaveBlock1) - 3 * SECTOR_DATA_SIZE, 3744);
    EXPECT_EQ(4 * SECTOR_DATA_SIZE - sizeof(struct SaveBlock1), 224);
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
