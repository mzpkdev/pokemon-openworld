#include "global.h"
#include "recorded_battle.h"
#include "util.h"
#include "constants/opponents.h"
#include "test/test.h"

static EWRAM_DATA struct RecordedBattleSave sRecordedBattleSave;

static struct RecordedBattleSave *InitRecordedBattleSave(u32 battleFlags, u16 partnerId)
{
    memset(&sRecordedBattleSave, 0, sizeof(sRecordedBattleSave));
    sRecordedBattleSave.battleFlags = battleFlags;
    sRecordedBattleSave.partnerId = partnerId;
    return &sRecordedBattleSave;
}

static void FinalizeRecordedBattleSave(struct RecordedBattleSave *save)
{
    save->checksum = CalcByteArraySum((const u8 *)save, sizeof(*save) - sizeof(save->checksum));
}

TEST("Recorded battles normalize the legacy Steven partner ID after validation")
{
    u32 checksum;
    struct RecordedBattleSave *save = InitRecordedBattleSave(
        BATTLE_TYPE_INGAME_PARTNER,
        RECORDED_BATTLE_LEGACY_PARTNER_BASE + PARTNER_STEVEN);

    FinalizeRecordedBattleSave(save);
    checksum = save->checksum;

    EXPECT(RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(save->partnerId, TRAINER_PARTNER(PARTNER_STEVEN));
    EXPECT_EQ(save->checksum, checksum);
}

TEST("Recorded battles normalize the complete legacy partner namespace including its sentinel")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(
        BATTLE_TYPE_INGAME_PARTNER,
        RECORDED_BATTLE_LEGACY_PARTNER_BASE + PARTNER_NONE);

    FinalizeRecordedBattleSave(save);

    EXPECT(RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(save->partnerId, TRAINER_PARTNER(PARTNER_NONE));
}

TEST("Recorded battles leave current partner IDs unchanged")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(
        BATTLE_TYPE_INGAME_PARTNER,
        TRAINER_PARTNER(PARTNER_STEVEN));

    FinalizeRecordedBattleSave(save);

    EXPECT(RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(save->partnerId, TRAINER_PARTNER(PARTNER_STEVEN));
}

TEST("Recorded battles never normalize ordinary trainer IDs stored as opponents")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(
        BATTLE_TYPE_INGAME_PARTNER,
        RECORDED_BATTLE_LEGACY_PARTNER_BASE + PARTNER_STEVEN);

    save->opponentA = RECORDED_BATTLE_LEGACY_PARTNER_BASE;
    save->opponentB = RECORDED_BATTLE_LEGACY_PARTNER_BASE + 1;
    FinalizeRecordedBattleSave(save);

    EXPECT(RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(save->opponentA, RECORDED_BATTLE_LEGACY_PARTNER_BASE);
    EXPECT_EQ(save->opponentB, RECORDED_BATTLE_LEGACY_PARTNER_BASE + 1);
    EXPECT_EQ(save->partnerId, TRAINER_PARTNER(PARTNER_STEVEN));
}

TEST("Recorded battles without an in-game partner leave legacy-range values unchanged")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(
        BATTLE_TYPE_TRAINER,
        RECORDED_BATTLE_LEGACY_PARTNER_BASE + PARTNER_STEVEN);

    FinalizeRecordedBattleSave(save);

    EXPECT(RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(save->partnerId, RECORDED_BATTLE_LEGACY_PARTNER_BASE + PARTNER_STEVEN);
}

TEST("Recorded battles reject bad checksums before normalizing partner IDs")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(
        BATTLE_TYPE_INGAME_PARTNER,
        RECORDED_BATTLE_LEGACY_PARTNER_BASE + PARTNER_STEVEN);

    FinalizeRecordedBattleSave(save);
    save->checksum++;

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(save->partnerId, RECORDED_BATTLE_LEGACY_PARTNER_BASE + PARTNER_STEVEN);
}
