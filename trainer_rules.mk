# party files are run through trainerproc, which is a tool that converts party data to an output file
# matching the current trainer .h formatting

AUTO_GEN_TARGETS += src/data/trainers.h
AUTO_GEN_TARGETS += src/data/trainers_frlg.h
AUTO_GEN_TARGETS += src/data/battle_partners.h
AUTO_GEN_TARGETS += test/battle/trainer_control.h
AUTO_GEN_TARGETS += test/battle/partner_control.h
AUTO_GEN_TARGETS += src/data/debug_trainers.h

# Like mapjson, the bundled trainer processor must be buildable from a clean
# checkout and must become stale when its source changes.  Keep this rule
# conditional so an external TRAINERPROC override never builds the bundled
# executable as a side effect.
ifeq ($(TRAINERPROC),$(BUNDLED_TRAINERPROC))
$(BUNDLED_TRAINERPROC): $(TOOLS_DIR)/trainerproc/main.c \
                        $(TOOLS_DIR)/trainerproc/Makefile
	@$(MAKE) -C $(TOOLS_DIR)/trainerproc -B $(notdir $@)
endif

%.h: %.party $(TRAINERPROC)
	$(CPP) $(TRAINER_CPPFLAGS) -traditional-cpp - < $< | $(TRAINERPROC) -o $@ -i $< -
