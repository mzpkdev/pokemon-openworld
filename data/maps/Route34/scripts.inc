Route34_MapScripts::
	.byte 0

Route34_EventScript_YoungsterSamuel::
	trainerbattle_single TRAINER_YOUNGSTER_SAMUEL_JOHTO, Route34_Text_YoungsterSamuel_Seen, Route34_Text_YoungsterSamuel_Beaten
	msgbox Route34_Text_YoungsterSamuel_After, MSGBOX_AUTOCLOSE
	end

Route34_Text_YoungsterSamuel_Seen:
	.string "Hey! I'm looking for MANKEY!$"

Route34_Text_YoungsterSamuel_Beaten:
	.string "Beaten by a passing stranger!$"

Route34_Text_YoungsterSamuel_After:
	.string "I'm going to train even harder.\p"
	.string "After all, I'm trying to become\n"
	.string "a GYM LEADER.$"

Route34_EventScript_PokefanMBrandon::
	trainerbattle_single TRAINER_POKEFAN_BRANDON_JOHTO, Route34_Text_PokefanBrandon_Seen, Route34_Text_PokefanBrandon_Beaten
	msgbox Route34_Text_PokefanBrandon_After, MSGBOX_AUTOCLOSE
	end

Route34_Text_PokefanBrandon_Seen:
	.string "I just got my POKéMON back from\n"
	.string "DAY-CARE.\p"
	.string "Let's see how much stronger it got!$"

Route34_Text_PokefanBrandon_Beaten:
	.string "Why does it end this way?$"

Route34_Text_PokefanBrandon_After:
	.string "My POKéMON came back with new moves.\p"
	.string "That confounded me to no end!$"

Route34_EventScript_CamperTodd::
	trainerbattle_single TRAINER_CAMPER_TODD_JOHTO, Route34_Text_CamperTodd_Seen, Route34_Text_CamperTodd_Beaten
	msgbox Route34_Text_CamperTodd_After, MSGBOX_AUTOCLOSE
	end

Route34_Text_CamperTodd_Seen:
	.string "I'm confident in my ability to\n"
	.string "raise POKéMON.\p"
	.string "Want to see?$"

Route34_Text_CamperTodd_Beaten:
	.string "Did I screw up my training?$"

Route34_Text_CamperTodd_After:
	.string "Maybe I should take one to DAY-CARE,\n"
	.string "or maybe use some items…$"

Route34_EventScript_YoungsterIan::
	trainerbattle_single TRAINER_YOUNGSTER_IAN_JOHTO, Route34_Text_YoungsterIan_Seen, Route34_Text_YoungsterIan_Beaten
	msgbox Route34_Text_YoungsterIan_After, MSGBOX_AUTOCLOSE
	end

Route34_Text_YoungsterIan_Seen:
	.string "I'm the best in my class at\n"
	.string "POKéMON.$"

Route34_Text_YoungsterIan_Beaten:
	.string "No! There are better trainers…$"

Route34_Text_YoungsterIan_After:
	.string "I'm trying hard so I can be the\n"
	.string "star in my class.$"

Route34_EventScript_PicnickerGina::
	trainerbattle_single TRAINER_PICNICKER_GINA_JOHTO, Route34_Text_PicnickerGina_Seen, Route34_Text_PicnickerGina_Beaten
	msgbox Route34_Text_PicnickerGina_After, MSGBOX_AUTOCLOSE
	end

Route34_Text_PicnickerGina_Seen:
	.string "Are you a TRAINER?\p"
	.string "Let's have a practice battle.$"

Route34_Text_PicnickerGina_Beaten:
	.string "Oh, no! I just can't win…$"

Route34_Text_PicnickerGina_After:
	.string "You're too strong to be a\n"
	.string "practice partner.$"
