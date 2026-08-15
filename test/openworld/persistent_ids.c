#include "global.h"
#include "event_data.h"
#include "persistent_ids.h"
#include "test/test.h"

TEST("Persistent trainer IDs preserve every published defeat flag")
{
    u16 flag;
    struct TrainerDefeatBinding binding;

    for (u16 trainerId = 0; trainerId < PERSISTENT_TRAINER_FLAG_COUNT; trainerId++)
    {
        EXPECT(PersistentId_GetTrainerDefeatBinding(trainerId, &binding));
        EXPECT_EQ(binding.storage, TRAINER_DEFEAT_STORAGE_FLAG);
        EXPECT_EQ(binding.id, 0x500 + trainerId);
        EXPECT_EQ(binding.bit, 0);
        EXPECT(PersistentId_GetTrainerDefeatFlag(trainerId, &flag));
        EXPECT_EQ(flag, 0x500 + trainerId);
        EXPECT_EQ(gTrainerDefeatFlagById[trainerId], 0x500 + trainerId);
    }
}

TEST("Persistent regional trainer IDs use every dedicated bitmap bit exactly once")
{
    u16 flag = 0x1234;
    struct TrainerDefeatBinding binding;
    bool32 defeated = TRUE;

    memset(gSaveBlock1Ptr->trainerDefeated, 0, sizeof(gSaveBlock1Ptr->trainerDefeated));
    for (u16 trainerId = PERSISTENT_TRAINER_BITMAP_FIRST; trainerId < PERSISTENT_TRAINER_COUNT; trainerId++)
    {
        u16 bitIndex = trainerId - PERSISTENT_TRAINER_BITMAP_FIRST;

        EXPECT(PersistentId_GetTrainerDefeatBinding(trainerId, &binding));
        EXPECT_EQ(binding.storage, TRAINER_DEFEAT_STORAGE_BITMAP);
        EXPECT_EQ(binding.id, bitIndex / 8);
        EXPECT_EQ(binding.bit, bitIndex % 8);
        EXPECT_EQ(gTrainerDefeatFlagById[trainerId], 0xFFFF);
        EXPECT(!PersistentId_GetTrainerDefeatFlag(trainerId, &flag));
        EXPECT_EQ(flag, 0x1234);
        EXPECT(PersistentId_GetTrainerDefeated(trainerId, &defeated));
        EXPECT(!defeated);
        EXPECT(PersistentId_SetTrainerDefeated(trainerId));
        EXPECT(PersistentId_GetTrainerDefeated(trainerId, &defeated));
        EXPECT(defeated);
    }
    for (u32 i = 0; i + 1 < sizeof(gSaveBlock1Ptr->trainerDefeated); i++)
        EXPECT_EQ(gSaveBlock1Ptr->trainerDefeated[i], 0xFF);
    EXPECT_EQ(gSaveBlock1Ptr->trainerDefeated[PERSISTENT_TRAINER_BITMAP_BYTES - 1], 3);

    for (u16 trainerId = PERSISTENT_TRAINER_BITMAP_FIRST; trainerId < PERSISTENT_TRAINER_COUNT; trainerId++)
        EXPECT(PersistentId_ClearTrainerDefeated(trainerId));
    for (u32 i = 0; i < sizeof(gSaveBlock1Ptr->trainerDefeated); i++)
        EXPECT_EQ(gSaveBlock1Ptr->trainerDefeated[i], 0);
}

TEST("Eugene owns the next stable trainer identity and bitmap defeat bit")
{
    struct TrainerDefeatBinding binding;

    EXPECT_EQ(TRAINER_SAILOR_EUGENE_JOHTO, 1482);
    EXPECT(PersistentId_GetTrainerDefeatBinding(
        TRAINER_SAILOR_EUGENE_JOHTO,
        &binding));
    EXPECT_EQ(binding.storage, TRAINER_DEFEAT_STORAGE_BITMAP);
    EXPECT_EQ(binding.id, 78);
    EXPECT_EQ(binding.bit, 0);
}

