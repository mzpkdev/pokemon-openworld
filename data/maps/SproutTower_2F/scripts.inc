SproutTower_2F_MapScripts::
	.byte 0

SproutTower_2F_EventScript_SageEdmond::
	trainerbattle_single TRAINER_SAGE_EDMOND_JOHTO, SproutTower_Text_SageEdmond_Seen, SproutTower_Text_SageEdmond_Beaten
	msgbox SproutTower_Text_SageEdmond_AfterBattle, MSGBOX_AUTOCLOSE
	end

SproutTower_Text_SageEdmond_Seen:
	.string "…Sway like leaves in the wind…$"

SproutTower_Text_SageEdmond_Beaten:
	.string "Oh, I'm weak!$"

SproutTower_Text_SageEdmond_AfterBattle:
	.string "I tried to copy BELLSPROUT's\n"
	.string "gentle movements for battle…\p"
	.string "But I didn't train well enough.$"

SproutTower_2F_EventScript_SageNico::
	trainerbattle_single TRAINER_SAGE_NICO_JOHTO, SproutTower_Text_SageNico_Seen, SproutTower_Text_SageNico_Beaten
	msgbox SproutTower_Text_SageNico_AfterBattle, MSGBOX_AUTOCLOSE
	end

SproutTower_Text_SageNico_Seen:
	.string "However hard we battle,\n"
	.string "the TOWER will stand strong.$"

SproutTower_Text_SageNico_Beaten:
	.string "I fought hard but I'm too weak.$"

SproutTower_Text_SageNico_AfterBattle:
	.string "The flexible pillar protects the\n"
	.string "TOWER, even from earthquakes.$"
