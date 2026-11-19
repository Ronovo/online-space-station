import pytest

from helpers import new_game
from space_online.game.character_methods import character_creation
from space_online.game.character_methods.character_creation import NPC_NAMES, new_shift
from space_online.game.helper_methods import ui_panels
from space_online.game.helper_methods.alcohol_helper import fall_chance, sober_up_cost, stumble_chance
from space_online.game.helper_methods.door_control import ACCESS_ERROR, toggle_door_lock
from space_online.game.helper_methods.game_clock import format_elapsed
from space_online.game.helper_methods.health_bands import (
    change_limb,
    damage_band,
    health_band,
    new_body,
    overall_health,
    reduce_damage,
)
from space_online.game.helper_methods.lighting_helper import (
    battery_lighting_band,
    clamp_lighting_for_battery,
    lighting_style,
)
from space_online.game.helper_methods.oxygen_helper import (
    DOCTOR_REQUIRED_FLOOR,
    RECOVERY_SECONDS_PER_PERCENT,
    apply_oxygen_tick,
)
from space_online.game.helper_methods.power_constants import battery_band, calculate_discharge, default_station_power
from space_online.game.helper_methods.ui_panels import current_feedback, set_feedback
from space_online.game.maps.donut import BRIDGE_KEY, MEDBAY_KEY


@pytest.mark.parametrize("alcohol, stumble, fall", [
    (5, 0, 0), (6, 10, 0), (10, 15, 0), (15, 20, 0), (20, 25, 0),
    (25, 35, 25), (50, 55, 35), (75, 75, 50), (100, 80, 75),
])
def test_stumbling_and_falling_get_likelier_with_drink(alcohol, stumble, fall):
    assert (stumble_chance(alcohol), fall_chance(alcohol)) == (stumble, fall)


@pytest.mark.parametrize("alcohol, cost", [(24.9, 0), (25, 25), (60.7, 60)])
def test_sobering_up_costs_a_credit_a_percent_from_the_doctor_floor(alcohol, cost):
    assert sober_up_cost(alcohol) == cost


@pytest.mark.parametrize("value, band", [(100, "Healthy"), (99.9, "Minor injuries"), (76, "Minor injuries"),
                                         (75, "Injured"), (41, "Injured"), (40, "Critical")])
def test_health_bands(value, band):
    assert health_band(value)[0] == band


@pytest.mark.parametrize("value, band", [(9, "Clear"), (10, "Mild"), (29, "Mild"), (30, "Moderate"),
                                         (59, "Moderate"), (60, "Severe")])
def test_damage_bands(value, band):
    assert damage_band(value)[0] == band


def test_limbs_stay_between_0_and_100():
    body = new_body()
    assert change_limb(body, "head", 30) == (100, 100)
    assert change_limb(body, "head", -130) == (100, 0)


def test_damage_heals_down_to_zero():
    body = new_body()
    body["damage"]["burn"] = 20
    assert reduce_damage(body, "burn", 50) == (20, 0)


def test_overall_health_scales_the_limbs_by_the_damage_taken():
    body = new_body()
    assert overall_health(body) == 100
    body["damage"] = {"burn": 50, "poison": 50, "oxygen": 50}
    assert overall_health(body) == 50


@pytest.mark.parametrize("battery, band", [(5, "emergency"), (6, "dim"), (15, "dim"), (16, "normal")])
def test_battery_lighting_bands(battery, band):
    assert battery_lighting_band(battery) == band


def test_lighting_is_pulled_into_the_band_only_when_the_band_changes():
    power = default_station_power()
    power["battery_level"] = 4
    clamp_lighting_for_battery(power)
    assert power["system_levels"]["hallway_lighting"] == 2
    power["system_levels"]["hallway_lighting"] = 8
    clamp_lighting_for_battery(power)
    assert power["system_levels"]["hallway_lighting"] == 8
    power["battery_level"] = 12
    clamp_lighting_for_battery(power)
    assert power["system_levels"]["hallway_lighting"] == 5


