#include "global.h"
#include "fieldmap.h"
#include "generated_dungeon.h"
#include "generated_dungeon_persistence.h"
#include "generated_ocean.h"
#include "test/test.h"
#include "constants/event_objects.h"
#include "constants/maps.h"
#include "constants/metatile_labels.h"
#include "constants/trainer_types.h"

STATIC_ASSERT(sizeof(struct GeneratedDungeonWorkspace) <= sizeof(sBackupMapData), GeneratedOceanTestWorkspaceFitsBackupMapBuffer);

static struct GeneratedDungeonWorkspace *GetTestWorkspace(void)
{
    return (void *)sBackupMapData;
}

static bool32 AlwaysFailGeneration(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonRngStreams *rng, u8 attempt, struct GeneratedDungeonWorkspace *workspace)
{
    (void)provider;
    (void)rng;
    (void)attempt;
    (void)workspace;
    return FALSE;
}

static u16 CountImpassableCells(const struct GeneratedDungeonProvider *provider, const struct GeneratedDungeonWorkspace *workspace)
{
    u16 impassableCount = 0;
    u16 i;

    for (i = 0; i < workspace->width * workspace->height; i++)
    {
        u16 metatile;

        if (provider->translateCell(provider, workspace->cells[i], &metatile)
         && (metatile & MAPGRID_IMPASSABLE) != 0)
            impassableCount++;
    }
    return impassableCount;
}

TEST("Generated ocean registers its fixed shell and only emits swimmers")
{
    const struct GeneratedDungeonProvider *provider = NULL;
    struct GeneratedDungeonWorkspace *workspace = GetTestWorkspace();
    struct GeneratedDungeonPoint blocked = {0};
    struct GeneratedDungeonPoint adjacent = {0};
    u16 metatile;
    u8 i;
    bool32 foundBlocked = FALSE;

    EXPECT(GeneratedOcean_Init());
    EXPECT(GeneratedDungeon_FindProviderById(GENERATED_OCEAN_PROVIDER_ID, GENERATED_OCEAN_GENERATION_VERSION, &provider));
    EXPECT_EQ(provider->mapGroup, MAP_GROUP(MAP_AQUA_HIDEOUT_UNUSED_RUBY_MAP2));
    EXPECT_EQ(provider->mapNum, MAP_NUM(MAP_AQUA_HIDEOUT_UNUSED_RUBY_MAP2));
    EXPECT_EQ(provider->maxWorkspaceCells, 62 * 24);
    EXPECT_EQ(provider->maxGeneratedObjects, 4);
    EXPECT_EQ(GeneratedDungeon_Generate(provider, 0x91a5c0de, workspace), GENERATED_DUNGEON_GENERATION_SUCCEEDED);
    EXPECT_EQ(workspace->width, 62);
    EXPECT_EQ(workspace->height, 24);
    EXPECT_EQ(workspace->spawn.x, 2);
    EXPECT_EQ(workspace->originEndpoint.x, 1);
    EXPECT_EQ(workspace->destinationEndpoint.x, 60);
    EXPECT_EQ(workspace->spawn.y, 12);
    EXPECT_EQ(workspace->objectCount, 4);
    EXPECT(provider->translateCell(provider, workspace->cells[workspace->spawn.x + workspace->spawn.y * workspace->width], &metatile));
    EXPECT_EQ(metatile, METATILE_General_CalmWater);
    EXPECT(provider->translateCell(provider, workspace->cells[workspace->originEndpoint.x + workspace->originEndpoint.y * workspace->width], &metatile));
    EXPECT_EQ(metatile, METATILE_General_CalmWater);
    EXPECT(provider->translateCell(provider, workspace->cells[workspace->destinationEndpoint.x + workspace->destinationEndpoint.y * workspace->width], &metatile));
    EXPECT_EQ(metatile, METATILE_General_CalmWater);
    EXPECT(CountImpassableCells(provider, workspace) > 0);

    for (i = 0; i < workspace->objectCount; i++)
    {
        EXPECT_EQ(workspace->objects[i].template.localId, i + 1);
        EXPECT(workspace->objects[i].template.graphicsId == OBJ_EVENT_GFX_SWIMMER_M_WATER
            || workspace->objects[i].template.graphicsId == OBJ_EVENT_GFX_SWIMMER_F_WATER);
        EXPECT_EQ(workspace->objects[i].template.trainerType, TRAINER_TYPE_NORMAL);
        EXPECT_NE(workspace->objects[i].template.script, NULL);
        EXPECT(workspace->objects[i].template.y + workspace->objects[i].template.trainerRange_berryTreeId < workspace->spawn.y
            || workspace->objects[i].template.y > workspace->spawn.y + workspace->objects[i].template.trainerRange_berryTreeId);
    }

    for (u16 y = 0; y < workspace->height && !foundBlocked; y++)
    {
        for (u16 x = 0; x < workspace->width; x++)
        {
            if (!provider->translateCell(provider, workspace->cells[x + y * workspace->width], &metatile)
             || (metatile & MAPGRID_IMPASSABLE) == 0)
                continue;

            blocked = (struct GeneratedDungeonPoint){x, y};
            adjacent = (struct GeneratedDungeonPoint){x + 1, y};
            if (adjacent.x >= workspace->width)
                adjacent = (struct GeneratedDungeonPoint){x - 1, y};
            foundBlocked = TRUE;
            break;
        }
    }
    EXPECT(foundBlocked);
    EXPECT(!provider->canMove(provider, workspace, adjacent, blocked));
}

