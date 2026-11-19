import pytest

from helpers import (
    crew,
    ctx,
    feedback,
    give,
    html,
    in_room,
    messages,
    new_game,
    notes,
    only_working,
    open_station,
    pda_messages,
)
from space_online.game.helper_methods import antagonists, engine as engine_rules, gas_mix
from space_online.game.helper_methods.antagonists import ACTS, COOLANT_LINE
from space_online.game.helper_methods.atmos import CANISTER_SLOTS, RUPTURE_DAMAGE, connect, new_canister
from space_online.game.helper_methods.crew_work import ATMOSPHERICS_WORK_SECONDS, ENGINEER_WORK_SECONDS, tick_crew_work
from space_online.game.helper_methods.engine import (
    BAY_SLOTS,
    BURN_CHAMBER,
    CANISTER_MOLES,
    HOT_LIMIT,
    LOW_MOLES,
    OUTPUT_CAP,
    SAFE_SETTINGS,
    STALL_WARNING,
    engine_output,
    hint,
    new_engine,
    send_back_empty,
    send_fresh_canister,
    step_engine,
    tick_engine,
)
from space_online.game.helper_methods.pda import power_readout_panel, tick_pda_needs
from space_online.game.maps.donut import ATMOSPHERICS_KEY, ENGINEERING_KEY, location_from_key
from space_online.game.objects.items import get_item_definition

ENGINE_PANEL = "combustion_engine"


def engine(game):
    return game.player_data["engine"]


def at_engine(department="Engineering", job="Engineer"):
    """A player in the Engineering Bay with the Combustion Engine panel open."""
    return open_station(in_room(ENGINEERING_KEY, department, job), "engineering_station", "access_combustion_engine")


def lit(fuel="Hydrogen", oxidizer="Oxygen", **settings):
    """A running engine on its own, with fuel and oxidizer canisters too big to run dry."""
    state = new_engine(running=True)
    for slot, gas in enumerate((fuel, oxidizer)):
        state["canisters"][slot]["mix"] = gas_mix.mix_of({gas: 1}, 10 ** 6, 293)
    state["settings"].update(settings)
    return state


def run(state, seconds):
    for _ in range(seconds):
        step_engine(state, 1)
    return state


def seconds_to_overheat(state, longest=1500):
    for second in range(longest):
        step_engine(state, 1)
        if state["hot"] > HOT_LIMIT:
            return second
    return None


# --- The shift's engine --------------------------------------------------------------------------------------------

def test_a_shift_starts_with_hydrogen_on_the_fuel_line_and_oxygen_on_the_oxidizer_line():
    state = engine(new_game("Engineering", "Engineer"))
    fuel, oxidizer, *empty = state["canisters"]
    assert (len(state["canisters"]), empty) == (BAY_SLOTS, [None] * (BAY_SLOTS - 2))
    assert (fuel["label"], fuel["port"], gas_mix.fractions(fuel["mix"])) == ("Canister E1", "fuel", {"Hydrogen": 1})
    assert (oxidizer["label"], oxidizer["port"], gas_mix.fractions(oxidizer["mix"])) == (
        "Canister E2", "oxidizer", {"Oxygen": 1})
    assert (state["settings"], state["running"], state["damage"], state["coolant_fault"]) == (
        SAFE_SETTINGS, False, 0, False)


# --- The burn ------------------------------------------------------------------------------------------------------

def test_a_clean_mix_gives_more_than_the_same_amount_burned_lean_or_rich():
    clean, lean, rich = (engine_output(run(lit(mixer=mixer), 300)) for mixer in (40, 20, 60))
    assert clean > lean and clean > rich


def test_more_coolant_widens_the_gap_and_none_lets_the_loops_meet():
    outputs = [engine_output(run(lit(coolant=coolant), 300)) for coolant in (2, 6, 10)]
    assert outputs == sorted(outputs)
    stopped = lit(coolant=0)
    gaps = [run(stopped, 300)["hot"] - stopped["cold"] for _ in range(3)]
    assert gaps[0] > gaps[1] > gaps[2]
    assert engine_output(stopped) < 0.2 < outputs[0]


