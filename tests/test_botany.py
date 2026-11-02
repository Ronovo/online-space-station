import time

import pytest

from helpers import new_game, reports
from space_online.game.maps.donut import BOTANY_KEY, location_from_key
from space_online.game.objects.botany_items import (
    BOTANIST_STAND_PRICES,
    BOTANY_VEND_CATALOG,
    GROWTH_CLASS_SECONDS,
    GROWTH_STAGES,
    MIN_STAGE_SECONDS,
    MIRACLE_GROW_SPEED_BONUS,
    PLENTIFUL_HARVEST_YIELD_MULTIPLIER,
    VEND_RESTOCK_SECONDS,
    compute_growth_stage,
    effective_stage_seconds,
    empty_planter,
    growth_seconds_to_next_stage,
    growth_stage_label,
    new_botany,
    refresh_planter_growth,
    restock_vending,
)
from space_online.game.objects.items import get_item_definition
from space_online.game.special_rooms.botany import announce_planter_changes, clear_planter

CROP = GROWTH_CLASS_SECONDS["crop"]


def in_botany(department="Civilian", job="Staff Assistant"):
    game = new_game(department, job)
    game.player_data["location"] = location_from_key(BOTANY_KEY)
    return game


def buttons(game):
    return [(w.get("label") or w.get("text"), w.get("action")) for w in game.view()["screen"]["buttons"]]


def panel(game):
    return game.view()["panel"]


def last_message(game):
    return game._messages[-1][1:3]


def notes(game):
    return [note["text"] for note in game.player_data["notes"]]


def planted(growth_class="crop", **values):
    return {**empty_planter(), "occupied": True, "plant": "Potato", "seed_id": "potato_seeds", "produces": "potato",
            "growth_class": growth_class, "planted_at_seconds": 0, "growth_stage": 1, **values}


def clock(game, seconds):
    game.player_data["game_clock"]["elapsed_seconds"] = seconds


def row(game, allow_harvest=True, number=0):
    game.ui["panels"] = []
    game.open_panel("planter_row", row=number, allow_harvest=allow_harvest)


def hold(game, item_id, side="left"):
    game.player_data["hands"][side] = get_item_definition(item_id)


def use(game, index=0, side="left"):
    game.perform("panel.use_hand", {"index": index, "side": side})


def planter(game, index=0):
    return game.player_data["botany"]["planters"][index]


def test_stages_advance_with_the_clock_and_stop_at_mature():
    assert compute_growth_stage(None, "crop", 999) == 1
    assert [compute_growth_stage(0, "crop", t) for t in (0, CROP - 1, CROP, 10 * CROP)] == [1, 1, 2, GROWTH_STAGES]
    assert compute_growth_stage(0, "mystery", CROP) == 2


def test_miracle_grow_shortens_stages_but_never_below_the_floor():
    assert effective_stage_seconds("crop", MIRACLE_GROW_SPEED_BONUS) == CROP * (1 - MIRACLE_GROW_SPEED_BONUS)
    assert effective_stage_seconds("crop", 0.99) == MIN_STAGE_SECONDS


def test_time_to_the_next_stage():
    assert growth_seconds_to_next_stage(None, "crop", 50) == 0
    assert growth_seconds_to_next_stage(0, "crop", 50) == CROP - 50
    assert growth_seconds_to_next_stage(0, "crop", 10 * CROP) == 0


def test_stage_labels():
    assert [growth_stage_label(stage) for stage in (1, 5, 9)] == ["Seedling", "Mature", "Growing"]


def test_a_watered_plant_grows_one_stage_and_needs_water_again():
    plant = planted(watered=True)
    assert refresh_planter_growth(plant, CROP) == 2
    assert (plant["watered"], plant["dead"]) == (False, False)


def test_an_unwatered_plant_dies_when_its_stage_is_due():
    plant = planted()
    assert refresh_planter_growth(plant, CROP) == 1
    assert plant["dead"]
    assert refresh_planter_growth(plant, 10 * CROP) == 1


def test_one_watering_only_carries_one_stage():
    plant = planted(watered=True)
    assert refresh_planter_growth(plant, 2 * CROP) == 2
    assert plant["dead"]


def test_the_last_watering_carries_a_plant_to_mature():
    plant = planted(watered=True, growth_stage=GROWTH_STAGES - 1)
    assert refresh_planter_growth(plant, 10 * CROP) == GROWTH_STAGES
    assert (plant["dead"], plant["watered"]) == (False, True)


