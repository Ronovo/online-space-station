from helpers import new_game, reports
from space_online.game.objects.items import (
    add_to_inventory,
    get_item_definition,
    inventory_item_count,
    remove_one_from_inventory,
)


def give(game, *item_ids):
    for item_id in item_ids:
        add_to_inventory(game.player_data, get_item_definition(item_id))
    return game


def index_of(game, item_id):
    return next(i for i, item in enumerate(game.player_data["inventory"]) if item.get("id") == item_id)


def panel(game):
    return game.view()["panel"]


def last_message(game):
    return game._messages[-1][1:3]


def notes(game):
    return [note["text"] for note in game.player_data["notes"]]


def open_actions(game, item_id):
    """Open the inventory, select item_id and open its actions menu."""
    game.ui["panels"] = []
    game.open_panel("inventory")
    game.perform("panel.select", {"index": index_of(game, item_id)})
    game.perform("panel.actions", {})


def do(game, item_id, action):
    open_actions(game, item_id)
    game.perform("panel.item_action", {"name": action})


def test_unknown_items_have_no_definition():
    assert get_item_definition("flux_capacitor") is None


def test_items_stack_by_id_but_containers_never_do():
    game = give(new_game(), "snack", "snack", "basic_tools", "basic_tools")
    assert [(item["id"], item["quantity"]) for item in game.player_data["inventory"]] == [
        ("snack", 2), ("basic_tools", 1), ("basic_tools", 1)]
    assert inventory_item_count(game.player_data) == 4
    assert remove_one_from_inventory(game.player_data, 9) is None


def test_the_inventory_lists_stacks_and_hands():
    game = give(new_game(), "snack", "snack", "medkit")
    game.player_data["hands"]["left"] = get_item_definition("trowel")
    game.open_panel("inventory")
    ctx = panel(game)["ctx"]
    assert [row["label"] for row in ctx["item_rows"]] == ["Snack x 2", "Medkit"]
    assert [row["held"] for row in ctx["hands"]] == ["Trowel", None]
    assert (ctx["selected"], ctx["can_examine"], ctx["can_act"]) == (None, False, False)
    game.perform("panel.select", {"index": 1})
    ctx = panel(game)["ctx"]
    assert (ctx["selected"], ctx["can_examine"], ctx["can_act"]) == (1, True, True)


def test_examining_an_item():
    game = give(new_game(), "medkit")
    game.open_panel("inventory")
    game.perform("panel.select", {"index": 0})
    game.perform("panel.examine", {})
    assert last_message(game) == ("Examine: Medkit", "A standard first aid kit.")
    assert notes(game) == ["Examined the Medkit."]


def test_nothing_selected_means_nothing_to_examine_or_do():
    game = give(new_game(), "medkit")
    game.open_panel("inventory")
    game.perform("panel.select", {"index": 5})
    game.perform("panel.examine", {})
    game.perform("panel.actions", {})
    assert [message for _, _, message, _ in game._messages] == [
        "Could not identify the selected item.", "Cannot perform actions on this item."]


def test_an_item_with_nothing_to_do_says_so():
    game = new_game()
    add_to_inventory(game.player_data, {"id": "pebble", "name": "Pebble", "actions": ["examine"]})
    open_actions(game, "pebble")
    assert last_message(game) == ("No Actions", "No special actions available for Pebble.")
    assert panel(game)["type"] == "inventory"


def test_tools_offer_drop_but_not_use():
    game = give(new_game(), "wrench")
    open_actions(game, "wrench")
    ctx = panel(game)["ctx"]
    assert (ctx["title"], [a["name"] for a in ctx["actions"]]) == ("Actions: Wrench", ["drop"])
    game.perform("panel.item_action", {"name": "use"})
    assert game._messages == []


