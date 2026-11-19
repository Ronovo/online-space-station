import re
import time

import pytest

from helpers import at, crew, fix_random, give, in_room, labels, last_message, new_game, notes, reports
from space_online.game.helper_methods import hazards, random_events
from space_online.game.helper_methods.crew_work import ENGINEER_WORK_SECONDS, post_worker, tick_crew_work
from space_online.game.helper_methods.hazards import (
    HAZARD_DAMAGE,
    HAZARD_DAMAGE_CAP,
    HAZARD_HURT_SECONDS,
    HAZARD_INTERVAL_RANGE,
    HAZARD_ROOM_KEYS,
    HAZARDS,
    hazard_rooms,
    room_hazard,
    set_hazard,
    start_random_hazard,
    tick_hazards,
)
from space_online.game.helper_methods.power_constants import fault_system
from space_online.game.helper_methods.random_events import build_job_event
from space_online.game.maps.donut import (
    BAR_KEY,
    DEPARTURES_KEY,
    ENGINEERING_KEY,
    MEDBAY_KEY,
    MINING_KEY,
    QUARTERS_KEY,
    ROOMS,
)
from space_online.game.objects.items import get_item_definition, has_tool
from space_online.game.special_rooms.shared import available_npc


def in_hazard(room_key, hazard, department="Civilian", job="Staff Assistant"):
    game = in_room(room_key, department, job)
    set_hazard(game.player_data, room_key, hazard)
    return game


def dice(monkeypatch, pick=lambda options: options[0]):
    fix_random(monkeypatch, hazards, random_events, pick=pick, randint=lambda low, high: low)


def test_a_tool_is_to_hand_when_carried_held_or_still_in_a_carried_toolkit():
    game = new_game()
    assert not has_tool(game.player_data, "wrench")
    give(game, "basic_tools")
    assert has_tool(game.player_data, "wrench") and not has_tool(game.player_data, "fire_extinguisher")
    game.player_data["inventory"][0]["attributes"]["contents"].pop(0)
    assert not has_tool(game.player_data, "wrench")
    game.player_data["hands"]["left"] = get_item_definition("wrench")
    assert has_tool(game.player_data, "wrench")


def test_hazards_break_out_on_the_clock_in_a_room_without_one(monkeypatch):
    dice(monkeypatch)
    game = new_game()
    state = game.player_data["hazards"]
    assert HAZARD_INTERVAL_RANGE[0] <= state["next_at"] <= HAZARD_INTERVAL_RANGE[1]
    state["next_at"] = 100
    game.player_data["game_clock"]["elapsed_seconds"] = 99
    tick_hazards(game, 1)
    assert hazard_rooms(game.player_data) == []
    game.player_data["game_clock"]["elapsed_seconds"] = 100
    tick_hazards(game, 1)
    first = HAZARD_ROOM_KEYS[0]
    assert hazard_rooms(game.player_data) == [(first, "breach")]
    assert state["next_at"] == 100 + HAZARD_INTERVAL_RANGE[0]
    assert game._messages == [("Hazard", "A hull breach has opened in the Bridge. The air is venting out.", "warning")]
    assert start_random_hazard(game) == (HAZARD_ROOM_KEYS[1], "breach")
    assert QUARTERS_KEY not in HAZARD_ROOM_KEYS and DEPARTURES_KEY not in HAZARD_ROOM_KEYS


def test_no_new_hazard_when_every_room_has_one():
    game = new_game()
    for key in HAZARD_ROOM_KEYS:
        set_hazard(game.player_data, key, "fire")
    assert start_random_hazard(game) is None


def test_a_hazard_is_not_announced_while_the_communication_array_is_down(monkeypatch):
    dice(monkeypatch)
    game = new_game()
    fault_system(game.player_data["station_power"], "communication_array")
    start_random_hazard(game)
    assert game._messages == [] and len(hazard_rooms(game.player_data)) == 1
    assert notes(game)[-1].startswith("A hull breach has opened")


