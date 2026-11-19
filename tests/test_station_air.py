import copy
import time

import pytest
from flask import render_template

from helpers import (
    at_atmospherics_station,
    atmos,
    canister,
    crew,
    ctx,
    feedback,
    fill_air,
    give_tank,
    html,
    messages,
    new_game,
    notes,
    pda_messages,
    pure,
    select_item,
    stale_air,
    tank_item,
    tank_mix,
)
from space_online.game import main
from space_online.game.character_methods import character_creation
from space_online.game.helper_methods import antagonists, gas_mix
from space_online.game.helper_methods.antagonists import ACTS, CONTAMINATE_MOLES, OBJECTIVES, THREAT_TYPES
from space_online.game.helper_methods.atmos import connect
from space_online.game.helper_methods.crew_work import ATMOSPHERICS_WORK_SECONDS, CREW_WORK, tick_crew_work
from space_online.game.helper_methods.hazards import (
    HAZARD_DAMAGE,
    HAZARD_HURT_SECONDS,
    HAZARD_ROOM_KEYS,
    RICH_FIRE_DAMAGE,
    clear_hazard,
    hazard_rooms,
    set_hazard,
    tick_hazards,
)
from space_online.game.helper_methods.npc_movement import can_work, step_crew
from space_online.game.helper_methods.oxygen_helper import RECOVERY_SECONDS_PER_PERCENT, apply_oxygen_tick
from space_online.game.helper_methods.pda import tick_pda_needs
from space_online.game.helper_methods.station_air import (
    AIR_LASTS_SECONDS,
    AIR_MOLES,
    CLEAR_TEXT,
    DAZED_TEXT,
    FIRE_OXYGEN_RATE,
    FLASH_BURN,
    FULL_CREW,
    LONGEST_SHIFT_SECONDS,
    N2O_TIME_FACTOR,
    RESERVOIR_FILL,
    RESERVOIR_LOW,
    TANK_EMPTY_TEXT,
    TANK_FULL,
    TANK_LASTS_SECONDS,
    TANK_LOW_TEXT,
    UPKEEP_MOLES,
    VENT_SHARE,
    air_threat,
    breath_effects,
    contaminated,
    readings,
    reservoir_share,
    reservoir_tainted,
    tick_air,
    time_factor,
)
from space_online.game.helper_methods.station_status import collect_station_status
from space_online.game.maps.donut import ATMOSPHERICS_KEY, BAR_KEY, location_from_key
from space_online.game.objects.gases import (
    AIR,
    GAS_TANK,
    PLASMA_MAX,
    RESERVOIR,
    ROOM_TEMP,
    STANDARD_PRESSURE,
    STATION_AIR,
)

FRESH_AIR = f"{STANDARD_PRESSURE} kPa, {ROOM_TEMP} K: Oxygen 21.0%, Nitrogen 79.0%"


def shift_with_extras(monkeypatch, extras, department="Civilian", job="Staff Assistant"):
    monkeypatch.setattr(character_creation, "EXTRA_CREW_RANGE", (extras, extras))
    return new_game(department, job, extras=True)


def crew_of(game, size):
    """The game with `size` crew aboard, the player included: the crew cut down, or made up with Staff Assistants."""
    crew = game.player_data["station_crew"]
    spare = next(npc for npc in crew if npc["job"] == "Staff Assistant")
    del crew[size - 1:]
    while len(crew) < size - 1:
        extra = copy.deepcopy(spare)
        extra["name"] = f"Extra {len(crew)}"
        crew.append(extra)
    return game


def life_support(game, level):
    game.player_data["station_power"]["system_levels"]["life_support"] = level
    return game


def air(game):
    return atmos(game)["air"]


def reservoir(game):
    return atmos(game)["reservoir"]


def kpa(game, gas=None):
    return (gas_mix.partial_pressure(air(game), STATION_AIR["volume"], gas) if gas
            else gas_mix.pressure(air(game), STATION_AIR["volume"]))


def hurts(game):
    return breath_effects(air(game))["oxygen"] is not None


def run(game, seconds):
    """Run the air a second at a time. Returns the first second at which it hurt, or None."""
    first = None
    for second in range(1, seconds + 1):
        tick_air(game, 1)
        if first is None and hurts(game):
            first = second
    return first


def full_station(level):
    return life_support(crew_of(new_game(), FULL_CREW), level)


