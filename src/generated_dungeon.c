#include "global.h"
#include "generated_dungeon.h"
#include "generated_dungeon_persistence.h"
#include "overworld.h"
#include "constants/map_groups.h"
#include "data/map_group_count.h"

extern const struct MapHeader *const *const gMapGroups[];

static const struct GeneratedDungeonProvider *sRegistry;
static u16 sRegistryCount;

static const struct GeneratedDungeonSaveRecord *GetActiveRecord(void)
{
    return (const struct GeneratedDungeonSaveRecord *)gSaveBlock1Ptr->generatedDungeon;
}

static bool32 IsValidFacing(u8 facing)
{
    return facing >= DIR_SOUTH && facing < CARDINAL_DIRECTION_COUNT;
}

static bool32 IsValidWarpContext(const struct WarpData *warp)
{
    const struct MapHeader *mapHeader;

    if (warp == NULL || warp->mapGroup < 0 || warp->mapNum < 0
     || warp->mapGroup >= MAP_GROUPS_COUNT
     || gMapGroups[warp->mapGroup] == NULL
     || warp->mapNum >= MAP_GROUP_COUNT[warp->mapGroup])
        return FALSE;

    mapHeader = gMapGroups[warp->mapGroup][warp->mapNum];
    if (mapHeader == NULL || mapHeader->mapLayout == NULL || mapHeader->events == NULL)
        return FALSE;

    if (warp->warpId != WARP_ID_NONE)
        return warp->warpId >= 0 && warp->warpId < mapHeader->events->warpCount;

    return warp->x >= 0 && warp->y >= 0
        && warp->x < mapHeader->mapLayout->width
        && warp->y < mapHeader->mapLayout->height;
}

static enum GeneratedDungeonRecordClassification ClassifyCurrentRecord(void)
{
    const struct GeneratedDungeonSaveRecord *record = GetActiveRecord();
    const struct GeneratedDungeonProvider *provider;
    bool8 payloadSupported = GeneratedDungeon_FindProviderById(record->providerId, record->generationVersion, &provider);

    return GeneratedDungeonRecordClassify(record, payloadSupported);
}

STATIC_ASSERT(sizeof(struct GeneratedDungeonWorkspace) < GENERATED_DUNGEON_WORKSPACE_MAX_BYTES, GeneratedDungeonWorkspaceFitsMapBufferOverlay);

static bool32 IsProviderValid(const struct GeneratedDungeonProvider *provider)
{
    if (provider == NULL
     || provider->providerId == 0
     || provider->generationVersion == 0
     || provider->generationVersion > 0xFF
     || provider->maxWorkspaceCells == 0
     || provider->maxWorkspaceCells > GENERATED_DUNGEON_MAX_CELLS
     || provider->maxGeneratedObjects > GENERATED_DUNGEON_MAX_OBJECTS
     || provider->translateCell == NULL
     || provider->canMove == NULL
     || provider->generate == NULL
     || provider->fallback == NULL)
        return FALSE;

    return TRUE;
}

static u32 MixSeed(u32 value)
{
    value ^= value >> 16;
    value *= 0x7FEB352D;
    value ^= value >> 15;
    value *= 0x846CA68B;
    return value ^ (value >> 16);
}

bool32 GeneratedDungeon_ValidateRegistry(const struct GeneratedDungeonProvider *providers, u16 count)
{
    u16 i;
    u16 j;

    if (count != 0 && providers == NULL)
        return FALSE;

    for (i = 0; i < count; i++)
    {
        if (!IsProviderValid(&providers[i]))
            return FALSE;

        for (j = 0; j < i; j++)
        {
            if (providers[i].providerId == providers[j].providerId
             || (providers[i].mapGroup == providers[j].mapGroup && providers[i].mapNum == providers[j].mapNum))
                return FALSE;
        }
    }

    return TRUE;
}

