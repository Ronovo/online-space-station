import logging
import time
from types import SimpleNamespace

import pytest

from helpers import new_game, reports
from space_online.game import main
from space_online.game.helper_methods import jail, player_movement, ui_panels
from space_online.game.helper_methods.oxygen_helper import OXYGEN_DEATH_TITLE, POST_DEATH_OXYGEN
from space_online.game.maps.donut import BAR_KEY, QUARTERS_KEY, QUARTERS_LOCATION, SECURITY_KEY

QUIET_TILE = {"x": 2, "y": 5}


@pytest.fixture(autouse=True)
def no_hallway_events(monkeypatch):
    monkeypatch.setattr(player_movement, "maybe_trigger_hallway_event", lambda game: None)


def quiet(game):
    """Park every wandering NPC on one tile away from the tests, so nobody passes the player by chance."""
    for npc in game.station_crew:
        if npc["job"] == "Staff Assistant":
            npc["location"] = dict(QUIET_TILE)
    return game


def at(game, x, y):
    game.player_data["location"] = {"x": x, "y": y}
    return game


def crew(game, job):
    return next(npc for npc in game.station_crew if npc["job"] == job)


def messages(game):
    return [message for _, _, message, _ in game._messages]


def due_tick(game, seconds=60):
    """Make the next tick() run, as if `seconds` of real time had passed."""
    game.player_data["game_clock"]["last_real_time"] = time.time() - seconds


def grid_labels(view):
    return {cell["label"]: (row, col, cell["action"], cell["args"])
            for row, cells in enumerate(view["screen"]["grid"]) for col, cell in enumerate(cells) if cell}


def test_the_hallway_shows_the_ways_on_and_the_doors_here():
    view = at(quiet(new_game()), 0, 0).view()
    assert view["screen"]["type"] == "hallway"
    assert view["screen"]["coords"] == "Location: 0 North, 0 East"
    assert grid_labels(view) == {
        "Go North": (0, 1, "game.move", {"direction": "north"}),
        "Go East": (1, 2, "game.move", {"direction": "east"}),
        "Quarters": (3, 1, "game.enter_room", {"room_key": QUARTERS_KEY}),
    }


def test_walking_the_hallway():
    game = at(quiet(new_game()), 0, 0)
    game.perform("game.move", {"direction": "north"})
    assert game.player_data["location"] == {"x": 1, "y": 0}
    game.perform("game.move", {"direction": "east"})
    assert game.player_data["location"] == {"x": 1, "y": 0}
    assert game.drain_alerts() == [{"title": "Error", "message": "You can't go that way!", "kind": "error"}]
    game.perform("game.move", {"direction": "up"})
    assert game.player_data["location"] == {"x": 1, "y": 0}
    assert game.drain_alerts() == []


def test_no_walking_inside_a_room_or_with_a_panel_open():
    game = quiet(new_game())
    game.perform("game.move", {"direction": "north"})
    assert game.player_data["location"] == QUARTERS_LOCATION
    at(game, 0, 0).perform("game.character_sheet", {})
    game.perform("game.move", {"direction": "north"})
    assert game.player_data["location"] == {"x": 0, "y": 0}


def test_entering_and_leaving_a_room():
    game = at(quiet(new_game()), 0, 3)
    game.perform("game.enter_room", {"room_key": BAR_KEY})
    assert game.location_key() == BAR_KEY
    assert game.view()["screen"]["type"] == "room"
    game.perform("room.exit", {})
    assert game.player_data["location"] == {"x": 0, "y": 3}


@pytest.mark.parametrize("where, panel", [((0, 0), False), ((0, 3), True)])
def test_only_the_door_in_front_of_you_opens_and_only_with_no_panel_open(where, panel):
    game = at(quiet(new_game()), *where)
    if panel:
        game.open_panel("character_sheet")
    game.perform("game.enter_room", {"room_key": BAR_KEY})
    assert game.player_data["location"] == {"x": where[0], "y": where[1]}


def test_entering_a_room_from_inside_another_does_nothing():
    game = quiet(new_game())
    game.enter_room(BAR_KEY)
    assert game.player_data["location"] == QUARTERS_LOCATION


