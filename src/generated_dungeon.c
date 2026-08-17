#include "global.h"
#include "generated_dungeon.h"

static const struct GeneratedDungeonProvider *sRegistry;
static u16 sRegistryCount;

STATIC_ASSERT(sizeof(struct GeneratedDungeonWorkspace) < GENERATED_DUNGEON_WORKSPACE_MAX_BYTES, GeneratedDungeonWorkspaceFitsMapBufferOverlay);

static bool32 IsProviderValid(const struct GeneratedDungeonProvider *provider)
{
    if (provider == NULL
     || provider->providerId == 0
     || provider->generationVersion == 0
     || provider->maxWorkspaceCells == 0
     || provider->maxWorkspaceCells > GENERATED_DUNGEON_MAX_CELLS
     || provider->maxGeneratedObjects > GENERATED_DUNGEON_MAX_OBJECTS
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

bool32 GeneratedDungeonWorkspace_IsValid(const struct GeneratedDungeonProvider *provider, const struct GeneratedDungeonWorkspace *workspace)
{
    u32 cells;

    if (!IsProviderValid(provider) || workspace == NULL)
        return FALSE;

    cells = (u32)workspace->width * workspace->height;
    return workspace->width != 0
        && workspace->height != 0
        && cells <= provider->maxWorkspaceCells
        && cells <= GENERATED_DUNGEON_MAX_CELLS
        && workspace->objectCount <= provider->maxGeneratedObjects
        && workspace->objectCount <= GENERATED_DUNGEON_MAX_OBJECTS;
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
         && GeneratedDungeonWorkspace_IsValid(provider, workspace))
            return GENERATED_DUNGEON_GENERATION_SUCCEEDED;
    }

    GeneratedDungeonWorkspace_Reset(workspace);
    if (provider->fallback(provider, workspace)
     && GeneratedDungeonWorkspace_IsValid(provider, workspace))
        return GENERATED_DUNGEON_GENERATION_FALLBACK;

    GeneratedDungeonWorkspace_Reset(workspace);
    return GENERATED_DUNGEON_GENERATION_FAILED;
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
