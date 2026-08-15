#include "global.h"
#include "constants/opponents.h"
#include "test/test.h"

bool32 TrainerSlide_TestTryGetTableIndex(u32 trainerId, u32 *tableIndex);

TEST("Trainer slide table indexes ordinary trainers directly")
{
    u32 tableIndex = TRAINERS_COUNT;

    EXPECT(TrainerSlide_TestTryGetTableIndex(TRAINER_RED, &tableIndex));
    EXPECT_EQ(tableIndex, TRAINER_RED);
}

TEST("Trainer slide table accommodates newly allocated trainers without slides")
{
    u32 tableIndex = TRAINERS_COUNT;

    EXPECT(TrainerSlide_TestTryGetTableIndex(TRAINER_EXPERT_ROXANNE_JOHTO, &tableIndex));
    EXPECT_EQ(tableIndex, TRAINER_EXPERT_ROXANNE_JOHTO);
}

TEST("Trainer slide table compacts canonical partner IDs after ordinary trainers")
{
    u32 tableIndex = TRAINERS_COUNT;

    EXPECT(TrainerSlide_TestTryGetTableIndex(TRAINER_PARTNER(PARTNER_STEVEN), &tableIndex));
    EXPECT_EQ(tableIndex, TRAINERS_COUNT + PARTNER_STEVEN);
}

TEST("Trainer slide table does not reinterpret historical partner values")
{
    static const u16 historicalStevenIds[] =
    {
        MAX_TRAINERS_COUNT_EMERALD + PARTNER_STEVEN,
        1536 + PARTNER_STEVEN,
    };

    for (u32 i = 0; i < ARRAY_COUNT(historicalStevenIds); i++)
    {
        u32 tableIndex = TRAINERS_COUNT;

        EXPECT(TrainerSlide_TestTryGetTableIndex(historicalStevenIds[i], &tableIndex));
        EXPECT_EQ(tableIndex, historicalStevenIds[i]);
        EXPECT_NE(tableIndex, TRAINERS_COUNT + PARTNER_STEVEN);
    }
}

TEST("Trainer slide table rejects namespace gaps and malformed IDs")
{
    static const u32 invalidIds[] =
    {
        TRAINERS_COUNT,
        MAX_TRAINERS_COUNT - 1,
        TRAINER_PARTNER(PARTNER_NONE),
        TRAINER_PARTNER(PARTNER_COUNT),
        UINT16_MAX,
        UINT16_MAX + 1,
    };

    for (u32 i = 0; i < ARRAY_COUNT(invalidIds); i++)
    {
        u32 tableIndex = 0xFFFFFFFF;

        EXPECT(!TrainerSlide_TestTryGetTableIndex(invalidIds[i], &tableIndex));
        EXPECT_EQ(tableIndex, 0xFFFFFFFF);
    }
    EXPECT(!TrainerSlide_TestTryGetTableIndex(TRAINER_RED, NULL));
}
