BlackthornCity_Gym_MapScripts::
	.byte 0

BlackthornGym_EventScript_Mike::
	trainerbattle_single TRAINER_DRAGON_TAMER_MIKE_JOHTO, BlackthornGym_Text_CooltrainermMikeSeenText, BlackthornGym_Text_CooltrainermMikeBeatenText
	msgbox BlackthornGym_Text_CooltrainermMikeAfterBattleText, MSGBOX_AUTOCLOSE
	end

BlackthornGym_Text_CooltrainermMikeSeenText:
	.string "My chance of losing? Not even one\n"
	.string "percent!$"

BlackthornGym_Text_CooltrainermMikeBeatenText:
	.string "That's odd.$"

BlackthornGym_Text_CooltrainermMikeAfterBattleText:
	.string "I know my short-comings now.\p"
	.string "Thanks for showing me!$"

BlackthornGym_EventScript_Paul::
	trainerbattle_single TRAINER_DRAGON_TAMER_PAUL_JOHTO, BlackthornGym_Text_CooltrainermPaulSeenText, BlackthornGym_Text_CooltrainermPaulBeatenText
	msgbox BlackthornGym_Text_CooltrainermPaulAfterBattleText, MSGBOX_AUTOCLOSE
	end

BlackthornGym_Text_CooltrainermPaulSeenText:
	.string "Your first battle against dragons?\p"
	.string "I'll show you how tough they are!$"

BlackthornGym_Text_CooltrainermPaulBeatenText:
	.string "My dragon POKéMON lost?$"

BlackthornGym_Text_CooltrainermPaulAfterBattleText:
	.string "LANCE told you that he'd like to\n"
	.string "see you again?\p"
	.string "Not a chance!$"

BlackthornGym_EventScript_Lola::
	trainerbattle_single TRAINER_COOLTRAINER_LOLA_JOHTO, BlackthornGym_Text_CooltrainerfLolaSeenText, BlackthornGym_Text_CooltrainerfLolaBeatenText
	msgbox BlackthornGym_Text_CooltrainerfLolaAfterBattleText, MSGBOX_AUTOCLOSE
	end

BlackthornGym_Text_CooltrainerfLolaSeenText:
	.string "Dragons are sacred POKéMON.\p"
	.string "They are full of life energy.\p"
	.string "If you're not serious, you won't\n"
	.string "be able to beat them.$"

BlackthornGym_Text_CooltrainerfLolaBeatenText:
	.string "Way to go!$"

BlackthornGym_Text_CooltrainerfLolaAfterBattleText:
	.string "Dragons are weak against DRAGON-\n"
	.string "type moves.$"

BlackthornGym_EventScript_Fran::
	trainerbattle_single TRAINER_COOLTRAINER_FRAN_JOHTO, BlackthornGym_Text_CooltrainerfFranSeenText, BlackthornGym_Text_CooltrainerfFranBeatenText
	msgbox BlackthornGym_Text_CooltrainerfFranAfterBattleText, MSGBOX_AUTOCLOSE
	end

BlackthornGym_Text_CooltrainerfFranSeenText:
	.string "I can't allow a nameless trainer\n"
	.string "past me!\p"
	.string "CLAIR would be livid if I did!$"

BlackthornGym_Text_CooltrainerfFranBeatenText:
	.string "Awww… I lost…$"

BlackthornGym_Text_CooltrainerfFranAfterBattleText:
	.string "Uh-oh… CLAIR is going to be mad…$"

BlackthornGym_EventScript_Cody::
	trainerbattle_single TRAINER_DRAGON_TAMER_CODY_JOHTO, BlackthornGym_Text_CooltrainermCodySeenText, BlackthornGym_Text_CooltrainermCodyBeatenText
	msgbox BlackthornGym_Text_CooltrainermCodyAfterBattleText, MSGBOX_AUTOCLOSE
	end

BlackthornGym_Text_CooltrainermCodySeenText:
	.string "I just got access to use DRAGON-\n"
	.string "type POKéMON!$"

BlackthornGym_Text_CooltrainermCodyBeatenText:
	.string "Rats! If only I had a DRAGONITE!$"

BlackthornGym_Text_CooltrainermCodyAfterBattleText:
	.string "Members of our dragon-user clan\n"
	.string "can use dragon POKéMON only after\l"
	.string "our MASTER allows it.$"
