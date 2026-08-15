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

AzaleaTown_Gym_EventScript_Benny::
	trainerbattle_single TRAINER_BUG_CATCHER_BENNY_JOHTO, AzaleaTown_Gym_Text_BugCatcherBennySeen, AzaleaTown_Gym_Text_BugCatcherBennyBeaten
	msgbox AzaleaTown_Gym_Text_BugCatcherBennyAfter, MSGBOX_AUTOCLOSE
	end

AzaleaTown_Gym_Text_BugCatcherBennySeen:
	.string "Bug POKéMON evolve young. So they\n"
	.string "get stronger that much faster.$"

AzaleaTown_Gym_Text_BugCatcherBennyBeaten:
	.string "Just evolving isn't enough!$"

AzaleaTown_Gym_Text_BugCatcherBennyAfter:
	.string "POKéMON become stronger\n"
	.string "if they evolve. Really!$"

AzaleaTown_Gym_EventScript_Josh::
	trainerbattle_single TRAINER_BUG_CATCHER_JOSH_JOHTO, AzaleaTown_Gym_Text_BugCatcherJoshSeen, AzaleaTown_Gym_Text_BugCatcherJoshBeaten
	msgbox AzaleaTown_Gym_Text_BugCatcherJoshAfter, MSGBOX_AUTOCLOSE
	end

AzaleaTown_Gym_Text_BugCatcherJoshSeen:
	.string "You saved all the SLOWPOKE?\n"
	.string "Whew, you're mighty!\p"
	.string "But my grown-up POKéMON are\n"
	.string "pretty tough too!$"

AzaleaTown_Gym_Text_BugCatcherJoshBeaten:
	.string "Urrgggh!$"

AzaleaTown_Gym_Text_BugCatcherJoshAfter:
	.string "I guess I should teach them\n"
	.string "better moves…$"

AzaleaTown_Gym_EventScript_Al::
	trainerbattle_single TRAINER_BUG_CATCHER_AL_JOHTO, AzaleaTown_Gym_Text_BugCatcherAlSeen, AzaleaTown_Gym_Text_BugCatcherAlBeaten
	msgbox AzaleaTown_Gym_Text_BugCatcherAlAfter, MSGBOX_AUTOCLOSE
	end

AzaleaTown_Gym_Text_BugCatcherAlSeen:
	.string "Bug POKéMON are cool and tough!\n"
	.string "I'll prove it to you!$"

AzaleaTown_Gym_Text_BugCatcherAlBeaten:
	.string "You proved how tough you are…$"

AzaleaTown_Gym_Text_BugCatcherAlAfter:
	.string "They're so cool, but most girls\n"
	.string "don't like bug POKéMON.\p"
	.string "I don't know why…$"
