"""Food item definitions."""

FOOD_ITEMS = {
    "snack": {
        "id": "snack",
        "name": "Snack",
        "description": "A packaged station snack from a vending machine.",
        "category": "Food",
        "attributes": {"feeds": 25},
        "actions": ["examine", "eat", "drop"],
    },
    "energy_bar": {
        "id": "energy_bar",
        "name": "Energy Bar",
        "description": "A dense, nutrient-rich bar. Tastes like cardboard.",
        "category": "Food",
        "attributes": {"feeds": 35},
        "actions": ["examine", "eat", "drop"],
    },
    "emergency_rations": {
        "id": "emergency_rations",
        "name": "Emergency Rations",
        "plural": True,
        "description": "Standard emergency food supply. Use only when necessary.",
        "category": "Food",
        "attributes": {"feeds": 50},
        "actions": ["examine", "eat", "drop"],
    },
}

PRODUCE = {
    "tomato": {
        "id": "tomato",
        "name": "Tomato",
        "description": "A juicy red tomato fresh from the hydroponics bay.",
        "category": "Food",
        "attributes": {},
        "actions": ["examine", "eat", "drop"],
    },
    "potato": {
        "id": "potato",
        "name": "Potato",
        "description": "A starchy potato grown on the station.",
        "category": "Food",
        "attributes": {},
        "actions": ["examine", "eat", "drop"],
    },
    "wheat": {
        "id": "wheat",
        "name": "Wheat",
        "description": "A bundle of tall wheat stalks.",
        "category": "Food",
        "attributes": {},
        "actions": ["examine", "eat", "drop"],
    },
    "carrot": {
        "id": "carrot",
        "name": "Carrot",
        "description": "An orange root vegetable from the botany lab.",
        "category": "Food",
        "attributes": {},
        "actions": ["examine", "eat", "drop"],
    },
    "apple": {
        "id": "apple",
        "name": "Apple",
        "description": "A crisp apple from a small hydroponic tree.",
        "category": "Food",
        "attributes": {},
        "actions": ["examine", "eat", "drop"],
    },
}

def _mutant(item_id, name, description, **attributes):
    return {
        "id": item_id,
        "name": name,
        "description": description,
        "category": "Food",
        "attributes": attributes,
        "actions": ["examine", "eat", "drop"],
    }


# What "The Ooze" Mutagen can turn each plant's harvest into. Each feeds more than the plain kind or mends
# something as it is eaten ("heals", as a remedy has it).
MUTANT_PRODUCE = {
    "blood_tomato": _mutant("blood_tomato", "Blood Tomato", "A dark, heavy tomato that pulses faintly. It draws "
                            "poison out of whoever eats it.", feeds=40, heals={"poison": 15}),
    "glow_potato": _mutant("glow_potato", "Glow Potato", "A potato that gives off a soft green light. One is a "
                           "meal.", feeds=60),
    "steelwheat": _mutant("steelwheat", "Steelwheat", "Wheat with a grey, metallic sheen. It knits bruises as it "
                          "goes down.", feeds=30, heals={"limbs": 5}),
    "night_carrot": _mutant("night_carrot", "Night Carrot", "A carrot as black as the space outside. It clears the "
                            "lungs.", feeds=30, heals={"oxygen": 15}),
    "golden_apple": _mutant("golden_apple", "Golden Apple", "An apple with a skin like polished brass. It mends "
                            "limbs.", feeds=40, heals={"limbs": 10}),
    "royal_aloe": {
        "id": "royal_aloe",
        "name": "Royal Aloe",
        "description": "A thick purple aloe leaf, far stronger on burns than the plain kind.",
        "category": "Healing",
        "attributes": {"heals": {"burn": 25}},
        "actions": ["examine", "use", "drop"],
    },
}
# plain produce id -> the mutant it can become
MUTANT_OF = {"tomato": "blood_tomato", "potato": "glow_potato", "wheat": "steelwheat", "carrot": "night_carrot",
             "apple": "golden_apple", "aloe": "royal_aloe"}

# The produce the kitchen cooks with, which Botany sends it through the station stores.
KITCHEN_PRODUCE_IDS = ("tomato", "potato", "carrot", "apple")

FOOD_ITEMS.update(PRODUCE)
FOOD_ITEMS.update(MUTANT_PRODUCE)
