Route36_MapScripts::
	.byte 0

Route36_EventScript_Mark::
	trainerbattle_single TRAINER_PSYCHIC_M_MARK_JOHTO, Route36_Text_PsychicMarkSeen, Route36_Text_PsychicMarkBeaten
	msgbox Route36_Text_PsychicMarkAfter, MSGBOX_AUTOCLOSE
	end

Route36_Text_PsychicMarkSeen:
	.string "I'm going to read your thoughts!$"

Route36_Text_PsychicMarkBeaten:
	.string "I misread you!$"

Route36_Text_PsychicMarkAfter:
	.string "I'd be strong if only I could tell\n"
	.string "what my opponent was thinking.$"

Route36_EventScript_Schoolboy::
	trainerbattle_single TRAINER_SCHOOL_KID_ALAN_JOHTO, Route36_Text_SchoolboyAlan1Seen, Route36_Text_SchoolboyAlan1Beaten
	msgbox Route36_Text_SchoolboyAlanAfter, MSGBOX_AUTOCLOSE
	end

Route36_Text_SchoolboyAlan1Seen:
	.string "Thanks to my studies, I'm ready\n"
	.string "for any POKéMON!$"

Route36_Text_SchoolboyAlan1Beaten:
	.string "Oops! Computation error?$"

Route36_Text_SchoolboyAlanAfter:
	.string "Darn. I study five hours a day too.\p"
	.string "There's more to learning than just\n"
	.string "reading books.$"