def test_reading_a_book_and_the_station_map():
    game = give(new_game(), "welcome_guide", "station_map")
    do(game, "welcome_guide", "read")
    ctx = panel(game)["ctx"]
    assert (ctx["title"], ctx["is_map"]) == ("Reading: Welcome Guide", False)
    assert ctx["content"] == get_item_definition("welcome_guide")["attributes"]["content"]
    do(game, "station_map", "read")
    assert panel(game)["ctx"]["is_map"]
    assert notes(game) == ["Read the Welcome Guide.", "Read the Station Map."]


def test_a_panel_for_an_item_that_is_gone_closes():
    game = give(new_game(), "welcome_guide")
    do(game, "welcome_guide", "read")
    game.player_data["inventory"].clear()
    assert panel(game)["type"] == "inventory"


def test_dropping_asks_first_and_takes_one():
    game = give(new_game(), "snack", "snack")
    do(game, "snack", "drop")
    choice = game.view()["choice"]
    assert (choice["title"], choice["buttons"]) == ("Confirm Drop", ["Yes", "No"])
    game.perform("game.choose", {"id": choice["id"], "index": 0})
    assert game.player_data["inventory"][0]["quantity"] == 1
    assert panel(game)["type"] == "inventory"
    assert notes(game)[-1] == "Dropped the Snack."


def test_a_drop_confirmed_after_the_item_moved_does_nothing():
    game = give(new_game(), "snack")
    do(game, "snack", "drop")
    choice_id = game.ui["choices"][0]["id"]
    game.player_data["inventory"][0] = get_item_definition("medkit")
    game.perform("game.choose", {"id": choice_id, "index": 0})
    assert [item["id"] for item in game.player_data["inventory"]] == ["medkit"]


def drink(alcoholic):
    return {"id": "drink_test", "name": "Test Drink", "description": "", "category": "Drink",
            "attributes": {"alcoholic": alcoholic, "alcohol_content": 5 if alcoholic else 0},
            "actions": ["examine", "drink", "drop"]}


def test_drinking_adds_alcohol_only_for_alcoholic_drinks():
    game = new_game()
    add_to_inventory(game.player_data, drink(False))
    do(game, "drink_test", "drink")
    assert last_message(game) == ("Drink", "You finish the Test Drink.")
    add_to_inventory(game.player_data, drink(True))
    do(game, "drink_test", "drink")
    assert last_message(game) == ("Drink", "You finish the Test Drink.\nAlcohol: 5.0%")
    assert game.player_data["alcohol_percent"] == 5
    assert game.player_data["inventory"] == []


def test_eating():
    game = give(new_game(), "snack")
    do(game, "snack", "eat")
    assert last_message(game) == ("Eat", "You eat the Snack.")
    assert game.player_data["inventory"] == []
    assert panel(game)["type"] == "inventory"


def test_a_medkit_heals_ten_percent_of_everything_hurt():
    game = give(new_game(), "medkit")
    game.player_data["limbs"]["head"] = 50
    game.player_data["damage"]["burn"] = 30
    do(game, "medkit", "use")
    assert (game.player_data["limbs"]["head"], game.player_data["damage"]["burn"]) == (60, 20)
    assert last_message(game) == ("Medkit", "You use the medkit:\n\nHead: 50% → 60%\nBurn: 30% → 20%")
    assert game.player_data["inventory"] == []


def test_a_medkit_is_kept_when_nothing_needs_healing():
    game = give(new_game(), "medkit")
    do(game, "medkit", "use")
    assert last_message(game) == ("Medkit", "You are already at full health. The medkit is not needed.")
    assert len(game.player_data["inventory"]) == 1


def open_toolkit(game):
    do(game, "basic_tools", "use")
    return panel(game)


