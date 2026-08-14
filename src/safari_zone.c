#include "global.h"
#include "battle.h"
#include "event_data.h"
#include "field_player_avatar.h"
#include "overworld.h"
#include "main.h"
#include "pokeblock.h"
#include "safari_zone.h"
#include "script.h"
#include "string_util.h"
#include "tv.h"
#include "constants/game_stat.h"
#include "constants/maps.h"
#include "constants/safari_zone.h"
#include "constants/vars.h"
#include "field_screen_effect.h"

struct PokeblockFeeder
{
    /*0x00*/ s16 x;
    /*0x02*/ s16 y;
    /*0x04*/ s8 mapNum;
    /*0x05*/ u8 stepCounter;
    /*0x08*/ struct Pokeblock pokeblock;
};

#define NUM_POKEBLOCK_FEEDERS 10

extern const u8 SafariZone_EventScript_TimesUp[];
extern const u8 SafariZone_EventScript_RetirePrompt[];
extern const u8 SafariZone_EventScript_OutOfBallsMidBattle[];
extern const u8 SafariZone_EventScript_OutOfBalls[];

EWRAM_DATA u8 gNumSafariBalls = 0;
EWRAM_DATA u16 gSafariZoneStepCounter = 0;
EWRAM_DATA static u8 sSafariZoneFacility = SAFARI_ZONE_FACILITY_NONE;
EWRAM_DATA static u8 sSafariZoneCaughtMons = 0;
EWRAM_DATA static u8 sSafariZonePkblkUses = 0;
EWRAM_DATA static struct PokeblockFeeder sPokeblockFeeders[NUM_POKEBLOCK_FEEDERS] = {0};

static void ClearAllPokeblockFeeders(void);
static void DecrementFeederStepCounters(void);

bool32 GetSafariZoneFlag(void)
{
    return FlagGet(FLAG_SYS_SAFARI_MODE)
        && sSafariZoneFacility != SAFARI_ZONE_FACILITY_NONE;
}

void SetSafariZoneFlag(void)
{
    FlagSet(FLAG_SYS_SAFARI_MODE);
}

void ResetSafariZoneFlag(void)
{
    FlagClear(FLAG_SYS_SAFARI_MODE);
    sSafariZoneFacility = SAFARI_ZONE_FACILITY_NONE;
    ClearAllPokeblockFeeders();
    gNumSafariBalls = 0;
    gSafariZoneStepCounter = 0;
    sSafariZoneCaughtMons = 0;
    sSafariZonePkblkUses = 0;
}

u8 GetSafariZoneFacility(void)
{
    return sSafariZoneFacility;
}

bool32 SafariZoneUsesKantoRules(void)
{
    return sSafariZoneFacility == SAFARI_ZONE_FACILITY_KANTO_FUCHSIA;
}

bool32 SafariZonePublishesFanClubShow(void)
{
    return sSafariZoneFacility == SAFARI_ZONE_FACILITY_HOENN_ROUTE_121;
}

u16 GetSafariZoneStepLimit(void)
{
    switch (sSafariZoneFacility)
    {
    case SAFARI_ZONE_FACILITY_HOENN_ROUTE_121:
        return SAFARI_ZONE_HOENN_STEP_LIMIT;
    case SAFARI_ZONE_FACILITY_KANTO_FUCHSIA:
        return SAFARI_ZONE_KANTO_STEP_LIMIT;
    default:
        return 0;
    }
}

bool32 GetSafariZoneExitSpec(u8 facility, struct SafariZoneExitSpec *spec)
{
    static const struct SafariZoneExitSpec specs[] =
    {
        [SAFARI_ZONE_FACILITY_HOENN_ROUTE_121] =
        {
            .sceneVar = VAR_SAFARI_ZONE_STATE,
            .normalScene = 1,
            .midBattleScene = 1,
            .entranceMap = MAP_ROUTE121_SAFARI_ZONE_ENTRANCE,
            .x = 2,
            .y = 5,
        },
        [SAFARI_ZONE_FACILITY_KANTO_FUCHSIA] =
        {
            .sceneVar = VAR_MAP_SCENE_FUCHSIA_CITY_SAFARI_ZONE_ENTRANCE,
            .normalScene = 1,
            .midBattleScene = 3,
            .entranceMap = MAP_FUCHSIA_CITY_SAFARI_ZONE_ENTRANCE,
            .x = 4,
            .y = 1,
        },
    };

    if (spec == NULL || facility == SAFARI_ZONE_FACILITY_NONE || facility >= ARRAY_COUNT(specs))
        return FALSE;
    *spec = specs[facility];
    return TRUE;
}

bool32 EnterSafariModeForFacility(u8 facility)
{
    sSafariZoneFacility = facility;
    if (GetSafariZoneStepLimit() == 0)
    {
        ResetSafariZoneFlag();
        return FALSE;
    }

    IncrementGameStat(GAME_STAT_ENTERED_SAFARI_ZONE);
    SetSafariZoneFlag();
    ClearAllPokeblockFeeders();
    gNumSafariBalls = 30;
    gSafariZoneStepCounter = GetSafariZoneStepLimit();
    sSafariZoneCaughtMons = 0;
    sSafariZonePkblkUses = 0;
    return TRUE;
}

void EnterHoennSafariMode(void)
{
    EnterSafariModeForFacility(SAFARI_ZONE_FACILITY_HOENN_ROUTE_121);
}

void EnterKantoSafariMode(void)
{
    EnterSafariModeForFacility(SAFARI_ZONE_FACILITY_KANTO_FUCHSIA);
}

void ExitSafariMode(void)
{
    if (SafariZonePublishesFanClubShow())
        TryPutSafariFanClubOnAir(sSafariZoneCaughtMons, sSafariZonePkblkUses);
    ResetSafariZoneFlag();
}

