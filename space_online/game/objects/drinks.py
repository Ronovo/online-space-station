"""Drink definitions, what the bartender's mixer, recipe book, and ingredient list are made of, and the coffee the
crew shuttle's machine brews."""

from space_online.game.helper_methods.errands import with_article
from space_online.game.helper_methods.mixing import RecipeBook, add_to_stock, match_recipe, register_recipe_book
from space_online.game.helper_methods.needs import DEFAULT_QUENCHES
from space_online.game.helper_methods.ui_panels import register_panel
from space_online.game.objects.items import add_to_inventory

# Alcohol does less for a thirst than anything else on the menu.
ALCOHOL_QUENCHES = 25

DRINKS_MENU = {
    "Beer": {"price": 10, "alcohol_content": 1, "desc": "A refreshing glass of regular beer."},
    "Whiskey": {"price": 20, "alcohol_content": 2, "desc": "A shot of strong whiskey."},
    "Wine": {"price": 15, "alcohol_content": 2, "desc": "A fine glass of red wine."},
    "Vodka": {"price": 15, "alcohol_content": 2, "desc": "A shot of clear, strong vodka."},
    "Gin": {"price": 15, "alcohol_content": 2, "desc": "A botanical spirit with a distinctive flavor."},
    "Rum": {"price": 15, "alcohol_content": 2, "desc": "A sweet spirit distilled from sugarcane."},
    "Tequila": {"price": 18, "alcohol_content": 2, "desc": "A spirit made from the blue agave plant."},
    "Brandy": {"price": 22, "alcohol_content": 2, "desc": "A spirit distilled from wine or fermented fruit juice."},
    "Scotch": {"price": 25, "alcohol_content": 2, "desc": "A smoky whisky from Scotland."},
    "Orange Juice": {"price": 5, "desc": "A glass of fresh orange juice."},
    "Cranberry Juice": {"price": 5, "desc": "Tart and refreshing red juice."},
    "Pineapple Juice": {"price": 6, "desc": "Sweet tropical juice."},
    "Tonic Water": {"price": 4, "desc": "Carbonated water with quinine."},
    "Soda Water": {"price": 3, "desc": "Simple carbonated water."},
    "Cola": {"price": 4, "desc": "A sweet carbonated soft drink."},
    "Lemon Juice": {"price": 4, "desc": "Fresh, sour citrus juice."},
    "Lime Juice": {"price": 4, "desc": "Zesty green citrus juice."},
    "Grenadine": {"price": 5, "desc": "Sweet red syrup made from pomegranate."},
    "Water": {"price": 1, "desc": "A glass of water. Refreshing and healthy."},
}

