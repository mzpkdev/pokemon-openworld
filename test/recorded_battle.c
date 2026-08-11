#include "global.h"
#include "recorded_battle.h"
#include "util.h"
#include "constants/apprentice.h"
#include "constants/battle_frontier.h"
#include "constants/opponents.h"
#include "constants/trainers.h"
#include "test/test.h"

#define TRAINER_RED_TEST 1
#define BATTLE_TOWER_SINGLE_FLAGS (BATTLE_TYPE_TRAINER | BATTLE_TYPE_BATTLE_TOWER)
#define BATTLE_TOWER_MULTI_FLAGS (BATTLE_TYPE_TRAINER | BATTLE_TYPE_BATTLE_TOWER \
                                | BATTLE_TYPE_DOUBLE | BATTLE_TYPE_INGAME_PARTNER \
                                | BATTLE_TYPE_MULTI | BATTLE_TYPE_TWO_OPPONENTS)

static EWRAM_DATA struct RecordedBattleSave sRecordedBattleSave;
static EWRAM_DATA struct RecordedBattleSave sRecordedBattleBefore;

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

TEST("Recorded battles reject the legacy partner sentinel without mutation")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(
        BATTLE_TYPE_INGAME_PARTNER,
        RECORDED_BATTLE_LEGACY_PARTNER_BASE + PARTNER_NONE);
    u16 partnerId = save->partnerId;

    FinalizeRecordedBattleSave(save);

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(save->partnerId, partnerId);
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

TEST("Recorded partner wild battles reject nonzero opponents without normalizing them")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(
        BATTLE_TYPE_INGAME_PARTNER,
        RECORDED_BATTLE_LEGACY_PARTNER_BASE + PARTNER_STEVEN);
    u16 partnerId = save->partnerId;

    save->opponentA = RECORDED_BATTLE_LEGACY_PARTNER_BASE;
    save->opponentB = RECORDED_BATTLE_LEGACY_PARTNER_BASE + 1;
    FinalizeRecordedBattleSave(save);

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(save->opponentA, RECORDED_BATTLE_LEGACY_PARTNER_BASE);
    EXPECT_EQ(save->opponentB, RECORDED_BATTLE_LEGACY_PARTNER_BASE + 1);
    EXPECT_EQ(save->partnerId, partnerId);
}

TEST("Recorded partner wild battles reject absent and invalid current partners")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(
        BATTLE_TYPE_INGAME_PARTNER,
        TRAINER_PARTNER(PARTNER_NONE));

    FinalizeRecordedBattleSave(save);
    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));

    save = InitRecordedBattleSave(
        BATTLE_TYPE_INGAME_PARTNER,
        TRAINER_PARTNER(PARTNER_COUNT));
    FinalizeRecordedBattleSave(save);
    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
}

TEST("Recorded battles without an in-game partner leave legacy-range values unchanged")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(
        BATTLE_TYPE_FRONTIER,
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

TEST("Recorded ordinary battles reject invalid trainers after checksum validation")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(BATTLE_TYPE_TRAINER, TRAINER_NONE);

    save->opponentA = TRAINERS_COUNT;
    FinalizeRecordedBattleSave(save);

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
}

TEST("Recorded ordinary and special battles keep their explicit namespaces")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(BATTLE_TYPE_TRAINER, TRAINER_NONE);

    save->opponentA = TRAINER_RED_TEST;
    FinalizeRecordedBattleSave(save);
    EXPECT(RecordedBattle_TestValidateAndNormalizeSave(save));

    save = InitRecordedBattleSave(BATTLE_TYPE_PIKE, TRAINER_NONE);
    save->opponentA = 0xFFFF;
    FinalizeRecordedBattleSave(save);
    EXPECT(RecordedBattle_TestValidateAndNormalizeSave(save));
}

