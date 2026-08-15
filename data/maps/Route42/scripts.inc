Route42_MapScripts::
	.byte 0

Route42_EventScript_Shane::
	trainerbattle_single TRAINER_POKEMANIAC_SHANE_JOHTO, Route42_Text_PokemaniacShaneSeen, Route42_Text_PokemaniacShaneBeaten
	msgbox Route42_Text_PokemaniacShaneAfter, MSGBOX_AUTOCLOSE
	end

Route42_Text_PokemaniacShaneSeen:
	.string "HEY!\p"
	.string "This is my secret place!\n"
	.string "Get lost, you outsider!$"

Route42_Text_PokemaniacShaneBeaten:
	.string "I should have used my\n"
	.string "MOON STONE…$"

Route42_Text_PokemaniacShaneAfter:
	.string "You're working on a POKéDEX?\p"
	.string "Wow, you must know some\n"
	.string "pretty rare POKéMON!\p"
	.string "May I please see it?\n"
	.string "Please?$"

Route42_EventScript_Ben::
	trainerbattle_single TRAINER_HIKER_BENJAMIN_JOHTO, Route42_Text_HikerBenjaminSeen, Route42_Text_HikerBenjaminBeaten
	msgbox Route42_Text_HikerBenjaminAfter, MSGBOX_AUTOCLOSE
	end

Route42_Text_HikerBenjaminSeen:
	.string "Ah, it's good to be outside!\n"
	.string "I feel so free!$"

Route42_Text_HikerBenjaminBeaten:
	.string "Gahahah! That was a good\n"
	.string "battle!$"

Route42_Text_HikerBenjaminAfter:
	.string "Losing feels insignificant\n"
	.string "if you look up at the big sky!$"