bool32 GeneratedDungeon_FindProviderByMap(u8 mapGroup, u8 mapNum, const struct GeneratedDungeonProvider **provider)
{
    u16 i;

    if (provider == NULL || !GeneratedDungeon_ValidateRegistry(sRegistry, sRegistryCount))
        return FALSE;

    for (i = 0; i < sRegistryCount; i++)
    {
        if (sRegistry[i].mapGroup == mapGroup && sRegistry[i].mapNum == mapNum)
        {
            *provider = &sRegistry[i];
            return TRUE;
        }
    }

    return FALSE;
}

bool32 GeneratedDungeon_FindProviderById(u16 providerId, u16 generationVersion, const struct GeneratedDungeonProvider **provider)
{
    u16 i;

    if (provider == NULL || !GeneratedDungeon_ValidateRegistry(sRegistry, sRegistryCount))
        return FALSE;

    for (i = 0; i < sRegistryCount; i++)
    {
        if (sRegistry[i].providerId == providerId && sRegistry[i].generationVersion == generationVersion)
        {
            *provider = &sRegistry[i];
            return TRUE;
        }
    }

    return FALSE;
}

bool32 GeneratedDungeon_IsActiveMap(u8 mapGroup, u8 mapNum)
{
    const struct GeneratedDungeonProvider *provider;
    const struct GeneratedDungeonSaveRecord *record = GetActiveRecord();

    if (!GeneratedDungeon_FindProviderById(record->providerId, record->generationVersion, &provider))
        return FALSE;
    if (GeneratedDungeonRecordClassify(record, TRUE) != GENERATED_DUNGEON_RECORD_ACTIVE)
        return FALSE;
    return provider->mapGroup == mapGroup && provider->mapNum == mapNum;
}

u8 GeneratedDungeon_GetActiveObjectEventCount(void)
{
    const struct GeneratedDungeonSaveRecord *record = GetActiveRecord();
    const struct GeneratedDungeonProvider *provider;

    if (!GeneratedDungeon_FindProviderById(record->providerId, record->generationVersion, &provider)
     || GeneratedDungeonRecordClassify(record, TRUE) != GENERATED_DUNGEON_RECORD_ACTIVE)
        return 0;
    for (u8 count = 0; count < provider->maxGeneratedObjects; count++)
        if (gSaveBlock1Ptr->objectEventTemplates[count].localId == 0)
            return count;
    return provider->maxGeneratedObjects;
}

bool32 GeneratedDungeon_BeginRun(u16 providerId, u16 generationVersion, u32 seed, const struct WarpData *origin, u8 originFacing, const struct WarpData *destination, u8 destinationFacing)
{
    const struct GeneratedDungeonProvider *provider;
    struct GeneratedDungeonSaveRecord record;

    if (!GeneratedDungeon_FindProviderById(providerId, generationVersion, &provider)
     || !IsValidWarpContext(origin)
     || !IsValidWarpContext(destination)
     || !IsValidFacing(originFacing)
     || !IsValidFacing(destinationFacing))
        return FALSE;

    GeneratedDungeonRecordClear(&record);
    record.providerId = provider->providerId;
    record.generationVersion = provider->generationVersion;
    record.seed = seed;
    record.origin = *origin;
    record.originFacing = originFacing;
    record.destination = *destination;
    record.destinationFacing = destinationFacing;
    GeneratedDungeonRecordFinalize(&record);
    *(struct GeneratedDungeonSaveRecord *)gSaveBlock1Ptr->generatedDungeon = record;
    return TRUE;
}

void GeneratedDungeon_ClearRun(void)
{
    GeneratedDungeonRecordClear((struct GeneratedDungeonSaveRecord *)gSaveBlock1Ptr->generatedDungeon);
}

static bool32 DepartUsingRecordedWarp(bool32 useDestination)
{
    const struct GeneratedDungeonSaveRecord *record = GetActiveRecord();
    struct WarpData warp;
    u8 facing;

    if (ClassifyCurrentRecord() != GENERATED_DUNGEON_RECORD_ACTIVE)
        return FALSE;

    warp = useDestination ? record->destination : record->origin;
    facing = useDestination ? record->destinationFacing : record->originFacing;
    if (!IsValidWarpContext(&warp) || !IsValidFacing(facing))
        return FALSE;

    GeneratedDungeon_ClearRun();
    SetGeneratedDungeonWarpDestination(&warp, facing);
    return TRUE;
}

