"""Chemistry: the dispenser's chemicals, the compounds mixed from them, and what the processor makes of items."""

DISPENSER = {
    "Elements": ["Carbon", "Chlorine", "Hydrogen", "Nitrogen", "Oxygen", "Phosphorus", "Potassium", "Sodium",
                 "Sulfur"],
    "Solvents": ["Water"],
}
DISPENSER_CHEMICALS = sorted(name for names in DISPENSER.values() for name in names)
MAX_BEAKER_CHEMICALS = 6

# Each compound's "item" is the inventory item a successful mix makes.
COMPOUNDS = {
    "Burn Salve": {
        "ingredients": ["Aloe Extract", "Sodium", "Water"],
        "desc": "A cooling salve that takes the heat out of burns.",
        "item": "burn_salve",
    },
    "Antitoxin": {
        "ingredients": ["Carbon", "Fruit Acid", "Water"],
        "desc": "Binds poison so the body can flush it out.",
        "item": "antitoxin",
    },
    "Oxygen Tonic": {
        "ingredients": ["Oxygen", "Iron Powder", "Water"],
        "desc": "Helps the blood carry oxygen again after life support trouble.",
        "item": "oxygen_tonic",
    },
    "Healing Gel": {
        "ingredients": ["Aloe Extract", "Starch", "Ethanol"],
        "desc": "A thick gel that knits bruised and broken limbs.",
        "item": "healing_gel",
    },
    "Sober-Up": {
        "ingredients": ["Potassium", "Fruit Acid", "Water"],
        "desc": "Clears alcohol from the system in a hurry.",
        "item": "sober_up",
    },
    "Miracle Grow": {
        "ingredients": ["Nitrogen", "Phosphorus", "Potassium"],
        "desc": "The botanist's fertilizer, made from scratch.",
        "item": "miracle_grow",
    },
    "Acid Flask": {
        "ingredients": ["Sulfur", "Oxygen", "Hydrogen"],
        "desc": "A flask of strong acid. Thrown, it hits hard, once.",
        "item": "acid_flask",
    },
}

# Solid items the processor turns into a reagent item the beaker can take.
PROCESSOR_RESULTS = {
    "aloe": "aloe_extract",
    "potato": "starch",
    "wheat": "starch",
    "tomato": "fruit_acid",
    "apple": "fruit_acid",
    "carrot": "fruit_acid",
    "iron_ore": "iron_powder",
}


def _reagent(item_id, name, description):
    return {
        "id": item_id,
        "name": name,
        "description": description,
        "category": "Reagent",
        "attributes": {"reagent": name},
        "actions": ["examine", "drop"],
    }


def _remedy(item_id, name, description, heals):
    return {
        "id": item_id,
        "name": name,
        "description": description,
        "category": "Healing",
        "attributes": {"heals": heals},
        "actions": ["examine", "use", "drop"],
    }


CHEMISTRY_ITEMS = {
    "aloe_extract": _reagent("aloe_extract", "Aloe Extract", "Clear gel pressed out of aloe leaves."),
    "starch": _reagent("starch", "Starch", "A fine white powder ground from potatoes or wheat."),
    "fruit_acid": _reagent("fruit_acid", "Fruit Acid", "Sharp juice strained from fruit and vegetables."),
    "iron_powder": _reagent("iron_powder", "Iron Powder", "Iron ore ground down to a dark powder."),
    "burn_salve": _remedy("burn_salve", "Burn Salve", COMPOUNDS["Burn Salve"]["desc"], {"burn": 30}),
    "antitoxin": _remedy("antitoxin", "Antitoxin", COMPOUNDS["Antitoxin"]["desc"], {"poison": 30}),
    "oxygen_tonic": _remedy("oxygen_tonic", "Oxygen Tonic", COMPOUNDS["Oxygen Tonic"]["desc"], {"oxygen": 30}),
    "healing_gel": _remedy("healing_gel", "Healing Gel", COMPOUNDS["Healing Gel"]["desc"], {"limbs": 15}),
    "sober_up": _remedy("sober_up", "Sober-Up", COMPOUNDS["Sober-Up"]["desc"], {"alcohol": 20}),
    "acid_flask": {
        "id": "acid_flask",
        "name": "Acid Flask",
        "description": COMPOUNDS["Acid Flask"]["desc"],
        "category": "Weapon",
        "attributes": {"attack": 30, "single_use": True},
        "actions": ["examine", "equip", "drop"],
    },
}


# The compounds MedBay treats with, which Chemistry sends it through the station stores.
STORE_REMEDY_IDS = ("burn_salve", "antitoxin", "oxygen_tonic", "healing_gel")


def reagent_of(item):
    """The chemical an inventory item goes into the beaker as, or None when it needs processing or is no use.

    Reagent items carry their chemical. Drinks are already liquid: alcohol gives Ethanol and juice gives Fruit Acid.
    """
    attributes = item.get("attributes") or {}
    if "reagent" in attributes:
        return attributes["reagent"]
    if item.get("category") == "Drink":
        if attributes.get("alcoholic"):
            return "Ethanol"
        if item["name"].endswith("Juice"):
            return "Fruit Acid"
    return None


def get_compound_feedback(ingredients):
    """Return failure feedback for chemicals that make no known compound."""
    if len(ingredients) < 2:
        return "A compound needs at least two chemicals."
    return "Check the formula book for what reacts."
