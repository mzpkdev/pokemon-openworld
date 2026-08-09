# GNU Make always executes recipe lines containing $(MAKE), even in dry-run mode.
# Entering the lifetime-lock wrapper from `make -n` would therefore turn an
# inspection into a real build.  Dry runs do not publish build outputs, so keep
# them in this Make process and let the product rules render their recipes.
ifneq (,$(findstring n,$(firstword $(MAKEFLAGS))))
CONTENT_PORT_BUILD_LOCK_HELD := 1
endif

ifneq ($(CONTENT_PORT_BUILD_LOCK_HELD),1)
_CONTENT_PORT_BUILD_GOALS := $(if $(MAKECMDGOALS),$(MAKECMDGOALS),all)
.PHONY: __content-port-build-lock
__content-port-build-lock:
	@if [ -e .git ] || [ -L .git ]; then \
		root="$$(git rev-parse --show-toplevel)" || exit 2; \
		root="$$(cd "$$root" && pwd -P)" || exit 2; \
		current="$$(pwd -P)" || exit 2; \
		if [ "$$root" != "$$current" ]; then \
			echo "content-port: Makefile must run at its Git worktree root" >&2; \
			exit 2; \
		fi; \
		state="$$(git rev-parse --path-format=absolute --git-path content-port-transaction)" || exit 2; \
		case "$$state" in /*/content-port-transaction) ;; \
			*) echo "content-port: invalid transaction state path" >&2; exit 2 ;; \
		esac; \
		mkdir -p "$$state" || exit 2; \
		python3 -c 'import fcntl, os, subprocess, sys; fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o644); fcntl.flock(fd, fcntl.LOCK_SH); raise SystemExit(subprocess.call(sys.argv[2:]))' \
			"$$state/lifetime.lock" $(MAKE) CONTENT_PORT_BUILD_LOCK_HELD=1 $(_CONTENT_PORT_BUILD_GOALS); \
	else \
		$(MAKE) CONTENT_PORT_BUILD_LOCK_HELD=1 $(_CONTENT_PORT_BUILD_GOALS); \
	fi

%:: __content-port-build-lock
	@:

else

# Product identity is deliberately closed.  Diagnostic map dialects are exposed
# only by the generator-fixture-* targets below; they can never select a link.
ifeq ($(origin GAME_VERSION),command line)
  ifneq ($(GAME_VERSION),EMERALD)
    $(error pokemon-openworld requires GAME_VERSION=EMERALD)
  endif
endif
ifeq ($(origin ALL_REGIONS),command line)
  ifneq ($(ALL_REGIONS),1)
    $(error pokemon-openworld requires ALL_REGIONS=1)
  endif
endif
ifeq ($(origin MAP_VERSION),command line)
  ifneq ($(MAP_VERSION),allregions)
    $(error pokemon-openworld requires MAP_VERSION=allregions)
  endif
endif
ifeq ($(origin FILE_NAME),command line)
  ifneq ($(FILE_NAME),pokemon-openworld)
    $(error pokemon-openworld requires FILE_NAME=pokemon-openworld)
  endif
endif

override GAME_VERSION := EMERALD
override TITLE        := POKEMON EMER
override GAME_CODE    := BPEE
override BUILD_NAME   := emerald
override IS_FRLG      := 0
override MAP_VERSION  := allregions
override ALL_REGIONS  := 1

# GBA rom header
MAKER_CODE  := 01
REVISION    := 0
KEEP_TEMPS  ?= 0

# `File name`.gba
override FILE_NAME := pokemon-openworld
BUILD_DIR := build
GENERATED_POLICY_ROOT := $(BUILD_DIR)/generated/$(MAP_VERSION)
GENERATED_ROOT := $(GENERATED_POLICY_ROOT)/current

# Compares the ROM to a checksum of the original - only makes sense using when non-modern
COMPARE     ?= 0
# Executes the Test Runner System that checks that all mechanics work as expected
TEST         ?= 0
# Enables -fanalyzer C flag to analyze in depth potential UBs
ANALYZE      ?= 0
# Count unused warnings as errors. Used by RH-Hideout's repo
UNUSED_ERROR ?= 0
# Count deprecated warnings as errors. Used by RH-Hideout's repo
DEPRECATED_ERROR ?= 0
# Adds -Og and -g flags, which optimize the build for debugging and include debug info respectively
DEBUG        ?= 0
# Adds -flto flag, which increases link time but results in a more efficient binary (especially in audio processing)
LTO          ?= 0
# Makes an optimized build for release, also enabling NDEBUG macro and disabling other debugging features
# Enables LTO by default, but can be changed in the config.mk file
RELEASE      ?= 0

ifeq (compare,$(MAKECMDGOALS))
  COMPARE := 1
endif
ifneq (,$(filter check,$(MAKECMDGOALS)))
  ifneq (,$(filter-out check,$(MAKECMDGOALS)))
    $(error check must be run as a standalone goal)
  endif
  TEST := 1
endif
ifneq (,$(filter debug,$(MAKECMDGOALS)))
  DEBUG := 1
endif
ifneq (,$(filter release tidyrelease,$(MAKECMDGOALS)))
  RELEASE := 1
endif
override _E2E_SUITE_GOALS := e2e-core e2e-extended e2e-integrity
override _E2E_ONLY := 0
ifneq (,$(filter $(_E2E_SUITE_GOALS),$(MAKECMDGOALS)))
  ifneq (,$(filter-out $(_E2E_SUITE_GOALS),$(MAKECMDGOALS)))
    $(error E2E suite goals cannot be combined with non-E2E goals)
  endif
  override _E2E_ONLY := 1
endif

include config.mk

# Default make rule
all: content-port-transaction-check rom

# Toolchain selection
TOOLCHAIN := $(DEVKITARM)
# don't use dkP's base_tools anymore
# because the redefinition of $(CC) conflicts
# with when we want to use $(CC) to preprocess files
# thus, manually create the variables for the bin
# files, or use arm-none-eabi binaries on the system
# if dkP is not installed on this system
ifneq (,$(TOOLCHAIN))
  ifneq ($(wildcard $(TOOLCHAIN)/bin),)
    export PATH := $(TOOLCHAIN)/bin:$(PATH)
  endif
endif

PREFIX := arm-none-eabi-
OBJCOPY := $(PREFIX)objcopy
OBJDUMP := $(PREFIX)objdump
AS := $(PREFIX)as
LD := $(PREFIX)ld

EXE :=
ifeq ($(OS),Windows_NT)
  EXE := .exe
endif

CPP := $(PREFIX)cpp

ifeq ($(RELEASE),1)
override OUTPUT_NAME := $(FILE_NAME)-release
else
override OUTPUT_NAME := $(FILE_NAME)
endif
ifeq ($(DEBUG),1)
override OUTPUT_NAME := $(FILE_NAME)-debug
endif

override ROM_NAME := $(OUTPUT_NAME).gba
# Keep the historical Emerald/ALL_REGIONS=0 object path, but ensure every other
# content-policy tuple has a distinct namespace. Output artifact names stay put.
ifeq ($(MAP_VERSION)-$(ALL_REGIONS),emerald-0)
BUILD_POLICY_SUFFIX :=
else
BUILD_POLICY_SUFFIX := -$(MAP_VERSION)-allregions$(ALL_REGIONS)
endif
OBJ_DIR_NAME := $(BUILD_DIR)/$(BUILD_NAME)$(BUILD_POLICY_SUFFIX)
OBJ_DIR_NAME_TEST := $(BUILD_DIR)/$(BUILD_NAME)$(BUILD_POLICY_SUFFIX)-test
OBJ_DIR_NAME_DEBUG := $(BUILD_DIR)/$(BUILD_NAME)$(BUILD_POLICY_SUFFIX)-debug
OBJ_DIR_NAME_RELEASE := $(BUILD_DIR)/$(BUILD_NAME)$(BUILD_POLICY_SUFFIX)-release
ASSETS_DIR_NAME := $(BUILD_DIR)/assets

override ELF_NAME := $(ROM_NAME:.gba=.elf)
override MAP_NAME := $(ROM_NAME:.gba=.map)
override TESTELF := $(ROM_NAME:.gba=-test.elf)
override HEADLESSELF := $(ROM_NAME:.gba=-test-headless.elf)

# Pick our active variables
override ROM := $(ROM_NAME)
ifneq (,$(filter $(TESTELF) $(HEADLESSELF),$(MAKECMDGOALS)))
  TEST := 1
endif
ifeq ($(DEBUG),1)
  ifeq ($(TEST),1)
    $(error DEBUG=1 and TEST=1 are mutually exclusive)
  endif
  ifeq ($(RELEASE),1)
    $(error DEBUG=1 and RELEASE=1 are mutually exclusive)
  endif
endif
ifeq ($(RELEASE),1)
  ifeq ($(TEST),1)
    $(error RELEASE=1 and TEST=1 are mutually exclusive)
  endif
endif
ifneq (,$(filter $(TESTELF) $(HEADLESSELF),$(MAKECMDGOALS)))
  ifneq (1,$(words $(MAKECMDGOALS)))
    $(error $(TESTELF) must be run as a standalone goal)
  endif
endif
ifeq ($(TEST), 0)
  OBJ_DIR := $(OBJ_DIR_NAME)
else
  OBJ_DIR := $(OBJ_DIR_NAME_TEST)
endif
ifeq ($(DEBUG),1)
  OBJ_DIR := $(OBJ_DIR_NAME_DEBUG)
endif
ifeq ($(RELEASE),1)
  OBJ_DIR := $(OBJ_DIR_NAME_RELEASE)
endif
override ELF := $(ROM:.gba=.elf)
override MAP := $(ROM:.gba=.map)
override SYM := $(ROM:.gba=.sym)

# Select a private live-ABI/evidence tree for the active compiler purpose.  The
# aggregate target sets this explicitly for the two TESTING=1 artifacts because
# they intentionally share an object directory while carrying distinct evidence.
ifeq ($(origin SAVE_ABI_PURPOSE),undefined)
ifeq ($(TEST),1)
ifneq (,$(filter check $(HEADLESSELF),$(MAKECMDGOALS)))
SAVE_ABI_PURPOSE := headless-test
else
SAVE_ABI_PURPOSE := test-runner
endif
else ifeq ($(RELEASE),1)
SAVE_ABI_PURPOSE := release
else ifeq ($(DEBUG),1)
SAVE_ABI_PURPOSE := debug
else
SAVE_ABI_PURPOSE := normal
endif
endif
SAVE_ABI_DIR := $(BUILD_DIR)/save-contract/$(SAVE_ABI_PURPOSE)

# Commonly used directories
C_SUBDIR = src
ASM_SUBDIR = asm
DATA_SRC_SUBDIR = src/data
DATA_ASM_SUBDIR = data
MID_SUBDIR = sound/songs/midi
TEST_SUBDIR = test

C_BUILDDIR = $(OBJ_DIR)/$(C_SUBDIR)
ASM_BUILDDIR = $(OBJ_DIR)/$(ASM_SUBDIR)
DATA_ASM_BUILDDIR = $(OBJ_DIR)/$(DATA_ASM_SUBDIR)
MID_BUILDDIR = $(OBJ_DIR)/$(MID_SUBDIR)
TEST_BUILDDIR = $(OBJ_DIR)/$(TEST_SUBDIR)

SHELL := bash -o pipefail

# Set flags for tools
ASFLAGS := -mcpu=arm7tdmi -march=armv4t -meabi=5 --defsym MODERN=1 --defsym $(GAME_VERSION)=1 --defsym ALL_REGIONS=$(ALL_REGIONS)

SOURCE_INCLUDE_DIR := include
INCLUDE_DIRS := $(SAVE_ABI_DIR)/include $(GENERATED_ROOT)/src $(GENERATED_ROOT)/include $(SOURCE_INCLUDE_DIR)
GENERATED_CONSTANT_INCLUDE_DIR := $(GENERATED_ROOT)/include/constants
CPP_INCLUDE_DIRS := $(GENERATED_CONSTANT_INCLUDE_DIR) $(INCLUDE_DIRS)
INCLUDE_CPP_ARGS := $(CPP_INCLUDE_DIRS:%=-iquote %)
INCLUDE_SCANINC_ARGS := $(CPP_INCLUDE_DIRS:%=-I %)

ifeq ($(DEBUG),1)
O_LEVEL ?= g
else
O_LEVEL ?= 2
endif
INHERITED_CPPFLAGS := $(CPPFLAGS)
BASE_CPPFLAGS := $(INCLUDE_CPP_ARGS) -Wno-trigraphs -DMODERN=1 -DTESTING=$(TEST) -D$(GAME_VERSION) -DALL_REGIONS=$(ALL_REGIONS) -std=gnu17 $(INHERITED_CPPFLAGS)
GENERATED_CONSTANT_HEADERS := $(GENERATED_ROOT)/include/constants/map_groups.h \
                              $(GENERATED_ROOT)/include/constants/layouts.h \
                              $(GENERATED_ROOT)/include/constants/map_event_ids.h
GENERATED_CONSTANT_CPPFLAGS := $(addprefix -include ,$(GENERATED_CONSTANT_HEADERS))
# trainerproc consumes its own party language, not C. Keep the common defines and
# include search paths, but do not inject C declarations ahead of the party data.
override CPPFLAGS = $(BASE_CPPFLAGS) $(GENERATED_CONSTANT_CPPFLAGS)
TRAINER_CPPFLAGS = $(BASE_CPPFLAGS)
ifeq ($(DEBUG),1)
	BASE_CPPFLAGS += -DDEBUG
endif
ifeq ($(RELEASE),1)
	BASE_CPPFLAGS += -DRELEASE
	ifeq ($(USE_LTO_ON_RELEASE),1)
		LTO := 1
	endif
endif
ARMCC := $(PREFIX)gcc
PATH_ARMCC := PATH="$(PATH)" $(ARMCC)
ifeq ($(_E2E_ONLY),0)
CC1 := $(shell $(PATH_ARMCC) --print-prog-name=cc1) -quiet
endif

override CFLAGS += -mthumb -mthumb-interwork -O$(O_LEVEL) -mabi=apcs-gnu -mtune=arm7tdmi -march=armv4t -Wno-pointer-to-int-cast -std=gnu17 -Werror -Wall -Wno-strict-aliasing -Wno-attribute-alias -Woverride-init -Wnonnull -Wenum-conversion

ifneq ($(LTO),0)
  ifneq ($(TEST),1)
    override CFLAGS += -flto=auto -fno-fat-lto-objects -fno-asynchronous-unwind-tables -ffunction-sections -fdata-sections
  endif
endif

ifeq ($(ANALYZE),1)
  override CFLAGS += -fanalyzer
endif
# Only throw an error for unused elements if its RH-Hideout's repo
ifeq ($(UNUSED_ERROR),0)
  ifneq ($(GITHUB_REPOSITORY_OWNER),rh-hideout)
    override CFLAGS += -Wno-error=unused-variable -Wno-error=unused-const-variable -Wno-error=unused-parameter -Wno-error=unused-function -Wno-error=unused-but-set-parameter -Wno-error=unused-but-set-variable -Wno-error=unused-value -Wno-error=unused-local-typedefs
  endif
endif

ifeq ($(DEPRECATED_ERROR),0)
  ifneq ($(GITHUB_REPOSITORY_OWNER),rh-hideout)
    override CFLAGS += -Wno-error=deprecated-declarations
  endif
endif

ifeq ($(_E2E_ONLY),0)
LIBPATH := -L "$(dir $(shell $(PATH_ARMCC) -mthumb -print-file-name=libgcc.a))" -L "$(dir $(shell $(PATH_ARMCC) -mthumb -print-file-name=libnosys.a))" -L "$(dir $(shell $(PATH_ARMCC) -mthumb -print-file-name=libc.a))"
endif
LIB := $(LIBPATH) -lc -lnosys -lgcc -L../../libagbsyscall -lagbsyscall
# Enable debug info if set
ifeq ($(DINFO),1)
  override CFLAGS += -g
else
  ifeq ($(DEBUG),1)
    override CFLAGS += -g
  endif
endif

ifeq ($(NOOPT),1)
override CFLAGS := $(filter-out -O1 -Og -O2,$(CFLAGS))
override CFLAGS += -O0
endif

# Variable filled out in other make files
AUTO_GEN_TARGETS :=
include make_tools.mk
# Tool executables
SMOLTM       := $(TOOLS_DIR)/compresSmol/compresSmolTilemap$(EXE)
SMOL         := $(TOOLS_DIR)/compresSmol/compresSmol$(EXE)
GFX          := $(TOOLS_DIR)/gbagfx/gbagfx$(EXE)
WAV2AGB      := $(TOOLS_DIR)/wav2agb/wav2agb$(EXE)
MID          := $(TOOLS_DIR)/mid2agb/mid2agb$(EXE)
SCANINC      := $(TOOLS_DIR)/scaninc/scaninc$(EXE)
PREPROC      := $(TOOLS_DIR)/preproc/preproc$(EXE)
RAMSCRGEN    := $(TOOLS_DIR)/ramscrgen/ramscrgen$(EXE)
FIX          := $(TOOLS_DIR)/gbafix/gbafix$(EXE)
BUNDLED_MAPJSON := $(TOOLS_DIR)/mapjson/mapjson$(EXE)
MAPJSON      ?= $(BUNDLED_MAPJSON)
JSONPROC     := $(TOOLS_DIR)/jsonproc/jsonproc$(EXE)
BUNDLED_TRAINERPROC := $(TOOLS_DIR)/trainerproc/trainerproc$(EXE)
TRAINERPROC  ?= $(BUNDLED_TRAINERPROC)
PATCHELF     := $(TOOLS_DIR)/patchelf/patchelf$(EXE)
# Generated map sources name the executable as a prerequisite.  Give the
# bundled executable a real source-aware rule so a missing or stale tool is
# rebuilt before map generation in the same make invocation.  An external
# MAPJSON override must remain an ordinary prerequisite and skip this rule.
ifeq ($(MAPJSON),$(BUNDLED_MAPJSON))
$(BUNDLED_MAPJSON): $(TOOLS_DIR)/mapjson/json11.cpp \
                    $(TOOLS_DIR)/mapjson/json11.h \
                    $(TOOLS_DIR)/mapjson/mapjson.cpp \
                    $(TOOLS_DIR)/mapjson/mapjson.h \
                    $(TOOLS_DIR)/mapjson/Makefile
	@$(MAKE) -C $(TOOLS_DIR)/mapjson -B $(notdir $@)
endif
ifeq ($(shell uname),Darwin)
    ROMTEST ?= $(shell command -v mgba-rom-test-mac 2>/dev/null || echo $(TOOLS_DIR)/mgba/mgba-rom-test-mac)
    ROMTESTHYDRA := $(shell command -v mgba-rom-test-hydra 2>/dev/null || echo $(TOOLS_DIR)/mgba-rom-test-hydra/mgba-rom-test-hydra)
else ifeq ($(shell uname),Linux)
    ROMTEST ?= $(shell command -v mgba-rom-test 2>/dev/null || echo $(TOOLS_DIR)/mgba/mgba-rom-test)
    ROMTESTHYDRA := $(shell command -v mgba-rom-test-hydra 2>/dev/null || echo $(TOOLS_DIR)/mgba-rom-test-hydra/mgba-rom-test-hydra)
else
    ROMTEST ?= $(TOOLS_DIR)/mgba/mgba-rom-test$(EXE)
    ROMTESTHYDRA := $(TOOLS_DIR)/mgba-rom-test-hydra/mgba-rom-test-hydra$(EXE)
endif

# Learnset helper is a Python script
LEARNSET_HELPERS_DIR := $(TOOLS_DIR)/learnset_helpers
LEARNSET_HELPERS_DATA_DIR := $(LEARNSET_HELPERS_DIR)/porymoves_files
LEARNSET_HELPERS_BUILD_DIR := $(LEARNSET_HELPERS_DIR)/build
ALL_LEARNABLES_JSON := $(DATA_SRC_SUBDIR)/pokemon/all_learnables.json
ALL_TUTORS_JSON := $(LEARNSET_HELPERS_BUILD_DIR)/all_tutors.json
ALL_TEACHING_TYPES_JSON := $(LEARNSET_HELPERS_BUILD_DIR)/all_teaching_types.json

# wild_encounters.h is generated by a Python script
WILD_ENCOUNTERS_TOOL_DIR := $(TOOLS_DIR)/wild_encounters
AUTO_GEN_TARGETS += $(DATA_SRC_SUBDIR)/wild_encounters.h

MISC_TOOL_DIR := $(TOOLS_DIR)/misc
SCRIPT_COMMANDS_HEADER := $(SOURCE_INCLUDE_DIR)/constants/script_commands.h
AUTO_GEN_TARGETS += $(SCRIPT_COMMANDS_HEADER)

$(DATA_SRC_SUBDIR)/wild_encounters.h: $(DATA_SRC_SUBDIR)/wild_encounters.json $(WILD_ENCOUNTERS_TOOL_DIR)/wild_encounters_to_header.py $(SOURCE_INCLUDE_DIR)/config/overworld.h $(SOURCE_INCLUDE_DIR)/config/dexnav.h
	python3 $(WILD_ENCOUNTERS_TOOL_DIR)/wild_encounters_to_header.py

$(SCRIPT_COMMANDS_HEADER): $(MISC_TOOL_DIR)/make_scr_cmd_constants.py $(DATA_ASM_SUBDIR)/script_cmd_table.inc
	python3  $(MISC_TOOL_DIR)/make_scr_cmd_constants.py

PERL := perl
SHA1 := $(shell { command -v sha1sum || command -v shasum; } 2>/dev/null) -c

MAKEFLAGS += --no-print-directory

# Clear the default suffixes
.SUFFIXES:
# Don't delete intermediate files
.SECONDARY:
# Delete files that weren't built properly
.DELETE_ON_ERROR:

RULES_NO_SCAN += libagbsyscall clean clean-assets tidy tidymodern tidycheck tidydebug tidyrelease generated clean-generated clean-teachables clean-teachables_intermediates
RULES_NO_SCAN += _e2e-build-debug-artifacts _e2e-require-artifacts _e2e-skyemu e2e-core e2e-extended e2e-integrity integrity-check integrity-check-all-purposes save-contract-check build-variant-isolation-check format format-check lint lint-check
RULES_NO_SCAN += content-port-transaction-check content-port-check content-port-bundle content-port-test
RULES_NO_SCAN += generator-fixture-emerald generator-fixture-firered generator-fixture-ruby
.PHONY: all rom agbcc modern compare check debug release format format-check lint lint-check
.PHONY: _e2e-build-debug-artifacts _e2e-require-artifacts _e2e-skyemu e2e-core e2e-extended e2e-integrity integrity-check integrity-check-all-purposes save-contract-check build-variant-isolation-check
.PHONY: content-port-transaction-check content-port-check content-port-bundle content-port-test
.PHONY: $(RULES_NO_SCAN)

infoshell = $(foreach line, $(shell $1 | sed "s/ /__SPACE__/g"), $(info $(subst __SPACE__, ,$(line))))

# Check if we need to scan dependencies based on the chosen rule OR user preference
NODEP ?= 0
# Check if we need to pre-build tools and generate assets based on the chosen rule.
SETUP_PREREQS ?= 1
# Disable dependency scanning for rules that don't need it.
ifneq (,$(MAKECMDGOALS))
  ifeq (,$(filter-out $(RULES_NO_SCAN),$(MAKECMDGOALS)))
    NODEP := 1
    SETUP_PREREQS := 0
  endif
endif

.SHELLSTATUS ?= 0

ifeq ($(SETUP_PREREQS),1)
  # This runs before parse-time tool and source generation, which otherwise
  # precedes the normal prerequisite graph and could consume a mixed tree.
  $(foreach line, $(shell python3 -m tools.content_port transaction-check --repo . 2>&1 | sed "s/ /__SPACE__/g"), $(info $(subst __SPACE__, ,$(line))))
  ifneq ($(.SHELLSTATUS),0)
    $(error Active content-port transaction blocks build setup)
  endif
  # If set on: Default target or a rule requiring a scan
  # Forcibly execute `make tools` since we need them for what we are doing.
  $(foreach line, $(shell $(MAKE) -f make_tools.mk | sed "s/ /__SPACE__/g"), $(info $(subst __SPACE__, ,$(line))))
  ifneq ($(.SHELLSTATUS),0)
    $(error Errors occurred while building tools. See error messages above for more details)
  endif
  # Oh and also generate mapjson sources before we use `SCANINC`.
  $(foreach line, $(shell $(MAKE) MAP_VERSION=$(MAP_VERSION) generated | sed "s/ /__SPACE__/g"), $(info $(subst __SPACE__, ,$(line))))
  ifneq ($(.SHELLSTATUS),0)
    $(error Errors occurred while generating map-related sources. See error messages above for more details)
  endif
endif

# Collect sources
C_SRCS_IN := $(wildcard $(C_SUBDIR)/*.c $(C_SUBDIR)/*/*.c $(C_SUBDIR)/*/*/*.c)
C_SRCS := $(foreach src,$(C_SRCS_IN),$(if $(findstring .inc.c,$(src)),,$(src)))
C_OBJS := $(patsubst $(C_SUBDIR)/%.c,$(C_BUILDDIR)/%.o,$(C_SRCS))

