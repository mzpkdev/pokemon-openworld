#include "global.h"
#include "frontier_pass.h"
#include "test/test.h"
#include "constants/region_map_sections.h"

TEST("Frontier Pass does not alias wide map section IDs")
{
    EXPECT(IsFrontierPassMapSection(MAPSEC_BATTLE_FRONTIER));
    EXPECT(IsFrontierPassMapSection(MAPSEC_ARTISAN_CAVE));
    EXPECT(!IsFrontierPassMapSection(MAPSEC_BATTLE_FRONTIER + 0x100));
    EXPECT(!IsFrontierPassMapSection(MAPSEC_ARTISAN_CAVE + 0x100));
}
