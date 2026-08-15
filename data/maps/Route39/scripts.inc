Route39_MapScripts::
	.byte 0

Route39_EventScript_Norman::
	trainerbattle_single TRAINER_PSYCHIC_M_NORMAN_JOHTO, Route39_Text_PsychicNormanSeen, Route39_Text_PsychicNormanBeaten
	msgbox Route39_Text_PsychicNormanAfter, MSGBOX_AUTOCLOSE
	end

Route39_Text_PsychicNormanSeen:
	.string "Let me see what your\n"
	.string "POKéMON are capable of.$"

Route39_Text_PsychicNormanBeaten:
	.string "Ooh, your POKéMON have\n"
	.string "potential.$"

Route39_Text_PsychicNormanAfter:
	.string "You know how POKéMON have\n"
	.string "different abilities?\p"
	.string "People are like that too.\n"
	.string "Everyone has different\l"
	.string "potential.$"

Route39_EventScript_Ruth::
	trainerbattle_single TRAINER_PARASOL_LADY_RUTH_JOHTO, Route39_Text_PokefanFRuthSeen, Route39_Text_PokefanFRuthBeaten
	msgbox Route39_Text_PokefanFRuthAfter, MSGBOX_AUTOCLOSE
	end

Route39_Text_PokefanFRuthSeen:
	.string "Such darling POKéMON.\p"
	.string "Let's show our POKéMON\n"
	.string "together at the same time.$"

Route39_Text_PokefanFRuthBeaten:
	.string "I don't mind losing.$"

Route39_Text_PokefanFRuthAfter:
	.string "Do you know about baby\n"
	.string "POKéMON?\p"
	.string "I bet they're just adorable!$"

Route39_EventScript_Derek::
	trainerbattle_single TRAINER_POKEFAN_DEREK_JOHTO, Route39_Text_PokefanMDerekSeen, Route39_Text_PokefanMDerekBeaten
	msgbox Route39_Text_PokefanMDerekAfter, MSGBOX_AUTOCLOSE
	end

Route39_Text_PokefanMDerekSeen:
	.string "This is a good time to brag\n"
	.string "about my PIKACHU!$"

Route39_Text_PokefanMDerekBeaten:
	.string "I had no time to show off\n"
	.string "PIKACHU…$"

Route39_Text_PokefanMDerekAfter:
	.string "I'm not listening to your\n"
	.string "bragging!\p"
	.string "We POKé FANS have a policy\n"
	.string "of not listening to bragging!$"

Route39_EventScript_Eugene::
	trainerbattle_single TRAINER_SAILOR_EUGENE_JOHTO, Route39_Text_SailorEugeneSeen, Route39_Text_SailorEugeneBeaten
	msgbox Route39_Text_SailorEugeneAfter, MSGBOX_AUTOCLOSE
	end

Route39_Text_SailorEugeneSeen:
	.string "I just got back to OLIVINE.\p"
	.string "So how about a POKéMON battle?$"

Route39_Text_SailorEugeneBeaten:
	.string "Awaaargh!$"

Route39_Text_SailorEugeneAfter:
	.string "My POKéMON were caught and\n"
	.string "raised overseas.\p"
	.string "They're my companions on\n"
	.string "those long voyages.$"
