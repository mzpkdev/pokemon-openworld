EcruteakCity_Gym_MapScripts::
	.byte 0

EcruteakCity_Gym_EventScript_Jeffrey::
	trainerbattle_single TRAINER_SAGE_JEFFREY_JOHTO, SageJeffreySeenText, SageJeffreyBeatenText
	msgbox SageJeffreyAfterBattleText, MSGBOX_AUTOCLOSE
	end

SageJeffreySeenText:
	.string "I spent the spring with my\n"
	.string "POKéMON.\p"
	.string "Then summer, fall, and winter...\p"
	.string "Then spring came again.\n"
	.string "We've been together a long time.$"

SageJeffreyBeatenText:
	.string "Wins and losses--I've known\n"
	.string "them both.$"

SageJeffreyAfterBattleText:
	.string "Where did POKéMON come from?$"

EcruteakCity_Gym_EventScript_Martha::
	trainerbattle_single TRAINER_HEX_MANIAC_MARTHA_JOHTO, MediumMarthaSeenText, MediumMarthaBeatenText
	msgbox MediumMarthaAfterBattleText, MSGBOX_AUTOCLOSE
	end

MediumMarthaSeenText:
	.string "I shall win!$"

MediumMarthaBeatenText:
	.string "I... I... I lost!$"

MediumMarthaAfterBattleText:
	.string "The one who wants to win the\n"
	.string "most is the one who will!$"

EcruteakCity_Gym_EventScript_Ping::
	trainerbattle_single TRAINER_SAGE_PING_JOHTO, SagePingSeenText, SagePingBeatenText
	msgbox SagePingAfterBattleText, MSGBOX_AUTOCLOSE
	end

SagePingSeenText:
	.string "Can you inflict any damage\n"
	.string "on our POKéMON?$"

SagePingBeatenText:
	.string "Ah! Well done!$"

SagePingAfterBattleText:
	.string "We use GHOST-type POKéMON.\p"
	.string "No NORMAL-type attacks can\n"
	.string "harm them!$"

EcruteakCity_Gym_EventScript_Grace::
	trainerbattle_single TRAINER_HEX_MANIAC_GRACE_JOHTO, MediumGraceSeenText, MediumGraceBeatenText
	msgbox MediumGraceAfterBattleText, MSGBOX_AUTOCLOSE
	end

MediumGraceSeenText:
	.string "Stumped by our dark corridors?\n"
	.string "Defeat me if you want a hint!$"

MediumGraceBeatenText:
	.string "Wha-what?$"

MediumGraceAfterBattleText:
	.string "Fine. I'll tell you the secret\n"
	.string "of the shadows.\p"
	.string "The path is right in front of\n"
	.string "your eyes!$"
