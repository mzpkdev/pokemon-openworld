PewterCity_Hns_MapScripts::
	map_script MAP_SCRIPT_ON_TRANSITION, PewterCity_Hns_OnTransition
	.byte 0

PewterCity_Hns_OnTransition::
	setworldmapflag FLAG_WORLD_MAP_PEWTER_CITY
	setvar VAR_MAP_SCENE_PEWTER_CITY_MUSEUM_1F, 0
	end

PewterCity_Hns_EventScript_Lass::
	msgbox PewterCity_Text_ClefairyCameFromMoon, MSGBOX_NPC
	end

PewterCity_Hns_EventScript_MuseumGuide::
	lock
	faceplayer
	msgbox PewterCity_Text_DidYouCheckOutMuseum, MSGBOX_YESNO
	goto_if_eq VAR_RESULT, YES, PewterCity_Hns_EventScript_CheckedOutMuseum
	msgbox PewterCity_Text_ReallyYouHaveToGo
	closemessage
	playbgm MUS_FOLLOW_ME, 0
	call_if_eq VAR_FACING, DIR_NORTH, PewterCity_Hns_EventScript_LeadToMuseumNorth
	call_if_eq VAR_FACING, DIR_SOUTH, PewterCity_Hns_EventScript_LeadToMuseumSouth
	call_if_eq VAR_FACING, DIR_WEST, PewterCity_Hns_EventScript_LeadToMuseumWest
	call_if_eq VAR_FACING, DIR_EAST, PewterCity_Hns_EventScript_LeadToMuseumEast
	msgbox PewterCity_Text_ThisIsTheMuseum
	closemessage
	applymovement LOCALID_PEWTER_MUSEUM_GUIDE, PewterCity_Hns_Movement_MuseumGuideExit
	waitmovement 0
	fadedefaultbgm
	removeobject LOCALID_PEWTER_MUSEUM_GUIDE
	clearflag FLAG_HIDE_PEWTER_MUSEUM_GUIDE
	release
	end

PewterCity_Hns_EventScript_LeadToMuseumNorth::
	applymovement LOCALID_PEWTER_MUSEUM_GUIDE, PewterCity_Hns_Movement_GuideToMuseum
	applymovement LOCALID_PLAYER, PewterCity_Hns_Movement_PlayerFollowMuseumNorth
	waitmovement 0
	return

PewterCity_Hns_EventScript_LeadToMuseumSouth::
	applymovement LOCALID_PEWTER_MUSEUM_GUIDE, PewterCity_Hns_Movement_GuideToMuseum
	applymovement LOCALID_PLAYER, PewterCity_Hns_Movement_PlayerFollowMuseumSouth
	waitmovement 0
	return

PewterCity_Hns_EventScript_LeadToMuseumWest::
	applymovement LOCALID_PEWTER_MUSEUM_GUIDE, PewterCity_Hns_Movement_GuideToMuseum
	applymovement LOCALID_PLAYER, PewterCity_Hns_Movement_PlayerFollowMuseumWest
	waitmovement 0
	return

PewterCity_Hns_EventScript_LeadToMuseumEast::
	applymovement LOCALID_PEWTER_MUSEUM_GUIDE, PewterCity_Hns_Movement_GuideToMuseum
	applymovement LOCALID_PLAYER, PewterCity_Hns_Movement_PlayerFollowMuseumEast
	waitmovement 0
	return

PewterCity_Hns_EventScript_CheckedOutMuseum::
	msgbox PewterCity_Text_WerentThoseFossilsAmazing
	release
	end

PewterCity_Hns_EventScript_FatMan::
	lock
	faceplayer
	famechecker FAMECHECKER_BROCK, 2
	msgbox PewterCity_Text_BrockOnlySeriousTrainerHere
	release
	end

PewterCity_Hns_EventScript_BugCatcher::
	lock
	faceplayer
	msgbox PewterCity_Text_DoYouKnowWhatImDoing, MSGBOX_YESNO
	goto_if_eq VAR_RESULT, YES, PewterCity_Hns_EventScript_KnowWhatTheyreDoing
	msgbox PewterCity_Text_SprayingRepelToKeepWildMonsOut
	release
	end

