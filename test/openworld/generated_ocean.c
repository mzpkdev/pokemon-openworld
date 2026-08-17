#include "global.h"
#include "fieldmap.h"
#include "generated_dungeon.h"
#include "generated_dungeon_persistence.h"
#include "generated_ocean.h"
#include "test/test.h"
#include "constants/event_objects.h"
#include "constants/maps.h"
#include "constants/trainer_types.h"

STATIC_ASSERT(sizeof(struct GeneratedDungeonWorkspace) <= sizeof(sBackupMapData), GeneratedOceanTestWorkspaceFitsBackupMapBuffer);

static struct GeneratedDungeonWorkspace *GetTestWorkspace(void)
{
    return (void *)sBackupMapData;
}

TEST("Generated ocean registers its fixed shell and only emits swimmers")
{
    const struct GeneratedDungeonProvider *provider = NULL;
    struct GeneratedDungeonWorkspace *workspace = GetTestWorkspace();
    u8 i;

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
    EXPECT(workspace->cells[workspace->spawn.x + workspace->spawn.y * workspace->width] <= 1);

    for (i = 0; i < workspace->objectCount; i++)
    {
        EXPECT_EQ(workspace->objects[i].template.localId, i + 1);
        EXPECT(workspace->objects[i].template.graphicsId == OBJ_EVENT_GFX_SWIMMER_M_WATER
            || workspace->objects[i].template.graphicsId == OBJ_EVENT_GFX_SWIMMER_F_WATER);
        EXPECT_EQ(workspace->objects[i].template.trainerType, TRAINER_TYPE_NORMAL);
        EXPECT_NE(workspace->objects[i].template.script, NULL);
    }
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
