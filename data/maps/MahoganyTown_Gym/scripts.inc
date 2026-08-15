MahoganyTown_Gym_MapScripts::
	.byte 0

MahoganyTown_Gym_EventScript_Clarissa::
	trainerbattle_single TRAINER_EXPERT_CLARISSA_JOHTO, MahoganyTown_Gym_Text_SkierClarissaSeen, MahoganyTown_Gym_Text_SkierClarissaBeaten
	msgbox MahoganyTown_Gym_Text_SkierClarissaAfter, MSGBOX_AUTOCLOSE
	end

MahoganyTown_Gym_Text_SkierClarissaSeen:
	.string "Check out my parallel turn!$"

MahoganyTown_Gym_Text_SkierClarissaBeaten:
	.string "No! You made me wipe out!$"

MahoganyTown_Gym_Text_SkierClarissaAfter:
	.string "I shouldn't have been bragging\n"
	.string "about my skiing…$"

MahoganyTown_Gym_EventScript_Brad::
	trainerbattle_single TRAINER_EXPERT_BRAD_JOHTO, MahoganyTown_Gym_Text_BoarderBradSeen, MahoganyTown_Gym_Text_BoarderBradBeaten
	msgbox MahoganyTown_Gym_Text_BoarderBradAfter, MSGBOX_AUTOCLOSE
	end

MahoganyTown_Gym_Text_BoarderBradSeen:
	.string "This GYM has a slippery floor.\p"
	.string "It's fun, isn't it?\p"
	.string "But hey--we're not playing\n"
	.string "games here!$"

MahoganyTown_Gym_Text_BoarderBradBeaten:
	.string "Do you see how serious we are?$"

MahoganyTown_Gym_Text_BoarderBradAfter:
	.string "This GYM is great.\n"
	.string "I love boarding with my\l"
	.string "POKéMON!$"

MahoganyTown_Gym_EventScript_Ronald::
	trainerbattle_single TRAINER_EXPERT_RONALD_JOHTO, MahoganyTown_Gym_Text_BoarderRonaldSeen, MahoganyTown_Gym_Text_BoarderRonaldBeaten
	msgbox MahoganyTown_Gym_Text_BoarderRonaldAfter, MSGBOX_AUTOCLOSE
	end

MahoganyTown_Gym_Text_BoarderRonaldSeen:
	.string "I'll freeze your POKéMON,\n"
	.string "so you can't do a thing!$"

MahoganyTown_Gym_Text_BoarderRonaldBeaten:
	.string "Darn. I couldn't do a thing.$"

MahoganyTown_Gym_Text_BoarderRonaldAfter:
	.string "I think there's a move a\n"
	.string "POKéMON can use while it's\l"
	.string "frozen.$"

MahoganyTown_Gym_EventScript_Douglas::
	trainerbattle_single TRAINER_EXPERT_DOUGLAS_JOHTO, MahoganyTown_Gym_Text_BoarderDouglasSeen, MahoganyTown_Gym_Text_BoarderDouglasBeaten
	msgbox MahoganyTown_Gym_Text_BoarderDouglasAfter, MSGBOX_AUTOCLOSE
	end

MahoganyTown_Gym_Text_BoarderDouglasSeen:
	.string "I know PRYCE's secret.$"

MahoganyTown_Gym_Text_BoarderDouglasBeaten:
	.string "OK. I'll tell you PRYCE's secret.$"

MahoganyTown_Gym_Text_BoarderDouglasAfter:
	.string "The secret behind PRYCE's power…\p"
	.string "He meditates under a waterfall\n"
	.string "daily to strengthen his mind\l"
	.string "and body.$"

MahoganyTown_Gym_EventScript_Roxanne::
	trainerbattle_single TRAINER_EXPERT_ROXANNE_JOHTO, MahoganyTown_Gym_Text_SkierRoxanneSeen, MahoganyTown_Gym_Text_SkierRoxanneBeaten
	msgbox MahoganyTown_Gym_Text_SkierRoxanneAfter, MSGBOX_AUTOCLOSE
	end

MahoganyTown_Gym_Text_SkierRoxanneSeen:
	.string "To get to PRYCE, our GYM LEADER,\n"
	.string "you need to think before you skate.$"

MahoganyTown_Gym_Text_SkierRoxanneBeaten:
	.string "I wouldn't lose to you in skiing!$"

MahoganyTown_Gym_Text_SkierRoxanneAfter:
	.string "If you don't skate with precision,\n"
	.string "you won't get far in this GYM.$"