PewterCity_Hns_EventScript_KnowWhatTheyreDoing::
	msgbox PewterCity_Text_ThatsRightItsHardWork
	release
	end

PewterCity_Hns_EventScript_GymGuide::
	lock
	faceplayer
	call PewterCity_Hns_EventScript_LeadToGym
	release
	end

PewterCity_Hns_EventScript_GymGuideTrigger::
	lockall
	call PewterCity_Hns_EventScript_LeadToGym
	releaseall
	end

PewterCity_Hns_EventScript_LeadToGym::
	msgbox PewterCity_Text_BrocksLookingForChallengersFollowMe
	closemessage
	playbgm MUS_FOLLOW_ME, 0
	applymovement LOCALID_PEWTER_GYM_GUIDE, PewterCity_Hns_Movement_GuideToGym
	applymovement LOCALID_PLAYER, PewterCity_Hns_Movement_PlayerFollowGym
	waitmovement 0
	msgbox PewterCity_Text_GoTakeOnBrock
	closemessage
	applymovement LOCALID_PEWTER_GYM_GUIDE, PewterCity_Hns_Movement_GymGuideExit
	waitmovement 0
	fadedefaultbgm
	removeobject LOCALID_PEWTER_GYM_GUIDE
	clearflag FLAG_HIDE_PEWTER_CITY_GYM_GUIDE
	return

PewterCity_Hns_EventScript_RunningShoesAide::
	lock
	faceplayer
	setvar VAR_TEMP_1, 0
	call PewterCity_Hns_EventScript_GiveRunningShoes
	release
	end

PewterCity_Hns_EventScript_RunningShoesAideTriggerTop::
	lockall
	setvar VAR_TEMP_1, 1
	call PewterCity_Hns_EventScript_GiveRunningShoes
	releaseall
	end

PewterCity_Hns_EventScript_RunningShoesAideTriggerMid::
	lockall
	setvar VAR_TEMP_1, 2
	call PewterCity_Hns_EventScript_GiveRunningShoes
	releaseall
	end

PewterCity_Hns_EventScript_RunningShoesAideTriggerLow::
	lockall
	setvar VAR_TEMP_1, 3
	call PewterCity_Hns_EventScript_GiveRunningShoes
	releaseall
	end

PewterCity_Hns_EventScript_RunningShoesAideTriggerBottom::
	lockall
	setvar VAR_TEMP_1, 4
	call PewterCity_Hns_EventScript_GiveRunningShoes
	releaseall
	end

