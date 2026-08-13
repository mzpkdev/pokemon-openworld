#ifndef GUARD_SAFARI_ZONE_H
#define GUARD_SAFARI_ZONE_H

extern u8 gNumSafariBalls;
extern u16 gSafariZoneStepCounter;

struct SafariZoneExitSpec
{
    u16 sceneVar;
    u16 normalScene;
    u16 midBattleScene;
    u16 entranceMap;
    u8 x;
    u8 y;
};

bool32 EnterSafariModeForFacility(u8 facility);
void EnterHoennSafariMode(void);
void EnterKantoSafariMode(void);
u8 GetSafariZoneFacility(void);
bool32 SafariZoneUsesKantoRules(void);
bool32 SafariZonePublishesFanClubShow(void);
u16 GetSafariZoneStepLimit(void);
bool32 GetSafariZoneExitSpec(u8 facility, struct SafariZoneExitSpec *spec);

bool32 GetSafariZoneFlag(void);
void SetSafariZoneFlag(void);
void ResetSafariZoneFlag(void);

void ExitSafariMode(void);

bool8 SafariZoneTakeStep(void);
void SafariZoneRetirePrompt(void);

void CB2_EndSafariBattle(void);

struct Pokeblock *SafariZoneGetActivePokeblock(void);
void SafariZoneActivatePokeblockFeeder(u8 pkblId);

#endif // GUARD_SAFARI_ZONE_H
