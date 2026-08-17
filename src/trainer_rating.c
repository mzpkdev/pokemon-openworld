#include "global.h"
#include "event_data.h"
#include "regional_fact.h"
#include "trainer_rating.h"

u16 TrainerRating_CalculateBadge(u16 badgeCount)
{
    u32 rating = 0;
    u16 maximumBadges = 0;

    for (u32 i = 0; i < gTrainerRatingBadgeSegmentCount; i++)
    {
        const struct TrainerRatingBadgeSegment *segment = &gTrainerRatingBadgeSegments[i];
        u16 segmentEnd = segment->firstBadgeOrdinal + segment->badgeCount - 1;

        if (maximumBadges < segmentEnd)
            maximumBadges = segmentEnd;
    }
    if (badgeCount > maximumBadges)
        badgeCount = maximumBadges;

    for (u32 i = 0; i < gTrainerRatingBadgeSegmentCount; i++)
    {
        const struct TrainerRatingBadgeSegment *segment = &gTrainerRatingBadgeSegments[i];
        u16 earnedBadges = 0;

        if (badgeCount >= segment->firstBadgeOrdinal)
            earnedBadges = badgeCount - segment->firstBadgeOrdinal + 1;
        if (earnedBadges > segment->badgeCount)
            earnedBadges = segment->badgeCount;
        rating += earnedBadges * segment->value;
    }

    return rating;
}

u16 TrainerRating_GetBadge(void)
{
    u16 badgeCount = 0;

    for (u32 i = 0; i < gTrainerRatingSourceCount; i++)
    {
        const struct TrainerRatingSource *source = &gTrainerRatingSources[i];

        if (source->kind == TRAINER_RATING_SOURCE_BADGE
         && (RegionalFact_Get(source->fact)
          || (source->legacyFallbackFlag != TRAINER_RATING_LEGACY_FLAG_NONE
           && FlagGet(source->legacyFallbackFlag))))
            badgeCount++;
    }

    return TrainerRating_CalculateBadge(badgeCount);
}

u16 TrainerRating_GetStory(void)
{
    u32 rating = 0;

    for (u32 i = 0; i < gTrainerRatingSourceCount; i++)
    {
        const struct TrainerRatingSource *source = &gTrainerRatingSources[i];

        if (source->kind == TRAINER_RATING_SOURCE_STORY && RegionalFact_Get(source->fact))
            rating += source->value;
    }

    return rating;
}

u16 TrainerRating_Get(void)
{
    return TrainerRating_GetBadge() + TrainerRating_GetStory();
}