bool8 SafariZoneTakeStep(void)
{
    if (GetSafariZoneFlag() == FALSE)
    {
        return FALSE;
    }

    DecrementFeederStepCounters();
    gSafariZoneStepCounter--;
    if (gSafariZoneStepCounter == 0)
    {
        ScriptContext_SetupScript(SafariZone_EventScript_TimesUp);
        return TRUE;
    }
    return FALSE;
}

void SafariZoneRetirePrompt(void)
{
    ScriptContext_SetupScript(SafariZone_EventScript_RetirePrompt);
}

void CB2_EndSafariBattle(void)
{
    sSafariZonePkblkUses += gBattleResults.pokeblockThrows;
    if (gBattleOutcome == B_OUTCOME_CAUGHT)
        sSafariZoneCaughtMons++;
    if (gNumSafariBalls != 0)
    {
        SetMainCallback2(CB2_ReturnToField);
    }
    else if (gBattleOutcome == B_OUTCOME_NO_SAFARI_BALLS)
    {
        RunScriptImmediately(SafariZone_EventScript_OutOfBallsMidBattle);
        WarpIntoMap();
        gFieldCallback = FieldCB_ReturnToFieldNoScriptCheckMusic;
        SetMainCallback2(CB2_LoadMap);
    }
    else if (gBattleOutcome == B_OUTCOME_CAUGHT)
    {
        ScriptContext_SetupScript(SafariZone_EventScript_OutOfBalls);
        ScriptContext_Stop();
        SetMainCallback2(CB2_ReturnToFieldContinueScriptPlayMapMusic);
    }
}

static void ClearPokeblockFeeder(u8 index)
{
    memset(&sPokeblockFeeders[index], 0, sizeof(struct PokeblockFeeder));
}

static void ClearAllPokeblockFeeders(void)
{
    memset(sPokeblockFeeders, 0, sizeof(sPokeblockFeeders));
}

void GetPokeblockFeederInFront(void)
{
    s16 x, y;
    u16 i;

    GetXYCoordsOneStepInFrontOfPlayer(&x, &y);

    for (i = 0; i < NUM_POKEBLOCK_FEEDERS; i++)
    {
        if (gSaveBlock1Ptr->location.mapNum == sPokeblockFeeders[i].mapNum
         && sPokeblockFeeders[i].x == x
         && sPokeblockFeeders[i].y == y)
        {
            gSpecialVar_Result = i;
            StringCopy(gStringVar1, gPokeblockNames[sPokeblockFeeders[i].pokeblock.color]);
            return;
        }
    }

    gSpecialVar_Result = -1;
}

void GetPokeblockFeederWithinRange(void)
{
    s16 x, y;
    u16 i;

    PlayerGetDestCoords(&x, &y);

    for (i = 0; i < NUM_POKEBLOCK_FEEDERS; i++)
    {
        if (gSaveBlock1Ptr->location.mapNum == sPokeblockFeeders[i].mapNum)
        {
            // Get absolute value of x and y distance from Pokeblock feeder on current map.
            x -= sPokeblockFeeders[i].x;
            y -= sPokeblockFeeders[i].y;
            if (x < 0)
                x *= -1;
            if (y < 0)
                y *= -1;
            if ((x + y) <= 5)
            {
                gSpecialVar_Result = i;
                return;
            }
        }
    }

    gSpecialVar_Result = -1;
}

// unused
struct Pokeblock *SafariZoneGetPokeblockInFront(void)
{
    GetPokeblockFeederInFront();

    if (gSpecialVar_Result == 0xFFFF)
        return NULL;
    else
        return &sPokeblockFeeders[gSpecialVar_Result].pokeblock;
}

struct Pokeblock *SafariZoneGetActivePokeblock(void)
{
    GetPokeblockFeederWithinRange();

    if (gSpecialVar_Result == 0xFFFF)
        return NULL;
    else
        return &sPokeblockFeeders[gSpecialVar_Result].pokeblock;
}

void SafariZoneActivatePokeblockFeeder(u8 pkblId)
{
    s16 x, y;
    u8 i;

    for (i = 0; i < NUM_POKEBLOCK_FEEDERS; i++)
    {
        // Find free entry in sPokeblockFeeders
        if (sPokeblockFeeders[i].mapNum == 0
         && sPokeblockFeeders[i].x == 0
         && sPokeblockFeeders[i].y == 0)
        {
            // Initialize Pokeblock feeder
            GetXYCoordsOneStepInFrontOfPlayer(&x, &y);
            sPokeblockFeeders[i].mapNum = gSaveBlock1Ptr->location.mapNum;
            sPokeblockFeeders[i].pokeblock = gSaveBlock1Ptr->pokeblocks[pkblId];
            sPokeblockFeeders[i].stepCounter = 100;
            sPokeblockFeeders[i].x = x;
            sPokeblockFeeders[i].y = y;
            break;
        }
    }
}

static void DecrementFeederStepCounters(void)
{
    u8 i;

    for (i = 0; i < NUM_POKEBLOCK_FEEDERS; i++)
    {
        if (sPokeblockFeeders[i].stepCounter != 0)
        {
            sPokeblockFeeders[i].stepCounter--;
            if (sPokeblockFeeders[i].stepCounter == 0)
                ClearPokeblockFeeder(i);
        }
    }
}

// unused
bool8 GetInFrontFeederPokeblockAndSteps(void)
{
    GetPokeblockFeederInFront();

    if (gSpecialVar_Result == 0xFFFF)
    {
        return FALSE;
    }

    ConvertIntToDecimalStringN(gStringVar2,
        sPokeblockFeeders[gSpecialVar_Result].stepCounter,
        STR_CONV_MODE_LEADING_ZEROS, 3);

    return TRUE;
}
