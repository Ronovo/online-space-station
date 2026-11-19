import pytest

from helpers import (
    add_ingredients,
    buttons,
    crew,
    ctx,
    duty,
    give_duty,
    in_room,
    job_event,
    labels,
    last_message,
    new_game,
    notes,
    panel,
    serve,
)
from space_online.game.maps.donut import BAR_KEY, KITCHEN_KEY
from space_online.game.objects.dishes import DISHES, MAX_PAN_INGREDIENTS, PANTRY_INGREDIENTS
from space_online.game.objects.items import add_to_inventory, get_item_definition
from space_online.game.special_rooms.kitchen import STOVE
from space_online.game.special_rooms.service_window import MAX_WINDOW_PASS, tick_service_window


def chef_station():
    return in_room(KITCHEN_KEY, "Civilian", "Chef", room_mode="service_station")


def bartender_station():
    return in_room(BAR_KEY, "Civilian", "Bartender", room_mode="service_station")


def window(game):
    return game.player_data["service_window"]


def test_the_kitchen_is_next_to_the_bar_and_a_chef_starts_with_a_station():
    game = new_game("Civilian", "Chef")
    game.player_data["location"] = {"x": 0, "y": 2}
    grid = game.view()["screen"]["grid"]
    assert grid[2][1] == {"label": "Kitchen", "action": "game.enter_room", "args": {"room_key": KITCHEN_KEY}}
    game.perform("game.enter_room", {"room_key": KITCHEN_KEY})
    assert buttons(game) == [("Enter Chef Station", "room.open_station"), ("Lock/Unlock Door", "room.toggle_door"),
                             ("Room Options", "room.set_mode")]
    game.perform("room.open_station", {"mode": "service_station"})
    assert labels(game) == ["Cook Dishes", "View Recipes", "Serve Food", "Service Window", "Stock the Kitchen",
                            "Back to Station Menu"]
    assert all(member["job"] != "Chef" for member in game.station_crew)


def test_crew_order_food_from_the_chef():
    game = in_room(KITCHEN_KEY)
    assert buttons(game) == [("Order Food", "room.show_menu")]
    game.player_data["kitchen_stock"] = {"Omelette": 1}
    game.perform("room.show_menu", {})
    assert panel(game)["type"] == "food_menu"
    assert ctx(game)["categories"] == ["All Food", "Basics", "Dishes"]
    assert ctx(game)["description"] == "Select a dish to see its description"
    game.perform("panel.category", {"name": "Dishes"})
    assert ctx(game)["rows"] == [{"name": "Omelette", "label": "Omelette (Qty: 1) - 18 credits"}]
    game.perform("panel.select", {"name": "Omelette"})
    game.perform("panel.order", {})
    assert last_message(game) == ("Order Successful",
                                  "You've ordered an Omelette for 18 credits. It has been added to your inventory.")
    dish = game.player_data["inventory"][0]
    assert (dish["id"], dish["category"], dish["actions"]) == ("dish_omelette", "Food", ["examine", "eat", "drop"])
    assert (game.player_data["credits"], game.player_data["kitchen_stock"]) == (982, {})


def test_the_chef_eats_free():
    game = chef_station()
    game.perform("room.show_menu", {})
    game.perform("panel.select", {"name": "Bread Roll"})
    game.perform("panel.order", {})
    assert last_message(game) == ("Order Successful",
                                  "You plate yourself a Bread Roll on the house. It has been added to your inventory.")
    assert game.player_data["credits"] == 2000


def test_only_the_chef_gets_the_stove():
    game = in_room(KITCHEN_KEY)
    for action in ("show_mixer", "show_recipes", "show_window"):
        game.perform(f"room.{action}", {})
    game.perform("room.serve_order", {"duty_id": "none"})
    assert game.ui["panels"] == []


def test_cooking_a_recipe_stocks_the_kitchen():
    game = chef_station()
    game.perform("room.show_mixer", {})
    labels = ctx(game)["labels"]
    assert (panel(game)["template"], labels.title, labels.container_label) == ("mixer", "Chef's Stove", "Pan")
    assert ctx(game)["categories"] == ["All", "Produce", "Staples", "Proteins", "Seasonings", "Window", "Botany"]
    add_ingredients(game, "Egg", "Cheese", "Butter")
    game.perform("panel.mix", {})
    assert ctx(game)["result"] == {"text": f"Success! You've cooked an Omelette.\n{DISHES['Omelette']['desc']}\n(Qty: 1)",
                                   "color": "lightgreen"}
    assert game.player_data["kitchen_stock"] == {"Omelette": 1}
    assert notes(game)[-1] == "Successfully cooked an Omelette in the kitchen."