TEST("Wade owns his stable trainer identity and bitmap defeat bit")
{
    struct TrainerDefeatBinding binding;

    EXPECT_EQ(TRAINER_BUG_CATCHER_WADE_JOHTO, 1570);
    EXPECT(PersistentId_GetTrainerDefeatBinding(
        TRAINER_BUG_CATCHER_WADE_JOHTO,
        &binding));
    EXPECT_EQ(binding.storage, TRAINER_DEFEAT_STORAGE_BITMAP);
    EXPECT_EQ(binding.id, 89);
    EXPECT_EQ(binding.bit, 0);
}

TEST("Route 30 and Route 33 trainers own their stable identities and bitmap defeat bits")
{
    static const struct
    {
        u16 trainerId;
        u16 value;
        u8 id;
        u8 bit;
    } cases[] =
    {
        { TRAINER_HIKER_ANTHONY_JOHTO, 1576, 89, 6 },
        { TRAINER_YOUNGSTER_MIKEY_JOHTO, 1619, 95, 1 },
        { TRAINER_BUG_CATCHER_DON_JOHTO, 1662, 100, 4 },
    };
    u32 i;

    for (i = 0; i < ARRAY_COUNT(cases); i++)
    {
        struct TrainerDefeatBinding binding;

        EXPECT_EQ(cases[i].trainerId, cases[i].value);
        EXPECT(PersistentId_GetTrainerDefeatBinding(cases[i].trainerId, &binding));
        EXPECT_EQ(binding.storage, TRAINER_DEFEAT_STORAGE_BITMAP);
        EXPECT_EQ(binding.id, cases[i].id);
        EXPECT_EQ(binding.bit, cases[i].bit);
    }
}

TEST("Bulk fixed Johto trainer samples own stable bitmap defeat bits")
{
    static const u16 trainerIds[] =
    {
        TRAINER_YOUNGSTER_ALBERT_JOHTO,
        TRAINER_BIRD_KEEPER_ABE_JOHTO,
        TRAINER_FIREBREATHER_BILL_JOHTO,
        TRAINER_BEAUTY_VALERIE_JOHTO,
        TRAINER_BIRD_KEEPER_VANCE_JOHTO,
    };
    u32 i;

    for (i = 0; i < ARRAY_COUNT(trainerIds); i++)
    {
        struct TrainerDefeatBinding binding;
        u16 bitIndex = trainerIds[i] - PERSISTENT_TRAINER_BITMAP_FIRST;

        EXPECT(PersistentId_GetTrainerDefeatBinding(trainerIds[i], &binding));
        EXPECT_EQ(binding.storage, TRAINER_DEFEAT_STORAGE_BITMAP);
        EXPECT_EQ(binding.id, bitIndex / 8);
        EXPECT_EQ(binding.bit, bitIndex % 8);
    }
}

TEST("Surf and field-move Johto trainer samples own stable bitmap defeat bits")
{
    static const u16 trainerIds[] =
    {
        TRAINER_HIKER_PHILLIP_JOHTO,
        TRAINER_COOLTRAINER_NICK_JOHTO,
        TRAINER_SWIMMER_F_ELAINE_JOHTO,
        TRAINER_SWIMMER_M_BERKE_JOHTO,
        TRAINER_HIKER_BENJAMIN_JOHTO,
        TRAINER_FISHERMAN_ANDRE_JOHTO,
        TRAINER_FISHERMAN_SCOTT_JOHTO,
    };
    u32 i;

    for (i = 0; i < ARRAY_COUNT(trainerIds); i++)
    {
        struct TrainerDefeatBinding binding;
        u16 bitIndex = trainerIds[i] - PERSISTENT_TRAINER_BITMAP_FIRST;

        EXPECT(PersistentId_GetTrainerDefeatBinding(trainerIds[i], &binding));
        EXPECT_EQ(binding.storage, TRAINER_DEFEAT_STORAGE_BITMAP);
        EXPECT_EQ(binding.id, bitIndex / 8);
        EXPECT_EQ(binding.bit, bitIndex % 8);
    }
}

