#include "global.h"
#include "fieldmap.h"
#include "constants/maps.h"
#include "generated_dungeon.h"
#include "generated_dungeon_persistence.h"
#include "overworld.h"
#include "test/test.h"

static u8 sGenerateCalls;
static const u8 sTestScript[] = {0};

STATIC_ASSERT(sizeof(struct GeneratedDungeonWorkspace) <= sizeof(sBackupMapData), GeneratedDungeonTestWorkspaceFitsBackupMapBuffer);

static struct GeneratedDungeonWorkspace *GetTestWorkspace(void)
{
    return (void *)sBackupMapData;
}

static const u8 sWalkingScript[] = {0};
static const u8 sSurfScript[] = {1, 0};

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

static bool32 TranslateWalkingCell(const struct GeneratedDungeonProvider *provider, u16 cell, u16 *metatile)
{
    (void)provider;
    if (cell > 99)
        return FALSE;
    *metatile = 0x210 + cell;
    return TRUE;
}

static bool32 TranslateSurfCell(const struct GeneratedDungeonProvider *provider, u16 cell, u16 *metatile)
{
    (void)provider;
    if (cell > 99)
        return FALSE;
    *metatile = 0x480 + cell;
    return TRUE;
}

static bool32 CanWalkEastThenSouth(const struct GeneratedDungeonProvider *provider, const struct GeneratedDungeonWorkspace *workspace, struct GeneratedDungeonPoint from, struct GeneratedDungeonPoint to)
{
    u16 fromCell;
    u16 toCell;

    (void)provider;
    if (!GeneratedDungeonWorkspace_GetCell(workspace, from.x, from.y, &fromCell)
     || !GeneratedDungeonWorkspace_GetCell(workspace, to.x, to.y, &toCell)
     || fromCell >= 50 || toCell >= 50)
        return FALSE;
    return (to.x == from.x + 1 && to.y == from.y)
        || (from.x == 2 && to.x == from.x && to.y == from.y + 1);
}

