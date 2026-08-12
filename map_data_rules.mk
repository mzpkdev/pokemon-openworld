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
DEBUG_MAP_NAMES_OUT := $(GENERATED_ROOT)/src/data/debug_map_names.h
MAP_GENERATION_STAMP := $(GENERATED_ROOT)/.map-build-policy
INTEGRITY_MANIFEST := $(GENERATED_ROOT)/integrity-manifest.json
MAP_SECTION_METADATA_HEADER := $(GENERATED_ROOT)/include/generated/map_section_metadata.h
MAP_SECTION_METADATA_SOURCE := $(GENERATED_ROOT)/src/data/map_section_metadata.inc.c

AUTO_GEN_TARGETS += $(MAP_GENERATION_STAMP)

MAP_DIRS := $(dir $(wildcard $(MAPS_DIR)/*/map.json))
MAP_JSONS := $(patsubst $(MAPS_DIR)/%/,$(MAPS_DIR)/%/map.json,$(MAP_DIRS))
MAP_NAMES := $(notdir $(patsubst %/,%,$(MAP_DIRS)))
MAP_INPUT_DIRS := $(MAPS_DIR)/ $(wildcard $(MAPS_DIR)/*/)
MAP_SCRIPT_REGISTRIES := $(wildcard $(MAPS_DIR)/*/scripts.inc)
mapjson_recursive_wildcard = $(foreach path,$(wildcard $1*),$(call mapjson_recursive_wildcard,$(path)/,$2) $(filter $(subst *,%,$2),$(path)))
mapjson_recursive_directories = $(foreach directory,$(wildcard $1*/),$(directory) $(call mapjson_recursive_directories,$(directory)))
GLOBAL_SCRIPT_REGISTRIES := $(call mapjson_recursive_wildcard,data/scripts/,*.inc)
GLOBAL_SCRIPT_INPUT_DIRS := data/scripts/ $(call mapjson_recursive_directories,data/scripts/)
LAYOUT_INPUT_DIRS := $(LAYOUTS_DIR)/ $(wildcard $(LAYOUTS_DIR)/*/)
LAYOUT_BINARIES := $(wildcard $(LAYOUTS_DIR)/*/*.bin)
TILESET_REGISTRY_HEADERS := src/data/tilesets/headers.h src/data/tilesets/metatiles.h
TILESET_BLOBS := $(shell sed -n 's/.*INCBIN_U16("\([^"]*\)").*/\1/p' src/data/tilesets/metatiles.h)
MAP_GENERATOR_POLICY_INPUTS := \
	tools/mapjson/required_map_defines.json \
	tools/mapjson/product_exclusions.json \
	tools/mapjson/product_hidden_item_flags.json \
	tools/persistence/published_allocations.json \
	src/data/heal_locations.json \
	src/data/region_map/region_map_sections.json \
	src/data/region_map/map_section_compatibility.json
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
	$(DEBUG_MAP_NAMES_OUT) \
	$(MAP_SECTION_METADATA_HEADER) \
	$(MAP_SECTION_METADATA_SOURCE) \
	$(INTEGRITY_MANIFEST)

$(MAP_GENERATION_STAMP): $(MAPS_DIR)/map_groups.json $(LAYOUTS_DIR)/layouts.json $(MAP_JSONS) \
		$(MAP_INPUT_DIRS) $(MAP_SCRIPT_REGISTRIES) $(GLOBAL_SCRIPT_INPUT_DIRS) $(GLOBAL_SCRIPT_REGISTRIES) \
		$(LAYOUT_INPUT_DIRS) $(LAYOUT_BINARIES) \
		$(TILESET_REGISTRY_HEADERS) $(TILESET_BLOBS) $(MAP_GENERATOR_POLICY_INPUTS) $(MAPJSON)
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

$(C_BUILDDIR)/debug.o: $(MAP_GROUP_COUNT_OUT) $(DEBUG_MAP_NAMES_OUT)
$(TEST_BUILDDIR)/text.o: $(MAP_GROUP_COUNT_OUT)
$(C_BUILDDIR)/location_codecs.o $(C_BUILDDIR)/regions.o: $(MAP_SECTION_METADATA_HEADER) $(MAP_SECTION_METADATA_SOURCE)

# Retail dialects remain useful generator diagnostics, but never inherit the
# product name or enter a link/release graph.
GENERATOR_FIXTURE_ROOT := $(BUILD_DIR)/fixtures
.PHONY: generator-fixture-emerald generator-fixture-firered generator-fixture-ruby
generator-fixture-emerald generator-fixture-firered generator-fixture-ruby: generator-fixture-%: $(MAPJSON)
	@$(MAPJSON) generate $* $(MAPS_DIR)/map_groups.json $(LAYOUTS_DIR)/layouts.json \
		$(GENERATOR_FIXTURE_ROOT)/$*/current $(MAP_JSONS)
	@echo "Generated diagnostic $* registry fixture under $(GENERATOR_FIXTURE_ROOT)/$*"
