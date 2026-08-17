@ Audibly exact HnS Pewter closure for MIDI programs 5, 15, 20, 35, and 39.

	.align 2
.set hns_pewter_keysplit_vibraphone, . - 0
	.rept 68
	.byte 0
	.endr
	.rept 60
	.byte 1
	.endr

.set hns_pewter_keysplit_martin_guitar, . - 0
	.rept 53
	.byte 0
	.endr
	.rept 8
	.byte 1
	.endr
	.rept 9
	.byte 2
	.endr
	.rept 58
	.byte 3
	.endr

.set hns_pewter_keysplit_fingered_bass, . - 0
	.rept 54
	.byte 0
	.endr
	.rept 74
	.byte 1
	.endr

.set hns_pewter_keysplit_bassoon, . - 0
	.rept 46
	.byte 0
	.endr
	.rept 8
	.byte 1
	.endr
	.rept 74
	.byte 2
	.endr

voice_group hns_pewter_vibraphone
	voice_directsound 60, 0, DirectSoundWaveData_hg_148vibrc4, 255, 246, 0, 192
	voice_directsound 60, 0, DirectSoundWaveData_hg_149vibrc5, 255, 246, 0, 205

voice_group hns_pewter_martin_guitar
	voice_directsound 60, 0, DirectSoundWaveData_hg_117marting2, 255, 251, 14, 192
	voice_directsound 60, 0, DirectSoundWaveData_hg_118marting3, 255, 251, 14, 192
	voice_directsound 60, 0, DirectSoundWaveData_hg_116martine4, 255, 251, 14, 192
	voice_directsound 60, 0, DirectSoundWaveData_hg_115martinc5, 255, 251, 14, 192

voice_group hns_pewter_fingered_bass
	voice_directsound 60, 0, DirectSoundWaveData_hg_041ampega2, 255, 234, 159, 192
	voice_directsound 60, 0, DirectSoundWaveData_hg_042ampega3, 255, 234, 159, 192

voice_group hns_pewter_bassoon
	voice_directsound 60, 0, DirectSoundWaveData_hg_012bsne2, 255, 242, 127, 214
	voice_directsound 60, 0, DirectSoundWaveData_hg_011bsnc3, 255, 242, 127, 214
	voice_directsound 60, 0, DirectSoundWaveData_hg_010bsna3, 255, 242, 127, 214

@ The MIDI only addresses drum keys 12, 13, 18, 22, 33, 34, 35, 52, and 53.
@ Each resolves to this exact donor voice entry.
voice_group hns_pewter_taiko
	.rept 54
	voice_directsound 24, 40, DirectSoundWaveData_hg_128jdruml, 255, 0, 227, 171
	.endr

voice_group hns_pewter
	.rept 5
	voice_square_1 60, 0, 0, 2, 0, 0, 15, 0
	.endr
	voice_keysplit voicegroup_hns_pewter_vibraphone, hns_pewter_keysplit_vibraphone
	.rept 9
	voice_square_1 60, 0, 0, 2, 0, 0, 15, 0
	.endr
	voice_keysplit voicegroup_hns_pewter_martin_guitar, hns_pewter_keysplit_martin_guitar
	.rept 4
	voice_square_1 60, 0, 0, 2, 0, 0, 15, 0
	.endr
	voice_keysplit voicegroup_hns_pewter_fingered_bass, hns_pewter_keysplit_fingered_bass
	.rept 14
	voice_square_1 60, 0, 0, 2, 0, 0, 15, 0
	.endr
	voice_keysplit voicegroup_hns_pewter_bassoon, hns_pewter_keysplit_bassoon
	.rept 3
	voice_square_1 60, 0, 0, 2, 0, 0, 15, 0
	.endr
	voice_keysplit_all voicegroup_hns_pewter_taiko