def test_plasma_out_produces_hydrogen_and_overheats_sooner():
    assert engine_output(run(lit("Plasma"), 300)) > engine_output(run(lit(), 300))
    assert seconds_to_overheat(lit("Plasma", coolant=0)) < seconds_to_overheat(lit(coolant=0))


def test_a_premixed_canister_on_the_fuel_line_burns_with_the_mixer_at_100():
    state = new_engine(running=True)
    state["canisters"][0]["mix"] = gas_mix.mix_of({"Hydrogen": 0.4, "Oxygen": 0.6}, CANISTER_MOLES, 293)
    state["canisters"][1] = None
    state["settings"]["mixer"] = 100
    run(state, 120)
    assert state["running"] and engine_output(state) > 0.5


def test_nitrous_oxide_is_a_weaker_oxidizer_than_oxygen():
    assert engine_output(run(lit(oxidizer="Nitrous Oxide"), 300)) < engine_output(run(lit(), 300))


def test_the_output_tops_out_at_its_cap():
    state = run(lit("Plasma", injection=8), 300)
    assert engine_output(state) == OUTPUT_CAP


def test_a_stopped_engine_gives_nothing_and_wears_nothing():
    state = lit()
    state.update(running=False, hot=HOT_LIMIT + 500, cold=0)
    step_engine(state, 1)
    assert (engine_output(state), state["damage"]) == (0, 0)


def test_over_pressure_stalls_injection_and_exhaust_until_it_drops():
    state = lit()
    state["chamber"] = gas_mix.mix_of({"Carbon Dioxide": 1},
                                      gas_mix.moles_at(1.1 * BURN_CHAMBER["rated"], BURN_CHAMBER["volume"], 800), 800)
    fuel, chamber_moles = gas_mix.total_moles(state["canisters"][0]["mix"]), gas_mix.total_moles(state["chamber"])
    step_engine(state, 1)
    assert gas_mix.total_moles(state["canisters"][0]["mix"]) == fuel
    assert gas_mix.total_moles(state["chamber"]) == chamber_moles
    assert hint(state) == "Pumps stalling."
    while engine_rules.chamber_pressure(state) > BURN_CHAMBER["rated"]:
        step_engine(state, 1)
    step_engine(state, 1)
    assert gas_mix.total_moles(state["canisters"][0]["mix"]) < fuel


def test_the_log_warns_as_the_pressure_climbs_to_a_stall():
    game = new_game()
    state = engine(game)
    state["canisters"][0]["mix"] = gas_mix.mix_of({"Plasma": 1}, 10 ** 6, 293)
    state["settings"]["injection"] = 10
    tick_engine(game, 300)
    rated = BURN_CHAMBER["rated"]
    pressure_lines = [message for _, message in messages(game) if "kPa" in message]
    assert pressure_lines[:2] == [
        f"Chamber pressure is past {STALL_WARNING:.0%} of its {rated} kPa rating. The pumps stall over it.",
        f"The pumps stall: the chamber is over {rated} kPa. Injection and exhaust stop until it drops."]


def test_an_empty_canister_flames_the_engine_out_without_harm():
    game = new_game()
    state = engine(game)
    state["canisters"][1]["mix"] = gas_mix.mix_of({"Oxygen": 1}, 20, 293)
    tick_engine(game, 120)
    assert (state["running"], state["damage"]) == (False, 0)
    assert messages(game) == [("Combustion Engine",
                               "The engine flames out: there is nothing left in the chamber to burn.")]
    assert notes(game)[-1] == "The combustion engine flamed out."


def test_a_long_tick_runs_in_steps_and_matches_one_second_at_a_time():
    stepped, whole = new_game(), new_game()
    for _ in range(30):
        tick_engine(stepped, 1)
    tick_engine(whole, 30)
    assert engine(whole)["hot"] == pytest.approx(engine(stepped)["hot"])


