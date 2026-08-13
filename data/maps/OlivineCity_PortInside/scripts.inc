OlivineCity_PortInside_MapScripts::
	.byte 0

OlivineCity_PortInside_EventScript_Sailor::
	lock
	faceplayer
	msgbox OlivineCity_PortInside_Text_TravelToVermilion, MSGBOX_YESNO
	switch VAR_RESULT
	case YES, OlivineCity_PortInside_EventScript_TravelToVermilion
	release
	end

OlivineCity_PortInside_EventScript_TravelToVermilion::
	closemessage
	warp MAP_VERMILION_CITY_PORT_INSIDE, 8, 9
	waitstate
	release
	end

OlivineCity_PortInside_Text_TravelToVermilion:
	.string "The ferry is ready to sail for\n"
	.string "VERMILION CITY. Will you board?$"
