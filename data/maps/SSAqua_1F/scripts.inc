SSAqua_1F_MapScripts::
	.byte 0

SSAqua_B1F_EventScript_Jeff::
	trainerbattle_single TRAINER_SAILOR_JEFF_JOHTO, SSAqua_B1F_Text_SailorJeffSeen, SSAqua_B1F_Text_SailorJeffBeaten
	msgbox SSAqua_B1F_Text_SailorJeffAfter, MSGBOX_AUTOCLOSE
	end

SSAqua_B1F_Text_SailorJeffSeen:
	.string "Nothing beats a battle when\n"
	.string "I'm on my break.$"

SSAqua_B1F_Text_SailorJeffBeaten:
	.string "Win or lose, my break's over!$"

SSAqua_B1F_Text_SailorJeffAfter:
	.string "I guess I can't win if I don't\n"
	.string "get serious.$"