def fill_reservoir(game, fractions, moles=RESERVOIR_FILL):
    atmos(game)["reservoir"] = gas_mix.mix_of(fractions, moles, ROOM_TEMP)
    return game


# --- The tuning ----------------------------------------------------------------------------------------------------

def test_a_full_crew_is_the_largest_a_shift_has_and_the_smallest_is_two_short(monkeypatch):
    largest = character_creation.EXTRA_CREW_RANGE[1]
    smallest = character_creation.EXTRA_CREW_RANGE[0]
    assert len(shift_with_extras(monkeypatch, largest).station_crew) + 1 == FULL_CREW
    assert len(shift_with_extras(monkeypatch, smallest, "Civilian", "Chef").station_crew) + 1 == FULL_CREW - 2


def test_a_shift_starts_with_fresh_air_and_a_full_reservoir():
    game = new_game()
    assert gas_mix.readout(air(game), STATION_AIR["volume"]) == FRESH_AIR
    assert gas_mix.fractions(reservoir(game)) == pytest.approx(AIR)
    assert reservoir_share(reservoir(game)) == pytest.approx(1)
    assert atmos(game)["dazed"] is False


def test_a_quiet_station_at_level_10_stays_breathable_all_the_longest_shift_with_a_third_of_its_reservoir_left_over():
    game = full_station(10)
    assert run(game, LONGEST_SHIFT_SECONDS) is None
    assert reservoir_share(reservoir(game)) == pytest.approx(1 / 3, abs=0.01)


def test_at_level_5_the_air_holds_for_a_full_crew():
    game = full_station(5)
    assert run(game, LONGEST_SHIFT_SECONDS) is None


def test_at_level_4_the_air_thins_until_it_hurts_even_the_smallest_crew():
    game = life_support(crew_of(new_game(), FULL_CREW - 2), 4)
    assert run(game, 10 * 60) is not None
    assert 0 < breath_effects(air(game))["oxygen"] < 0.1


def test_with_life_support_off_a_full_crew_breathes_the_air_down_to_the_limit_in_two_minutes_and_not_before():
    game = full_station(0)
    assert run(game, AIR_LASTS_SECONDS - 1) is None
    assert run(game, 2) is not None
    assert reservoir_share(reservoir(game)) == pytest.approx(1)


def test_a_smaller_crew_makes_the_air_last_longer():
    game = life_support(crew_of(new_game(), FULL_CREW - 2), 0)
    assert run(game, AIR_LASTS_SECONDS + 5) is None


# --- The reservoir changes the air ---------------------------------------------------------------------------------

def test_a_reservoir_of_carbon_dioxide_suffocates_the_crew():
    game = fill_reservoir(full_station(10), {"Carbon Dioxide": 1})
    assert run(game, 120) is not None
    assert next(row for row in readings(air(game)) if row["name"] == "Carbon Dioxide")["past"]
    apply_oxygen_tick(game.player_data, game.station_crew, 60)
    assert {member["damage"]["oxygen"] > 0 for member in [game.player_data, *game.station_crew]} == {True}


def test_plasma_in_the_reservoir_poisons_everyone():
    game = fill_reservoir(full_station(10), {"Plasma": 0.2, "Oxygen": 0.21, "Nitrogen": 0.59})
    run(game, 300)
    effects = breath_effects(air(game))
    assert (effects["oxygen"], effects["poison"] > 0) == (None, True)
    apply_oxygen_tick(game.player_data, game.station_crew, 60)
    assert {(member["damage"]["poison"] > 0, member["damage"]["oxygen"])
            for member in [game.player_data, *game.station_crew]} == {(True, 0)}


def test_poison_damage_stops_at_the_top():
    game = fill_air(new_game(), {"Plasma": 0.5, "Oxygen": 0.5})
    game.player_data["damage"]["poison"] = 99
    apply_oxygen_tick(game.player_data, [], 600)
    assert game.player_data["damage"]["poison"] == 100


@pytest.mark.parametrize("fractions, recovered", [(AIR, 10), ({"Oxygen": 0.4, "Nitrogen": 0.6}, 20)])
def test_extra_oxygen_makes_oxygen_damage_wear_off_twice_as_fast(fractions, recovered):
    game = fill_air(new_game(), fractions)
    game.player_data["damage"]["oxygen"] = 20
    apply_oxygen_tick(game.player_data, [], 10 * RECOVERY_SECONDS_PER_PERCENT)
    assert game.player_data["damage"]["oxygen"] == 20 - recovered


