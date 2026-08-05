#ifndef GUARD_RECORD_MIXING_H
#define GUARD_RECORD_MIXING_H

struct PlayerHallRecords
{
    struct RankingHall1P onePlayer[HALL_FACILITIES_COUNT][FRONTIER_LVL_MODE_COUNT];
    struct RankingHall2P twoPlayers[FRONTIER_LVL_MODE_COUNT];
};

void RecordMixingPlayerSpotTriggered(void);
void GetPlayerHallRecords(struct PlayerHallRecords *dst);
void CopyTVShowsForRecordMixing(TVShow *dest, const TVShow *src, u32 count);

#endif //GUARD_RECORD_MIXING_H
