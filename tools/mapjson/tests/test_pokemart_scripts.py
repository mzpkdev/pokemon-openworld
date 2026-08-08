import re
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MAPS_ROOT = ROOT / "data" / "maps"
EVENT_MACROS = ROOT / "asm" / "macros" / "event.inc"

# This is the deliberately narrow migration set.  Keeping the complete mapping here
# catches a clerk being pointed at the wrong stock list just as readily as it catches
# an accidental expansion of the refactor's scope.
EXPECTED_STANDARD_MARTS = {
    "BattleFrontier_Mart_EventScript_Clerk": (
        "BattleFrontier_Mart_Pokemart",
        "pokemart",
    ),
    "CeladonCity_DepartmentStore_2F_EventScript_ClerkItems": (
        "CeladonCity_DepartmentStore_2F_Items",
        "pokemart",
    ),
    "CeladonCity_DepartmentStore_2F_EventScript_ClerkTMs": (
        "CeladonCity_DepartmentStore_2F_TMs",
        "pokemart",
    ),
    "CeladonCity_DepartmentStore_4F_EventScript_Clerk": (
        "CeladonCity_DepartmentStore_4F_Items",
        "pokemart",
    ),
    "CeladonCity_DepartmentStore_5F_EventScript_ClerkXItems": (
        "CeladonCity_DepartmentStore_5F_XItems",
        "pokemart",
    ),
    "CeladonCity_DepartmentStore_5F_EventScript_ClerkVitamins": (
        "CeladonCity_DepartmentStore_5F_Vitamins",
        "pokemart",
    ),
    "CeruleanCity_Mart_EventScript_Clerk": ("CeruleanCity_Mart_Items", "pokemart"),
    "CinnabarIsland_Mart_EventScript_Clerk": ("CinnabarIsland_Mart_Items", "pokemart"),
    "EverGrandeCity_PokemonLeague_1F_EventScript_Clerk": (
        "EverGrandeCity_PokemonLeague_1F_Pokemart",
        "pokemart",
    ),
    "FallarborTown_Mart_EventScript_Clerk": ("FallarborTown_Mart_Pokemart", "pokemart"),
    "FortreeCity_DecorationShop_EventScript_ClerkChairs": (
        "FortreeCity_DecorationShop_PokemartDecor_Chairs",
        "pokemartdecoration",
    ),
    "FortreeCity_DecorationShop_EventScript_ClerkDesks": (
        "FortreeCity_DecorationShop_PokemartDecor_Desks",
        "pokemartdecoration",
    ),
    "FortreeCity_Mart_EventScript_Clerk": ("FortreeCity_Mart_Pokemart", "pokemart"),
    "FourIsland_Mart_EventScript_Clerk": ("FourIsland_Mart_Items", "pokemart"),
    "FuchsiaCity_Mart_EventScript_Clerk": ("FuchsiaCity_Mart_Items", "pokemart"),
    "IndigoPlateau_PokemonCenter_1F_EventScript_Clerk": (
        "IndigoPlateau_PokemonCenter_1F_Items",
        "pokemart",
    ),
    "LavaridgeTown_Mart_EventScript_Clerk": ("LavaridgeTown_Mart_Pokemart", "pokemart"),
    "LavenderTown_Mart_EventScript_Clerk": ("LavenderTown_Mart_Items", "pokemart"),
    "LilycoveCity_DepartmentStoreRooftop_EventScript_SaleWoman": (
        "LilycoveCity_DepartmentStoreRooftop_PokemartDecor_ClearOutSale",
        "pokemartdecoration",
    ),
    "LilycoveCity_DepartmentStore_2F_EventScript_ClerkLeft": (
        "LilycoveCity_DepartmentStore_2F_Pokemart1",
        "pokemart",
    ),
    "LilycoveCity_DepartmentStore_2F_EventScript_ClerkRight": (
        "LilycoveCity_DepartmentStore_2F_Pokemart2",
        "pokemart",
    ),
    "LilycoveCity_DepartmentStore_3F_EventScript_ClerkLeft": (
        "LilycoveCity_DepartmentStore_3F_Pokemart_Vitamins",
        "pokemart",
    ),
    "LilycoveCity_DepartmentStore_3F_EventScript_ClerkRight": (
        "LilycoveCity_DepartmentStore_3F_Pokemart_StatBoosters",
        "pokemart",
    ),
    "LilycoveCity_DepartmentStore_4F_EventScript_ClerkLeft": (
        "LilycoveCity_DepartmentStore_4F_Pokemart_AttackTMs",
        "pokemart",
    ),
    "LilycoveCity_DepartmentStore_4F_EventScript_ClerkRight": (
        "LilycoveCity_DepartmentStore_4F_Pokemart_DefenseTMs",
        "pokemart",
    ),
    "LilycoveCity_DepartmentStore_5F_EventScript_ClerkFarLeft": (
        "LilycoveCity_DepartmentStore_5F_Pokemart_Dolls",
        "pokemartdecoration2",
    ),
    "LilycoveCity_DepartmentStore_5F_EventScript_ClerkFarRight": (
        "LilycoveCity_DepartmentStore_5F_Pokemart_Mats",
        "pokemartdecoration2",
    ),
    "LilycoveCity_DepartmentStore_5F_EventScript_ClerkMidLeft": (
        "LilycoveCity_DepartmentStore_5F_Pokemart_Cushions",
        "pokemartdecoration2",
    ),
    "LilycoveCity_DepartmentStore_5F_EventScript_ClerkMidRight": (
        "LilycoveCity_DepartmentStore_5F_Pokemart_Posters",
        "pokemartdecoration2",
    ),
    "MauvilleCity_Mart_EventScript_Clerk": ("MauvilleCity_Mart_Pokemart", "pokemart"),
    "MossdeepCity_Mart_EventScript_Clerk": ("MossdeepCity_Mart_Pokemart", "pokemart"),
    "PewterCity_Mart_EventScript_Clerk": ("PewterCity_Mart_Items", "pokemart"),
    "SaffronCity_Mart_EventScript_Clerk": ("SaffronCity_Mart_Items", "pokemart"),
    "SevenIsland_Mart_EventScript_Clerk": ("SevenIsland_Mart_Items", "pokemart"),
    "SixIsland_Mart_EventScript_Clerk": ("SixIsland_Mart_Items", "pokemart"),
    "SlateportCity_EventScript_DollClerk": (
        "SlateportCity_PokemartDecor_Dolls",
        "pokemartdecoration",
    ),
    "SlateportCity_EventScript_PowerTMClerk": (
        "SlateportCity_Pokemart_PowerTMs",
        "pokemart",
    ),
    "SlateportCity_Mart_EventScript_Clerk": ("SlateportCity_Mart_Pokemart", "pokemart"),
    "SootopolisCity_Mart_EventScript_Clerk": (
        "SootopolisCity_Mart_Pokemart",
        "pokemart",
    ),
    "ThreeIsland_Mart_EventScript_Clerk": ("ThreeIsland_Mart_Items", "pokemart"),
    "TrainerTower_Lobby_EventScript_MartClerk": (
        "TrainerTower_Lobby_Mart_Items",
        "pokemart",
    ),
    "VerdanturfTown_Mart_EventScript_Clerk": (
        "VerdanturfTown_Mart_Pokemart",
        "pokemart",
    ),
    "VermilionCity_Mart_EventScript_Clerk": ("VermilionCity_Mart_Items", "pokemart"),
}

