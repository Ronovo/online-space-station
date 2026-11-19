from helpers import (
    at,
    buttons,
    carried,
    crew,
    duty,
    fix_random,
    give,
    hold,
    in_room,
    job_event,
    labels,
    last_message,
    new_game,
    notes,
)
from space_online.game.helper_methods.artifacts import is_unknown_artifact
from space_online.game.maps.donut import ENGINEERING_KEY, MINING_KEY, QUARTERS_LOCATION
from space_online.game.objects.items import ALL_ITEMS
from space_online.game.objects.mining_items import (
    MAGNET_MAX_ROCKS,
    MAGNET_SECONDS_PER_ROCK,
    ORBIT_SECONDS,
    ORE_VALUES,
    PLANETS,
    planet_index,
)
from space_online.game.helper_methods import combat
from space_online.game.helper_methods.combat import DEFEAT_HEALTH
from space_online.game.helper_methods.rounds import round_over
from space_online.game.special_rooms import mining
from space_online.game.special_rooms.mining import (
    ARTIFACT_CHANCE,
    HOLD_CAPACITY,
    MONSTER_CHANCE,
    ORE_CHANCE,
    SEARCH_SECONDS_RANGE,
)


def in_mining(department="Supply", job="Miner"):
    return in_room(MINING_KEY, department, job, room_mode="locker_room")


def rolls(monkeypatch, **fixed):
    fix_random(monkeypatch, mining, combat, **fixed)


def on_planet(monkeypatch, **hands):
    game = hold(give(in_mining(), "pickaxe"), **hands)
    game.perform("room.board_shuttle", {})
    rolls(monkeypatch)
    return game


def fighting(monkeypatch, **hands):
    game = on_planet(monkeypatch, **hands)
    game.perform("room.search", {})
    return game


def expedition(game):
    return game.player_data["mining"]["expedition"]


def test_the_mining_bay_is_off_the_northeast_hallway():
    game = new_game("Supply", "Miner")
    game.player_data["location"] = {"x": 5, "y": 2}
    assert game.view()["screen"]["grid"][0][1] == {"label": "Mining Bay", "action": "game.enter_room",
                                                   "args": {"room_key": MINING_KEY}}
    game.perform("game.enter_room", {"room_key": MINING_KEY})
    assert buttons(game)[0] == ("Enter Miner Station", "room.open_station")


def test_the_miner_station_is_the_locker_room():
    game = in_mining()
    assert labels(game) == ["Locker Room", f"The station is passing over {PLANETS[0]['name']}.", "Take Mining Gear",
                            "Magnet: OFF", "Mine Rocks (0 waiting)", f"Board the Shuttle to {PLANETS[0]['name']}",
                            "Ore sells at the Cargo Bay's export counter.", "Back to Station Menu"]


def test_the_station_passes_over_each_planet_in_turn():
    assert [planet_index(turn * ORBIT_SECONDS) for turn in range(len(PLANETS) + 1)] == [0, 1, 2, 3, 0]
    game = at(in_mining(), ORBIT_SECONDS)
    assert f"Board the Shuttle to {PLANETS[1]['name']}" in labels(game)


def test_taking_mining_gear_from_the_lockers():
    game = in_mining()
    game.perform("room.take_gear", {})
    assert carried(game) == {"pickaxe": 1, "blast_shield": 1}
    assert last_message(game) == ("Lockers", "You take the Pickaxe and Blast Shield from the mining lockers. "
                                             "Equip them from Hands to use them.")
    game.perform("room.take_gear", {})
    assert last_message(game) == ("Lockers", "You already have your mining gear.")
    hold(game, left="pickaxe").player_data["inventory"] = []
    game.perform("room.take_gear", {})
    assert carried(game) == {"blast_shield": 1}


