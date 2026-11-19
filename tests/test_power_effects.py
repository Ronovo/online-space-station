import time

from helpers import at, choose, crew, give, last_message, new_game, notes
from space_online.game.helper_methods import jail, random_events
from space_online.game.helper_methods.crew_work import ENGINEER_WORK_SECONDS, tick_crew_work
from space_online.game.helper_methods.jail import (
    arrest_wanted_in_room,
    can_hack_doors,
    is_jailed,
    offer_player_arrest_choice,
    warrants_enforced,
)
from space_online.game.helper_methods.power_constants import fault_system, system_online
from space_online.game.helper_methods.rounds import SHUTTLE_LOCKOUT_SECONDS, call_shuttle
from space_online.game.maps.donut import BAR_KEY, ENGINEERING_KEY, MEDBAY_KEY, location_from_key


def power(game):
    return game.player_data["station_power"]


def test_a_system_is_online_while_it_has_power():
    game = new_game()
    assert system_online(game.player_data, "communication_array")
    fault_system(power(game), "communication_array")
    assert not system_online(game.player_data, "communication_array")


def test_station_announcements_only_get_through_while_the_communication_array_is_up():
    game = new_game()
    game.announce("Crew Shuttle", "Docked.", "warning")
    assert game._messages == [("Crew Shuttle", "Docked.", "warning")]
    fault_system(power(game), "communication_array")
    game.announce("Crew Shuttle", "Leaving.")
    game.player_data["game_clock"]["elapsed_seconds"] = SHUTTLE_LOCKOUT_SECONDS
    assert call_shuttle(game, "the shift is over")
    assert len(game._messages) == 1
    assert notes(game)[-1].endswith("It docks at Departures in 5m 0s.")
    game.alert("Door Control", "Still works.")
    assert len(game._messages) == 2


def test_nobody_can_be_called_while_the_communication_array_is_down():
    game = new_game()
    doctor = crew(game, "Doctor")
    doctor.update(on_duty=False, location={"x": 2, "y": 5})
    game.player_data["location"] = location_from_key(MEDBAY_KEY)
    fault_system(power(game), "communication_array")
    game.perform("room.call_npc", {"job": "Doctor"})
    assert last_message(game) == ("No Signal", "The Communication Array is down. Nobody can be called.")
    assert not doctor["on_duty"]


def test_locked_doors_open_while_the_security_systems_are_down():
    game = new_game()
    game.ship_map[BAR_KEY]["locked"] = True
    game.player_data["location"] = {"x": 0, "y": 3}
    game.perform("game.enter_room", {"room_key": BAR_KEY})
    assert last_message(game) == ("Locked", "The Bar door is locked.")
    fault_system(power(game), "security_systems")
    game.perform("game.enter_room", {"room_key": BAR_KEY})
    assert game.location_key() == BAR_KEY


def test_nobody_is_scanned_for_warrants_while_the_security_systems_are_down(monkeypatch):
    game = new_game("Security", "Security Guard")
    doctor, engineer = crew(game, "Doctor"), crew(game, "Engineer")
    doctor["warrant"] = True
    fault_system(power(game), "security_systems")
    assert not warrants_enforced(game.player_data)
    assert not offer_player_arrest_choice(game, doctor)
    arrest_wanted_in_room(MEDBAY_KEY, game, engineer, 0)
    assert not is_jailed(doctor)

    game.player_data.update(warrant=True, location={"x": 0, "y": 1})
    guard = crew(game := new_game(), "Security Guard")
    game.player_data.update(warrant=True)
    fault_system(power(game), "security_systems")
    assert game._handle_hallway_security_encounter(guard) is False

    monkeypatch.setattr(random_events.random, "choice", lambda options: "security")
    random_events.bot_moves_by(game)
    assert not is_jailed(game.player_data)
    assert last_message(game) == ("Security Bot", "A security bot scans you briefly and continues on its patrol.")


def test_a_dead_battery_takes_life_support_down_with_it():
    game = new_game()
    power(game).update(battery_level=0.01, solar_charging=False)
    game.player_data["engine"]["running"] = False
    game.player_data["game_clock"]["last_real_time"] = time.time() - 60
    game.tick()
    assert (power(game)["battery_level"], power(game)["system_levels"]["life_support"]) == (0, 0)
    titles = [title for title, *_ in game._messages]
    assert titles[0] == "Power Outage" and game.ui["panels"][-1]["type"] == "oxygen_announcement"
    assert notes(game)[-1] == "CRITICAL: Station suffered complete power failure. Life support shut down."