EXPECTED_COMMAND_COUNTS = {
    "pokemart": 35,
    "pokemartdecoration": 4,
    "pokemartdecoration2": 4,
}

# Each entry names a script that looks close to the common wrapper but has behavior
# that makes it intentionally ineligible.  The tokens pin the reason for exclusion.
EXPLICIT_EXCLUSIONS = {
    ("LavaridgeTown_HerbShop", "LavaridgeTown_HerbShop_EventScript_Clerk"): (
        "message LavaridgeTown_HerbShop_Text_WelcomeToHerbShop",
        "pokemart LavaridgeTown_HerbShop_Pokemart",
    ),
    ("SlateportCity", "SlateportCity_EventScript_EnergyGuru"): (
        "message SlateportCity_Text_EnergyGuruSellWhatYouNeed",
        "pokemart SlateportCity_Pokemart_EnergyGuru",
    ),
    ("CherrygroveCity_Mart", "Cherrygrove_Pokemart_EventScript_Clerk"): (
        "goto_if_ge VAR_NEWBARK_TOWN_STATE, 5, Cherrygrove_Pokemart_EventScript_Clerk2",
        "pokemart Cherrygrove_Pokemart_Pokemart",
    ),
    ("CherrygroveCity_Mart", "Cherrygrove_Pokemart_EventScript_Clerk2"): (
        "pokemart Cherrygrove_Pokemart_Pokemart",
        "msgbox gText_PleaseComeAgain, MSGBOX_DEFAULT",
    ),
    ("OldaleTown_Mart", "OldaleTown_Mart_EventScript_Clerk"): (
        "goto_if_set FLAG_ADVENTURE_STARTED, OldaleTown_Mart_ExpandedItems",
        "pokemart OldaleTown_Mart_Pokemart_Basic",
    ),
    ("OldaleTown_Mart", "OldaleTown_Mart_ExpandedItems"): (
        "pokemart OldaleTown_Mart_Pokemart_Expanded",
        "msgbox gText_PleaseComeAgain, MSGBOX_DEFAULT",
    ),
    ("PetalburgCity_Mart", "PetalburgCity_Mart_EventScript_Clerk"): (
        "goto_if_set FLAG_PETALBURG_MART_EXPANDED_ITEMS, PetalburgCity_Mart_EventScript_ExpandedItems",
        "pokemart PetalburgCity_Mart_Pokemart_Basic",
    ),
    ("PetalburgCity_Mart", "PetalburgCity_Mart_EventScript_ExpandedItems"): (
        "pokemart PetalburgCity_Mart_Pokemart_Expanded",
        "msgbox gText_PleaseComeAgain, MSGBOX_DEFAULT",
    ),
    ("RustboroCity_Mart", "RustboroCity_Mart_EventScript_Clerk"): (
        "goto_if_unset FLAG_MET_DEVON_EMPLOYEE, RustboroCity_Mart_EventScript_PokemartBasic",
        "goto_if_set FLAG_MET_DEVON_EMPLOYEE, RustboroCity_Mart_EventScript_PokemartExpanded",
    ),
    ("RustboroCity_Mart", "RustboroCity_Mart_EventScript_PokemartBasic"): (
        "pokemart RustboroCity_Mart_Pokemart_Basic",
        "msgbox gText_PleaseComeAgain, MSGBOX_DEFAULT",
    ),
    ("RustboroCity_Mart", "RustboroCity_Mart_EventScript_PokemartExpanded"): (
        "pokemart RustboroCity_Mart_Pokemart_Expanded",
        "msgbox gText_PleaseComeAgain, MSGBOX_DEFAULT",
    ),
    ("TrainerHill_Entrance", "TrainerHill_Entrance_EventScript_Clerk"): (
        "goto_if_set FLAG_SYS_GAME_CLEAR, TrainerHill_Entrance_EventScript_ExpandedPokemart",
        "pokemart TrainerHill_Entrance_Pokemart_Basic",
    ),
    ("TrainerHill_Entrance", "TrainerHill_Entrance_EventScript_ExpandedPokemart"): (
        "pokemart TrainerHill_Entrance_Pokemart_Expanded",
        "msgbox gText_PleaseComeAgain, MSGBOX_DEFAULT",
    ),
    ("TwoIsland_Frlg", "TwoIsland_EventScript_ClerkShopSkipIntro"): (
        "goto_if_eq VAR_MAP_SCENE_TWO_ISLAND, 4, TwoIsland_EventScript_ShopExpanded3",
        "goto TwoIsland_EventScript_ShopInitial",
    ),
    ("TwoIsland_Frlg", "TwoIsland_EventScript_ShopInitial"): (
        "pokemart TwoIsland_Items_ShopInitial",
        "msgbox gText_PleaseComeAgain",
    ),
    ("TwoIsland_Frlg", "TwoIsland_EventScript_ShopExpanded1"): (
        "pokemart TwoIsland_Items_ShopExpanded1",
        "msgbox gText_PleaseComeAgain",
    ),
    ("TwoIsland_Frlg", "TwoIsland_EventScript_ShopExpanded2"): (
        "pokemart TwoIsland_Items_ShopExpanded2",
        "msgbox gText_PleaseComeAgain",
    ),
    ("TwoIsland_Frlg", "TwoIsland_EventScript_ShopExpanded3"): (
        "pokemart TwoIsland_Items_ShopExpanded3",
        "msgbox gText_PleaseComeAgain",
    ),
    ("ViridianCity_Mart_Frlg", "ViridianCity_Mart_EventScript_Clerk"): (
        "goto_if_eq VAR_MAP_SCENE_VIRIDIAN_CITY_MART, 1, ViridianCity_Mart_EventScript_SayHiToOak",
        "pokemart ViridianCity_Mart_Items",
    ),
    ("SlateportCity", "SlateportCity_EventScript_DecorClerk"): (
        "goto_if_unset FLAG_RECEIVED_SECRET_POWER, SlateportCity_EventScript_ComeBackWithSecretPower",
        "pokemartdecoration SlateportCity_PokemartDecor",
    ),
    (
        "Route104_PrettyPetalFlowerShop",
        "Route104_PrettyPetalFlowerShop_EventScript_SellDecorations",
    ): (
        "message gText_PlayerWhatCanIDoForYou",
        "pokemartdecoration2 Route104_PrettyPetalFlowerShop_Pokemart_Plants",
    ),
}

