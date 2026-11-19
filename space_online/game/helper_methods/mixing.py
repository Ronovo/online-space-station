"""Mixing stations and their recipe books.

A mixing station puts ingredients in a container and mixes them: the bar's drink mixer, the kitchen stove and
the chemistry dispenser are each one. A recipe book lists what a station can make.
"""

import functools
from dataclasses import dataclass
from typing import Callable, NamedTuple, Optional

from space_online.game.helper_methods.ui_panels import panel_action, register_panel


class Supply(NamedTuple):
    """Ingredients a station only has a counted number of, on top of its own shelf. A station can draw on several."""
    key: str
    heading: str
    counts: Callable  # game -> {name: count}
    take: Callable  # (game, name) uses one up


@dataclass(frozen=True)
class MixingStation:
    panel: str
    title: str
    name: str
    container: str
    container_label: str
    mix_label: str
    idle_text: str
    capacity: int
    shelf: Callable  # game -> {category key: (heading, names)}, with an "All" category
    mix: Callable  # (game, ingredients) -> {"text", "color"}
    supplies: tuple  # of Supply
    book: str


def match_recipe(recipes, ingredients):
    """(name, recipe) of the recipe made from exactly these ingredients, else (None, None)."""
    wanted = sorted(ingredients)
    for name, recipe in recipes.items():
        if wanted == sorted(recipe["ingredients"]):
            return name, recipe
    return None, None


def add_to_stock(stock, name):
    """Put one more of name in a stock of made items. Returns the new quantity."""
    stock[name] = stock.get(name, 0) + 1
    return stock[name]


def take_from_stock(stock, name):
    """Take one of name out of a stock, dropping the entry when it runs out."""
    stock[name] -= 1
    if stock[name] <= 0:
        del stock[name]


def _supply_counts(station, game):
    """{name: count} of everything the station's supplies hold."""
    counts = {}
    for supply in station.supplies:
        for name, count in supply.counts(game).items():
            counts[name] = counts.get(name, 0) + count
    return counts


def _categories(station, game):
    categories = dict(station.shelf(game))
    heading, shelved = categories["All"]
    categories["All"] = (heading, sorted(set(shelved) | set(_supply_counts(station, game))))
    for supply in station.supplies:
        categories[supply.key] = (supply.heading, sorted(supply.counts(game)))
    return categories


def _category(station, game, state):
    categories = _categories(station, game)
    key = state.get("category", "All")
    return key if key in categories else "All", categories


def _supplied(station, game):
    """{name: count} of the ingredients that only come from a supply."""
    shelved = station.shelf(game)["All"][1]
    return {name: count for name, count in _supply_counts(station, game).items() if name not in shelved}


def _take_supplied(station, game, name):
    """Use up one of name from the first supply that still has some."""
    supply = next(supply for supply in station.supplies if supply.counts(game).get(name, 0) > 0)
    supply.take(game, name)


def _context(station, game, state):
    key, categories = _category(station, game, state)
    heading, items = categories[key]
    glass = state.get("glass", [])
    return {
        "labels": station,
        "categories": list(categories),
        "category": key,
        "heading": f"--- {heading} ---",
        "ingredients": sorted(items),
        "counts": {name: count - glass.count(name) for name, count in _supplied(station, game).items()},
        "selected_ingredient": state.get("selected_ingredient"),
        "glass": glass,
        "selected_glass": state.get("selected_glass"),
        "result": state.get("result"),
    }


def category(station, game, state, args):
    if args["name"] in _categories(station, game):
        state["category"] = args["name"]
        state.pop("selected_ingredient", None)


def select_ingredient(station, game, state, args):
    if args["name"] in _categories(station, game)["All"][1]:
        state["selected_ingredient"] = args["name"]


