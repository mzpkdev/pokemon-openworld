.set LOCALID_OLIVINEPORT_SAILOR, 1
.set LOCALID_OLIVINEPORT_BOAT, 2

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
	applymovement LOCALID_OLIVINEPORT_SAILOR, OlivinePort_Movement_SailorEnterBoat
	waitmovement 0
	playse SE_EXIT
	applymovement OBJ_EVENT_ID_PLAYER, OlivinePort_Movement_PlayerEnterBoat
	waitmovement 0
	special SpawnCameraObject
	playse SE_EXIT
	removeobject OBJ_EVENT_ID_PLAYER
	delay 60
	applymovement LOCALID_OLIVINEPORT_SAILOR, OlivinePort_Movement_BoatLeave
	applymovement LOCALID_OLIVINEPORT_BOAT, OlivinePort_Movement_BoatLeave
	waitmovement LOCALID_OLIVINEPORT_BOAT
	setdynamicwarp MAP_VERMILION_CITY_PORT_INSIDE, 8, 9
	warp MAP_SSAQUA_1F, 29, 3
	waitstate
	release
	end

OlivinePort_Movement_SailorEnterBoat:
	walk_down
	walk_down
	step_end

OlivinePort_Movement_PlayerEnterBoat:
	walk_down
	walk_down
	walk_in_place_down
	step_end

OlivinePort_Movement_BoatLeave:
	walk_right
	walk_right
	walk_right
	walk_right
	walk_right
	step_end

OlivineCity_PortInside_Text_TravelToVermilion:
	.string "The ferry is ready to sail for\n"
	.string "VERMILION CITY. Will you board?$"