def test_oxygen_damage_gets_worse_the_further_past_the_limit():
    thin = fill_air(new_game(), {"Oxygen": 0.15, "Nitrogen": 0.85})
    none = stale_air(new_game())
    for game in (thin, none):
        apply_oxygen_tick(game.player_data, [], 60)
    assert (thin.player_data["damage"]["oxygen"], none.player_data["damage"]["oxygen"]) == (16, 32)


# --- Hazards and the air -------------------------------------------------------------------------------------------

def test_an_open_breach_drains_the_reservoir_and_sealing_it_stops_that():
    quiet, breached = full_station(10), full_station(10)
    set_hazard(breached.player_data, BAR_KEY, "breach")
    for game in (quiet, breached):
        run(game, 600)
    quiet_loss = 1 - reservoir_share(reservoir(quiet))
    assert 1 - reservoir_share(reservoir(breached)) > 1.4 * quiet_loss
    assert not hurts(breached)

    clear_hazard(breached.player_data, BAR_KEY)
    before = reservoir_share(reservoir(breached))
    run(breached, 600)
    assert before - reservoir_share(reservoir(breached)) == pytest.approx(quiet_loss, rel=0.05)


def test_a_breach_with_life_support_low_thins_the_whole_station_out():
    game = full_station(1)
    set_hazard(game.player_data, BAR_KEY, "breach")
    run(game, 600)
    assert next(row for row in readings(air(game)) if row["name"] == "Pressure")["past"]


def test_a_fire_burns_the_stations_oxygen_into_carbon_dioxide():
    game = life_support(crew_of(new_game(), 1), 0)
    game.player_data["hands"]["left"] = tank_item(pure("Oxygen", 10), valve_open=True)
    set_hazard(game.player_data, BAR_KEY, "fire")
    oxygen = air(game)["moles"]["Oxygen"]
    tick_air(game, 10)
    assert air(game)["moles"]["Oxygen"] == pytest.approx(oxygen - 10 * FIRE_OXYGEN_RATE)
    assert air(game)["moles"]["Carbon Dioxide"] == pytest.approx(10 * FIRE_OXYGEN_RATE)


@pytest.mark.parametrize("fractions, damage", [(AIR, HAZARD_DAMAGE), ({"Oxygen": 0.4, "Nitrogen": 0.6}, RICH_FIRE_DAMAGE)])
def test_a_fire_burns_hotter_in_oxygen_rich_air(fractions, damage):
    game = fill_air(new_game(), fractions)
    set_hazard(game.player_data, BAR_KEY, "fire")
    game.player_data["location"] = location_from_key(BAR_KEY)
    tick_hazards(game, HAZARD_HURT_SECONDS)
    assert game.player_data["damage"]["burn"] == damage


def test_rich_air_makes_no_difference_to_a_breach():
    game = fill_air(new_game(), {"Oxygen": 0.4, "Nitrogen": 0.6})
    set_hazard(game.player_data, BAR_KEY, "breach")
    game.player_data["location"] = location_from_key(BAR_KEY)
    tick_hazards(game, HAZARD_HURT_SECONDS)
    assert game.player_data["damage"]["oxygen"] == HAZARD_DAMAGE


@pytest.mark.parametrize("spark", ["fire", "wiring"])
def test_fuel_in_the_air_flashes_on_a_spark_burning_everyone_and_starting_a_fire(spark):
    game = fill_air(new_game(), {"Plasma": 0.02, "Oxygen": 0.2, "Nitrogen": 0.78})
    set_hazard(game.player_data, BAR_KEY, spark)
    tick_air(game, 1)
    assert "Plasma" not in air(game)["moles"]
    assert {member["damage"]["burn"] for member in [game.player_data, *game.station_crew]} == {FLASH_BURN}
    assert messages(game)[0] == ("Station Air", "The fuel in the station's air catches a spark and flashes into flame. "
                                                f"Everyone is burned. Burn damage: {FLASH_BURN}%.")
    assert sorted(kind for _, kind in hazard_rooms(game.player_data)) == sorted([spark, "fire"])


def test_a_flash_with_every_room_already_in_trouble_starts_no_new_fire():
    game = fill_air(new_game(), {"Plasma": 0.02, "Oxygen": 0.2, "Nitrogen": 0.78})
    for key in HAZARD_ROOM_KEYS:
        set_hazard(game.player_data, key, "wiring")
    game.player_data["damage"]["burn"] = 95
    tick_air(game, 1)
    assert game.player_data["damage"]["burn"] == 100
    assert {kind for _, kind in hazard_rooms(game.player_data)} == {"wiring"}


