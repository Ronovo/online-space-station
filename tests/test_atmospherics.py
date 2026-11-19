import copy
import time

import pytest

from helpers import (
    at_atmospherics_station,
    atmos,
    canister,
    ctx,
    feedback,
    fill_air,
    give,
    give_tank,
    html,
    in_atmospherics,
    item_action,
    labels,
    messages,
    new_game,
    pure,
    select_item,
    tank_item,
)
from space_online.game.helper_methods import gas_mix, random_events
from space_online.game.helper_methods.atmos import (
    BURN_OVER_JOULES,
    CANISTER_FILL,
    CANISTER_SLOTS,
    CHAMBER,
    DISPENSER_STOCK,
    HEATER_RANGE,
    HEATER_WATTS,
    REQUEST_PRESSURE,
    RUPTURE_DAMAGE,
    move_canister,
    new_atmos,
    port_canister,
    tank_holds,
    tick_atmos,
)
from space_online.game.helper_methods.pda import JOB_GUIDES
from space_online.game.helper_methods.random_events import build_job_event
from space_online.game.maps.donut import ATMOSPHERICS_KEY, MEDBAY_KEY, location_from_key
from space_online.game.objects.gases import AIR, CANISTER, DANGEROUS_GASES, GAS_TANK, ROOM_TEMP, STANDARD_PRESSURE
from space_online.game.objects.items import get_item_definition, tank_readout
from space_online.game.special_rooms.atmospherics import DISPENSE_MAX, TANK_FILL_MAX


def kpa(mix, volume=CANISTER["volume"]):
    return gas_mix.pressure(mix, volume)


def fuel_and_oxygen(fuel_moles, temp=ROOM_TEMP, fuel="Plasma"):
    """Fuel and Oxygen in the clean 2 to 3 burn ratio."""
    return gas_mix.mix_of({fuel: 0.4, "Oxygen": 0.6}, fuel_moles / 0.4, temp)


def limb_total(game):
    return sum(game.player_data["limbs"].values())


def hazard(game):
    return game.player_data["ship_map"][ATMOSPHERICS_KEY]["hazard"]


# --- The room ------------------------------------------------------------------------------------------------------

def test_atmospherics_is_the_north_door_of_the_science_hall():
    game = new_game("Science", "Scientist", post=ATMOSPHERICS_KEY)
    game.player_data["location"] = {"x": 3, "y": 6}
    assert game.view()["screen"]["grid"][0][1]["label"] == "Atmospherics"
    game.perform("game.enter_room", {"room_key": ATMOSPHERICS_KEY})
    assert game.current_room_name() == "Atmospherics"
    assert game.view()["screen"]["heading"] == "Atmospherics"


@pytest.mark.parametrize("department, job", [("Science", "Scientist"), ("Administration", "Captain"),
                                             ("Administration", "Head of Personnel")])
def test_scientists_the_captain_and_the_head_of_personnel_work_the_station(department, job):
    game = in_atmospherics(department, job)
    assert "Enter Atmospherics Station" in labels(game)
    game.perform("room.open_station", {"mode": "atmospherics_station"})
    assert labels(game) == ["Atmospherics Station Controls", "Canister Rack", "Gas Dispenser", "Combustion Chamber",
                            "Reservoir", "Air Monitor", "Tank Rack", "Test Range", "Back to Station Menu"]


def test_a_staff_assistant_only_gets_the_room_options_and_can_talk_to_the_scientist():
    game = in_atmospherics("Civilian", "Staff Assistant")
    assert "Enter Atmospherics Station" not in labels(game)
    game.ui["room_mode"] = "atmospherics_station"
    assert "Canister Rack" not in labels(game)
    game.perform("room.show_canister_rack", {})
    assert game.ui["panels"] == []
    assert "Talk to Scientist" in labels(game)
    game.perform("room.talk_to_scientist", {})
    assert messages(game)[-1][0] == "Scientist"


def test_a_scientist_posted_here_has_nobody_to_talk_to_and_is_the_post_holder():
    game = in_atmospherics()
    assert "Talk to Scientist" not in labels(game)
    game.perform("room.talk_to_scientist", {})
    assert messages(game) == []


def test_every_shift_gets_a_scientist_in_atmospherics_unless_the_player_is_posted_there():
    game = new_game("Civilian", "Staff Assistant")
    posted = [npc for npc in game.station_crew if npc["post_key"] == ATMOSPHERICS_KEY]
    assert [npc["job"] for npc in posted] == ["Scientist"]
    assert not any(npc["post_key"] == ATMOSPHERICS_KEY for npc in in_atmospherics().station_crew)


