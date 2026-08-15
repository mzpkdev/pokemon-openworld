CianwoodGym_MapScripts::
	.byte 0

CianwoodGym_EventScript_Nob::
	trainerbattle_single TRAINER_BLACK_BELT_NOB_JOHTO, CianwoodGym_Text_BlackbeltNobSeen, CianwoodGym_Text_BlackbeltNobBeaten
	msgbox CianwoodGym_Text_BlackbeltNobAfter, MSGBOX_AUTOCLOSE
	end

CianwoodGym_Text_BlackbeltNobSeen:
	.string "Words are useless.\n"
	.string "Let your fists do the talking!$"

CianwoodGym_Text_BlackbeltNobBeaten:
	.string "…$"

CianwoodGym_Text_BlackbeltNobAfter:
	.string "I lost! I'm speechless!$"

CianwoodGym_EventScript_Yoshi::
	trainerbattle_single TRAINER_BLACK_BELT_YOSHI_JOHTO, CianwoodGym_Text_BlackbeltYoshiSeen, CianwoodGym_Text_BlackbeltYoshiBeaten
	msgbox CianwoodGym_Text_BlackbeltYoshiAfter, MSGBOX_AUTOCLOSE
	end

CianwoodGym_Text_BlackbeltYoshiSeen:
	.string "My POKéMON and I are bound togeth-\n"
	.string "er by friendship.\p"
	.string "Our bond will never be broken!$"

CianwoodGym_Text_BlackbeltYoshiBeaten:
	.string "This isn't real!$"

CianwoodGym_Text_BlackbeltYoshiAfter:
	.string "You seem to have a strong bond\n"
	.string "with your POKéMON too!$"

CianwoodGym_EventScript_Lao::
	trainerbattle_single TRAINER_BLACK_BELT_LAO_JOHTO, CianwoodGym_Text_BlackbeltLaoSeen, CianwoodGym_Text_BlackbeltLaoBeaten
	msgbox CianwoodGym_Text_BlackbeltLaoAfter, MSGBOX_AUTOCLOSE
	end

CianwoodGym_Text_BlackbeltLaoSeen:
	.string "We martial artists fear nothing!$"

CianwoodGym_Text_BlackbeltLaoBeaten:
	.string "That's shocking!$"

CianwoodGym_Text_BlackbeltLaoAfter:
	.string "Fighting POKéMON are afraid of\n"
	.string "psychics…$"

CianwoodGym_EventScript_Lung::
	trainerbattle_single TRAINER_BLACK_BELT_LUNG_JOHTO, CianwoodGym_Text_BlackbeltLungSeen, CianwoodGym_Text_BlackbeltLungBeaten
	msgbox CianwoodGym_Text_BlackbeltLungAfter, MSGBOX_AUTOCLOSE
	end

CianwoodGym_Text_BlackbeltLungSeen:
	.string "My raging fists will shatter your\n"
	.string "POKéMON!$"

CianwoodGym_Text_BlackbeltLungBeaten:
	.string "I got shattered!$"

CianwoodGym_Text_BlackbeltLungAfter:
	.string "My POKéMON lost…\n"
	.string "My… my pride is shattered…$"
