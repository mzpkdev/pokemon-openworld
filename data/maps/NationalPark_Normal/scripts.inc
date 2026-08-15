NationalPark_Normal_MapScripts::
	.byte 0

NationalPark_Normal_EventScript_Beverly::
	trainerbattle_single TRAINER_PARASOL_LADY_BEVERLY_JOHTO, NationalPark_Normal_Text_PokefanFBeverly1_Seen, NationalPark_Normal_Text_PokefanFBeverly1_Beaten
	msgbox NationalPark_Normal_Text_PokefanFBeverly_After, MSGBOX_AUTOCLOSE
	end

NationalPark_Normal_Text_PokefanFBeverly1_Seen:
	.string "My POKéMON are simply darling.\p"
	.string "Let me tell you how proud my\n"
	.string "darlings make me.$"

NationalPark_Normal_Text_PokefanFBeverly1_Beaten:
	.string "I can beat you in pride, but…$"

NationalPark_Normal_Text_PokefanFBeverly_After:
	.string "I must say, your POKéMON are quite\n"
	.string "cute, too.$"

NationalPark_Normal_EventScript_Jack::
	trainerbattle_single TRAINER_SCHOOL_KID_JACK_JOHTO, NationalPark_Normal_Text_SchoolboyJack1_Seen, NationalPark_Normal_Text_SchoolboyJack1_Beaten
	msgbox NationalPark_Normal_Text_SchoolboyJack_After, MSGBOX_AUTOCLOSE
	end

NationalPark_Normal_Text_SchoolboyJack1_Seen:
	.string "The world of POKéMON is deep.\p"
	.string "There are still lots of things we\n"
	.string "don't know.\p"
	.string "But I know more than you do!$"

NationalPark_Normal_Text_SchoolboyJack1_Beaten:
	.string "Wha-wha-what?$"

NationalPark_Normal_Text_SchoolboyJack_After:
	.string "There is a lot to learn.\p"
	.string "For example…\p"
	.string "There are 50 kinds of TMs.\p"
	.string "Traded POKéMON level up faster.$"

NationalPark_Normal_EventScript_Krise::
	trainerbattle_single TRAINER_LASS_KRISE_JOHTO, NationalPark_Normal_Text_LassKrise_Seen, NationalPark_Normal_Text_LassKrise_Beaten
	msgbox NationalPark_Normal_Text_LassKrise_After, MSGBOX_AUTOCLOSE
	end

NationalPark_Normal_Text_LassKrise_Seen:
	.string "Hello? Why are you staring at me?\p"
	.string "Oh, a battle?$"

NationalPark_Normal_Text_LassKrise_Beaten:
	.string "…Hmmm…$"

NationalPark_Normal_Text_LassKrise_After:
	.string "I thought you were staring at me\n"
	.string "because I'm cute!$"

NationalPark_Normal_EventScript_William::
	trainerbattle_single TRAINER_POKEFAN_WILLIAM_JOHTO, NationalPark_Normal_Text_PokefanmWilliam_Seen, NationalPark_Normal_Text_PokefanmWilliam_Beaten
	msgbox NationalPark_Normal_Text_PokefanmWilliam_After, MSGBOX_AUTOCLOSE
	end

NationalPark_Normal_Text_PokefanmWilliam_Seen:
	.string "We adore our POKéMON, even if they\n"
	.string "dislike us.\p"
	.string "That's what being a FAN is about.$"

NationalPark_Normal_Text_PokefanmWilliam_Beaten:
	.string "M-my POKéMON!$"

NationalPark_Normal_Text_PokefanmWilliam_After:
	.string "I lost the battle, but my POKéMON win\n"
	.string "the prize for being most lovely.$"