def test_the_tank_rack_hands_out_an_empty_tank_and_an_analyzer_once_and_the_shifts_valve():
    game = at_atmospherics_station()
    game.perform("room.take_tanks", {})
    assert [item["id"] for item in game.player_data["inventory"]] == ["gas_tank", "gas_analyzer", "transfer_valve"]
    assert gas_mix.total_moles(game.player_data["inventory"][0]["attributes"]["contents"]) == 0
    game.perform("room.take_tanks", {})
    assert len(game.player_data["inventory"]) == 3
    assert messages(game)[-1] == ("Tank Rack", "You already have a Gas Tank and a Gas Analyzer.")


# --- Starting state and the canister tube -------------------------------------------------------------------------

def test_a_shift_starts_with_six_canisters_and_a_stock_of_each_dangerous_gas():
    state = new_game().player_data["atmos"]
    canisters = state["canisters"]
    assert len(canisters) == CANISTER_SLOTS == 6
    assert [slot["label"] for slot in canisters] == [f"Canister {number}" for number in range(1, 7)]
    assert [gas_mix.fractions(slot["mix"]) for slot in canisters] == [
        pytest.approx(AIR), pytest.approx(AIR), {"Oxygen": 1}, {"Nitrogen": 1}, {"Plasma": 1}, {}]
    for slot in canisters[:5]:
        assert (kpa(slot["mix"]), slot["mix"]["temp"]) == (pytest.approx(CANISTER_FILL), ROOM_TEMP)
    assert all(slot["port"] is None and not slot["thermo"]["on"] for slot in canisters)
    assert state["stock"] == {gas: DISPENSER_STOCK for gas in DANGEROUS_GASES}
    assert (gas_mix.total_moles(state["chamber"]["mix"]), state["chamber"]["lit"]) == (0, False)


def test_the_tube_moves_a_canister_into_the_first_free_slot_with_its_heater_off():
    rack = new_atmos()["canisters"]
    bay = [None, None]
    sent = rack[2]
    sent["thermo"]["on"] = True
    assert move_canister(rack, 2, bay) == 0
    assert (rack[2], bay[0], sent["thermo"]["on"]) == (None, sent, False)
    assert move_canister(bay, 0, rack) == 2
    assert rack[2] is sent


def test_the_tube_refuses_an_empty_slot_a_connected_canister_and_a_full_end():
    rack = new_atmos()["canisters"]
    assert move_canister(rack, 0, rack) is None
    rack[0]["port"] = "chamber"
    assert move_canister(rack, 0, [None]) is None
    assert move_canister([None], 0, [None]) is None
    assert rack[0]["port"] == "chamber"


# --- Canister Rack -----------------------------------------------------------------------------------------------

def test_the_rack_lists_every_slot_and_reads_the_selected_canisters_gauge():
    game = at_atmospherics_station("canister_rack")
    atmos(game)["canisters"][5] = None
    context = ctx(game)
    assert [slot["label"] for slot in context["slots"]][-2:] == ["Canister 5", "Slot 6: empty"]
    assert (context["canister"], context["selected"]) == (None, None)
    game.perform("panel.select_canister", {"index": 5})
    assert ctx(game)["selected"] is None
    game.perform("panel.select_canister", {"index": 2})
    context = ctx(game)
    assert context["canister"]["gauge"] == gas_mix.readout(canister(game, 2)["mix"], CANISTER["volume"])
    assert context["max_amount"] == int(gas_mix.total_moles(canister(game, 2)["mix"]))
    assert [row["index"] for row in context["targets"]] == [0, 1, 3, 4]


def test_actions_on_the_rack_need_a_canister_picked_first():
    game = at_atmospherics_station("canister_rack")
    for action in ("transfer", "fill_tank", "empty_tank", "vent_canister", "toggle_heater"):
        game.perform(f"panel.{action}", {})
        assert feedback(game) == "Pick a canister on the rack first.", action
    game.perform("panel.set_port", {"port": "chamber"})
    game.perform("panel.set_heater_target", {"value": "500"})
    assert port_canister(atmos(game), "chamber") is None


def test_transfer_moves_the_amount_between_canisters():
    game = at_atmospherics_station("canister_rack")
    game.perform("panel.select_canister", {"index": 2})
    game.perform("panel.transfer", {})
    assert feedback(game) == "Pick a canister to transfer into."
    game.perform("panel.set_target", {"index": 5})
    game.perform("panel.set_amount", {"value": "100"})
    before = gas_mix.total_moles(canister(game, 2)["mix"])
    game.perform("panel.transfer", {})
    assert gas_mix.total_moles(canister(game, 2)["mix"]) == pytest.approx(before - 100)
    assert canister(game, 5)["mix"]["moles"] == {"Oxygen": pytest.approx(100)}
    assert canister(game, 5)["mix"]["temp"] == ROOM_TEMP
    assert feedback(game) == "Moved 100 mol from Canister 3 to Canister 6."


