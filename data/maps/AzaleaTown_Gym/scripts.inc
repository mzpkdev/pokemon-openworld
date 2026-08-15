AzaleaTown_Gym_MapScripts::
	.byte 0

AzaleaTown_Gym_EventScript_Amy::
	trainerbattle_double TRAINER_TWINS_AMY_AND_MAY_JOHTO, AzaleaTown_Gym_Text_TwinsAmyMay1Seen, AzaleaTown_Gym_Text_TwinsAmyMay1Beaten, Johto_Text_PairedDoubleNotEnoughMons
	special GetPlayerBigGuyGirlString
	msgbox AzaleaTown_Gym_Text_TwinsAmyMay1After, MSGBOX_DEFAULT
	release
	end

AzaleaTown_Gym_Text_TwinsAmyMay1Seen:
	.string "AMY: Hi! Are you challenging\n"
	.string "the LEADER? No way!$"

AzaleaTown_Gym_Text_TwinsAmyMay1Beaten:
	.string "AMY & MAY: Oh, double\n"
	.string "goodness!$"

AzaleaTown_Gym_Text_TwinsAmyMay1After:
	.string "AMY: You're really strong!\p"
	.string "But BUGSY's even stronger!\n"
	.string "His SCYTHER's CUT almost\l"
	.string "always makes critical hits!$"

AzaleaTown_Gym_EventScript_May::
	trainerbattle_double TRAINER_TWINS_AMY_AND_MAY_JOHTO, AzaleaTown_Gym_Text_TwinsAmyMay2Seen, AzaleaTown_Gym_Text_TwinsAmyMay2Beaten, Johto_Text_PairedDoubleNotEnoughMons
	special GetPlayerBigGuyGirlString
	msgbox AzaleaTown_Gym_Text_TwinsAmyMay2After, MSGBOX_DEFAULT
	release
	end

AzaleaTown_Gym_Text_TwinsAmyMay2Seen:
	.string "MAY: You want to see the\n"
	.string "LEADER? Good luck!\p"
	.string "BUGSY is so strong!\n"
	.string "His SCYTHER's CUT always\l"
	.string "seems to crit!$"

AzaleaTown_Gym_Text_TwinsAmyMay2Beaten:
	.string "AMY & MAY: Oh, double\n"
	.string "goodness!$"

AzaleaTown_Gym_Text_TwinsAmyMay2After:
	.string "MAY: Our bug POKéMON lost!\n"
	.string "Oh, what a shame.\p"
	.string "BUGSY's won't lose though!\p"
	.string "His PINECO makes short work\n"
	.string "of ROCK-type POKéMON!$"
