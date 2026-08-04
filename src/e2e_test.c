#include "global.h"

#if E2E_TESTING

#include "e2e_test.h"
#include "gba/isagbprint.h"
#include "main.h"
#include "overworld.h"
#include "title_screen.h"

#define E2E_TIMEOUT_FRAMES (60 * 120)

static u32 sFrameCount;
static bool8 sSawTitleScreen;
static u16 sPreviousKeys;

static void E2E_Exit(u8 exitCode)
{
    register u32 r0 asm("r0") = exitCode;
    asm volatile("swi 0x3" :: "r" (r0));
    for (;;)
        ;
}

static void E2E_SetKeys(u16 keys)
{
    gMain.newKeysRaw = keys & ~sPreviousKeys;
    gMain.newKeys = gMain.newKeysRaw;
    gMain.newAndRepeatedKeys = gMain.newKeysRaw;
    gMain.heldKeysRaw = keys;
    gMain.heldKeys = keys;
    sPreviousKeys = keys;
}

void E2E_RunFrame(void)
{
    u16 keys = 0;

    sFrameCount++;
    if (gMain.callback2 == CB2_InitTitleScreen)
        sSawTitleScreen = TRUE;

    if (sSawTitleScreen && gMain.callback2 == CB2_Overworld)
    {
        MgbaPrintf(MGBA_LOG_INFO, "E2E PASS milestone=CB2_Overworld frames=%u", sFrameCount);
        E2E_Exit(0);
    }

    if (sFrameCount >= E2E_TIMEOUT_FRAMES)
    {
        MgbaPrintf(MGBA_LOG_ERROR, "E2E FAIL timeout frames=%u sawTitle=%u", sFrameCount, sSawTitleScreen);
        E2E_Exit(1);
    }

    // Once title initialization is observed, keep producing distinct SELECT
    // presses until the title task reaches its Quickstart input phase.
    if (sSawTitleScreen && (sFrameCount & 1))
        keys = SELECT_BUTTON;
    E2E_SetKeys(keys);
}

#endif // E2E_TESTING