@pytest.mark.parametrize("pan, feedback", [
    (["Egg"], "One ingredient on its own isn't a dish."),
    (["Egg"] * 6, "That's too much in one pan - dishes use 3-5 ingredients."),
    (["Egg", "Fish"], "Check the recipe book for what goes together."),
])
def test_a_pan_that_makes_no_dish_says_why(pan, feedback):
    game = chef_station()
    game.perform("room.show_mixer", {})
    add_ingredients(game, *pan)
    game.perform("panel.mix", {})
    assert ctx(game)["result"] == {"text": f"You've cooked something nobody would order. {feedback}", "color": "red"}
    assert game.player_data["kitchen_stock"] == {}


def test_the_pan_holds_a_limited_number_of_ingredients():
    game = chef_station()
    game.perform("room.show_mixer", {})
    add_ingredients(game, *["Rice"] * (MAX_PAN_INGREDIENTS + 1))
    assert last_message(game) == ("Stove", "The pan is full.")


def test_the_chefs_recipe_book():
    game = chef_station()
    game.perform("room.show_recipes", {})
    assert (panel(game)["type"], panel(game)["template"]) == ("kitchen_recipes", "recipes")
    assert [section["title"] for section in ctx(game)["sections"]] == ["SIMPLE DISHES", "MAIN COURSES"]
    game.perform("panel.category", {"name": "simple"})
    assert [recipe["name"] for recipe in ctx(game)["sections"][0]["recipes"]] == [
        "Apple Pie", "Garden Salad", "Mashed Potatoes", "Omelette", "Tomato Soup"]
    game.perform("panel.category", {"name": "mains"})
    assert "Rum Cake" in [recipe["name"] for recipe in ctx(game)["sections"][0]["recipes"]]
    game.perform("panel.search", {"query": "wine"})
    assert [recipe["name"] for recipe in ctx(game)["sections"][0]["recipes"]] == ["Coq au Vin"]
    game.perform("panel.ingredients", {})
    assert panel(game)["type"] == "kitchen_recipes"
    game.ui["panels"] = []
    game.perform("room.show_mixer", {})
    game.perform("panel.recipes", {})
    assert panel(game)["type"] == "kitchen_recipes"


def food_order(game, dish="Omelette", patron="Morgan Yu", reward=18, room=KITCHEN_KEY):
    give_duty(game, kind="serve", room=room, item=dish, patron=patron, reward=reward, summary="Serve it")
    return game


def test_serving_a_food_order_from_stock():
    game = food_order(chef_station())
    assert ("Serve Omelette to Morgan Yu", "room.serve_order") in buttons(game)
    serve(game)
    assert last_message(game) == ("Not in Stock", "There's no Omelette ready. Cook one first.")
    game.player_data["kitchen_stock"]["Omelette"] = 1
    serve(game)
    assert (game.player_data["kitchen_stock"], game.player_data["credits"]) == ({}, 2018)
    assert last_message(game) == ("Duty Done", "You serve Morgan Yu an Omelette. They pay you 18 credits.")
    assert game.player_data["duties"] == []


def test_an_order_is_served_in_the_room_it_was_made_for():
    game = food_order(bartender_station())
    game.player_data["bar_mixed_stock"]["Omelette"] = 1
    assert labels(game)[-2:] == ["Service Window", "Back to Station Menu"]
    serve(game)
    assert (game._messages, duty(game)["room"]) == ([], KITCHEN_KEY)


def open_window(game, mode=None):
    game.ui["panels"] = []
    game.perform("room.show_window", {})
    if mode:
        game.perform("panel.mode", {"name": mode})
    return game


def send(game, name, amount):
    game.perform("panel.select", {"name": name})
    game.perform("panel.confirm", {"amount": amount})


def test_the_chef_puts_ingredients_on_the_window_for_the_bar():
    game = open_window(chef_station())
    context = ctx(game)
    assert (context["here"].place, context["there"].job, context["mode"]) == ("kitchen", "Bartender", "pass")
    assert context["ingredients"] == PANTRY_INGREDIENTS
    send(game, "Celery", "2")
    assert window(game)["stock"] == {"bar": {"Celery": 2}, "kitchen": {}}
    assert ctx(game)["sent"] == [("Celery", 2)]
    assert ctx(game)["feedback"]["text"] == "You put 2 Celery on the window for the bar."
    assert notes(game)[-1] == "Passed 2 Celery through the service window to the bar."


