MtMortar_2F_MapScripts::
	.byte 0

MtMortar_2F_EventScript_Nerd::
	trainerbattle_single TRAINER_SUPER_NERD_HUGH_JOHTO, MtMortar_2F_Text_SupernerdHughSeen, MtMortar_2F_Text_SupernerdHughBeaten
	msgbox MtMortar_2F_Text_SupernerdHughAfter, MSGBOX_AUTOCLOSE
	end

MtMortar_2F_Text_SupernerdHughSeen:
	.string "Yo! MARKUS!$"

MtMortar_2F_Text_SupernerdHughBeaten:
	.string "Sorry, my mistake.\n"
	.string "I misjudged you.$"

MtMortar_2F_Text_SupernerdHughAfter:
	.string "I'm investigating MT.MORTAR,\n"
	.string "but my pal's gone AWOL.\p"
	.string "Have you seen a trainer who\n"
	.string "has a SLOWPOKE that can use\l"
	.string "STRENGTH?$"