bool32 GeneratedDungeon_DepartToOrigin(void)
{
    return DepartUsingRecordedWarp(FALSE);
}

bool32 GeneratedDungeon_DepartToDestination(void)
{
    return DepartUsingRecordedWarp(TRUE);
}

bool32 GeneratedDungeon_RecoverUnsupportedRun(void)
{
    const struct GeneratedDungeonSaveRecord *record = GetActiveRecord();
    struct WarpData origin;
    u8 facing;

    if (ClassifyCurrentRecord() != GENERATED_DUNGEON_RECORD_RECOVER_TO_ORIGIN)
        return FALSE;

    origin = record->origin;
    facing = record->originFacing;
    if (!IsValidWarpContext(&origin) || !IsValidFacing(facing))
        return FALSE;

    GeneratedDungeon_ClearRun();
    SetGeneratedDungeonWarpDestination(&origin, facing);
    return TRUE;
}

bool32 GeneratedDungeon_ShouldClearForDeparture(const struct WarpData *source, const struct WarpData *destination)
{
    if (source == NULL || destination == NULL)
        return FALSE;
    if (!GeneratedDungeon_IsActiveMap(source->mapGroup, source->mapNum))
        return FALSE;
    return source->mapGroup != destination->mapGroup || source->mapNum != destination->mapNum;
}

bool32 GeneratedDungeon_ClearForDeparture(const struct WarpData *source, const struct WarpData *destination)
{
    if (!GeneratedDungeon_ShouldClearForDeparture(source, destination))
        return FALSE;

    GeneratedDungeon_ClearRun();
    return TRUE;
}

rng_value_t GeneratedDungeon_DeriveStream(u16 providerId, u16 generationVersion, u32 seed, enum GeneratedDungeonRngDomain domain, u8 attempt)
{
    u32 identity = providerId | ((u32)generationVersion << 16);
    u32 domainIdentity = (u32)domain * 0x9E3779B9;
    u32 attemptIdentity = (u32)attempt * 0x85EBCA6B;

    return LocalRandomSeed(MixSeed(seed ^ identity ^ domainIdentity ^ attemptIdentity));
}

void GeneratedDungeon_DeriveStreams(const struct GeneratedDungeonProvider *provider, u32 seed, u8 attempt, struct GeneratedDungeonRngStreams *rng)
{
    u8 domain;

    if (!IsProviderValid(provider) || rng == NULL)
        return;

    for (domain = 0; domain < GENERATED_DUNGEON_RNG_DOMAIN_COUNT; domain++)
        rng->values[domain] = GeneratedDungeon_DeriveStream(provider->providerId, provider->generationVersion, seed, domain, attempt);
}

void GeneratedDungeonWorkspace_Reset(struct GeneratedDungeonWorkspace *workspace)
{
    if (workspace != NULL)
        memset(workspace, 0, sizeof(*workspace));
}

bool32 GeneratedDungeonWorkspace_SetDimensions(struct GeneratedDungeonWorkspace *workspace, u16 width, u16 height)
{
    u32 cells = (u32)width * height;

    if (workspace == NULL || width == 0 || height == 0 || cells > GENERATED_DUNGEON_MAX_CELLS)
        return FALSE;

    workspace->width = width;
    workspace->height = height;
    return TRUE;
}

bool32 GeneratedDungeonWorkspace_SetCell(struct GeneratedDungeonWorkspace *workspace, u16 x, u16 y, u16 cell)
{
    if (workspace == NULL || x >= workspace->width || y >= workspace->height)
        return FALSE;

    workspace->cells[x + y * workspace->width] = cell;
    return TRUE;
}

bool32 GeneratedDungeonWorkspace_GetCell(const struct GeneratedDungeonWorkspace *workspace, u16 x, u16 y, u16 *cell)
{
    if (workspace == NULL || cell == NULL || x >= workspace->width || y >= workspace->height)
        return FALSE;

    *cell = workspace->cells[x + y * workspace->width];
    return TRUE;
}