def test_pulling_tools_out_of_the_set_and_putting_them_back():
    game = give(new_game(), "basic_tools")
    assert open_toolkit(game)["ctx"] == {"contents": ["Wrench", "Screwdriver", "Wirecutters"], "selected": None}
    game.perform("panel.select", {"index": 1})
    assert panel(game)["ctx"]["selected"] == 1
    game.perform("panel.pull_out", {})
    assert panel(game)["ctx"]["contents"] == ["Wrench", "Wirecutters"]
    assert game.player_data["inventory"][-1]["id"] == "screwdriver"
    game.perform("panel.put_back", {})
    assert panel(game)["ctx"]["tools"] == [{"index": 1, "label": "Screwdriver"}]
    game.perform("panel.confirm", {})
    assert last_message(game) == ("Put Back", "Select a tool first.")
    game.perform("panel.select", {"index": 1})
    game.perform("panel.confirm", {})
    assert panel(game)["ctx"]["contents"] == ["Wrench", "Wirecutters", "Screwdriver"]
    assert notes(game)[-2:] == ["Pulled the Screwdriver out of the Basic Tools set.",
                                "Put the Screwdriver back into the Basic Tools set."]


def test_pulling_from_an_empty_set_or_without_a_pick():
    game = give(new_game(), "basic_tools")
    open_toolkit(game)
    game.perform("panel.pull_out", {})
    assert last_message(game) == ("Basic Tools", "Select a tool to pull out.")
    for _ in range(3):
        game.perform("panel.select", {"index": 0})
        game.perform("panel.pull_out", {})
    game.perform("panel.pull_out", {})
    assert last_message(game) == ("Basic Tools", "The set is empty.")
    game.perform("panel.select", {"index": 7})
    assert panel(game)["ctx"]["selected"] is None


def test_nothing_to_put_back():
    game = give(new_game(), "basic_tools")
    open_toolkit(game)
    game.perform("panel.put_back", {})
    assert last_message(game) == ("Put Back", "No matching tools in your inventory to put back\n"
                                              "(or those slots are already filled).")


def test_putting_back_a_tool_whose_slot_was_filled_meanwhile():
    game = give(new_game(), "basic_tools", "screwdriver")
    toolkit = game.player_data["inventory"][0]
    toolkit["attributes"]["contents"].pop(1)
    open_toolkit(game)
    game.perform("panel.put_back", {})
    game.perform("panel.select", {"index": 1})
    toolkit["attributes"]["contents"].append(get_item_definition("screwdriver"))
    game.perform("panel.confirm", {})
    assert last_message(game) == ("Put Back", "That tool slot is already filled.")
    assert panel(game)["type"] == "basic_tools"


def test_putting_back_after_the_inventory_changed():
    game = give(new_game(), "basic_tools", "screwdriver")
    game.player_data["inventory"][0]["attributes"]["contents"].pop(1)
    open_toolkit(game)
    game.perform("panel.put_back", {})
    game.perform("panel.select", {"index": 1})
    game.player_data["inventory"].insert(1, get_item_definition("medkit"))
    game.perform("panel.confirm", {})
    assert last_message(game) == ("Error", "Inventory changed. Try again.")


def test_toolkit_panels_close_when_the_set_is_gone():
    game = give(new_game(), "basic_tools", "screwdriver")
    game.player_data["inventory"][0]["attributes"]["contents"].pop(1)
    open_toolkit(game)
    game.perform("panel.put_back", {})
    uid = game.player_data["inventory"].pop(0)["uid"]
    game.perform("panel.confirm", {})
    assert panel(game)["type"] == "inventory"
    game.open_panel("basic_tools", uid=uid)
    game.perform("panel.put_back", {})
    game.perform("panel.pull_out", {})
    assert game._messages == []