TEST("Ordinary Johto bulk trainer samples own stable bitmap defeat bits")
{
    static const u16 trainerIds[] =
    {
        TRAINER_PSYCHIC_M_NATHAN_JOHTO,
        TRAINER_COOLTRAINER_JENN_JOHTO,
        TRAINER_PARASOL_LADY_BEVERLY_JOHTO,
        TRAINER_BLACK_BELT_WAI_JOHTO,
        TRAINER_HIKER_NOLAND_JOHTO,
        TRAINER_COOLTRAINER_CAROL_JOHTO,
        TRAINER_FIREBREATHER_LYLE_JOHTO,
        TRAINER_BEAUTY_CASSIE_JOHTO,
    };
    u32 i;

    for (i = 0; i < ARRAY_COUNT(trainerIds); i++)
    {
        struct TrainerDefeatBinding binding;
        u16 bitIndex = trainerIds[i] - PERSISTENT_TRAINER_BITMAP_FIRST;

        EXPECT(PersistentId_GetTrainerDefeatBinding(trainerIds[i], &binding));
        EXPECT_EQ(binding.storage, TRAINER_DEFEAT_STORAGE_BITMAP);
        EXPECT_EQ(binding.id, bitIndex / 8);
        EXPECT_EQ(binding.bit, bitIndex % 8);
    }
}

TEST("Route 45 and Route 46 trainer samples own stable bitmap defeat bits")
{
    static const u16 trainerIds[] =
    {
        TRAINER_HIKER_ERIK_JOHTO,
        TRAINER_COOLTRAINER_KELLY_JOHTO,
        TRAINER_CAMPER_TED_JOHTO,
        TRAINER_HIKER_BAILEY_JOHTO,
    };
    u32 i;

    for (i = 0; i < ARRAY_COUNT(trainerIds); i++)
    {
        struct TrainerDefeatBinding binding;
        u16 bitIndex = trainerIds[i] - PERSISTENT_TRAINER_BITMAP_FIRST;

        EXPECT(PersistentId_GetTrainerDefeatBinding(trainerIds[i], &binding));
        EXPECT_EQ(binding.storage, TRAINER_DEFEAT_STORAGE_BITMAP);
        EXPECT_EQ(binding.id, bitIndex / 8);
        EXPECT_EQ(binding.bit, bitIndex % 8);
    }
}

TEST("Last admitted Johto trainer owns the final allocated bit without consuming padding")
{
    struct TrainerDefeatBinding binding;

    EXPECT_EQ(TRAINER_EXPERT_ROXANNE_JOHTO, 1675);
    EXPECT_EQ(PERSISTENT_TRAINER_COUNT, 1676);
    EXPECT(PersistentId_GetTrainerDefeatBinding(
        TRAINER_EXPERT_ROXANNE_JOHTO,
        &binding));
    EXPECT_EQ(binding.storage, TRAINER_DEFEAT_STORAGE_BITMAP);
    EXPECT_EQ(binding.id, 102);
    EXPECT_EQ(binding.bit, 1);
    EXPECT(!PersistentId_GetTrainerDefeatBinding(1676, &binding));
}

TEST("Persistent trainer IDs fail closed when invalid")
{
    u16 flag = 0x1234;
    struct TrainerDefeatBinding binding = {0x1234, 0x56, 0x78};

    EXPECT(!PersistentId_GetTrainerDefeatBinding(PERSISTENT_TRAINER_COUNT, &binding));
    EXPECT_EQ(binding.id, 0x1234);
    EXPECT_EQ(binding.storage, 0x56);
    EXPECT_EQ(binding.bit, 0x78);
    EXPECT(!PersistentId_GetTrainerDefeatFlag(PERSISTENT_TRAINER_COUNT, &flag));
    EXPECT_EQ(flag, 0x1234);
    EXPECT(!PersistentId_GetTrainerDefeatFlag(0xFFFF, &flag));
    EXPECT_EQ(flag, 0x1234);
    EXPECT(!PersistentId_GetTrainerDefeatFlag(0, NULL));
    EXPECT(!PersistentId_GetTrainerDefeatBinding(0, NULL));
}

