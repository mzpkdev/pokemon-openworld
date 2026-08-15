DragonsDen_Cavern_MapScripts::
	.byte 0

DragonsDen_Cavern_EventScript_Darin::
	trainerbattle_single TRAINER_DRAGON_TAMER_DARIN_JOHTO, DragonsDen_Cavern_Text_CooltrainermDarinSeen, DragonsDen_Cavern_Text_CooltrainermDarinBeaten
	msgbox DragonsDen_Cavern_Text_CooltrainermDarinAfter, MSGBOX_AUTOCLOSE
	end

DragonsDen_Cavern_Text_CooltrainermDarinSeen:
	.string "You! How dare you enter\n"
	.string "uninvited!$"

DragonsDen_Cavern_Text_CooltrainermDarinBeaten:
	.string "S-strong!$"

DragonsDen_Cavern_Text_CooltrainermDarinAfter:
	.string "The SHRINE ahead is home to the\n"
	.string "MASTER of our dragon-user clan.\p"
	.string "You're not allowed to just go in!$"

DragonsDen_Cavern_EventScript_TwinPia::
	trainerbattle_double TRAINER_TWINS_LEA_AND_PIA_JOHTO, DragonsDen_Cavern_Text_TwinsLeaandPia2Seen, DragonsDen_Cavern_Text_TwinsLeaandPia2Beaten, Johto_Text_PairedDoubleNotEnoughMons
	special GetPlayerBigGuyGirlString
	msgbox DragonsDen_Cavern_Text_TwinsLeaandPia2After, MSGBOX_DEFAULT
	release
	end

DragonsDen_Cavern_Text_TwinsLeaandPia2Seen:
	.string "Who are you?$"

DragonsDen_Cavern_Text_TwinsLeaandPia2Beaten:
	.string "Meanie.$"

DragonsDen_Cavern_Text_TwinsLeaandPia2After:
	.string "We'll tell on you.\p"
	.string "MASTER will be angry with you.$"

DragonsDen_Cavern_EventScript_TwinLea::
	trainerbattle_double TRAINER_TWINS_LEA_AND_PIA_JOHTO, DragonsDen_Cavern_Text_TwinsLeaandPia1Seen, DragonsDen_Cavern_Text_TwinsLeaandPia1Beaten, Johto_Text_PairedDoubleNotEnoughMons
	special GetPlayerBigGuyGirlString
	msgbox DragonsDen_Cavern_Text_TwinsLeaandPia1After, MSGBOX_DEFAULT
	release
	end

DragonsDen_Cavern_Text_TwinsLeaandPia1Seen:
	.string "It's a stranger we don't know.$"

DragonsDen_Cavern_Text_TwinsLeaandPia1Beaten:
	.string "Ouchies.$"

DragonsDen_Cavern_Text_TwinsLeaandPia1After:
	.string "It was like having to battle\n"
	.string "LANCE.$"