def test_walking_into_a_hazard_warns_you_and_the_room_shows_it_and_how_to_fix_it():
    game = new_game()
    set_hazard(game.player_data, BAR_KEY, "fire")
    game.player_data["location"] = {"x": 0, "y": 3}
    game.perform("game.enter_room", {"room_key": BAR_KEY})
    assert last_message(game) == ("Hazard", "Part of the room is on fire, and the smoke is thick. "
                                            "Staying here will hurt you.")
    screen = game.view()["screen"]
    assert screen["hazard"] == "Part of the room is on fire, and the smoke is thick."
    assert labels(game)[0] == "Put Out the Fire"
    assert labels(game)[1] == "The Bartender has cleared out until the fire is dealt with."
    assert available_npc(game, "Bartender", BAR_KEY) is None


@pytest.mark.parametrize("kind, damage_type", [("breach", "oxygen"), ("fire", "burn")])
def test_standing_in_a_breach_or_a_fire_hurts_every_few_seconds_but_never_quite_kills(kind, damage_type):
    game = in_hazard(BAR_KEY, kind)
    tick_hazards(game, HAZARD_HURT_SECONDS - 1)
    assert game.player_data["damage"][damage_type] == 0
    tick_hazards(game, 1)
    assert game.player_data["damage"][damage_type] == HAZARD_DAMAGE
    assert last_message(game)[1].endswith(f"{damage_type.title()} damage: {HAZARD_DAMAGE}%.")
    tick_hazards(game, 100 * HAZARD_HURT_SECONDS)
    assert game.player_data["damage"][damage_type] == HAZARD_DAMAGE_CAP
    game.player_data["damage"][damage_type] = 99
    tick_hazards(game, HAZARD_HURT_SECONDS)
    assert game.player_data["damage"][damage_type] == 99


def test_bad_wiring_shocks_a_limb(monkeypatch):
    dice(monkeypatch)
    game = in_hazard(BAR_KEY, "wiring")
    tick_hazards(game, HAZARD_HURT_SECONDS)
    assert game.player_data["limbs"]["head"] == 100 - HAZARD_DAMAGE
    assert last_message(game) == ("Hazard", f"A live wire catches your head. It is at {100 - HAZARD_DAMAGE}%.")


def test_a_hazard_only_hurts_while_you_are_in_its_room_and_not_down_on_the_planet():
    game = in_room(BAR_KEY)
    set_hazard(game.player_data, MEDBAY_KEY, "fire")
    tick_hazards(game, 5 * HAZARD_HURT_SECONDS)
    game = in_hazard(MINING_KEY, "fire", "Supply", "Miner")
    game.player_data["mining"]["expedition"] = {"planet": 0, "haul": {}, "vein": None, "artifacts": 0, "log": []}
    tick_hazards(game, 5 * HAZARD_HURT_SECONDS)
    assert game.player_data["damage"]["burn"] == 0 and labels(game)[0] != "Put Out the Fire"
    game.player_data["mining"]["expedition"] = None
    tick_hazards(game, HAZARD_HURT_SECONDS - 1)
    game.player_data["location"] = {"x": 0, "y": 0}
    tick_hazards(game, HAZARD_HURT_SECONDS - 1)
    assert (game.player_data["damage"]["burn"], game.player_data["damage_timers"]["hazard_acc"]) == (0, 0.0)


def test_the_master_clock_runs_the_hazards():
    game = in_hazard(BAR_KEY, "fire")
    game.player_data["game_clock"]["last_real_time"] = time.time() - HAZARD_HURT_SECONDS
    game.tick()
    assert game.player_data["damage"]["burn"] == HAZARD_DAMAGE