TEST("Typed trainer defeat service reads sets and clears flag bindings")
{
    struct TrainerDefeatBinding binding;
    bool32 defeated = TRUE;

    EXPECT(PersistentId_GetTrainerDefeatBinding(0, &binding));
    FlagClear(binding.id);
    EXPECT(PersistentId_GetTrainerDefeated(0, &defeated));
    EXPECT(!defeated);
    EXPECT(PersistentId_SetTrainerDefeated(0));
    EXPECT(FlagGet(binding.id));
    EXPECT(PersistentId_GetTrainerDefeated(0, &defeated));
    EXPECT(defeated);
    EXPECT(PersistentId_ClearTrainerDefeated(0));
    EXPECT(!FlagGet(binding.id));
}

TEST("Typed trainer defeat service reads sets and clears variable bits")
{
    const struct TrainerDefeatBinding binding =
    {
        .id = VAR_UNUSED_0x40F7,
        .storage = TRAINER_DEFEAT_STORAGE_VARIABLE_BIT,
        .bit = 11,
    };
    bool32 defeated = TRUE;

    VarSet(binding.id, 0xA55A & ~(1 << binding.bit));
    EXPECT(PersistentId_TestGetTrainerDefeated(&binding, &defeated));
    EXPECT(!defeated);
    EXPECT(PersistentId_TestSetTrainerDefeated(&binding));
    EXPECT_EQ(VarGet(binding.id), 0xA55A | (1 << binding.bit));
    EXPECT(PersistentId_TestGetTrainerDefeated(&binding, &defeated));
    EXPECT(defeated);
    EXPECT(PersistentId_TestClearTrainerDefeated(&binding));
    EXPECT_EQ(VarGet(binding.id), 0xA55A & ~(1 << binding.bit));
}

