#include "global.h"
#include "data.h"
#include "string_util.h"
#include "trainer.h"
#include "test/test.h"

struct ExpectedJohtoTrainerClass
{
    u8 id;
    const u8 *name;
    u8 money;
};

TEST("Johto trainer classes append without renumbering published classes")
{
    static const struct ExpectedJohtoTrainerClass sExpected[] =
    {
        {JOHTO_TRAINER_CLASS_BURGLAR, COMPOUND_STRING("BURGLAR"), 5},
        {JOHTO_TRAINER_CLASS_FIREBREATHER, COMPOUND_STRING("FIREBREATHER"), 5},
        {JOHTO_TRAINER_CLASS_JUGGLER, COMPOUND_STRING("JUGGLER"), 5},
        {JOHTO_TRAINER_CLASS_PSYCHIC_M, COMPOUND_STRING("PSYCHIC"), 5},
        {JOHTO_TRAINER_CLASS_SAGE, COMPOUND_STRING("SAGE"), 5},
        {JOHTO_TRAINER_CLASS_SUPER_NERD, COMPOUND_STRING("SUPER NERD"), 8},
    };

    EXPECT_EQ(TRAINER_CLASS_PAINTER_FRLG, 115);
    EXPECT_EQ(TRAINER_CLASS_COUNT, 116);
    EXPECT_EQ(JOHTO_TRAINER_CLASS_BURGLAR, 116);
    EXPECT_EQ(JOHTO_TRAINER_CLASS_FIREBREATHER, 117);
    EXPECT_EQ(JOHTO_TRAINER_CLASS_JUGGLER, 118);
    EXPECT_EQ(JOHTO_TRAINER_CLASS_PSYCHIC_M, 119);
    EXPECT_EQ(JOHTO_TRAINER_CLASS_SAGE, 120);
    EXPECT_EQ(JOHTO_TRAINER_CLASS_SUPER_NERD, 121);
    EXPECT_EQ(JOHTO_TRAINER_CLASS_COUNT, 122);

    for (u32 i = 0; i < ARRAY_COUNT(sExpected); i++)
    {
        EXPECT_EQ(StringCompare(gTrainerClasses[sExpected[i].id].name, sExpected[i].name), 0);
        EXPECT_EQ(gTrainerClasses[sExpected[i].id].money, sExpected[i].money);
    }
}

TEST("Johto trainer front pictures append with complete asset table coverage")
{
    static const enum TrainerPicID sPics[] =
    {
        JOHTO_TRAINER_PIC_FIREBREATHER,
        JOHTO_TRAINER_PIC_PSYCHIC_M,
        JOHTO_TRAINER_PIC_SAGE,
        JOHTO_TRAINER_PIC_SUPER_NERD,
    };

    EXPECT_EQ(TRAINER_PIC_PAINTER_FRLG, 157);
    EXPECT_EQ(TRAINER_PIC_COUNT, 158);
    EXPECT_EQ(JOHTO_TRAINER_PIC_FIREBREATHER, 158);
    EXPECT_EQ(JOHTO_TRAINER_PIC_PSYCHIC_M, 159);
    EXPECT_EQ(JOHTO_TRAINER_PIC_SAGE, 160);
    EXPECT_EQ(JOHTO_TRAINER_PIC_SUPER_NERD, 161);
    EXPECT_EQ(JOHTO_TRAINER_PIC_COUNT, 162);

    EXPECT_EQ(GetTrainerPicTag(JOHTO_TRAINER_PIC_FIREBREATHER, TRUE), 158);
    EXPECT_EQ(GetTrainerPicTag(TRAINER_PIC_BRENDAN, FALSE), 163);

    for (u32 i = 0; i < ARRAY_COUNT(sPics); i++)
    {
        EXPECT(gTrainerPicInfo[sPics[i]].frontPic != NULL);
        EXPECT(gTrainerPicInfo[sPics[i]].frontPic->imageData != NULL);
        EXPECT(gTrainerPicInfo[sPics[i]].frontPic->paletteData != NULL);
    }
}
