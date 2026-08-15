LakeOfRage_MapScripts::
	.byte 0

LakeOfRage_EventScript_Andre::
	trainerbattle_single TRAINER_FISHERMAN_ANDRE_JOHTO, LakeOfRage_Text_FisherAndreSeen, LakeOfRage_Text_FisherAndreBeaten
	msgbox LakeOfRage_Text_FisherAndreAfter, MSGBOX_AUTOCLOSE
	end

LakeOfRage_Text_FisherAndreSeen:
	.string "Let me battle with the POKéMON I\n"
	.string "just caught!$"

LakeOfRage_Text_FisherAndreBeaten:
	.string "I might be an expert angler, but\n"
	.string "I stink as a POKéMON trainer…$"

LakeOfRage_Text_FisherAndreAfter:
	.string "I won't lose as an angler! I catch\n"
	.string "POKéMON all day.$"

LakeOfRage_EventScript_Raymond::
	trainerbattle_single TRAINER_FISHERMAN_RAYMOND_JOHTO, LakeOfRage_Text_FisherRaymondSeen, LakeOfRage_Text_FisherRaymondBeaten
	msgbox LakeOfRage_Text_FisherRaymondAfter, MSGBOX_AUTOCLOSE
	end

LakeOfRage_Text_FisherRaymondSeen:
	.string "No matter what I do, all I catch\n"
	.string "are the same POKéMON…$"

LakeOfRage_Text_FisherRaymondBeaten:
	.string "My line's all tangled up…$"

LakeOfRage_Text_FisherRaymondAfter:
	.string "Why can't I catch any good\n"
	.string "POKéMON?$"

LakeOfRage_EventScript_Aaron::
	trainerbattle_single TRAINER_COOLTRAINER_AARON_JOHTO, LakeOfRage_Text_CooltrainermAaronSeen, LakeOfRage_Text_CooltrainermAaronBeaten
	msgbox LakeOfRage_Text_CooltrainermAaronAfter, MSGBOX_AUTOCLOSE
	end

LakeOfRage_Text_CooltrainermAaronSeen:
	.string "If a trainer spots another trainer,\n"
	.string "he has to make a challenge.\p"
	.string "That is our destiny.$"

LakeOfRage_Text_CooltrainermAaronBeaten:
	.string "Whew… Good battle.$"

LakeOfRage_Text_CooltrainermAaronAfter:
	.string "POKéMON and their trainer become\n"
	.string "powerful through constant battling.$"
