Route37_MapScripts::
	.byte 0

Route37_EventScript_TwinAnn::
	trainerbattle_double TRAINER_TWINS_ANN_AND_ANNE_JOHTO, Route37_Text_TwinsAnnAndAnne1_Seen, Route37_Text_TwinsAnnAndAnne1_Beaten, Johto_Text_PairedDoubleNotEnoughMons
	special GetPlayerBigGuyGirlString
	msgbox Route37_Text_TwinsAnnAndAnne1_After, MSGBOX_DEFAULT
	release
	end

Route37_Text_TwinsAnnAndAnne1_Seen:
	.string "ANN: ANNE and I are in this\n"
	.string "together!$"

Route37_Text_TwinsAnnAndAnne1_Beaten:
	.string "ANN & ANNE: Nnn… A little too\n"
	.string "strong.$"

Route37_Text_TwinsAnnAndAnne1_After:
	.string "ANN: I can tell what my sister and\n"
	.string "my POKéMON are thinking.$"

Route37_EventScript_TwinAnne::
	trainerbattle_double TRAINER_TWINS_ANN_AND_ANNE_JOHTO, Route37_Text_TwinsAnnAndAnne2_Seen, Route37_Text_TwinsAnnAndAnne2_Beaten, Johto_Text_PairedDoubleNotEnoughMons
	special GetPlayerBigGuyGirlString
	msgbox Route37_Text_TwinsAnnAndAnne2_After, MSGBOX_DEFAULT
	release
	end

Route37_Text_TwinsAnnAndAnne2_Seen:
	.string "ANNE: ANN and I are in this\n"
	.string "together!$"

Route37_Text_TwinsAnnAndAnne2_Beaten:
	.string "ANN & ANNE: Nnn… A little too\n"
	.string "strong.$"

Route37_Text_TwinsAnnAndAnne2_After:
	.string "ANNE: We share the same feelings as\n"
	.string "our POKéMON.$"

Route37_EventScript_Greg::
	trainerbattle_single TRAINER_PSYCHIC_M_GREG_JOHTO, Route37_Text_PsychicGreg_Seen, Route37_Text_PsychicGreg_Beaten
	msgbox Route37_Text_PsychicGreg_After, MSGBOX_AUTOCLOSE
	end

Route37_Text_PsychicGreg_Seen:
	.string "POKéMON can't do a thing if they are\n"
	.string "asleep.\p"
	.string "I'll show you how scary that is!$"

Route37_Text_PsychicGreg_Beaten:
	.string "I lost. That's pretty sad…$"

Route37_Text_PsychicGreg_After:
	.string "Putting POKéMON to sleep or paralyz-\n"
	.string "ing them are good battle techniques.$"
