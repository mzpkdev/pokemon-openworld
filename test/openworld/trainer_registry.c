#include "global.h"
#include "battle_main.h"
#include "battle_setup.h"
#include "event_data.h"
#include "persistent_ids.h"
#include "strings.h"
#include "trainer_registry.h"
#include "trainer_rematch_registry.h"
#include "constants/characters.h"
#include "constants/opponents.h"
#include "test/test.h"

#define REGISTRY_TEST_TRAINER_COUNT 8

static const struct TrainerMon sRegistryParty[] =
{
    {.species = SPECIES_BULBASAUR, .lvl = 5},
    {.species = SPECIES_CHARMANDER, .lvl = 6},
};

static EWRAM_DATA struct Trainer sRegistryTrainers[DIFFICULTY_COUNT][REGISTRY_TEST_TRAINER_COUNT];

static void InitRegistryTrainers(void)
{
    memset(sRegistryTrainers, 0, sizeof(sRegistryTrainers));

    sRegistryTrainers[DIFFICULTY_NORMAL][1] = (struct Trainer)
    {
        .isRegistered = TRUE,
        .party = sRegistryParty,
        .partySize = 1,
        .encounterMusic = TRAINER_ENCOUNTER_MUSIC_MALE,
    };
    sRegistryTrainers[DIFFICULTY_NORMAL][2] = (struct Trainer)
    {
        .isRegistered = TRUE,
        .party = sRegistryParty,
        .partySize = 1,
    };
    sRegistryTrainers[DIFFICULTY_HARD][2] = (struct Trainer)
    {
        .isRegistered = TRUE,
        .party = sRegistryParty,
        .partySize = 2,
        .encounterMusic = TRAINER_ENCOUNTER_MUSIC_AQUA,
    };
}

TEST("Ordinary trainer registry resolves authored trainers and difficulty fallback")
{
    struct ResolvedOrdinaryTrainer resolved;

    InitRegistryTrainers();
    EXPECT(TrainerRegistry_TestResolve(
        &sRegistryTrainers[0][0],
        REGISTRY_TEST_TRAINER_COUNT,
        1,
        DIFFICULTY_HARD,
        &resolved));
    EXPECT_EQ(resolved.difficulty, DIFFICULTY_NORMAL);
    EXPECT_EQ(resolved.trainer.party, sRegistryParty);
    EXPECT_EQ((u32)resolved.trainer.partySize, 1);

    EXPECT(TrainerRegistry_TestResolve(
        &sRegistryTrainers[0][0],
        REGISTRY_TEST_TRAINER_COUNT,
        2,
        DIFFICULTY_HARD,
        &resolved));
    EXPECT_EQ(resolved.difficulty, DIFFICULTY_HARD);
    EXPECT_EQ((u32)resolved.trainer.partySize, 2);
    EXPECT_EQ((u32)resolved.trainer.encounterMusic, TRAINER_ENCOUNTER_MUSIC_AQUA);
}

TEST("Ordinary trainer registry rejects invalid IDs holes and missing parties")
{
    struct ResolvedOrdinaryTrainer resolved;

    InitRegistryTrainers();
    EXPECT(!TrainerRegistry_TestResolve(&sRegistryTrainers[0][0], REGISTRY_TEST_TRAINER_COUNT, TRAINER_NONE, DIFFICULTY_NORMAL, &resolved));
    EXPECT(!TrainerRegistry_TestResolve(&sRegistryTrainers[0][0], REGISTRY_TEST_TRAINER_COUNT, REGISTRY_TEST_TRAINER_COUNT, DIFFICULTY_NORMAL, &resolved));
    EXPECT(!TrainerRegistry_TestResolve(&sRegistryTrainers[0][0], REGISTRY_TEST_TRAINER_COUNT, 0xFFFF, DIFFICULTY_NORMAL, &resolved));
    EXPECT(!TrainerRegistry_TestResolve(&sRegistryTrainers[0][0], REGISTRY_TEST_TRAINER_COUNT, 3, DIFFICULTY_NORMAL, &resolved));
    sRegistryTrainers[DIFFICULTY_HARD][3] = (struct Trainer)
    {
        .isRegistered = TRUE,
        .party = sRegistryParty,
        .partySize = 1,
    };
    EXPECT(!TrainerRegistry_TestResolve(&sRegistryTrainers[0][0], REGISTRY_TEST_TRAINER_COUNT, 3, DIFFICULTY_HARD, &resolved));
    EXPECT(!TryResolveOrdinaryTrainer(TRAINERS_COUNT, &resolved));
    EXPECT(!TryResolveOrdinaryTrainer(TRAINER_FISHERMAN_SCOTT_JOHTO, &resolved));
}