@pytest.mark.parametrize("change, expected", [
    ({"coolant_fault": True}, "Coolant line cut."),
    ({"hot": 0.95 * HOT_LIMIT}, "Hot loop near its limit."),
    ({"running": False}, "Not running."),
    ({"chamber": gas_mix.mix_of({"Hydrogen": 0.4, "Oxygen": 0.6}, 10, 500)}, "Burning clean."),
    ({"chamber": gas_mix.mix_of({"Hydrogen": 0.6, "Oxygen": 0.4}, 10, 500)},
     "Burning rich: unburnt fuel in the exhaust."),
    ({"chamber": gas_mix.mix_of({"Hydrogen": 0.2, "Oxygen": 0.8}, 10, 500)}, "Burning lean."),
    ({"chamber": gas_mix.mix_of({"Hydrogen": 1}, 10, 500)}, "Burning rich: unburnt fuel in the exhaust."),
])
def test_the_hint_names_the_most_urgent_thing(change, expected):
    state = new_engine(running=True)
    state.update(change)
    assert hint(state) == expected


# --- Power ---------------------------------------------------------------------------------------------------------

def test_a_safe_hydrogen_burn_alone_holds_balanced_with_some_to_spare():
    game = new_game("Engineering", "Engineer")
    engine(game)["running"] = True
    power = game.player_data["station_power"]
    assert (power["solar_charging"], power["power_mode"]) == (False, "balanced")
    for _ in range(180):
        tick_engine(game, 1)
        game._tick_power(1)
    before = power["battery_level"]
    for _ in range(60):
        tick_engine(game, 1)
        game._tick_power(1)
    assert 1.0 < engine_output(engine(game)) < 2.0
    assert power["battery_level"] - before == pytest.approx(engine_output(engine(game)) - 0.99, abs=0.05)


def test_the_engineering_panel_and_the_power_readout_show_the_engine(app):
    game = new_game("Engineering", "Engineer")
    engine(game).update(running=True, hot=500, cold=200)
    output = engine_output(engine(game))
    assert power_readout_panel(game, {})["engine_output"] == output
    game.player_data["location"] = location_from_key(ENGINEERING_KEY)
    open_station(game, "engineering_station", "access_engineering_panel")
    assert ctx(game)["engine_output"] == output
    assert f"Combustion Engine: +{output:.2f}% per minute" in html(app, game)
    game.ui["panels"] = []
    game.player_data["hands"]["left"] = get_item_definition("pda")
    game.perform("game.pda", {})
    game.perform("panel.app", {})
    assert f"Combustion Engine: +{output:.2f}% per minute" in html(app, game)


# --- The panel -----------------------------------------------------------------------------------------------------

def test_the_panel_reads_the_engine(app):
    game = at_engine()
    view = ctx(game)
    assert (view["running"], view["output"], view["hint"], view["damage"]) == (False, 0, "Not running.", 0)
    assert [slot and (slot["label"], slot["port"]) for slot in view["slots"]] == [
        ("Canister E1", "fuel"), ("Canister E2", "oxidizer"), None, None]
    assert [(setting["key"], setting["value"], setting["max"]) for setting in view["settings"]] == [
        ("mixer", 40, 100), ("injection", 2, 10), ("coolant", 10, 10)]
    page = html(app, game)
    assert "Connect as Fuel" in page and "Send to Atmospherics" in page and "Slot 3: empty" in page
    assert "Repair Coolant Line" not in page and "Repair Chamber" not in page