def test_what_the_bartender_asked_for_is_taken_first():
    game = open_window(chef_station())
    window(game)["requests"]["bar"] = {"Celery": 2}
    assert ctx(game)["requests"] == [("Celery", 2)]
    send(game, "Celery", "1")
    assert (window(game)["requests"]["bar"], window(game)["stock"]["bar"]) == ({"Celery": 1}, {})
    assert ctx(game)["feedback"]["text"] == "You pass 1 Celery through the window. The Bartender takes 1."
    send(game, "Celery", "3")
    assert (window(game)["requests"]["bar"], window(game)["stock"]["bar"]) == ({}, {"Celery": 2})
    assert ctx(game)["feedback"]["text"] == "You pass 3 Celery through the window. The Bartender takes 1."


def test_the_bartender_asks_the_chef_for_what_only_the_kitchen_has():
    game = open_window(bartender_station(), mode="ask")
    assert (ctx(game)["mode"], ctx(game)["ingredients"]) == ("ask", PANTRY_INGREDIENTS)
    send(game, "Celery", "2")
    assert window(game)["stock"]["bar"] == {"Celery": 2}
    assert ctx(game)["waiting"] == [("Celery", 2)]
    assert ctx(game)["feedback"]["text"] == "The Chef passes 2 Celery through the window."


def away(game):
    crew(game, "Chef").update(on_duty=False, location={"x": 2, "y": 5})


def jailed(game):
    crew(game, "Chef").update(in_jail=True, jail_release_at_seconds=600)


def gone(game):
    game.player_data["station_crew"] = [member for member in game.station_crew if member["job"] != "Chef"]


@pytest.mark.parametrize("change, works", [(None, True), (away, True), (jailed, False), (gone, False)])
def test_the_chef_passes_things_through_exactly_when_they_could_ask_for_them(monkeypatch, change, works):
    game = open_window(bartender_station(), mode="ask")
    if change:
        change(game)
    asks = job_event(monkeypatch, game, roll=0.99)["title"] == "Window Request"
    send(game, "Celery", "2")
    passed = window(game)["stock"]["bar"] == {"Celery": 2}
    assert (asks, passed) == (works, works)
    if not works:
        assert window(game)["requests"]["bar"] == {"Celery": 2}
        assert ctx(game)["feedback"]["text"] == (
            "The Chef can't pass you Celery right now. It will come through the window when they can.")
        assert notes(game)[-1] == "Asked the Chef for 2 Celery at the service window."


def test_an_ask_waits_while_the_chef_cannot_work_and_comes_through_when_they_can():
    game = open_window(bartender_station(), mode="ask")
    jailed(game)
    send(game, "Celery", "2")
    send(game, "Celery", "1")
    tick_service_window(game)
    assert (window(game)["requests"]["bar"], window(game)["stock"]["bar"]) == ({"Celery": 3}, {})
    crew(game, "Chef")["in_jail"] = False
    tick_service_window(game)
    assert (window(game)["requests"]["bar"], window(game)["stock"]["bar"]) == ({}, {"Celery": 3})
    assert last_message(game) == ("Service Window", "The Chef passes 3 Celery through the window.")
    assert notes(game)[-1] == "The Chef passed 3 Celery through the service window."


def test_an_ask_waits_while_the_bartender_cannot_work_and_comes_through_when_they_can():
    game = open_window(chef_station(), mode="ask")
    bartender = crew(game, "Bartender")
    bartender["limbs"] = {limb: 0 for limb in bartender["limbs"]}
    send(game, "Beer", "2")
    assert ctx(game)["feedback"]["text"] == (
        "The Bartender can't pass you Beer right now. It will come through the window when they can.")
    tick_service_window(game)
    assert (window(game)["requests"]["kitchen"], window(game)["stock"]["kitchen"]) == ({"Beer": 2}, {})
    bartender["limbs"] = {limb: 100 for limb in bartender["limbs"]}
    tick_service_window(game)
    assert (window(game)["requests"]["kitchen"], window(game)["stock"]["kitchen"]) == ({}, {"Beer": 2})
    assert last_message(game) == ("Service Window", "The Bartender passes 2 Beer through the window.")


def test_what_is_asked_of_the_players_own_job_waits_for_the_player():
    game = chef_station()
    window(game)["requests"]["bar"] = {"Celery": 2}
    crew(game, "Bartender")["job"] = "Chef"
    tick_service_window(game)
    assert (window(game)["requests"]["bar"], window(game)["stock"]["bar"]) == ({"Celery": 2}, {})


@pytest.mark.parametrize("amount", ["lots", "0", str(MAX_WINDOW_PASS + 1)])
def test_the_window_takes_a_sensible_amount_of_a_chosen_ingredient(amount):
    game = open_window(chef_station())
    send(game, "Celery", amount)
    assert last_message(game) == ("Service Window", f"Enter an amount from 1 to {MAX_WINDOW_PASS}.")
    assert window(game)["stock"]["bar"] == {}


