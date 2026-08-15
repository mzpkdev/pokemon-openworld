.set LOCALID_VERMILIONMARINA_SAILOR, 1
.set LOCALID_VERMILIONMARINA_BOAT, 2

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
	applymovement LOCALID_VERMILIONMARINA_SAILOR, VermilionPort_Movement_SailorEnterBoat
	waitmovement 0
	playse SE_EXIT
	applymovement OBJ_EVENT_ID_PLAYER, VermilionPort_Movement_PlayerEnterBoat
	waitmovement 0
	special SpawnCameraObject
	playse SE_EXIT
	removeobject OBJ_EVENT_ID_PLAYER
	delay 60
	applymovement LOCALID_VERMILIONMARINA_SAILOR, VermilionPort_Movement_BoatLeave
	applymovement LOCALID_VERMILIONMARINA_BOAT, VermilionPort_Movement_BoatLeave
	waitmovement LOCALID_VERMILIONMARINA_BOAT
	setdynamicwarp MAP_OLIVINE_CITY_PORT_INSIDE, 8, 16
	warp MAP_SSAQUA_1F, 29, 3
	waitstate
	release
	end

VermilionPort_Movement_SailorEnterBoat:
	walk_down
	walk_down
	step_end

VermilionPort_Movement_PlayerEnterBoat:
	walk_down
	walk_down
	walk_in_place_down
	step_end

VermilionPort_Movement_BoatLeave:
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	step_end

VermilionCity_PortInside_Text_TravelToOlivine:
	.string "The ferry is ready to sail for\n"
	.string "OLIVINE CITY. Will you board?$"