def test_a_locked_door_keeps_you_out():
    game = at(quiet(new_game()), 0, 3)
    game.ship_map[BAR_KEY]["locked"] = True
    game.perform("game.enter_room", {"room_key": BAR_KEY})
    assert game.player_data["location"] == {"x": 0, "y": 3}
    assert messages(game) == ["The Bar door is locked."]


def test_save_and_exit_goes_home_unless_a_panel_is_open():
    game = new_game()
    game.open_panel("character_sheet")
    game.perform("game.save_and_exit", {})
    assert game.view()["redirect"] is None
    game.perform("game.close_panel", {})
    game.perform("game.save_and_exit", {})
    assert game.view()["redirect"] == "home"


def test_a_pending_choice_blocks_everything_but_answering_it(monkeypatch):
    picked = []
    monkeypatch.setitem(ui_panels.CHOICE_HANDLERS, "test_pick", lambda game, **args: picked.append(args))
    game = at(quiet(new_game()), 0, 0)
    game.ask("Pick", "Which one?", [("This", "test_pick", {"n": 1}), ("Nothing", None, None)])
    choice = game.view()["choice"]
    assert (choice["title"], choice["message"], choice["buttons"]) == ("Pick", "Which one?", ["This", "Nothing"])
    game.perform("game.move", {"direction": "north"})
    assert game.player_data["location"] == {"x": 0, "y": 0}
    game.perform("game.choose", {"id": "stale", "index": 0})
    assert picked == [] and game.ui["choices"]
    game.perform("game.choose", {"id": choice["id"], "index": 0})
    assert picked == [{"n": 1}]
    assert game.view()["choice"] is None


def test_a_button_without_a_handler_just_closes_the_choice():
    game = new_game()
    game.ask("Note", "Done.", [("OK", None, None)])
    game.perform("game.choose", {"id": game.ui["choices"][0]["id"], "index": 0})
    assert game.ui["choices"] == []
    game.perform("game.choose", {"id": "none left", "index": 0})
    assert game.drain_alerts() == []


@pytest.mark.parametrize("action, args", [("game.move", {}), ("game.enter_room", "not a dict"),
                                          ("game.choose", "not a dict")])
def test_unusable_arguments_are_refused(action, args):
    game = at(quiet(new_game()), 0, 0)
    if action == "game.choose":
        game.ask("Pick", "?", [("OK", None, None)])
        args = {"id": game.ui["choices"][0]["id"], "index": "first"}
    game.perform(action, args)
    assert game.drain_alerts() == [{"title": "Error", "message": "That action could not be completed.", "kind": "error"}]


@pytest.mark.parametrize("action", ["game.fly", "game", "nonsense.move", "panel.inventory", "room.exit"])
def test_actions_that_do_not_apply_do_nothing(action):
    game = at(quiet(new_game()), 0, 0)
    game.perform(action, {})
    assert (game.player_data["location"], game.ui["panels"], game.drain_alerts()) == ({"x": 0, "y": 0}, [], [])


def test_panels_stack_and_close():
    game = new_game()
    game.add_note("Woke up.")
    game.perform("game.character_sheet", {})
    sheet = game.view()["panel"]
    assert (sheet["type"], sheet["title"], sheet["ctx"]["name"], sheet["ctx"]["notes_count"]) == (
        "character_sheet", "Character Sheet", "Ada", 1)
    for action, panel in (("notes", "notes"), ("holdings", "holdings"), ("inventory", "inventory")):
        game.perform(f"panel.{action}", {})
        assert game.view()["panel"]["type"] == panel
        game.perform("game.close_panel", {})
    assert game.view()["panel"]["type"] == "character_sheet"
    game.perform("panel.notes", {})
    assert [note["text"] for note in game.view()["panel"]["ctx"]["notes"]] == ["Woke up."]
    game.perform("game.hands", {})
    assert game.view()["panel"]["type"] == "hands"


