GoldenrodCity_Gym_MapScripts::
	.byte 0

GoldenrodCity_Gym_EventScript_Carrie::
	trainerbattle_single TRAINER_LASS_CARRIE_JOHTO, GoldenrodCity_Gym_Text_LassCarrieSeen, GoldenrodCity_Gym_Text_LassCarrieBeaten
	msgbox GoldenrodCity_Gym_Text_LassCarrieAfter, MSGBOX_AUTOCLOSE
	end

GoldenrodCity_Gym_Text_LassCarrieSeen:
	.string "Don't let my POKéMON's cute looks\n"
	.string "fool you.\p"
	.string "They can whip you!$"

GoldenrodCity_Gym_Text_LassCarrieBeaten:
	.string "Darn… I thought you were weak…$"

GoldenrodCity_Gym_Text_LassCarrieAfter:
	.string "Do my POKéMON think I'm cute?$"

GoldenrodCity_Gym_EventScript_Victoria::
	trainerbattle_single TRAINER_BEAUTY_VICTORIA_JOHTO, GoldenrodCity_Gym_Text_BeautyVictoriaSeen, GoldenrodCity_Gym_Text_BeautyVictoriaBeaten
	msgbox GoldenrodCity_Gym_Text_BeautyVictoriaAfter, MSGBOX_AUTOCLOSE
	end

GoldenrodCity_Gym_Text_BeautyVictoriaSeen:
	.string "Oh, you are a cute little trainer!\p"
	.string "I like you, but I won't hold back!$"

GoldenrodCity_Gym_Text_BeautyVictoriaBeaten:
	.string "Let's see… Oops, it's over?$"

GoldenrodCity_Gym_Text_BeautyVictoriaAfter:
	.string "Wow, you must be good to beat me!\n"
	.string "Keep it up!$"

GoldenrodCity_Gym_EventScript_Samantha::
	trainerbattle_single TRAINER_BEAUTY_SAMANTHA_JOHTO, GoldenrodCity_Gym_Text_BeautySamanthaSeen, GoldenrodCity_Gym_Text_BeautySamanthaBeaten
	msgbox GoldenrodCity_Gym_Text_BeautySamanthaAfter, MSGBOX_AUTOCLOSE
	end

GoldenrodCity_Gym_Text_BeautySamanthaSeen:
	.string "Give it your best shot, or I'll take\n"
	.string "you down!$"

GoldenrodCity_Gym_Text_BeautySamanthaBeaten:
	.string "No! Oh, MEOWTH, I'm so sorry!$"

GoldenrodCity_Gym_Text_BeautySamanthaAfter:
	.string "I taught MEOWTH moves for taking on\n"
	.string "any type…$"

GoldenrodCity_Gym_EventScript_Bridget::
	trainerbattle_single TRAINER_LASS_BRIDGET_JOHTO, GoldenrodCity_Gym_Text_LassBridgetSeen, GoldenrodCity_Gym_Text_LassBridgetBeaten
	msgbox GoldenrodCity_Gym_Text_LassBridgetAfter, MSGBOX_AUTOCLOSE
	end

GoldenrodCity_Gym_Text_LassBridgetSeen:
	.string "I like cute POKéMON better than\n"
	.string "strong POKéMON.\p"
	.string "But I have strong and cute POKéMON!$"

GoldenrodCity_Gym_Text_LassBridgetBeaten:
	.string "Oh, no, no, no!$"

GoldenrodCity_Gym_Text_LassBridgetAfter:
	.string "I'm trying to beat WHITNEY, but…\n"
	.string "It's depressing.\p"
	.string "I'm okay! If I lose, I'll just try\n"
	.string "harder next time!$"