def test_the_amount_slider_stays_within_what_the_canister_holds():
    game = at_atmospherics_station("canister_rack")
    game.perform("panel.select_canister", {"index": 5})
    game.perform("panel.set_amount", {"value": "-5"})
    assert ctx(game)["amount"] == 0
    game.perform("panel.set_amount", {"value": "50"})
    assert (ctx(game)["amount"], ctx(game)["max_amount"]) == (0, 0)


def test_a_canister_pushed_past_its_rating_ruptures_into_a_breach_and_hurts_whoever_is_in_the_room():
    game = at_atmospherics_station("canister_rack")
    canister(game, 1)["mix"] = pure("Nitrogen", gas_mix.moles_at(8900, CANISTER["volume"], ROOM_TEMP))
    game.perform("panel.select_canister", {"index": 0})
    game.perform("panel.set_target", {"index": 1})
    game.perform("panel.set_amount", {"value": "500"})
    unhurt = limb_total(game)
    game.perform("panel.transfer", {})
    assert gas_mix.total_moles(canister(game, 1)["mix"]) == 0
    assert hazard(game) == "breach"
    assert limb_total(game) == unhurt - RUPTURE_DAMAGE
    title, message = messages(game)[0]
    assert title == "Atmospherics" and message.startswith("Canister 2 ruptures with a bang at ")
    assert message.endswith(f"%.") and "The blast catches your" in message


def test_a_canister_of_fuel_and_oxidizer_ruptures_into_a_fire():
    game = at_atmospherics_station("canister_rack")
    canister(game, 1)["mix"] = fuel_and_oxygen(gas_mix.moles_at(4000, CANISTER["volume"], ROOM_TEMP))
    game.perform("panel.select_canister", {"index": 0})
    game.perform("panel.set_target", {"index": 1})
    game.perform("panel.set_amount", {"value": "1800"})
    game.perform("panel.transfer", {})
    assert hazard(game) == "fire"


def test_venting_empties_the_canister():
    game = at_atmospherics_station("canister_rack")
    game.perform("panel.select_canister", {"index": 4})
    game.perform("panel.vent_canister", {})
    assert gas_mix.total_moles(canister(game, 4)["mix"]) == 0
    assert feedback(game) == "Canister 5 hisses empty into space."


def test_one_canister_at_a_time_connects_to_the_chamber_inlet():
    game = at_atmospherics_station("canister_rack")
    game.perform("panel.select_canister", {"index": 2})
    game.perform("panel.set_port", {"port": "chamber"})
    assert feedback(game) == "Canister 3 is connected to the Combustion Chamber Inlet."
    game.perform("panel.select_canister", {"index": 4})
    game.perform("panel.set_port", {"port": "chamber"})
    assert (canister(game, 2)["port"], port_canister(atmos(game), "chamber")) == (None, canister(game, 4))
    game.perform("panel.set_port", {"port": "airlock"})
    assert canister(game, 4)["port"] == "chamber"
    game.perform("panel.set_port", {"port": ""})
    assert (canister(game, 4)["port"], feedback(game)) == (None, "Canister 5 is disconnected.")
    game.perform("panel.set_port", {})
    assert port_canister(atmos(game), "chamber") is None


# --- Gas Tanks at the rack -----------------------------------------------------------------------------------------

def test_tank_actions_need_a_carried_tank_picked():
    game = at_atmospherics_station("canister_rack")
    game.perform("panel.select_canister", {"index": 2})
    game.perform("panel.fill_tank", {})
    assert feedback(game) == "Pick a Gas Tank you are carrying. The tank rack hands out empty ones."
    give(game, "gas_analyzer")
    game.perform("panel.select_tank", {"index": 0})
    game.perform("panel.empty_tank", {})
    assert feedback(game) == "Pick a Gas Tank you are carrying. The tank rack hands out empty ones."
    assert ctx(game)["tanks"] == [] and ctx(game)["tank"] is None


def test_filling_a_tank_takes_gas_from_the_canister_up_to_the_tanks_rating():
    game = at_atmospherics_station("canister_rack")
    index = give_tank(game)
    game.perform("panel.select_canister", {"index": 2})
    game.perform("panel.select_tank", {"index": index})
    game.perform("panel.set_tank_amount", {"value": str(TANK_FILL_MAX + 50)})
    assert ctx(game)["tank_amount"] == TANK_FILL_MAX
    game.perform("panel.set_tank_amount", {"value": "20"})
    before = gas_mix.total_moles(canister(game, 2)["mix"])
    game.perform("panel.fill_tank", {})
    tank = game.player_data["inventory"][index]
    assert tank["attributes"]["contents"]["moles"] == {"Oxygen": pytest.approx(20)}
    assert gas_mix.total_moles(canister(game, 2)["mix"]) == pytest.approx(before - 20)
    assert feedback(game) == f"The tank reads {tank_readout(tank)}."
    assert ctx(game)["tanks"] == [{"index": index, "label": f"Gas Tank: {tank_readout(tank)}"}]
    game.perform("panel.set_tank_amount", {"value": str(TANK_FILL_MAX)})
    game.perform("panel.fill_tank", {})
    assert feedback(game) == f"That would take the tank past its rated {GAS_TANK['rated']} kPa."
    assert tank["attributes"]["contents"]["moles"] == {"Oxygen": pytest.approx(20)}
    assert gas_mix.total_moles(canister(game, 2)["mix"]) == pytest.approx(before - 20)