def test_empty_and_unplanted_planters_do_not_grow():
    assert refresh_planter_growth(empty_planter(), 999) == 0
    assert refresh_planter_growth(planted(planted_at_seconds=None, growth_stage=3), 999) == 3


def test_visitors_can_look_at_the_plants_but_not_tend_them():
    game = in_botany()
    assert buttons(game) == [("View Plants", "room.view_plants"), ("Talk to Botanist", "room.talk_to_botanist")]
    game.perform("room.view_plants", {})
    assert list(panel(game)["ctx"]["rows"]) == [0, 1, 2, 3]
    game.perform("panel.choose_row", {"row": 9})
    game.perform("panel.choose_row", {"row": 1})
    ctx = panel(game)["ctx"]
    assert (ctx["title"], ctx["hand_buttons"]) == ("Viewing Plants - Row 2", [])
    assert [card["title"] for card in ctx["cards"]] == [f"Planter {n}: Empty" for n in range(5, 9)]
    hold(game, "potato_seeds")
    use(game, index=4)
    planter(game, 4).update(planted(growth_stage=GROWTH_STAGES))
    game.perform("panel.harvest", {"index": 4})
    assert planter(game, 4)["growth_stage"] == GROWTH_STAGES and game.player_data["inventory"] == []
    game.perform("panel.back", {})
    assert panel(game)["type"] == "planter_rows"


def test_the_botanist_works_the_station():
    game = in_botany("Civilian", "Botanist")
    assert [label for label, _ in buttons(game)] == ["Enter Botany Station", "Lock/Unlock Door", "Room Options"]
    game.perform("room.open_station", {"mode": "botany_station"})
    assert buttons(game) == [("Botany Station Controls", None), ("Botany Vending Machine", "room.access_botany_vending"),
                             ("View Plants", "room.view_plants_station"), ("Back to Station Menu", "room.set_mode")]
    game.perform("room.view_plants_station", {})
    game.perform("panel.choose_row", {"row": 0})
    hold(game, "watering_can")
    assert [b["label"] for b in panel(game)["ctx"]["hand_buttons"]] == ["Use Watering Can", "Use Right Hand"]
    game.perform("panel.hands", {})
    assert panel(game)["type"] == "hands"


def test_visitors_get_no_station():
    game = in_botany()
    game.ui["room_mode"] = "botany_station"
    game.perform("room.access_botany_vending", {})
    assert game.ui["panels"] == []
    assert buttons(game)[0] == ("View Plants", "room.view_plants")


def test_planting_watering_and_harvesting():
    game = in_botany("Civilian", "Botanist")
    row(game)
    hold(game, "potato_seeds")
    use(game)
    card = panel(game)["ctx"]["cards"][0]
    assert (card["title"], card["stage"], card["stage_color"]) == ("Planter 1: Potato", "Stage: Seedling (1/5) - needs water",
                                                                   "orange")
    assert card["time"] == "Next stage in 3m 0s"
    assert game.player_data["hands"]["left"] is None
    hold(game, "watering_can", side="right")
    use(game, side="right")
    assert panel(game)["ctx"]["cards"][0]["stage"] == "Stage: Seedling (1/5)"
    game.perform("panel.harvest", {"index": 0})
    assert last_message(game) == ("Not Ready", "Planter 1 is not ready to harvest yet.")
    planter(game).update(growth_stage=GROWTH_STAGES)
    clock(game, 10 * CROP)
    card = panel(game)["ctx"]["cards"][0]
    assert (card["time"], card["can_harvest"]) == ("Ready to harvest", True)
    game.perform("panel.harvest", {"index": 0})
    assert game.player_data["inventory"][0]["id"] == "potato"
    assert planter(game) == empty_planter()
    assert notes(game) == ["Planted Potato Seeds in planter 1 using your left hand.", "Watered planter 1.",
                           "Harvested 1x Potato from planter 1."]


def test_a_mature_plant_cannot_be_harvested_from_the_visitor_view():
    game = in_botany("Civilian", "Botanist")
    planter(game).update(planted(growth_stage=GROWTH_STAGES))
    clock(game, 10 * CROP)
    row(game, allow_harvest=False)
    assert panel(game)["ctx"]["cards"][0]["can_harvest"] is False


