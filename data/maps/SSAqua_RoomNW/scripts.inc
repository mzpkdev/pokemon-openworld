SSAqua_RoomNW_MapScripts::
	.byte 0

SSAqua_RoomNW_EventScript_Edward::
	trainerbattle_single TRAINER_GENTLEMAN_EDWARD_JOHTO, SSAqua_RoomNW_Text_GentlemanEdwardSeen, SSAqua_RoomNW_Text_GentlemanEdwardBeaten
	msgbox SSAqua_RoomNW_Text_GentlemanEdwardAfterBattle, MSGBOX_AUTOCLOSE
	end

SSAqua_RoomNW_Text_GentlemanEdwardSeen:
	.string "Oh, no. I've lost something\n"
	.string "that's very important.$"

SSAqua_RoomNW_Text_GentlemanEdwardBeaten:
	.string "I… I can't find it…$"

SSAqua_RoomNW_Text_GentlemanEdwardAfterBattle:
	.string "I give up. You don't have to\n"
	.string "look.\p"
	.string "Just forget about it!$"

SSAqua_RoomNW_EventScript_Corey::
	trainerbattle_single TRAINER_FIREBREATHER_COREY_JOHTO, SSAqua_RoomNW_Text_BurglarCoreySeen, SSAqua_RoomNW_Text_BurglarCoreyBeaten
	msgbox SSAqua_RoomNW_Text_BurglarCoreyAfterBattle, MSGBOX_AUTOCLOSE
	end

SSAqua_RoomNW_Text_BurglarCoreySeen:
	.string "Yeehaw! Lucky!$"

SSAqua_RoomNW_Text_BurglarCoreyBeaten:
	.string "How unlucky! I lost!$"

SSAqua_RoomNW_Text_BurglarCoreyAfterBattle:
	.string "I found a pretty coin here.\p"
	.string "Someone must have lost it…$"