PewterCity_Hns_EventScript_GiveRunningShoes::
	goto_if_set FLAG_SYS_B_DASH, PewterCity_Hns_EventScript_RunningShoesAlreadyDelivered
	textcolor NPC_TEXT_COLOR_MALE
	call_if_eq VAR_TEMP_1, 1, PewterCity_Hns_EventScript_AideNoticePlayer
	call_if_eq VAR_TEMP_1, 2, PewterCity_Hns_EventScript_AideNoticePlayer
	call_if_eq VAR_TEMP_1, 3, PewterCity_Hns_EventScript_AideNoticePlayer
	call_if_eq VAR_TEMP_1, 4, PewterCity_Hns_EventScript_AideNoticePlayer
	waitse
	playse SE_PIN
	applymovement LOCALID_PEWTER_AIDE, Common_Movement_ExclamationMark
	waitmovement 0
	applymovement LOCALID_PEWTER_AIDE, Common_Movement_Delay48
	waitmovement 0
	msgbox PewterCity_Text_OhPlayer
	call_if_eq VAR_TEMP_1, 0, PewterCity_Hns_EventScript_AideApproachPlayer0
	call_if_eq VAR_TEMP_1, 1, PewterCity_Hns_EventScript_AideApproachPlayerTop
	call_if_eq VAR_TEMP_1, 2, PewterCity_Hns_EventScript_AideApproachPlayerMid
	call_if_eq VAR_TEMP_1, 3, PewterCity_Hns_EventScript_AideApproachPlayerLow
	call_if_eq VAR_TEMP_1, 4, PewterCity_Hns_EventScript_AideApproachPlayerBottom
	msgbox PewterCity_Text_AskedToDeliverThis
	textcolor NPC_TEXT_COLOR_NEUTRAL
	playfanfare MUS_RG_OBTAIN_KEY_ITEM
	message PewterCity_Text_ReceivedRunningShoesFromAide
	waitmessage
	waitfanfare
	msgbox PewterCity_Text_SwitchedShoesWithRunningShoes
	special DisableMsgBoxWalkaway
	signmsg
	msgbox PewterCity_Text_ExplainRunningShoes
	normalmsg
	call EventScript_RestorePrevTextColor
	msgbox PewterCity_Text_MustBeGoingBackToLab
	closemessage
	call_if_eq VAR_TEMP_1, 0, PewterCity_Hns_EventScript_AideExit0
	call_if_eq VAR_TEMP_1, 1, PewterCity_Hns_EventScript_AideExitTop
	call_if_eq VAR_TEMP_1, 2, PewterCity_Hns_EventScript_AideExitMid
	call_if_eq VAR_TEMP_1, 3, PewterCity_Hns_EventScript_AideExitLow
	call_if_eq VAR_TEMP_1, 4, PewterCity_Hns_EventScript_AideExitBottom
	delay 30
	textcolor NPC_TEXT_COLOR_NEUTRAL
	msgbox PewterCity_Text_RunningShoesLetterFromMom
	closemessage
	removeobject LOCALID_PEWTER_AIDE
	setflag FLAG_SYS_B_DASH
	setvar VAR_MAP_SCENE_PEWTER_CITY, 2
	return

PewterCity_Hns_EventScript_RunningShoesAlreadyDelivered::
	return

PewterCity_Hns_EventScript_AideNoticePlayer::
	applymovement LOCALID_PEWTER_AIDE, Common_Movement_WalkInPlaceFasterDown
	waitmovement 0
	return

PewterCity_Hns_EventScript_AideApproachPlayer0::
	closemessage
	delay 20
	return

PewterCity_Hns_EventScript_AideApproachPlayerTop::
	closemessage
	applymovement LOCALID_PLAYER, Common_Movement_WalkInPlaceFasterUp
	waitmovement 0
	return

PewterCity_Hns_EventScript_AideApproachPlayerMid::
	closemessage
	applymovement LOCALID_PEWTER_AIDE, PewterCity_Hns_Movement_AideApproachPlayerMid
	waitmovement 0
	applymovement LOCALID_PLAYER, Common_Movement_WalkInPlaceFasterUp
	waitmovement 0
	return

PewterCity_Hns_EventScript_AideApproachPlayerLow::
	closemessage
	applymovement LOCALID_PEWTER_AIDE, PewterCity_Hns_Movement_AideApproachPlayerLow
	waitmovement 0
	applymovement LOCALID_PLAYER, Common_Movement_WalkInPlaceFasterUp
	waitmovement 0
	return

PewterCity_Hns_EventScript_AideApproachPlayerBottom::
	closemessage
	applymovement LOCALID_PEWTER_AIDE, PewterCity_Hns_Movement_AideApproachPlayerBottom
	waitmovement 0
	applymovement LOCALID_PLAYER, Common_Movement_WalkInPlaceFasterUp
	waitmovement 0
	return

PewterCity_Hns_EventScript_AideExit0::
	applymovement LOCALID_PEWTER_AIDE, PewterCity_Hns_Movement_AideExit0
	waitmovement 0
	return

PewterCity_Hns_EventScript_AideExitTop::
	applymovement LOCALID_PEWTER_AIDE, PewterCity_Hns_Movement_AideExitTop
	waitmovement 0
	return

