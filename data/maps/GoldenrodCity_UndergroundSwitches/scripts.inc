GoldenrodCity_UndergroundSwitches_MapScripts::
	.byte 0

GoldenrodCity_UndergroundSwitches_EventScript_Duncan::
	trainerbattle_single TRAINER_BURGLAR_DUNCAN_JOHTO, GoldenrodUnderground_Text_BurglarDuncanSeen, GoldenrodUnderground_Text_BurglarDuncanBeaten
	msgbox GoldenrodUnderground_Text_BurglarDuncanAfter, MSGBOX_AUTOCLOSE
	end

GoldenrodUnderground_Text_BurglarDuncanSeen:
	.string "Fork over your goodies!$"

GoldenrodUnderground_Text_BurglarDuncanBeaten:
	.string "Mercy!$"

GoldenrodUnderground_Text_BurglarDuncanAfter:
	.string "Steal and sell! That's basic in\n"
	.string "crime, kid!$"

GoldenrodCity_UndergroundSwitches_EventScript_Eddie::
	trainerbattle_single TRAINER_BURGLAR_EDDIE_JOHTO, GoldenrodUnderground_Text_BurglarEddieSeen, GoldenrodUnderground_Text_BurglarEddieBeaten
	msgbox GoldenrodUnderground_Text_BurglarEddieAfter, MSGBOX_AUTOCLOSE
	end

GoldenrodUnderground_Text_BurglarEddieSeen:
	.string "They ditched this project before they\n"
	.string "finished.\p"
	.string "I'm searching for leftover loot.$"

GoldenrodUnderground_Text_BurglarEddieBeaten:
	.string "Over the top!$"

GoldenrodUnderground_Text_BurglarEddieAfter:
	.string "UNDERGROUND WAREHOUSE?\p"
	.string "What do you want to go there for?\p"
	.string "There's nothing down there.$"