@pytest.mark.parametrize("fractions, hazard", [
    ({"Plasma": 0.005, "Oxygen": 0.2, "Nitrogen": 0.795}, "fire"),
    ({"Plasma": 0.02, "Oxygen": 0.2, "Nitrogen": 0.78}, "breach"),
])
def test_too_little_fuel_or_no_spark_and_nothing_flashes(fractions, hazard):
    game = fill_air(new_game(), fractions)
    set_hazard(game.player_data, BAR_KEY, hazard)
    tick_air(game, 1)
    assert "Plasma" in air(game)["moles"] and game.player_data["damage"]["burn"] == 0


# --- Venting -------------------------------------------------------------------------------------------------------

def test_venting_the_station_asks_first_then_clears_a_contaminant():
    game = fill_air(at_atmospherics_station("air_monitor"), {"Plasma": 0.1, "Oxygen": 0.21, "Nitrogen": 0.69})
    game.perform("panel.vent", {})
    choice = game.view()["choice"]
    assert (choice["title"], choice["buttons"]) == ("Vent the Station", ["Vent It", "Leave It"])
    game.perform("game.choose", {"id": choice["id"], "index": 1})
    assert kpa(game, "Plasma") == pytest.approx(0.1 * STANDARD_PRESSURE)

    game.perform("panel.vent", {})
    game.perform("game.choose", {"id": game.view()["choice"]["id"], "index": 0})
    assert kpa(game, "Plasma") == pytest.approx((1 - VENT_SHARE) * 0.1 * STANDARD_PRESSURE)
    assert messages(game)[-1] == ("Air Monitor", "You vent the station's air to space. The pump starts refilling it "
                                                 "from the reservoir.")
    assert notes(game)[-1] == "Vented the station's air to space."
    run(game, 120)
    assert not contaminated(air(game))
    assert gas_mix.pressure(air(game), STATION_AIR["volume"]) == pytest.approx(STANDARD_PRESSURE)


# --- The Air Monitor and the Reservoir -----------------------------------------------------------------------------

def test_the_air_monitor_reads_the_air_against_every_limit():
    game = fill_air(at_atmospherics_station("air_monitor"), {"Oxygen": 0.4, "Nitrogen": 0.55, "Carbon Dioxide": 0.05})
    life_support(game, 6)
    view = ctx(game)
    assert view["gauge"] == gas_mix.readout(air(game), STATION_AIR["volume"])
    assert [(row["name"], row["status"][0]) for row in view["limits"]] == [
        ("Oxygen", "OK"), ("Carbon Dioxide", "OK"), ("Pressure", "OK"), ("Plasma", "OK"), ("Oxygen-rich", "Rich"),
        ("Nitrous Oxide", "OK")]
    assert view["level"] == 6 and view["pump_rate"] > 0

    fill_air(game, {"Nitrogen": 0.6, "Carbon Dioxide": 0.4})
    assert [row["status"][0] for row in ctx(game)["limits"]][:2] == ["Low", "Dangerous"]


def test_the_reservoir_panel_reads_the_reservoir_and_the_canister_on_its_port():
    game = at_atmospherics_station("reservoir")
    view = ctx(game)
    assert view["gauge"] == gas_mix.readout(reservoir(game), RESERVOIR["volume"])
    assert (round(view["fill"]), view["rated"], view["port"]) == (100, RESERVOIR["rated"], None)
    game.perform("panel.pump_in", {})
    assert feedback(game) == "Connect a canister to the Reservoir Port at the Canister Rack first."
    game.perform("panel.draw_off", {})
    assert feedback(game) == "Connect a canister to the Reservoir Port at the Canister Rack first."
    connect(atmos(game), canister(game, 2), "reservoir")
    assert ctx(game)["port"]["label"] == "Canister 3"