PewterCity_Hns_EventScript_AideExitMid::
	applymovement LOCALID_PEWTER_AIDE, PewterCity_Hns_Movement_AideExitMid
	waitmovement 0
	return

PewterCity_Hns_EventScript_AideExitLow::
	applymovement LOCALID_PEWTER_AIDE, PewterCity_Hns_Movement_AideExitLow
	waitmovement 0
	return

PewterCity_Hns_EventScript_AideExitBottom::
	applymovement LOCALID_PEWTER_AIDE, PewterCity_Hns_Movement_AideExitBottom
	waitmovement 0
	return

PewterCity_Hns_EventScript_TrainerTips::
	msgbox PewterCity_Text_TrainerTipsEarningEXP, MSGBOX_SIGN
	end

PewterCity_Hns_EventScript_PoliceNotice::
	msgbox PewterCity_Text_CallPoliceIfInfoOnThieves, MSGBOX_SIGN
	end

PewterCity_Hns_EventScript_MuseumSign::
	msgbox PewterCity_Text_MuseumOfScience, MSGBOX_SIGN
	end

PewterCity_Hns_EventScript_GymSign::
	lockall
	famechecker FAMECHECKER_BROCK, 0
	msgbox PewterCity_Text_GymSign
	releaseall
	end

PewterCity_Hns_EventScript_CitySign::
	msgbox PewterCity_Text_CitySign, MSGBOX_SIGN
	end

PewterCity_Hns_Movement_GuideToMuseum::
	walk_up
	walk_left
	walk_left
	walk_left
	walk_up
	walk_up
	walk_left
	walk_in_place_faster_up
	step_end

PewterCity_Hns_Movement_PlayerFollowMuseumNorth::
	walk_up
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_right
	walk_in_place_faster_up
	step_end

PewterCity_Hns_Movement_PlayerFollowMuseumSouth::
	walk_up
	walk_up
	walk_left
	walk_left
	walk_left
	walk_up
	walk_up
	walk_in_place_faster_up
	step_end

PewterCity_Hns_Movement_PlayerFollowMuseumWest::
	walk_up
	walk_up
	walk_left
	walk_left
	walk_left
	walk_left
	walk_right
	walk_in_place_faster_up
	step_end

PewterCity_Hns_Movement_PlayerFollowMuseumEast::
	walk_up
	walk_up
	walk_left
	walk_left
	walk_left
	walk_left
	walk_up
	walk_in_place_faster_up
	step_end

PewterCity_Hns_Movement_MuseumGuideExit::
	walk_down
	walk_down
	walk_right
	walk_right
	walk_right
	walk_right
	walk_right
	step_end

PewterCity_Hns_Movement_GuideToGym::
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_up
	walk_up
	walk_up
	walk_up
	walk_up
	walk_up
	walk_in_place_faster_up
	step_end

PewterCity_Hns_Movement_PlayerFollowGym::
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_up
	walk_up
	walk_up
	walk_up
	walk_up
	walk_up
	walk_in_place_faster_up
	step_end

PewterCity_Hns_Movement_GymGuideExit::
	walk_right
	walk_right
	walk_right
	walk_right
	walk_right
	walk_right
	walk_right
	walk_right
	walk_right
	walk_right
	step_end

PewterCity_Hns_Movement_AideApproachPlayerMid::
	delay_4
	walk_down
	step_end

PewterCity_Hns_Movement_AideApproachPlayerLow::
	delay_4
	walk_down
	walk_down
	step_end

PewterCity_Hns_Movement_AideApproachPlayerBottom::
	delay_4
	walk_down
	walk_down
	walk_down
	step_end

PewterCity_Hns_Movement_AideExit0::
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	step_end

PewterCity_Hns_Movement_AideExitTop::
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	step_end

PewterCity_Hns_Movement_AideExitMid::
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	step_end

PewterCity_Hns_Movement_AideExitLow::
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	step_end

PewterCity_Hns_Movement_AideExitBottom::
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	walk_left
	step_end