TEST_SRCS_IN := $(wildcard $(TEST_SUBDIR)/*.c $(TEST_SUBDIR)/*/*.c $(TEST_SUBDIR)/*/*/*.c)
TEST_SRCS := $(foreach src,$(TEST_SRCS_IN),$(if $(findstring .inc.c,$(src)),,$(src)))
TEST_OBJS := $(patsubst $(TEST_SUBDIR)/%.c,$(TEST_BUILDDIR)/%.o,$(TEST_SRCS))
TEST_OBJS_REL := $(patsubst $(OBJ_DIR)/%,%,$(TEST_OBJS))

C_ASM_SRCS := $(wildcard $(C_SUBDIR)/*.s $(C_SUBDIR)/*/*.s $(C_SUBDIR)/*/*/*.s)
C_ASM_OBJS := $(patsubst $(C_SUBDIR)/%.s,$(C_BUILDDIR)/%.o,$(C_ASM_SRCS))

ASM_SRCS := $(wildcard $(ASM_SUBDIR)/*.s)
ASM_OBJS := $(patsubst $(ASM_SUBDIR)/%.s,$(ASM_BUILDDIR)/%.o,$(ASM_SRCS))

DATA_ASM_SRCS := $(wildcard $(DATA_ASM_SUBDIR)/*.s)
DATA_ASM_OBJS := $(patsubst $(DATA_ASM_SUBDIR)/%.s,$(DATA_ASM_BUILDDIR)/%.o,$(DATA_ASM_SRCS))

MID_SRCS := $(wildcard $(MID_SUBDIR)/*.mid)
MID_OBJS := $(patsubst $(MID_SUBDIR)/%.mid,$(MID_BUILDDIR)/%.o,$(MID_SRCS))

OBJS     := $(C_OBJS) $(C_ASM_OBJS) $(ASM_OBJS) $(DATA_ASM_OBJS) $(MID_OBJS)
OBJS_REL := $(patsubst $(OBJ_DIR)/%,%,$(OBJS))

SUBDIRS  := $(sort $(dir $(OBJS) $(dir $(TEST_OBJS))))
$(shell mkdir -p $(SUBDIRS))

# Pretend rules that are actually flags defer to `make all`
modern: all
compare: all
debug: all
release: all
# Uncomment the next line, and then comment the 4 lines after it to reenable agbcc.
#agbcc: all
agbcc:
	@echo "'make agbcc' is deprecated as of pokeemerald-expansion 1.9 and will be removed in 1.10."
	@echo "Search for 'agbcc: all' in Makefile to reenable agbcc."
	@exit 1

LD_SCRIPT_TEST := ld_script_test.ld

$(OBJ_DIR)/ld_script_test.ld: $(LD_SCRIPT_TEST)
	cd $(OBJ_DIR) && sed "s#tools/#../../tools/#g" ../../$(LD_SCRIPT_TEST) > ld_script_test.ld

$(TESTELF): $(OBJ_DIR)/ld_script_test.ld $(OBJS) $(TEST_OBJS) libagbsyscall tools check-tools | content-port-transaction-check
	@echo "cd $(OBJ_DIR) && $(LD) -T ld_script_test.ld -o ../../$@ <objects> <test-objects> <lib>"
	@cd $(OBJ_DIR) && $(LD) $(TESTLDFLAGS) --undefined=gSaveAbiEvidence -T ld_script_test.ld -o ../../$@ $(OBJS_REL) $(TEST_OBJS_REL) $(LIB)
	$(FIX) $@ -t"$(TITLE)" -c$(GAME_CODE) -m$(MAKER_CODE) -r$(REVISION) -d0 --silent
	$(PATCHELF) $(TESTELF) gTestRunnerArgv "$(TESTS:%*=%)\0"

TEST_SKIP_IS_FAIL := \x01

$(HEADLESSELF): $(TESTELF) | content-port-transaction-check
	@cp $(TESTELF) $@
	$(PATCHELF) $(HEADLESSELF) gTestRunnerHeadless '\x01' gTestRunnerSkipIsFail "$(TEST_SKIP_IS_FAIL)"

check: content-port-transaction-check save-contract-check $(HEADLESSELF)
	$(ROMTESTHYDRA) $(ROMTEST) $(OBJCOPY) $(HEADLESSELF)

CONTENT_PORT ?= johto
CONTENT_PORT_DONOR_ROOT ?= .references
CONTENT_PORT_OUTPUT ?= $(BUILD_DIR)/content-port/$(CONTENT_PORT)

content-port-transaction-check:
	@if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
		python3 -m tools.content_port transaction-check --repo .; \
	fi

content-port-test: content-port-transaction-check
	CONTENT_PORT_DONOR_ROOT=$(CONTENT_PORT_DONOR_ROOT) \
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
		-s tools/content_port/tests -p 'test_*.py' -q

content-port-check: content-port-transaction-check
	python3 -m tools.content_port check --port $(CONTENT_PORT) \
		--donor-root $(CONTENT_PORT_DONOR_ROOT)

content-port-bundle: content-port-transaction-check
	python3 -m tools.content_port bundle --port $(CONTENT_PORT) \
		--donor-root $(CONTENT_PORT_DONOR_ROOT) --output $(CONTENT_PORT_OUTPUT)

RUFF_VENV := $(BUILD_DIR)/ruff-venv
RUFF_PYTHON := $(RUFF_VENV)/bin/python
RUFF := $(RUFF_VENV)/bin/ruff
RUFF_REQUIREMENTS := tools/ruff/requirements.txt
RUFF_REQUIREMENTS_STAMP := $(RUFF_VENV)/.requirements-v1

$(RUFF_PYTHON):
	python3 -m venv $(RUFF_VENV)

$(RUFF_REQUIREMENTS_STAMP): $(RUFF_REQUIREMENTS) $(RUFF_PYTHON)
	$(RUFF_PYTHON) -m pip install --disable-pip-version-check -r $(RUFF_REQUIREMENTS)
	@touch $@

format: content-port-transaction-check $(RUFF_REQUIREMENTS_STAMP)
	$(RUFF) format .

format-check: content-port-transaction-check $(RUFF_REQUIREMENTS_STAMP)
	$(RUFF) format --check .

lint: content-port-transaction-check $(RUFF_REQUIREMENTS_STAMP)
	$(RUFF) check --fix .

lint-check: content-port-transaction-check $(RUFF_REQUIREMENTS_STAMP)
	$(RUFF) check .

E2E_VENV := $(BUILD_DIR)/e2e-venv
E2E_PYTHON := $(E2E_VENV)/bin/python
E2E_REQUIREMENTS := tools/e2e/requirements.txt
E2E_REQUIREMENTS_STAMP := $(E2E_VENV)/.requirements-v1
E2E_TOOLS_DIR := $(BUILD_DIR)/e2e-tools
E2E_ROM := $(FILE_NAME)-debug.gba
E2E_SYMS := $(FILE_NAME)-debug.sym
SKYEMU := $(E2E_TOOLS_DIR)/SkyEmu-v5

# E2E-only parsing deliberately omits the ROM rules above. Re-enter make once
# with the debug purpose selected so the artifacts are refreshed by the same
# generated-source, object, link, ROM, and symbol dependency graph as a normal
# debug build. CI may trust artifacts produced by its required build job for the
# exact same commit; local runs always traverse the graph.
_e2e-build-debug-artifacts: content-port-transaction-check
ifeq ($(E2E_PREBUILT_DEBUG),1)
	@:
else
	+$(MAKE) DEBUG=1 $(E2E_ROM) $(E2E_SYMS)
endif

_e2e-require-artifacts: content-port-transaction-check _e2e-build-debug-artifacts
	@missing=0; \
	for artifact in "$(E2E_ROM)" "$(E2E_SYMS)"; do \
		if [[ ! -f "$$artifact" ]]; then \
			echo "Missing required E2E artifact: $$artifact" >&2; \
			missing=1; \
		fi; \
	done; \
	if (( missing )); then \
		echo "Prepare the debug artifacts first with: make DEBUG=1 $(E2E_ROM) $(E2E_SYMS)" >&2; \
		exit 1; \
	fi

build-variant-isolation-check: content-port-transaction-check
	@test -f $(FILE_NAME).sym -a -f $(FILE_NAME)-debug.sym || { \
		echo "Build normal and debug symbol artifacts before checking variant isolation." >&2; \
		exit 1; \
	}
	@grep -Eq 'DebugAction_Util_Warp_SelectNamedMapGroup' $(FILE_NAME).sym
	@grep -Eq 'gDebugNamedWarpRegistryIdentity' $(FILE_NAME).sym
	@grep -Eq 'DebugAction_Util_Warp_SelectNamedMapGroup' $(FILE_NAME)-debug.sym
	@grep -Eq 'gDebugNamedWarpRegistryIdentity' $(FILE_NAME)-debug.sym
	@! grep -Eq 'DebugAction_Util_Warp_Select(MapGroup|Map|Warp)$$' $(FILE_NAME).sym $(FILE_NAME)-debug.sym

$(E2E_PYTHON):
	python3 -m venv $(E2E_VENV)

$(E2E_REQUIREMENTS_STAMP): $(E2E_REQUIREMENTS) $(E2E_PYTHON)
	$(E2E_PYTHON) -m pip install --disable-pip-version-check -r $(E2E_REQUIREMENTS)
	@touch $@

_e2e-skyemu: tools/e2e/install_skyemu.py
	python3 tools/e2e/install_skyemu.py --output $(SKYEMU)

e2e-core: content-port-transaction-check _e2e-require-artifacts _e2e-skyemu $(E2E_REQUIREMENTS_STAMP)
	E2E_ROM=$(E2E_ROM) E2E_SYMS=$(E2E_SYMS) SKYEMU=$(SKYEMU) \
	E2E_RESULTS=test-results/e2e E2E_SUITE=core \
	$(E2E_PYTHON) tools/e2e/run.py core

e2e-extended: content-port-transaction-check _e2e-require-artifacts _e2e-skyemu $(E2E_REQUIREMENTS_STAMP)
	E2E_ROM=$(E2E_ROM) E2E_SYMS=$(E2E_SYMS) SKYEMU=$(SKYEMU) \
	E2E_RESULTS=test-results/e2e E2E_SUITE=extended \
	$(E2E_PYTHON) tools/e2e/run.py extended

e2e-integrity: content-port-transaction-check _e2e-require-artifacts _e2e-skyemu $(E2E_REQUIREMENTS_STAMP)
	E2E_ROM=$(E2E_ROM) E2E_SYMS=$(E2E_SYMS) SKYEMU=$(SKYEMU) \
	E2E_RESULTS=test-results/e2e E2E_SUITE=integrity \
	$(E2E_PYTHON) tools/e2e/run.py integrity

CAPACITY_POLICY := tools/integrity/capacity_policy.json
SAVE_CONTRACT := tools/integrity/save_contract.json
LIVE_SAVE_ABI := $(SAVE_ABI_DIR)/live-save-abi.json
LINKED_SAVE_ABI := $(SAVE_ABI_DIR)/include/save_abi_evidence.inc
ifeq ($(RELEASE),1)
INTEGRITY_PURPOSE := release
else ifeq ($(DEBUG),1)
INTEGRITY_PURPOSE := debug
else
INTEGRITY_PURPOSE := normal
endif
INTEGRITY_REPORT ?= $(BUILD_DIR)/integrity/$(INTEGRITY_PURPOSE).json
PURPOSE_REPORT_DIR := $(BUILD_DIR)/integrity/purposes

$(LIVE_SAVE_ABI): $(SAVE_CONTRACT) tools/persistence/contract.py tools/persistence/abi_anchor.c src/record_mixing.c $(shell find include -type f -name '*.h') | content-port-transaction-check
	@mkdir -p $(dir $(LIVE_SAVE_ABI))
	python3 tools/persistence/contract.py validate-contract --contract $(SAVE_CONTRACT)
	python3 tools/persistence/contract.py measure-abi --tree . --purpose $(SAVE_ABI_PURPOSE) --output $(LIVE_SAVE_ABI)
	python3 tools/persistence/contract.py validate --contract $(SAVE_CONTRACT) --abi $(LIVE_SAVE_ABI) --purpose $(SAVE_ABI_PURPOSE)

$(LINKED_SAVE_ABI): $(LIVE_SAVE_ABI)
	python3 tools/persistence/contract.py generate-abi-evidence --abi $(LIVE_SAVE_ABI) --output $@

$(C_BUILDDIR)/save_abi.o: $(LINKED_SAVE_ABI)

save-contract-check: content-port-transaction-check $(LINKED_SAVE_ABI)

integrity-check: content-port-transaction-check $(CAPACITY_POLICY) save-contract-check
	+$(MAKE) $(ROM) $(SYM)
	@mkdir -p $(dir $(INTEGRITY_REPORT))
	python3 tools/integrity/validate_artifact.py \
		--rom $(ROM) --map $(MAP) --sym $(SYM) \
		--manifest $(INTEGRITY_MANIFEST) --capacity-policy $(CAPACITY_POLICY) \
		--save-contract $(SAVE_CONTRACT) --purpose $(INTEGRITY_PURPOSE) \
		--output $(INTEGRITY_REPORT)

integrity-check-all-purposes: content-port-transaction-check
	@rm -rf $(PURPOSE_REPORT_DIR)
	@mkdir -p $(PURPOSE_REPORT_DIR)
	+$(MAKE) integrity-check SAVE_ABI_PURPOSE=normal INTEGRITY_PURPOSE=normal INTEGRITY_REPORT=$(PURPOSE_REPORT_DIR)/normal.json
	+$(MAKE) DEBUG=1 integrity-check SAVE_ABI_PURPOSE=debug INTEGRITY_PURPOSE=debug INTEGRITY_REPORT=$(PURPOSE_REPORT_DIR)/debug.json
	+$(MAKE) RELEASE=1 integrity-check SAVE_ABI_PURPOSE=release INTEGRITY_PURPOSE=release INTEGRITY_REPORT=$(PURPOSE_REPORT_DIR)/release.json
	+$(MAKE) SAVE_ABI_PURPOSE=test-runner $(TESTELF)
	python3 tools/integrity/validate_artifact.py --elf $(TESTELF) --purpose test-runner \
		--save-contract $(SAVE_CONTRACT) --output $(PURPOSE_REPORT_DIR)/test-runner.json
	+$(MAKE) SAVE_ABI_PURPOSE=headless-test $(HEADLESSELF)
	python3 tools/integrity/validate_artifact.py --elf $(HEADLESSELF) --purpose headless-test \
		--save-contract $(SAVE_CONTRACT) --output $(PURPOSE_REPORT_DIR)/headless-test.json
	python3 tools/persistence/contract.py validate-budgets \
		--contract $(SAVE_CONTRACT) --reports $(PURPOSE_REPORT_DIR)

# Other rules
rom: content-port-transaction-check $(ROM)
ifeq ($(COMPARE),1)
	@$(SHA1) rom.sha1
endif

syms: content-port-transaction-check $(SYM)

clean: tidy clean-tools clean-check-tools clean-generated clean-assets
	@$(MAKE) clean -C libagbsyscall
	@rm -rf $(BUILD_DIR)/integrity/purposes $(BUILD_DIR)/save-contract

clean-assets:
	rm -rf $(ASSETS_DIR_NAME)
	rm -f $(MID_SUBDIR)/*.s
	rm -f $(DATA_ASM_SUBDIR)/layouts/layouts.inc $(DATA_ASM_SUBDIR)/layouts/layouts_table.inc
	rm -f $(DATA_ASM_SUBDIR)/maps/connections.inc $(DATA_ASM_SUBDIR)/maps/events.inc $(DATA_ASM_SUBDIR)/maps/groups.inc $(DATA_ASM_SUBDIR)/maps/headers.inc $(DATA_SRC_SUBDIR)/map_group_count.h
	rm -f .map_version
	rm -rf $(BUILD_DIR)/generated
	find sound -iname '*.bin' -exec rm {} +
	find . \( -iname '*.1bpp' -o -iname '*.4bpp' -o -iname '*.8bpp' -o -iname '*.gbapal' -o -iname '*.lz' -o -iname '*.smol' -o -iname '*.fastSmol' -o -iname '*.smolTM' -o -iname '*.rl' -o -iname '*.latfont' -o -iname '*.hwjpnfont' -o -iname '*.fwjpnfont' \) -exec rm {} +
	find $(DATA_ASM_SUBDIR)/maps \( -iname 'connections.inc' -o -iname 'events.inc' -o -iname 'header.inc' \) -exec rm {} +

tidy: tidymodern tidycheck tidydebug tidyrelease

tidymodern:
	rm -f pokemon-openworld.gba pokemon-openworld.elf pokemon-openworld.map pokemon-openworld.sym
	rm -rf $(OBJ_DIR_NAME)

tidycheck:
	rm -f $(FILE_NAME)-test.elf $(FILE_NAME)-test-headless.elf
	rm -rf $(OBJ_DIR_NAME_TEST)

tidydebug:
	rm -f $(FILE_NAME)-debug.gba $(FILE_NAME)-debug.elf $(FILE_NAME)-debug.map $(FILE_NAME)-debug.sym
	rm -rf $(OBJ_DIR_NAME_DEBUG)
	# Remove artifacts left by the legacy E2E compile mode.
	rm -f $(FILE_NAME)-e2e.gba $(FILE_NAME)-e2e.elf $(FILE_NAME)-e2e.map $(FILE_NAME)-e2e.sym
	rm -rf $(BUILD_DIR)/$(BUILD_NAME)-e2e

tidyrelease:
ifeq ($(RELEASE),1)
	rm -f $(ROM_NAME) $(ELF_NAME) $(MAP_NAME) $(ROM_NAME:.gba=.sym)
else # Manually remove the release files on clean/tidy
	rm -f $(FILE_NAME)-release.gba $(FILE_NAME)-release.elf $(FILE_NAME)-release.map $(FILE_NAME)-release.sym
endif
	rm -rf $(OBJ_DIR_NAME_RELEASE)

# Other rules
include graphics_file_rules.mk
include map_data_rules.mk
include spritesheet_rules.mk
include json_data_rules.mk
include audio_rules.mk
include trainer_rules.mk

# Every C translation unit is preprocessed with these generated constants forced
# in, so their object targets must carry the same dependency.  A present policy
# stamp is not sufficient evidence of a complete atomic generation: if any
# forced header is absent, invalidate the authority and let mapjson repromote the
# complete tree before an object recipe starts.
ifneq ($(words $(wildcard $(GENERATED_CONSTANT_HEADERS))),$(words $(GENERATED_CONSTANT_HEADERS)))
.PHONY: $(MAP_GENERATION_STAMP)
endif
$(C_OBJS) $(TEST_OBJS): $(MAP_GENERATION_STAMP) $(GENERATED_CONSTANT_HEADERS) | content-port-transaction-check
$(OBJS) $(TEST_OBJS): | content-port-transaction-check

$(AUTO_GEN_TARGETS): | content-port-transaction-check

# NOTE: Tools must have been built prior (FIXME)
# so you can't really call this rule directly
generated: content-port-transaction-check $(AUTO_GEN_TARGETS)
	@: # Silence the "Nothing to be done for `generated'" message, which some people were confusing for an error.


%.s:   ;
%.png: ;
%.pal: ;
%.wav: ;

%.1bpp:     %.png  ; $(GFX) $< $@
%.4bpp:     %.png  ; $(GFX) $< $@
%.8bpp:     %.png  ; $(GFX) $< $@
%.gbapal:   %.pal  ; $(GFX) $< $@
%.gbapal:   %.png  ; $(GFX) $< $@
%.lz:       %      ; $(GFX) $< $@
%.smolTM:   %      ; $(SMOLTM) $< $@
%.fastSmol: %      ; $(SMOL) -w $< $@ false false false
%.smol:     %      ; $(SMOL) -w $< $@
%.rl:       %      ; $(GFX) $< $@

clean-teachables_intermediates:
	rm -f $(DATA_SRC_SUBDIR)/tutor_moves.h
	rm -f $(DATA_SRC_SUBDIR)/pokemon/teachable_learnsets.h
	@rm -Rf $(LEARNSET_HELPERS_BUILD_DIR)
	@echo "rm -Rf <LEARNSET_HELPERS_BUILD_DIR>"

clean-generated: clean-teachables_intermediates
	@rm -f $(AUTO_GEN_TARGETS)
	@echo "rm -f <AUTO_GEN_TARGETS>"
	@rm -rf $(BUILD_DIR)/generated
	@echo "rm -rf $(BUILD_DIR)/generated"

clean-teachables: clean-teachables_intermediates
	rm -f $(ALL_LEARNABLES_JSON)
	@touch $(C_SUBDIR)/pokemon.c

$(C_BUILDDIR)/librfu_intr.o: CFLAGS := -mthumb-interwork -O2 -mabi=apcs-gnu -mtune=arm7tdmi -march=armv4t -fno-toplevel-reorder -Wno-pointer-to-int-cast
$(C_BUILDDIR)/berry_crush.o: override CFLAGS += -Wno-address-of-packed-member
$(C_BUILDDIR)/agb_flash.o: override CFLAGS += -fno-toplevel-reorder
$(C_BUILDDIR)/pokedex_plus_hgss.o: CFLAGS := -mthumb -mthumb-interwork -O2 -mabi=apcs-gnu -mtune=arm7tdmi -march=armv4t -Wno-pointer-to-int-cast -std=gnu17 -Werror -Wall -Wno-strict-aliasing -Wno-attribute-alias -Woverride-init
# Annoyingly we can't turn this on just for src/data/trainers.h
$(C_BUILDDIR)/data.o: CFLAGS += -fno-show-column -fno-diagnostics-show-caret

# Needed for parity with pret
$(C_BUILDDIR)/graphics.o: override CFLAGS += -Wno-missing-braces

# Dependency rules (for the *.c & *.s sources to .o files)
# Have to be explicit or else missing files won't be reported.
$(C_BUILDDIR)/move_relearner.o: $(C_SUBDIR)/move_relearner.c $(DATA_SRC_SUBDIR)/tutor_moves.h
$(C_BUILDDIR)/pokemon.o: $(C_SUBDIR)/pokemon.c $(DATA_SRC_SUBDIR)/pokemon/teachable_learnsets.h

# As a side effect, they're evaluated immediately instead of when the rule is invoked.
# It doesn't look like $(shell) can be deferred so there might not be a better way (Icedude_907: there is soon).

$(C_BUILDDIR)/%.o: $(C_SUBDIR)/%.c
ifneq ($(KEEP_TEMPS),1)
	@echo "$(CC1) <flags> -o $@ $<"
	@$(CPP) $(CPPFLAGS) $< | $(PREPROC) -i -g $(ASSETS_DIR_NAME) $< charmap.txt | $(CC1) $(CFLAGS) -o - - | cat - <(echo -e ".text\n\t.align\t2, 0") | $(AS) $(ASFLAGS) -o $@ -
else
	@$(CPP) $(CPPFLAGS) $< -o $(C_BUILDDIR)/$*.i
	@$(PREPROC) -g $(ASSETS_DIR_NAME) $(C_BUILDDIR)/$*.i charmap.txt | $(CC1) $(CFLAGS) -o $(C_BUILDDIR)/$*.s
	@echo -e ".text\n\t.align\t2, 0\n" >> $(C_BUILDDIR)/$*.s
	$(AS) $(ASFLAGS) -o $@ $(C_BUILDDIR)/$*.s
endif

$(C_BUILDDIR)/%.d: $(C_SUBDIR)/%.c
	$(SCANINC) -M $@ -g $(ASSETS_DIR_NAME) $(INCLUDE_SCANINC_ARGS) -I tools/agbcc/include $<

ifneq ($(NODEP),1)
-include $(ALL_TUTORS_JSON), $(ALL_TEACHING_TYPES_JSON),
-include $(addprefix $(OBJ_DIR)/,$(C_SRCS:.c=.d))
endif

ifeq ($(TEST),1)
$(TEST_BUILDDIR)/%.o: $(TEST_SUBDIR)/%.c
	@echo "$(CC1) <flags> -o $@ $<"
	@$(CPP) $(CPPFLAGS) $< | $(PREPROC) -i -g $(ASSETS_DIR_NAME) $< charmap.txt | $(CC1) $(CFLAGS) -o - - | cat - <(echo -e ".text\n\t.align\t2, 0") | $(AS) $(ASFLAGS) -o $@ -

$(TEST_BUILDDIR)/%.d: $(TEST_SUBDIR)/%.c
	$(SCANINC) -M $@ -g $(ASSETS_DIR_NAME) $(INCLUDE_SCANINC_ARGS) -I tools/agbcc/include $<

ifneq ($(NODEP),1)
-include $(addprefix $(OBJ_DIR)/,$(TEST_SRCS:.c=.d))
endif
endif

$(ASM_BUILDDIR)/%.o: $(ASM_SUBDIR)/%.s
	$(AS) $(ASFLAGS) -o $@ $<

$(ASM_BUILDDIR)/%.d: $(ASM_SUBDIR)/%.s
	$(SCANINC) -M $@ -g $(ASSETS_DIR_NAME) $(INCLUDE_SCANINC_ARGS) -I "" $<

ifneq ($(NODEP),1)
-include $(addprefix $(OBJ_DIR)/,$(ASM_SRCS:.s=.d))
endif

$(C_BUILDDIR)/%.o: $(C_SUBDIR)/%.s
	$(PREPROC) $< charmap.txt | $(CPP) $(CPPFLAGS) $(INCLUDE_SCANINC_ARGS) - | $(PREPROC) -ie $< charmap.txt | $(AS) $(ASFLAGS) -o $@

$(C_BUILDDIR)/%.d: $(C_SUBDIR)/%.s
	$(SCANINC) -M $@ -g $(ASSETS_DIR_NAME) $(INCLUDE_SCANINC_ARGS) -I "" $<

ifneq ($(NODEP),1)
-include $(addprefix $(OBJ_DIR)/,$(C_ASM_SRCS:.s=.d))
endif

$(DATA_ASM_BUILDDIR)/%.o: $(DATA_ASM_SUBDIR)/%.s
	$(PREPROC) -s $< charmap.txt | $(CPP) $(CPPFLAGS) $(INCLUDE_SCANINC_ARGS) - | $(PREPROC) -ie $< charmap.txt | $(AS) $(ASFLAGS) -o $@

$(DATA_ASM_BUILDDIR)/%.d: $(DATA_ASM_SUBDIR)/%.s
	$(SCANINC) -M $@ -g $(ASSETS_DIR_NAME) $(INCLUDE_SCANINC_ARGS) -I "" $<

ifneq ($(NODEP),1)
-include $(addprefix $(OBJ_DIR)/,$(DATA_ASM_SRCS:.s=.d))
endif

$(OBJ_DIR)/sym_bss.ld: sym_bss.txt
	$(RAMSCRGEN) .bss $< ENGLISH > $@

$(OBJ_DIR)/sym_common.ld: sym_common.txt $(C_OBJS) $(wildcard common_syms/*.txt)
	$(RAMSCRGEN) COMMON $< ENGLISH -c $(C_BUILDDIR),common_syms > $@

$(OBJ_DIR)/sym_ewram.ld: sym_ewram.txt
	$(RAMSCRGEN) ewram_data $< ENGLISH > $@

TEACHABLE_DEPS := $(ALL_LEARNABLES_JSON) $(SOURCE_INCLUDE_DIR)/constants/tms_hms.h $(SOURCE_INCLUDE_DIR)/config/pokemon.h $(DATA_SRC_SUBDIR)/pokemon/special_movesets.json $(SOURCE_INCLUDE_DIR)/config/pokedex_plus_hgss.h $(LEARNSET_HELPERS_DIR)/make_teachables.py

$(LEARNSET_HELPERS_BUILD_DIR):
	@mkdir -p $@

$(ALL_LEARNABLES_JSON):
	python3 $(LEARNSET_HELPERS_DIR)/make_learnables.py $(LEARNSET_HELPERS_DATA_DIR) $@

$(ALL_TUTORS_JSON): $(shell find data/ -type f -name '*.inc')  $(LEARNSET_HELPERS_DIR)/make_tutors.py | $(LEARNSET_HELPERS_BUILD_DIR)
	python3 $(LEARNSET_HELPERS_DIR)/make_tutors.py $@

$(ALL_TEACHING_TYPES_JSON): $(wildcard $(DATA_SRC_SUBDIR)/pokemon/species_info/*_families.h)  $(LEARNSET_HELPERS_DIR)/make_teaching_types.py | $(LEARNSET_HELPERS_BUILD_DIR)
	python3 $(LEARNSET_HELPERS_DIR)/make_teaching_types.py $@

$(DATA_SRC_SUBDIR)/pokemon/teachable_learnsets.h: $(TEACHABLE_DEPS) | $(ALL_TUTORS_JSON) $(ALL_TEACHING_TYPES_JSON)
	python3 $(LEARNSET_HELPERS_DIR)/make_teachables.py $(LEARNSET_HELPERS_BUILD_DIR)

$(DATA_SRC_SUBDIR)/tutor_moves.h: $(DATA_SRC_SUBDIR)/pokemon/special_movesets.json | $(ALL_TUTORS_JSON)
	python3 $(LEARNSET_HELPERS_DIR)/make_teachables.py  --tutors $(LEARNSET_HELPERS_BUILD_DIR)

# Linker script
LD_SCRIPT := ld_script_modern.ld

# Final rules

libagbsyscall:
	@$(MAKE) -C libagbsyscall TOOLCHAIN=$(TOOLCHAIN) MODERN=1

# Enable LTO LDFLAGS if set
ifneq ($(LTO),0)
LDFLAGS := -march=armv4t -mabi=apcs-gnu -mcpu=arm7tdmi -Xlinker -Map=../../$(MAP) -Xlinker --print-memory-usage -Xassembler -meabi=5 -Xassembler -march=armv4t -Xassembler -mcpu=arm7tdmi -Xlinker --gc-sections -Xlinker --undefined=gSaveAbiEvidence
LDFLAGS += -Xlinker -flto=auto
$(ELF): $(LD_SCRIPT) $(OBJS) libagbsyscall | content-port-transaction-check
	@echo "cd $(OBJ_DIR) && $(ARMCC) $(LDFLAGS) -T ../../$< -o ../../$@ <objs> <libs>"
	+@cd $(OBJ_DIR) && $(ARMCC) $(LDFLAGS) -T ../../$< -o ../../$@ $(OBJS_REL) $(LIB)
	$(FIX) $@ -t"$(TITLE)" -c$(GAME_CODE) -m$(MAKER_CODE) -r$(REVISION) --silent
else
# Output .map file, memory usage readout and gc sections to clean-up unused data
LDFLAGS = -Map ../../$(MAP) --print-memory-usage --gc-sections --undefined=gSaveAbiEvidence
$(ELF): $(LD_SCRIPT) $(OBJS) libagbsyscall | content-port-transaction-check
	@cd $(OBJ_DIR) && $(LD) $(LDFLAGS) -T ../../$<  -o ../../$@ $(OBJS_REL) $(LIB) | cat
	@echo "cd $(OBJ_DIR) && $(LD) $(LDFLAGS) -T ../../$< -o ../../$@ <objs> <libs> | cat"
	$(FIX) $@ -t"$(TITLE)" -c$(GAME_CODE) -m$(MAKER_CODE) -r$(REVISION) --silent
endif

# Builds the rom from the elf file
$(ROM): $(ELF) | content-port-transaction-check
	$(OBJCOPY) -O binary $< $@
	$(FIX) $@ -p --silent

emerald: all
# Symbol file (`make syms`)
$(SYM): $(ELF) | content-port-transaction-check
	$(OBJDUMP) -t $< | sort -u | grep -E "^0[2389]" | $(PERL) -p -e 's/^(\w{8}) (\w).{6} \S+\t(\w{8}) (\S+)$$/\1 \2 \3 \4/g' > $@

endif
