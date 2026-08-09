#ifndef GUARD_INTEGRITY_CAPTURE_H
#define GUARD_INTEGRITY_CAPTURE_H

#ifdef DEBUG

enum IntegrityCaptureStatus
{
    INTEGRITY_CAPTURE_IDLE,
    INTEGRITY_CAPTURE_PENDING,
    INTEGRITY_CAPTURE_RUNNING,
    INTEGRITY_CAPTURE_SUCCESS,
    INTEGRITY_CAPTURE_ERROR,
};

enum IntegrityCaptureError
{
    INTEGRITY_CAPTURE_ERROR_NONE,
    INTEGRITY_CAPTURE_ERROR_SPECIES,
    INTEGRITY_CAPTURE_ERROR_LEVEL,
    INTEGRITY_CAPTURE_ERROR_BALL,
    INTEGRITY_CAPTURE_ERROR_PARTY,
    INTEGRITY_CAPTURE_ERROR_BAG,
    INTEGRITY_CAPTURE_ERROR_NOT_READY,
};

struct IntegrityCaptureRequest
{
    u32 requestId;
    u16 species;
    u16 ball;
    u8 level;
    u8 status;
    u16 reserved;
};

struct IntegrityCaptureResult
{
    u32 requestId;
    u16 mapSection;
    u16 species;
    u8 metLocation;
    u8 partyIndex;
    u8 status;
    u8 error;
    u32 reserved;
};

struct IntegrityProvenanceRequest
{
    u32 requestId;
    u8 partyIndex;
    u8 status;
    u16 reserved;
};

struct IntegrityProvenanceResult
{
    u32 requestId;
    u16 species;
    u16 mapSection;
    u8 metLocation;
    u8 partyIndex;
    u8 status;
    u8 error;
};

extern volatile struct IntegrityCaptureRequest gIntegrityCaptureRequest;
extern volatile struct IntegrityCaptureResult gIntegrityCaptureResult;
extern volatile struct IntegrityProvenanceRequest gIntegrityProvenanceRequest;
extern volatile struct IntegrityProvenanceResult gIntegrityProvenanceResult;

void IntegrityCapture_Update(void);
bool32 IntegrityCapture_ConsumeGuaranteedThrow(enum Item ball);
void IntegrityCapture_Complete(struct Pokemon *caughtMon, u8 partyIndex, bool32 storedInParty);

#endif // DEBUG

#endif // GUARD_INTEGRITY_CAPTURE_H