MIXED_DRINKS = {
    "Screwdriver": {
        "ingredients": ["Vodka", "Orange Juice"],
        "price": 25,
        "alcohol_content": 2,
        "desc": "A classic mix of vodka and orange juice.",
    },
    "Gin and Tonic": {
        "ingredients": ["Gin", "Tonic Water"],
        "price": 20,
        "alcohol_content": 2,
        "desc": "A refreshing mix of gin and tonic water.",
    },
    "Rum and Cola": {
        "ingredients": ["Rum", "Cola"],
        "price": 20,
        "alcohol_content": 2,
        "desc": "A sweet mix of rum and cola.",
    },
    "Whiskey Sour": {
        "ingredients": ["Whiskey", "Lemon Juice", "Sugar"],
        "price": 28,
        "alcohol_content": 2,
        "desc": "A perfect balance of sour and sweet with whiskey.",
    },
    "Margarita": {
        "ingredients": ["Tequila", "Lime Juice", "Triple Sec"],
        "price": 30,
        "alcohol_content": 2,
        "desc": "A tangy, refreshing cocktail with a salt rim.",
    },
    "Bloody Mary": {
        "ingredients": ["Vodka", "Tomato Juice", "Hot Sauce", "Worcestershire Sauce", "Celery"],
        "price": 28,
        "alcohol_content": 2,
        "desc": "A savory, spicy morning cocktail.",
    },
    "Mojito": {
        "ingredients": ["Rum", "Lime Juice", "Mint", "Sugar", "Soda Water"],
        "price": 32,
        "alcohol_content": 2,
        "desc": "A refreshing minty cocktail from Cuba.",
    },
    "Piña Colada": {
        "ingredients": ["Rum", "Coconut Cream", "Pineapple Juice"],
        "price": 30,
        "alcohol_content": 2,
        "desc": "A tropical blend that tastes like vacation.",
    },
    "Cosmopolitan": {
        "ingredients": ["Vodka", "Triple Sec", "Cranberry Juice", "Lime Juice"],
        "price": 30,
        "alcohol_content": 2,
        "desc": "A sophisticated, slightly tart cocktail.",
    },
    "Old Fashioned": {
        "ingredients": ["Whiskey", "Bitters", "Sugar", "Water"],
        "price": 32,
        "alcohol_content": 4,
        "desc": "A timeless cocktail that never goes out of style.",
    },
    "Negroni": {
        "ingredients": ["Gin", "Vermouth", "Campari"],
        "price": 30,
        "alcohol_content": 4,
        "desc": "A perfectly balanced bitter and sweet aperitif.",
    },
    "Manhattan": {
        "ingredients": ["Whiskey", "Vermouth", "Bitters"],
        "price": 32,
        "alcohol_content": 4,
        "desc": "A sophisticated whiskey cocktail.",
    },
    "Mai Tai": {
        "ingredients": ["Rum", "Lime Juice", "Orange Curacao", "Orgeat Syrup"],
        "price": 35,
        "alcohol_content": 4,
        "desc": "A complex tropical rum cocktail.",
    },
    "Daiquiri": {
        "ingredients": ["Rum", "Lime Juice", "Sugar"],
        "price": 28,
        "alcohol_content": 2,
        "desc": "A simple, refreshing rum cocktail.",
    },
    "Tom Collins": {
        "ingredients": ["Gin", "Lemon Juice", "Sugar", "Soda Water"],
        "price": 28,
        "alcohol_content": 2,
        "desc": "A refreshing gin cocktail served in a tall glass.",
    },
    "Singapore Sling": {
        "ingredients": ["Gin", "Cherry Brandy", "Pineapple Juice", "Lime Juice", "Grenadine"],
        "price": 35,
        "alcohol_content": 4,
        "desc": "A complex, fruity gin cocktail.",
    },
    "Between the Sheets": {
        "ingredients": ["Brandy", "Rum", "Triple Sec", "Lemon Juice"],
        "price": 35,
        "alcohol_content": 3,
        "desc": "A potent classic blending brandy, rum, orange, and lemon.",
    },
    "Suffering Bastard": {
        "ingredients": ["Brandy", "Gin", "Lime Juice", "Bitters", "Ginger Ale"],
        "price": 34,
        "alcohol_content": 3,
        "desc": "A sharp brandy and gin cocktail softened with ginger ale.",
    },
    "Boston Sidecar": {
        "ingredients": ["Brandy", "Rum", "Triple Sec", "Lime Juice"],
        "price": 34,
        "alcohol_content": 3,
        "desc": "A rum and brandy variation on the citrus-forward Sidecar.",
    },
    "Brass Monkey": {
        "ingredients": ["Vodka", "Rum", "Orange Juice"],
        "price": 30,
        "alcohol_content": 3,
        "desc": "A retro mix of vodka, rum, and orange juice.",
    },
    "Long Island Iced Tea": {
        "ingredients": ["Vodka", "Gin", "Rum", "Tequila", "Triple Sec", "Lemon Juice", "Cola"],
        "price": 40,
        "alcohol_content": 5,
        "desc": "A potent mix of multiple spirits with a cola finish.",
    },
    "Space Blaster": {
        "ingredients": ["Vodka", "Blue Curacao", "Sprite", "Lemon Juice"],
        "price": 35,
        "alcohol_content": 2,
        "desc": "A station specialty with an electric blue color.",
    },
    "Quantum Fizz": {
        "ingredients": ["Gin", "Lime Juice", "Sugar", "Mint", "Helium Gas"],
        "price": 38,
        "alcohol_content": 2,
        "desc": "A fizzy gin cocktail with a hint of helium. It tastes like a party.",
    },
    "Nebula Cloud": {
        "ingredients": ["Whiskey", "Honey", "Dry Ice", "Cinnamon"],
        "price": 42,
        "alcohol_content": 2,
        "desc": "A smoky cocktail that mimics a space nebula.",
    },
    "Solar Flare": {
        "ingredients": ["Tequila", "Rum", "Pineapple Juice", "Lime Juice", "Grenadine"],
        "price": 36,
        "alcohol_content": 3,
        "desc": "A fiery tropical station special with a bright red glow.",
    },
}