bool32 GeneratedDungeonWorkspace_SetObjectCount(struct GeneratedDungeonWorkspace *workspace, u8 objectCount)
{
    if (workspace == NULL || objectCount > GENERATED_DUNGEON_MAX_OBJECTS)
        return FALSE;

    workspace->objectCount = objectCount;
    return TRUE;
}

static bool32 IsPointInWorkspace(const struct GeneratedDungeonWorkspace *workspace, struct GeneratedDungeonPoint point)
{
    return workspace != NULL && point.x < workspace->width && point.y < workspace->height;
}

bool32 GeneratedDungeonWorkspace_SetSpawn(struct GeneratedDungeonWorkspace *workspace, u16 x, u16 y)
{
    struct GeneratedDungeonPoint point = {x, y};

    if (!IsPointInWorkspace(workspace, point))
        return FALSE;
    workspace->spawn = point;
    return TRUE;
}

bool32 GeneratedDungeonWorkspace_SetOriginEndpoint(struct GeneratedDungeonWorkspace *workspace, u16 x, u16 y)
{
    struct GeneratedDungeonPoint point = {x, y};

    if (!IsPointInWorkspace(workspace, point))
        return FALSE;
    workspace->originEndpoint = point;
    return TRUE;
}

bool32 GeneratedDungeonWorkspace_SetDestinationEndpoint(struct GeneratedDungeonWorkspace *workspace, u16 x, u16 y)
{
    struct GeneratedDungeonPoint point = {x, y};

    if (!IsPointInWorkspace(workspace, point))
        return FALSE;
    workspace->destinationEndpoint = point;
    return TRUE;
}

bool32 GeneratedDungeonWorkspace_SetObject(struct GeneratedDungeonWorkspace *workspace, u8 index, const struct ObjectEventTemplate *template, bool8 blocksMovement)
{
    if (workspace == NULL || template == NULL || index >= workspace->objectCount)
        return FALSE;

    workspace->objects[index].template = *template;
    workspace->objects[index].blocksMovement = blocksMovement;
    return TRUE;
}

static bool32 IsObjectValid(const struct GeneratedDungeonWorkspace *workspace, const struct GeneratedDungeonObject *object, u8 index)
{
    u8 i;

    if (object->template.localId == 0
     || object->template.script == NULL
     || object->template.x < 0
     || object->template.y < 0
     || object->template.x >= workspace->width
     || object->template.y >= workspace->height)
        return FALSE;

    for (i = 0; i < index; i++)
    {
        if (workspace->objects[i].template.localId == object->template.localId
         || (workspace->objects[i].template.x == object->template.x && workspace->objects[i].template.y == object->template.y))
            return FALSE;
    }
    return TRUE;
}

static bool32 IsOccupied(const struct GeneratedDungeonWorkspace *workspace, struct GeneratedDungeonPoint point)
{
    u8 i;

    for (i = 0; i < workspace->objectCount; i++)
    {
        const struct GeneratedDungeonObject *object = &workspace->objects[i];

        if (object->blocksMovement && object->template.x == point.x && object->template.y == point.y)
            return TRUE;
    }
    return FALSE;
}

bool32 GeneratedDungeonWorkspace_IsValid(const struct GeneratedDungeonProvider *provider, const struct GeneratedDungeonWorkspace *workspace)
{
    u32 cells;
    u8 i;

    if (!IsProviderValid(provider) || workspace == NULL)
        return FALSE;

    cells = (u32)workspace->width * workspace->height;
    if (!(workspace->width != 0
        && workspace->height != 0
        && cells <= provider->maxWorkspaceCells
        && cells <= GENERATED_DUNGEON_MAX_CELLS
        && workspace->objectCount <= provider->maxGeneratedObjects
        && workspace->objectCount <= GENERATED_DUNGEON_MAX_OBJECTS
        && IsPointInWorkspace(workspace, workspace->spawn)
        && IsPointInWorkspace(workspace, workspace->originEndpoint)
        && IsPointInWorkspace(workspace, workspace->destinationEndpoint)))
        return FALSE;

    if (IsOccupied(workspace, workspace->spawn)
     || IsOccupied(workspace, workspace->originEndpoint)
     || IsOccupied(workspace, workspace->destinationEndpoint))
        return FALSE;

    for (i = 0; i < workspace->objectCount; i++)
        if (!IsObjectValid(workspace, &workspace->objects[i], i))
            return FALSE;

    return TRUE;
}

