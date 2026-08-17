#include "global.h"
#include "fieldmap.h"
#include "generated_dungeon.h"
#include "test/test.h"

static u8 sGenerateCalls;
static const u8 sTestScript[] = {0};

STATIC_ASSERT(sizeof(struct GeneratedDungeonWorkspace) <= sizeof(sBackupMapData), GeneratedDungeonTestWorkspaceFitsBackupMapBuffer);

static struct GeneratedDungeonWorkspace *GetTestWorkspace(void)
{
    return (void *)sBackupMapData;
}

static bool32 TranslateTestCell(const struct GeneratedDungeonProvider *provider, u16 cell, u16 *metatile)
{
    (void)provider;
    if (cell > 99)
        return FALSE;
    *metatile = cell + 100;
    return TRUE;
}

static bool32 CanWalkEverywhere(const struct GeneratedDungeonProvider *provider, const struct GeneratedDungeonWorkspace *workspace, struct GeneratedDungeonPoint from, struct GeneratedDungeonPoint to)
{
    (void)provider;
    (void)workspace;
    (void)from;
    (void)to;
    return TRUE;
}

static bool32 CanMoveEastOnly(const struct GeneratedDungeonProvider *provider, const struct GeneratedDungeonWorkspace *workspace, struct GeneratedDungeonPoint from, struct GeneratedDungeonPoint to)
{
    (void)provider;
    (void)workspace;
    return to.x == from.x + 1 && to.y == from.y;
}

static bool32 SetEndpoints(struct GeneratedDungeonWorkspace *workspace, u16 width, u16 height)
{
    return GeneratedDungeonWorkspace_SetSpawn(workspace, 0, 0)
        && GeneratedDungeonWorkspace_SetOriginEndpoint(workspace, width - 1, 0)
        && GeneratedDungeonWorkspace_SetDestinationEndpoint(workspace, width - 1, height - 1);
}

static bool32 GenerateOneCell(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonRngStreams *rng, u8 attempt, struct GeneratedDungeonWorkspace *workspace)
{
    (void)provider;
    (void)rng;
    (void)attempt;
    return GeneratedDungeonWorkspace_SetDimensions(workspace, 1, 1)
        && GeneratedDungeonWorkspace_SetCell(workspace, 0, 0, 7)
        && SetEndpoints(workspace, 1, 1);
}

static bool32 GenerateAfterAllAttempts(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonRngStreams *rng, u8 attempt, struct GeneratedDungeonWorkspace *workspace)
{
    (void)provider;
    (void)rng;
    (void)attempt;
    (void)workspace;
    sGenerateCalls++;
    return FALSE;
}

static bool32 GenerateOversize(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonRngStreams *rng, u8 attempt, struct GeneratedDungeonWorkspace *workspace)
{
    (void)provider;
    (void)rng;
    (void)attempt;
    return GeneratedDungeonWorkspace_SetDimensions(workspace, 65, 64);
}

static bool32 FallbackOneCell(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonWorkspace *workspace)
{
    (void)provider;
    return GeneratedDungeonWorkspace_SetDimensions(workspace, 1, 1)
        && GeneratedDungeonWorkspace_SetCell(workspace, 0, 0, 9)
        && SetEndpoints(workspace, 1, 1);
}

static bool32 FallbackOversize(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonWorkspace *workspace)
{
    (void)provider;
    return GeneratedDungeonWorkspace_SetDimensions(workspace, 65, 64);
}

static const struct GeneratedDungeonProvider sProviders[] =
{
    {
        .providerId = 17,
        .generationVersion = 3,
        .mapGroup = 1,
        .mapNum = 2,
        .maxWorkspaceCells = 64,
        .maxGeneratedObjects = 2,
        .translateCell = TranslateTestCell,
        .canMove = CanWalkEverywhere,
        .generate = GenerateOneCell,
        .fallback = FallbackOneCell,
    },
    {
        .providerId = 18,
        .generationVersion = 3,
        .mapGroup = 1,
        .mapNum = 3,
        .maxWorkspaceCells = 64,
        .maxGeneratedObjects = 2,
        .translateCell = TranslateTestCell,
        .canMove = CanWalkEverywhere,
        .generate = GenerateAfterAllAttempts,
        .fallback = FallbackOneCell,
    },
};