TWO_ISLAND_SHOP_BODIES = {
    "TwoIsland_EventScript_ShopInitial": (
        "pokemart TwoIsland_Items_ShopInitial",
        "msgbox gText_PleaseComeAgain",
        "release",
        "end",
    ),
    "TwoIsland_EventScript_ShopExpanded1": (
        "pokemart TwoIsland_Items_ShopExpanded1",
        "msgbox gText_PleaseComeAgain",
        "release",
        "end",
    ),
    "TwoIsland_EventScript_ShopExpanded2": (
        "pokemart TwoIsland_Items_ShopExpanded2",
        "msgbox gText_PleaseComeAgain",
        "release",
        "end",
    ),
    "TwoIsland_EventScript_ShopExpanded3": (
        "pokemart TwoIsland_Items_ShopExpanded3",
        "msgbox gText_PleaseComeAgain",
        "release",
        "end",
    ),
}

TWO_ISLAND_SHOP_DISPATCH = (
    "message gText_HowMayIServeYou",
    "waitmessage",
    "goto_if_eq VAR_MAP_SCENE_TWO_ISLAND, 4, TwoIsland_EventScript_ShopExpanded3",
    "goto_if_eq VAR_MAP_SCENE_TWO_ISLAND, 3, TwoIsland_EventScript_ShopExpanded2",
    "goto_if_eq VAR_MAP_SCENE_TWO_ISLAND, 2, TwoIsland_EventScript_ShopExpanded1",
    "goto TwoIsland_EventScript_ShopInitial",
    "end",
)