def test_harvesting_empty_dead_or_other_rows_does_nothing():
    game = in_botany("Civilian", "Botanist")
    planter(game, 1).update(planted(dead=True))
    row(game)
    for index in (0, 1, 7):
        game.perform("panel.harvest", {"index": index})
    assert game._messages == [] and game.player_data["inventory"] == []


def test_buffs_show_on_the_card_and_plentiful_harvest_triples_the_crop():
    game = in_botany("Civilian", "Botanist")
    planter(game).update(planted(watered=True))
    row(game)
    for item_id in ("miracle_grow", "plentiful_harvest", "the_ooze_mutagen"):
        hold(game, item_id)
        use(game)
        assert game.player_data["hands"]["left"] is None
    assert last_message(game) == ("Mutation", "The Plant does not mutate.")
    assert panel(game)["ctx"]["cards"][0]["buffs"] == [("Miracle Grow", "#90EE90"), ("Plentiful Harvest", "#FFD700"),
                                                       ("The Ooze", "#7CFC00")]
    assert planter(game)["miracle_grow"] == MIRACLE_GROW_SPEED_BONUS
    planter(game)["growth_stage"] = GROWTH_STAGES
    clock(game, 10 * CROP)
    game.perform("panel.harvest", {"index": 0})
    assert game.player_data["inventory"][0]["quantity"] == PLENTIFUL_HARVEST_YIELD_MULTIPLIER


def test_a_dead_plant_takes_no_water_and_shows_it_must_be_cleared():
    game = in_botany("Civilian", "Botanist")
    planter(game).update(planted(dead=True))
    row(game)
    card = panel(game)["ctx"]["cards"][0]
    assert (card["stage"], card["time"]) == ("Status: Dead", "Needs to be cleared with a Trowel or Chainsaw.")
    for item_id in ("watering_can", "miracle_grow"):
        hold(game, item_id)
        use(game)
        assert last_message(game) == ("Plant Dead", "This plant has died. It needs to be cleared with a Trowel or Chainsaw.")
    assert game.player_data["hands"]["left"]["id"] == "miracle_grow"


@pytest.mark.parametrize("tool, growth_class, hint", [
    ("trowel", "tree", "Use a Chainsaw on trees."),
    ("chainsaw", "crop", "Use a Trowel on non-tree plants."),
])
def test_each_tool_clears_its_own_kind_of_plant(tool, growth_class, hint):
    game = in_botany("Civilian", "Botanist")
    planter(game).update(planted(growth_class))
    row(game)
    hold(game, tool)
    use(game)
    name = get_item_definition(tool)["name"]
    assert last_message(game) == ("Wrong Tool", f"The {name} can't clear this plant. {hint}")


@pytest.mark.parametrize("tool, growth_class", [("trowel", "crop"), ("chainsaw", "tree")])
def test_clearing_a_planter_asks_first(tool, growth_class):
    game = in_botany("Civilian", "Botanist")
    planter(game).update(planted(growth_class, dead=True))
    row(game)
    hold(game, tool)
    use(game)
    choice = game.view()["choice"]
    assert choice["title"] == "Clear Planter"
    game.perform("game.choose", {"id": choice["id"], "index": 0})
    assert planter(game) == empty_planter()
    assert game.player_data["hands"]["left"]["id"] == tool


def test_a_clear_for_a_planter_that_is_gone_does_nothing():
    game = in_botany()
    clear_planter(game, 99, "Trowel")
    assert game.player_data["notes"] == []


def test_using_hands_on_planters_that_cannot_take_them():
    game = in_botany("Civilian", "Botanist")
    planter(game, 1).update(planted())
    row(game)
    use(game, side="left")
    assert last_message(game) == ("Empty Hand", "Your left hand is empty.")
    hold(game, "watering_can")
    use(game)
    assert last_message(game) == ("Nothing Planted", "There is nothing planted in this planter.")
    hold(game, "potato_seeds")
    use(game, index=1)
    assert last_message(game) == ("Planter Occupied",
                                  "Planter 2 already has a plant in it. Choose an empty planter.")
    game.player_data["hands"]["left"] = {"id": "pebble", "name": "Pebble"}
    use(game, index=1)
    assert last_message(game) == ("Cannot Use", "The Pebble can't be used on planters.")
    count = len(game._messages)
    use(game, index=9)
    use(game, side="tail")
    assert len(game._messages) == count


