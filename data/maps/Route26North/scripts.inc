Route26North_MapScripts::
	.byte 0

Route26_EventScript_Beth::
	trainerbattle_single TRAINER_COOLTRAINER_BETH_JOHTO, Route26_Text_CooltrainerfBethSeen, Route26_Text_CooltrainerfBethBeaten
	msgbox Route26_Text_CooltrainerfBethAfter, MSGBOX_AUTOCLOSE
	end

Route26_Text_CooltrainerfBethSeen:
	.string "I lost to a trainer named {RIVAL}.\p"
	.string "He was really strong, but…\p"
	.string "It was as if he absolutely had to\n"
	.string "win at any cost.\p"
	.string "I felt sorry for his POKéMON.$"

Route26_Text_CooltrainerfBethBeaten:
	.string "POKéMON aren't tools of war.$"

Route26_Text_CooltrainerfBethAfter:
	.string "POKéMON are in-valuable, lifelong\n"
	.string "partners.$"
