RuinsOfAlph_Outside_MapScripts::
	.byte 0

RuinsOfAlph_Outside_EventScript_Nathan::
	trainerbattle_single TRAINER_PSYCHIC_M_NATHAN_JOHTO, RuinsOfAlph_Outside_Text_PsychicNathan_Seen, RuinsOfAlph_Outside_Text_PsychicNathan_Beaten
	msgbox RuinsOfAlph_Outside_Text_PsychicNathan_After, MSGBOX_AUTOCLOSE
	end

RuinsOfAlph_Outside_Text_PsychicNathan_Seen:
	.string "Hmmm… This is a strange place.$"

RuinsOfAlph_Outside_Text_PsychicNathan_Beaten:
	.string "…$"

RuinsOfAlph_Outside_Text_PsychicNathan_After:
	.string "I like thinking here.$"

RuinsOfAlph_Outside_EventScript_Stan::
	trainerbattle_single TRAINER_SUPER_NERD_STAN_JOHTO, RuinsOfAlph_Outside_Text_SuperNerdStan_Seen, RuinsOfAlph_Outside_Text_SuperNerdStan_Beaten
	msgbox RuinsOfAlph_Outside_Text_SuperNerdStan_After, MSGBOX_AUTOCLOSE
	end

RuinsOfAlph_Outside_Text_SuperNerdStan_Seen:
	.string "What do you want? I'm studying--\n"
	.string "don't disturb me!$"

RuinsOfAlph_Outside_Text_SuperNerdStan_Beaten:
	.string "Sorry…\n"
	.string "I'm frustrated by our lack of\p"
	.string "real understanding…$"

RuinsOfAlph_Outside_Text_SuperNerdStan_After:
	.string "The RUINS are from about 1500\n"
	.string "years ago.\p"
	.string "Nobody knows who built them.\p"
	.string "It's also not known if the POKéMON\n"
	.string "statues have any meaning.\p"
	.string "It's all one big mystery…$"