def test_emptying_a_tank_pours_all_of_it_into_the_canister_which_can_rupture():
    game = at_atmospherics_station("canister_rack")
    index = give_tank(game, pure("Plasma", 10))
    game.perform("panel.select_canister", {"index": 5})
    game.perform("panel.select_tank", {"index": index})
    game.perform("panel.empty_tank", {})
    assert canister(game, 5)["mix"]["moles"] == {"Plasma": pytest.approx(10)}
    assert gas_mix.total_moles(game.player_data["inventory"][index]["attributes"]["contents"]) == 0
    assert feedback(game) == "You empty the tank into Canister 6."
    canister(game, 5)["mix"] = pure("Nitrogen", gas_mix.moles_at(CANISTER["rated"], CANISTER["volume"], ROOM_TEMP))
    game.player_data["inventory"][index]["attributes"]["contents"] = pure("Nitrogen", 20)
    game.perform("panel.empty_tank", {})
    assert hazard(game) == "breach"


# --- Heater / Freezer and the tick ------------------------------------------------------------------------------------

def test_the_heater_target_stays_in_its_range():
    game = at_atmospherics_station("canister_rack")
    game.perform("panel.select_canister", {"index": 3})
    game.perform("panel.set_heater_target", {"value": "5000"})
    assert canister(game, 3)["thermo"]["target"] == HEATER_RANGE[1]
    game.perform("panel.set_heater_target", {"value": "1"})
    assert ctx(game)["canister"]["thermo"]["target"] == HEATER_RANGE[0]


def test_one_heater_freezer_runs_on_one_canister_at_a_time():
    game = at_atmospherics_station("canister_rack")
    game.perform("panel.select_canister", {"index": 3})
    game.perform("panel.set_heater_target", {"value": "400"})
    game.perform("panel.toggle_heater", {})
    assert canister(game, 3)["thermo"] == {"target": 400, "on": True}
    assert feedback(game) == "The heater/freezer works Canister 4 toward 400 K."
    atmos(game)["canisters"][5] = None
    game.perform("panel.select_canister", {"index": 0})
    game.perform("panel.toggle_heater", {})
    assert [slot["thermo"]["on"] for slot in atmos(game)["canisters"][:5]] == [True, False, False, False, False]
    game.perform("panel.toggle_heater", {})
    assert not canister(game, 0)["thermo"]["on"]
    assert feedback(game) == "The heater/freezer winds down."


def test_the_heater_moves_a_canister_toward_its_target_by_its_wattage_and_stops_there():
    game = new_game()
    full, light = canister(game, 3), canister(game, 5)
    light["mix"] = pure("Nitrogen", 10)
    for slot in (full, light):
        slot["thermo"] = {"target": 400, "on": True}
    tick_atmos(game, 2)
    assert full["mix"]["temp"] == pytest.approx(ROOM_TEMP + 2 * HEATER_WATTS / gas_mix.heat_capacity(full["mix"]))
    assert light["mix"]["temp"] == pytest.approx(400)
    canister(game, 2)["thermo"] = {"target": 100, "on": True}
    tick_atmos(game, 1)
    oxygen = canister(game, 2)["mix"]
    assert oxygen["temp"] == pytest.approx(ROOM_TEMP - HEATER_WATTS / gas_mix.heat_capacity(oxygen))
    assert canister(game, 0)["mix"]["temp"] == ROOM_TEMP


def test_heating_fuel_and_oxidizer_past_the_fuels_ignition_sets_it_burning_and_can_rupture_it():
    game = in_atmospherics()
    slot = canister(game, 5)
    slot["mix"] = fuel_and_oxygen(5, temp=370)
    slot["thermo"] = {"target": 380, "on": True}
    tick_atmos(game, 1)
    assert slot["mix"]["moles"]["Carbon Dioxide"] > 0 and slot["mix"]["temp"] > 380
    slot["mix"] = fuel_and_oxygen(1500, temp=380)
    unhurt = limb_total(game)
    tick_atmos(game, 1)
    assert (gas_mix.total_moles(slot["mix"]), hazard(game)) == (0, "fire")
    assert limb_total(game) == unhurt - RUPTURE_DAMAGE