static bool32 IsReached(const struct GeneratedDungeonWorkspace *workspace, u16 index)
{
    return (workspace->reached[index / 8] & (1 << (index % 8))) != 0;
}

static void SetReached(struct GeneratedDungeonWorkspace *workspace, u16 index)
{
    workspace->reached[index / 8] |= 1 << (index % 8);
}

bool32 GeneratedDungeonWorkspace_HasReachableEndpoints(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonWorkspace *workspace)
{
    static const s8 sDx[] = {0, 1, 0, -1};
    static const s8 sDy[] = {-1, 0, 1, 0};
    u16 head = 0;
    u16 tail = 0;

    if (!GeneratedDungeonWorkspace_IsValid(provider, workspace))
        return FALSE;

    memset(workspace->reached, 0, sizeof(workspace->reached));
    workspace->queue[tail++] = workspace->spawn.x + workspace->spawn.y * workspace->width;
    SetReached(workspace, workspace->queue[0]);
    while (head < tail)
    {
        struct GeneratedDungeonPoint from;
        u8 direction;
        u16 index = workspace->queue[head++];

        from.x = index % workspace->width;
        from.y = index / workspace->width;
        for (direction = 0; direction < ARRAY_COUNT(sDx); direction++)
        {
            struct GeneratedDungeonPoint to = {from.x + sDx[direction], from.y + sDy[direction]};
            u16 toIndex;

            if ((s16)to.x < 0 || (s16)to.y < 0 || !IsPointInWorkspace(workspace, to) || IsOccupied(workspace, to))
                continue;
            toIndex = to.x + to.y * workspace->width;
            if (!IsReached(workspace, toIndex) && provider->canMove(provider, workspace, from, to))
            {
                SetReached(workspace, toIndex);
                workspace->queue[tail++] = toIndex;
            }
        }
    }
    return IsReached(workspace, workspace->originEndpoint.x + workspace->originEndpoint.y * workspace->width)
        && IsReached(workspace, workspace->destinationEndpoint.x + workspace->destinationEndpoint.y * workspace->width);
}

enum GeneratedDungeonGenerationResult GeneratedDungeon_Generate(const struct GeneratedDungeonProvider *provider, u32 seed, struct GeneratedDungeonWorkspace *workspace)
{
    struct GeneratedDungeonRngStreams rng;
    u8 attempt;

    if (!IsProviderValid(provider) || workspace == NULL)
        return GENERATED_DUNGEON_GENERATION_FAILED;

    for (attempt = 0; attempt < GENERATED_DUNGEON_MAX_ATTEMPTS; attempt++)
    {
        GeneratedDungeonWorkspace_Reset(workspace);
        GeneratedDungeon_DeriveStreams(provider, seed, attempt, &rng);
        if (provider->generate(provider, &rng, attempt, workspace)
         && GeneratedDungeonWorkspace_IsValid(provider, workspace)
         && GeneratedDungeonWorkspace_HasReachableEndpoints(provider, workspace))
            return GENERATED_DUNGEON_GENERATION_SUCCEEDED;
    }

    GeneratedDungeonWorkspace_Reset(workspace);
    if (provider->fallback(provider, workspace)
     && GeneratedDungeonWorkspace_IsValid(provider, workspace)
     && GeneratedDungeonWorkspace_HasReachableEndpoints(provider, workspace))
        return GENERATED_DUNGEON_GENERATION_FALLBACK;

    GeneratedDungeonWorkspace_Reset(workspace);
    return GENERATED_DUNGEON_GENERATION_FAILED;
}