def test_the_character_sheet_colours_damage_and_limbs():
    game = new_game()
    game.player_data["damage"]["burn"] = 45
    game.player_data["limbs"]["left_leg"] = 30
    game.player_data["stock_holdings"] = {"NOVA": 3}
    game.perform("game.character_sheet", {})
    ctx = game.view()["panel"]["ctx"]
    assert ctx["damage"][0] == {"name": "Burn", "value": 45, "color": "orange", "effect": "Moderate"}
    assert ctx["damage"][1]["effect"] is None
    assert {"name": "Left Leg", "health": 30, "color": "red"} in ctx["limbs"]
    assert ctx["damage_health"] == 85
    assert ctx["holdings_count"] == 1
    game.perform("panel.holdings", {})
    assert game.view()["panel"]["ctx"] == {"holdings": [("NOVA", 3)]}


def test_room_actions_wait_until_the_panels_are_closed():
    game = at(quiet(new_game()), 0, 3)
    game.enter_room(BAR_KEY)
    game.open_panel("character_sheet")
    game.perform("room.exit", {})
    assert game.location_key() == BAR_KEY


def test_a_panel_with_nothing_left_to_show_closes_itself(monkeypatch):
    monkeypatch.setitem(ui_panels.PANELS, "emptied", {"title": "Emptied", "context": lambda game, state: None})
    game = new_game()
    game.open_panel("character_sheet")
    game.open_panel("emptied")
    game.open_panel("not a panel")
    assert game.view()["panel"]["type"] == "character_sheet"
    assert [panel["type"] for panel in game.ui["panels"]] == ["character_sheet"]


def test_replacing_and_closing_panels():
    game = new_game()
    game.replace_panel("notes")
    game.replace_panel("holdings")
    assert [panel["type"] for panel in game.ui["panels"]] == ["holdings"]
    game.close_panel("notes")
    assert game.top_panel()["type"] == "holdings"
    game.close_panel("holdings")
    game.close_panel()
    assert game.top_panel() is None


def test_reports_merge_into_the_first_alerts_place():
    game = new_game()
    game.report("Power", "Low", "warning")
    game.alert("Door", "Locked")
    game.report("Oxygen", "Thin", "error")
    assert game.drain_alerts() == [
        {"title": "Station Alerts", "message": "[Power] Low\n\n[Oxygen] Thin", "kind": "error"},
        {"title": "Door", "message": "Locked", "kind": "info"},
    ]
    assert game.drain_alerts() == []


def test_the_clock_waits_a_second_between_ticks():
    game = new_game()
    before = game.player_data["station_power"]["battery_level"]
    game.player_data["game_clock"]["last_real_time"] = time.time()
    game.tick()
    assert game.player_data["station_power"]["battery_level"] == before


def power_after_a_minute(solar, mode, battery=50.0):
    game = new_game()
    power = game.player_data["station_power"]
    power.update(solar_charging=solar, power_mode=mode, battery_level=battery)
    due_tick(game)
    game.tick()
    return game, power["battery_level"]


def test_power_modes_with_the_solar_array_on():
    assert power_after_a_minute(True, "high")[1] == pytest.approx(49.5, abs=0.01)
    assert power_after_a_minute(True, "balanced")[1] == 50.0
    assert power_after_a_minute(True, "emergency")[1] == pytest.approx(50 + 1.5 * (3 - 0.63), abs=0.02)


def test_without_solar_the_systems_drain_the_battery():
    assert power_after_a_minute(False, "balanced")[1] == pytest.approx(50 - 0.96, abs=0.01)


def test_falling_through_the_critical_level_warns_once():
    game, level = power_after_a_minute(False, "balanced", battery=10.5)
    assert 0 < level <= 10
    assert reports(game) == ["Low Power Warning"]


def test_running_the_battery_flat_is_an_outage():
    game, level = power_after_a_minute(False, "balanced", battery=0.5)
    assert level == 0
    assert reports(game) == ["Power Outage"]
    assert game.player_data["notes"][-1]["text"].startswith("CRITICAL: Station suffered complete power failure")