SPIRITS = ["Vodka", "Gin", "Rum", "Whiskey", "Tequila", "Brandy", "Scotch"]
AVAILABLE_INGREDIENTS = SPIRITS + [
    "Orange Juice", "Cranberry Juice", "Pineapple Juice", "Tomato Juice",
    "Tonic Water", "Soda Water", "Water", "Cola", "Ginger Ale", "Sprite",
    "Lemon Juice", "Lime Juice", "Sugar", "Salt", "Honey",
    "Triple Sec", "Blue Curacao", "Orange Curacao", "Grenadine",
    "Bitters", "Vermouth", "Campari", "Cherry Brandy",
    "Mint", "Coconut Cream", "Hot Sauce", "Worcestershire Sauce",
    "Cinnamon", "Orgeat Syrup", "Dry Ice", "Helium Gas",
]

BASIC_RECIPES = ["Screwdriver", "Gin and Tonic", "Rum and Cola", "Whiskey Sour", "Daiquiri"]
SPECIAL_RECIPES = ["Space Blaster", "Quantum Fizz", "Nebula Cloud", "Solar Flare"]
MODIFIERS = [
    "Lemon Juice", "Lime Juice", "Sugar", "Salt", "Honey", "Triple Sec",
    "Blue Curacao", "Orange Curacao", "Grenadine", "Bitters", "Vermouth",
    "Campari", "Cherry Brandy",
]
BASIC_ALCOHOLIC_DRINKS = frozenset(SPIRITS) | {"Beer", "Wine"}


def is_drink_alcoholic(name, details):
    """Return True if the drink contains alcohol."""
    if name in DRINKS_MENU:
        return name in BASIC_ALCOHOLIC_DRINKS
    return any(ing in SPIRITS for ing in details.get("ingredients", []))


def drink_id(name):
    return f"drink_{name.lower().replace(' ', '_')}"


def drink_item(name, details):
    """The inventory item for a glass of the drink called name, made from its menu or recipe details."""
    alcoholic = is_drink_alcoholic(name, details)
    return {
        "id": drink_id(name),
        "name": name,
        "description": details["desc"],
        "category": "Drink",
        "attributes": {
            "alcoholic": alcoholic,
            "alcohol_content": details.get("alcohol_content", 0),
            "quenches": ALCOHOL_QUENCHES if alcoholic else DEFAULT_QUENCHES,
        },
        "actions": ["examine", "drink", "drop"],
    }


def _is_mixer(ingredient):
    return any(word in ingredient for word in ("Juice", "Water", "Cola", "Ale", "Sprite"))


def categorize_ingredients(ingredients=None):
    """Return (spirits, mixers, modifiers, specials) for the mixer UI."""
    ingredients = ingredients or AVAILABLE_INGREDIENTS
    spirits = [i for i in ingredients if i in SPIRITS]
    mixers = [i for i in ingredients if _is_mixer(i)]
    modifiers = [i for i in ingredients if i in MODIFIERS]
    specials = [i for i in ingredients if i not in spirits and i not in mixers and i not in modifiers]
    return spirits, mixers, modifiers, specials


def categorize_ingredients_exclusive(ingredients=None):
    """Return mutually exclusive (spirits, mixers, modifiers, specials) for display."""
    ingredients = sorted(ingredients or AVAILABLE_INGREDIENTS)
    spirits = []
    mixers = []
    modifiers = []
    specials = []

    for ingredient in ingredients:
        if ingredient in SPIRITS:
            spirits.append(ingredient)
        elif _is_mixer(ingredient):
            mixers.append(ingredient)
        elif ingredient in MODIFIERS:
            modifiers.append(ingredient)
        else:
            specials.append(ingredient)

    return spirits, mixers, modifiers, specials