static bool32 CanPublish(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonWorkspace *workspace, const struct GeneratedDungeonPublication *publication)
{
    u32 cells;
    u16 i;
    u16 metatile;

    if (publication == NULL || publication->map == NULL || publication->templates == NULL
     || publication->mapWidth != workspace->width || publication->mapHeight != workspace->height
     || publication->mapStride < workspace->width || publication->templateCapacity < workspace->objectCount)
        return FALSE;

    cells = (u32)workspace->width * workspace->height;
    for (i = 0; i < cells; i++)
        if (!provider->translateCell(provider, workspace->cells[i], &metatile))
            return FALSE;
    return TRUE;
}

static void Publish(const struct GeneratedDungeonProvider *provider, struct GeneratedDungeonWorkspace *workspace, const struct GeneratedDungeonPublication *publication)
{
    u16 x;
    u16 y;
    u8 i;
    u16 metatile;

    if (publication->mapWritesAfterCells)
    {
        // The map shell begins after the workspace's semantic cell storage.
        // Descending order keeps an aliased destination from replacing a cell
        // which the next translation has not yet consumed.
        for (y = workspace->height; y-- > 0;)
            for (x = workspace->width; x-- > 0;)
            {
                provider->translateCell(provider, workspace->cells[x + y * workspace->width], &metatile);
                publication->map[x + y * publication->mapStride] = metatile;
            }
    }
    else
    {
        for (y = 0; y < workspace->height; y++)
            for (x = 0; x < workspace->width; x++)
            {
                provider->translateCell(provider, workspace->cells[x + y * workspace->width], &metatile);
                publication->map[x + y * publication->mapStride] = metatile;
            }
    }
    memset(publication->templates, 0, sizeof(*publication->templates) * publication->templateCapacity);
    for (i = 0; i < workspace->objectCount; i++)
        publication->templates[i] = workspace->objects[i].template;
}

enum GeneratedDungeonGenerationResult GeneratedDungeon_GenerateAndPublish(const struct GeneratedDungeonProvider *provider, u32 seed, struct GeneratedDungeonWorkspace *workspace, const struct GeneratedDungeonPublication *publication)
{
    enum GeneratedDungeonGenerationResult result = GeneratedDungeon_Generate(provider, seed, workspace);

    if (result == GENERATED_DUNGEON_GENERATION_FAILED || !CanPublish(provider, workspace, publication))
        return GENERATED_DUNGEON_GENERATION_FAILED;
    Publish(provider, workspace, publication);
    return result;
}

bool32 GeneratedDungeonProgress_TryGet(u64 progress, u8 bit, bool32 *set)
{
    if (set == NULL || bit >= GENERATED_DUNGEON_PROGRESS_BITS)
        return FALSE;

    *set = (progress & ((u64)1 << bit)) != 0;
    return TRUE;
}

bool32 GeneratedDungeonProgress_TrySet(u64 *progress, u8 bit)
{
    if (progress == NULL || bit >= GENERATED_DUNGEON_PROGRESS_BITS)
        return FALSE;

    *progress |= (u64)1 << bit;
    return TRUE;
}

bool32 GeneratedDungeonProgress_TryClear(u64 *progress, u8 bit)
{
    if (progress == NULL || bit >= GENERATED_DUNGEON_PROGRESS_BITS)
        return FALSE;

    *progress &= ~((u64)1 << bit);
    return TRUE;
}

#if TESTING
bool32 GeneratedDungeon_TestSetRegistry(const struct GeneratedDungeonProvider *providers, u16 count)
{
    if (!GeneratedDungeon_ValidateRegistry(providers, count))
        return FALSE;

    sRegistry = providers;
    sRegistryCount = count;
    return TRUE;
}

void GeneratedDungeon_TestResetRegistry(void)
{
    sRegistry = NULL;
    sRegistryCount = 0;
}
#endif

#ifdef DEBUG
bool32 GeneratedDungeon_DebugSetRegistry(const struct GeneratedDungeonProvider *providers, u16 count)
{
    if (!GeneratedDungeon_ValidateRegistry(providers, count))
        return FALSE;

    sRegistry = providers;
    sRegistryCount = count;
    return TRUE;
}
#endif