TEST("Recorded frontier trainer battles reject out-of-domain active opponents without mutation")
{
    static const u16 invalidTrainerIds[] =
    {
        TRAINER_FRONTIER_BRAIN + 1,
        0xFFFF,
    };

    for (u32 i = 0; i < ARRAY_COUNT(invalidTrainerIds); i++)
    {
        struct RecordedBattleSave *save = InitRecordedBattleSave(BATTLE_TOWER_SINGLE_FLAGS, TRAINER_NONE);

        save->opponentA = invalidTrainerIds[i];
        FinalizeRecordedBattleSave(save);
        sRecordedBattleBefore = *save;

        EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
        EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);
    }

    struct RecordedBattleSave *save = InitRecordedBattleSave(BATTLE_TOWER_MULTI_FLAGS, 0);
    save->opponentA = 0;
    save->opponentB = 0xFFFF;
    FinalizeRecordedBattleSave(save);
    sRecordedBattleBefore = *save;

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);
}

TEST("Recorded frontier partner battles reject non-facility IDs without mutation")
{
    static const u16 invalidPartnerIds[] =
    {
        TRAINER_EREADER,
        TRAINER_PARTNER(PARTNER_STEVEN),
        0xFFFF,
    };

    for (u32 i = 0; i < ARRAY_COUNT(invalidPartnerIds); i++)
    {
        struct RecordedBattleSave *save = InitRecordedBattleSave(
            BATTLE_TOWER_MULTI_FLAGS,
            invalidPartnerIds[i]);

        save->opponentA = 0;
        save->opponentB = 1;
        FinalizeRecordedBattleSave(save);
        sRecordedBattleBefore = *save;

        EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
        EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);
    }
}

TEST("Recorded frontier partner battles reject legacy global IDs without mutation")
{
    static const u16 invalidPartnerIds[] =
    {
        RECORDED_BATTLE_LEGACY_PARTNER_BASE + PARTNER_NONE,
        RECORDED_BATTLE_LEGACY_PARTNER_BASE + PARTNER_COUNT,
    };

    for (u32 i = 0; i < ARRAY_COUNT(invalidPartnerIds); i++)
    {
        struct RecordedBattleSave *save = InitRecordedBattleSave(
            BATTLE_TOWER_MULTI_FLAGS,
            invalidPartnerIds[i]);

        save->opponentA = 0;
        save->opponentB = 1;
        FinalizeRecordedBattleSave(save);
        sRecordedBattleBefore = *save;

        EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
        EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);
    }
}

TEST("Recorded frontier partners require the native Battle Tower multi topology")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(
        BATTLE_TOWER_MULTI_FLAGS & ~BATTLE_TYPE_MULTI,
        0);

    save->opponentA = 0;
    save->opponentB = 1;
    FinalizeRecordedBattleSave(save);
    sRecordedBattleBefore = *save;

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);
}

TEST("Recorded Battle Tower multi battles accept facility partners")
{
    static const u16 validPartnerIds[] =
    {
        0,
        FRONTIER_TRAINERS_COUNT - 1,
        TRAINER_RECORD_MIXING_FRIEND,
        TRAINER_RECORD_MIXING_APPRENTICE,
        TRAINER_EREADER - 1,
    };

    for (u32 i = 0; i < ARRAY_COUNT(validPartnerIds); i++)
    {
        struct RecordedBattleSave *save = InitRecordedBattleSave(
            BATTLE_TOWER_MULTI_FLAGS,
            validPartnerIds[i]);

        save->opponentA = 0;
        save->opponentB = 1;
        if (validPartnerIds[i] >= TRAINER_RECORD_MIXING_FRIEND
         && validPartnerIds[i] < TRAINER_RECORD_MIXING_APPRENTICE)
            save->recordMixFriendClass = FACILITY_CLASSES_COUNT - 1;
        if (validPartnerIds[i] >= TRAINER_RECORD_MIXING_APPRENTICE)
            save->apprenticeId = NUM_APPRENTICES - 1;
        FinalizeRecordedBattleSave(save);

        EXPECT(RecordedBattle_TestValidateAndNormalizeSave(save));
        EXPECT_EQ(save->partnerId, validPartnerIds[i]);
    }
}