TWO_ISLAND_CLERK_PROGRESSION = {
    "TwoIsland_EventScript_Clerk": (
        "lock",
        "faceplayer",
        "goto_if_eq VAR_MAP_SCENE_TWO_ISLAND, 4, TwoIsland_EventScript_ClerkShopExpanded3",
        "goto_if_eq VAR_MAP_SCENE_TWO_ISLAND, 3, TwoIsland_EventScript_ClerkShopExpanded2",
        "goto_if_eq VAR_MAP_SCENE_TWO_ISLAND, 2, TwoIsland_EventScript_ClerkShopExpanded1",
        "goto TwoIsland_EventScript_ClerkShopInitial",
        "end",
    ),
    "TwoIsland_EventScript_ClerkShopExpanded3": (
        "goto_if_set FLAG_TWO_ISLAND_SHOP_EXPANDED_3, TwoIsland_EventScript_ClerkShopSkipIntro",
        "setflag FLAG_TWO_ISLAND_SHOP_EXPANDED_3",
        "message TwoIsland_Text_BringingItemsFromDistantLands",
        "waitmessage",
        "goto TwoIsland_EventScript_ShopExpanded3",
        "end",
    ),
    "TwoIsland_EventScript_ClerkShopExpanded2": (
        "goto_if_set FLAG_TWO_ISLAND_SHOP_EXPANDED_2, TwoIsland_EventScript_ClerkShopSkipIntro",
        "setflag FLAG_TWO_ISLAND_SHOP_EXPANDED_2",
        "message TwoIsland_Text_HopeYouGiveItYourBest",
        "waitmessage",
        "goto TwoIsland_EventScript_ShopExpanded2",
        "end",
    ),
    "TwoIsland_EventScript_ClerkShopExpanded1": (
        "goto_if_set FLAG_TWO_ISLAND_SHOP_EXPANDED_1, TwoIsland_EventScript_ClerkShopSkipIntro",
        "setflag FLAG_TWO_ISLAND_SHOP_EXPANDED_1",
        "message TwoIsland_Text_AddedMerchandiseForLostelle",
        "waitmessage",
        "goto TwoIsland_EventScript_ShopExpanded1",
        "end",
    ),
    "TwoIsland_EventScript_ClerkShopInitial": (
        "goto_if_set FLAG_TWO_ISLAND_SHOP_INTRODUCED, TwoIsland_EventScript_ClerkShopSkipIntro",
        "setflag FLAG_TWO_ISLAND_SHOP_INTRODUCED",
        "message TwoIsland_Text_WelcomeToShopMerchandiseLimited",
        "waitmessage",
        "goto TwoIsland_EventScript_ShopInitial",
        "end",
    ),
}

