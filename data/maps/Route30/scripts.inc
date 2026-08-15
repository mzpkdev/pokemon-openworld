Route30_MapScripts::
	.byte 0

Route30_EventScript_Bugcatcher_Don::
	trainerbattle_single TRAINER_BUG_CATCHER_DON_JOHTO, Route30_Text_BugCatcherDonSeen, Route30_Text_BugCatcherDonBeaten
	msgbox Route30_Text_BugCatcherDonAfter, MSGBOX_AUTOCLOSE
	end

Route30_Text_BugCatcherDonSeen:
	.string "Instead of a bug POKéMON,\n"
	.string "I found a trainer!$"

Route30_Text_BugCatcherDonBeaten:
	.string "Argh! You're too strong!$"

Route30_Text_BugCatcherDonAfter:
	.string "I ran out of POKé BALLS while\n"
	.string "I was catching POKéMON.\p"
	.string "I should've bought some more…$"

Route30_EventScript_Youngster_Mikey::
	trainerbattle_single TRAINER_YOUNGSTER_MIKEY_JOHTO, Route30_Text_YoungsterMikeySeen, Route30_Text_YoungsterMikeyBeaten
	msgbox Route30_Text_YoungsterMikeyAfter, MSGBOX_AUTOCLOSE
	end

Route30_Text_YoungsterMikeySeen:
	.string "You're a POKéMON trainer,\n"
	.string "right?\p"
	.string "Then you have to battle!$"

Route30_Text_YoungsterMikeyBeaten:
	.string "That's strange.\n"
	.string "I won before.$"

Route30_Text_YoungsterMikeyAfter:
	.string "Becoming a good trainer is\n"
	.string "really tough.\p"
	.string "I'm going to battle other\n"
	.string "people to get better.$"
