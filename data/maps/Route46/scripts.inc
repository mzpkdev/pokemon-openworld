Route46_MapScripts::
	.byte 0

Route46_EventScript_Ted::
	trainerbattle_single TRAINER_CAMPER_TED_JOHTO, Route46_Text_CamperTedSeen, Route46_Text_CamperTedBeaten
	msgbox Route46_Text_CamperTedAfterBattle, MSGBOX_AUTOCLOSE
	end

Route46_Text_CamperTedSeen:
	.string "I'm raising POKéMON too!\p"
	.string "Will you battle with me?$"

Route46_Text_CamperTedBeaten:
	.string "Wha…?$"

Route46_Text_CamperTedAfterBattle:
	.string "I did my best but came up\n"
	.string "short.\p"
	.string "No excuses--I admit I lost.$"

Route46_EventScript_Erin::
	trainerbattle_single TRAINER_PICNICKER_ERIN_JOHTO, Route46_Text_PicnickerErinSeen, Route46_Text_PicnickerErinBeaten
	msgbox Route46_Text_PicnickerErinAfterBattle, MSGBOX_AUTOCLOSE
	end

Route46_Text_PicnickerErinSeen:
	.string "I raise POKéMON too!\p"
	.string "Will you battle with me?$"

Route46_Text_PicnickerErinBeaten:
	.string "Oh, rats!$"

Route46_Text_PicnickerErinAfterBattle:
	.string "I've been to many GYMS, but the\n"
	.string "GYM in GOLDENROD is my favorite.\p"
	.string "It's filled with pretty flowers!$"

Route46_EventScript_Bailey::
	trainerbattle_single TRAINER_HIKER_BAILEY_JOHTO, Route46_Text_HikerBaileySeen, Route46_Text_HikerBaileyBeaten
	msgbox Route46_Text_HikerBaileyAfterBattle, MSGBOX_AUTOCLOSE
	end

Route46_Text_HikerBaileySeen:
	.string "Awright! I'll show you the\n"
	.string "power of mountain POKéMON!$"

Route46_Text_HikerBaileyBeaten:
	.string "Mercy! You showed me your\n"
	.string "power!$"

Route46_Text_HikerBaileyAfterBattle:
	.string "It's over. I don't mind.\n"
	.string "We HIKERS are like that.$"