def test_life_support_cannot_be_brought_back_until_the_battery_has_charge():
    game = new_game("Engineering", "Engineer")
    power(game).update(battery_level=0)
    power(game)["system_levels"]["life_support"] = 0
    game.player_data["location"] = location_from_key(ENGINEERING_KEY)
    game.open_panel("engineering_panel")
    game.perform("panel.set_level", {"system": "life_support", "value": 10})
    assert last_message(game) == ("No Power", "The battery is dead. Life support can't run until it has some charge.")
    game.perform("panel.set_power_mode", {"mode": "high"})
    levels = power(game)["system_levels"]
    assert (levels["life_support"], levels["hallway_lighting"]) == (0, 10)
    power(game)["battery_level"] = 5
    game.perform("panel.set_level", {"system": "life_support", "value": 10})
    assert levels["life_support"] == 10


def test_the_npc_engineer_brings_life_support_back_once_there_is_power():
    game = new_game()
    engineer = crew(game, "Engineer")
    power(game).update(battery_level=0, solar_charging=True)
    power(game)["system_levels"]["life_support"] = 0
    game.player_data["crew_work"] = {MEDBAY_KEY: 10 ** 9}
    at(game, ENGINEER_WORK_SECONDS, tick_crew_work)
    assert power(game)["system_levels"]["life_support"] == 0 and game._messages == []
    power(game)["battery_level"] = 3
    at(game, 2 * ENGINEER_WORK_SECONDS, tick_crew_work)
    assert power(game)["system_levels"]["life_support"] == 10
    assert last_message(game) == ("Engineering", f"{engineer['name']} brings life support back up.")


def test_bringing_life_support_back_leaves_the_other_systems_as_they_were_set():
    game = new_game()
    power(game).update(battery_level=3, solar_charging=True)
    power(game)["system_levels"].update(life_support=0, hallway_lighting=2, security_systems=0, communication_array=9)
    game.player_data["crew_work"] = {MEDBAY_KEY: 10 ** 9}
    at(game, ENGINEER_WORK_SECONDS, tick_crew_work)
    assert power(game)["system_levels"] == {"life_support": 10, "hallway_lighting": 2, "security_systems": 0,
                                            "communication_array": 9}


def at_locked_bar(department="Civilian", job="Staff Assistant"):
    game = new_game(department, job)
    game.ship_map[BAR_KEY]["locked"] = True
    game.player_data["location"] = {"x": 0, "y": 3}
    return game


def test_a_screwdriver_and_wirecutters_force_a_locked_door_and_the_door_reports_it():
    game = give(at_locked_bar(), "screwdriver")
    assert not can_hack_doors(game.player_data)
    give(game, "wirecutters")
    game.perform("game.enter_room", {"room_key": BAR_KEY})
    choice = game.view()["choice"]
    assert (choice["message"], choice["buttons"]) == (
        "The Bar door is locked. Force it with your screwdriver and wirecutters?", ["Force the Lock", "Leave It"])
    choose(game, "Force the Lock")
    assert not game.ship_map[BAR_KEY]["locked"]
    assert (game.player_data["warrant"], game.player_data["warrant_reason"]) == (True, "Breaking and entering")
    assert last_message(game) == ("Door Hacked", "You short the lock on the Bar door, and it slides open. "
                                                 "The door logs the break-in: there is a warrant out for you.")
    game.perform("game.enter_room", {"room_key": BAR_KEY})
    assert game.location_key() == BAR_KEY


def test_the_rooms_own_crew_walk_through_its_locked_door_and_it_stays_locked():
    game = give(at_locked_bar("Civilian", "Bartender"), "basic_tools")
    game.perform("game.enter_room", {"room_key": BAR_KEY})
    assert (game.location_key(), game.view()["choice"], game._messages) == (BAR_KEY, None, [])
    assert (game.ship_map[BAR_KEY]["locked"], game.player_data["warrant"]) == (True, False)


def test_leaving_a_locked_door_alone_changes_nothing():
    game = give(at_locked_bar(), "basic_tools")
    game.perform("game.enter_room", {"room_key": BAR_KEY})
    choose(game, "Leave It")
    assert game.ship_map[BAR_KEY]["locked"] and game._messages == []
    assert game.location_key() != BAR_KEY


def test_a_door_cannot_be_forced_once_it_is_open_or_the_tools_are_gone():
    game = give(at_locked_bar(), "screwdriver", "wirecutters")
    game.ship_map[BAR_KEY]["locked"] = False
    jail.hack_door(game, BAR_KEY)
    game.ship_map[BAR_KEY]["locked"] = True
    game.player_data["inventory"] = []
    jail.hack_door(game, BAR_KEY)
    assert (game.ship_map[BAR_KEY]["locked"], game.player_data["warrant"], game._messages) == (True, False, [])
