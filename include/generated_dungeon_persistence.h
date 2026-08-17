#ifndef GUARD_GENERATED_DUNGEON_PERSISTENCE_H
#define GUARD_GENERATED_DUNGEON_PERSISTENCE_H

#include "global.h"

#define GENERATED_DUNGEON_RECORD_SIZE 64
#define GENERATED_DUNGEON_RECORD_MAGIC 0x314E4447 // "GDN1"
#define GENERATED_DUNGEON_ENVELOPE_VERSION 1
#define GENERATED_DUNGEON_PAYLOAD_VERSION 1
#define GENERATED_DUNGEON_RECORD_PROGRESS_BITS 64

// The first 20 bytes are the version-stable recovery envelope. They contain
// only the origin context needed to leave an unsupported, otherwise valid run.
struct GeneratedDungeonSaveRecord
{
    u32 magic;
    u8 envelopeVersion;
    u8 recordSize;
    u8 originFacing;
    u8 recoveryReserved;
    struct WarpData origin;
    u32 recoveryCrc32;
    u8 payloadVersion;
    u8 generationVersion;
    u16 providerId;
    u32 seed;
    u64 progress;
    struct WarpData destination;
    u8 destinationFacing;
    u8 progressBitCount;
    u16 flags;
    u8 reserved[12];
    u32 recordCrc32;
};

enum GeneratedDungeonRecordClassification
{
    GENERATED_DUNGEON_RECORD_INACTIVE,
    GENERATED_DUNGEON_RECORD_ACTIVE,
    GENERATED_DUNGEON_RECORD_RECOVER_TO_ORIGIN,
};

void GeneratedDungeonRecordClear(struct GeneratedDungeonSaveRecord *record);
void GeneratedDungeonRecordFinalize(struct GeneratedDungeonSaveRecord *record);
bool8 GeneratedDungeonRecordHasValidRecoveryEnvelope(const struct GeneratedDungeonSaveRecord *record);
bool8 GeneratedDungeonRecordHasValidFullEnvelope(const struct GeneratedDungeonSaveRecord *record);
enum GeneratedDungeonRecordClassification GeneratedDungeonRecordClassify(const struct GeneratedDungeonSaveRecord *record, bool8 payloadSupported);

#endif // GUARD_GENERATED_DUNGEON_PERSISTENCE_H
