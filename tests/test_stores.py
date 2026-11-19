from types import SimpleNamespace

from helpers import (
    carried,
    crew,
    give,
    give_duty,
    hurt_badly,
    in_room,
    last_message,
    new_game,
    nobody_covers,
    notes,
    only_working,
)
from space_online.game.helper_methods import crew_work
from space_online.game.helper_methods.crew_work import (
    BARTENDER_WORK_SECONDS,
    CHEF_WORK_SECONDS,
    CHEMISTRY_WORK_SECONDS,
    MAX_READY,
    MINER_WORK_SECONDS,
    ORE_PER_TURN,
    tick_crew_work,
)
from space_online.game.helper_methods.stores import (
    MAX_ORE,
    MAX_PRODUCE,
    MAX_REMEDIES,
    STARTING_ORE,
    STARTING_PRODUCE,
    STARTING_REMEDIES,
    add_to_stores,
    new_stores,
    send_from_inventory,
    store_of,
    take_from_stores,
)
from space_online.game.maps.donut import (
    BAR_KEY,
    BOTANY_KEY,
    CHEMISTRY_KEY,
    ENGINEERING_KEY,
    KITCHEN_KEY,
    MEDBAY_KEY,
)
from space_online.game.objects.dishes import DISHES
from space_online.game.objects.drinks import BASIC_RECIPES


def at(game, seconds):
    game.player_data["game_clock"]["elapsed_seconds"] = seconds
    tick_crew_work(game)
    return game


def test_a_shift_starts_with_a_little_of_everything_in_the_stores():
    assert new_game().player_data["stores"] == new_stores() == {
        "ore": STARTING_ORE, "remedies": STARTING_REMEDIES,
        "produce": {"Tomato": STARTING_PRODUCE, "Potato": STARTING_PRODUCE, "Carrot": STARTING_PRODUCE,
                    "Apple": STARTING_PRODUCE}}


def test_each_store_takes_its_own_kind_of_item_and_only_so_much():
    assert [store_of(item_id) for item_id in ("gold_ore", "carrot", "antitoxin", "wheat", "sober_up", "medkit")] == [
        "ore", "produce", "remedies", None, None, None]
    player = new_game().player_data
    add_to_stores(player, "gold_ore", 2)
    add_to_stores(player, "carrot")
    add_to_stores(player, "healing_gel")
    stores = player["stores"]
    assert (stores["ore"], stores["produce"]["Carrot"], stores["remedies"]) == (
        STARTING_ORE + 2, STARTING_PRODUCE + 1, STARTING_REMEDIES + 1)
    for item_id in ("iron_ore", "apple", "burn_salve"):
        add_to_stores(player, item_id, 99)
    assert (stores["ore"], stores["produce"]["Apple"], stores["remedies"]) == (MAX_ORE, MAX_PRODUCE, MAX_REMEDIES)


def test_taking_from_a_store_needs_that_much_to_be_there():
    player = new_game().player_data
    assert not take_from_stores(player, "ore", STARTING_ORE + 1)
    assert take_from_stores(player, "ore", STARTING_ORE)
    assert (player["stores"]["ore"], take_from_stores(player, "ore")) == (0, False)
    assert take_from_stores(player, "ore", 0)


def test_sending_moves_everything_for_one_store_out_of_the_inventory():
    game = give(new_game(), "tomato", "tomato", "wheat", "iron_ore", "apple")
    assert send_from_inventory(game.player_data, "produce") == ({"Tomato": 2, "Apple": 1}, {})
    assert carried(game) == {"wheat": 1, "iron_ore": 1}
    assert game.player_data["stores"]["produce"]["Tomato"] == STARTING_PRODUCE + 2
    assert send_from_inventory(game.player_data, "remedies") == ({}, {})


def test_the_botanist_sends_produce_to_the_kitchen():
    game = in_room(BOTANY_KEY, "Civilian", "Botanist", "botany_station")
    game.perform("room.send_produce", {})
    assert last_message(game) == ("Station Stores", "You have no produce the kitchen cooks with.")
    give(game, "potato", "potato", "aloe")
    game.perform("room.send_produce", {})
    assert last_message(game) == ("Station Stores", "You send 2 Potato to the Kitchen.")
    assert (carried(game), game.player_data["stores"]["produce"]["Potato"]) == ({"aloe": 1}, STARTING_PRODUCE + 2)
    assert notes(game)[-1] == "Sent 2 Potato to the Kitchen."


