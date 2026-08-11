# FRLG rematch chains have one reviewed symbolic authority. Generated tables live
# in the policy-specific build tree and cannot become a second authored source.
TRAINER_REMATCH_MANIFEST := src/data/trainer_rematches/frlg.json
TRAINER_REMATCH_GENERATOR := tools/trainer_rematches/generate.py
TRAINER_REMATCH_DATA := $(GENERATED_ROOT)/src/data/trainer_rematches/frlg.inc.c

AUTO_GEN_TARGETS += $(TRAINER_REMATCH_DATA)

$(TRAINER_REMATCH_DATA): $(TRAINER_REMATCH_MANIFEST) $(TRAINER_REMATCH_GENERATOR) \
		include/constants/opponents.h include/constants/opponents_frlg.h
	python3 -m tools.trainer_rematches.generate generate --output $@

.PHONY: validate-trainer-rematches
validate-trainer-rematches:
	python3 -m tools.trainer_rematches.generate validate