def test_ignite_needs_a_canister_on_the_fuel_line():
    game = at_engine()
    game.perform("panel.set_port", {"index": 0, "port": ""})
    game.perform("panel.ignite", {})
    assert (engine(game)["running"], feedback(game)) == (False, "Connect a canister as Fuel first.")
    game.perform("panel.set_port", {"index": 0, "port": "fuel"})
    game.perform("panel.ignite", {})
    assert (engine(game)["running"], feedback(game)) == (True, "The igniter sparks, and the chamber catches.")
    assert notes(game)[-1] == "Lit the combustion engine."
    game.perform("panel.ignite", {})
    assert feedback(game) == "The engine is already running."


def test_shutting_down_and_the_emergency_vent():
    game = at_engine()
    game.perform("panel.shut_down", {})
    assert feedback(game) == "The engine isn't running."
    game.perform("panel.ignite", {})
    tick_engine(game, 30)
    game.perform("panel.shut_down", {})
    assert (engine(game)["running"], feedback(game)) == (False, "The injectors close and the burn dies away.")
    game.perform("panel.ignite", {})
    tick_engine(game, 30)
    assert gas_mix.total_moles(engine(game)["chamber"]) > 0
    game.perform("panel.emergency_vent", {})
    assert (engine(game)["running"], gas_mix.total_moles(engine(game)["chamber"])) == (False, 0)
    assert feedback(game) == "The chamber vents to space. Whatever was burning goes out."


def test_the_sliders_stay_in_range():
    game = at_engine()
    game.perform("panel.set_setting", {"setting": "mixer", "value": "150"})
    game.perform("panel.set_setting", {"setting": "injection", "value": "-3"})
    game.perform("panel.set_setting", {"setting": "coolant", "value": "4"})
    game.perform("panel.set_setting", {"setting": "warp", "value": "4"})
    assert engine(game)["settings"] == {"mixer": 100, "injection": 0, "coolant": 4}


def test_a_line_being_drawn_from_waits_for_a_shut_down():
    game = at_engine()
    engine(game)["canisters"][2] = new_canister("E3", {"Plasma": 1})
    game.perform("panel.ignite", {})
    game.perform("panel.set_port", {"index": 0, "port": ""})
    assert feedback(game) == "Shut the engine down before changing a line it is drawing from."
    game.perform("panel.set_port", {"index": 2, "port": "fuel"})
    assert engine(game)["canisters"][2]["port"] is None
    game.perform("panel.shut_down", {})
    game.perform("panel.set_port", {"index": 2, "port": "fuel"})
    assert feedback(game) == "Canister E3 is connected as Fuel."
    assert [canister and canister["port"] for canister in engine(game)["canisters"]] == [None, "oxidizer", "fuel",
                                                                                         None]
    game.perform("panel.set_port", {"index": 0, "port": ""})
    assert feedback(game) == "Canister E1 is disconnected."
    game.perform("panel.set_port", {"index": 3, "port": "fuel"})
    game.perform("panel.set_port", {"index": 2, "port": "exhaust"})
    assert engine(game)["canisters"][2]["port"] == "fuel"


def test_controls_refuse_a_player_without_engineering_access():
    game = new_game()
    game.open_panel(ENGINE_PANEL)
    before = engine(game)["settings"].copy()
    engine(game)["coolant_fault"] = True
    give(game, "repair_tool")
    for action, args in (("ignite", {}), ("shut_down", {}), ("emergency_vent", {}), ("repair_coolant_line", {}),
                         ("set_setting", {"setting": "injection", "value": 9}),
                         ("set_port", {"index": 0, "port": ""}), ("send_to_atmospherics", {"index": 0})):
        game.perform(f"panel.{action}", args)
    assert engine(game)["running"] and engine(game)["coolant_fault"]
    assert engine(game)["settings"] == before and engine(game)["canisters"][0]["port"] == "fuel"
    assert game._messages == []


def test_visitors_cannot_open_the_engine_panel():
    game = at_engine("Civilian", "Staff Assistant")
    assert game.ui["panels"] == []


# --- The tube ------------------------------------------------------------------------------------------------------

def captain_at(panel):
    game = new_game("Administration", "Captain")
    game.open_panel(panel)
    return game