def test_the_magnet_pulls_in_rocks_while_it_is_on():
    game = in_mining()
    game.perform("room.toggle_magnet", {})
    assert "Magnet: ON" in labels(game)
    at(game, 3 * MAGNET_SECONDS_PER_ROCK + 5)
    assert "Mine Rocks (3 waiting)" in labels(game)
    game.perform("room.toggle_magnet", {})
    at(game, 100 * MAGNET_SECONDS_PER_ROCK)
    assert labels(game)[3:5] == ["Magnet: OFF", "Mine Rocks (3 waiting)"]
    game.perform("room.toggle_magnet", {})
    at(game, 1000 * MAGNET_SECONDS_PER_ROCK)
    assert f"Mine Rocks ({MAGNET_MAX_ROCKS} waiting)" in labels(game)


def test_mining_the_magnets_rocks(monkeypatch):
    game = in_mining()
    game.perform("room.mine_rocks", {})
    assert last_message(game) == ("Magnet", "There are no rocks to mine yet. The magnet brings them in while it is on.")
    game.perform("room.toggle_magnet", {})
    at(game, 2 * MAGNET_SECONDS_PER_ROCK)
    game.perform("room.mine_rocks", {})
    assert last_message(game) == ("No Pickaxe", "You need a pickaxe. Take your mining gear from the lockers.")
    give(game, "pickaxe")
    picks = iter(["iron_ore", "quartz"])
    rolls(monkeypatch, pick=lambda options: next(picks))
    game.perform("room.mine_rocks", {})
    assert carried(game) == {"pickaxe": 1, "iron_ore": 1, "quartz": 1}
    assert last_message(game) == ("Mining", "You break up 2 rocks and get 1 Iron Ore, 1 Quartz.")
    assert "Mine Rocks (0 waiting)" in labels(game)
    at(game, 3 * MAGNET_SECONDS_PER_ROCK)
    assert "Mine Rocks (1 waiting)" in labels(game)


def test_rocks_pulled_in_before_the_magnet_was_switched_off_can_still_be_mined(monkeypatch):
    game = give(in_mining(), "pickaxe")
    game.player_data["mining"]["rocks"] = 2
    rolls(monkeypatch)
    game.perform("room.mine_rocks", {})
    assert carried(game) == {"pickaxe": 1, "iron_ore": 2}
    assert game.player_data["mining"] == {"magnet_since": None, "rocks": 0, "expedition": None, "identified": []}


def test_every_ore_is_an_item_with_a_price():
    ores = {item_id for item_id, item in ALL_ITEMS.items() if item["category"] == "Ore"}
    assert ores == set(ORE_VALUES)
    for planet in PLANETS:
        assert set(planet["ores"]) <= ores


def test_other_crew_buy_ore_from_the_miner():
    game = in_mining("Civilian", "Staff Assistant")
    assert buttons(game) == [("Buy Ore", "room.buy_ore")]
    for action in ("take_gear", "toggle_magnet", "mine_rocks", "sell_ore", "board_shuttle"):
        game.perform(f"room.{action}", {})
    assert (game._messages, game.player_data["mining"]["magnet_since"]) == ([], None)
    game.perform("room.buy_ore", {})
    panel = game.view()["panel"]
    assert (panel["type"], panel["template"], panel["ctx"]["title"]) == ("ore_counter", "stand", "Ore Counter")
    game.perform("panel.buy", {"item_id": "iron_ore"})
    assert (carried(game), game.player_data["credits"]) == ({"iron_ore": 1}, 980)


def test_the_ore_counter_is_shut_while_the_miner_is_away():
    game = in_mining("Civilian", "Staff Assistant")
    crew(game, "Miner").update(on_duty=False, location={"x": 2, "y": 5})
    game.perform("room.buy_ore", {})
    assert game.ui["panels"] == []


def test_the_shuttle_needs_a_pickaxe_and_a_miner_fit_to_fly():
    game = in_mining()
    game.perform("room.board_shuttle", {})
    assert last_message(game)[0] == "No Pickaxe"
    give(game, "pickaxe")
    game.player_data["limbs"] = {limb: DEFEAT_HEALTH - 1 for limb in game.player_data["limbs"]}
    game.perform("room.board_shuttle", {})
    assert last_message(game) == ("Shuttle", "You are in no shape for the surface. Get treated in MedBay first.")
    assert expedition(game) is None