def test_failing_life_support_warns_then_kills():
    game = at(new_game(), 0, 0)
    game.player_data["station_power"]["system_levels"]["life_support"] = 0
    game.player_data["station_power"]["solar_charging"] = True
    due_tick(game)
    game.tick()
    assert "Oxygen Warning" in reports(game)
    assert game.player_data["notes"][-1]["text"] == "Suffered 30% oxygen damage due to life support failure."
    game.player_data["damage"]["oxygen"] = 95
    game.open_panel("character_sheet")
    due_tick(game)
    game.tick()
    assert OXYGEN_DEATH_TITLE in reports(game)
    assert game.player_data["damage"]["oxygen"] == POST_DEATH_OXYGEN
    assert game.player_data["location"] == QUARTERS_LOCATION
    assert game.ui["panels"] == []


def test_a_failing_subsystem_does_not_stop_the_others(monkeypatch, caplog):
    def broken(*args):
        raise RuntimeError("alcohol is broken")

    monkeypatch.setattr(main, "apply_alcohol_tick", broken)
    game, level = power_after_a_minute(False, "balanced")
    assert level < 50
    assert "Master clock subsystem failed" in caplog.text


def test_npcs_move_at_most_every_few_seconds(monkeypatch):
    moves = []
    monkeypatch.setattr(main, "roll_departures", lambda crew: moves.append("departures"))
    monkeypatch.setattr(main, "step_wanderers", lambda game: moves.append("wander"))
    game = new_game()
    due_tick(game)
    game.tick()
    due_tick(game)
    game.tick()
    assert moves == ["departures", "wander"]
    game.player_data["game_clock"]["last_npc_move_real"] -= main.NPC_MOVE_INTERVAL_SECONDS
    due_tick(game)
    game.tick()
    assert moves == ["departures", "wander"] * 2


def test_a_jailed_player_is_kept_in_security():
    game = at(new_game(), 0, 0)
    game.player_data["in_jail"] = True
    game.view()
    assert game.location_key() == SECURITY_KEY


def test_a_location_off_the_map_goes_back_to_quarters():
    game = at(new_game(), 40, 40)
    view = game.view()
    assert game.player_data["location"] == QUARTERS_LOCATION
    assert view["alerts"] == [{"title": "Error", "message": "Invalid location!", "kind": "error"}]


def test_arrest_and_release_move_the_player():
    game = at(new_game(), 0, 0)
    game.handle_player_arrest("Got you.", show_message=False)
    assert game.location_key() == SECURITY_KEY
    assert game._messages == []
    game.handle_player_release()
    assert game.player_data["location"] == jail.security_hallway_location()
    assert reports(game) == ["Released"]


def test_a_jailed_player_cannot_walk():
    game = at(new_game(), 0, 0)
    game.player_data.update(in_jail=True, jail_release_at_seconds=90)
    game.move_direction("north")
    assert game.player_data["location"] == {"x": 0, "y": 0}
    assert messages(game) == ["You are in jail. Time remaining: 1m 30s."]


def drunk_dice(monkeypatch, *, stumble, fall):
    rolls = iter([0.0 if stumble else 0.99, 0.0 if fall else 0.99])
    monkeypatch.setattr(player_movement, "random", SimpleNamespace(
        random=lambda: next(rolls), choice=lambda limbs: limbs[0], randint=lambda low, high: high))


def test_a_drunk_player_can_fall_and_get_hurt(monkeypatch):
    drunk_dice(monkeypatch, stumble=True, fall=True)
    game = at(quiet(new_game()), 0, 0)
    game.player_data["alcohol_percent"] = 30
    game.move_direction("north")
    assert game.player_data["location"] == {"x": 0, "y": 0}
    assert game.player_data["limbs"]["head"] == 95
    assert messages(game) == ["You stumble and fall hard!\n\nYour Head took 5% blunt damage and is now at 95%."]


def test_a_drunk_player_can_stumble_and_stay_put(monkeypatch):
    drunk_dice(monkeypatch, stumble=True, fall=True)
    game = at(quiet(new_game()), 0, 0)
    game.player_data["alcohol_percent"] = 10
    game.move_direction("north")
    assert game.player_data["location"] == {"x": 0, "y": 0}
    assert reports(game) == ["You Stumble"]