def test_a_canister_sent_from_atmospherics_lands_in_the_bay():
    game = captain_at("canister_rack")
    rack = game.player_data["atmos"]["canisters"]
    plasma = rack[4]
    game.perform("panel.select_canister", {"index": 4})
    game.perform("panel.send_to_engineering", {})
    assert (rack[4], engine(game)["canisters"][2]) == (None, plasma)
    assert feedback(game) == (f"{plasma['label']} goes down the tube into slot 3 of the Combustion Engine's canister "
                              "bay.")
    assert notes(game)[-1] == feedback(game)


def test_atmospherics_keeps_a_connected_canister_and_a_full_bay_refuses():
    game = captain_at("canister_rack")
    game.perform("panel.send_to_engineering", {})
    assert feedback(game) == "Pick a canister on the rack first."
    game.perform("panel.select_canister", {"index": 0})
    game.perform("panel.set_port", {"port": "reservoir"})
    game.perform("panel.send_to_engineering", {})
    assert feedback(game) == "Disconnect Canister 1 first."
    game.perform("panel.set_port", {"port": ""})
    engine(game)["canisters"][2:] = [new_canister("X", None), new_canister("Y", None)]
    game.perform("panel.send_to_engineering", {})
    assert feedback(game) == "The Combustion Engine's canister bay has no free slot."
    assert game.player_data["atmos"]["canisters"][0]["label"] == "Canister 1"


def test_a_canister_sent_back_lands_on_the_rack():
    game = captain_at(ENGINE_PANEL)
    rack = game.player_data["atmos"]["canisters"]
    game.perform("panel.shut_down", {})
    game.perform("panel.send_to_atmospherics", {"index": 0})
    assert feedback(game) == "Disconnect Canister E1 first."
    game.perform("panel.set_port", {"index": 0, "port": ""})
    game.perform("panel.send_to_atmospherics", {"index": 0})
    assert feedback(game) == "The Canister Rack in Atmospherics has no free slot."
    rack[5] = None
    hydrogen = engine(game)["canisters"][0]
    game.perform("panel.send_to_atmospherics", {"index": 0})
    assert (rack[5], engine(game)["canisters"][0]) == (hydrogen, None)
    assert feedback(game) == "Canister E1 goes down the tube into slot 6 of the Atmospherics Canister Rack."
    game.perform("panel.send_to_atmospherics", {"index": 0})
    game.perform("panel.send_to_atmospherics", {"index": 9})
    game.perform("panel.set_port", {"index": 9, "port": "fuel"})
    assert len(rack) == CANISTER_SLOTS and rack[5] is hydrogen


# --- Failures ------------------------------------------------------------------------------------------------------

def overheat(game, seconds=600):
    state = engine(game)
    state["canisters"][0]["mix"] = gas_mix.mix_of({"Plasma": 1}, 10 ** 6, 293)
    state.update(running=True, coolant_fault=True)
    tick_engine(game, seconds)
    return state


def test_holding_the_engine_over_its_limit_ends_in_a_fire_and_a_dead_engine():
    game = at_engine()
    state = overheat(game)
    assert (state["running"], state["damage"]) == (False, 100)
    assert game.player_data["ship_map"][ENGINEERING_KEY]["hazard"] == "fire"
    assert messages(game) == [
        ("Combustion Engine", f"The hot loop is over its {HOT_LIMIT} K limit. The chamber takes damage while the "
                              "engine runs."),
        ("Combustion Engine", "The combustion chamber is at 50% damage."),
        ("Combustion Engine", "The combustion chamber is at 80% damage."),
        ("Combustion Engine", "The combustion chamber gives out. The engine shuts down until it is repaired."),
        ("Hazard", "A fire has broken out in the Engineering Bay.")]
    game.perform("panel.ignite", {})
    assert (state["running"], feedback(game)) == (False, "The chamber is wrecked. Repair it first.")


