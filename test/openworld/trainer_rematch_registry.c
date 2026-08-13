#include "global.h"
#include "trainer_rematch_registry.h"
#include "constants/opponents.h"
#include "test/test.h"

TEST("FRLG rematch registry resolves Ben stages and skips")
{
    struct TrainerRematchBinding binding = TrainerRematch_GetBinding(TRAINER_FRLG_YOUNGSTER_BEN);
    u16 trainerId = 0xA5A5;

    EXPECT_EQ(binding.kind, TRAINER_REMATCH_BINDING_VS_SEEKER);
    EXPECT_EQ(binding.index, 0);
    EXPECT(TrainerRematch_TryResolveStage(TRAINER_FRLG_YOUNGSTER_BEN, 0, &trainerId));
    EXPECT_EQ(trainerId, TRAINER_FRLG_YOUNGSTER_BEN);
    EXPECT(TrainerRematch_TryResolveStage(TRAINER_FRLG_YOUNGSTER_BEN, 1, &trainerId));
    EXPECT_EQ(trainerId, TRAINER_FRLG_YOUNGSTER_BEN_2);
    EXPECT(TrainerRematch_TryResolveStage(TRAINER_FRLG_YOUNGSTER_BEN, 2, &trainerId));
    EXPECT_EQ(trainerId, TRAINER_FRLG_YOUNGSTER_BEN_2);
    EXPECT(TrainerRematch_TryResolveStage(TRAINER_FRLG_YOUNGSTER_BEN, 3, &trainerId));
    EXPECT_EQ(trainerId, TRAINER_FRLG_YOUNGSTER_BEN_3);
    EXPECT(TrainerRematch_TryResolveStage(TRAINER_FRLG_YOUNGSTER_BEN, 4, &trainerId));
    EXPECT_EQ(trainerId, TRAINER_FRLG_YOUNGSTER_BEN_4);

    trainerId = 0xA5A5;
    EXPECT(!TrainerRematch_TryResolveStage(TRAINER_FRLG_YOUNGSTER_BEN, 5, &trainerId));
    EXPECT_EQ(trainerId, 0xA5A5);
}

TEST("FRLG rematch registry resolves Calvin self-rematch and zero tail")
{
    struct TrainerRematchBinding binding = TrainerRematch_GetBinding(TRAINER_FRLG_YOUNGSTER_CALVIN);
    u16 trainerId = 0xA5A5;

    EXPECT_EQ(binding.kind, TRAINER_REMATCH_BINDING_VS_SEEKER);
    EXPECT(TrainerRematch_TryResolveStage(TRAINER_FRLG_YOUNGSTER_CALVIN, 0, &trainerId));
    EXPECT_EQ(trainerId, TRAINER_FRLG_YOUNGSTER_CALVIN);
    EXPECT(TrainerRematch_TryResolveStage(TRAINER_FRLG_YOUNGSTER_CALVIN, 1, &trainerId));
    EXPECT_EQ(trainerId, TRAINER_FRLG_YOUNGSTER_CALVIN);

    trainerId = 0xA5A5;
    EXPECT(!TrainerRematch_TryResolveStage(TRAINER_FRLG_YOUNGSTER_CALVIN, 2, &trainerId));
    EXPECT_EQ(trainerId, 0xA5A5);
}

TEST("Trainer rematch registry distinguishes none invalid and Match Call")
{
    u16 trainerId = 0xA5A5;

    EXPECT_EQ(TrainerRematch_GetBinding(TRAINER_FRLG_RUIN_MANIAC_LAWSON).kind, TRAINER_REMATCH_BINDING_NONE);
    EXPECT_EQ(TrainerRematch_GetBinding(TRAINER_YOUNGSTER_SAMUEL_JOHTO).kind, TRAINER_REMATCH_BINDING_NONE);
    EXPECT_EQ(TrainerRematch_GetBinding(TRAINER_SAILOR_EUGENE_JOHTO).kind, TRAINER_REMATCH_BINDING_NONE);
    EXPECT_EQ(TrainerRematch_GetBinding(TRAINER_FRLG_RIVAL_OAKS_LAB_SQUIRTLE).kind, TRAINER_REMATCH_BINDING_INVALID);
    EXPECT_EQ(TrainerRematch_GetBinding(TRAINER_ROSE_1).kind, TRAINER_REMATCH_BINDING_MATCH_CALL);
    EXPECT_EQ(TrainerRematch_GetBinding(TRAINER_NONE).kind, TRAINER_REMATCH_BINDING_INVALID);
    EXPECT_EQ(TrainerRematch_GetBinding(TRAINERS_COUNT).kind, TRAINER_REMATCH_BINDING_INVALID);

    EXPECT(!TrainerRematch_TryResolveStage(TRAINER_FRLG_RUIN_MANIAC_LAWSON, 0, &trainerId));
    EXPECT(!TrainerRematch_TryResolveStage(TRAINER_YOUNGSTER_SAMUEL_JOHTO, 0, &trainerId));
    EXPECT(!TrainerRematch_TryResolveStage(TRAINER_SAILOR_EUGENE_JOHTO, 0, &trainerId));
    EXPECT(!TrainerRematch_TryResolveStage(TRAINER_FRLG_RIVAL_OAKS_LAB_SQUIRTLE, 0, &trainerId));
    EXPECT(!TrainerRematch_TryResolveStage(TRAINER_FRLG_YOUNGSTER_BEN, TRAINER_REMATCH_STAGE_COUNT, &trainerId));
    EXPECT(!TrainerRematch_TryResolveStage(TRAINER_FRLG_YOUNGSTER_BEN, 0, NULL));
    EXPECT_EQ(trainerId, 0xA5A5);
}