def test_pumping_in_moves_gas_from_the_canister_into_the_reservoir_up_to_its_rating():
    game = at_atmospherics_station("reservoir")
    oxygen = canister(game, 2)
    connect(atmos(game), oxygen, "reservoir")
    game.perform("panel.set_amount", {"value": 1000})
    game.perform("panel.pump_in", {})
    assert feedback(game) == "Pumped 1000 mol from Canister 3 into the life support reservoir."
    assert gas_mix.total_moles(reservoir(game)) == pytest.approx(RESERVOIR_FILL + 1000)
    assert reservoir(game)["moles"]["Oxygen"] == pytest.approx(0.21 * RESERVOIR_FILL + 1000)

    full = gas_mix.moles_at(RESERVOIR["rated"], RESERVOIR["volume"], ROOM_TEMP)
    atmos(game)["reservoir"] = gas_mix.mix_of(AIR, full - 10, ROOM_TEMP)
    game.perform("panel.pump_in", {})
    assert feedback(game) == f"That would take the reservoir past its rated {RESERVOIR['rated']} kPa."
    assert gas_mix.total_moles(reservoir(game)) == pytest.approx(full - 10)


def test_drawing_off_moves_reservoir_gas_into_the_canister_which_can_rupture():
    game = at_atmospherics_station("reservoir")
    empty = canister(game, 5)
    connect(atmos(game), empty, "reservoir")
    game.perform("panel.set_amount", {"value": 500})
    game.perform("panel.draw_off", {})
    assert gas_mix.total_moles(empty["mix"]) == pytest.approx(500)
    assert gas_mix.total_moles(reservoir(game)) == pytest.approx(RESERVOIR_FILL - 500)
    assert feedback(game) == "Drew 500 mol off the life support reservoir into Canister 6."

    game.perform("panel.set_amount", {"value": 5000})
    game.perform("panel.draw_off", {})
    assert atmos(game)["canisters"][5]["mix"] == gas_mix.empty_mix()
    assert gas_mix.total_moles(reservoir(game)) == pytest.approx(RESERVOIR_FILL - 5500)


# --- Breathing from a Gas Tank -------------------------------------------------------------------------------------

def tank_kpa(tank):
    return gas_mix.pressure(tank["attributes"]["contents"], GAS_TANK["volume"])


def test_the_tank_valve_opens_and_closes_from_the_item_menu():
    game = new_game()
    index = give_tank(game, tank_mix("Oxygen"))
    select_item(game, index)
    game.perform("panel.actions", {})
    assert [action["label"] for action in ctx(game)["actions"]] == ["Equip", "Open Valve", "Drop"]
    game.perform("panel.item_action", {"name": "open_valve"})
    tank = game.player_data["inventory"][index]
    assert tank["attributes"]["valve_open"] is True
    assert messages(game)[-1] == ("Gas Tank", "You open the tank's valve. Hold it in a hand to breathe from it.")
    game.perform("panel.actions", {})
    assert [action["name"] for action in ctx(game)["actions"]] == ["equip", "close_valve", "drop"]
    game.perform("panel.item_action", {"name": "close_valve"})
    assert tank["attributes"]["valve_open"] is False
    assert messages(game)[-1] == ("Gas Tank", "You close the tank's valve.")


def test_with_life_support_off_an_open_oxygen_tank_in_hand_keeps_you_breathing_until_it_runs_dry():
    game = life_support(stale_air(new_game()), 0)
    tank = tank_item(tank_mix("Oxygen"), valve_open=True)
    game.player_data["hands"]["right"] = tank
    for _ in range(TANK_LASTS_SECONDS - 1):
        apply_oxygen_tick(game.player_data, game.station_crew, 1)
        tick_air(game, 1)
    assert game.player_data["damage"]["oxygen"] == 0
    assert game.station_crew[0]["damage"]["oxygen"] > 0
    assert tank_kpa(tank) > 0
    assert messages(game) == [("Gas Tank", TANK_LOW_TEXT)]

    tick_air(game, 2)
    assert (tank_kpa(tank), messages(game)[-1]) == (0, ("Gas Tank", TANK_EMPTY_TEXT))
    apply_oxygen_tick(game.player_data, game.station_crew, 60)
    assert game.player_data["damage"]["oxygen"] > 0


@pytest.mark.parametrize("where, valve_open", [("hand", False), ("inventory", True)])
def test_a_closed_tank_or_one_in_the_inventory_does_nothing(where, valve_open):
    game = life_support(stale_air(new_game()), 0)
    tank = tank_item(tank_mix("Oxygen"), valve_open=valve_open)
    if where == "hand":
        game.player_data["hands"]["left"] = tank
    else:
        game.player_data["inventory"].append(tank)
    tick_air(game, 60)
    apply_oxygen_tick(game.player_data, game.station_crew, 60)
    assert tank_kpa(tank) == pytest.approx(GAS_TANK["rated"])
    assert game.player_data["damage"]["oxygen"] > 0


