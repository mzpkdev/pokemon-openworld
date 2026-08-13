VermilionCity_PortInside_MapScripts::
	.byte 0

VermilionCity_PortInside_EventScript_Sailor::
	lock
	faceplayer
	msgbox VermilionCity_PortInside_Text_TravelToOlivine, MSGBOX_YESNO
	switch VAR_RESULT
	case YES, VermilionCity_PortInside_EventScript_TravelToOlivine
	release
	end

VermilionCity_PortInside_EventScript_TravelToOlivine::
	closemessage
	warp MAP_OLIVINE_CITY_PORT_INSIDE, 8, 16
	waitstate
	release
	end

VermilionCity_PortInside_Text_TravelToOlivine:
	.string "The ferry is ready to sail for\n"
	.string "OLIVINE CITY. Will you board?$"