def test_a_rupture_away_from_the_room_hurts_nobody_but_still_starts_the_hazard():
    game = new_game()
    canister(game, 5)["mix"] = pure("Nitrogen", gas_mix.moles_at(9500, CANISTER["volume"], ROOM_TEMP))
    unhurt = limb_total(game)
    tick_atmos(game, 1)
    assert (hazard(game), limb_total(game)) == ("breach", unhurt)
    assert "blast" not in messages(game)[0][1]


def test_the_master_clock_runs_the_atmospherics_tick():
    game = new_game()
    canister(game, 3)["thermo"] = {"target": 800, "on": True}
    game.player_data["game_clock"]["last_real_time"] = time.time() - 5
    game.tick()
    assert canister(game, 3)["mix"]["temp"] > ROOM_TEMP


def test_the_tick_skips_empty_slots():
    game = new_game()
    atmos(game)["canisters"] = [None] * CANISTER_SLOTS
    tick_atmos(game, 1)
    assert messages(game) == []


# --- Gas Dispenser -----------------------------------------------------------------------------------------------

def test_the_dispenser_lists_every_gas_with_the_stock_of_the_dangerous_ones():
    game = at_atmospherics_station("gas_dispenser")
    context = ctx(game)
    assert [gas["label"] for gas in context["gases"]] == [
        "Oxygen", "Nitrogen", "Carbon Dioxide", f"Plasma ({DISPENSER_STOCK} mol left)",
        f"Hydrogen ({DISPENSER_STOCK} mol left)", f"Nitrous Oxide ({DISPENSER_STOCK} mol left)"]
    assert (context["gas"], context["canister"], context["before"], context["max_amount"]) == (
        "Oxygen", None, None, DISPENSE_MAX)
    game.perform("panel.pick_gas", {"name": "Argon"})
    assert ctx(game)["gas"] == "Oxygen"


def test_the_dispenser_needs_a_canister_and_an_amount():
    game = at_atmospherics_station("gas_dispenser")
    game.perform("panel.dispense", {})
    assert feedback(game) == "Pick a canister to fill."
    game.perform("panel.pick_canister", {"index": 5})
    game.perform("panel.dispense", {})
    assert feedback(game) == "Set an amount to dispense."


def test_the_dispenser_shows_the_gauge_before_and_after_and_fills_at_room_temperature():
    game = at_atmospherics_station("gas_dispenser")
    game.perform("panel.pick_gas", {"name": "Carbon Dioxide"})
    game.perform("panel.pick_canister", {"index": 5})
    game.perform("panel.set_amount", {"value": "200"})
    context = ctx(game)
    expected = gas_mix.readout(pure("Carbon Dioxide", 200), CANISTER["volume"])
    assert (context["before"], context["after"]) == ("0.0 kPa, 3 K: Empty", expected)
    game.perform("panel.dispense", {})
    assert canister(game, 5)["mix"] == pure("Carbon Dioxide", 200)
    assert feedback(game) == "Dispensed 200 mol of Carbon Dioxide into Canister 6."


def test_oxygen_never_runs_out_but_a_dangerous_gas_does():
    game = at_atmospherics_station("gas_dispenser")
    game.perform("panel.pick_canister", {"index": 5})
    game.perform("panel.set_amount", {"value": "1000"})
    for _ in range(3):
        game.perform("panel.dispense", {})
        game.perform("panel.dispense", {})
        canister(game, 5)["mix"] = gas_mix.empty_mix()
    assert "Oxygen" not in atmos(game)["stock"]
    game.perform("panel.pick_gas", {"name": "Plasma"})
    atmos(game)["stock"]["Plasma"] = 1500
    game.perform("panel.dispense", {})
    assert atmos(game)["stock"]["Plasma"] == 500
    assert ctx(game)["max_amount"] == 500 and ctx(game)["amount"] == 500
    game.perform("panel.dispense", {})
    assert feedback(game) == "Only 500 mol of Plasma is left this shift."
    assert canister(game, 5)["mix"]["moles"] == {"Plasma": pytest.approx(1000)}
    game.perform("panel.set_amount", {"value": "500"})
    game.perform("panel.dispense", {})
    assert atmos(game)["stock"]["Plasma"] == 0
    assert ctx(game)["gases"][3]["label"] == "Plasma (0 mol left)"


def test_the_dispenser_wont_take_a_canister_past_its_rating():
    game = at_atmospherics_station("gas_dispenser")
    game.perform("panel.pick_canister", {"index": 0})
    game.perform("panel.set_amount", {"value": str(DISPENSE_MAX)})
    before = copy.deepcopy(canister(game, 0)["mix"])
    game.perform("panel.dispense", {})
    assert feedback(game) == f"That would take Canister 1 past its rated {CANISTER['rated']} kPa."
    assert canister(game, 0)["mix"] == before
    assert hazard(game) is None


# --- Combustion Chamber ---------------------------------------------------------------------------------------------

def chamber(game):
    return atmos(game)["chamber"]