def test_holding_and_putting_away_equippable_items():
    game = give(new_game(), "snack", "trowel", "trowel")
    game.open_panel("hands")
    ctx = panel(game)["ctx"]
    assert ctx["item_rows"] == [{"index": 1, "label": "Trowel x 2"}]
    game.perform("panel.select", {"index": 0})
    assert panel(game)["ctx"]["selected"] is None
    game.perform("panel.select", {"index": 1})
    assert [row["can_equip"] for row in panel(game)["ctx"]["hands"]] == [True, True]
    game.perform("panel.equip", {"side": "left"})
    assert game.player_data["hands"]["left"]["name"] == "Trowel"
    assert "quantity" not in game.player_data["hands"]["left"]
    assert game.player_data["inventory"][1]["quantity"] == 1
    game.perform("panel.equip", {"side": "right"})
    assert game.player_data["hands"]["right"] is None
    game.perform("panel.select", {"index": 1})
    game.perform("panel.equip", {"side": "left"})
    assert last_message(game) == ("Hand Occupied", "Your left hand is already holding something. Unequip it first.")
    game.perform("panel.unequip", {"side": "left"})
    game.perform("panel.unequip", {"side": "left"})
    assert game.player_data["inventory"][1]["quantity"] == 2
    assert notes(game) == ["Equipped the Trowel to your left hand.", "Unequipped the Trowel from your left hand."]


def test_a_hand_that_does_not_exist_takes_nothing():
    game = give(new_game(), "trowel")
    game.open_panel("hands")
    game.perform("panel.select", {"index": 0})
    game.perform("panel.equip", {"side": "tail"})
    assert game.player_data["inventory"][0]["id"] == "trowel"


def test_equipping_from_the_item_menu():
    game = give(new_game(), "trowel")
    do(game, "trowel", "equip")
    assert panel(game)["ctx"]["title"] == "Equip: Trowel"
    game.perform("panel.choose", {"side": "right"})
    assert game.player_data["hands"]["right"]["id"] == "trowel"
    assert panel(game)["type"] == "inventory"


def test_the_equip_menu_closes_when_its_item_is_gone():
    game = give(new_game(), "trowel")
    do(game, "trowel", "equip")
    game.player_data["inventory"].clear()
    assert panel(game)["type"] == "inventory"


def test_equipping_an_item_that_is_gone():
    game = give(new_game(), "trowel")
    do(game, "trowel", "equip")
    game.player_data["inventory"].clear()
    game.perform("panel.choose", {"side": "right"})
    assert last_message(game) == ("Error", "Invalid item index for equip.")


def test_the_locker_hands_items_over_and_takes_them_back():
    game = new_game()
    game.perform("room.storage", {})
    ctx = panel(game)["ctx"]
    assert [row["label"] for row in ctx["locker"]] == ["Welcome Guide", "Station Map", "Emergency Rations",
                                                       "Basic Tools", "Medkit"]
    game.perform("panel.take", {"index": 4})
    assert panel(game)["ctx"]["inventory"] == [{"label": "Medkit"}]
    game.perform("panel.store", {"index": 0})
    assert panel(game)["ctx"]["locker"][0]["label"] == "Medkit"
    assert notes(game) == ["Took Medkit (medkit) from locker.", "Stored Medkit (medkit) in locker."]
    game.perform("panel.take", {"index": 9})
    game.perform("panel.store", {"index": 9})
    assert reports(game)[-2:] == ["Error", "Error"]


def test_quarters():
    game = new_game()
    screen = game.view()["screen"]
    assert (screen["type"], screen["name"], screen["job"], screen["credits"]) == ("quarters", "Ada", "Staff Assistant",
                                                                                1000)
    game.perform("room.bed", {})
    game.perform("game.choose", {"id": game.ui["choices"][0]["id"], "index": 0})
    assert last_message(game) == ("Game Saved", "Your game has been saved successfully.")
    game.perform("room.computer", {})
    assert panel(game)["ctx"] == {}
    game.perform("panel.stock_market", {})
    assert panel(game)["type"] == "stock_market"
    game.ui["panels"] = []
    game.perform("room.not_an_action", {})
    game.perform("room.door", {})
    assert game.player_data["location"] == {"x": 0, "y": 0}