def test_the_lighting_from_before_a_dim_follows_the_battery_bands_too():
    power = default_station_power()
    power["dimmed_from"] = 8
    clamp_lighting_for_battery(power)
    assert power["dimmed_from"] == 8
    power["battery_level"] = 12
    clamp_lighting_for_battery(power)
    assert power["dimmed_from"] == 5


def test_lighting_styles():
    assert "eerie red glow" in lighting_style(2)["light"]
    assert "dimmed" in lighting_style(5)["light"]
    assert lighting_style(7)["light"] == ""
    assert lighting_style(9)["light"].endswith("This hallway is very well lit.")
    assert lighting_style(10, place="room")["light"].endswith("This room is very well lit.")


@pytest.mark.parametrize("level, band", [(0, "outage"), (10, "critical"), (11, "low"), (50, "low"), (51, "normal")])
def test_battery_bands(level, band):
    assert battery_band(level) == band


def test_switched_off_systems_draw_no_power():
    assert calculate_discharge({"life_support": 0, "hallway_lighting": 10}, 60) == pytest.approx(0.3)


@pytest.mark.parametrize("seconds, shown", [(-5, "0s"), (59.9, "59s"), (61, "1m 1s"), (3725, "1h 2m 5s")])
def test_durations_read_largest_unit_first(seconds, shown):
    assert format_elapsed(seconds) == shown


def test_feedback_shows_until_its_time_is_up(monkeypatch):
    now = 1000.0
    monkeypatch.setattr(ui_panels.time, "time", lambda: now)
    state = {}
    assert current_feedback(state) is None
    set_feedback(state, "Bought 1 share.", seconds=3)
    assert current_feedback(state)["text"] == "Bought 1 share."
    now += 3
    assert current_feedback(state) is None
    assert "feedback" not in state


def test_feedback_without_a_time_limit_stays(monkeypatch):
    state = {}
    set_feedback(state, "Pick a seed.", seconds=None)
    monkeypatch.setattr(ui_panels.time, "time", lambda: 10 ** 12)
    assert current_feedback(state)["text"] == "Pick a seed."


def test_doors_lock_and_unlock_for_the_jobs_allowed_to():
    game = new_game("Medical", "Doctor")
    assert toggle_door_lock(game, MEDBAY_KEY)
    assert game.ship_map[MEDBAY_KEY]["locked"]
    assert toggle_door_lock(game, MEDBAY_KEY)
    assert not game.ship_map[MEDBAY_KEY]["locked"]
    assert [message for _, message, _ in game._messages] == ["The MedBay door has been locked.",
                                                                "The MedBay door has been unlocked."]


@pytest.mark.parametrize("door_key", [BRIDGE_KEY, "not-a-door"])
def test_other_doors_refuse(door_key):
    game = new_game("Medical", "Doctor")
    assert not toggle_door_lock(game, door_key)
    assert game._messages == [("Door Control", ACCESS_ERROR, "info")]


def test_fresh_air_does_no_breathing_damage():
    game = new_game()
    apply_oxygen_tick(game.player_data, game.station_crew, 600)
    assert {tuple(member["damage"].values()) for member in [game.player_data, *game.station_crew]} == {(0, 0, 0)}


@pytest.mark.parametrize("before, after", [(40, DOCTOR_REQUIRED_FLOOR), (DOCTOR_REQUIRED_FLOOR, DOCTOR_REQUIRED_FLOOR),
                                           (20, 0)])
def test_oxygen_recovers_by_itself_only_down_to_the_doctor_floor(before, after):
    game = new_game()
    for member in [game.player_data, *game.station_crew]:
        member["damage"]["oxygen"] = before
    apply_oxygen_tick(game.player_data, game.station_crew, RECOVERY_SECONDS_PER_PERCENT * 100)
    assert {member["damage"]["oxygen"] for member in [game.player_data, *game.station_crew]} == {after}



def test_no_crew_member_shares_the_players_name(monkeypatch):
    monkeypatch.setattr(character_creation.random, "choice", lambda names: names[0])
    player = new_shift(NPC_NAMES[0], "Staff Assistant")
    assert NPC_NAMES[0] not in [npc["name"] for npc in player["station_crew"]]