def test_injecting_needs_a_canister_on_the_inlet_and_moves_its_gas_in():
    game = at_atmospherics_station("combustion_chamber")
    assert (ctx(game)["inlet"], ctx(game)["max_amount"], ctx(game)["lit"]) == (None, 0, False)
    game.perform("panel.inject", {})
    assert feedback(game) == "Connect a canister to the Combustion Chamber Inlet at the Canister Rack first."
    canister(game, 4)["port"] = "chamber"
    game.perform("panel.set_amount", {"value": "40"})
    game.perform("panel.inject", {})
    assert chamber(game)["mix"]["moles"] == {"Plasma": pytest.approx(40)}
    assert feedback(game) == "Injected 40 mol from Canister 5."
    assert ctx(game)["inlet"]["label"] == "Canister 5"


def test_the_igniter_lights_a_fuel_and_oxidizer_and_nothing_else():
    game = at_atmospherics_station("combustion_chamber")
    game.perform("panel.ignite", {})
    assert feedback(game) == "The igniter sparks. Nothing in the chamber burns: it needs a fuel and an oxidizer."
    chamber(game)["mix"] = fuel_and_oxygen(20, fuel="Hydrogen")
    game.perform("panel.ignite", {})
    assert chamber(game)["lit"] and ctx(game)["lit"]
    assert feedback(game) == "The igniter sparks, and the chamber fills with flame."
    game.perform("panel.ignite", {})
    assert feedback(game) == "It is already burning."


def test_a_lit_burn_runs_until_nothing_more_reacts_and_logs_its_peak():
    game = at_atmospherics_station("combustion_chamber")
    chamber(game)["mix"] = fuel_and_oxygen(20)
    game.perform("panel.ignite", {})
    temps, pressures = [], []
    for _ in range(200):
        tick_atmos(game, 1)
        temps.append(chamber(game)["mix"]["temp"])
        pressures.append(kpa(chamber(game)["mix"], CHAMBER["volume"]))
        if not chamber(game)["lit"]:
            break
    assert not chamber(game)["lit"] and chamber(game)["peak"] is None
    assert chamber(game)["mix"]["moles"]["Carbon Dioxide"] == pytest.approx(50, rel=0.01)
    assert messages(game)[-1] == ("Combustion Chamber", f"The burn is over. It peaked at {max(temps):.0f} K and "
                                                        f"{max(pressures):.1f} kPa.")


def test_a_burn_still_going_strong_stays_lit():
    game = new_game()
    chamber(game)["mix"] = fuel_and_oxygen(20)
    chamber(game)["lit"] = True
    chamber(game)["peak"] = {"temp": ROOM_TEMP, "pressure": 0}
    tick_atmos(game, 1)
    assert chamber(game)["lit"] and messages(game) == []
    assert chamber(game)["peak"]["temp"] == chamber(game)["mix"]["temp"]


def test_a_burn_is_over_once_a_second_of_it_releases_less_than_the_threshold():
    game = new_game()
    chamber(game)["mix"] = fuel_and_oxygen(BURN_OVER_JOULES / 300_000 / 0.2 / 2)
    chamber(game)["lit"] = True
    chamber(game)["peak"] = {"temp": ROOM_TEMP, "pressure": 0}
    tick_atmos(game, 1)
    assert not chamber(game)["lit"]


def test_hot_fuel_in_the_chamber_lights_without_the_igniter():
    game = new_game()
    chamber(game)["mix"] = fuel_and_oxygen(20, temp=400)
    tick_atmos(game, 1)
    assert chamber(game)["lit"]
    assert chamber(game)["mix"]["moles"]["Carbon Dioxide"] > 0
    chamber(game)["mix"] = fuel_and_oxygen(20)
    chamber(game)["lit"] = False
    tick_atmos(game, 1)
    assert not chamber(game)["lit"]


def test_a_burn_past_the_chambers_rating_ruptures_it_into_a_fire():
    game = in_atmospherics()
    chamber(game)["mix"] = fuel_and_oxygen(2000)
    chamber(game)["lit"] = True
    chamber(game)["peak"] = {"temp": ROOM_TEMP, "pressure": 0}
    unhurt = limb_total(game)
    tick_atmos(game, 5)
    assert (gas_mix.total_moles(chamber(game)["mix"]), chamber(game)["lit"], chamber(game)["peak"]) == (0, False, None)
    assert hazard(game) == "fire" and limb_total(game) == unhurt - RUPTURE_DAMAGE
    assert messages(game)[0][1].startswith("The combustion chamber ruptures with a bang at ")


