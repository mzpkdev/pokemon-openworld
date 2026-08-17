#include "global.h"
#include "generated_dungeon_persistence.h"
#include "random.h"
#include "test/test.h"

static struct GeneratedDungeonSaveRecord MakeRecord(void)
{
    struct GeneratedDungeonSaveRecord record;

    GeneratedDungeonRecordClear(&record);
    record.providerId = 7;
    record.generationVersion = 3;
    record.seed = 0x12345678;
    record.progress = 0xFEDCBA9876543210ULL;
    record.origin = (struct WarpData){ .mapGroup = 2, .mapNum = 3, .warpId = 4, .x = -300, .y = 301 };
    record.originFacing = DIR_EAST;
    record.destination = (struct WarpData){ .mapGroup = 6, .mapNum = 7, .warpId = 8, .x = 1234, .y = -1235 };
    record.destinationFacing = DIR_SOUTH;
    GeneratedDungeonRecordFinalize(&record);
    return record;
}

static void RefreshChecksums(struct GeneratedDungeonSaveRecord *record)
{
    record->recoveryCrc32 = Crc32B((const u8 *)record, offsetof(struct GeneratedDungeonSaveRecord, recoveryCrc32));
    record->recordCrc32 = Crc32B((const u8 *)record, offsetof(struct GeneratedDungeonSaveRecord, recordCrc32));
}

TEST("Generated dungeon save record has a fixed inactive representation")
{
    struct GeneratedDungeonSaveRecord record;
    const u8 *bytes;
    u32 i;

    GeneratedDungeonRecordClear(&record);
    EXPECT_EQ(sizeof(record), 64);
    EXPECT_EQ(offsetof(struct GeneratedDungeonSaveRecord, progress), 28);
    EXPECT_EQ(GeneratedDungeonRecordClassify(&record, TRUE), GENERATED_DUNGEON_RECORD_INACTIVE);
    bytes = (const u8 *)&record;
    for (i = 0; i < sizeof(record); i++)
        EXPECT_EQ(bytes[i], 0);
}

TEST("Generated dungeon save record protects recovery and full envelopes")
{
    struct GeneratedDungeonSaveRecord record = MakeRecord();

    EXPECT(GeneratedDungeonRecordHasValidRecoveryEnvelope(&record));
    EXPECT(GeneratedDungeonRecordHasValidFullEnvelope(&record));
    EXPECT_EQ(GeneratedDungeonRecordClassify(&record, TRUE), GENERATED_DUNGEON_RECORD_ACTIVE);
    EXPECT_EQ(GeneratedDungeonRecordClassify(&record, FALSE), GENERATED_DUNGEON_RECORD_RECOVER_TO_ORIGIN);

    record.seed++;
    EXPECT(GeneratedDungeonRecordHasValidRecoveryEnvelope(&record));
    EXPECT(!GeneratedDungeonRecordHasValidFullEnvelope(&record));
    EXPECT_EQ(GeneratedDungeonRecordClassify(&record, TRUE), GENERATED_DUNGEON_RECORD_INACTIVE);

    record = MakeRecord();
    record.origin.x++;
    EXPECT(!GeneratedDungeonRecordHasValidRecoveryEnvelope(&record));
    EXPECT_EQ(GeneratedDungeonRecordClassify(&record, FALSE), GENERATED_DUNGEON_RECORD_INACTIVE);

    record = MakeRecord();
    record.reserved[0] = 1;
    RefreshChecksums(&record);
    EXPECT(!GeneratedDungeonRecordHasValidFullEnvelope(&record));
    EXPECT_EQ(GeneratedDungeonRecordClassify(&record, FALSE), GENERATED_DUNGEON_RECORD_INACTIVE);

    record = MakeRecord();
    record.flags = 1;
    RefreshChecksums(&record);
    EXPECT(!GeneratedDungeonRecordHasValidFullEnvelope(&record));

    record = MakeRecord();
    record.progressBitCount++;
    RefreshChecksums(&record);
    EXPECT(!GeneratedDungeonRecordHasValidFullEnvelope(&record));

    record = MakeRecord();
    record.providerId = 0;
    RefreshChecksums(&record);
    EXPECT(!GeneratedDungeonRecordHasValidFullEnvelope(&record));

    record = MakeRecord();
    record.generationVersion = 0;
    RefreshChecksums(&record);
    EXPECT(!GeneratedDungeonRecordHasValidFullEnvelope(&record));

    record = MakeRecord();
    record.destinationFacing = DIR_NONE;
    RefreshChecksums(&record);
    EXPECT(!GeneratedDungeonRecordHasValidFullEnvelope(&record));
}

TEST("Generated dungeon save record rejects unknown envelopes and recovers unsupported payloads")
{
    struct GeneratedDungeonSaveRecord record = MakeRecord();

    record.payloadVersion++;
    RefreshChecksums(&record);
    EXPECT(GeneratedDungeonRecordHasValidFullEnvelope(&record));
    EXPECT_EQ(GeneratedDungeonRecordClassify(&record, TRUE), GENERATED_DUNGEON_RECORD_RECOVER_TO_ORIGIN);

    record = MakeRecord();
    record.envelopeVersion++;
    RefreshChecksums(&record);
    EXPECT(!GeneratedDungeonRecordHasValidRecoveryEnvelope(&record));
    EXPECT_EQ(GeneratedDungeonRecordClassify(&record, TRUE), GENERATED_DUNGEON_RECORD_INACTIVE);

    record = MakeRecord();
    record.recordSize--;
    RefreshChecksums(&record);
    EXPECT(!GeneratedDungeonRecordHasValidRecoveryEnvelope(&record));
    EXPECT_EQ(GeneratedDungeonRecordClassify(&record, TRUE), GENERATED_DUNGEON_RECORD_INACTIVE);
}