def test_the_shuttle_lands_on_the_planet_below():
    game = at(give(in_mining(), "pickaxe"), ORBIT_SECONDS)
    game.perform("room.board_shuttle", {})
    planet = PLANETS[1]
    screen = game.view()["screen"]
    assert (screen["title"], screen["heading"], screen["description"]) == (
        planet["name"], f"Surface of {planet['name']}", planet["desc"])
    assert buttons(game) == [(f"The shuttle sets down on {planet['name']}.", None),
                             ("In the shuttle's hold: nothing yet.", None),
                             ("Search for Rocks", "room.search"),
                             ("Return to the Station", "room.return_to_station")]
    at(game, 3 * ORBIT_SECONDS)
    assert game.view()["screen"]["title"] == planet["name"]


def test_there_is_no_walking_off_the_planet(monkeypatch):
    game = on_planet(monkeypatch)
    game.perform("room.exit", {})
    assert last_message(game) == ("On the Surface", "The shuttle is the only way back to the station.")
    for action in ("set_mode", "take_gear"):
        game.perform(f"room.{action}", {"mode": "menu"} if action == "set_mode" else {})
    assert (game.ui["room_mode"], expedition(game) is not None) == ("locker_room", True)


def test_the_surface_actions_do_nothing_aboard_the_station():
    game = give(in_mining(), "pickaxe")
    for action in ("search", "return_to_station"):
        game.perform(f"room.{action}", {})
    assert (game._messages, expedition(game)) == ([], None)


def test_searching_finds_ore_or_nothing(monkeypatch):
    game = on_planet(monkeypatch)
    rolls(monkeypatch, roll=MONSTER_CHANCE)
    game.perform("room.search", {})
    assert expedition(game)["haul"] == {"titanium_ore": 1}
    assert labels(game)[:2] == ["You find a vein of ore you don't recognise and dig some out.",
                                "In the shuttle's hold: 1 unidentified ore."]
    rolls(monkeypatch, roll=MONSTER_CHANCE + ORE_CHANCE + ARTIFACT_CHANCE)
    game.perform("room.search", {})
    assert labels(game)[0] == "You search the rocks and find nothing worth taking."
    assert expedition(game)["haul"] == {"titanium_ore": 1}


def test_a_miner_identifies_a_vein_with_the_pda_in_hand_and_knows_that_ore_from_then_on(monkeypatch):
    game = on_planet(monkeypatch, left="pda")
    rolls(monkeypatch, roll=MONSTER_CHANCE, pick=lambda options: options[-1])
    game.perform("room.search", {})
    rolls(monkeypatch, roll=MONSTER_CHANCE)
    game.perform("room.search", {})
    assert labels(game)[:3] == ["You find a vein of ore you don't recognise and dig some out.",
                                "In the shuttle's hold: 2 unidentified ore.", "Scan the Vein"]
    game.perform("room.scan_vein", {})
    assert last_message(game) == ("PDA Scan: Vein", "Titanium Ore. Exports for 45 credits. "
                                                    "Found on Kessar IV, Glacia.")
    assert game.player_data["mining"]["identified"] == ["titanium_ore"]
    assert labels(game)[:3] == ["Your PDA identifies the vein: Titanium Ore.",
                                "In the shuttle's hold: 1 Titanium Ore, 1 unidentified ore.", "Search for Rocks"]
    game.perform("room.search", {})
    assert labels(game)[:3] == ["You find a vein of Titanium Ore and dig some out.",
                                "In the shuttle's hold: 2 Titanium Ore, 1 unidentified ore.", "Search for Rocks"]


