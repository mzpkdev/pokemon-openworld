#ifdef DEBUG

#include "global.h"
#include "battle_setup.h"
#include "integrity_capture.h"
#include "item.h"
#include "item_menu.h"
#include "location_codecs.h"
#include "main.h"
#include "overworld.h"
#include "pokeball.h"
#include "pokemon.h"
#include "script_pokemon_util.h"
#include "constants/item.h"
#include "constants/items.h"
#include "constants/pokemon.h"

volatile struct IntegrityCaptureRequest gIntegrityCaptureRequest;
volatile struct IntegrityCaptureResult gIntegrityCaptureResult;
volatile struct IntegrityProvenanceRequest gIntegrityProvenanceRequest;
volatile struct IntegrityProvenanceResult gIntegrityProvenanceResult;

STATIC_ASSERT(sizeof(struct IntegrityCaptureRequest) == 12, IntegrityCaptureRequestSize);
STATIC_ASSERT(offsetof(struct IntegrityCaptureRequest, status) == 9, IntegrityCaptureRequestStatusOffset);
STATIC_ASSERT(sizeof(struct IntegrityCaptureResult) == 16, IntegrityCaptureResultSize);
STATIC_ASSERT(offsetof(struct IntegrityCaptureResult, status) == 10, IntegrityCaptureResultStatusOffset);
STATIC_ASSERT(sizeof(struct IntegrityProvenanceRequest) == 8, IntegrityProvenanceRequestSize);
STATIC_ASSERT(offsetof(struct IntegrityProvenanceRequest, status) == 5, IntegrityProvenanceRequestStatusOffset);
STATIC_ASSERT(sizeof(struct IntegrityProvenanceResult) == 12, IntegrityProvenanceResultSize);
STATIC_ASSERT(offsetof(struct IntegrityProvenanceResult, status) == 10, IntegrityProvenanceResultStatusOffset);

static struct IntegrityCaptureRequest sRequest;
static MapSectionId sMapSection;
static bool8 sCaptureActive;
static bool8 sGuaranteedThrowArmed;
static bool8 sGuaranteedThrowConsumed;

static void UpdateProvenanceInspection(void)
{
    u32 requestId;
    u8 partyIndex;
    enum Species species;
    MetLocationCode metLocation;

    if (gIntegrityProvenanceRequest.status != INTEGRITY_CAPTURE_PENDING)
        return;

    requestId = gIntegrityProvenanceRequest.requestId;
    partyIndex = gIntegrityProvenanceRequest.partyIndex;
    gIntegrityProvenanceRequest.status = INTEGRITY_CAPTURE_RUNNING;
    gIntegrityProvenanceResult.requestId = requestId;
    gIntegrityProvenanceResult.partyIndex = partyIndex;
    gIntegrityProvenanceResult.species = SPECIES_NONE;
    gIntegrityProvenanceResult.mapSection = MAPSEC_INVALID;
    gIntegrityProvenanceResult.metLocation = MET_LOCATION_INVALID;
    gIntegrityProvenanceResult.error = INTEGRITY_CAPTURE_ERROR_PARTY;

    if (gIntegrityProvenanceRequest.reserved != 0
     || partyIndex >= CalculatePlayerPartyCount())
    {
        gIntegrityProvenanceRequest.status = INTEGRITY_CAPTURE_ERROR;
        gIntegrityProvenanceResult.status = INTEGRITY_CAPTURE_ERROR;
        return;
    }

    species = GetMonData(&gParties[B_TRAINER_PLAYER][partyIndex], MON_DATA_SPECIES);
    metLocation = GetMonData(&gParties[B_TRAINER_PLAYER][partyIndex], MON_DATA_MET_LOCATION);
    gIntegrityProvenanceResult.species = species;
    gIntegrityProvenanceResult.mapSection = DecodeMetLocation(metLocation);
    gIntegrityProvenanceResult.metLocation = metLocation;
    gIntegrityProvenanceResult.error = INTEGRITY_CAPTURE_ERROR_NONE;
    gIntegrityProvenanceRequest.status = INTEGRITY_CAPTURE_SUCCESS;
    gIntegrityProvenanceResult.status = INTEGRITY_CAPTURE_SUCCESS;
}

static bool32 IsReady(void)
{
    return gSaveBlock1Ptr != NULL
        && gSaveBlock2Ptr != NULL
        && gMain.callback1 == CB1_Overworld
        && gMain.callback2 == CB2_Overworld
        && gMain.state == 0
        && !gMain.inBattle
        && !gLinkTransferringData;
}

static void PublishResult(u8 status, enum IntegrityCaptureError error, u16 species, u8 metLocation, u8 partyIndex)
{
    gIntegrityCaptureResult.requestId = sRequest.requestId;
    gIntegrityCaptureResult.mapSection = sMapSection;
    gIntegrityCaptureResult.species = species;
    gIntegrityCaptureResult.metLocation = metLocation;
    gIntegrityCaptureResult.partyIndex = partyIndex;
    gIntegrityCaptureResult.error = error;
    gIntegrityCaptureResult.reserved = 0;
    gIntegrityCaptureResult.status = status;
}

