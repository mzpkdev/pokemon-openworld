#include "global.h"

// Complete linked structural evidence generated from the active purpose's live
// ARM DWARF measurement, including private packet types that cannot be named here.
const u32 gSaveAbiEvidence[] =
{
    0x53414249, // "SABI"
    1,
#define SAVE_ABI_VALUE(value) value,
#include "save_abi_evidence.inc"
#undef SAVE_ABI_VALUE
};