TEST("Recorded frontier partner metadata is bounded without mutation")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(
        BATTLE_TOWER_MULTI_FLAGS,
        TRAINER_RECORD_MIXING_FRIEND);

    save->opponentA = 0;
    save->opponentB = 1;
    save->recordMixFriendClass = FACILITY_CLASSES_COUNT;
    FinalizeRecordedBattleSave(save);
    sRecordedBattleBefore = *save;

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);

    save = InitRecordedBattleSave(
        BATTLE_TOWER_MULTI_FLAGS,
        TRAINER_RECORD_MIXING_APPRENTICE);

    save->opponentA = 0;
    save->opponentB = 1;
    save->apprenticeId = NUM_APPRENTICES;
    FinalizeRecordedBattleSave(save);
    sRecordedBattleBefore = *save;

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);
}

TEST("Recorded Battle Tower singles bound record-mix opponent metadata")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(BATTLE_TOWER_SINGLE_FLAGS, TRAINER_NONE);

    save->opponentA = TRAINER_RECORD_MIXING_FRIEND;
    save->recordMixFriendClass = FACILITY_CLASSES_COUNT;
    FinalizeRecordedBattleSave(save);
    sRecordedBattleBefore = *save;

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);

    save->recordMixFriendClass = FACILITY_CLASSES_COUNT - 1;
    FinalizeRecordedBattleSave(save);
    EXPECT(RecordedBattle_TestValidateAndNormalizeSave(save));
}

TEST("Recorded Battle Tower singles bound apprentice opponent metadata")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(BATTLE_TOWER_SINGLE_FLAGS, TRAINER_NONE);

    save->opponentA = TRAINER_RECORD_MIXING_APPRENTICE;
    save->apprenticeId = NUM_APPRENTICES;
    FinalizeRecordedBattleSave(save);
    sRecordedBattleBefore = *save;

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);

    save->apprenticeId = NUM_APPRENTICES - 1;
    FinalizeRecordedBattleSave(save);
    EXPECT(RecordedBattle_TestValidateAndNormalizeSave(save));
}

TEST("Recorded Battle Tower multis bound special opponent A with an ordinary partner")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(BATTLE_TOWER_MULTI_FLAGS, 0);

    save->opponentA = TRAINER_RECORD_MIXING_FRIEND;
    save->opponentB = 1;
    save->recordMixFriendClass = FACILITY_CLASSES_COUNT;
    FinalizeRecordedBattleSave(save);
    sRecordedBattleBefore = *save;

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);

    save->recordMixFriendClass = FACILITY_CLASSES_COUNT - 1;
    FinalizeRecordedBattleSave(save);
    EXPECT(RecordedBattle_TestValidateAndNormalizeSave(save));
}

TEST("Recorded Battle Tower multis bound special opponent B with an ordinary partner")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(BATTLE_TOWER_MULTI_FLAGS, 0);

    save->opponentA = 1;
    save->opponentB = TRAINER_RECORD_MIXING_APPRENTICE;
    save->apprenticeId = NUM_APPRENTICES;
    FinalizeRecordedBattleSave(save);
    sRecordedBattleBefore = *save;

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);

    save->apprenticeId = NUM_APPRENTICES - 1;
    FinalizeRecordedBattleSave(save);
    EXPECT(RecordedBattle_TestValidateAndNormalizeSave(save));
}

TEST("Recorded metadata ignores absent B slots and unrelated facility domains")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(BATTLE_TOWER_SINGLE_FLAGS, TRAINER_NONE);

    save->opponentA = 0;
    save->opponentB = TRAINER_RECORD_MIXING_FRIEND;
    save->recordMixFriendClass = FACILITY_CLASSES_COUNT;
    save->apprenticeId = NUM_APPRENTICES;
    FinalizeRecordedBattleSave(save);

    EXPECT(RecordedBattle_TestValidateAndNormalizeSave(save));

    save->opponentA = 0xFFFF;
    FinalizeRecordedBattleSave(save);
    sRecordedBattleBefore = *save;
    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);
}