def get_mix_feedback(ingredients):
    """Return failure feedback for an unknown ingredient mix."""
    if len(ingredients) > 5:
        return "This has too many ingredients - most cocktails use 2-5 ingredients."
    if not any(item in SPIRITS for item in ingredients):
        return "Most mixed drinks need a spirit as the base (like Vodka, Rum, or Whiskey)."
    if all(item in SPIRITS for item in ingredients):
        return "This is just a mix of different spirits. Try adding some mixers or modifiers."
    return "This combination doesn't match any known recipe. Try a different mix."


def mixer_shelf(game):
    spirits, mixers, modifiers, specials = categorize_ingredients()
    return {
        "All": ("All Ingredients", AVAILABLE_INGREDIENTS),
        "Spirits": ("Spirits", spirits),
        "Mixers": ("Mixers", mixers),
        "Modifiers": ("Modifiers", modifiers),
        "Specials": ("Special Ingredients", specials),
    }


MAX_GLASS_POURS = 10


def mix_drink(game, ingredients):
    drink, recipe = match_recipe(MIXED_DRINKS, ingredients)
    if not drink:
        return {"text": f"You've created an unknown concoction. {get_mix_feedback(ingredients)}", "color": "red"}
    quantity = add_to_stock(game.player_data["bar_mixed_stock"], drink)
    game.add_note(f"Successfully mixed {with_article(drink)} at the bar.")
    return {
        "text": f"Success! You've mixed {with_article(drink)}.\n{recipe['desc']}\n(Qty: {quantity})",
        "color": "lightgreen",
    }


def _advanced_recipes():
    return sorted(d for d in MIXED_DRINKS if d not in BASIC_RECIPES and d not in SPECIAL_RECIPES)


def _recipe_sections(category):
    basic = ("BASIC COCKTAILS", sorted(BASIC_RECIPES))
    advanced = ("ADVANCED COCKTAILS", _advanced_recipes())
    special = ("STATION SPECIALTIES", sorted(SPECIAL_RECIPES))
    return {"basic": [basic], "advanced": [advanced], "special": [special]}.get(category, [basic, advanced, special])


register_recipe_book(RecipeBook(
    panel="recipes",
    title="Bartender's Recipe Book",
    recipes=MIXED_DRINKS,
    categories=(
        ("all", "All Recipes"),
        ("basic", "Basic Recipes"),
        ("advanced", "Advanced Recipes"),
        ("special", "Station Specials"),
    ),
    sections=_recipe_sections,
    ingredients_panel="ingredients",
))


@register_panel("ingredients", "Available Ingredients")
def ingredients_panel(game, state):
    spirits, mixers, modifiers, specials = categorize_ingredients_exclusive()
    return {
        "sections": [
            ("SPIRITS", spirits),
            ("MIXERS", mixers),
            ("MODIFIERS", modifiers),
            ("SPECIAL INGREDIENTS", specials),
        ],
    }


COFFEE_GROUNDS = "Coffee Grounds"
COFFEE_RECIPES = {
    "Coffee": {
        "ingredients": [COFFEE_GROUNDS, "Water"],
        "desc": "A cup of hot black coffee from the shuttle's machine.",
    },
}
COFFEE_MACHINE_CAPACITY = 2


def coffee_shelf(game):
    return {"All": ("Supplies", [COFFEE_GROUNDS, "Water"])}


def brew_coffee(game, ingredients):
    """Brew what is in the coffee machine. Only grounds and water make a cup, which goes in the inventory."""
    name, recipe = match_recipe(COFFEE_RECIPES, ingredients)
    if name:
        add_to_inventory(game.player_data, drink_item(name, recipe))
        game.add_note(f"Brewed {with_article(name.lower())} in the shuttle's coffee machine.")
        return {"text": f"The machine gurgles and fills a cup. You take {with_article(name.lower())}.",
                "color": "lightgreen"}
    if COFFEE_GROUNDS not in ingredients:
        return {"text": "The water runs through clear. It needs coffee grounds.", "color": "orange"}
    return {"text": "The grounds scorch on the hot plate. It needs water.", "color": "orange"}
