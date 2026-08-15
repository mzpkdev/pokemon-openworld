Route47_MapScripts::
	.byte 0

Route47_EventScript_Hiker::
	trainerbattle_single TRAINER_HIKER_DEVIN_JOHTO, Route47_Text_HikerSeen, Route47_Text_HikerBeaten
	msgbox Route47_Text_HikerAfter, MSGBOX_AUTOCLOSE
	end

Route47_Text_HikerSeen:
	.string "Longing for others is...\n"
	.string "what it is. \p"
	.string "But battles are battles,\n"
	.string "so let's go!$"

Route47_Text_HikerBeaten:
	.string "Wahaha!$"

Route47_Text_HikerAfter:
	.string "After a battle you should always leave\n"
	.string "with a parting laugh!$"

Route47_EventScript_Camper::
	trainerbattle_single TRAINER_CAMPER_GRANT_JOHTO, Route47_Text_CamperSeen, Route47_Text_CamperBeaten
	msgbox Route47_Text_CamperAfter, MSGBOX_AUTOCLOSE
	end

Route47_Text_CamperSeen:
	.string "I'm not good with large crowds, so\n"
	.string "I'm camping out here with my\l"
	.string "POKéMON!$"

Route47_Text_CamperBeaten:
	.string "I should be headed deeper into the\n"
	.string "mountain I guess...$"

Route47_Text_CamperAfter:
	.string "See ya!$"

Route47_EventScript_Kae::
	trainerbattle_double TRAINER_YOUNG_COUPLE_THOM_AND_KAE_JOHTO, Route47_Text_Couple1Seen, Route47_Text_Couple1Beaten, Johto_Text_PairedDoubleNotEnoughMons
	special GetPlayerBigGuyGirlString
	msgbox Route47_Text_Couple1After2, MSGBOX_AUTOCLOSE
	end

Route47_Text_Couple1Seen:
	.string "THOM: One plus one is two. But the\n"
	.string "two of us together is much\l"
	.string "stronger!\p"
	.string "KAE: The two of us aren't just some\n"
	.string "boring pair!$"

Route47_Text_Couple1Beaten:
	.string "THOM: That wasn't what I expected.\l"
	.string "KAE: You're unusual too!$"

Route47_Text_Couple1After2:
	.string "KAE: I figured you were an ordinary\n"
	.string "lone trainer. Boy was I wrong!$"

Route47_EventScript_Thom::
	trainerbattle_double TRAINER_YOUNG_COUPLE_THOM_AND_KAE_JOHTO, Route47_Text_Couple1Seen, Route47_Text_Couple1Beaten, Johto_Text_PairedDoubleNotEnoughMons
	special GetPlayerBigGuyGirlString
	msgbox Route47_Text_Couple1After1, MSGBOX_AUTOCLOSE
	end

Route47_Text_Couple1After1:
	.string "THOM: It seems your power is\n"
	.string "impossible to predict!$"

Route47_EventScript_Duff::
	trainerbattle_double TRAINER_YOUNG_COUPLE_DUFF_AND_EDA_JOHTO, Route47_Text_Couple2Seen, Route47_Text_Couple2Beaten, Johto_Text_PairedDoubleNotEnoughMons
	special GetPlayerBigGuyGirlString
	msgbox Route47_Text_Couple2After1, MSGBOX_AUTOCLOSE
	end

Route47_Text_Couple2Seen:
	.string "DUFF: Watching over my girlfriend\n"
	.string "makes my heart soar!\p"
	.string "EDA: My heart's feelings for my\n"
	.string "boyfriend are as wide and deep\l"
	.string "the ocean!$"

Route47_Text_Couple2Beaten:
	.string "DUFF: I was no match for you...\l"
	.string "EDA: You are really something...$"

Route47_Text_Couple2After1:
	.string "DUFF: Thank you for the awe-\n"
	.string "inspiring battle! Bye!$"

Route47_EventScript_Eda::
	trainerbattle_double TRAINER_YOUNG_COUPLE_DUFF_AND_EDA_JOHTO, Route47_Text_Couple2Seen, Route47_Text_Couple2Beaten, Johto_Text_PairedDoubleNotEnoughMons
	msgbox Route47_Text_Couple2After2, MSGBOX_AUTOCLOSE
	end

Route47_Text_Couple2After2:
	.string "EDA: You should really find a\n"
	.string "wonderful partner, too!$"