def test_a_vein_is_only_scanned_by_a_miner_holding_the_pda_and_only_until_the_next_search(monkeypatch):
    game = on_planet(monkeypatch)
    rolls(monkeypatch, roll=MONSTER_CHANCE)
    game.perform("room.search", {})
    game.perform("room.scan_vein", {})
    assert ("Scan the Vein" in labels(game), game.player_data["mining"]["identified"]) == (False, [])

    hold(game, left="pda")
    game.player_data["job"] = "Captain"
    assert "Scan the Vein" not in labels(game)
    game.player_data["job"] = "Miner"
    assert "Scan the Vein" in labels(game)

    rolls(monkeypatch, roll=MONSTER_CHANCE + ORE_CHANCE + ARTIFACT_CHANCE)
    game.perform("room.search", {})
    game.perform("room.scan_vein", {})
    assert ("Scan the Vein" in labels(game), game.player_data["mining"]["identified"]) == (False, [])


def test_the_ore_log_names_only_the_ores_identified_this_shift():
    game = in_mining()
    game.open_panel("ore_log")
    assert game.view()["panel"]["ctx"] == {"ores": [None] * 5, "found": 0, "total": 5}
    game.player_data["mining"]["identified"] = ["gold_ore"]
    assert game.view()["panel"]["ctx"] == {
        "ores": [None, {"name": "Gold Ore", "value": 60, "planets": "Kessar IV, Pyros, Verdis"}, None, None, None],
        "found": 1, "total": 5}


def test_now_and_then_a_search_turns_up_an_alien_artifact_which_comes_home_with_the_ore(monkeypatch):
    game = on_planet(monkeypatch)
    rolls(monkeypatch, roll=MONSTER_CHANCE)
    game.perform("room.search", {})
    rolls(monkeypatch, roll=MONSTER_CHANCE + ORE_CHANCE)
    game.perform("room.search", {})
    assert labels(game)[:2] == ["Half buried in the rock is something nobody mined: an alien artifact. "
                                "The Research Lab will want it.",
                                "In the shuttle's hold: 1 unidentified ore, 1 Alien Artifact."]
    game.perform("room.search", {})
    game.perform("room.return_to_station", {})
    assert last_message(game) == ("Back Aboard", "The shuttle docks. You unload 1 Titanium Ore, 2 Alien Artifact.")
    artifacts = [item for item in game.player_data["inventory"] if is_unknown_artifact(item)]
    assert len(artifacts) == 2 and artifacts[0] is not artifacts[1]


def test_coming_back_unloads_the_haul(monkeypatch):
    game = on_planet(monkeypatch)
    rolls(monkeypatch, roll=MONSTER_CHANCE)
    game.perform("room.search", {})
    game.perform("room.search", {})
    game.perform("room.return_to_station", {})
    assert (expedition(game), carried(game)) == (None, {"pickaxe": 1, "titanium_ore": 2})
    assert last_message(game) == ("Back Aboard", "The shuttle docks. You unload 2 Titanium Ore.")
    assert notes(game)[-1] == f"Came back from {PLANETS[0]['name']} with 2 Titanium Ore."
    assert labels(game)[0] == "Locker Room"


def test_coming_back_empty_handed(monkeypatch):
    game = on_planet(monkeypatch)
    game.perform("room.return_to_station", {})
    assert last_message(game) == ("Back Aboard", "The shuttle docks. You came back empty-handed.")
    assert carried(game) == {"pickaxe": 1}


def test_a_monster_forces_a_fight(monkeypatch):
    game = fighting(monkeypatch)
    monster = PLANETS[0]["monsters"][0]
    screen = game.view()["screen"]
    assert (screen["type"], screen["heading"], screen["hp"], screen["max_hp"]) == (
        "fight", f"The {monster['name']}", monster["hp"], monster["hp"])
    assert screen["log"] == [f"A {monster['name']} bursts out of the rocks and comes straight at you!"]
    assert [action["action"] for action in screen["actions"]] == ["fight.attack", "fight.block"]
    for action in ("room.search", "room.return_to_station", "room.exit", "game.save_and_exit"):
        game.perform(action, {})
    assert game.player_data["fight"]["enemy"]["hp"] == monster["hp"]
    assert (game.redirect, expedition(game)["haul"]) == (None, {})


