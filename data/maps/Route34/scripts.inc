Route34_MapScripts::
	.byte 0

Route34_EventScript_YoungsterSamuel::
	trainerbattle_single TRAINER_YOUNGSTER_SAMUEL_JOHTO, Route34_Text_YoungsterSamuel_Seen, Route34_Text_YoungsterSamuel_Beaten
	msgbox Route34_Text_YoungsterSamuel_After, MSGBOX_AUTOCLOSE
	end

Route34_Text_YoungsterSamuel_Seen:
	.string "Hey! I'm looking for MANKEY!$"

Route34_Text_YoungsterSamuel_Beaten:
	.string "Beaten by a passing stranger!$"

Route34_Text_YoungsterSamuel_After:
	.string "I'm going to train even harder.\p"
	.string "After all, I'm trying to become\n"
	.string "a GYM LEADER.$"
