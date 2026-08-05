# Map JSON data

# Reviewed inputs
MAPS_DIR := $(DATA_ASM_SUBDIR)/maps
LAYOUTS_DIR := $(DATA_ASM_SUBDIR)/layouts

# Policy-isolated outputs. mapjson builds a complete sibling staging tree and only
# promotes it after every file has been generated successfully.
MAPS_OUTDIR := $(GENERATED_ROOT)/data/maps
LAYOUTS_OUTDIR := $(GENERATED_ROOT)/data/layouts
INCLUDECONSTS_OUTDIR := $(GENERATED_ROOT)/include/constants
MAP_GROUP_COUNT_OUT := $(GENERATED_ROOT)/src/data/map_group_count.h
MAP_GENERATION_STAMP := $(GENERATED_ROOT)/.map-build-policy
FOUNDATION_MANIFEST := $(GENERATED_ROOT)/foundation-manifest.json

AUTO_GEN_TARGETS += $(MAP_GENERATION_STAMP)

MAP_DIRS := $(dir $(wildcard $(MAPS_DIR)/*/map.json))
MAP_JSONS := $(patsubst $(MAPS_DIR)/%/,$(MAPS_DIR)/%/map.json,$(MAP_DIRS))
MAP_NAMES := $(notdir $(patsubst %/,%,$(MAP_DIRS)))
MAP_CONNECTIONS := $(MAP_NAMES:%=$(MAPS_OUTDIR)/%/connections.inc)
MAP_EVENTS := $(MAP_NAMES:%=$(MAPS_OUTDIR)/%/events.inc)
MAP_HEADERS := $(MAP_NAMES:%=$(MAPS_OUTDIR)/%/header.inc)

MAP_GENERATED_GLOBALS := \
	$(MAPS_OUTDIR)/connections.inc \
	$(MAPS_OUTDIR)/groups.inc \
	$(MAPS_OUTDIR)/events.inc \
	$(MAPS_OUTDIR)/headers.inc \
	$(LAYOUTS_OUTDIR)/layouts.inc \
	$(LAYOUTS_OUTDIR)/layouts_table.inc \
	$(INCLUDECONSTS_OUTDIR)/map_groups.h \
	$(INCLUDECONSTS_OUTDIR)/layouts.h \
	$(INCLUDECONSTS_OUTDIR)/map_event_ids.h \
	$(MAP_GROUP_COUNT_OUT) \
	$(FOUNDATION_MANIFEST)

$(MAP_GENERATION_STAMP): $(MAPS_DIR)/map_groups.json $(LAYOUTS_DIR)/layouts.json $(MAP_JSONS) \
		tools/mapjson/product_exclusions.json tools/mapjson/product_hidden_item_flags.json $(MAPJSON)
	@$(MAPJSON) generate $(MAP_VERSION) $(MAPS_DIR)/map_groups.json $(LAYOUTS_DIR)/layouts.json $(GENERATED_ROOT) $(MAP_JSONS)
	@echo "$(MAPJSON) generate $(MAP_VERSION) $(MAPS_DIR)/map_groups.json $(LAYOUTS_DIR)/layouts.json $(GENERATED_ROOT) <MAP_JSONS>"

# These are products of the atomic generation above. Keeping them as explicit
# targets gives make useful dependency errors if a supposedly complete tree is
# ever missing a member.
$(MAP_GENERATED_GLOBALS) $(MAP_CONNECTIONS) $(MAP_EVENTS) $(MAP_HEADERS): $(MAP_GENERATION_STAMP)
	@test -f $@

$(DATA_ASM_BUILDDIR)/maps.o: $(DATA_ASM_SUBDIR)/maps.s $(LAYOUTS_OUTDIR)/layouts.inc $(LAYOUTS_OUTDIR)/layouts_table.inc $(MAPS_OUTDIR)/headers.inc $(MAPS_OUTDIR)/groups.inc $(MAPS_OUTDIR)/connections.inc $(MAP_CONNECTIONS) $(MAP_HEADERS)
	sed -e 's#"data/layouts/layouts.inc"#"$(LAYOUTS_OUTDIR)/layouts.inc"#' \
	    -e 's#"data/layouts/layouts_table.inc"#"$(LAYOUTS_OUTDIR)/layouts_table.inc"#' \
	    -e 's#"data/maps/headers.inc"#"$(MAPS_OUTDIR)/headers.inc"#' \
	    -e 's#"data/maps/groups.inc"#"$(MAPS_OUTDIR)/groups.inc"#' \
	    -e 's#"data/maps/connections.inc"#"$(MAPS_OUTDIR)/connections.inc"#' $< \
	| $(PREPROC) -is $< charmap.txt | $(CPP) $(CPPFLAGS) -I include - \
	| $(PREPROC) -ie $< charmap.txt | $(AS) $(ASFLAGS) -o $@

$(DATA_ASM_BUILDDIR)/map_events.o: $(DATA_ASM_SUBDIR)/map_events.s $(MAPS_OUTDIR)/events.inc $(MAP_EVENTS)
	sed -e 's#"data/maps/events.inc"#"$(MAPS_OUTDIR)/events.inc"#' $< \
	| $(PREPROC) -is $< charmap.txt | $(CPP) $(CPPFLAGS) -I include - \
	| $(PREPROC) -ie $< charmap.txt | $(AS) $(ASFLAGS) -o $@

$(C_BUILDDIR)/debug.o $(TEST_BUILDDIR)/text.o: $(MAP_GROUP_COUNT_OUT)

# Retail dialects remain useful generator diagnostics, but never inherit the
# product name or enter a link/release graph.
GENERATOR_FIXTURE_ROOT := $(BUILD_DIR)/fixtures
.PHONY: generator-fixture-emerald generator-fixture-firered generator-fixture-ruby
generator-fixture-emerald generator-fixture-firered generator-fixture-ruby: generator-fixture-%: $(MAPJSON)
	@$(MAPJSON) generate $* $(MAPS_DIR)/map_groups.json $(LAYOUTS_DIR)/layouts.json \
		$(GENERATOR_FIXTURE_ROOT)/$*/current $(MAP_JSONS)
	@echo "Generated diagnostic $* registry fixture under $(GENERATOR_FIXTURE_ROOT)/$*"