TEST("Recorded Frontier modes accept their maximum native normal trainer")
{
    static const struct
    {
        u32 flags;
        u8 facility;
    } modes[] =
    {
        {BATTLE_TYPE_BATTLE_TOWER, FRONTIER_FACILITY_TOWER},
        {BATTLE_TYPE_DOME, FRONTIER_FACILITY_DOME},
        {BATTLE_TYPE_PALACE, FRONTIER_FACILITY_PALACE},
        {BATTLE_TYPE_ARENA, FRONTIER_FACILITY_ARENA},
        {BATTLE_TYPE_FACTORY, FRONTIER_FACILITY_FACTORY},
        {BATTLE_TYPE_BATTLE_TOWER, FRONTIER_FACILITY_PIKE},
        {BATTLE_TYPE_PYRAMID, FRONTIER_FACILITY_PYRAMID},
    };

    for (u32 i = 0; i < ARRAY_COUNT(modes); i++)
    {
        struct RecordedBattleSave *save = InitRecordedBattleSave(BATTLE_TYPE_TRAINER | modes[i].flags, TRAINER_NONE);
        save->opponentA = FRONTIER_TRAINERS_COUNT - 1;
        save->frontierFacility = modes[i].facility;
        FinalizeRecordedBattleSave(save);

        EXPECT(RecordedBattle_TestValidateAndNormalizeSave(save));
    }
}

TEST("Recorded Frontier brains require the matching facility and reject facility seven without mutation")
{
    static const struct
    {
        u32 flags;
        u8 facility;
    } modes[] =
    {
        {BATTLE_TYPE_BATTLE_TOWER, FRONTIER_FACILITY_TOWER},
        {BATTLE_TYPE_DOME, FRONTIER_FACILITY_DOME},
        {BATTLE_TYPE_PALACE, FRONTIER_FACILITY_PALACE},
        {BATTLE_TYPE_ARENA, FRONTIER_FACILITY_ARENA},
        {BATTLE_TYPE_FACTORY, FRONTIER_FACILITY_FACTORY},
        {BATTLE_TYPE_BATTLE_TOWER, FRONTIER_FACILITY_PIKE},
        {BATTLE_TYPE_PYRAMID, FRONTIER_FACILITY_PYRAMID},
    };

    for (u32 i = 0; i < ARRAY_COUNT(modes); i++)
    {
        struct RecordedBattleSave *save = InitRecordedBattleSave(BATTLE_TYPE_TRAINER | modes[i].flags, TRAINER_NONE);
        save->opponentA = TRAINER_FRONTIER_BRAIN;
        save->frontierFacility = modes[i].facility;
        FinalizeRecordedBattleSave(save);
        EXPECT(RecordedBattle_TestValidateAndNormalizeSave(save));
    }

    struct RecordedBattleSave *save = InitRecordedBattleSave(
        BATTLE_TYPE_TRAINER | BATTLE_TYPE_PYRAMID,
        TRAINER_NONE);
    save->opponentA = TRAINER_FRONTIER_BRAIN;
    save->frontierFacility = NUM_FRONTIER_FACILITIES;
    FinalizeRecordedBattleSave(save);
    sRecordedBattleBefore = *save;

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);
}