TEST("Generated dungeon registry uses stable identities and rejects malformed providers")
{
    struct GeneratedDungeonProvider invalid = sProviders[0];
    struct GeneratedDungeonProvider duplicate[2] = {sProviders[0], sProviders[1]};
    const struct GeneratedDungeonProvider *provider = NULL;

    EXPECT(GeneratedDungeon_ValidateRegistry(sProviders, ARRAY_COUNT(sProviders)));
    EXPECT(GeneratedDungeon_TestSetRegistry(sProviders, ARRAY_COUNT(sProviders)));
    EXPECT(GeneratedDungeon_FindProviderByMap(1, 2, &provider));
    EXPECT_EQ(provider->providerId, 17);
    EXPECT(GeneratedDungeon_FindProviderById(18, 3, &provider));
    EXPECT_EQ(provider->mapNum, 3);
    EXPECT(!GeneratedDungeon_FindProviderById(18, 2, &provider));
    EXPECT(!GeneratedDungeon_FindProviderByMap(1, 4, &provider));

    duplicate[1].providerId = duplicate[0].providerId;
    EXPECT(!GeneratedDungeon_ValidateRegistry(duplicate, ARRAY_COUNT(duplicate)));
    invalid = sProviders[0];
    invalid.generate = NULL;
    EXPECT(!GeneratedDungeon_ValidateRegistry(&invalid, 1));
    invalid = sProviders[0];
    invalid.maxWorkspaceCells = GENERATED_DUNGEON_MAX_CELLS + 1;
    EXPECT(!GeneratedDungeon_ValidateRegistry(&invalid, 1));

    GeneratedDungeon_TestResetRegistry();
}

TEST("Generated dungeon named RNG streams are deterministic and isolated")
{
    rng_value_t topology = GeneratedDungeon_DeriveStream(17, 3, 0x12345678, GENERATED_DUNGEON_RNG_TOPOLOGY, 0);
    rng_value_t endpoints = GeneratedDungeon_DeriveStream(17, 3, 0x12345678, GENERATED_DUNGEON_RNG_ENDPOINTS, 0);
    rng_value_t expectedEndpoints = GeneratedDungeon_DeriveStream(17, 3, 0x12345678, GENERATED_DUNGEON_RNG_ENDPOINTS, 0);
    rng_value_t topologyAgain = GeneratedDungeon_DeriveStream(17, 3, 0x12345678, GENERATED_DUNGEON_RNG_TOPOLOGY, 0);
    rng_value_t expectedTopology = GeneratedDungeon_DeriveStream(17, 3, 0x12345678, GENERATED_DUNGEON_RNG_TOPOLOGY, 0);
    u32 expectedEndpoint = LocalRandom32(&expectedEndpoints);

    LocalRandom32(&topology);
    LocalRandom32(&topology);
    LocalRandom32(&topology);
    EXPECT_EQ(LocalRandom32(&topologyAgain), LocalRandom32(&expectedTopology));
    EXPECT_EQ(LocalRandom32(&endpoints), expectedEndpoint);
    EXPECT_NE(GeneratedDungeon_DeriveStream(17, 3, 0x12345678, GENERATED_DUNGEON_RNG_TOPOLOGY, 0).c, GeneratedDungeon_DeriveStream(17, 3, 0x12345678, GENERATED_DUNGEON_RNG_ENDPOINTS, 0).c);
}

TEST("Generated dungeon workspace and progress APIs are bounded")
{
    struct GeneratedDungeonWorkspace *workspace = GetTestWorkspace();
    u16 cell = 0;
    u64 progress = 0;
    bool32 set = FALSE;

    GeneratedDungeonWorkspace_Reset(workspace);
    EXPECT(GeneratedDungeonWorkspace_SetDimensions(workspace, 64, 64));
    EXPECT(!GeneratedDungeonWorkspace_SetDimensions(workspace, 65, 64));
    EXPECT(GeneratedDungeonWorkspace_SetCell(workspace, 63, 63, 99));
    EXPECT(GeneratedDungeonWorkspace_GetCell(workspace, 63, 63, &cell));
    EXPECT_EQ(cell, 99);
    EXPECT(!GeneratedDungeonWorkspace_SetCell(workspace, 64, 0, 0));
    EXPECT(!GeneratedDungeonWorkspace_SetObjectCount(workspace, GENERATED_DUNGEON_MAX_OBJECTS + 1));

    EXPECT(GeneratedDungeonProgress_TrySet(&progress, 63));
    EXPECT(GeneratedDungeonProgress_TryGet(progress, 63, &set));
    EXPECT(set);
    EXPECT(!GeneratedDungeonProgress_TrySet(&progress, 64));
    EXPECT(GeneratedDungeonProgress_TryClear(&progress, 63));
    EXPECT_EQ(progress, 0);
}

