Route27_MapScripts::
	.byte 0

Route27_EventScript_Megan::
	trainerbattle_single TRAINER_COOLTRAINER_MEGAN_JOHTO, Route27_Text_CooltrainerfMeganSeen, Route27_Text_CooltrainerfMeganBeaten
	msgbox Route27_Text_CooltrainerfMeganAfter, MSGBOX_AUTOCLOSE
	end

Route27_Text_CooltrainerfMeganSeen:
	.string "It's rare to see anyone come here.\p"
	.string "Are you training on your own?$"

Route27_Text_CooltrainerfMeganBeaten:
	.string "Oh! You're really strong!$"

Route27_Text_CooltrainerfMeganAfter:
	.string "I'm checking out pre- and post-\n"
	.string "evolution POKéMON.\p"
	.string "Evolution really does make\n"
	.string "POKéMON stronger.\p"
	.string "But evolved forms also learn\n"
	.string "moves later on.$"

Route27_EventScript_Brian::
	trainerbattle_single TRAINER_COOLTRAINER_BRIAN_JOHTO, Route27_Text_CooltrainermBrianSeen, Route27_Text_CooltrainermBrianBeaten
	msgbox Route27_Text_CooltrainermBrianAfter, MSGBOX_AUTOCLOSE
	end

Route27_Text_CooltrainermBrianSeen:
	.string "Hm? You're good, aren't you?$"

Route27_Text_CooltrainermBrianBeaten:
	.string "Just as I thought!$"

Route27_Text_CooltrainermBrianAfter:
	.string "A good trainer can recognize other\n"
	.string "good trainers.$"

Route27_EventScript_Jose::
	trainerbattle_single TRAINER_BIRD_KEEPER_JOSE_JOHTO, Route27_Text_BirdKeeperJoseSeen, Route27_Text_BirdKeeperJoseBeaten
	msgbox Route27_Text_BirdKeeperJoseAfter, MSGBOX_AUTOCLOSE
	end

Route27_Text_BirdKeeperJoseSeen:
	.string "Tweet! Tweet! Tetweet!$"

Route27_Text_BirdKeeperJoseBeaten:
	.string "Tweet!$"

Route27_Text_BirdKeeperJoseAfter:
	.string "BIRD KEEPERS like me mimic bird\n"
	.string "whistles to command POKéMON.$"

Route27_EventScript_Blake::
	trainerbattle_single TRAINER_COOLTRAINER_BLAKE_JOHTO, Route27_Text_CooltrainermBlakeSeen, Route27_Text_CooltrainermBlakeBeaten
	msgbox Route27_Text_CooltrainermBlakeAfter, MSGBOX_AUTOCLOSE
	end

Route27_Text_CooltrainermBlakeSeen:
	.string "You look pretty strong.\n"
	.string "Let me battle you!$"

Route27_Text_CooltrainermBlakeBeaten:
	.string "Yow!$"

Route27_Text_CooltrainermBlakeAfter:
	.string "If you prevail on this harsh trek,\n"
	.string "the truth will be revealed!\p"
	.string "Heh, sorry, I just wanted to say\n"
	.string "something cool.$"

Route27_EventScript_Gilbert::
	trainerbattle_single TRAINER_PSYCHIC_M_GILBERT_JOHTO, Route27_Text_PsychicGilbertSeen, Route27_Text_PsychicGilbertBeaten
	msgbox Route27_Text_PsychicGilbertAfter, MSGBOX_AUTOCLOSE
	end

Route27_Text_PsychicGilbertSeen:
	.string "Don't say a thing!\p"
	.string "Let me guess what you're thinking.\p"
	.string "Mmmmmmm…\p"
	.string "I got it! You're on the POKéMON\n"
	.string "LEAGUE challenge!$"

Route27_Text_PsychicGilbertBeaten:
	.string "You're too much!$"

Route27_Text_PsychicGilbertAfter:
	.string "With your skills, you'll do well at\n"
	.string "the LEAGUE.\p"
	.string "That's what my premonition says.$"

Route27_EventScript_Reena::
	trainerbattle_single TRAINER_COOLTRAINER_REENA_JOHTO, Route27_Text_CooltrainerfReenaSeen, Route27_Text_CooltrainerfReenaBeaten
	msgbox Route27_Text_CooltrainerfReenaAfter, MSGBOX_AUTOCLOSE
	end

Route27_Text_CooltrainerfReenaSeen:
	.string "You shouldn't underestimate the\n"
	.string "wild POKéMON in these parts.$"

Route27_Text_CooltrainerfReenaBeaten:
	.string "Oh! You're much too strong!$"

Route27_Text_CooltrainerfReenaAfter:
	.string "You're just a kid, but you're not\n"
	.string "to be underestimated either.$"

Route27_EventScript_Scott::
	trainerbattle_single TRAINER_FISHERMAN_SCOTT_JOHTO, Route27_Text_FisherScottSeen, Route27_Text_FisherScottBeaten
	msgbox Route27_Text_FisherScottAfter, MSGBOX_AUTOCLOSE
	end

Route27_Text_FisherScottSeen:
	.string "I'm feeling great today!\p"
	.string "I feel like I could boot even the\n"
	.string "LEAGUE CHAMP!$"

Route27_Text_FisherScottBeaten:
	.string "No! Not in this battle!$"

Route27_Text_FisherScottAfter:
	.string "Just like in fishing, it's all over\n"
	.string "in POKéMON if you give up.$"
