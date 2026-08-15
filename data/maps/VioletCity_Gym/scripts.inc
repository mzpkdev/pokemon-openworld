VioletCity_Gym_MapScripts::
	.byte 0

VioletCity_Gym_EventScript_Abe::
	trainerbattle_single TRAINER_BIRD_KEEPER_ABE_JOHTO, VioletGym_Text_BirdKeeperAbe_Seen, VioletGym_Text_BirdKeeperAbe_Beaten
	msgbox VioletGym_Text_BirdKeeperAbe_After, MSGBOX_AUTOCLOSE
	end

VioletGym_Text_BirdKeeperAbe_Seen:
	.string "Let me see if you are good\n"
	.string "enough to face FALKNER!$"

VioletGym_Text_BirdKeeperAbe_Beaten:
	.string "This can't be true!$"

VioletGym_Text_BirdKeeperAbe_After:
	.string "This is pathetic, losing to some\n"
	.string "rookie trainer…$"

VioletCity_Gym_EventScript_Rod::
	trainerbattle_single TRAINER_BIRD_KEEPER_ROD_JOHTO, VioletGym_Text_BirdKeeperRod_Seen, VioletGym_Text_BirdKeeperRod_Beaten
	msgbox VioletGym_Text_BirdKeeperRod_After, MSGBOX_AUTOCLOSE
	end

VioletGym_Text_BirdKeeperRod_Seen:
	.string "The keyword is guts!\p"
	.string "Those here are training night and\n"
	.string "day to become bird POKéMON masters.\p"
	.string "Come on!$"

VioletGym_Text_BirdKeeperRod_Beaten:
	.string "Gaaah!$"

VioletGym_Text_BirdKeeperRod_After:
	.string "FALKNER's skills are for real!\p"
	.string "Don't get cocky just because\n"
	.string "you beat me!$"