def test_a_wrecked_chamber_is_repaired_with_tools_like_a_faulted_system(app):
    game = at_engine()
    overheat(game)
    assert "Repair Chamber" in html(app, game)
    game.perform("panel.repair_chamber", {})
    assert messages(game)[-1] == ("Repair", "You need Basic Tools or a Repair Tool to repair the combustion chamber.")
    give(game, "basic_tools").perform("panel.repair_chamber", {})
    assert engine(game)["damage"] == 0
    assert messages(game)[-1] == ("Repair", "You repair the combustion chamber with the Basic Tools. It is ready to "
                                            "light.")
    assert notes(game)[-1] == "Repaired the combustion chamber with the Basic Tools."
    game.perform("panel.ignite", {})
    assert engine(game)["running"]
    engine(game)["damage"] = 30
    game.perform("panel.repair_chamber", {})
    assert engine(game)["damage"] == 30


def test_a_chamber_far_past_its_rating_when_it_fails_bursts_and_hurts_the_player_in_the_room():
    game = at_engine()
    state = engine(game)
    state.update(running=True, damage=99.5, hot=HOT_LIMIT + 200, cold=HOT_LIMIT + 200,
                 chamber=gas_mix.mix_of({"Carbon Dioxide": 1}, gas_mix.moles_at(
                     3 * BURN_CHAMBER["rated"], BURN_CHAMBER["volume"], 1500), 1500))
    before = sum(game.player_data["limbs"].values())
    tick_engine(game, 1)
    assert sum(game.player_data["limbs"].values()) == before - RUPTURE_DAMAGE
    assert game.player_data["ship_map"][ENGINEERING_KEY]["hazard"] == "breach"
    title, message = messages(game)[-2]
    assert title == "Combustion Engine" and message.startswith(
        "The combustion chamber bursts and tears a hole in the hull. The engine is dead until it is repaired. The "
        "blast catches your ")
    assert (state["running"], gas_mix.total_moles(state["chamber"])) == (False, 0)


def test_the_engineers_pda_hears_about_chamber_damage():
    game = new_game("Engineering", "Engineer")
    game.player_data["station_power"]["solar_charging"] = True
    engine(game)["damage"] = 55
    tick_pda_needs(game)
    engine(game)["damage"] = 85
    tick_pda_needs(game)
    assert pda_messages(game) == [
        ("Combustion Engine", "The combustion chamber is at 50% damage."),
        ("Combustion Engine", "The combustion chamber is at 80% damage.")]


def test_sabotage_cuts_the_coolant_line_and_repair_coolant_line_fixes_it(monkeypatch, app):
    game = at_engine()
    monkeypatch.setattr(antagonists.random, "choice", lambda options: COOLANT_LINE)
    assert ACTS["sabotage"](game, None) == ("Someone has cut the engine's coolant line.", "Engineering Bay")
    state = engine(game)
    state["running"] = True
    tick_engine(game, 120)
    hot = state["hot"]
    assert state["settings"]["coolant"] == 10 and hint(state) == "Coolant line cut."
    assert "The coolant line is cut." in html(app, game)
    tick_engine(game, 30)
    assert state["hot"] > hot
    game.perform("panel.repair_coolant_line", {})
    assert messages(game)[-1] == ("Repair", "You need Basic Tools or a Repair Tool to repair the coolant line.")
    give(game, "repair_tool").perform("panel.repair_coolant_line", {})
    assert not state["coolant_fault"]
    assert messages(game)[-1] == ("Repair", "You repair the coolant line with the Repair Tool. Coolant flows again.")
    game.perform("panel.repair_coolant_line", {})
    assert len(game.player_data["notes"]) == 1


# --- The NPC crew --------------------------------------------------------------------------------------------------

def at(game, seconds):
    game.player_data["game_clock"]["elapsed_seconds"] = seconds
    tick_crew_work(game)
    return game


