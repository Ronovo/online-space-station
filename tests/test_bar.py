import pytest

from helpers import new_game
from space_online.game.helper_methods import npc_movement
from space_online.game.objects.drinks import MAX_GLASS_POURS, MIXED_DRINKS
from space_online.game.special_rooms import bar
from space_online.game.maps.donut import BAR_KEY, location_from_key


def at_bar(department="Civilian", job="Staff Assistant"):
    game = new_game(department, job)
    game.player_data["location"] = location_from_key(BAR_KEY)
    return game


def bartender(game):
    return next(npc for npc in game.station_crew if npc["job"] == "Bartender")


def buttons(game):
    return [(w.get("label") or w.get("text"), w.get("action")) for w in game.view()["screen"]["buttons"]]


def panel(game):
    return game.view()["panel"]


def last_message(game):
    return game._messages[-1][1:3]


def test_the_bar_takes_orders_while_the_bartender_is_in():
    game = at_bar()
    assert buttons(game) == [("Order Drinks", "room.show_drink_menu"), ("Socialize", "room.socialize")]


def test_an_absent_bartender_can_be_called(monkeypatch):
    game = at_bar()
    away = bartender(game)
    away.update(on_duty=False, location={"x": 2, "y": 5})
    assert buttons(game) == [("The bartender is away from the bar.", None), (f"Call {away['name']}", "room.call_npc"),
                             ("Socialize", "room.socialize")]
    game.perform("room.show_drink_menu", {})
    assert game.ui["panels"] == []
    monkeypatch.setattr(npc_movement.random, "random", lambda: 0.0)
    game.perform("room.call_npc", {"job": "Bartender"})
    assert last_message(game) == ("Call Successful", f"{away['name']} answers the call and heads back to their post.")
    assert away["on_duty"]


def test_an_unanswered_call(monkeypatch):
    game = at_bar()
    away = bartender(game)
    away.update(on_duty=False, location={"x": 2, "y": 5})
    monkeypatch.setattr(npc_movement.random, "random", lambda: 0.99)
    game.perform("room.call_npc", {"job": "Bartender"})
    assert last_message(game) == ("No Answer", f"{away['name']} doesn't answer. Maybe try calling again later.")
    assert not away["on_duty"]


def test_calling_a_jailed_bartender():
    game = at_bar()
    jailed = bartender(game)
    jailed.update(in_jail=True, jail_release_at_seconds=60)
    game.perform("room.call_npc", {"job": "Bartender"})
    assert last_message(game) == ("In Jail", f"{jailed['name']} is in jail and will be released in 1m 0s.")


@pytest.mark.parametrize("department, job, call", [
    ("Civilian", "Staff Assistant", "Doctor"),
    ("Civilian", "Bartender", "Bartender"),
    ("Administration", "Head of Personnel", "Bartender"),
])
def test_calls_only_reach_someone_else_who_works_here(department, job, call):
    game = at_bar(department, job)
    game.perform("room.call_npc", {"job": call})
    assert game._messages == []


def test_a_jailed_bartender_shows_when_they_get_out():
    game = at_bar()
    jailed = bartender(game)
    jailed.update(in_jail=True, jail_release_at_seconds=60)
    assert buttons(game)[0] == (f"{jailed['name']} is in jail and will be released in 1m 0s.", None)


def test_socializing(monkeypatch):
    monkeypatch.setattr(bar.random, "choice", lambda options: options[2])
    game = at_bar()
    game.perform("room.socialize", {})
    assert last_message(game) == ("Socializing", bar.CONVERSATIONS[2])


def order(game, drink, category=None):
    game.ui["panels"] = []
    game.perform("room.show_drink_menu", {})
    if category:
        game.perform("panel.category", {"name": category})
    game.perform("panel.select", {"name": drink})
    game.perform("panel.order", {})


def test_ordering_a_drink():
    game = at_bar()
    order(game, "Beer")
    assert game.player_data["credits"] == 990
    drink = game.player_data["inventory"][0]
    assert (drink["id"], drink["attributes"]) == ("drink_beer", {"alcoholic": True, "alcohol_content": 1})
    assert last_message(game) == ("Order Successful",
                                  "You've ordered a Beer for 10 credits. It has been added to your inventory.")


def test_ordering_needs_a_drink_and_the_credits():
    game = at_bar()
    game.perform("room.show_drink_menu", {})
    game.perform("panel.order", {})
    assert last_message(game) == ("Selection Needed", "Please select a drink first")
    game.player_data["credits"] = 5
    order(game, "Beer")
    assert last_message(game) == ("Insufficient Credits", "You don't have enough credits to order Beer.")
    assert game.player_data["inventory"] == []


def test_ordering_a_mixed_drink_takes_one_from_stock():
    game = at_bar()
    game.player_data["bar_mixed_stock"] = {"Screwdriver": 2}
    order(game, "Screwdriver", category="Mixed Drinks")
    assert game.player_data["bar_mixed_stock"] == {"Screwdriver": 1}
    assert panel(game)["ctx"]["selected"] == "Screwdriver"


