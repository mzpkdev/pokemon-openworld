BurnedTower_1F_MapScripts::
	.byte 0

BurnedTower_1F_EventScript_Nard::
	trainerbattle_single TRAINER_FIREBREATHER_NARD_JOHTO, BurnedTower_Text_NardSeen, BurnedTower_Text_NardBeaten
	msgbox BurnedTower_Text_NardAfter, MSGBOX_AUTOCLOSE
	end

BurnedTower_Text_NardSeen:
	.string "Don't worry!\p"
	.string "We fire-breathers know the true\n"
	.string "power of fire better than anyone!$"

BurnedTower_Text_NardBeaten:
	.string "Thanks for such a heated battle!$"

BurnedTower_Text_NardAfter:
	.string "The reason this tower's burned is\n"
	.string "that it was hit by lightning.\p"
	.string "The fire I'm breathing is tiny\n"
	.string "in comparison...$"

BurnedTower_1F_EventScript_Richardo::
	trainerbattle_single TRAINER_BURGLAR_RICHARDO_JOHTO, BurnedTower_Text_RichardoSeen, BurnedTower_Text_RichardoBeaten
	msgbox BurnedTower_Text_RichardoAfter, MSGBOX_AUTOCLOSE
	end

BurnedTower_Text_RichardoSeen:
	.string "I'm practicing my stealing in the\n"
	.string "BURNED TOWER! Don't try\l"
	.string "this at home!$"

BurnedTower_Text_RichardoBeaten:
	.string "Pfffffffffffffff.$"

BurnedTower_Text_RichardoAfter:
	.string "Maybe a life of crime isn't for\n"
	.string "me...$"