TEST("Samuel resolves his authored normal party without legacy defeat flag or rematch state")
{
    struct ResolvedOrdinaryTrainer resolved;
    u16 defeatFlag = TRAINER_NONE;

    EXPECT(TryResolveOrdinaryTrainerAtDifficulty(
        TRAINER_YOUNGSTER_SAMUEL_JOHTO,
        DIFFICULTY_HARD,
        &resolved));
    EXPECT_EQ(resolved.difficulty, DIFFICULTY_NORMAL);
    EXPECT_EQ((u32)resolved.trainer.partySize, 3);
    EXPECT_EQ(resolved.trainer.party[0].species, SPECIES_TEDDIURSA);
    EXPECT_EQ((u32)resolved.trainer.party[0].lvl, 12);
    EXPECT_EQ((u32)resolved.trainer.party[0].iv, 0);
    EXPECT_EQ(resolved.trainer.party[1].species, SPECIES_SANDSHREW);
    EXPECT_EQ((u32)resolved.trainer.party[1].lvl, 10);
    EXPECT_EQ((u32)resolved.trainer.party[1].iv, 0);
    EXPECT_EQ(resolved.trainer.party[2].species, SPECIES_SPEAROW);
    EXPECT_EQ((u32)resolved.trainer.party[2].lvl, 12);
    EXPECT_EQ((u32)resolved.trainer.party[2].iv, 0);
    EXPECT(!PersistentId_GetTrainerDefeatFlag(
        TRAINER_YOUNGSTER_SAMUEL_JOHTO,
        &defeatFlag));
    EXPECT_EQ(defeatFlag, TRAINER_NONE);
    EXPECT_EQ(
        TrainerRematch_GetBinding(TRAINER_YOUNGSTER_SAMUEL_JOHTO).kind,
        TRAINER_REMATCH_BINDING_NONE);
}

TEST("Eugene resolves his authored normal party without legacy defeat flag or rematch state")
{
    struct ResolvedOrdinaryTrainer resolved;
    u16 defeatFlag = TRAINER_NONE;

    EXPECT(TryResolveOrdinaryTrainerAtDifficulty(
        TRAINER_SAILOR_EUGENE_JOHTO,
        DIFFICULTY_HARD,
        &resolved));
    EXPECT_EQ(resolved.difficulty, DIFFICULTY_NORMAL);
    EXPECT_EQ((u32)resolved.trainer.partySize, 2);
    EXPECT_EQ(resolved.trainer.party[0].species, SPECIES_POLIWHIRL);
    EXPECT_EQ((u32)resolved.trainer.party[0].lvl, 20);
    EXPECT_EQ((u32)resolved.trainer.party[0].iv, 0);
    EXPECT_EQ(resolved.trainer.party[1].species, SPECIES_TAUROS);
    EXPECT_EQ((u32)resolved.trainer.party[1].lvl, 22);
    EXPECT_EQ((u32)resolved.trainer.party[1].iv, 0);
    EXPECT(!PersistentId_GetTrainerDefeatFlag(
        TRAINER_SAILOR_EUGENE_JOHTO,
        &defeatFlag));
    EXPECT_EQ(defeatFlag, TRAINER_NONE);
    EXPECT_EQ(
        TrainerRematch_GetBinding(TRAINER_SAILOR_EUGENE_JOHTO).kind,
        TRAINER_REMATCH_BINDING_NONE);
}

