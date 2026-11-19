"""Mining: the gear, the ores, the magnet, and the planets the station passes over with what lives on them."""


def _ore(item_id, name, description):
    return {
        "id": item_id,
        "name": name,
        "description": description,
        "category": "Ore",
        "attributes": {},
        "actions": ["examine", "drop"],
    }


MINING_ITEMS = {
    "pickaxe": {
        "id": "pickaxe",
        "name": "Pickaxe",
        "description": "A miner's pickaxe. It breaks rock, and anything else in the way.",
        "category": "Tool",
        "attributes": {"attack": 15},
        "actions": ["examine", "equip", "drop"],
    },
    "blast_shield": {
        "id": "blast_shield",
        "name": "Blast Shield",
        "description": "A heavy shield for working close to blasting charges. It stops a lot.",
        "category": "Tool",
        "attributes": {"attack": 2, "block": 50},
        "actions": ["examine", "equip", "drop"],
    },
    "iron_ore": _ore("iron_ore", "Iron Ore", "A lump of rusty brown iron ore."),
    "copper_ore": _ore("copper_ore", "Copper Ore", "Ore streaked with green and orange copper."),
    "quartz": _ore("quartz", "Quartz", "A cloudy chunk of quartz."),
    "titanium_ore": _ore("titanium_ore", "Titanium Ore", "Dense grey ore, prized for hull plating."),
    "gold_ore": _ore("gold_ore", "Gold Ore", "Rock shot through with veins of gold."),
    "ice_diamond": _ore("ice_diamond", "Ice Diamond", "A diamond formed in ice, cold to the touch."),
    "emberite": _ore("emberite", "Emberite", "A glowing orange crystal that never quite cools."),
    "plasma_crystal": _ore("plasma_crystal", "Plasma Crystal", "A crystal that hums with stored energy."),
}

# Credits the Mining Bay pays for each ore.
ORE_VALUES = {
    "iron_ore": 8,
    "copper_ore": 12,
    "quartz": 16,
    "titanium_ore": 45,
    "gold_ore": 60,
    "emberite": 70,
    "ice_diamond": 75,
    "plasma_crystal": 90,
}

MAGNET_ORES = ("iron_ore", "copper_ore", "quartz")
MAGNET_SECONDS_PER_ROCK = 60
MAGNET_MAX_ROCKS = 10

# What the Miner charges other crew for common ore.
MINER_STAND_PRICES = {"iron_ore": 20, "copper_ore": 30, "quartz": 40}
MINING_GEAR_IDS = ("pickaxe", "blast_shield")

# A monster's "attack" is its (low, high) blunt damage; "extra" is a (damage type, amount) it adds to each hit.
PLANETS = (
    {
        "name": "Kessar IV",
        "desc": "A dusty red desert under a pale sun. The wind never stops.",
        "ores": ("titanium_ore", "gold_ore"),
        "monsters": (
            {"name": "Sand Crawler", "hp": 30, "attack": (6, 12), "extra": None},
            {"name": "Dune Stalker", "hp": 45, "attack": (8, 16), "extra": None},
        ),
    },
    {
        "name": "Glacia",
        "desc": "A frozen moon of blue ice. Your breath hangs in the air.",
        "ores": ("titanium_ore", "ice_diamond"),
        "monsters": (
            {"name": "Frost Mite", "hp": 25, "attack": (5, 10), "extra": None},
            {"name": "Ice Wraith", "hp": 50, "attack": (9, 15), "extra": None},
        ),
    },
    {
        "name": "Pyros",
        "desc": "A volcanic world of black rock and slow rivers of lava.",
        "ores": ("gold_ore", "emberite"),
        "monsters": (
            {"name": "Magma Slug", "hp": 40, "attack": (6, 12), "extra": ("burn", 6)},
            {"name": "Cinder Hound", "hp": 45, "attack": (10, 16), "extra": ("burn", 4)},
        ),
    },
    {
        "name": "Verdis",
        "desc": "A humid jungle world, loud with things you can't see.",
        "ores": ("gold_ore", "plasma_crystal"),
        "monsters": (
            {"name": "Spore Creeper", "hp": 30, "attack": (5, 10), "extra": ("poison", 8)},
            {"name": "Vine Lasher", "hp": 50, "attack": (9, 16), "extra": None},
        ),
    },
)
ORBIT_SECONDS = 1800
# The ores found in veins on the planets, which a Miner's PDA can identify.
SURFACE_ORES = tuple(dict.fromkeys(ore_id for planet in PLANETS for ore_id in planet["ores"]))


def planet_index(elapsed_seconds):
    """Which of PLANETS the station is over: it moves on to the next every ORBIT_SECONDS."""
    return int(elapsed_seconds // ORBIT_SECONDS) % len(PLANETS)


def new_mining():
    """A fresh mining block for player_data.

    magnet_since  game seconds when the running magnet last started counting, or None while it is off
    rocks         rocks pulled in before that
    expedition    the shuttle trip in progress, or None
    identified    the ore ids whose veins the Miner's PDA has identified this shift
    """
    return {"magnet_since": None, "rocks": 0, "expedition": None, "identified": []}


def rocks_waiting(mining, elapsed_seconds):
    """Rocks the magnet has pulled in so far, up to MAGNET_MAX_ROCKS."""
    pulled = 0
    if mining["magnet_since"] is not None:
        pulled = int((elapsed_seconds - mining["magnet_since"]) // MAGNET_SECONDS_PER_ROCK)
    return min(MAGNET_MAX_ROCKS, mining["rocks"] + pulled)