def test_the_npc_engineer_repairs_a_cut_line_then_shuts_down_an_overheating_engine():
    game = only_working(new_game(), "Engineer")
    name = crew(game, "Engineer")["name"]
    state = engine(game)
    state.update(coolant_fault=True, hot=HOT_LIMIT + 50)
    at(game, ENGINEER_WORK_SECONDS)
    assert (state["coolant_fault"], state["running"]) == (False, True)
    assert messages(game)[-1] == ("Engineering", f"{name} repairs the engine's coolant line.")
    at(game, 2 * ENGINEER_WORK_SECONDS)
    assert not state["running"]
    assert messages(game)[-1] == ("Engineering", f"{name} shuts down the overheating combustion engine.")


def test_the_npc_engineer_lights_the_engine_at_the_safe_setting_swapping_in_a_fresh_canister():
    game = only_working(new_game(), "Engineer")
    state = engine(game)
    state["settings"].update(injection=9, coolant=1)
    state["running"] = False
    state["canisters"][1]["mix"] = gas_mix.empty_mix()
    state["canisters"][3] = new_canister("E3", {"Oxygen": 1})
    at(game, ENGINEER_WORK_SECONDS)
    assert (state["running"], state["settings"]) == (True, SAFE_SETTINGS)
    assert [canister and canister["port"] for canister in state["canisters"]] == ["fuel", None, None, "oxidizer"]
    assert messages(game)[-1] == ("Engineering", f"{crew(game, 'Engineer')['name']} lights the combustion engine.")


@pytest.mark.parametrize("trouble", ["no oxygen", "wrecked"])
def test_the_npc_engineer_leaves_an_engine_they_cannot_light(trouble):
    game = only_working(new_game(), "Engineer")
    state = engine(game)
    state["running"] = False
    if trouble == "no oxygen":
        state["canisters"][1]["mix"] = gas_mix.empty_mix()
    else:
        state["damage"] = 100
    at(game, ENGINEER_WORK_SECONDS)
    assert not state["running"] and game._messages == []


def test_nobody_runs_the_engine_for_a_player_engineer():
    game = only_working(new_game("Engineering", "Engineer"), "Engineer")
    state = engine(game)
    state["coolant_fault"] = True
    at(game, ENGINEER_WORK_SECONDS)
    assert (state["running"], state["coolant_fault"], game._messages) == (False, True, [])


def low(gas):
    return gas_mix.mix_of({gas: 1}, LOW_MOLES - 1, 293)


def test_the_atmospherics_scientist_fills_a_rack_canister_for_a_line_running_low():
    game = only_working(new_game(), "Scientist")
    state, atmos = engine(game), game.player_data["atmos"]
    rack = atmos["canisters"]
    at(game, ATMOSPHERICS_WORK_SECONDS)
    assert state["canisters"][2:] == [None, None]

    state["canisters"][1]["mix"] = low("Oxygen")
    at(game, 2 * ATMOSPHERICS_WORK_SECONDS)
    fresh = state["canisters"][2]
    assert (fresh["label"], fresh["port"], gas_mix.fractions(fresh["mix"]), rack[5]) == (
        "Canister 6", None, {"Oxygen": 1}, None)
    assert gas_mix.total_moles(fresh["mix"]) == pytest.approx(CANISTER_MOLES)
    scientist = next(member for member in game.station_crew if member["post_key"] == ATMOSPHERICS_KEY)["name"]
    assert messages(game)[-1] == ("Atmospherics", f"{scientist} fills Canister 6 with Oxygen and sends it down the tube "
                                                  "to the Combustion Engine.")

    at(game, 3 * ATMOSPHERICS_WORK_SECONDS)
    assert state["canisters"][3] is None

    state["canisters"][0]["mix"] = low("Hydrogen")
    at(game, 4 * ATMOSPHERICS_WORK_SECONDS)
    assert state["canisters"][3] is None and len(game._messages) == 1

    rack[5] = new_canister(7)
    stock = atmos["stock"]["Hydrogen"]
    at(game, 5 * ATMOSPHERICS_WORK_SECONDS)
    fresh = state["canisters"][3]
    assert (fresh["label"], gas_mix.fractions(fresh["mix"])) == ("Canister 7", {"Hydrogen": 1})
    assert atmos["stock"]["Hydrogen"] == pytest.approx(stock - CANISTER_MOLES)