def test_the_window_only_lists_what_the_giving_side_has():
    game = open_window(chef_station())
    game.perform("panel.confirm", {"amount": "1"})
    assert last_message(game) == ("Service Window", "Select an ingredient first.")
    game.perform("panel.select", {"name": "Vodka"})
    assert ctx(game)["selected"] is None
    game.perform("panel.select", {"name": "Celery"})
    game.perform("panel.mode", {"name": "steal"})
    assert (ctx(game)["mode"], ctx(game)["selected"]) == ("pass", "Celery")
    game.perform("panel.mode", {"name": "ask"})
    assert (ctx(game)["selected"], "Vodka" in ctx(game)["ingredients"]) == (None, True)


def test_a_bloody_mary_needs_celery_from_the_window():
    game = bartender_station()
    game.perform("room.show_mixer", {})
    assert "Celery" not in ctx(game)["ingredients"]
    window(game)["stock"]["bar"] = {"Celery": 1}
    context = ctx(game)
    assert ("Celery" in context["ingredients"], context["counts"], context["categories"][-1]) == (
        True, {"Celery": 1}, "Window")
    game.perform("panel.category", {"name": "Window"})
    assert (ctx(game)["heading"], ctx(game)["ingredients"]) == ("--- From the Service Window ---", ["Celery"])
    add_ingredients(game, "Celery", "Celery")
    assert last_message(game) == ("Mixer", "There is no more Celery to add.")
    assert (ctx(game)["glass"], ctx(game)["counts"]) == (["Celery"], {"Celery": 0})
    game.perform("panel.category", {"name": "All"})
    add_ingredients(game, "Vodka", "Tomato Juice", "Hot Sauce", "Worcestershire Sauce")
    game.perform("panel.mix", {})
    assert game.player_data["bar_mixed_stock"] == {"Bloody Mary": 1}
    assert window(game)["stock"]["bar"] == {}


def test_a_dish_can_use_drink_from_the_bar():
    game = chef_station()
    window(game)["stock"]["kitchen"] = {"Beer": 2}
    game.perform("room.show_mixer", {})
    add_ingredients(game, "Fish", "Flour", "Potato", "Beer")
    game.perform("panel.mix", {})
    assert game.player_data["kitchen_stock"] == {"Beer-Battered Fish": 1}
    assert window(game)["stock"]["kitchen"] == {"Beer": 1}


def test_the_chef_gets_a_food_order(monkeypatch):
    game = new_game("Civilian", "Chef")
    patron = game.station_crew[0]["name"]
    event = job_event(monkeypatch, game, roll=0.0)
    assert (event["title"], event["desc"]) == (
        "Food Order", f"{patron} orders a Tomato Soup. Cook one and serve it from the Chef Station for 18 credits.")
    event["effect"]()
    assert duty(game) == {"kind": "serve", "room": KITCHEN_KEY, "item": "Tomato Soup", "patron": patron,
                          "reward": 18, "summary": f"Serve a Tomato Soup to {patron} (18 cr)"}


def test_the_bartender_asks_the_chef_for_an_ingredient_without_paying(monkeypatch):
    game = new_game("Civilian", "Chef")
    event = job_event(monkeypatch, game, roll=0.99)
    assert (event["title"], event["desc"]) == (
        "Window Request", "The Bartender asks for 3 Celery at the service window. "
                          "Put it on the window from the Chef Station when you can.")
    event["effect"]()
    assert window(game)["requests"] == {"bar": {"Celery": 3}, "kitchen": {}}
    assert game.player_data["duties"] == []
    assert job_event(monkeypatch, game, roll=0.99)["title"] == "Food Order"


def test_the_chef_asks_the_bartender_for_drink(monkeypatch):
    game = new_game("Civilian", "Bartender")
    event = job_event(monkeypatch, game, roll=0.99)
    assert event["desc"].startswith("The Chef asks for 3 Beer at the service window.")
    gone(game)
    assert job_event(monkeypatch, game, roll=0.99)["title"] == "Drink Order"


def test_the_chef_stocks_the_kitchen_with_bought_produce():
    game = chef_station()
    assert ("Stock the Kitchen", "room.stock_kitchen") in buttons(game)
    botany = next(supply for supply in STOVE.supplies if supply.key == "Botany")
    before = botany.counts(game)["Carrot"]
    for _ in range(2):
        add_to_inventory(game.player_data, get_item_definition("carrot"))
    game.perform("room.stock_kitchen", {})
    assert (botany.counts(game)["Carrot"], game.player_data["inventory"]) == (before + 2, [])
    assert last_message(game) == ("Station Stores", "You send 2 Carrot to the Kitchen.")
    game.perform("room.stock_kitchen", {})
    assert last_message(game) == ("Station Stores", "You have no produce the kitchen cooks with.")