TEST("Typed trainer defeat service rejects invalid storage without mutation")
{
    static const struct TrainerDefeatBinding invalid[] =
    {
        {.id = 0x500, .storage = 0xFF, .bit = 0},
        {.id = FLAG_TEMP_1, .storage = TRAINER_DEFEAT_STORAGE_FLAG, .bit = 0},
        {.id = FLAG_DAILY_SECRET_BASE, .storage = TRAINER_DEFEAT_STORAGE_FLAG, .bit = 0},
        {.id = FLAG_HIDE_MAP_NAME_POPUP, .storage = TRAINER_DEFEAT_STORAGE_FLAG, .bit = 0},
        {.id = 0x8FE, .storage = TRAINER_DEFEAT_STORAGE_FLAG, .bit = 0},
        {.id = 0x8FF, .storage = TRAINER_DEFEAT_STORAGE_FLAG, .bit = 0},
        {.id = FLAGS_COUNT, .storage = TRAINER_DEFEAT_STORAGE_FLAG, .bit = 0},
        {.id = 0x500, .storage = TRAINER_DEFEAT_STORAGE_FLAG, .bit = 1},
        {.id = VAR_TEMP_1, .storage = TRAINER_DEFEAT_STORAGE_VARIABLE_BIT, .bit = 0},
        {.id = VAR_DAILY_SLOTS, .storage = TRAINER_DEFEAT_STORAGE_VARIABLE_BIT, .bit = 0},
        {.id = VAR_0x8000, .storage = TRAINER_DEFEAT_STORAGE_VARIABLE_BIT, .bit = 0},
        {.id = TESTING_VARS_START, .storage = TRAINER_DEFEAT_STORAGE_VARIABLE_BIT, .bit = 0},
        {.id = VARS_END + 1, .storage = TRAINER_DEFEAT_STORAGE_VARIABLE_BIT, .bit = 0},
        {.id = VAR_UNUSED_0x40F7, .storage = TRAINER_DEFEAT_STORAGE_VARIABLE_BIT, .bit = 16},
        {.id = PERSISTENT_TRAINER_BITMAP_BYTES, .storage = TRAINER_DEFEAT_STORAGE_BITMAP, .bit = 0},
        {.id = 0, .storage = TRAINER_DEFEAT_STORAGE_BITMAP, .bit = 8},
    };
    const u16 flag = 0x500;
    const u16 var = VAR_UNUSED_0x40F7;
    static const u16 preservedFlags[] =
    {
        FLAG_TEMP_1,
        FLAG_DAILY_SECRET_BASE,
        FLAG_HIDE_MAP_NAME_POPUP,
        0x8FE,
        0x8FF,
    };
    static const struct
    {
        u16 id;
        u16 value;
    } preservedVars[] =
    {
        {VAR_TEMP_1, 0x1111},
        {VAR_DAILY_SLOTS, 0x2222},
        {VAR_0x8000, 0x3333},
        {TESTING_VARS_START, 0x4444},
    };
    u16 originalVars[ARRAY_COUNT(preservedVars)];
    bool32 defeated = 0x12345678;

    FlagClear(flag);
    VarSet(var, 0xA55A);
    memset(gSaveBlock1Ptr->trainerDefeated, 0xA5, sizeof(gSaveBlock1Ptr->trainerDefeated));
    for (u32 i = 0; i < ARRAY_COUNT(preservedFlags); i++)
        FlagClear(preservedFlags[i]);
    for (u32 i = 0; i < ARRAY_COUNT(preservedVars); i++)
    {
        originalVars[i] = VarGet(preservedVars[i].id);
        VarSet(preservedVars[i].id, preservedVars[i].value);
    }
    for (u32 i = 0; i < ARRAY_COUNT(invalid); i++)
    {
        EXPECT(!PersistentId_TestGetTrainerDefeated(&invalid[i], &defeated));
        EXPECT_EQ(defeated, 0x12345678);
        EXPECT(!PersistentId_TestSetTrainerDefeated(&invalid[i]));
        EXPECT(!FlagGet(flag));
        EXPECT_EQ(VarGet(var), 0xA55A);
        for (u32 j = 0; j < sizeof(gSaveBlock1Ptr->trainerDefeated); j++)
            EXPECT_EQ(gSaveBlock1Ptr->trainerDefeated[j], 0xA5);
        for (u32 j = 0; j < ARRAY_COUNT(preservedFlags); j++)
            EXPECT(!FlagGet(preservedFlags[j]));
        for (u32 j = 0; j < ARRAY_COUNT(preservedVars); j++)
            EXPECT_EQ(VarGet(preservedVars[j].id), preservedVars[j].value);
        EXPECT(!PersistentId_TestClearTrainerDefeated(&invalid[i]));
        EXPECT(!FlagGet(flag));
        EXPECT_EQ(VarGet(var), 0xA55A);
        for (u32 j = 0; j < sizeof(gSaveBlock1Ptr->trainerDefeated); j++)
            EXPECT_EQ(gSaveBlock1Ptr->trainerDefeated[j], 0xA5);
        for (u32 j = 0; j < ARRAY_COUNT(preservedFlags); j++)
            EXPECT(!FlagGet(preservedFlags[j]));
        for (u32 j = 0; j < ARRAY_COUNT(preservedVars); j++)
            EXPECT_EQ(VarGet(preservedVars[j].id), preservedVars[j].value);
    }
    EXPECT(!PersistentId_TestGetTrainerDefeated(NULL, &defeated));
    EXPECT(!PersistentId_TestGetTrainerDefeated(&invalid[0], NULL));
    EXPECT(!PersistentId_TestSetTrainerDefeated(NULL));
    EXPECT(!PersistentId_TestClearTrainerDefeated(NULL));
    EXPECT(!PersistentId_GetTrainerDefeated(PERSISTENT_TRAINER_COUNT, &defeated));
    EXPECT_EQ(defeated, 0x12345678);
    EXPECT(!PersistentId_GetTrainerDefeated(0, NULL));
    EXPECT(!PersistentId_SetTrainerDefeated(PERSISTENT_TRAINER_COUNT));
    EXPECT(!PersistentId_ClearTrainerDefeated(PERSISTENT_TRAINER_COUNT));
    for (u32 i = 0; i < ARRAY_COUNT(preservedVars); i++)
    {
        VarSet(preservedVars[i].id, originalVars[i]);
        EXPECT_EQ(VarGet(preservedVars[i].id), originalVars[i]);
    }
}
