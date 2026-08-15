SSAqua_B1F_MapScripts::
	.byte 0

SSAqua_B1F_EventScript_Wai::
	trainerbattle_single TRAINER_BLACK_BELT_WAI_JOHTO, SSAqua_B1F_Text_BlackbeltWaiSeen, SSAqua_B1F_Text_BlackbeltWaiBeaten
	msgbox SSAqua_B1F_Text_BlackbeltWaiAfter, MSGBOX_AUTOCLOSE
	end

SSAqua_B1F_Text_BlackbeltWaiSeen:
	.string "I'm building up my legs by\n"
	.string "bracing\p"
	.string "against the ship's rocking!$"

SSAqua_B1F_Text_BlackbeltWaiBeaten:
	.string "Rocked and rolled over!$"

SSAqua_B1F_Text_BlackbeltWaiAfter:
	.string "I couldn't find the KARATE KING\n"
	.string "in JOHTO.\p"
	.string "He's supposed to be training in\n"
	.string "a cave somewhere.$"

SSAqua_B1F_EventScript_Nate::
	trainerbattle_single TRAINER_SCHOOL_KID_NATE_JOHTO, SSAqua_B1F_Text_SchoolboyNateSeen, SSAqua_B1F_Text_SchoolboyNateBeaten
	msgbox SSAqua_B1F_Text_SchoolboyNateAfter, MSGBOX_AUTOCLOSE
	end

SSAqua_B1F_Text_SchoolboyNateSeen:
	.string "Do you know the RUINS OF ALPH?$"

SSAqua_B1F_Text_SchoolboyNateBeaten:
	.string "Yaargh!$"

SSAqua_B1F_Text_SchoolboyNateAfter:
	.string "Radios pick up strange signals\n"
	.string "inside the RUINS.$"

SSAqua_B1F_EventScript_Shirley::
	trainerbattle_single TRAINER_EXPERT_SHIRLEY_JOHTO, SSAqua_B1F_Text_TeacherShirleySeen, SSAqua_B1F_Text_TeacherShirleyBeaten
	msgbox SSAqua_B1F_Text_TeacherShirleyAfter, MSGBOX_AUTOCLOSE
	end

SSAqua_B1F_Text_TeacherShirleySeen:
	.string "Don't lay a finger on my\n"
	.string "students!$"

SSAqua_B1F_Text_TeacherShirleyBeaten:
	.string "Aaack!$"

SSAqua_B1F_Text_TeacherShirleyAfter:
	.string "We're on a field trip to the\n"
	.string "RUINS outside VIOLET.$"

SSAqua_B1F_EventScript_Ricky::
	trainerbattle_single TRAINER_SCHOOL_KID_RICKY_JOHTO, SSAqua_B1F_Text_SchoolboyRickySeen, SSAqua_B1F_Text_SchoolboyRickyBeaten
	msgbox SSAqua_B1F_Text_SchoolboyRickyAfter, MSGBOX_AUTOCLOSE
	end

SSAqua_B1F_Text_SchoolboyRickySeen:
	.string "There are some odd stone panels\n"
	.string "in the RUINS OF ALPH.$"

SSAqua_B1F_Text_SchoolboyRickyBeaten:
	.string "I was done in!$"

SSAqua_B1F_Text_SchoolboyRickyAfter:
	.string "I read that there are four of\n"
	.string "those stone panels.$"

SSAqua_B1F_EventScript_Debra::
	trainerbattle_single TRAINER_PICNICKER_DEBRA_JOHTO, SSAqua_B1F_Text_PicnickerDebraSeen, SSAqua_B1F_Text_PicnickerDebraBeaten
	msgbox SSAqua_B1F_Text_PicnickerDebraAfter, MSGBOX_AUTOCLOSE
	end

SSAqua_B1F_Text_PicnickerDebraSeen:
	.string "I'm so bored. Want to battle?$"

SSAqua_B1F_Text_PicnickerDebraBeaten:
	.string "Yow! You're too strong!$"

SSAqua_B1F_Text_PicnickerDebraAfter:
	.string "SAFFRON, CELADON… I hear there\n"
	.string "are many big cities in KANTO.$"

SSAqua_B1F_EventScript_Kenneth::
	trainerbattle_single TRAINER_SAILOR_KENNETH_JOHTO, SSAqua_B1F_Text_SailorKennethSeen, SSAqua_B1F_Text_SailorKennethBeaten
	msgbox SSAqua_B1F_Text_SailorKennethAfter, MSGBOX_AUTOCLOSE
	end

SSAqua_B1F_Text_SailorKennethSeen:
	.string "I'm a sailor man!\p"
	.string "But I'm training POKéMON, so I\n"
	.string "can become the CHAMP!$"

SSAqua_B1F_Text_SailorKennethBeaten:
	.string "My lack of training is obvious…$"

SSAqua_B1F_Text_SailorKennethAfter:
	.string "Eight BADGES! They must prove\n"
	.string "that you've beaten\p"
	.string "GYM LEADERS.\p"
	.string "No wonder you're so good!$"

SSAqua_B1F_EventScript_Jonah::
	trainerbattle_single TRAINER_FISHERMAN_JONAH_JOHTO, SSAqua_B1F_Text_FisherJonahSeen, SSAqua_B1F_Text_FisherJonahBeaten
	msgbox SSAqua_B1F_Text_FisherJonahAfter, MSGBOX_AUTOCLOSE
	end

SSAqua_B1F_Text_FisherJonahSeen:
	.string "Even though we're out on the\n"
	.string "sea, I can't fish!\p"
	.string "This is boring! Let's battle!$"

SSAqua_B1F_Text_FisherJonahBeaten:
	.string "I… I'm not bored anymore…$"

SSAqua_B1F_Text_FisherJonahAfter:
	.string "I plan to fish off\n"
	.string "VERMILION's pier.$"

SSAqua_B1F_EventScript_Fritz::
	trainerbattle_single TRAINER_JUGGLER_FRITZ_JOHTO, SSAqua_B1F_Text_JugglerFritzSeen, SSAqua_B1F_Text_JugglerFritzBeaten
	msgbox SSAqua_B1F_Text_JugglerFritzAfter, MSGBOX_AUTOCLOSE
	end

SSAqua_B1F_Text_JugglerFritzSeen:
	.string "Urrf… I'm seasick!$"

SSAqua_B1F_Text_JugglerFritzBeaten:
	.string "I can't move anymore…$"

SSAqua_B1F_Text_JugglerFritzAfter:
	.string "No more ships for me.\n"
	.string "Next time,\p"
	.string "I'm taking the MAGNET TRAIN.$"

SSAqua_B1F_EventScript_Garrett::
	trainerbattle_single TRAINER_SAILOR_GARRETT_JOHTO, SSAqua_B1F_Text_SailorGarrettSeen, SSAqua_B1F_Text_SailorGarrettBeaten
	msgbox SSAqua_B1F_Text_SailorGarrettAfter, MSGBOX_AUTOCLOSE
	end

SSAqua_B1F_Text_SailorGarrettSeen:
	.string "This is where we sailors work!$"

SSAqua_B1F_Text_SailorGarrettBeaten:
	.string "I lost on my home field…$"

SSAqua_B1F_Text_SailorGarrettAfter:
	.string "We get different passengers\n"
	.string "from VERMILION CITY to\p"
	.string "OLIVINE CITY.$"