def test_a_plasma_tank_poisons_whoever_breathes_it():
    game = new_game()
    game.player_data["hands"]["left"] = tank_item(tank_mix("Plasma"), valve_open=True)
    apply_oxygen_tick(game.player_data, game.station_crew, 60)
    assert (game.player_data["damage"]["poison"] > 0, game.player_data["damage"]["oxygen"] > 0) == (True, True)
    assert game.station_crew[0]["damage"] == {"burn": 0, "poison": 0, "oxygen": 0}


def test_an_emptied_tank_can_be_refilled_at_the_canister_rack():
    game = at_atmospherics_station("canister_rack")
    index = give_tank(game, gas_mix.empty_mix())
    game.perform("panel.select_canister", {"index": 2})
    game.perform("panel.select_tank", {"index": index})
    game.perform("panel.set_tank_amount", {"value": int(TANK_FULL)})
    game.perform("panel.fill_tank", {})
    assert tank_kpa(game.player_data["inventory"][index]) == pytest.approx(GAS_TANK["rated"], rel=0.05)


def test_the_character_sheet_says_when_you_breathe_from_a_tank():
    game = new_game()
    game.open_panel("character_sheet")
    assert ctx(game)["tank_kpa"] is None
    game.player_data["hands"]["left"] = tank_item(tank_mix("Oxygen"), valve_open=True)
    assert ctx(game)["tank_kpa"] == pytest.approx(GAS_TANK["rated"])


# --- Nitrous Oxide -------------------------------------------------------------------------------------------------

LAUGHING_AIR = {"Nitrous Oxide": 0.1, "Oxygen": 0.21, "Nitrogen": 0.69}


def test_breathing_nitrous_oxide_makes_you_lose_time_and_says_so_once_when_it_starts_and_stops():
    game = new_game()
    assert time_factor(game) == 1
    fill_air(game, LAUGHING_AIR)
    assert (time_factor(game), time_factor(game)) == (N2O_TIME_FACTOR, N2O_TIME_FACTOR)
    fill_air(game, AIR)
    assert time_factor(game) == 1
    assert messages(game) == [("Nitrous Oxide", DAZED_TEXT), ("Nitrous Oxide", CLEAR_TEXT)]


def test_a_tank_of_nitrous_oxide_does_it_too():
    game = new_game()
    game.player_data["hands"]["left"] = tank_item(tank_mix("Nitrous Oxide"), valve_open=True)
    assert time_factor(game) == N2O_TIME_FACTOR


def test_while_you_lose_time_the_whole_station_runs_on_ahead(monkeypatch):
    game = fill_air(new_game(), LAUGHING_AIR)
    deltas = []
    monkeypatch.setattr(main, "tick_needs", lambda game, delta_seconds: deltas.append(delta_seconds))
    game.player_data["game_clock"]["last_real_time"] = time.time() - 2
    game.tick()
    elapsed = game.player_data["game_clock"]["elapsed_seconds"]
    assert elapsed == pytest.approx(2 * N2O_TIME_FACTOR, abs=0.5)
    assert deltas == [pytest.approx(elapsed)]


def test_the_crew_walk_the_factors_worth_of_steps(monkeypatch):
    game = new_game()
    steps = []
    monkeypatch.setattr(main, "step_crew", lambda game: steps.append("crew"))
    monkeypatch.setattr(main, "step_threats", lambda game: steps.append("threats"))
    game._tick_npc_move(N2O_TIME_FACTOR)
    assert steps == ["crew", "threats"] * N2O_TIME_FACTOR


def test_npc_crew_fall_asleep_in_nitrous_oxide_and_wake_when_it_clears():
    game = fill_air(new_game(), LAUGHING_AIR)
    npc = game.station_crew[0]
    location = dict(npc["location"])
    tick_air(game, 1)
    assert (npc["asleep"], can_work(npc)) == (True, False)
    npc["npc_goal"] = "stroll"
    step_crew(game)
    assert npc["location"] == location
    fill_air(game, AIR)
    tick_air(game, 1)
    assert (npc["asleep"], can_work(npc)) == (False, True)


# --- The Scientist on post -----------------------------------------------------------------------------------------

def atmospherics_turn(game):
    game.player_data["crew_work"] = {room_key: 10 ** 9 for _, room_key in CREW_WORK if room_key != ATMOSPHERICS_KEY}
    game.player_data["game_clock"]["elapsed_seconds"] = ATMOSPHERICS_WORK_SECONDS
    tick_crew_work(game)
    return game