def test_beating_the_monster_turns_up_ore(monkeypatch):
    game = fighting(monkeypatch, left="energy_sword", right="pickaxe")
    game.perform("fight.attack", {})
    assert (game.player_data["fight"], expedition(game)["haul"]) == (None, {"titanium_ore": 1})
    assert labels(game)[:2] == ["The Sand Crawler goes down. Under it you find a vein of ore you don't recognise "
                                "and dig some out.", "In the shuttle's hold: 1 unidentified ore."]
    assert game.player_data["limbs"]["head"] == 100


def test_the_rescue_drone_pulls_out_a_beaten_miner_without_the_ore(monkeypatch):
    game = on_planet(monkeypatch)
    rolls(monkeypatch, roll=MONSTER_CHANCE)
    game.perform("room.search", {})
    rolls(monkeypatch)
    game.perform("room.search", {})
    game.player_data["limbs"] = {limb: DEFEAT_HEALTH + 1 for limb in game.player_data["limbs"]}
    game.perform("fight.block", {})
    assert (game.player_data["fight"], expedition(game)) == (None, None)
    assert last_message(game)[0] == "Rescued"
    assert carried(game) == {"pickaxe": 1}
    assert notes(game)[-1] == (
        f"Was beaten by a Sand Crawler on {PLANETS[0]['name']} and lost the trip's ore.")
    assert labels(game)[0] == "Locker Room"
    assert not round_over(game.player_data)


def test_being_taken_off_the_planet_ends_the_trip(monkeypatch):
    game = on_planet(monkeypatch)
    game.player_data["location"] = dict(QUARTERS_LOCATION)
    game.view()
    assert expedition(game) is None


def test_the_miner_gets_an_ore_request(monkeypatch):
    game = new_game("Supply", "Miner")
    event = job_event(monkeypatch, game, randint=lambda low, high: low)
    assert (event["title"], event["desc"]) == (
        "Ore Request", "The Engineer needs an iron ore. Deliver it to the Engineering Bay for 60 credits.")
    event["effect"]()
    assert (duty(game)["room"], duty(game)["item"]) == (ENGINEERING_KEY, "iron_ore")


def test_mining_a_single_rock_reads_as_one(monkeypatch):
    game = in_mining()
    give(game, "pickaxe")
    game.perform("room.toggle_magnet", {})
    at(game, MAGNET_SECONDS_PER_ROCK)
    rolls(monkeypatch, pick=lambda options: "copper_ore")
    game.perform("room.mine_rocks", {})
    assert last_message(game) == ("Mining", "You break up 1 rock and get 1 Copper Ore.")
    assert notes(game)[-1] == "Mined 1 rock from the magnet: 1 Copper Ore."


def clock(game):
    return game.player_data["game_clock"]["elapsed_seconds"]


def test_each_search_takes_game_time(monkeypatch):
    game = on_planet(monkeypatch)
    asked = []
    rolls(monkeypatch, roll=MONSTER_CHANCE + ORE_CHANCE + ARTIFACT_CHANCE,
          randint=lambda low, high: asked.append((low, high)) or low)
    before = clock(game)
    game.perform("room.search", {})
    assert (asked, clock(game)) == ([SEARCH_SECONDS_RANGE], before + SEARCH_SECONDS_RANGE[0])


def test_a_full_hold_stops_the_search_but_artifacts_take_no_room(monkeypatch):
    game = on_planet(monkeypatch)
    rolls(monkeypatch, roll=MONSTER_CHANCE + ORE_CHANCE)
    game.perform("room.search", {})
    assert expedition(game)["artifacts"] == 1
    rolls(monkeypatch, roll=MONSTER_CHANCE)
    for _ in range(HOLD_CAPACITY):
        game.perform("room.search", {})
    assert sum(expedition(game)["haul"].values()) == HOLD_CAPACITY
    before = clock(game)
    game.perform("room.search", {})
    assert (sum(expedition(game)["haul"].values()), clock(game)) == (HOLD_CAPACITY, before)
    assert labels(game)[0] == "The shuttle's hold is full of ore. Take it back to the station."