def test_the_visitor_view_ignores_hands():
    game = in_botany("Civilian", "Botanist")
    row(game, allow_harvest=False)
    hold(game, "potato_seeds")
    use(game)
    assert not planter(game)["occupied"]


def vending(game):
    game.ui["room_mode"] = "botany_station"
    game.perform("room.access_botany_vending", {})


def vended(game, item_id):
    return next(item for item in panel(game)["ctx"]["available"] if item["id"] == item_id)


def test_the_vending_machine_lists_and_filters_what_it_sells():
    game = in_botany("Civilian", "Botanist")
    vending(game)
    ctx = panel(game)["ctx"]
    assert (ctx["filter"], len(ctx["available"]), ctx["owned"], ctx["credits"]) == ("all", 12, [], 3000)
    assert vended(game, "trowel") == {"id": "trowel", "name": "Trowel", "price": 30, "stock": 3}
    game.perform("panel.filter", {"kind": "tool"})
    assert [item["name"] for item in panel(game)["ctx"]["available"]] == ["Watering Can", "Trowel", "Chainsaw"]
    game.perform("panel.filter", {"kind": "weapons"})
    assert panel(game)["ctx"]["filter"] == "tool"


def test_buying_from_the_vending_machine_costs_credits_and_stock():
    game = in_botany("Civilian", "Botanist")
    vending(game)
    for item_id in ("trowel", "trowel", "medkit"):
        game.perform("panel.buy", {"item_id": item_id})
    assert panel(game)["ctx"]["owned"] == ["Trowel x 2"]
    assert (game.player_data["credits"], vended(game, "trowel")["stock"]) == (2940, 1)
    assert notes(game) == ["Bought Trowel from the botany vending machine for 30 credits."] * 2


def test_an_empty_slot_says_when_it_restocks():
    game = in_botany("Civilian", "Botanist")
    vending(game)
    for _ in range(4):
        game.perform("panel.buy", {"item_id": "chainsaw"})
    assert last_message(game) == ("Out of Stock", "The machine is out of Chainsaw. It restocks one every 5 minutes.")
    assert (game.player_data["credits"], vended(game, "chainsaw")["stock"]) == (2700, 0)
    clock(game, VEND_RESTOCK_SECONDS)
    assert vended(game, "chainsaw")["stock"] == 1


def test_the_vending_machine_needs_the_credits():
    game = in_botany("Civilian", "Botanist")
    vending(game)
    game.player_data["credits"] = 100
    game.perform("panel.buy", {"item_id": "chainsaw"})
    assert last_message(game) == ("Insufficient Credits", "You don't have enough credits to buy Chainsaw.")
    assert (game.player_data["credits"], vended(game, "chainsaw")["stock"], game.player_data["inventory"]) == (100, 2, [])


def test_restocking_adds_one_of_each_per_interval_up_to_the_most_it_holds():
    botany = new_botany()
    botany["vending_stock"].update(trowel=0, chainsaw=0, tomato_seeds=9)
    assert restock_vending(botany, VEND_RESTOCK_SECONDS - 1)["trowel"] == 0
    stock = restock_vending(botany, 2 * VEND_RESTOCK_SECONDS + 10)
    assert (stock["trowel"], stock["chainsaw"], stock["tomato_seeds"]) == (2, 2, 10)
    assert botany["vending_restocked_at_seconds"] == 2 * VEND_RESTOCK_SECONDS
    assert restock_vending(botany, 3 * VEND_RESTOCK_SECONDS - 1)["trowel"] == 2
    assert restock_vending(botany, 3 * VEND_RESTOCK_SECONDS)["trowel"] == BOTANY_VEND_CATALOG["trowel"][1]


def test_every_seed_grows_a_real_item_and_every_vended_item_exists():
    for item_id in BOTANY_VEND_CATALOG:
        item = get_item_definition(item_id)
        produces = item["attributes"].get("produces")
        assert produces is None or get_item_definition(produces) is not None
    assert get_item_definition("aloe_seeds")["attributes"]["produces"] == "aloe"


def test_miracle_grow_speeds_up_only_the_time_still_to_come():
    game = in_botany("Civilian", "Botanist")
    planter(game).update(planted(growth_stage=2))
    clock(game, 2 * CROP - 10)
    row(game)
    hold(game, "miracle_grow")
    use(game)
    card = panel(game)["ctx"]["cards"][0]
    assert planter(game)["dead"] is False
    assert (card["stage"], card["time"]) == ("Stage: Sprouting (2/5) - needs water", "Next stage in 9s")