TEST("Generated ocean fallback retains impassable terrain and endpoint reachability")
{
    const struct GeneratedDungeonProvider *provider = NULL;
    struct GeneratedDungeonProvider fallbackProvider;
    struct GeneratedDungeonWorkspace *workspace = GetTestWorkspace();

    EXPECT(GeneratedOcean_Init());
    EXPECT(GeneratedDungeon_FindProviderById(GENERATED_OCEAN_PROVIDER_ID, GENERATED_OCEAN_GENERATION_VERSION, &provider));
    fallbackProvider = *provider;
    fallbackProvider.generate = AlwaysFailGeneration;
    EXPECT_EQ(GeneratedDungeon_Generate(&fallbackProvider, 0x91a5c0de, workspace), GENERATED_DUNGEON_GENERATION_FALLBACK);
    EXPECT(CountImpassableCells(&fallbackProvider, workspace) > 0);
    EXPECT(GeneratedDungeonWorkspace_HasReachableEndpoints(&fallbackProvider, workspace));
}

TEST("Generated ocean trainer progress is checksummed and isolated to the active run")
{
    struct GeneratedDungeonSaveRecord *record = (struct GeneratedDungeonSaveRecord *)gSaveBlock1Ptr->generatedDungeon;
    struct WarpData origin = { .mapGroup = MAP_GROUP(MAP_LITTLEROOT_TOWN), .mapNum = MAP_NUM(MAP_LITTLEROOT_TOWN), .warpId = WARP_ID_NONE, .x = 0, .y = 0 };
    struct WarpData destination = { .mapGroup = MAP_GROUP(MAP_ROUTE40), .mapNum = MAP_NUM(MAP_ROUTE40), .warpId = WARP_ID_NONE, .x = 0, .y = 30 };
    struct WarpData savedLocation = gSaveBlock1Ptr->location;
    bool32 defeated = TRUE;

    EXPECT(GeneratedOcean_Init());
    GeneratedDungeonRecordClear(record);
    EXPECT(GeneratedDungeon_BeginRun(GENERATED_OCEAN_PROVIDER_ID, GENERATED_OCEAN_GENERATION_VERSION,
                                     0x12345678, &origin, DIR_NORTH, &destination, DIR_EAST));
    gSaveBlock1Ptr->location.mapGroup = MAP_GROUP(MAP_AQUA_HIDEOUT_UNUSED_RUBY_MAP2);
    gSaveBlock1Ptr->location.mapNum = MAP_NUM(MAP_AQUA_HIDEOUT_UNUSED_RUBY_MAP2);

    EXPECT(GeneratedOcean_IsActive());
    EXPECT(GeneratedOcean_GetTrainerDefeated(1, &defeated));
    EXPECT(!defeated);
    EXPECT(GeneratedOcean_SetTrainerDefeated(1));
    EXPECT(GeneratedDungeonRecordHasValidFullEnvelope(record));
    EXPECT(GeneratedOcean_GetTrainerDefeated(1, &defeated));
    EXPECT(defeated);
    EXPECT(!GeneratedOcean_GetTrainerDefeated(5, &defeated));
    EXPECT(!GeneratedOcean_SetTrainerDefeated(5));

    GeneratedDungeon_ClearRun();
    gSaveBlock1Ptr->location = savedLocation;
}