def test_the_scientist_tops_up_a_low_reservoir():
    game = fill_reservoir(new_game(), AIR, RESERVOIR_FILL * RESERVOIR_LOW * 0.9)
    atmospherics_turn(game)
    assert gas_mix.total_moles(reservoir(game)) == pytest.approx(RESERVOIR_FILL * RESERVOIR_LOW * 0.9 + UPKEEP_MOLES)
    assert notes(game)[-1].endswith("tops up the life support reservoir with fresh air.")


def test_the_scientist_flushes_a_tainted_reservoir_before_venting_the_air_it_spoiled():
    game = fill_reservoir(new_game(), {"Plasma": 0.2, "Oxygen": 0.2, "Nitrogen": 0.6})
    fill_air(game, {"Plasma": 0.2, "Oxygen": 0.2, "Nitrogen": 0.6})
    atmospherics_turn(game)
    assert gas_mix.fractions(reservoir(game))["Plasma"] == pytest.approx(0.1)
    assert kpa(game, "Plasma") == pytest.approx(0.2 * STANDARD_PRESSURE)
    assert notes(game)[-1].endswith("flushes the life support reservoir and refills it with fresh air.")


def test_the_scientist_vents_contaminated_air_once_the_reservoir_is_clean():
    game = fill_air(new_game(), {"Carbon Dioxide": 0.2, "Oxygen": 0.2, "Nitrogen": 0.6})
    atmospherics_turn(game)
    assert kpa(game, "Carbon Dioxide") == pytest.approx((1 - VENT_SHARE) * 0.2 * STANDARD_PRESSURE)
    assert notes(game)[-1].endswith("vents the station's air to clear it.")


def test_the_scientist_leaves_a_healthy_station_alone():
    game = atmospherics_turn(fill_air(new_game(), {"Oxygen": 0.4, "Nitrogen": 0.6}))
    assert reservoir_share(reservoir(game)) == pytest.approx(1)
    assert notes(game) == []


def test_nobody_tends_the_air_for_a_scientist_posted_to_atmospherics():
    game = new_game("Science", "Scientist", post=ATMOSPHERICS_KEY)
    fill_reservoir(game, AIR, RESERVOIR_FILL * 0.1)
    atmospherics_turn(game)
    assert reservoir_share(reservoir(game)) == pytest.approx(0.1)


def test_a_tainted_reservoir_is_one_with_more_than_a_trace_of_anything_but_air():
    assert not reservoir_tainted(gas_mix.mix_of({"Oxygen": 0.5, "Nitrogen": 0.5}, 100, ROOM_TEMP))
    assert not reservoir_tainted(gas_mix.mix_of({"Plasma": 0.004, "Nitrogen": 0.996}, 100, ROOM_TEMP))
    assert reservoir_tainted(gas_mix.mix_of({"Plasma": 0.01, "Nitrogen": 0.99}, 100, ROOM_TEMP))


def test_only_a_gas_that_isnt_part_of_air_contaminates_it():
    assert not contaminated(gas_mix.mix_of({"Oxygen": 0.5, "Nitrogen": 0.5}, AIR_MOLES, ROOM_TEMP))
    assert not contaminated(gas_mix.mix_of({"Nitrogen": 1}, AIR_MOLES, ROOM_TEMP))
    assert contaminated(gas_mix.mix_of({"Nitrous Oxide": 0.1, "Nitrogen": 0.9}, AIR_MOLES, ROOM_TEMP))


# --- The Traitor ---------------------------------------------------------------------------------------------------

def traitor_in(game, job):
    return {"type": "Traitor", "crew_name": crew(game, job)["name"], "revealed": False}


def test_the_traitor_can_contaminate_the_reservoir_and_it_counts_as_sabotage():
    assert "contaminate" in THREAT_TYPES["Traitor"]["acts"]
    assert "contaminate" in OBJECTIVES["sabotage"]["acts"]
    assert "contaminate" not in THREAT_TYPES["Rogue Bot"]["acts"]


@pytest.mark.parametrize("gas", antagonists.CONTAMINANTS)
def test_a_traitor_who_can_work_atmospherics_pumps_a_contaminant_into_the_reservoir(monkeypatch, gas):
    game = new_game()
    monkeypatch.setattr(antagonists.random, "choice", lambda options: gas)
    assert ACTS["contaminate"](game, traitor_in(game, "Scientist")) == (
        "Someone has tampered with the life support reservoir.", "Atmospherics")
    assert reservoir(game)["moles"][gas] == pytest.approx(CONTAMINATE_MOLES)
    assert reservoir_tainted(reservoir(game))