def test_the_scientist_fills_only_what_the_hydrogen_stock_allows():
    game = new_game()
    state, atmos = engine(game), game.player_data["atmos"]
    state["canisters"][0]["mix"] = low("Hydrogen")
    atmos["canisters"][5] = new_canister(6)
    atmos["stock"]["Hydrogen"] = LOW_MOLES - 1
    assert send_fresh_canister(atmos, state) is None
    assert gas_mix.total_moles(atmos["canisters"][5]["mix"]) == 0 and atmos["stock"]["Hydrogen"] == LOW_MOLES - 1

    atmos["stock"]["Hydrogen"] = LOW_MOLES + 1
    canister, gas = send_fresh_canister(atmos, state)
    assert (gas, gas_mix.total_moles(canister["mix"]), atmos["stock"]["Hydrogen"]) == (
        "Hydrogen", pytest.approx(LOW_MOLES + 1), 0)


def test_a_full_canister_on_the_rack_goes_as_it_is_and_nothing_goes_to_a_full_bay():
    game = new_game()
    state, atmos = engine(game), game.player_data["atmos"]
    state["canisters"][1]["mix"] = low("Oxygen")
    atmos["canisters"][5] = None
    oxygen = atmos["canisters"][2]
    held = gas_mix.total_moles(oxygen["mix"])
    assert send_fresh_canister(atmos, state) == (oxygen, "Oxygen")
    assert (state["canisters"][2], gas_mix.total_moles(oxygen["mix"])) == (oxygen, held)

    state["canisters"][1]["mix"] = low("Oxygen")
    state["canisters"][2]["mix"] = low("Oxygen")
    state["canisters"][3] = new_canister("E4")
    atmos["canisters"][5] = new_canister(6)
    assert send_fresh_canister(atmos, state) is None and atmos["canisters"][5] is not None


def test_the_npc_engineer_sends_empty_canisters_back_to_atmospherics():
    game = only_working(new_game(), "Engineer")
    state, rack = engine(game), game.player_data["atmos"]["canisters"]
    used = new_canister("E3", {"Hydrogen": 1.0})
    used["mix"] = low("Hydrogen")
    full = new_canister("E4", {"Oxygen": 1.0})
    state["canisters"][2:] = [used, full]
    state["canisters"][0]["mix"] = low("Hydrogen")

    at(game, ENGINEER_WORK_SECONDS)
    assert state["canisters"][2] is used and game._messages == []

    rack[5] = None
    at(game, 2 * ENGINEER_WORK_SECONDS)
    assert (rack[5], state["canisters"][2:]) == (used, [None, full])
    assert messages(game)[-1] == ("Engineering", f"{crew(game, 'Engineer')['name']} sends the empty Canister E3 back "
                                                 "down the tube to Atmospherics.")

    at(game, 3 * ENGINEER_WORK_SECONDS)
    assert state["canisters"][0]["port"] == "fuel" and len(game._messages) == 1


def test_a_canister_goes_round_between_the_engine_and_atmospherics():
    game = new_game()
    state, atmos = engine(game), game.player_data["atmos"]
    first = state["canisters"][1]
    first["mix"] = low("Oxygen")
    fresh, _ = send_fresh_canister(atmos, state)
    connect(state, fresh, "oxidizer")
    assert send_back_empty(state, atmos["canisters"]) is first and atmos["canisters"][5] is first

    fresh["mix"] = low("Oxygen")
    again, _ = send_fresh_canister(atmos, state)
    assert again is first and gas_mix.total_moles(first["mix"]) == pytest.approx(CANISTER_MOLES)