@pytest.mark.parametrize("kind, tool, fixed", [
    ("breach", "wrench", "You bolt a patch over the breach with the wrench. The air holds."),
    ("fire", "fire_extinguisher", "You smother the fire with the fire extinguisher."),
    ("wiring", "wirecutters", "You cut out the shorted wiring with the wirecutters."),
])
def test_each_hazard_is_dealt_with_from_inside_the_room_with_its_tool(kind, tool, fixed):
    game = in_hazard(BAR_KEY, kind)
    game.perform("room.fix_hazard", {})
    name = get_item_definition(tool)["name"]
    assert last_message(game) == ("Hazard", f"You need a {name} to deal with the {HAZARDS[kind]['name']}.")
    assert room_hazard(game.player_data, BAR_KEY) == kind
    give(game, tool)
    game.perform("room.fix_hazard", {})
    assert (last_message(game), room_hazard(game.player_data, BAR_KEY)) == (("Hazard", fixed), None)
    assert (notes(game)[-1], game.player_data["round"]["duties_done"]) == (fixed, 0)
    count = len(game._messages)
    game.perform("room.fix_hazard", {})
    assert len(game._messages) == count and labels(game)[0] == "Order Drinks"


def test_fixing_a_hazard_is_a_duty_done_for_an_engineer():
    game = give(in_hazard(BAR_KEY, "breach", "Engineering", "Engineer"), "basic_tools")
    game.perform("room.fix_hazard", {})
    assert game.player_data["round"]["duties_done"] == 1


def test_a_hazard_stops_the_rooms_post_working_except_the_engineers_own():
    game = new_game()
    set_hazard(game.player_data, MEDBAY_KEY, "fire")
    set_hazard(game.player_data, ENGINEERING_KEY, "wiring")
    assert post_worker(game, "Doctor", MEDBAY_KEY) is None
    assert post_worker(game, "Engineer", ENGINEERING_KEY) is crew(game, "Engineer")


def test_the_npc_engineer_deals_with_hazards_before_anything_else():
    game = new_game()
    engineer = crew(game, "Engineer")
    set_hazard(game.player_data, BAR_KEY, "fire")
    fault_system(game.player_data["station_power"], "security_systems")
    game.player_data["crew_work"] = {MEDBAY_KEY: 10 ** 9}
    at(game, ENGINEER_WORK_SECONDS, tick_crew_work)
    assert hazard_rooms(game.player_data) == [] and game.player_data["station_power"]["faults"]
    assert last_message(game) == ("Engineering", f"{engineer['name']} deals with the fire in the Bar.")


def test_an_engineers_job_never_starts_a_room_hazard(monkeypatch):
    offered = []
    dice(monkeypatch, pick=lambda options: offered.append(list(options)) or options[0])
    game = new_game("Engineering", "Engineer")
    game.player_data["station_power"]["solar_charging"] = True
    build_job_event(game)["effect"]()
    assert offered[0] == ["solar", "fault"]
    assert hazard_rooms(game.player_data) == []


def test_station_status_lists_a_hazard_above_a_system_fault():
    game = new_game("Administration", "Captain")
    game.player_data["station_power"]["battery_level"] = 80
    set_hazard(game.player_data, BAR_KEY, "breach")
    fault_system(game.player_data["station_power"], "security_systems")
    game.open_panel("station_status")
    ctx = game.view()["panel"]["ctx"]
    assert len(ctx["alerts"]) == 2
    assert (ctx["alerts"][0], ctx["overall"]) == ({"text": "Hull breach in the Bar", "severity": "critical"}, "CRITICAL")
    assert reports(game) == []


@pytest.mark.parametrize("room_key", HAZARD_ROOM_KEYS)
def test_a_hazard_starting_in_any_room_names_the_room_as_a_place(room_key):
    game = new_game()
    for kind in HAZARDS:
        hazards.start_hazard(game, room_key, kind)
    lines = [message for _, message, *_ in game._messages]
    assert len(lines) == len(HAZARDS)
    for line in lines:
        assert re.search(r"\bthe (Chemistry|Security)\b(?! Lab| Office)", line) is None
        assert f"the {ROOMS[room_key].name}" in line
