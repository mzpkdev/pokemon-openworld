Route32_MapScripts::
	.byte 0

Route32_EventScript_YoungsterAlbert::
	trainerbattle_single TRAINER_YOUNGSTER_ALBERT_JOHTO, Route32_Text_YoungsterAlbert_Seen, Route32_Text_YoungsterAlbert_Beaten
	msgbox Route32_Text_YoungsterAlbert_After, MSGBOX_AUTOCLOSE
	end

Route32_Text_YoungsterAlbert_Seen:
	.string "I haven't seen you around before.\n"
	.string "So you think you are pretty tough?$"

Route32_Text_YoungsterAlbert_Beaten:
	.string "You're strong!$"

Route32_Text_YoungsterAlbert_After:
	.string "I'm going to try to be the\n"
	.string "best with my favorites.\p"
	.string "I'm not using the same tough\n"
	.string "POKéMON as everyone else.$"

Route32_EventScript_PicnickerLiz::
	trainerbattle_single TRAINER_PICNICKER_LIZ_JOHTO, Route32_Text_PicnickerLiz1_Seen, Route32_Text_PicnickerLiz1_Beaten
	msgbox Route32_Text_PicnickerLiz1_After, MSGBOX_AUTOCLOSE
	end

Route32_Text_PicnickerLiz1_Seen:
	.string "Uh-huh. Yeah, and you know…\p"
	.string "Pardon? Battle? I'm on the phone.\n"
	.string "Oh, all right. But make it fast.$"

Route32_Text_PicnickerLiz1_Beaten:
	.string "Oh! I've got to relieve\n"
	.string "my anger!$"

Route32_Text_PicnickerLiz1_After:
	.string "I was having a nice chat too.$"

Route32_EventScript_CamperRoland::
	trainerbattle_single TRAINER_CAMPER_ROLAND_JOHTO, Route32_Text_CamperRoland_Seen, Route32_Text_CamperRoland_Beaten
	msgbox Route32_Text_CamperRoland_After, MSGBOX_AUTOCLOSE
	end

Route32_Text_CamperRoland_Seen:
	.string "That glance… It's intriguing.$"

Route32_Text_CamperRoland_Beaten:
	.string "Hmmm. This is disappointing.$"

Route32_Text_CamperRoland_After:
	.string "If you don't want to battle,\n"
	.string "just avoid eye contact.$"

Route32_EventScript_FisherRalph::
	trainerbattle_single TRAINER_FISHERMAN_RALPH_JOHTO, Route32_Text_FisherRalph1_Seen, Route32_Text_FisherRalph1_Beaten
	msgbox Route32_Text_FisherRalph1_After, MSGBOX_AUTOCLOSE
	end

Route32_Text_FisherRalph1_Seen:
	.string "I'm really good at both\n"
	.string "fishing and POKéMON.\p"
	.string "I'm not about to lose to any kid!$"

Route32_Text_FisherRalph1_Beaten:
	.string "Tch! I tried to rush\n"
	.string "things…$"

Route32_Text_FisherRalph1_After:
	.string "Fishing is a lifelong\n"
	.string "passion.\p"
	.string "POKéMON are lifelong friends!$"

Route32_EventScript_FisherHenry::
	trainerbattle_single TRAINER_FISHERMAN_HENRY_JOHTO, Route32_Text_FisherHenry_Seen, Route32_Text_FisherHenry_Beaten
	msgbox Route32_Text_FisherHenry_After, MSGBOX_AUTOCLOSE
	end

Route32_Text_FisherHenry_Seen:
	.string "My POKéMON? Freshly caught!$"

Route32_Text_FisherHenry_Beaten:
	.string "SPLASH?$"

Route32_Text_FisherHenry_After:
	.string "Freshly caught POKéMON are\n"
	.string "no match for properly raised ones.$"

Route32_EventScript_FisherJustin::
	trainerbattle_single TRAINER_FISHERMAN_JUSTIN_JOHTO, Route32_Text_FisherJustin_Seen, Route32_Text_FisherJustin_Beaten
	msgbox Route32_Text_FisherJustin_After, MSGBOX_AUTOCLOSE
	end

Route32_Text_FisherJustin_Seen:
	.string "Whoa!\p"
	.string "You made me lose that fish!$"

Route32_Text_FisherJustin_Beaten:
	.string "Sploosh!$"

Route32_Text_FisherJustin_After:
	.string "Calm, collected… The essence of\n"
	.string "fishing and POKéMON is the same.$"

Route32_EventScript_YoungsterGordon::
	trainerbattle_single TRAINER_YOUNGSTER_GORDON_JOHTO, Route32_Text_YoungsterGordon_Seen, Route32_Text_YoungsterGordon_Beaten
	msgbox Route32_Text_YoungsterGordon_After, MSGBOX_AUTOCLOSE
	end

Route32_Text_YoungsterGordon_Seen:
	.string "I found some good POKéMON\n"
	.string "in the grass!\p"
	.string "I think they'll do it for me!$"

Route32_Text_YoungsterGordon_Beaten:
	.string "Darn. I thought I could win.$"

Route32_Text_YoungsterGordon_After:
	.string "The grass is full of\n"
	.string "clingy things.$"

Route32_EventScript_BirdkeeperPeter::
	trainerbattle_single TRAINER_BIRD_KEEPER_PETER_JOHTO, Route32_Text_BirdKeeperPeter_Seen, Route32_Text_BirdKeeperPeter_Beaten
	msgbox Route32_Text_BirdKeeperPeter_After, MSGBOX_AUTOCLOSE
	end

Route32_Text_BirdKeeperPeter_Seen:
	.string "That BADGE! It's from VIOLET CITY!\n"
	.string "You beat FALKNER?$"

Route32_Text_BirdKeeperPeter_Beaten:
	.string "I know what my weaknesses are.$"

Route32_Text_BirdKeeperPeter_After:
	.string "I should train again at the\n"
	.string "GYM in VIOLET CITY.$"