def test_the_scientist_sends_remedies_to_medbay_and_visitors_cannot():
    game = give(in_room(CHEMISTRY_KEY, "Science", "Scientist", "chemistry_station"), "antitoxin", "sober_up")
    game.perform("room.send_remedies", {})
    assert last_message(game) == ("Station Stores", "You send 1 Antitoxin to MedBay.")
    assert (carried(game), game.player_data["stores"]["remedies"]) == ({"sober_up": 1}, STARTING_REMEDIES + 1)
    game.perform("room.send_remedies", {})
    assert last_message(game) == ("Station Stores", "You have no remedies MedBay treats with.")
    visitor = give(in_room(CHEMISTRY_KEY, room_mode="chemistry_station"), "antitoxin")
    visitor.perform("room.send_remedies", {})
    assert (carried(visitor), visitor._messages) == ({"antitoxin": 1}, [])


def test_a_delivery_to_the_room_a_store_belongs_to_goes_into_it():
    game = give(in_room(ENGINEERING_KEY, "Supply", "Miner", "options"), "iron_ore")
    order = give_duty(game, kind="deliver", giver="Engineer", room=ENGINEERING_KEY, item="iron_ore",
                      label="an iron ore", reward=60, summary="Bring it")
    game.perform("room.complete_duty", {"duty_id": order})
    assert game.player_data["stores"]["ore"] == STARTING_ORE + 1

    game = give(in_room(MEDBAY_KEY, "Supply", "Miner", "options"), "quartz")
    order = give_duty(game, kind="deliver", giver="Doctor", room=MEDBAY_KEY, item="quartz", label="a quartz",
                      reward=60, summary="Bring it")
    game.perform("room.complete_duty", {"duty_id": order})
    assert (game.player_data["stores"]["ore"], game.player_data["duties"]) == (STARTING_ORE, [])


def test_the_stove_cooks_with_the_produce_botany_sent_and_runs_out_of_it():
    game = in_room(KITCHEN_KEY, "Civilian", "Chef", "service_station")
    game.player_data["stores"]["produce"].update(Tomato=1, Carrot=0)
    game.perform("room.show_mixer", {})
    ctx = game.view()["panel"]["ctx"]
    assert "Tomato" in ctx["ingredients"] and ctx["counts"]["Tomato"] == 1 and ctx["counts"]["Carrot"] == 0
    game.perform("panel.category", {"name": "Botany"})
    assert game.view()["panel"]["ctx"]["ingredients"] == ["Apple", "Carrot", "Potato", "Tomato"]
    game.perform("panel.category", {"name": "All"})
    for name in ("Tomato", "Onion", "Butter", "Tomato", "Carrot"):
        game.perform("panel.select_ingredient", {"name": name})
        game.perform("panel.add_ingredient", {})
    assert game.view()["panel"]["ctx"]["glass"] == ["Tomato", "Onion", "Butter"]
    assert [message for _, message, _ in game._messages] == ["There is no more Tomato to add.",
                                                             "There is no more Carrot to add."]
    game.perform("panel.mix", {})
    assert (game.player_data["kitchen_stock"], game.player_data["stores"]["produce"]["Tomato"]) == (
        {"Tomato Soup": 1}, 0)


def test_the_npc_miner_botanist_and_scientist_keep_the_stores_topped_up():
    game = new_game()
    game.player_data["crew_work"] = {KITCHEN_KEY: 10 ** 9}
    stores = game.player_data["stores"]
    stores["produce"].update(Tomato=1, Apple=0)
    at(game, MINER_WORK_SECONDS)
    assert (stores["ore"], stores["remedies"]) == (STARTING_ORE + ORE_PER_TURN, STARTING_REMEDIES)
    at(game, CHEMISTRY_WORK_SECONDS)
    assert (stores["ore"], stores["remedies"], stores["produce"]["Apple"]) == (
        STARTING_ORE + 2 * ORE_PER_TURN, STARTING_REMEDIES + 1, 1)