EXPORTED_LABEL = re.compile(r"(?m)^(?P<label>[A-Za-z_][A-Za-z0-9_]*)::\s*$")


def _map_scripts():
    for path in sorted(MAPS_ROOT.glob("*/scripts.inc")):
        yield path, path.read_text(encoding="utf-8")


def _script_section(source, label, location="source"):
    match = re.search(
        rf"(?ms)^{re.escape(label)}::\s*\n(?P<body>.*?)"
        r"(?=^\s*\.align\b|^[A-Za-z_][A-Za-z0-9_]*:{1,2}\s*$|\Z)",
        source,
    )
    if match is None:
        raise AssertionError(f"{location}: missing exported script {label}::")
    return match.group("body")


def _script_instructions(source, label, location="source"):
    body = _script_section(source, label, location)
    return tuple(
        instruction
        for line in body.splitlines()
        if (instruction := line.split("@", 1)[0].strip())
    )


def _parse_standard_mart_clerk(source, label, location="source"):
    instructions = _script_instructions(source, label, location)
    if len(instructions) != 1:
        raise AssertionError(
            f"{location}:{label} must contain only one standard_mart_clerk invocation; "
            f"found {instructions!r}"
        )
    match = re.fullmatch(
        r"standard_mart_clerk\s+(?P<products>[A-Za-z_][A-Za-z0-9_]*)"
        r"(?:\s*,\s*(?P<command>pokemart(?:decoration2?)))?",
        instructions[0],
    )
    if match is None:
        raise AssertionError(
            f"{location}:{label} has invalid standard_mart_clerk invocation "
            f"{instructions[0]!r}"
        )
    return match.group("products"), match.group("command") or "pokemart"


def _script_block(map_name, label):
    path = MAPS_ROOT / map_name / "scripts.inc"
    source = path.read_text(encoding="utf-8")
    return _script_section(source, label, path)