def test_supplies_that_would_do_nothing_stay_in_your_hand():
    game = in_botany("Civilian", "Botanist")
    planter(game).update(planted(watered=True))
    planter(game, 1).update(planted(growth_stage=GROWTH_STAGES, planted_at_seconds=-10 * CROP))
    row(game)
    for item_id, index, message in [
        ("watering_can", 0, ("No Water Needed", "This plant doesn't need water right now.")),
        ("watering_can", 1, ("No Water Needed", "This plant doesn't need water right now.")),
        ("miracle_grow", 1, ("Fully Grown", "This plant is already fully grown.")),
    ]:
        hold(game, item_id)
        use(game, index=index)
        assert last_message(game) == message
        assert game.player_data["hands"]["left"]["id"] == item_id
    for item_id, name in (("miracle_grow", "Miracle Grow"), ("plentiful_harvest", "Plentiful Harvest")):
        hold(game, item_id)
        use(game)
        assert game.player_data["hands"]["left"] is None
        hold(game, item_id)
        use(game)
        assert last_message(game) == ("Already Applied", f"This plant already has {name}.")
        assert game.player_data["hands"]["left"]["id"] == item_id


def test_a_plant_whose_stage_came_due_unwatered_cannot_be_saved_by_watering_late():
    game = in_botany("Civilian", "Botanist")
    planter(game).update(planted())
    clock(game, CROP)
    row(game)
    hold(game, "watering_can")
    use(game)
    assert last_message(game) == ("Plant Dead", "This plant has died. It needs to be cleared with a Trowel or Chainsaw.")
    assert planter(game)["watered"] is False


def test_deaths_are_reported_and_ripe_plants_noted_once_each():
    game = in_botany("Civilian", "Botanist")
    planter(game, 0).update(planted())
    planter(game, 1).update(planted(watered=True, growth_stage=GROWTH_STAGES - 1))
    planter(game, 2).update(planted())
    planter(game, 3).update(planted(planted_at_seconds=10 * CROP - 1))
    clock(game, 10 * CROP)
    refresh_planter_growth(planter(game, 2), 10 * CROP)
    announce_planter_changes(game)
    announce_planter_changes(game)
    assert [message[1:] for message in game._messages] == [
        ("Plant Died", "The Potato in planter 1 died for lack of water.", "warning"),
        ("Plant Died", "The Potato in planter 3 died for lack of water.", "warning"),
    ]
    assert notes(game) == ["The Potato in planter 1 died for lack of water.", "The Potato in planter 2 is ready to harvest.",
                           "The Potato in planter 3 died for lack of water."]


def test_the_master_clock_announces_planter_changes():
    game = in_botany("Civilian", "Botanist")
    planter(game).update(planted())
    game.player_data["game_clock"].update(elapsed_seconds=CROP, last_real_time=time.time() - 2)
    game.tick()
    assert "Plant Died" in reports(game)


def test_the_botanist_sells_produce():
    game = in_botany()
    credits = game.player_data["credits"]
    game.perform("room.talk_to_botanist", {})
    ctx = panel(game)["ctx"]
    assert ctx["credits"] == credits
    assert [(item["name"], item["price"]) for item in ctx["produce"]] == [
        ("Potato", 15), ("Wheat", 15), ("Carrot", 15), ("Tomato", 20), ("Apple", 30), ("Aloe", 40)]
    for item_id in ("tomato", "medkit"):
        game.perform("panel.buy", {"item_id": item_id})
    assert game.player_data["credits"] == credits - BOTANIST_STAND_PRICES["tomato"]
    assert [item["id"] for item in game.player_data["inventory"]] == ["tomato"]
    assert notes(game) == ["Bought Tomato from the Botanist for 20 credits."]
    game.player_data["credits"] = 5
    game.perform("panel.buy", {"item_id": "aloe"})
    assert last_message(game) == ("Insufficient Credits", "You don't have enough credits to buy Aloe.")


def test_an_absent_botanist_sells_nothing():
    game = in_botany()
    botanist = next(npc for npc in game.station_crew if npc["job"] == "Botanist")
    botanist["on_duty"] = False
    assert ("Talk to Botanist", "room.talk_to_botanist") not in buttons(game)
    game.perform("room.talk_to_botanist", {})
    assert game.ui["panels"] == []