def test_injecting_past_the_chambers_rating_ruptures_it_into_a_breach():
    game = at_atmospherics_station("combustion_chamber")
    chamber(game)["mix"] = pure("Nitrogen", gas_mix.moles_at(14_900, CHAMBER["volume"], ROOM_TEMP))
    canister(game, 3)["port"] = "chamber"
    game.perform("panel.set_amount", {"value": "500"})
    game.perform("panel.inject", {})
    assert (gas_mix.total_moles(chamber(game)["mix"]), hazard(game)) == (0, "breach")


def test_pumping_out_moves_all_the_hot_gas_into_the_picked_canister():
    game = at_atmospherics_station("combustion_chamber")
    game.perform("panel.pump_out", {})
    assert feedback(game) == "Pick a canister to pump into."
    chamber(game)["mix"] = pure("Carbon Dioxide", 50, temp=900)
    game.perform("panel.pick_target", {"index": 5})
    assert ctx(game)["target"] == 5
    game.perform("panel.pump_out", {})
    assert canister(game, 5)["mix"] == pure("Carbon Dioxide", 50, temp=900)
    assert gas_mix.total_moles(chamber(game)["mix"]) == 0
    assert feedback(game).startswith("The chamber's gas is pumped into Canister 6, which reads ")


def test_pumping_into_a_full_canister_ruptures_it():
    game = at_atmospherics_station("combustion_chamber")
    chamber(game)["mix"] = pure("Nitrogen", 2000)
    game.perform("panel.pick_target", {"index": 0})
    game.perform("panel.pump_out", {})
    assert (gas_mix.total_moles(canister(game, 0)["mix"]), hazard(game)) == (0, "breach")


def test_venting_the_chamber_empties_it_and_puts_the_fire_out():
    game = at_atmospherics_station("combustion_chamber")
    chamber(game)["mix"] = fuel_and_oxygen(20)
    game.perform("panel.ignite", {})
    game.perform("panel.vent_chamber", {})
    assert (gas_mix.total_moles(chamber(game)["mix"]), chamber(game)["lit"]) == (0, False)
    assert feedback(game) == "The chamber vents to space. Whatever was burning goes out."


# --- Gas Tanks and the Gas Analyzer --------------------------------------------------------------------------------

def test_gas_tanks_never_stack_and_each_keeps_its_own_gas():
    game = new_game()
    give_tank(game, pure("Oxygen", 10))
    give_tank(game)
    tanks = game.player_data["inventory"]
    assert [item.get("quantity") for item in tanks] == [1, 1]
    assert [gas_mix.total_moles(item["attributes"]["contents"]) for item in tanks] == [10, 0]


def test_examining_a_tank_reads_only_its_pressure():
    game = new_game()
    index = give_tank(game, pure("Plasma", 20))
    select_item(game, index)
    game.perform("panel.examine", {})
    title, message = messages(game)[-1]
    assert title == "Examine: Gas Tank"
    assert message.endswith(f"Its gauge reads {kpa(pure('Plasma', 20), GAS_TANK['volume']):.1f} kPa.")
    assert "Plasma" not in message


def test_the_analyzer_reads_the_air_and_every_tank_carried_or_held():
    game = give(new_game(), "gas_analyzer")
    game.player_data["hands"]["left"] = held = tank_item(pure("Nitrogen", 5))
    carried = give_tank(game, pure("Oxygen", 15))
    select_item(game, 0)
    game.perform("panel.actions", {})
    assert [action["name"] for action in ctx(game)["actions"]] == ["use", "drop"]
    game.perform("panel.item_action", {"name": "use"})
    lines = messages(game)[-1][1].split("\n")
    assert lines == [f"The air here: {STANDARD_PRESSURE} kPa, {ROOM_TEMP} K: Oxygen 21.0%, Nitrogen 79.0%",
                     f"Gas Tank: {tank_readout(game.player_data['inventory'][carried])}",
                     f"Gas Tank: {tank_readout(held)}"]
    assert game.ui["panels"] == [{"type": "inventory", "selected": 0, "selected_id": "gas_analyzer"}]


def test_the_analyzer_alone_reads_the_station_air():
    game = fill_air(give(new_game(), "gas_analyzer"), {"Oxygen": 0.5, "Nitrogen": 0.5})
    item_action(game, 0, "use")
    assert messages(game)[-1] == ("Gas Analyzer", "The air here: 101.3 kPa, 293 K: Oxygen 50.0%, Nitrogen 50.0%")


def test_tank_holds_wants_a_gas_tank_mostly_of_the_gas_at_half_its_rating():
    enough = gas_mix.moles_at(REQUEST_PRESSURE, GAS_TANK["volume"], ROOM_TEMP) * 1.01
    assert tank_holds(tank_item(pure("Oxygen", enough)), "Oxygen")
    assert not tank_holds(tank_item(pure("Oxygen", enough * 0.9)), "Oxygen")
    assert not tank_holds(tank_item(gas_mix.mix_of(AIR, enough * 2, ROOM_TEMP)), "Oxygen")
    assert not tank_holds(tank_item(pure("Oxygen", enough)), "Nitrogen")
    assert not tank_holds(get_item_definition("medkit"), "Oxygen")