TEST("Recorded Battle Tower-only trainer domains reject other facilities")
{
    static const u16 towerOnlyIds[] =
    {
        TRAINER_RECORD_MIXING_FRIEND,
        TRAINER_RECORD_MIXING_APPRENTICE,
    };

    for (u32 i = 0; i < ARRAY_COUNT(towerOnlyIds); i++)
    {
        struct RecordedBattleSave *save = InitRecordedBattleSave(
            BATTLE_TYPE_TRAINER | BATTLE_TYPE_DOME,
            TRAINER_NONE);
        save->opponentA = towerOnlyIds[i];
        save->frontierFacility = FRONTIER_FACILITY_DOME;
        FinalizeRecordedBattleSave(save);
        sRecordedBattleBefore = *save;

        EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
        EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);
    }
}

TEST("Recorded e-Reader trainer forms remain unrecordable without mutation")
{
    static const u32 battleFlags[] =
    {
        BATTLE_TOWER_SINGLE_FLAGS,
        BATTLE_TYPE_TRAINER | BATTLE_TYPE_EREADER_TRAINER,
    };

    for (u32 i = 0; i < ARRAY_COUNT(battleFlags); i++)
    {
        struct RecordedBattleSave *save = InitRecordedBattleSave(battleFlags[i], TRAINER_NONE);
        save->opponentA = TRAINER_EREADER;
        save->frontierFacility = FRONTIER_FACILITY_TOWER;
        FinalizeRecordedBattleSave(save);
        sRecordedBattleBefore = *save;

        EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
        EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);
    }
}

TEST("Recorded playback bounds indexed options and Frontier level metadata without mutation")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(BATTLE_TYPE_TRAINER, TRAINER_NONE);
    save->opponentA = TRAINER_RED_TEST;
    save->textSpeed = OPTIONS_TEXT_SPEED_INSTANT + 1;
    FinalizeRecordedBattleSave(save);
    sRecordedBattleBefore = *save;

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);

    save = InitRecordedBattleSave(BATTLE_TOWER_SINGLE_FLAGS, TRAINER_NONE);
    save->opponentA = 0;
    save->lvlMode = FRONTIER_LVL_TENT + 1;
    FinalizeRecordedBattleSave(save);
    sRecordedBattleBefore = *save;

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);

    save->lvlMode = FRONTIER_LVL_TENT;
    FinalizeRecordedBattleSave(save);
    EXPECT(RecordedBattle_TestValidateAndNormalizeSave(save));
}

TEST("Recorded Battle Tower partner topology rejects link-only hybrids")
{
    static const u32 invalidFlags[] =
    {
        BATTLE_TOWER_MULTI_FLAGS | BATTLE_TYPE_TOWER_LINK_MULTI,
        BATTLE_TOWER_MULTI_FLAGS | BATTLE_TYPE_RECORDED_LINK,
    };

    for (u32 i = 0; i < ARRAY_COUNT(invalidFlags); i++)
    {
        struct RecordedBattleSave *save = InitRecordedBattleSave(invalidFlags[i], 0);

        save->opponentA = 1;
        save->opponentB = 2;
        FinalizeRecordedBattleSave(save);
        sRecordedBattleBefore = *save;

        EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
        EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);
    }
}

TEST("Recorded Battle Tower partners reject Pike facility metadata without mutation")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(BATTLE_TOWER_MULTI_FLAGS, 0);
    save->opponentA = 0;
    save->opponentB = 1;
    save->frontierFacility = FRONTIER_FACILITY_PIKE;
    FinalizeRecordedBattleSave(save);
    sRecordedBattleBefore = *save;

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);
}

TEST("Recorded Trainer Hill saves remain unrecordable without mutation")
{
    struct RecordedBattleSave *save = InitRecordedBattleSave(
        BATTLE_TYPE_TRAINER | BATTLE_TYPE_TRAINER_HILL,
        TRAINER_NONE);
    save->opponentA = 0;
    FinalizeRecordedBattleSave(save);
    sRecordedBattleBefore = *save;

    EXPECT(!RecordedBattle_TestValidateAndNormalizeSave(save));
    EXPECT_EQ(memcmp(save, &sRecordedBattleBefore, sizeof(sRecordedBattleBefore)), 0);
}
