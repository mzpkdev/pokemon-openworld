#include "global.h"
#include "generated_dungeon_persistence.h"
#include "random.h"

STATIC_ASSERT(sizeof(struct GeneratedDungeonSaveRecord) == GENERATED_DUNGEON_RECORD_SIZE, GeneratedDungeonSaveRecordSize);
STATIC_ASSERT(offsetof(struct GeneratedDungeonSaveRecord, recoveryCrc32) == 16, GeneratedDungeonRecoveryCrcOffset);
STATIC_ASSERT(offsetof(struct GeneratedDungeonSaveRecord, payloadVersion) == 20, GeneratedDungeonPayloadOffset);
STATIC_ASSERT(offsetof(struct GeneratedDungeonSaveRecord, progress) == 28, GeneratedDungeonProgressOffset);
STATIC_ASSERT(offsetof(struct GeneratedDungeonSaveRecord, recordCrc32) == 60, GeneratedDungeonRecordCrcOffset);
STATIC_ASSERT(sizeof(gSaveBlock1Ptr->generatedDungeon) == sizeof(struct GeneratedDungeonSaveRecord), GeneratedDungeonSaveBlockSize);

static bool8 IsValidFacing(u8 facing)
{
    return facing >= DIR_SOUTH && facing < CARDINAL_DIRECTION_COUNT;
}

void GeneratedDungeonRecordClear(struct GeneratedDungeonSaveRecord *record)
{
    u8 *bytes = (u8 *)record;
    u32 i;

    for (i = 0; i < sizeof(*record); i++)
        bytes[i] = 0;
}

void GeneratedDungeonRecordFinalize(struct GeneratedDungeonSaveRecord *record)
{
    u32 i;

    record->magic = GENERATED_DUNGEON_RECORD_MAGIC;
    record->envelopeVersion = GENERATED_DUNGEON_ENVELOPE_VERSION;
    record->recordSize = sizeof(*record);
    record->payloadVersion = GENERATED_DUNGEON_PAYLOAD_VERSION;
    record->progressBitCount = GENERATED_DUNGEON_RECORD_PROGRESS_BITS;
    record->flags = 0;
    for (i = 0; i < sizeof(record->reserved); i++)
        record->reserved[i] = 0;
    record->recoveryCrc32 = Crc32B((const u8 *)record, offsetof(struct GeneratedDungeonSaveRecord, recoveryCrc32));
    record->recordCrc32 = Crc32B((const u8 *)record, offsetof(struct GeneratedDungeonSaveRecord, recordCrc32));
}

bool8 GeneratedDungeonRecordHasValidRecoveryEnvelope(const struct GeneratedDungeonSaveRecord *record)
{
    if (record->magic != GENERATED_DUNGEON_RECORD_MAGIC
     || record->envelopeVersion != GENERATED_DUNGEON_ENVELOPE_VERSION
     || record->recordSize != sizeof(*record)
     || record->recoveryReserved != 0)
        return FALSE;
    return record->recoveryCrc32 == Crc32B((const u8 *)record, offsetof(struct GeneratedDungeonSaveRecord, recoveryCrc32));
}

bool8 GeneratedDungeonRecordHasValidFullEnvelope(const struct GeneratedDungeonSaveRecord *record)
{
    u32 i;

    if (!GeneratedDungeonRecordHasValidRecoveryEnvelope(record))
        return FALSE;
    if (record->flags != 0
     || record->progressBitCount > GENERATED_DUNGEON_RECORD_PROGRESS_BITS
     || !IsValidFacing(record->originFacing)
     || !IsValidFacing(record->destinationFacing))
        return FALSE;
    if (record->payloadVersion == GENERATED_DUNGEON_PAYLOAD_VERSION
     && (record->providerId == 0 || record->generationVersion == 0))
        return FALSE;
    for (i = 0; i < sizeof(record->reserved); i++)
    {
        if (record->reserved[i] != 0)
            return FALSE;
    }
    return record->recordCrc32 == Crc32B((const u8 *)record, offsetof(struct GeneratedDungeonSaveRecord, recordCrc32));
}

enum GeneratedDungeonRecordClassification GeneratedDungeonRecordClassify(const struct GeneratedDungeonSaveRecord *record, bool8 payloadSupported)
{
    u32 i;
    const u8 *bytes = (const u8 *)record;

    for (i = 0; i < sizeof(*record); i++)
    {
        if (bytes[i] != 0)
            break;
    }
    if (i == sizeof(*record) || !GeneratedDungeonRecordHasValidFullEnvelope(record))
        return GENERATED_DUNGEON_RECORD_INACTIVE;
    if (record->payloadVersion == GENERATED_DUNGEON_PAYLOAD_VERSION && payloadSupported)
        return GENERATED_DUNGEON_RECORD_ACTIVE;
    return GENERATED_DUNGEON_RECORD_RECOVER_TO_ORIGIN;
}