static bool32 CanSurfAcrossShore(const struct GeneratedDungeonProvider *provider, const struct GeneratedDungeonWorkspace *workspace, struct GeneratedDungeonPoint from, struct GeneratedDungeonPoint to)
{
    u16 fromCell;
    u16 toCell;

    (void)provider;
    if (!GeneratedDungeonWorkspace_GetCell(workspace, from.x, from.y, &fromCell)
     || !GeneratedDungeonWorkspace_GetCell(workspace, to.x, to.y, &toCell))
        return FALSE;
    if (!((from.x == to.x && (from.y + 1 == to.y || to.y + 1 == from.y))
       || (from.y == to.y && (from.x + 1 == to.x || to.x + 1 == from.x))))
        return FALSE;
    if (fromCell >= 50 || toCell >= 50)
        return TRUE; // Embark, Surf, and disembark transitions are provider-defined.
    return TRUE;
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

static bool32 GenerateTwoCells(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonRngStreams *rng, u8 attempt, struct GeneratedDungeonWorkspace *workspace)
{
    (void)provider;
    (void)rng;
    (void)attempt;
    return GeneratedDungeonWorkspace_SetDimensions(workspace, 2, 1)
        && GeneratedDungeonWorkspace_SetCell(workspace, 0, 0, 7)
        && GeneratedDungeonWorkspace_SetCell(workspace, 1, 0, 8)
        && SetEndpoints(workspace, 2, 1);
}

static bool32 GenerateWalkingLayout(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonRngStreams *rng, u8 attempt, struct GeneratedDungeonWorkspace *workspace)
{
    struct ObjectEventTemplate object = { .localId = 21, .x = 0, .y = 1, .script = sWalkingScript };

    (void)provider;
    (void)rng;
    (void)attempt;
    return GeneratedDungeonWorkspace_SetDimensions(workspace, 3, 2)
        && GeneratedDungeonWorkspace_SetCell(workspace, 0, 0, 10)
        && GeneratedDungeonWorkspace_SetCell(workspace, 1, 0, 11)
        && GeneratedDungeonWorkspace_SetCell(workspace, 2, 0, 12)
        && GeneratedDungeonWorkspace_SetCell(workspace, 0, 1, 13)
        && GeneratedDungeonWorkspace_SetCell(workspace, 1, 1, 14)
        && GeneratedDungeonWorkspace_SetCell(workspace, 2, 1, 15)
        && GeneratedDungeonWorkspace_SetSpawn(workspace, 0, 0)
        && GeneratedDungeonWorkspace_SetOriginEndpoint(workspace, 2, 0)
        && GeneratedDungeonWorkspace_SetDestinationEndpoint(workspace, 2, 1)
        && GeneratedDungeonWorkspace_SetObjectCount(workspace, 1)
        && GeneratedDungeonWorkspace_SetObject(workspace, 0, &object, FALSE);
}

static bool32 GenerateSurfLayout(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonRngStreams *rng, u8 attempt, struct GeneratedDungeonWorkspace *workspace)
{
    struct ObjectEventTemplate shoreObject = { .localId = 31, .x = 0, .y = 1, .script = sSurfScript };
    struct ObjectEventTemplate reefObject = { .localId = 32, .x = 1, .y = 1, .script = sSurfScript };

    (void)provider;
    (void)rng;
    (void)attempt;
    return GeneratedDungeonWorkspace_SetDimensions(workspace, 3, 2)
        && GeneratedDungeonWorkspace_SetCell(workspace, 0, 0, 30)
        && GeneratedDungeonWorkspace_SetCell(workspace, 1, 0, 50)
        && GeneratedDungeonWorkspace_SetCell(workspace, 2, 0, 50)
        && GeneratedDungeonWorkspace_SetCell(workspace, 0, 1, 31)
        && GeneratedDungeonWorkspace_SetCell(workspace, 1, 1, 51)
        && GeneratedDungeonWorkspace_SetCell(workspace, 2, 1, 60)
        && GeneratedDungeonWorkspace_SetSpawn(workspace, 0, 0)
        && GeneratedDungeonWorkspace_SetOriginEndpoint(workspace, 0, 1)
        && GeneratedDungeonWorkspace_SetDestinationEndpoint(workspace, 2, 1)
        && GeneratedDungeonWorkspace_SetObjectCount(workspace, 2)
        && GeneratedDungeonWorkspace_SetObject(workspace, 0, &shoreObject, FALSE)
        && GeneratedDungeonWorkspace_SetObject(workspace, 1, &reefObject, TRUE);
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

static const struct GeneratedDungeonProvider sProviderProofProviders[] =
{
    {
        .providerId = 117,
        .generationVersion = 3,
        .mapGroup = 11,
        .mapNum = 12,
        .maxWorkspaceCells = 64,
        .maxGeneratedObjects = 2,
        .translateCell = TranslateWalkingCell,
        .canMove = CanWalkEastThenSouth,
        .generate = GenerateWalkingLayout,
        .fallback = FallbackOneCell,
    },
    {
        .providerId = 118,
        .generationVersion = 3,
        .mapGroup = 11,
        .mapNum = 13,
        .maxWorkspaceCells = 64,
        .maxGeneratedObjects = 2,
        .translateCell = TranslateSurfCell,
        .canMove = CanSurfAcrossShore,
        .generate = GenerateSurfLayout,
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
    EXPECT(!GeneratedDungeon_FindProviderByMap(MAP_GROUP(MAP_BATTLE_FRONTIER_BATTLE_PYRAMID_FLOOR), MAP_NUM(MAP_BATTLE_FRONTIER_BATTLE_PYRAMID_FLOOR), &provider));

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

TEST("Generated dungeon active maps require a supported record and use generated object count")
{
    struct GeneratedDungeonSaveRecord *record = (struct GeneratedDungeonSaveRecord *)gSaveBlock1Ptr->generatedDungeon;

    GeneratedDungeonRecordClear(record);
    CpuFill32(0, gSaveBlock1Ptr->objectEventTemplates, sizeof(gSaveBlock1Ptr->objectEventTemplates));
    EXPECT(GeneratedDungeon_TestSetRegistry(sProviders, ARRAY_COUNT(sProviders)));
    EXPECT(!GeneratedDungeon_IsActiveMap(1, 2));

    record->providerId = 17;
    record->generationVersion = 3;
    record->seed = 9;
    record->originFacing = DIR_SOUTH;
    record->destinationFacing = DIR_NORTH;
    GeneratedDungeonRecordFinalize(record);
    EXPECT(GeneratedDungeon_IsActiveMap(1, 2));
    EXPECT(!GeneratedDungeon_IsActiveMap(1, 3));
    gSaveBlock1Ptr->objectEventTemplates[0].localId = 1;
    EXPECT_EQ(GeneratedDungeon_GetActiveObjectEventCount(), 1);

    GeneratedDungeonRecordClear(record);
    CpuFill32(0, gSaveBlock1Ptr->objectEventTemplates, sizeof(gSaveBlock1Ptr->objectEventTemplates));
    GeneratedDungeon_TestResetRegistry();
}

TEST("Generated dungeon begin replaces only valid runs without advancing global RNG")
{
    struct GeneratedDungeonSaveRecord *record = (struct GeneratedDungeonSaveRecord *)gSaveBlock1Ptr->generatedDungeon;
    struct WarpData origin = { .mapGroup = MAP_GROUP(MAP_LITTLEROOT_TOWN), .mapNum = MAP_NUM(MAP_LITTLEROOT_TOWN), .warpId = WARP_ID_NONE, .x = 0, .y = 0 };
    struct WarpData destination = { .mapGroup = MAP_GROUP(MAP_OLDALE_TOWN), .mapNum = MAP_NUM(MAP_OLDALE_TOWN), .warpId = WARP_ID_NONE, .x = 0, .y = 0 };
    rng_value_t rngBefore;

    GeneratedDungeonRecordClear(record);
    EXPECT(GeneratedDungeon_TestSetRegistry(sProviders, ARRAY_COUNT(sProviders)));
    SeedRng(0x5678);
    rngBefore = gRngValue;
    EXPECT(GeneratedDungeon_BeginRun(17, 3, 0x12345678, &origin, DIR_EAST, &destination, DIR_NORTH));
    EXPECT_EQ(memcmp(&rngBefore, &gRngValue, sizeof(rngBefore)), 0);
    EXPECT_EQ(record->seed, 0x12345678);
    EXPECT_EQ(record->origin.x, 0);
    EXPECT_EQ(record->destination.y, 0);
    EXPECT_EQ(GeneratedDungeonRecordClassify(record, TRUE), GENERATED_DUNGEON_RECORD_ACTIVE);
    EXPECT(!GeneratedDungeon_BeginRun(17, 2, 0, &origin, DIR_EAST, &destination, DIR_NORTH));
    EXPECT_EQ(record->seed, 0x12345678);
    EXPECT(GeneratedDungeon_BeginRun(18, 3, 9, &origin, DIR_SOUTH, &destination, DIR_WEST));
    EXPECT_EQ(record->providerId, 18);
    EXPECT_EQ(record->seed, 9);

    GeneratedDungeon_ClearRun();
    GeneratedDungeon_TestResetRegistry();
}

TEST("Generated dungeon departures only clear active generated-map sources")
{
    struct WarpData generated = { .mapGroup = 1, .mapNum = 2, .warpId = WARP_ID_NONE, .x = 0, .y = 0 };
    struct WarpData sameGenerated = { .mapGroup = 1, .mapNum = 2, .warpId = WARP_ID_NONE, .x = 1, .y = 1 };
    struct WarpData elsewhere = { .mapGroup = MAP_GROUP(MAP_LITTLEROOT_TOWN), .mapNum = MAP_NUM(MAP_LITTLEROOT_TOWN), .warpId = WARP_ID_NONE, .x = 0, .y = 0 };
    struct WarpData destination = { .mapGroup = MAP_GROUP(MAP_OLDALE_TOWN), .mapNum = MAP_NUM(MAP_OLDALE_TOWN), .warpId = WARP_ID_NONE, .x = 0, .y = 0 };

    EXPECT(GeneratedDungeon_TestSetRegistry(sProviders, ARRAY_COUNT(sProviders)));
    EXPECT(GeneratedDungeon_BeginRun(17, 3, 1, &elsewhere, DIR_SOUTH, &destination, DIR_NORTH));
    EXPECT(!GeneratedDungeon_ShouldClearForDeparture(&generated, &sameGenerated));
    EXPECT(GeneratedDungeon_ShouldClearForDeparture(&generated, &elsewhere));
    EXPECT(!GeneratedDungeon_ShouldClearForDeparture(&elsewhere, &generated));
    EXPECT(!GeneratedDungeon_ClearForDeparture(&generated, &sameGenerated));
    EXPECT_EQ(GeneratedDungeonRecordClassify((const struct GeneratedDungeonSaveRecord *)gSaveBlock1Ptr->generatedDungeon, TRUE), GENERATED_DUNGEON_RECORD_ACTIVE);
    EXPECT(GeneratedDungeon_ClearForDeparture(&generated, &elsewhere));
    EXPECT_EQ(GeneratedDungeonRecordClassify((const struct GeneratedDungeonSaveRecord *)gSaveBlock1Ptr->generatedDungeon, TRUE), GENERATED_DUNGEON_RECORD_INACTIVE);
    EXPECT(GeneratedDungeon_BeginRun(17, 3, 1, &elsewhere, DIR_SOUTH, &destination, DIR_NORTH));
    EXPECT(GeneratedDungeon_DepartToDestination());
    EXPECT_EQ(GeneratedDungeonRecordClassify((const struct GeneratedDungeonSaveRecord *)gSaveBlock1Ptr->generatedDungeon, TRUE), GENERATED_DUNGEON_RECORD_INACTIVE);

    GeneratedDungeon_TestResetRegistry();
}

TEST("Generated dungeon warp destination preserves signed coordinates and consumes facing once")
{
    struct WarpData warp = { .mapGroup = 6, .mapNum = 7, .warpId = WARP_ID_NONE, .x = 1234, .y = -1235 };
    const struct WarpData *destination;

    SetGeneratedDungeonWarpDestination(&warp, DIR_WEST);
    destination = Overworld_TestGetGeneratedDungeonWarpDestination();
    EXPECT_EQ(destination->mapGroup, warp.mapGroup);
    EXPECT_EQ(destination->mapNum, warp.mapNum);
    EXPECT_EQ(destination->x, 1234);
    EXPECT_EQ(destination->y, -1235);
    EXPECT_EQ(Overworld_TestApplyGeneratedDungeonWarpFacing(DIR_SOUTH), DIR_WEST);
    EXPECT_EQ(Overworld_TestApplyGeneratedDungeonWarpFacing(DIR_NORTH), DIR_NORTH);

    SetGeneratedDungeonWarpDestination(&warp, DIR_EAST);
    SetWarpDestination(1, 2, WARP_ID_NONE, 3, 4);
    EXPECT_EQ(Overworld_TestApplyGeneratedDungeonWarpFacing(DIR_NORTH), DIR_NORTH);
}

TEST("Generated dungeon recovery routes a supported envelope with an unsupported provider to its origin")
{
    struct GeneratedDungeonSaveRecord *record = (struct GeneratedDungeonSaveRecord *)gSaveBlock1Ptr->generatedDungeon;
    struct WarpData origin = { .mapGroup = MAP_GROUP(MAP_LITTLEROOT_TOWN), .mapNum = MAP_NUM(MAP_LITTLEROOT_TOWN), .warpId = WARP_ID_NONE, .x = 0, .y = 0 };
    struct WarpData destination = { .mapGroup = MAP_GROUP(MAP_OLDALE_TOWN), .mapNum = MAP_NUM(MAP_OLDALE_TOWN), .warpId = WARP_ID_NONE, .x = 0, .y = 0 };
    const struct WarpData *warp;

    EXPECT(GeneratedDungeon_TestSetRegistry(sProviders, ARRAY_COUNT(sProviders)));
    EXPECT(GeneratedDungeon_BeginRun(17, 3, 1, &origin, DIR_EAST, &destination, DIR_NORTH));
    record->generationVersion = 4;
    GeneratedDungeonRecordFinalize(record);
    EXPECT_EQ(GeneratedDungeonRecordClassify(record, FALSE), GENERATED_DUNGEON_RECORD_RECOVER_TO_ORIGIN);
    EXPECT(GeneratedDungeon_RecoverUnsupportedRun());
    EXPECT_EQ(GeneratedDungeonRecordClassify(record, TRUE), GENERATED_DUNGEON_RECORD_INACTIVE);
    warp = Overworld_TestGetGeneratedDungeonWarpDestination();
    EXPECT_EQ(warp->x, 0);
    EXPECT_EQ(warp->y, 0);
    EXPECT_EQ(Overworld_TestApplyGeneratedDungeonWarpFacing(DIR_SOUTH), DIR_EAST);

    GeneratedDungeon_TestResetRegistry();
}

TEST("Generated dungeon recovery preserves an unsupported record with an invalid origin")
{
    struct GeneratedDungeonSaveRecord *record = (struct GeneratedDungeonSaveRecord *)gSaveBlock1Ptr->generatedDungeon;
    struct WarpData origin = { .mapGroup = MAP_GROUP(MAP_LITTLEROOT_TOWN), .mapNum = MAP_NUM(MAP_LITTLEROOT_TOWN), .warpId = WARP_ID_NONE, .x = 0, .y = 0 };
    struct WarpData destination = { .mapGroup = MAP_GROUP(MAP_OLDALE_TOWN), .mapNum = MAP_NUM(MAP_OLDALE_TOWN), .warpId = WARP_ID_NONE, .x = 0, .y = 0 };

    EXPECT(GeneratedDungeon_TestSetRegistry(sProviders, ARRAY_COUNT(sProviders)));
    EXPECT(GeneratedDungeon_BeginRun(17, 3, 1, &origin, DIR_EAST, &destination, DIR_NORTH));
    record->generationVersion = 4;
    record->origin.mapGroup = MAP_GROUPS_COUNT;
    GeneratedDungeonRecordFinalize(record);
    EXPECT_EQ(GeneratedDungeonRecordClassify(record, FALSE), GENERATED_DUNGEON_RECORD_RECOVER_TO_ORIGIN);
    EXPECT(!GeneratedDungeon_RecoverUnsupportedRun());
    EXPECT_EQ(GeneratedDungeonRecordClassify(record, FALSE), GENERATED_DUNGEON_RECORD_RECOVER_TO_ORIGIN);

    GeneratedDungeon_ClearRun();
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

TEST("Generated dungeon test providers freeze distinct walking and Surf publications")
{
    struct GeneratedDungeonWorkspace *workspace = GetTestWorkspace();
    static const u16 sExpectedWalkingMap[] = {0x21a, 0x21b, 0x21c, 0x21d, 0x21e, 0x21f};
    static const u16 sExpectedSurfMap[] = {0x49e, 0x4b2, 0x4b2, 0x49f, 0x4b3, 0x4bc};
    struct ObjectEventTemplate templates[2];
    u16 map[6] = {0};
    struct GeneratedDungeonPublication publication =
    {
        .map = map,
        .mapWidth = 3,
        .mapHeight = 2,
        .mapStride = 3,
        .templates = templates,
        .templateCapacity = ARRAY_COUNT(templates),
    };
    u16 i;

    EXPECT(GeneratedDungeon_TestSetRegistry(sProviderProofProviders, ARRAY_COUNT(sProviderProofProviders)));
    EXPECT_EQ(GeneratedDungeon_GenerateAndPublish(&sProviderProofProviders[0], 0x12345678, workspace, &publication), GENERATED_DUNGEON_GENERATION_SUCCEEDED);
    for (i = 0; i < ARRAY_COUNT(map); i++)
        EXPECT_EQ(map[i], sExpectedWalkingMap[i]);
    EXPECT_EQ(templates[0].localId, 21);
    EXPECT(templates[0].script == sWalkingScript);
    EXPECT_EQ(templates[1].localId, 0);

    memset(map, 0xff, sizeof(map));
    memset(templates, 0xff, sizeof(templates));
    EXPECT_EQ(GeneratedDungeon_GenerateAndPublish(&sProviderProofProviders[0], 0x12345678, workspace, &publication), GENERATED_DUNGEON_GENERATION_SUCCEEDED);
    for (i = 0; i < ARRAY_COUNT(map); i++)
        EXPECT_EQ(map[i], sExpectedWalkingMap[i]);
    EXPECT_EQ(templates[0].localId, 21);
    EXPECT(templates[0].script == sWalkingScript);
    EXPECT_EQ(templates[1].localId, 0);

    EXPECT_EQ(GeneratedDungeon_GenerateAndPublish(&sProviderProofProviders[1], 0x12345678, workspace, &publication), GENERATED_DUNGEON_GENERATION_SUCCEEDED);
    for (i = 0; i < ARRAY_COUNT(map); i++)
        EXPECT_EQ(map[i], sExpectedSurfMap[i]);
    EXPECT_EQ(templates[0].localId, 31);
    EXPECT(templates[0].script == sSurfScript);
    EXPECT_EQ(templates[1].localId, 32);
    EXPECT(templates[1].script == sSurfScript);
    GeneratedDungeon_TestResetRegistry();
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

    provider.canMove = CanWalkEastThenSouth;
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

TEST("Generated dungeon walking rejects water while Surf crosses shore transitions")
{
    struct GeneratedDungeonWorkspace *workspace = GetTestWorkspace();
    struct GeneratedDungeonPoint shore = {0, 0};
    struct GeneratedDungeonPoint water = {1, 0};

    GeneratedDungeonWorkspace_Reset(workspace);
    EXPECT(GeneratedDungeonWorkspace_SetDimensions(workspace, 2, 1));
    EXPECT(GeneratedDungeonWorkspace_SetCell(workspace, 0, 0, 10));
    EXPECT(GeneratedDungeonWorkspace_SetCell(workspace, 1, 0, 11));
    EXPECT(sProviderProofProviders[0].canMove(&sProviderProofProviders[0], workspace, shore, water));
    EXPECT(!sProviderProofProviders[0].canMove(&sProviderProofProviders[0], workspace, water, shore));
    EXPECT(GeneratedDungeonWorkspace_SetCell(workspace, 0, 0, 30));
    EXPECT(GeneratedDungeonWorkspace_SetCell(workspace, 1, 0, 50));
    EXPECT(!sProviderProofProviders[0].canMove(&sProviderProofProviders[0], workspace, shore, water));
    EXPECT(!sProviderProofProviders[0].canMove(&sProviderProofProviders[0], workspace, water, shore));
    EXPECT(sProviderProofProviders[1].canMove(&sProviderProofProviders[1], workspace, shore, water));
    EXPECT(sProviderProofProviders[1].canMove(&sProviderProofProviders[1], workspace, water, shore));
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

TEST("Generated dungeon publication preserves semantic cells when its map aliases the workspace")
{
    struct GeneratedDungeonWorkspace *workspace = GetTestWorkspace();
    struct GeneratedDungeonProvider provider = sProviders[0];
    struct GeneratedDungeonPublication publication =
    {
        .map = &workspace->cells[1],
        .mapWidth = 2,
        .mapHeight = 1,
        .mapStride = 2,
        .mapWritesAfterCells = TRUE,
        .templates = gSaveBlock1Ptr->objectEventTemplates,
        .templateCapacity = OBJECT_EVENT_TEMPLATES_COUNT,
    };

    provider.generate = GenerateTwoCells;
    GeneratedDungeonWorkspace_Reset(workspace);
    EXPECT_EQ(GeneratedDungeon_GenerateAndPublish(&provider, 9, workspace, &publication), GENERATED_DUNGEON_GENERATION_SUCCEEDED);
    EXPECT_EQ(publication.map[0], 107);
    EXPECT_EQ(publication.map[1], 108);
}

TEST("Generated dungeon generation retries and uses a validated deterministic fallback")
{
    struct GeneratedDungeonWorkspace *workspace = GetTestWorkspace();
    struct GeneratedDungeonProvider retryProvider = sProviders[1];
    struct GeneratedDungeonProvider invalidFallback = sProviders[1];

    EXPECT_EQ(GeneratedDungeon_Generate(&sProviders[0], 7, workspace), GENERATED_DUNGEON_GENERATION_SUCCEEDED);
    EXPECT_EQ(workspace->cells[0], 7);
    sGenerateCalls = 0;
    retryProvider.generate = GenerateAfterAllAttempts;
    EXPECT_EQ(GeneratedDungeon_Generate(&retryProvider, 7, workspace), GENERATED_DUNGEON_GENERATION_FALLBACK);
    EXPECT_EQ(sGenerateCalls, GENERATED_DUNGEON_MAX_ATTEMPTS);
    EXPECT_EQ(workspace->cells[0], 9);

    invalidFallback.generate = GenerateOversize;
    invalidFallback.fallback = FallbackOversize;
    EXPECT_EQ(GeneratedDungeon_Generate(&invalidFallback, 7, workspace), GENERATED_DUNGEON_GENERATION_FAILED);
    EXPECT_EQ(workspace->width, 0);
}