def test_the_last_mixed_drink_leaves_the_menu():
    game = at_bar()
    game.player_data["bar_mixed_stock"] = {"Screwdriver": 1}
    order(game, "Screwdriver", category="Mixed Drinks")
    assert game.player_data["bar_mixed_stock"] == {}
    assert game.player_data["inventory"][0]["attributes"]["alcoholic"]
    ctx = panel(game)["ctx"]
    assert (ctx["drinks"], ctx["selected"]) == ([], None)


def test_the_drink_menu_filters_by_category():
    game = at_bar()
    game.player_data["bar_mixed_stock"] = {"Screwdriver": 2, "Gin and Tonic": 0}
    game.perform("room.show_drink_menu", {})
    ctx = panel(game)["ctx"]
    assert "Screwdriver (Qty: 2) - 25 credits" in [row["label"] for row in ctx["drinks"]]
    assert ctx["description"] == "Select a drink to see its description"
    game.perform("panel.select", {"name": "Beer"})
    game.perform("panel.category", {"name": "Non-Alcoholic"})
    ctx = panel(game)["ctx"]
    assert "Beer" not in [row["name"] for row in ctx["drinks"]] and "Water" in [row["name"] for row in ctx["drinks"]]
    assert ctx["selected"] is None
    game.perform("panel.select", {"name": "Beer"})
    game.perform("panel.category", {"name": "Free Drinks"})
    assert panel(game)["ctx"]["category"] == "Non-Alcoholic"
    game.perform("panel.select", {"name": "Water"})
    assert panel(game)["ctx"]["description"] == "A glass of water. Refreshing and healthy."
    game.ui["panels"][-1]["selected"] = "Beer"
    assert panel(game)["ctx"]["selected"] is None


def test_alcoholic_drinks_include_mixed_drinks_with_a_spirit():
    game = at_bar()
    game.player_data["bar_mixed_stock"] = {"Screwdriver": 1}
    game.perform("room.show_drink_menu", {})
    game.perform("panel.category", {"name": "Alcoholic"})
    names = [row["name"] for row in panel(game)["ctx"]["drinks"]]
    assert "Screwdriver" in names and "Beer" in names and "Water" not in names


def test_the_bartender_works_the_station():
    game = at_bar("Civilian", "Bartender")
    assert buttons(game) == [("Enter Bartender Station", "room.open_station"), ("Lock/Unlock Door", "room.toggle_door"),
                             ("Room Options", "room.set_mode")]
    game.perform("room.open_station", {"mode": "bartender"})
    assert [label for label, _ in buttons(game)] == ["Mix Drinks", "View Recipes", "Serve Regular Drinks",
                                                     "Back to Station Menu"]
    game.perform("room.show_drink_menu", {})
    assert panel(game)["type"] == "drink_menu"
    game.ui["panels"] = []
    game.perform("room.show_recipes", {})
    assert panel(game)["type"] == "recipes"
    game.ui["panels"] = []
    game.perform("room.set_mode", {"mode": "options"})
    assert buttons(game) == [("Socialize", "room.socialize"), ("Back to Station Menu", "room.set_mode")]
    game.perform("room.set_mode", {"mode": "bartender"})
    assert game.ui["room_mode"] == "options"
    game.perform("room.toggle_door", {})
    assert game.ship_map[BAR_KEY]["locked"]


def test_an_unknown_room_mode_shows_the_station_menu():
    game = at_bar("Civilian", "Bartender")
    game.ui["room_mode"] = "dance_floor"
    assert buttons(game)[0] == ("Enter Bartender Station", "room.open_station")


def test_only_the_bartender_gets_the_station():
    game = at_bar()
    game.perform("room.open_station", {"mode": "bartender"})
    game.perform("room.show_drink_mixer", {})
    game.perform("room.toggle_door", {})
    game.ui["room_mode"] = "bartender"
    assert buttons(game)[0] == ("Order Drinks", "room.show_drink_menu")
    assert game.ui["panels"] == []
    assert not game.ship_map[BAR_KEY]["locked"]


def mixer():
    game = at_bar("Civilian", "Bartender")
    game.ui["room_mode"] = "bartender"
    game.perform("room.show_drink_mixer", {})
    return game


def pour(game, *ingredients):
    for ingredient in ingredients:
        game.perform("panel.select_ingredient", {"name": ingredient})
        game.perform("panel.add_ingredient", {})


def test_mixing_a_known_recipe_stocks_the_bar():
    game = mixer()
    pour(game, "Vodka", "Orange Juice")
    assert panel(game)["ctx"]["glass"] == ["Vodka", "Orange Juice"]
    game.perform("panel.mix", {})
    ctx = panel(game)["ctx"]
    assert ctx["result"] == {"text": f"Success! You've mixed a Screwdriver.\n{MIXED_DRINKS['Screwdriver']['desc']}\n"
                                     "(Qty: 1)", "color": "lightgreen"}
    assert ctx["glass"] == []
    assert game.player_data["bar_mixed_stock"] == {"Screwdriver": 1}


