#ifndef GUARD_GENERATED_OCEAN_H
#define GUARD_GENERATED_OCEAN_H

#include "global.h"

#define GENERATED_OCEAN_PROVIDER_ID 0x0092
#define GENERATED_OCEAN_GENERATION_VERSION 1

struct SurfEdgeExit;

bool32 GeneratedOcean_Init(void);
bool8 GeneratedOcean_TryBegin(const struct SurfEdgeExit *exit);
bool32 GeneratedOcean_IsActive(void);
bool32 GeneratedOcean_GetTrainerDefeated(u8 localId, bool32 *defeated);
bool32 GeneratedOcean_SetTrainerDefeated(u8 localId);
void GeneratedOcean_DepartToOrigin(void);
void GeneratedOcean_DepartToDestination(void);

#endif // GUARD_GENERATED_OCEAN_H