# --- The Scientist's job event in Atmospherics ---------------------------------------------------------------------

def test_a_scientist_posted_here_gets_gas_requests_and_delivers_a_filled_tank(monkeypatch):
    game = new_game("Science", "Scientist", post=ATMOSPHERICS_KEY)
    monkeypatch.setattr(random_events.random, "choice", lambda options: options[0])
    monkeypatch.setattr(random_events.random, "randint", lambda low, high: 100)
    event = build_job_event(game)
    assert (event["title"], event["desc"]) == (
        "Gas Request", "The Doctor needs a gas tank of Oxygen. Deliver it to the MedBay for 100 credits.")
    event["effect"]()
    (duty,) = game.player_data["duties"]
    assert (duty["kind"], duty["giver"], duty["room"], duty["item"], duty["gas"]) == (
        "deliver", "Doctor", MEDBAY_KEY, "gas_tank", "Oxygen")
    assert duty["summary"] == "Bring a gas tank of Oxygen to the Doctor in the MedBay (100 cr)"

    game.player_data["location"] = location_from_key(MEDBAY_KEY)
    give_tank(game, pure("Oxygen", 5))
    assert "Deliver Gas Tank" in labels(game)
    game.perform("room.complete_duty", {"duty_id": duty["id"]})
    assert messages(game)[-1] == ("Nothing to Deliver", "You don't have a gas tank of Oxygen to deliver.")
    credits = game.player_data["credits"]
    give_tank(game, pure("Oxygen", 20))
    game.perform("room.complete_duty", {"duty_id": duty["id"]})
    assert game.player_data["duties"] == [] and game.player_data["credits"] == credits + 100
    assert [gas_mix.total_moles(item["attributes"]["contents"]) for item in game.player_data["inventory"]] == [5]


def test_no_gas_request_comes_when_nobody_is_there_to_ask(monkeypatch):
    game = new_game("Science", "Scientist", post=ATMOSPHERICS_KEY)
    monkeypatch.setattr(random_events.random, "choice", lambda options: options[0])
    game.player_data["station_crew"] = []
    assert build_job_event(game) is None


# --- The panels on the page ----------------------------------------------------------------------------------------

def test_the_three_panels_render(app):
    game = at_atmospherics_station("canister_rack")
    page = html(app, game)
    assert "<h2>Canister Rack</h2>" in page and "Pick a canister to read its gauge." in page
    assert "Transfer to Another Canister" not in page
    give_tank(game, pure("Oxygen", 5))
    atmos(game)["canisters"][5] = None
    canister(game, 2)["thermo"]["on"] = True
    game.perform("panel.select_canister", {"index": 2})
    game.perform("panel.set_port", {"port": "chamber"})
    page = html(app, game)
    for text in ("Slot 6: empty", "Transfer to Another Canister", "Heater/Freezer: ON", "Fill the Tank",
                 'data-action="panel.set_heater_target"', "Combustion Chamber Inlet", "Gas Tank: "):
        assert text in page, text
    assert "You carry no Gas Tank" not in page

    game.ui["panels"] = []
    game.perform("room.show_gas_dispenser", {})
    page = html(app, game)
    assert "<h2>Gas Dispenser</h2>" in page and "Pick a canister to see its gauge." in page
    game.perform("panel.pick_canister", {"index": 0})
    assert "Now: " in html(app, game)
    atmos(game)["canisters"] = [None] * CANISTER_SLOTS
    assert "There are no canisters on the rack." in html(app, game)

    game.ui["panels"] = []
    game.perform("room.show_combustion_chamber", {})
    page = html(app, game)
    assert "<h2>Combustion Chamber</h2>" in page and "Not burning" in page and "Nothing is connected." in page


def test_the_atmospherics_guide_page_quotes_the_game(client):
    page = client.get("/wiki/Atmospherics").get_data(as_text=True)
    for line in ("<tr><td>Plasma</td><td>fuel</td><td>200</td>", f"{DISPENSER_STOCK} mol of each a shift",
                 f"rated to {CHAMBER['rated']} kPa", "Canister 6: empty", "Canister 1: 21% Oxygen, 79% Nitrogen",
                 f"by {HEATER_WATTS // 1000} kW", f"takes {RUPTURE_DAMAGE}% off a limb", "Breathable air is 21% Oxygen"):
        assert line in page, line
    scientist = client.get("/wiki/Scientist").get_data(as_text=True)
    assert "<b>Gas Request</b> (Atmospherics)" in scientist and f"{int(REQUEST_PRESSURE)} kPa" in scientist


def test_the_scientists_guide_folder_has_the_atmospherics_page():
    assert "Atmospherics" in JOB_GUIDES["Scientist"]
