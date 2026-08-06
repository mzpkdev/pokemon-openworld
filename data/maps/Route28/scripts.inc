Route28_MapScripts::
	map_script MAP_SCRIPT_ON_TRANSITION, Route28_OnTransition
	map_script MAP_SCRIPT_ON_RESUME, Johto_EventScript_SetTimeEncounters
	.byte 0

Route28_OnTransition:
	call Johto_EventScript_SetTimeEncounters
	end

Route28_EventScript_Sign::
	msgbox Route28_Text_Sign, MSGBOX_SIGN
	end

Route28_Text_Sign:
	.string "ROUTE 28$"