def add_ingredient(station, game, state, args):
    key, categories = _category(station, game, state)
    ingredient = state.get("selected_ingredient")
    glass = state.setdefault("glass", [])
    supplied = _supplied(station, game)
    if len(glass) >= station.capacity:
        game.alert(station.name, f"The {station.container} is full.", kind="warning")
    elif ingredient in supplied and glass.count(ingredient) >= supplied[ingredient]:
        game.alert(station.name, f"There is no more {ingredient} to add.", kind="warning")
    elif ingredient in categories[key][1]:
        glass.append(ingredient)


def select_glass(station, game, state, args):
    state["selected_glass"] = int(args["index"])


def remove_ingredient(station, game, state, args):
    glass = state.setdefault("glass", [])
    index = state.pop("selected_glass", None)
    if index is not None and 0 <= index < len(glass):
        glass.pop(index)


def clear_glass(station, game, state, args):
    state["glass"] = []
    state.pop("selected_glass", None)


def mix(station, game, state, args):
    ingredients = state.get("glass", [])
    if not ingredients:
        state["result"] = {"text": "You need to add ingredients first!", "color": "white"}
        return

    supplied = _supplied(station, game)
    gone = sorted({name for name in ingredients if name in supplied and ingredients.count(name) > supplied[name]})
    if gone:
        state["result"] = {"text": f"There isn't enough {', '.join(gone)} left for that.", "color": "orange"}
        return
    for ingredient in ingredients:
        if ingredient in supplied:
            _take_supplied(station, game, ingredient)
    state["result"] = station.mix(game, ingredients)
    state["glass"] = []
    state.pop("selected_glass", None)


def recipes(station, game, state, args):
    game.open_panel(station.book)


MIXING_ACTIONS = (category, select_ingredient, add_ingredient, select_glass, remove_ingredient, clear_glass, mix,
                  recipes)


def register_mixing_station(station):
    register_panel(station.panel, station.title, template="mixer")(functools.partial(_context, station))
    for action in MIXING_ACTIONS:
        panel_action(station.panel, action.__name__)(functools.partial(action, station))
    return station


@dataclass(frozen=True)
class RecipeBook:
    panel: str
    title: str
    recipes: dict
    categories: tuple  # ((key, label), ...)
    sections: Callable  # category key -> [(section title, recipe names)]
    ingredients_panel: Optional[str] = None


def _recipe_entry(book, name):
    recipe = book.recipes[name]
    return {
        "name": name,
        "ingredients": ", ".join(recipe["ingredients"]),
        "price": recipe.get("price"),
        "desc": recipe["desc"],
    }


def _book_context(book, game, state):
    query = (state.get("query") or "").lower().strip()
    context = {"labels": book, "categories": book.categories}
    if not query:
        return {
            **context,
            "header": book.title.upper(),
            "sections": [{"title": title, "recipes": [_recipe_entry(book, name) for name in names]}
                         for title, names in book.sections(state.get("category"))],
            "query": "",
        }

    results = [
        _recipe_entry(book, name)
        for name, recipe in book.recipes.items()
        if query in name.lower()
        or any(query in ingredient.lower() for ingredient in recipe["ingredients"])
        or query in recipe["desc"].lower()
    ]
    return {
        **context,
        "header": f"SEARCH RESULTS FOR '{query}'",
        "sections": [{"title": None, "recipes": results}],
        "empty_message": None if results else "No recipes found matching your search.",
        "query": state.get("query", ""),
    }


def _book_category(book, game, state, args):
    if args["name"] in dict(book.categories):
        state["category"] = args["name"]
        state["query"] = ""


def _book_search(book, game, state, args):
    state["query"] = str(args.get("query", ""))[:100]


def _book_ingredients(book, game, state, args):
    if book.ingredients_panel:
        game.open_panel(book.ingredients_panel)


def register_recipe_book(book):
    register_panel(book.panel, book.title, template="recipes")(functools.partial(_book_context, book))
    for name, action in (("category", _book_category), ("search", _book_search), ("ingredients", _book_ingredients)):
        panel_action(book.panel, name)(functools.partial(action, book))
    return book
