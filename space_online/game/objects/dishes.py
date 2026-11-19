"""Food from the kitchen: the menu's ready-made basics, the pantry, and the dishes the stove cooks from it and
from the produce Botany sends (see stores)."""

from space_online.game.helper_methods.errands import with_article
from space_online.game.helper_methods.mixing import RecipeBook, add_to_stock, match_recipe, register_recipe_book

FOOD_MENU = {
    "Bread Roll": {"price": 3, "desc": "A warm roll, fresh from the oven."},
    "Boiled Egg": {"price": 4, "desc": "A plain boiled egg. Dependable."},
    "Fruit Cup": {"price": 5, "desc": "Diced fruit in a small cup."},
    "Side Salad": {"price": 6, "desc": "A few leaves and a slice of tomato."},
    "Rice Bowl": {"price": 6, "desc": "A bowl of plain steamed rice."},
}

DISHES = {
    "Tomato Soup": {
        "ingredients": ["Tomato", "Onion", "Butter"],
        "price": 18,
        "desc": "A smooth, warming soup.",
    },
    "Mashed Potatoes": {
        "ingredients": ["Potato", "Butter", "Milk"],
        "price": 16,
        "desc": "Creamy mashed potatoes.",
    },
    "Omelette": {
        "ingredients": ["Egg", "Cheese", "Butter"],
        "price": 18,
        "desc": "A folded omelette with melted cheese.",
    },
    "Garden Salad": {
        "ingredients": ["Lettuce", "Tomato", "Carrot"],
        "price": 15,
        "desc": "Crisp vegetables straight from the botany lab.",
    },
    "Apple Pie": {
        "ingredients": ["Apple", "Flour", "Butter", "Sugar"],
        "price": 26,
        "desc": "A golden pie with a sweet apple filling.",
    },
    "Cheeseburger": {
        "ingredients": ["Beef", "Bread", "Cheese", "Lettuce"],
        "price": 30,
        "desc": "A grilled beef patty with cheese in a bun.",
    },
    "Spaghetti Bolognese": {
        "ingredients": ["Pasta", "Beef", "Tomato", "Onion"],
        "price": 32,
        "desc": "Pasta in a rich meat sauce.",
    },
    "Chicken Stir Fry": {
        "ingredients": ["Chicken", "Rice", "Carrot", "Soy Sauce"],
        "price": 30,
        "desc": "Chicken and vegetables tossed over rice.",
    },
    "Station Stew": {
        "ingredients": ["Beef", "Potato", "Carrot", "Onion"],
        "price": 30,
        "desc": "The crew's favourite: a thick stew that sticks to your ribs.",
    },
    "Beer-Battered Fish": {
        "ingredients": ["Fish", "Flour", "Potato", "Beer"],
        "price": 34,
        "desc": "Crisp battered fish with chips. The batter needs beer from the bar.",
    },
    "Coq au Vin": {
        "ingredients": ["Chicken", "Mushroom", "Onion", "Wine"],
        "price": 38,
        "desc": "Chicken braised in wine from the bar.",
    },
    "Rum Cake": {
        "ingredients": ["Flour", "Egg", "Sugar", "Butter", "Rum"],
        "price": 36,
        "desc": "A dense cake soaked in rum from the bar.",
    },
}

PANTRY = {
    "Produce": ["Onion", "Celery", "Lettuce", "Mushroom"],
    "Staples": ["Flour", "Rice", "Pasta", "Bread", "Egg", "Butter", "Cheese", "Milk", "Sugar", "Salt"],
    "Proteins": ["Beef", "Chicken", "Fish"],
    "Seasonings": ["Herbs", "Pepper", "Soy Sauce"],
}
PANTRY_INGREDIENTS = sorted(name for names in PANTRY.values() for name in names)

SIMPLE_DISHES = ["Tomato Soup", "Mashed Potatoes", "Omelette", "Garden Salad", "Apple Pie"]
MAX_PAN_INGREDIENTS = 8


def stove_shelf(game):
    return {"All": ("All Ingredients", PANTRY_INGREDIENTS), **{name: (name, items) for name, items in PANTRY.items()}}


def get_cook_feedback(ingredients):
    """Return failure feedback for ingredients that make no known dish."""
    if len(ingredients) < 2:
        return "One ingredient on its own isn't a dish."
    if len(ingredients) > 5:
        return "That's too much in one pan - dishes use 3-5 ingredients."
    return "Check the recipe book for what goes together."


def cook_dish(game, ingredients):
    dish, recipe = match_recipe(DISHES, ingredients)
    if not dish:
        return {"text": f"You've cooked something nobody would order. {get_cook_feedback(ingredients)}",
                "color": "red"}
    quantity = add_to_stock(game.player_data["kitchen_stock"], dish)
    game.add_note(f"Successfully cooked {with_article(dish)} in the kitchen.")
    return {
        "text": f"Success! You've cooked {with_article(dish)}.\n{recipe['desc']}\n(Qty: {quantity})",
        "color": "lightgreen",
    }


def _recipe_sections(category):
    simple = ("SIMPLE DISHES", sorted(SIMPLE_DISHES))
    mains = ("MAIN COURSES", sorted(dish for dish in DISHES if dish not in SIMPLE_DISHES))
    return {"simple": [simple], "mains": [mains]}.get(category, [simple, mains])


register_recipe_book(RecipeBook(
    panel="kitchen_recipes",
    title="Chef's Recipe Book",
    recipes=DISHES,
    categories=(("all", "All Recipes"), ("simple", "Simple Dishes"), ("mains", "Main Courses")),
    sections=_recipe_sections,
))
