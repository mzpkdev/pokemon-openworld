#include "global.h"
#include "persistent_ids.h"
#include "test/test.h"

TEST("Persistent trainer IDs preserve every published defeat flag")
{
    u16 flag;

    for (u16 trainerId = 0; trainerId < PERSISTENT_TRAINER_COUNT; trainerId++)
    {
        EXPECT(PersistentId_GetTrainerDefeatFlag(trainerId, &flag));
        EXPECT_EQ(flag, 0x500 + trainerId);
    }
}

TEST("Persistent trainer IDs fail closed when invalid")
{
    u16 flag = 0x1234;

    EXPECT(!PersistentId_GetTrainerDefeatFlag(PERSISTENT_TRAINER_COUNT, &flag));
    EXPECT_EQ(flag, 0x1234);
    EXPECT(!PersistentId_GetTrainerDefeatFlag(0xFFFF, &flag));
    EXPECT_EQ(flag, 0x1234);
    EXPECT(!PersistentId_GetTrainerDefeatFlag(0, NULL));
}