static enum IntegrityCaptureError ValidateRequest(const struct IntegrityCaptureRequest *request)
{
    if (request->species == SPECIES_NONE
     || request->species >= NUM_SPECIES
     || !IsSpeciesEnabled(request->species))
        return INTEGRITY_CAPTURE_ERROR_SPECIES;
    if (request->level == 0 || request->level > MAX_LEVEL)
        return INTEGRITY_CAPTURE_ERROR_LEVEL;
    if (request->ball >= ITEMS_COUNT
     || GetItemPocket(request->ball) != POCKET_POKE_BALLS
     || ItemIdToBallId(request->ball) == BALL_STRANGE)
        return INTEGRITY_CAPTURE_ERROR_BALL;
    if (CalculatePlayerPartyCount() == 0)
        return INTEGRITY_CAPTURE_ERROR_PARTY;
    if (!CheckBagHasItem(request->ball, 1) && !CheckBagHasSpace(request->ball, 1))
        return INTEGRITY_CAPTURE_ERROR_BAG;
    if (request->reserved != 0 || !IsReady())
        return INTEGRITY_CAPTURE_ERROR_NOT_READY;
    return INTEGRITY_CAPTURE_ERROR_NONE;
}

void IntegrityCapture_Update(void)
{
    struct IntegrityCaptureRequest request;
    enum IntegrityCaptureError error;

    UpdateProvenanceInspection();

    if (sCaptureActive || gIntegrityCaptureRequest.status != INTEGRITY_CAPTURE_PENDING)
        return;

    request.requestId = gIntegrityCaptureRequest.requestId;
    request.species = gIntegrityCaptureRequest.species;
    request.ball = gIntegrityCaptureRequest.ball;
    request.level = gIntegrityCaptureRequest.level;
    request.status = gIntegrityCaptureRequest.status;
    request.reserved = gIntegrityCaptureRequest.reserved;
    sRequest = request;
    sMapSection = GetCurrentRegionMapSectionId();

    error = ValidateRequest(&sRequest);
    if (error != INTEGRITY_CAPTURE_ERROR_NONE)
    {
        gIntegrityCaptureRequest.status = INTEGRITY_CAPTURE_ERROR;
        PublishResult(INTEGRITY_CAPTURE_ERROR, error, SPECIES_NONE, MET_LOCATION_INVALID, PARTY_SIZE);
        return;
    }

    if (!CheckBagHasItem(sRequest.ball, 1) && !AddBagItem(sRequest.ball, 1))
    {
        gIntegrityCaptureRequest.status = INTEGRITY_CAPTURE_ERROR;
        PublishResult(INTEGRITY_CAPTURE_ERROR, INTEGRITY_CAPTURE_ERROR_BAG, SPECIES_NONE, MET_LOCATION_INVALID, PARTY_SIZE);
        return;
    }

    PublishResult(INTEGRITY_CAPTURE_RUNNING, INTEGRITY_CAPTURE_ERROR_NONE, SPECIES_NONE, MET_LOCATION_INVALID, PARTY_SIZE);
    gIntegrityCaptureRequest.status = INTEGRITY_CAPTURE_RUNNING;
    sCaptureActive = TRUE;
    sGuaranteedThrowArmed = TRUE;
    sGuaranteedThrowConsumed = FALSE;

    // Open the battle bag on the requested ball. The host still has to enter
    // the bag and use it, so the normal item-consumption and throw scripts run.
    gBagPosition.pocket = POCKET_POKE_BALLS;
    for (u32 i = 0; i < BAG_POKEBALLS_COUNT; i++)
    {
        if (GetBagItemId(POCKET_POKE_BALLS, i) == sRequest.ball)
        {
            gBagPosition.cursorPosition[POCKET_POKE_BALLS] = i;
            gBagPosition.scrollPosition[POCKET_POKE_BALLS] = 0;
            break;
        }
    }

    CreateScriptedWildMon(sRequest.species, sRequest.level, ITEM_NONE);
    CalculateEnemyPartyCount();
    BattleSetup_StartScriptedWildBattle();
}

bool32 IntegrityCapture_ConsumeGuaranteedThrow(enum Item ball)
{
    if (!sCaptureActive || !sGuaranteedThrowArmed || ball != sRequest.ball)
        return FALSE;

    sGuaranteedThrowArmed = FALSE;
    sGuaranteedThrowConsumed = TRUE;
    return TRUE;
}

void IntegrityCapture_Complete(struct Pokemon *caughtMon, u8 partyIndex, bool32 storedInParty)
{
    enum Species species;
    MetLocationCode metLocation;

    if (!sCaptureActive || !sGuaranteedThrowConsumed)
        return;

    species = GetMonData(caughtMon, MON_DATA_SPECIES);
    metLocation = GetMonData(caughtMon, MON_DATA_MET_LOCATION);
    gIntegrityCaptureRequest.status = INTEGRITY_CAPTURE_SUCCESS;
    sGuaranteedThrowArmed = FALSE;
    sGuaranteedThrowConsumed = FALSE;
    sCaptureActive = FALSE;
    PublishResult(
        INTEGRITY_CAPTURE_SUCCESS,
        INTEGRITY_CAPTURE_ERROR_NONE,
        species,
        metLocation,
        storedInParty ? partyIndex : PARTY_SIZE
    );
}

#endif // DEBUG
