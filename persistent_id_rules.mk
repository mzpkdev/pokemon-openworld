# Persistent IDs are authored only in the reviewed ledger. Generated files live
# in the policy-specific build tree and cannot become a second authority.
PERSISTENT_ID_LEDGER := src/data/persistence/persistent_ids.json
PERSISTENT_ID_SOURCES := tools/persistence/persistent_sources.json
PERSISTENT_ID_GENERATOR := tools/persistence/ledger.py
PERSISTENT_HEAL_SOURCE := src/data/heal_locations.json
PERSISTENT_LOCATION_SOURCE := src/data/region_map/region_map_sections.json
PERSISTENT_FACILITY_SOURCE := include/constants/battle_frontier.h
PERSISTENT_ID_TABLE := $(GENERATED_ROOT)/src/data/persistence/trainer_defeat_flags.inc.c
PERSISTENT_HEAL_CONSTANTS := $(GENERATED_ROOT)/include/constants/heal_locations.h
PERSISTENT_LOCATION_CODECS := $(GENERATED_ROOT)/src/data/persistence/location_codecs.inc.c
PERSISTENT_BINDING_FACADES := $(GENERATED_ROOT)/include/constants/persistent_bindings.h
PERSISTENT_PUBLIC_FACADES := $(addprefix $(GENERATED_ROOT)/include/constants/, \
		persistent_flags.inc.h persistent_vars.inc.h persistent_game_stats.inc.h \
		persistent_maps.inc.h persistent_facilities.inc.h persistent_locations.inc.h \
		persistent_opponents.inc.h persistent_trainer_special.inc.h persistent_trainer_hill.inc.h)
PERSISTENT_ID_OUTPUTS := $(PERSISTENT_ID_TABLE) $(PERSISTENT_HEAL_CONSTANTS) $(PERSISTENT_LOCATION_CODECS) $(PERSISTENT_BINDING_FACADES) $(PERSISTENT_PUBLIC_FACADES)

AUTO_GEN_TARGETS += $(PERSISTENT_ID_OUTPUTS)

$(PERSISTENT_ID_OUTPUTS) &: $(PERSISTENT_ID_LEDGER) $(PERSISTENT_ID_SOURCES) \
		tools/integrity/save_contract.json $(PERSISTENT_ID_GENERATOR) \
		$(PERSISTENT_HEAL_SOURCE) $(PERSISTENT_LOCATION_SOURCE) $(PERSISTENT_FACILITY_SOURCE) \
		include/constants/opponents.h include/constants/trainers.h include/constants/trainer_hill.h \
		include/constants/flags.h include/constants/vars.h include/constants/vars_frlg.h \
		include/constants/game_stat.h include/constants/maps.h include/config/item.h | $(MAP_GENERATION_STAMP)
	python3 -m tools.persistence.ledger generate --output-root $(GENERATED_ROOT)

$(C_BUILDDIR)/persistent_ids.o: c_dep += $(PERSISTENT_ID_TABLE)
$(C_BUILDDIR)/heal_location.o $(C_BUILDDIR)/region_map.o: c_dep += $(PERSISTENT_HEAL_CONSTANTS)
$(C_BUILDDIR)/location_codecs.o: c_dep += $(PERSISTENT_LOCATION_CODECS)

.PHONY: validate-persistent-ids
validate-persistent-ids:
	python3 -m tools.persistence.ledger validate