class PokemartScriptTests(unittest.TestCase):
    def test_macro_has_products_first_and_preserves_wrapper_semantics(self):
        source = EVENT_MACROS.read_text(encoding="utf-8")
        match = re.search(
            r"(?ms)^\s*\.macro standard_mart_clerk (?P<signature>[^\n]+)\n"
            r"(?P<body>.*?)^\s*\.endm\s*$",
            source,
        )
        self.assertIsNotNone(match, "missing standard_mart_clerk macro")
        self.assertEqual(
            match.group("signature").strip(),
            "products:req, mart_command=pokemart",
        )
        instructions = [
            line.strip()
            for line in match.group("body").splitlines()
            if line.strip() and not line.lstrip().startswith("@")
        ]
        self.assertEqual(
            instructions,
            [
                "lock",
                "faceplayer",
                "message gText_HowMayIServeYou",
                "waitmessage",
                r"\mart_command \products",
                "msgbox gText_PleaseComeAgain, MSGBOX_DEFAULT",
                "release",
                "end",
            ],
        )

    def test_exact_exported_label_inventory_and_command_mapping(self):
        actual = {}
        locations = {}
        for path, source in _map_scripts():
            location = path.relative_to(ROOT).as_posix()
            for match in EXPORTED_LABEL.finditer(source):
                label = match.group("label")
                instructions = _script_instructions(source, label, location)
                if not any(
                    instruction.startswith("standard_mart_clerk")
                    for instruction in instructions
                ):
                    continue
                self.assertNotIn(label, actual, f"duplicate migrated label {label}")
                actual[label] = _parse_standard_mart_clerk(source, label, location)
                locations[label] = location

        self.assertEqual(actual, EXPECTED_STANDARD_MARTS, locations)
        self.assertEqual(
            Counter(command for _, command in actual.values()),
            EXPECTED_COMMAND_COUNTS,
        )

    def test_standard_mart_section_rejects_appended_instruction(self):
        source = """\
Example_Clerk::
    standard_mart_clerk Example_Items
    end

    .align 2
Example_Items::
    .2byte ITEM_NONE
"""
        with self.assertRaisesRegex(AssertionError, "must contain only one"):
            _parse_standard_mart_clerk(source, "Example_Clerk")

    def test_no_eligible_common_greeting_shell_remains_expanded(self):
        expanded = re.compile(
            r"(?m)^(?P<label>[A-Za-z_][A-Za-z0-9_]*)::\s*\n"
            r"\s*lock\s*\n\s*faceplayer\s*\n"
            r"\s*message gText_HowMayIServeYou\s*\n\s*waitmessage\s*\n"
            r"\s*pokemart(?:decoration2?)?\s+[A-Za-z_][A-Za-z0-9_]*\s*\n"
            r"\s*msgbox gText_PleaseComeAgain(?:, MSGBOX_DEFAULT)?\s*\n"
            r"\s*release\s*\n\s*end\s*$"
        )
        leftovers = []
        for path, source in _map_scripts():
            leftovers.extend(
                f"{path.relative_to(ROOT)}:{match.group('label')}"
                for match in expanded.finditer(source)
            )
        self.assertEqual(leftovers, [])

    def test_custom_and_progression_marts_remain_explicit(self):
        for (map_name, label), required_tokens in EXPLICIT_EXCLUSIONS.items():
            with self.subTest(map=map_name, script=label):
                body = _script_block(map_name, label)
                self.assertNotIn("standard_mart_clerk", body)
                for token in required_tokens:
                    self.assertIn(token, body)

    def test_two_island_progression_shop_bodies_and_dispatch_are_pinned(self):
        path = MAPS_ROOT / "TwoIsland_Frlg" / "scripts.inc"
        source = path.read_text(encoding="utf-8")
        for label, expected in TWO_ISLAND_CLERK_PROGRESSION.items():
            with self.subTest(script=label):
                self.assertEqual(_script_instructions(source, label, path), expected)
        for label, expected in TWO_ISLAND_SHOP_BODIES.items():
            with self.subTest(script=label):
                self.assertEqual(_script_instructions(source, label, path), expected)
        self.assertEqual(
            _script_instructions(
                source, "TwoIsland_EventScript_ClerkShopSkipIntro", path
            ),
            TWO_ISLAND_SHOP_DISPATCH,
        )


if __name__ == "__main__":
    unittest.main()