TEST("Generated dungeon reachability uses provider-directed movement and blocking objects")
{
    struct GeneratedDungeonWorkspace *workspace = GetTestWorkspace();
    struct GeneratedDungeonProvider provider = sProviders[0];
    struct ObjectEventTemplate blocking = { .localId = 1, .x = 1, .y = 0, .script = sTestScript };

    provider.canMove = CanMoveEastOnly;
    GeneratedDungeonWorkspace_Reset(workspace);
    EXPECT(GeneratedDungeonWorkspace_SetDimensions(workspace, 3, 1));
    EXPECT(SetEndpoints(workspace, 3, 1));
    EXPECT(GeneratedDungeonWorkspace_SetObjectCount(workspace, 0));
    EXPECT(GeneratedDungeonWorkspace_HasReachableEndpoints(&provider, workspace));

    EXPECT(GeneratedDungeonWorkspace_SetObjectCount(workspace, 1));
    EXPECT(GeneratedDungeonWorkspace_SetObject(workspace, 0, &blocking, TRUE));
    EXPECT(!GeneratedDungeonWorkspace_HasReachableEndpoints(&provider, workspace));

    GeneratedDungeonWorkspace_Reset(workspace);
    EXPECT(GeneratedDungeonWorkspace_SetDimensions(workspace, 3, 1));
    EXPECT(GeneratedDungeonWorkspace_SetSpawn(workspace, 2, 0));
    EXPECT(GeneratedDungeonWorkspace_SetOriginEndpoint(workspace, 0, 0));
    EXPECT(GeneratedDungeonWorkspace_SetDestinationEndpoint(workspace, 0, 0));
    EXPECT(!GeneratedDungeonWorkspace_HasReachableEndpoints(&provider, workspace));
}

TEST("Generated dungeon publication is transactional after translation and template validation")
{
    struct GeneratedDungeonWorkspace *workspace = GetTestWorkspace();
    struct ObjectEventTemplate templates[2] = {{ .localId = 77 }};
    u16 map[2] = {0xaaaa, 0xbbbb};
    struct GeneratedDungeonPublication publication =
    {
        .map = map,
        .mapWidth = 1,
        .mapHeight = 1,
        .mapStride = 1,
        .templates = templates,
        .templateCapacity = ARRAY_COUNT(templates),
    };
    struct GeneratedDungeonProvider invalid = sProviders[0];

    EXPECT_EQ(GeneratedDungeon_GenerateAndPublish(&sProviders[0], 7, workspace, &publication), GENERATED_DUNGEON_GENERATION_SUCCEEDED);
    EXPECT_EQ(map[0], 107);
    EXPECT_EQ(templates[0].localId, 0);

    map[0] = 0xaaaa;
    templates[0].localId = 77;
    invalid.translateCell = NULL;
    EXPECT_EQ(GeneratedDungeon_GenerateAndPublish(&invalid, 7, workspace, &publication), GENERATED_DUNGEON_GENERATION_FAILED);
    EXPECT_EQ(map[0], 0xaaaa);
    EXPECT_EQ(templates[0].localId, 77);

    publication.mapWidth = 2;
    EXPECT_EQ(GeneratedDungeon_GenerateAndPublish(&sProviders[0], 7, workspace, &publication), GENERATED_DUNGEON_GENERATION_FAILED);
    EXPECT_EQ(map[0], 0xaaaa);
}

TEST("Generated dungeon generation retries and uses a validated deterministic fallback")
{
    struct GeneratedDungeonWorkspace *workspace = GetTestWorkspace();
    struct GeneratedDungeonProvider invalidFallback = sProviders[1];

    EXPECT_EQ(GeneratedDungeon_Generate(&sProviders[0], 7, workspace), GENERATED_DUNGEON_GENERATION_SUCCEEDED);
    EXPECT_EQ(workspace->cells[0], 7);
    sGenerateCalls = 0;
    EXPECT_EQ(GeneratedDungeon_Generate(&sProviders[1], 7, workspace), GENERATED_DUNGEON_GENERATION_FALLBACK);
    EXPECT_EQ(sGenerateCalls, GENERATED_DUNGEON_MAX_ATTEMPTS);
    EXPECT_EQ(workspace->cells[0], 9);

    invalidFallback.generate = GenerateOversize;
    invalidFallback.fallback = FallbackOversize;
    EXPECT_EQ(GeneratedDungeon_Generate(&invalidFallback, 7, workspace), GENERATED_DUNGEON_GENERATION_FAILED);
    EXPECT_EQ(workspace->width, 0);
}
