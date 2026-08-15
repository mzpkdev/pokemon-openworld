Route33_MapScripts::
	.byte 0

Route33_EventScript_HikerAnthony::
	trainerbattle_single TRAINER_HIKER_ANTHONY_JOHTO, Route33_Text_HikerAnthony2Seen, Route33_Text_HikerAnthony2Beaten
	msgbox Route33_Text_HikerAnthony2After, MSGBOX_AUTOCLOSE
	end

Route33_Text_HikerAnthony2Seen:
	.string "I came through the tunnel,\n"
	.string "but I still have plenty\l"
	.string "of energy left.$"

Route33_Text_HikerAnthony2Beaten:
	.string "Whoa! You've got more zip\n"
	.string "than me!$"

Route33_Text_HikerAnthony2After:
	.string "We HIKERS are at our best\n"
	.string "in the mountains.$"