def test_a_traitor_without_access_or_out_in_the_open_cannot():
    game = new_game()
    assert ACTS["contaminate"](game, traitor_in(game, "Chef")) is None
    assert ACTS["contaminate"](game, {**traitor_in(game, "Scientist"), "revealed": True}) is None
    assert not reservoir_tainted(reservoir(game))


# --- Station Status and the PDA ------------------------------------------------------------------------------------

def test_station_status_reads_the_air_and_the_reservoir():
    game = fill_reservoir(new_game(), AIR, RESERVOIR_FILL / 2)
    air_line = collect_station_status(game.player_data, game.station_crew)["power"]["air"]
    assert air_line == {"oxygen": pytest.approx(21), "pressure": pytest.approx(STANDARD_PRESSURE),
                        "reservoir": pytest.approx(50)}


@pytest.mark.parametrize("fractions, threat", [
    (AIR, "safe"),
    ({"Oxygen": 0.15, "Nitrogen": 0.85}, "damaging"),
    ({"Oxygen": 0.21, "Plasma": PLASMA_MAX * 8 / STANDARD_PRESSURE, "Nitrogen": 0.7}, "emergency"),
    ({"Nitrogen": 1}, "emergency"),
])
def test_how_bad_the_air_is(fractions, threat):
    assert air_threat(gas_mix.mix_of(fractions, AIR_MOLES, ROOM_TEMP)) == threat


AIR_NEEDS = [
    (lambda game: fill_air(game, {"Oxygen": 0.1, "Nitrogen": 0.9}),
     [("Atmospherics", "The station air is low on Oxygen.")]),
    (lambda game: fill_air(game, {"Plasma": 0.05, "Oxygen": 0.21, "Nitrogen": 0.74}),
     [("Atmospherics", "The station air is contaminated.")]),
    (lambda game: fill_reservoir(game, AIR, RESERVOIR_FILL * RESERVOIR_LOW / 2),
     [("Atmospherics", "The life support reservoir is nearly empty.")]),
]


@pytest.mark.parametrize("department, job, post", [("Science", "Scientist", ATMOSPHERICS_KEY),
                                                   ("Engineering", "Engineer", None)])
@pytest.mark.parametrize("trouble, expected", AIR_NEEDS)
def test_the_atmospherics_scientist_and_the_engineer_hear_when_the_air_needs_them(department, job, post, trouble,
                                                                                  expected):
    game = new_game(department, job, post=post)
    tick_pda_needs(game)
    trouble(game)
    tick_pda_needs(game)
    assert [line for line in pda_messages(game) if line[0] == "Atmospherics"] == expected


def test_scientists_in_the_other_labs_hear_nothing_about_the_air():
    game = stale_air(new_game("Science", "Scientist", post=next(
        room_key for job, room_key in CREW_WORK if job == "Scientist" and room_key != ATMOSPHERICS_KEY)))
    tick_pda_needs(game)
    assert pda_messages(game) == []


def test_station_status_shows_the_air_on_the_page(app):
    game = new_game()
    view = collect_station_status(game.player_data, game.station_crew)
    with app.test_request_context():
        page = render_template("panels/station_status.html", p=view)
    assert "Air: 21% Oxygen at 101.3 kPa" in page and "Reservoir: 100%" in page


def test_the_reservoir_and_air_monitor_panels_render(app):
    game = at_atmospherics_station("reservoir")
    page = html(app, game)
    assert "<h2>Reservoir</h2>" in page and "100% full" in page and "Nothing is connected." in page
    connect(atmos(game), canister(game, 0), "reservoir")
    assert "Canister 1: " in html(app, game)

    game.ui["panels"] = []
    game.perform("room.show_air_monitor", {})
    page = html(app, game)
    for text in ("<h2>Air Monitor</h2>", FRESH_AIR, "Carbon Dioxide", "Level 10.", "Vent the Station",
                 f"Dumps {VENT_SHARE:.0%} of the station's air"):
        assert text in page, text


def test_the_character_sheet_shows_the_tank_on_the_page(app):
    game = new_game()
    game.player_data["hands"]["left"] = tank_item(tank_mix("Oxygen"), valve_open=True)
    game.open_panel("character_sheet")
    assert f"Breathing from: Gas Tank ({GAS_TANK['rated']} kPa)" in html(app, game)