def test_a_drunk_player_who_keeps_their_feet_moves(monkeypatch):
    drunk_dice(monkeypatch, stumble=False, fall=False)
    game = at(quiet(new_game()), 0, 0)
    game.player_data["alcohol_percent"] = 30
    game.move_direction("north")
    assert game.player_data["location"] == {"x": 1, "y": 0}


def test_a_hallway_event_that_jails_the_player_ends_the_move(monkeypatch):
    def arrested(game):
        game.player_data["in_jail"] = True

    monkeypatch.setattr(player_movement, "maybe_trigger_hallway_event", arrested)
    game = at(quiet(new_game()), 0, 0)
    passerby = game.station_crew[-1]
    passerby["location"] = {"x": 1, "y": 0}
    game.move_direction("north")
    assert reports(game) == []


def meet(game, npc):
    """Put npc off duty on the tile north of the player at (0, 0), then step onto it."""
    npc.update(on_duty=False, room_visit_remaining=0, location={"x": 1, "y": 0})
    at(game, 0, 0).move_direction("north")


def never_refuse(monkeypatch):
    monkeypatch.setattr(jail.random, "random", lambda: 0.99)


def test_someone_passing_in_the_hall_is_mentioned():
    game = quiet(new_game())
    doctor = crew(game, "Doctor")
    meet(game, doctor)
    assert messages(game) == [f"{doctor['name']} (Doctor) passes you in the hall."]


def test_a_guard_collects_the_players_fine(monkeypatch):
    never_refuse(monkeypatch)
    game = quiet(new_game())
    game.player_data.update(fine_amount=100, fine_reason="Littering")
    meet(game, crew(game, "Security Guard"))
    assert reports(game) == ["Fine Paid", "Crew Encounter"]
    assert game.player_data["credits"] == 900


def test_a_guard_jails_a_player_who_cannot_pay(monkeypatch):
    never_refuse(monkeypatch)
    game = quiet(new_game())
    game.player_data.update(fine_amount=5000, fine_reason="Arson", credits=10)
    meet(game, crew(game, "Security Guard"))
    assert jail.is_jailed(game.player_data)
    assert game.location_key() == SECURITY_KEY


def test_a_guard_arrests_a_wanted_player_after_collecting_their_fine(monkeypatch):
    never_refuse(monkeypatch)
    game = quiet(new_game())
    game.player_data.update(fine_amount=10, fine_reason="Littering", warrant=True, warrant_reason="Theft")
    guard = crew(game, "Security Guard")
    meet(game, guard)
    assert reports(game) == ["Fine Paid", "Arrested"]
    assert game._messages[-1][2] == f"{guard['name']} stops you in the hall. You are under arrest!\nCharge: Theft"


def test_a_security_player_collects_a_passing_fine(monkeypatch):
    never_refuse(monkeypatch)
    game = quiet(new_game("Security", "Security Guard"))
    doctor = crew(game, "Doctor")
    doctor.update(fine_amount=50, fine_reason="Speeding")
    meet(game, doctor)
    assert reports(game) == ["Fine Paid"]
    assert doctor["fine_amount"] == 0


def test_a_security_player_stops_a_wanted_passerby():
    game = quiet(new_game("Security", "Security Guard"))
    doctor = crew(game, "Doctor")
    doctor.update(warrant=True, warrant_reason="Theft")
    meet(game, doctor)
    assert game.ui["choices"][0]["title"] == "Wanted Crew"
    assert reports(game) == []


def test_a_security_player_scans_a_room_on_entry(monkeypatch):
    never_refuse(monkeypatch)
    game = at(quiet(new_game("Security", "Security Guard")), 0, 3)
    bartender = crew(game, "Bartender")
    bartender.update(fine_amount=20, fine_reason="Noise")
    doctor = crew(game, "Doctor")
    doctor.update(location={"x": -1, "y": 3}, warrant=True, warrant_reason="Theft")
    game.perform("game.enter_room", {"room_key": BAR_KEY})
    assert reports(game) == ["Fine Paid"]
    assert game.ui["choices"][0]["title"] == "Wanted Crew"
