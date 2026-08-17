#ifndef GUARD_TRAINER_RATING_H
#define GUARD_TRAINER_RATING_H

#include "global.h"
#include "constants/flags.h"
#include "regional_fact.h"

#define TRAINER_RATING_LEGACY_FLAG_NONE 0xFFFF

enum TrainerRatingSourceKind
{
    TRAINER_RATING_SOURCE_BADGE,
    TRAINER_RATING_SOURCE_STORY,
};

struct TrainerRatingSource
{
    enum RegionalFact fact;
    u16 legacyFallbackFlag;
    u8 value;
    u8 kind;
};

struct TrainerRatingBadgeSegment
{
    u8 firstBadgeOrdinal;
    u8 badgeCount;
    u8 value;
};

// These generated arrays are defined alongside the normal wild-encounter
// authority so every ordinary-encounter consumer uses the same rating inputs.
extern const struct TrainerRatingSource gTrainerRatingSources[];
extern const u16 gTrainerRatingSourceCount;
extern const struct TrainerRatingBadgeSegment gTrainerRatingBadgeSegments[];
extern const u16 gTrainerRatingBadgeSegmentCount;

u16 TrainerRating_CalculateBadge(u16 badgeCount);
u16 TrainerRating_GetBadge(void);
u16 TrainerRating_GetStory(void);
u16 TrainerRating_Get(void);

#endif // GUARD_TRAINER_RATING_H