TEST("Wade resolves his authored normal party without legacy defeat flag or rematch state")
{
    struct ResolvedOrdinaryTrainer resolved;
    u16 defeatFlag = TRAINER_NONE;

    EXPECT(TryResolveOrdinaryTrainerAtDifficulty(
        TRAINER_BUG_CATCHER_WADE_JOHTO,
        DIFFICULTY_HARD,
        &resolved));
    EXPECT_EQ(resolved.difficulty, DIFFICULTY_NORMAL);
    EXPECT_EQ((u32)resolved.trainer.partySize, 2);
    EXPECT_EQ(resolved.trainer.party[0].species, SPECIES_WEEDLE);
    EXPECT_EQ((u32)resolved.trainer.party[0].lvl, 4);
    EXPECT_EQ((u32)resolved.trainer.party[0].iv, 0);
    EXPECT_EQ(resolved.trainer.party[1].species, SPECIES_PINECO);
    EXPECT_EQ((u32)resolved.trainer.party[1].lvl, 5);
    EXPECT_EQ((u32)resolved.trainer.party[1].iv, 0);
    EXPECT(!PersistentId_GetTrainerDefeatFlag(
        TRAINER_BUG_CATCHER_WADE_JOHTO,
        &defeatFlag));
    EXPECT_EQ(defeatFlag, TRAINER_NONE);
    EXPECT_EQ(
        TrainerRematch_GetBinding(TRAINER_BUG_CATCHER_WADE_JOHTO).kind,
        TRAINER_REMATCH_BINDING_NONE);
}

TEST("Route 30 and Route 33 trainers resolve their authored normal parties")
{
    static const struct
    {
        u16 trainerId;
        u16 species1;
        u8 level1;
        u16 species2;
        u8 level2;
    } cases[] =
    {
        { TRAINER_BUG_CATCHER_DON_JOHTO, SPECIES_LEDYBA, 3, SPECIES_SPINARAK, 3 },
        { TRAINER_YOUNGSTER_MIKEY_JOHTO, SPECIES_HOOTHOOT, 2, SPECIES_SENTRET, 4 },
        { TRAINER_HIKER_ANTHONY_JOHTO, SPECIES_GEODUDE, 11, SPECIES_MACHOP, 11 },
    };
    u32 i;

    for (i = 0; i < ARRAY_COUNT(cases); i++)
    {
        struct ResolvedOrdinaryTrainer resolved;
        u16 defeatFlag = TRAINER_NONE;

        EXPECT(TryResolveOrdinaryTrainerAtDifficulty(
            cases[i].trainerId,
            DIFFICULTY_HARD,
            &resolved));
        EXPECT_EQ(resolved.difficulty, DIFFICULTY_NORMAL);
        EXPECT_EQ((u32)resolved.trainer.partySize, 2);
        EXPECT_EQ(resolved.trainer.party[0].species, cases[i].species1);
        EXPECT_EQ((u32)resolved.trainer.party[0].lvl, cases[i].level1);
        EXPECT_EQ((u32)resolved.trainer.party[0].iv, 0);
        EXPECT_EQ(resolved.trainer.party[1].species, cases[i].species2);
        EXPECT_EQ((u32)resolved.trainer.party[1].lvl, cases[i].level2);
        EXPECT_EQ((u32)resolved.trainer.party[1].iv, 0);
        EXPECT(!PersistentId_GetTrainerDefeatFlag(cases[i].trainerId, &defeatFlag));
        EXPECT_EQ(defeatFlag, TRAINER_NONE);
        EXPECT_EQ(
            TrainerRematch_GetBinding(cases[i].trainerId).kind,
            TRAINER_REMATCH_BINDING_NONE);
    }
}

