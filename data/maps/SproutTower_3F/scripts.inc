SproutTower_3F_MapScripts::
	.byte 0

SproutTower_3F_EventScript_SageNeal::
	trainerbattle_single TRAINER_SAGE_NEAL_JOHTO, SproutTower_Text_SageNeal_Seen, SproutTower_Text_SageNeal_Beaten
	msgbox SproutTower_Text_SageNeal_AfterBattle, MSGBOX_AUTOCLOSE
	end

SproutTower_Text_SageNeal_Seen:
	.string "The ELDER's HM lights even\n"
	.string "pitch-black darkness.$"

SproutTower_Text_SageNeal_Beaten:
	.string "It is my head that is bright!$"

SproutTower_Text_SageNeal_AfterBattle:
	.string "Let there be light on your\n"
	.string "journey.$"

SproutTower_3F_EventScript_SageJin::
	trainerbattle_single TRAINER_SAGE_JIN_JOHTO, SproutTower_Text_SageJin_Seen, SproutTower_Text_SageJin_Beaten
	msgbox SproutTower_Text_SageJin_AfterBattle, MSGBOX_AUTOCLOSE
	end

SproutTower_Text_SageJin_Seen:
	.string "I train to find enlightenment\n"
	.string "in POKéMON!$"

SproutTower_Text_SageJin_Beaten:
	.string "My training is incomplete…$"

SproutTower_Text_SageJin_AfterBattle:
	.string "As POKéMON grow stronger,\n"
	.string "so does the trainer.\p"
	.string "No, wait. As the trainer\n"
	.string "grows stronger, so do the\l"
	.string "POKéMON.$"

SproutTower_3F_EventScript_SageTroy::
	trainerbattle_single TRAINER_SAGE_TROY_JOHTO, SproutTower_Text_SageTroy_Seen, SproutTower_Text_SageTroy_Beaten
	msgbox SproutTower_Text_SageTroy_AfterBattle, MSGBOX_AUTOCLOSE
	end

SproutTower_Text_SageTroy_Seen:
	.string "Let me see how much you trust\n"
	.string "your POKéMON.$"

SproutTower_Text_SageTroy_Beaten:
	.string "Yes, your trust is real!$"

SproutTower_Text_SageTroy_AfterBattle:
	.string "It is not far to the ELDER.$"