def test_a_store_runs_dry_when_the_player_holds_the_post_and_does_not_fill_it():
    game = new_game("Supply", "Miner")
    at(game, 10 * MINER_WORK_SECONDS)
    assert game.player_data["stores"]["ore"] == STARTING_ORE
    crew(game := new_game(), "Miner")["in_jail"] = True
    nobody_covers(game)
    at(game, MINER_WORK_SECONDS)
    assert game.player_data["stores"]["ore"] == STARTING_ORE


def test_the_npc_chef_cooks_what_the_produce_in_the_stores_allows(monkeypatch):
    monkeypatch.setattr(crew_work, "random", SimpleNamespace(choice=lambda options: options[0]))
    game = only_working(new_game(), "Chef")
    produce = game.player_data["stores"]["produce"]
    for turn in range(1, MAX_READY + 1):
        at(game, turn * CHEF_WORK_SECONDS)
    assert game.player_data["kitchen_stock"] == {"Tomato Soup": MAX_READY}
    assert produce["Tomato"] == STARTING_PRODUCE - MAX_READY == 0
    at(game, (MAX_READY + 1) * CHEF_WORK_SECONDS)
    assert game.player_data["kitchen_stock"] == {"Tomato Soup": MAX_READY, "Mashed Potatoes": 1}
    assert "Beer-Battered Fish" not in game.player_data["kitchen_stock"]
    for name in produce:
        produce[name] = 0
    game.player_data["kitchen_stock"] = {}
    at(game, (MAX_READY + 2) * CHEF_WORK_SECONDS)
    assert game.player_data["kitchen_stock"] == {"Omelette": 1}
    full = {dish: MAX_READY for dish in DISHES}
    game.player_data["kitchen_stock"] = dict(full)
    at(game, (MAX_READY + 3) * CHEF_WORK_SECONDS)
    assert game.player_data["kitchen_stock"] == full


def test_the_npc_bartender_keeps_a_few_of_the_basic_drinks_ready(monkeypatch):
    monkeypatch.setattr(crew_work, "random", SimpleNamespace(choice=lambda options: options[0]))
    game = only_working(new_game(), "Bartender")
    for turn in range(1, MAX_READY + 2):
        at(game, turn * BARTENDER_WORK_SECONDS)
    assert game.player_data["bar_mixed_stock"] == {BASIC_RECIPES[0]: MAX_READY, BASIC_RECIPES[1]: 1}
    game.player_data["bar_mixed_stock"] = {drink: MAX_READY for drink in BASIC_RECIPES}
    at(game, (MAX_READY + 2) * BARTENDER_WORK_SECONDS)
    assert set(game.player_data["bar_mixed_stock"].values()) == {MAX_READY}


def test_the_npc_doctor_needs_a_remedy_to_treat_anyone():
    game = only_working(new_game(), "Doctor")
    chef = hurt_badly(crew(game, "Chef"))
    game.player_data["stores"]["remedies"] = 0
    at(game, crew_work.DOCTOR_WORK_SECONDS)
    assert chef["limbs"]["head"] == 10 and game._messages == []
    game.player_data["stores"]["remedies"] = 1
    at(game, 2 * crew_work.DOCTOR_WORK_SECONDS)
    assert (chef["limbs"]["head"], game.player_data["stores"]["remedies"]) == (100, 0)


def test_station_status_lists_the_stores():
    game = new_game("Administration", "Captain")
    game.open_panel("station_status")
    assert game.view()["panel"]["ctx"]["facilities"]["stores"] == game.player_data["stores"]


def test_sending_produce_keeps_back_what_a_crop_request_asks_for():
    game = in_room(BOTANY_KEY, "Civilian", "Botanist", "botany_station")
    give(game, "potato", "potato", "potato", "tomato")
    give_duty(game, kind="deliver", giver="Bartender", room=BAR_KEY, item="potato", label="a potato", reward=50,
              summary="Bring a potato")
    game.perform("room.send_produce", {})
    assert carried(game) == {"potato": 1}
    assert last_message(game) == ("Station Stores", "You send 2 Potato, 1 Tomato to the Kitchen. Kept back: 1 Potato.")
    assert notes(game)[-1] == "Sent 2 Potato, 1 Tomato to the Kitchen. Kept back: 1 Potato."
    game.perform("room.send_produce", {})
    assert last_message(game) == ("Station Stores",
                                  "You have no produce the kitchen cooks with. Kept back: 1 Potato.")
    assert carried(game) == {"potato": 1}