TEST("Bulk fixed Johto trainers resolve registered normal parties")
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
        struct ResolvedOrdinaryTrainer resolved;

        EXPECT(TryResolveOrdinaryTrainerAtDifficulty(
            trainerIds[i],
            DIFFICULTY_HARD,
            &resolved));
        EXPECT_EQ(resolved.difficulty, DIFFICULTY_NORMAL);
        EXPECT(resolved.trainer.party != NULL);
        EXPECT(resolved.trainer.partySize > 0);
        EXPECT_EQ(
            TrainerRematch_GetBinding(trainerIds[i]).kind,
            TRAINER_REMATCH_BINDING_NONE);
    }
}

TEST("Ordinary trainer registry rejects invalid and cyclic party overrides")
{
    struct ResolvedOrdinaryTrainer resolved;

    InitRegistryTrainers();
    sRegistryTrainers[DIFFICULTY_NORMAL][3].isRegistered = TRUE;
    sRegistryTrainers[DIFFICULTY_NORMAL][3].overrideTrainer = REGISTRY_TEST_TRAINER_COUNT;
    EXPECT(!TrainerRegistry_TestResolve(&sRegistryTrainers[0][0], REGISTRY_TEST_TRAINER_COUNT, 3, DIFFICULTY_NORMAL, &resolved));

    sRegistryTrainers[DIFFICULTY_NORMAL][4].isRegistered = TRUE;
    sRegistryTrainers[DIFFICULTY_NORMAL][4].overrideTrainer = 5;
    sRegistryTrainers[DIFFICULTY_NORMAL][5].isRegistered = TRUE;
    sRegistryTrainers[DIFFICULTY_NORMAL][5].overrideTrainer = 4;
    EXPECT(!TrainerRegistry_TestResolve(&sRegistryTrainers[0][0], REGISTRY_TEST_TRAINER_COUNT, 4, DIFFICULTY_NORMAL, &resolved));
}

TEST("Ordinary trainer registry resolves override parties without replacing topology metadata")
{
    struct ResolvedOrdinaryTrainer resolved;

    InitRegistryTrainers();
    sRegistryTrainers[DIFFICULTY_NORMAL][6] = (struct Trainer)
    {
        .isRegistered = TRUE,
        .multiTeamSize = MULTI_TEAM_SIZE_HALF,
        .overrideTrainer = 7,
    };
    sRegistryTrainers[DIFFICULTY_NORMAL][7] = (struct Trainer)
    {
        .isRegistered = TRUE,
        .party = sRegistryParty,
        .partySize = 2,
        .poolSize = 2,
        .multiTeamSize = MULTI_TEAM_SIZE_FULL,
    };

    EXPECT(TrainerRegistry_TestResolve(&sRegistryTrainers[0][0], REGISTRY_TEST_TRAINER_COUNT, 6, DIFFICULTY_NORMAL, &resolved));
    EXPECT_EQ(resolved.trainer.party, sRegistryParty);
    EXPECT_EQ((u32)resolved.trainer.partySize, 2);
    EXPECT_EQ(resolved.trainer.poolSize, 2);
    EXPECT_EQ((u32)resolved.trainer.multiTeamSize, MULTI_TEAM_SIZE_HALF);

    sRegistryTrainers[DIFFICULTY_NORMAL][7].partySize = PARTY_SIZE + 1;
    EXPECT(!TrainerRegistry_TestResolve(&sRegistryTrainers[0][0], REGISTRY_TEST_TRAINER_COUNT, 6, DIFFICULTY_NORMAL, &resolved));
}

TEST("Ordinary trainer registry failures do not mutate inputs or output")
{
    struct Trainer before[DIFFICULTY_COUNT][REGISTRY_TEST_TRAINER_COUNT];
    struct ResolvedOrdinaryTrainer resolved;
    struct ResolvedOrdinaryTrainer expected;

    InitRegistryTrainers();
    memcpy(before, sRegistryTrainers, sizeof(before));
    memset(&resolved, 0xA5, sizeof(resolved));
    expected = resolved;

    EXPECT(!TrainerRegistry_TestResolve(&sRegistryTrainers[0][0], REGISTRY_TEST_TRAINER_COUNT, TRAINER_NONE, DIFFICULTY_NORMAL, &resolved));
    EXPECT_EQ(memcmp(&resolved, &expected, sizeof(resolved)), 0);
    EXPECT_EQ(memcmp(sRegistryTrainers, before, sizeof(before)), 0);
}