@pytest.mark.parametrize("glass, feedback", [
    ([], "You need to add ingredients first!"),
    (["Vodka", "Gin", "Rum", "Cola", "Sugar", "Salt"], "You've created an unknown concoction. This has too many "
                                                       "ingredients - most cocktails use 2-5 ingredients."),
    (["Cola", "Sugar"], "You've created an unknown concoction. Most mixed drinks need a spirit as the base "
                        "(like Vodka, Rum, or Whiskey)."),
    (["Vodka", "Gin"], "You've created an unknown concoction. This is just a mix of different spirits. Try adding "
                       "some mixers or modifiers."),
    (["Vodka", "Salt"], "You've created an unknown concoction. This combination doesn't match any known recipe. "
                        "Try a different mix."),
])
def test_mixes_that_do_not_work_explain_why(glass, feedback):
    game = mixer()
    pour(game, *glass)
    game.perform("panel.mix", {})
    assert panel(game)["ctx"]["result"]["text"] == feedback
    assert game.player_data["bar_mixed_stock"] == {}


def test_the_glass_holds_a_limited_number_of_pours():
    game = mixer()
    pour(game, *["Water"] * (MAX_GLASS_POURS + 1))
    assert last_message(game) == ("Mixer", "The glass is full.")
    assert len(panel(game)["ctx"]["glass"]) == MAX_GLASS_POURS


def test_ingredients_come_from_the_shown_category():
    game = mixer()
    game.perform("panel.category", {"name": "Spirits"})
    ctx = panel(game)["ctx"]
    assert (ctx["heading"], "Vodka" in ctx["ingredients"], "Cola" in ctx["ingredients"]) == ("--- Spirits ---", True,
                                                                                            False)
    pour(game, "Cola", "Moonshine", "Gin")
    assert panel(game)["ctx"]["glass"] == ["Gin"]
    game.perform("panel.category", {"name": "Snacks"})
    assert panel(game)["ctx"]["category"] == "Spirits"
    game.ui["panels"][-1]["category"] = "Snacks"
    assert panel(game)["ctx"]["category"] == "All"


def test_taking_ingredients_back_out_of_the_glass():
    game = mixer()
    pour(game, "Vodka", "Cola", "Sugar")
    game.perform("panel.select_glass", {"index": 1})
    assert panel(game)["ctx"]["selected_glass"] == 1
    game.perform("panel.remove_ingredient", {})
    game.perform("panel.remove_ingredient", {})
    assert panel(game)["ctx"]["glass"] == ["Vodka", "Sugar"]
    game.perform("panel.select_glass", {"index": 0})
    game.perform("panel.clear_glass", {})
    ctx = panel(game)["ctx"]
    assert (ctx["glass"], ctx["selected_glass"]) == ([], None)


def recipe_names(game):
    return [[recipe["name"] for recipe in section["recipes"]] for section in panel(game)["ctx"]["sections"]]


def test_the_recipe_book_by_category():
    game = mixer()
    game.perform("panel.recipes", {})
    assert [section["title"] for section in panel(game)["ctx"]["sections"]] == [
        "BASIC COCKTAILS", "ADVANCED COCKTAILS", "STATION SPECIALTIES"]
    game.perform("panel.category", {"name": "special"})
    assert recipe_names(game) == [["Nebula Cloud", "Quantum Fizz", "Solar Flare", "Space Blaster"]]
    game.perform("panel.category", {"name": "basic"})
    assert recipe_names(game)[0][0] == "Daiquiri"
    game.perform("panel.category", {"name": "advanced"})
    assert len(recipe_names(game)[0]) == len(MIXED_DRINKS) - 9
    game.perform("panel.category", {"name": "cursed"})
    assert len(recipe_names(game)[0]) == len(MIXED_DRINKS) - 9


def test_searching_recipes_by_name_ingredient_or_description():
    game = mixer()
    game.perform("panel.recipes", {})
    game.perform("panel.search", {"query": "  SCREWDRIVER "})
    ctx = panel(game)["ctx"]
    assert (ctx["header"], recipe_names(game), ctx["empty_message"]) == (
        "SEARCH RESULTS FOR 'screwdriver'", [["Screwdriver"]], None)
    game.perform("panel.search", {"query": "tonic water"})
    assert "Gin and Tonic" in recipe_names(game)[0]
    game.perform("panel.search", {"query": "classic mix"})
    assert "Screwdriver" in recipe_names(game)[0]
    game.perform("panel.search", {"query": "x" * 200})
    assert panel(game)["ctx"]["empty_message"] == "No recipes found matching your search."
    assert len(game.ui["panels"][-1]["query"]) == 100
    game.perform("panel.category", {"name": "basic"})
    assert panel(game)["ctx"]["query"] == ""


def test_the_ingredient_list_puts_each_ingredient_in_one_place():
    game = mixer()
    game.perform("panel.recipes", {})
    game.perform("panel.ingredients", {})
    sections = dict(panel(game)["ctx"]["sections"])
    listed = [name for names in sections.values() for name in names]
    assert len(listed) == len(set(listed))
    assert "Lemon Juice" in sections["MIXERS"] and "Lemon Juice" not in sections["MODIFIERS"]
    assert sections["SPIRITS"] == sorted(sections["SPIRITS"])