TEST("Trainer string metadata is safely empty for invalid ordinary IDs")
{
    static const u16 invalidTrainerIds[] =
    {
        TRAINER_NONE,
        TRAINERS_COUNT,
        0xFFFF,
    };

    for (u32 i = 0; i < ARRAY_COUNT(invalidTrainerIds); i++)
    {
        const u8 *className = GetTrainerClassNameFromId(invalidTrainerIds[i]);
        const u8 *trainerName = GetTrainerNameFromId(invalidTrainerIds[i]);

        EXPECT_EQ(className, gText_EmptyString2);
        EXPECT_EQ(trainerName, gText_EmptyString2);
        EXPECT_EQ(className[0], EOS);
        EXPECT_EQ(trainerName[0], EOS);
    }
}

TEST("Ordinary trainer battle namespace excludes facility-owned trainer IDs")
{
    static const u32 excludedNamespaces[] =
    {
        BATTLE_TYPE_LINK,
        BATTLE_TYPE_FRONTIER,
        BATTLE_TYPE_TRAINER_HILL,
        BATTLE_TYPE_SECRET_BASE,
        BATTLE_TYPE_EREADER_TRAINER,
    };

    EXPECT(IsOrdinaryTrainerBattleNamespace(BATTLE_TYPE_TRAINER));
    EXPECT(!IsOrdinaryTrainerBattleNamespace(0));
    for (u32 i = 0; i < ARRAY_COUNT(excludedNamespaces); i++)
        EXPECT(!IsOrdinaryTrainerBattleNamespace(BATTLE_TYPE_TRAINER | excludedNamespaces[i]));
}

TEST("Partner trainer resolution rejects invalid current difficulty before table access")
{
    u16 previousDifficulty = VarGet(B_VAR_DIFFICULTY);
    u16 partnerId = TRAINER_PARTNER(PARTNER_STEVEN);

    VarSet(B_VAR_DIFFICULTY, DIFFICULTY_COUNT);
    EXPECT_EQ(GetPartnerTrainerStructFromId(partnerId), NULL);
    EXPECT_EQ(GetBattlePartnerDifficultyLevel(partnerId), DIFFICULTY_NORMAL);
    VarSet(B_VAR_DIFFICULTY, previousDifficulty);
}

TEST("AI versus AI player party resolves an ordinary trainer through the registry")
{
    gSpecialVar_0x8004 = 1;
    gPartnerTrainerId = TRAINER_NONE;
    ZeroPlayerPartyMons();

    CreateTrainerPartyForPlayer();

    EXPECT_EQ(gPartnerTrainerId, 1);
    EXPECT_EQ(GetMonData(&gParties[B_TRAINER_PLAYER][0], MON_DATA_SPECIES), SPECIES_CHARMANDER);
    EXPECT_EQ(GetMonData(&gParties[B_TRAINER_PLAYER][0], MON_DATA_LEVEL), 5);
}

TEST("AI versus AI player party rejects invalid trainers without mutation")
{
    struct Pokemon before[PARTY_SIZE];

    memset(gParties[B_TRAINER_PLAYER], 0xA5, sizeof(gParties[B_TRAINER_PLAYER]));
    memcpy(before, gParties[B_TRAINER_PLAYER], sizeof(before));
    gPartnerTrainerId = 0x1234;
    gSpecialVar_0x8004 = TRAINERS_COUNT;

    CreateTrainerPartyForPlayer();

    EXPECT_EQ(gPartnerTrainerId, 0x1234);
    EXPECT_EQ(memcmp(gParties[B_TRAINER_PLAYER], before, sizeof(before)), 0);
}
