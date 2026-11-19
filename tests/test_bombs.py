import pytest
from flask import render_template

from helpers import (
    at,
    choose,
    ctx,
    feedback,
    item_action,
    messages,
    new_game,
    open_station,
    reopen,
    select_item,
    tank_mix,
)
from space_online.game.helper_methods import bombs, gas_mix, random_events
from space_online.game.helper_methods.antagonists import THREAT_TYPES, tick_threats
from space_online.game.helper_methods.bombs import (
    BLAST_SIZES,
    CREW_HARM,
    CRIME,
    DUD_HOT_TEMP,
    MAX_RANGE_LOG,
    PLANTED_TIMER,
    PLAYER_HARM,
    RANGE_BOUNTY,
    TIMER_SECONDS,
    blast_of,
    detonate,
    floor_label,
    new_bomb,
    planted_bomb,
    tick_bombs,
)
from space_online.game.helper_methods.random_events import build_job_event
from space_online.game.helper_methods.rounds import ANTAGONIST, PEACEFUL, round_over
from space_online.game.maps import donut
from space_online.game.maps.donut import ATMOSPHERICS_KEY, BAR_KEY, KITCHEN_KEY, QUARTERS_KEY, RESEARCH_KEY
from space_online.game.objects.gases import GAS_TANK, ROOM_TEMP
from space_online.game.objects.items import BOMB_ID, GAS_TANK_ID, TRANSFER_VALVE_ID, add_to_inventory, get_item_definition
from space_online.game.special_rooms.engineering import FABRICATABLE_ITEM_IDS, FABRICATION_ORE

HALL = donut.location_key(donut.location_from_tile(donut.ROOMS[BAR_KEY].hallway))


def hot_bomb(fill=1.0, oxidizer=None):
    """Plasma at 500 K on one side and an oxidizer at room temperature on the other, both at `fill`."""
    other = gas_mix.mix_of(oxidizer or {"Oxygen": 1},
                           gas_mix.moles_at(fill * GAS_TANK["rated"], GAS_TANK["volume"], ROOM_TEMP), ROOM_TEMP)
    return new_bomb([tank_mix("Plasma", fill, 500), other])


def dud():
    """Plasma and Oxygen, both full and at room temperature: too cold to burn."""
    return new_bomb([tank_mix("Plasma"), tank_mix("Oxygen")])


def tank(contents):
    item = get_item_definition(GAS_TANK_ID)
    item["attributes"]["contents"] = contents
    return item


def ids(items):
    return [item["id"] for item in items]


def spot(key):
    """The location of room key, or of the Bar's hallway tile for HALL."""
    if key in donut.ROOMS:
        return donut.location_from_key(key)
    return donut.location_from_tile(donut.ROOMS[BAR_KEY].hallway)


def stand_in(game, key):
    game.player_data["location"] = spot(key)
    return game


def first_limb(monkeypatch):
    monkeypatch.setattr(bombs.random, "choice", lambda options: options[0])


def open_valve(game):
    """Open the valve of the carried bomb at index 0 and confirm it."""
    item_action(game, 0, "open_transfer_valve")
    choose(game, "Open It")


def carrying_bomb(bomb, **kwargs):
    game = new_game(**kwargs)
    add_to_inventory(game.player_data, bomb)
    return game


def loose_threat(kind="Alien", **changes):
    return {"type": kind, "crew_name": None, "name": f"the {kind}", "acts": 1, "revealed": True,
            "hp": THREAT_TYPES[kind]["hp"], "location": None, "fate": None, **changes}


# --- The valve and putting a bomb together --------------------------------------------------------------------------

def test_the_valve_is_free_once_a_shift_at_the_tank_rack_and_more_come_from_the_fabricator():
    game = stand_in(new_game("Science", "Scientist", post=ATMOSPHERICS_KEY), ATMOSPHERICS_KEY)
    open_station(game, "atmospherics_station", "take_tanks")
    assert TRANSFER_VALVE_ID in ids(game.player_data["inventory"])
    assert messages(game)[-1] == ("Tank Rack", "You take the shift's one Tank Transfer Valve from the rack. The "
                                               "fabricator in Engineering makes more.")
    game.player_data["inventory"] = []
    game.perform("room.take_tanks", {})
    assert ids(game.player_data["inventory"]) == [GAS_TANK_ID, "gas_analyzer"]
    assert TRANSFER_VALVE_ID in FABRICATABLE_ITEM_IDS["Tool"] and FABRICATION_ORE[TRANSFER_VALVE_ID] == 3


def assembly(*contents):
    """A game carrying a valve and a Gas Tank of each of contents, with the valve's panel open from its Use action."""
    game = new_game()
    add_to_inventory(game.player_data, get_item_definition(TRANSFER_VALVE_ID))
    for gas in contents:
        add_to_inventory(game.player_data, tank(gas))
    item_action(game, 0, "use")
    return game


def test_using_the_valve_picks_two_carried_tanks_by_their_pressure_and_assembles_one_bomb():
    plasma, oxygen, spare = tank_mix("Plasma", 1, 500), tank_mix("Oxygen", 1), tank_mix("Nitrogen", 0.5)
    game = assembly(plasma, oxygen, spare)
    assert game.view()["panel"]["type"] == "transfer_valve"
    assert [row["label"] for row in ctx(game)["tanks"]] == ["Gas Tank: 1000.0 kPa", "Gas Tank: 1000.0 kPa",
                                                             "Gas Tank: 500.0 kPa"]
    game.perform("panel.assemble", {})
    assert feedback(game) == "Pick two Gas Tanks you carry, and carry a Tank Transfer Valve."
    for index in (1, 2, 3, 0):
        game.perform("panel.pick_tank", {"index": index})
    assert ctx(game)["picked"] == [2, 3] and ctx(game)["can_assemble"]
    game.perform("panel.pick_tank", {"index": 3})
    game.perform("panel.pick_tank", {"index": 1})
    assert ctx(game)["picked"] == [2, 1]
    game.perform("panel.assemble", {})
    inventory = game.player_data["inventory"]
    assert ids(inventory) == [GAS_TANK_ID, BOMB_ID]
    assert inventory[1]["attributes"]["contents"] == [oxygen, plasma]
    assert inventory[0]["attributes"]["contents"] == spare
    assert ctx(game)["picked"] == [] and ctx(game)["bombs"] == [{"index": 1, "label": "Transfer Valve Bomb",
                                                                 "armed": False}]


def test_taking_an_unarmed_bomb_apart_gives_the_valve_and_both_tanks_back_with_their_gas():
    bomb = hot_bomb()
    game = carrying_bomb(bomb)
    item_action(game, 0, "use")
    game.perform("panel.take_apart", {"index": 0})
    inventory = game.player_data["inventory"]
    assert ids(inventory) == [TRANSFER_VALVE_ID, GAS_TANK_ID, GAS_TANK_ID]
    assert [item["attributes"]["contents"] for item in inventory[1:]] == bomb["attributes"]["contents"]
    assert ctx(game)["has_valve"] and not ctx(game)["can_assemble"]


def test_an_armed_bomb_has_to_be_disarmed_before_it_comes_apart():
    game = carrying_bomb(hot_bomb())
    item_action(game, 0, "set_timer")
    choose(game, "30 seconds")
    game.open_panel("transfer_valve")
    assert ctx(game)["bombs"][0]["armed"]
    game.perform("panel.take_apart", {"index": 0})
    assert feedback(game) == "Disarm the bomb before you take it apart."
    assert ids(game.player_data["inventory"]) == [BOMB_ID]


def test_the_valve_panel_closes_once_there_is_no_valve_or_bomb_to_work_on():
    game = assembly()
    game.player_data["inventory"] = []
    assert game.view()["panel"]["type"] == "inventory"


def test_examining_a_bomb_reads_both_gauges_and_the_analyzer_reads_each_side():
    game = carrying_bomb(new_bomb([tank_mix("Plasma", 0.5, 500), tank_mix("Oxygen", 1)]))
    select_item(game, 0)
    game.perform("panel.examine", {})
    assert messages(game)[-1][1].endswith("Its two tanks' gauges read 500.0 kPa and 1000.0 kPa.")
    add_to_inventory(game.player_data, get_item_definition("gas_analyzer"))
    item_action(game, 1, "use")
    lines = messages(game)[-1][1].split("\n")
    assert lines[1:] == ["Bomb tank 1: 500.0 kPa, 500 K: Plasma 100.0%",
                         "Bomb tank 2: 1000.0 kPa, 293 K: Oxygen 100.0%"]


# --- What opening the valve would do -----------------------------------------------------------------------------

def test_the_blast_sizes_rise_clear_of_an_unburnt_merge():
    unburnt = new_bomb([tank_mix("Plasma", 1, 500), tank_mix("Nitrogen", 1)])
    assert 1 < blast_of(unburnt)["pressure"] / GAS_TANK["rated"] < dict(BLAST_SIZES)["Small"]


@pytest.mark.parametrize("fill, size", [(1.0, "Large"), (0.5, "Medium"), (0.25, "Small"), (0.1, "Dud")])
def test_more_gas_at_the_clean_ratio_gives_a_bigger_blast(fill, size):
    assert blast_of(hot_bomb(fill))["size"] == size


def test_the_same_gas_diluted_with_nitrogen_gives_a_smaller_blast():
    clean, diluted = blast_of(hot_bomb()), blast_of(hot_bomb(oxidizer={"Oxygen": 0.5, "Nitrogen": 0.5}))
    assert diluted["pressure"] < clean["pressure"]
    assert (clean["size"], diluted["size"]) == ("Large", "Medium")


def test_working_out_a_blast_leaves_the_bomb_as_it_was():
    bomb = hot_bomb()
    before = [dict(side, moles=dict(side["moles"])) for side in bomb["attributes"]["contents"]]
    blast_of(bomb)
    assert bomb["attributes"]["contents"] == before


# --- What a blast does ---------------------------------------------------------------------------------------------

def crew_at(game, key, count=1):
    crew = game.station_crew[:count]
    for npc in crew:
        npc["location"] = spot(key)
    return crew


@pytest.mark.parametrize("fill, size", [(0.25, "Small"), (0.5, "Medium")])
def test_a_small_or_medium_blast_in_a_room_starts_a_fire_and_hurts_everyone_there(monkeypatch, fill, size):
    first_limb(monkeypatch)
    game = stand_in(new_game(), KITCHEN_KEY)
    (npc,) = crew_at(game, KITCHEN_KEY)
    bystander = game.station_crew[1]
    detonate(game, hot_bomb(fill), KITCHEN_KEY)
    assert game.ship_map[KITCHEN_KEY]["hazard"] == "fire"
    burn, limb = PLAYER_HARM[size]
    assert (game.player_data["damage"]["burn"], game.player_data["limbs"]["head"]) == (burn, 100 - limb)
    crew_burn, crew_limb = CREW_HARM[size]
    assert (npc["damage"]["burn"], npc["limbs"]["head"]) == (crew_burn, 100 - crew_limb)
    assert bystander["limbs"]["head"] == 100 and bystander["damage"]["burn"] == 0
    assert messages(game)[0][1].startswith(f"A transfer valve bomb goes off in the Kitchen: a {size} blast at ")
    assert messages(game)[-1] == ("Explosion", f"The blast burns you. Burn damage: {burn}%. It catches your head, "
                                               f"which is at {100 - limb}%.")


def test_a_large_blast_breaches_the_hull_and_kills_the_crew_in_the_room(monkeypatch):
    first_limb(monkeypatch)
    game = new_game()
    crew_at(game, KITCHEN_KEY, 2)
    victims = [npc for npc in game.station_crew if donut.location_key(npc["location"]) == KITCHEN_KEY]
    names = [npc["name"] for npc in victims]
    detonate(game, hot_bomb(), KITCHEN_KEY)
    assert game.ship_map[KITCHEN_KEY]["hazard"] == "breach"
    assert not set(names) & {npc["name"] for npc in game.station_crew}
    assert [message for _, message in messages(game) if "killed" in message] == [
        f"{npc['name']} ({npc['job']}) was killed in the blast." for npc in victims]
    assert game.player_data["damage"]["burn"] == 0


def test_a_hidden_threat_killed_in_a_blast_is_over(monkeypatch):
    game = new_game(mode=ANTAGONIST)
    (host,) = crew_at(game, KITCHEN_KEY)
    hidden = loose_threat("Traitor", crew_name=host["name"], name=f"{host['name']} the Traitor", revealed=False)
    other = loose_threat("Traitor", crew_name="Somebody Else", revealed=False)
    game.player_data["threats"] = [hidden, other]
    detonate(game, hot_bomb(), KITCHEN_KEY)
    assert (hidden["fate"], other["fate"]) == ("killed by a bomb before it was found out", None)


def test_a_blast_on_a_hallway_tile_sets_no_hazard_and_only_hits_who_is_on_that_tile(monkeypatch):
    first_limb(monkeypatch)
    game = stand_in(new_game(), HALL)
    (npc,) = crew_at(game, HALL)
    detonate(game, hot_bomb(0.5), HALL)
    assert not any(place.get("hazard") for place in game.ship_map.values())
    assert npc["limbs"]["head"] == 100 - CREW_HARM["Medium"][1]
    assert game.player_data["damage"]["burn"] == PLAYER_HARM["Medium"][0]


def test_a_room_without_hazards_still_hits_whoever_is_in_it(monkeypatch):
    first_limb(monkeypatch)
    game = stand_in(new_game(), QUARTERS_KEY)
    detonate(game, hot_bomb(0.25), QUARTERS_KEY)
    assert game.ship_map[QUARTERS_KEY].get("hazard") is None
    assert game.player_data["damage"]["burn"] == PLAYER_HARM["Small"][0]


def test_a_player_away_on_the_mining_planet_is_not_hit_by_a_blast_in_the_mining_bay():
    game = stand_in(new_game(), donut.MINING_KEY)
    game.player_data["mining"]["expedition"] = {"haul": {}, "artifacts": 0}
    detonate(game, hot_bomb(), donut.MINING_KEY)
    assert not round_over(game.player_data) and game.player_data["damage"]["burn"] == 0


@pytest.mark.parametrize("fill, left", [(0.25, 0.75), (0.5, 0.5)])
def test_a_revealed_antagonist_on_the_tile_loses_a_share_of_its_full_health(fill, left):
    game = new_game(mode=ANTAGONIST)
    alien = loose_threat(location=spot(HALL))
    elsewhere = loose_threat("Wizard", location=donut.location_from_key(KITCHEN_KEY))
    hidden = loose_threat("Traitor", revealed=False, location=None)
    game.player_data["threats"] = [alien, elsewhere, hidden]
    detonate(game, hot_bomb(fill), HALL)
    assert alien["hp"] == round(left * THREAT_TYPES["Alien"]["hp"]) and alien["fate"] is None
    assert (elsewhere["hp"], hidden["hp"]) == (THREAT_TYPES["Wizard"]["hp"], THREAT_TYPES["Traitor"]["hp"])
    assert "The blast catches the Alien, which is hurt but still loose." in [message for _, message in messages(game)]


def test_a_large_blast_destroys_a_revealed_antagonist():
    game = new_game(mode=ANTAGONIST)
    alien = loose_threat(location=spot(HALL))
    game.player_data["threats"] = [alien]
    detonate(game, hot_bomb(), HALL)
    assert alien["fate"] == "destroyed by a bomb"
    assert game.player_data["round"]["resolved_at"] is not None
    assert ("Explosion", "The blast destroys the Alien.") in messages(game)


def test_a_dud_vents_into_the_station_air_and_leaves_its_valve_and_empty_tanks():
    game = stand_in(new_game(), KITCHEN_KEY)
    bomb = dud()
    plasma = gas_mix.total_moles(bomb["attributes"]["contents"][0])
    detonate(game, bomb, BAR_KEY)
    assert game.player_data["atmos"]["air"]["moles"]["Plasma"] == pytest.approx(plasma)
    floor = game.player_data["floor"][BAR_KEY]
    assert ids(floor) == [TRANSFER_VALVE_ID, GAS_TANK_ID, GAS_TANK_ID]
    assert all(not gas_mix.total_moles(item["attributes"]["contents"]) for item in floor[1:])
    assert game.ship_map[BAR_KEY].get("hazard") is None
    assert messages(game)[0][1].startswith("A transfer valve bomb fizzles in the Bar: a Dud at 293 K")


def test_a_hot_dud_scalds_whoever_holds_it_and_a_cold_one_does_not():
    cold_game = stand_in(new_game(), BAR_KEY)
    detonate(cold_game, dud(), BAR_KEY)
    assert cold_game.player_data["damage"]["burn"] == 0
    game = stand_in(new_game(), BAR_KEY)
    hot = new_bomb([tank_mix("Plasma", 1, 500), tank_mix("Nitrogen", 1)])
    assert blast_of(hot)["size"] == "Dud" and blast_of(hot)["temp"] >= DUD_HOT_TEMP
    detonate(game, hot, BAR_KEY)
    assert game.player_data["damage"]["burn"] == PLAYER_HARM["Dud"][0]
    assert messages(game)[-1] == ("Explosion", f"The blast burns you. Burn damage: {PLAYER_HARM['Dud'][0]}%.")


def test_a_large_blast_in_your_hands_kills_you_outside_a_peaceful_round(monkeypatch):
    game = carrying_bomb(hot_bomb(), mode=ANTAGONIST)
    item_action(game, 0, "open_transfer_valve")
    choose(game, "Leave It")
    assert ids(game.player_data["inventory"]) == [BOMB_ID]
    open_valve(game)
    outcome = game.player_data["round"]["outcome"]
    assert (outcome["survived"], outcome["cause"]) == (False, "killed by a transfer valve bomb")
    assert game.player_data["inventory"] == []


def test_a_large_blast_in_your_hands_only_badly_hurts_you_in_a_peaceful_round(monkeypatch):
    first_limb(monkeypatch)
    game = carrying_bomb(hot_bomb(), mode=PEACEFUL)
    open_valve(game)
    assert not round_over(game.player_data)
    burn, limb = PLAYER_HARM["Large"]
    assert (game.player_data["damage"]["burn"], game.player_data["limbs"]["head"]) == (burn, 100 - limb)


def test_a_stale_choice_for_a_bomb_no_longer_carried_does_nothing():
    game = carrying_bomb(hot_bomb())
    item_action(game, 0, "open_transfer_valve")
    game.player_data["inventory"] = []
    choose(game, "Open It")
    assert "Explosion" not in [title for title, _ in messages(game)]


# --- The law ---------------------------------------------------------------------------------------------------

def test_setting_off_a_bomb_with_no_revealed_threat_loose_is_a_crime_even_a_dud():
    game = carrying_bomb(dud())
    open_valve(game)
    assert (game.player_data["warrant"], game.player_data["warrant_reason"]) == (True, CRIME)
    assert messages(game)[-1][1].endswith(
        "No threat is loose on the station, so it was unauthorized: there is a warrant out for you.")


def test_with_a_revealed_threat_loose_a_bomb_is_no_crime_wherever_it_goes_off():
    game = carrying_bomb(dud(), mode=ANTAGONIST)
    game.player_data["threats"] = [loose_threat(location=donut.location_from_key(KITCHEN_KEY))]
    open_valve(game)
    assert not game.player_data["warrant"]
    assert messages(game)[-1][1].endswith("With a threat loose on the station, Security lets it pass.")


def test_a_hidden_threat_does_not_make_a_bomb_lawful_and_a_bomb_someone_else_armed_is_not_yours():
    game = carrying_bomb(dud(), mode=ANTAGONIST)
    game.player_data["threats"] = [loose_threat("Traitor", revealed=False)]
    detonate(game, planted_bomb(game, "the Traitor"), BAR_KEY)
    assert not game.player_data["warrant"]
    open_valve(game)
    assert game.player_data["warrant"]


# --- Timers and the floor -------------------------------------------------------------------------------------

def test_a_timed_bomb_left_on_the_floor_goes_off_at_its_tile_when_its_time_is_up():
    game = stand_in(carrying_bomb(dud()), BAR_KEY)
    at(game, 100)
    item_action(game, 0, "set_timer")
    assert game.view()["choice"]["buttons"] == [f"{seconds} seconds" for seconds in TIMER_SECONDS] + ["Cancel"]
    choose(game, "10 seconds")
    assert game.player_data["inventory"][0]["attributes"] == {
        **game.player_data["inventory"][0]["attributes"], "goes_off_at": 110, "armed_by": "Ada"}
    item_action(game, 0, "drop")
    at(game, 103)
    assert game.view()["floor"] == [{"index": 0, "label": "Transfer Valve Bomb (ticking: 7 s)"}]
    game.player_data["location"] = donut.location_from_key(KITCHEN_KEY)
    tick_bombs(game)
    assert ids(game.player_data["floor"][BAR_KEY]) == [BOMB_ID]
    at(game, 110)
    tick_bombs(game)
    assert ids(game.player_data["floor"][BAR_KEY]) == [TRANSFER_VALVE_ID, GAS_TANK_ID, GAS_TANK_ID]
    assert messages(game)[-1][1].startswith("A transfer valve bomb fizzles in the Bar")


def test_a_bomb_disarmed_before_its_time_never_goes_off():
    game = carrying_bomb(hot_bomb())
    item_action(game, 0, "set_timer")
    choose(game, "60 seconds")
    item_action(game, 0, "disarm")
    assert game.player_data["inventory"][0]["attributes"]["goes_off_at"] is None
    assert messages(game)[-1] == ("Transfer Valve Bomb",
                                  "You stop the timer. The bomb is safe until someone arms it again.")
    at(game, 1000)
    tick_bombs(game)
    assert ids(game.player_data["inventory"]) == [BOMB_ID]
    item_action(game, 0, "drop")
    assert game.view()["floor"][0]["label"] == "Transfer Valve Bomb"


def test_an_armed_bomb_picked_up_off_the_floor_goes_off_where_its_carrier_stands(monkeypatch):
    game = stand_in(new_game(), KITCHEN_KEY)
    game.player_data["floor"][BAR_KEY] = [planted_bomb(game, "the Traitor")]
    game.player_data["location"] = donut.location_from_key(BAR_KEY)
    game.perform("game.pick_up", {"index": 0})
    game.player_data["location"] = donut.location_from_key(KITCHEN_KEY)
    at(game, PLANTED_TIMER)
    tick_bombs(game)
    assert game.player_data["inventory"] == []
    assert game.ship_map[KITCHEN_KEY]["hazard"] == "fire" and game.ship_map[BAR_KEY].get("hazard") is None


def test_a_timer_choice_that_is_not_on_the_dial_or_for_a_bomb_no_longer_carried_does_nothing():
    game = carrying_bomb(hot_bomb())
    uid = game.player_data["inventory"][0]["uid"]
    bombs.set_bomb_timer(game, uid, 5)
    bombs.set_bomb_timer(game, "gone", 10)
    assert game.player_data["inventory"][0]["attributes"]["goes_off_at"] is None


def test_the_teleporter_can_deliver_an_armed_bomb_to_any_tile():
    game = stand_in(new_game("Science", "Scientist", post=RESEARCH_KEY), RESEARCH_KEY)
    game.player_data["research"]["tele"] = {"x": {"m": 1, "c": 0}, "y": {"m": 1, "c": 0}}
    add_to_inventory(game.player_data, hot_bomb(0.5))
    item_action(game, 0, "set_timer")
    choose(game, "30 seconds")
    kitchen = donut.location_from_key(KITCHEN_KEY)
    reopen(game, "teleporter")
    game.perform("panel.send_item", {"x": kitchen["x"], "y": kitchen["y"], "item": 0})
    assert ids(game.player_data["floor"][KITCHEN_KEY]) == [BOMB_ID]
    at(game, 30)
    tick_bombs(game)
    assert game.ship_map[KITCHEN_KEY]["hazard"] == "fire"
    assert game.player_data["damage"]["burn"] == 0


# --- The Traitor's bomb ------------------------------------------------------------------------------------------

def test_the_traitor_plants_a_ticking_medium_bomb_in_a_room_and_the_station_is_told(monkeypatch):
    game = new_game(mode=ANTAGONIST)
    traitor = loose_threat("Traitor", crew_name=game.station_crew[0]["name"], revealed=False, acts=0, next_act_at=0,
                     reveal_after=3, objective={"kind": "sabotage", "target": None, "progress": 0}, hurt=[])
    game.player_data["threats"] = [traitor]
    monkeypatch.setattr(bombs.random, "choice", lambda options: next(
        (pick for pick in ("bomb", KITCHEN_KEY) if pick in options), options[0]))
    tick_threats(game)
    (bomb,) = game.player_data["floor"][KITCHEN_KEY]
    assert (bomb["attributes"]["goes_off_at"], blast_of(bomb)["size"]) == (PLANTED_TIMER, "Medium")
    assert game.player_data["incidents"][-1]["what"] == "A device has been found ticking in the Kitchen."
    assert ("Station Incident", "A device has been found ticking in the Kitchen.") in messages(game)
    assert traitor["objective"]["progress"] == 1
    assert "bomb" in THREAT_TYPES["Traitor"]["acts"]


# --- The test range ----------------------------------------------------------------------------------------------

def on_range(*bombs_carried, **kwargs):
    game = stand_in(new_game("Science", "Scientist", post=ATMOSPHERICS_KEY, **kwargs), ATMOSPHERICS_KEY)
    for bomb in bombs_carried:
        add_to_inventory(game.player_data, bomb)
    return open_station(game, "atmospherics_station", "show_test_range")


def run_test(game, index=0):
    """Select the carried bomb at index on the open test range and run it."""
    game.perform("panel.select_bomb", {"index": index})
    game.perform("panel.run_test", {})


def test_the_range_reports_the_blast_detonate_would_produce_and_harms_nothing():
    bomb = hot_bomb()
    game = on_range(bomb)
    expected = blast_of(bomb)
    crew = [dict(npc["limbs"]) for npc in game.station_crew]
    game.perform("panel.run_test", {})
    assert feedback(game) == "Pick a Transfer Valve Bomb you carry first."
    game.perform("panel.select_bomb", {"index": 0})
    assert ctx(game)["selected"] == 0
    game.perform("panel.run_test", {})
    (line,) = ctx(game)["log"]
    assert line.startswith(f"Large: peaked at {expected['temp']:.0f} K and {expected['pressure']:.0f} kPa, "
                           f"{expected['pressure'] / GAS_TANK['rated']:.1f}x the tanks' rating.")
    assert not any(place.get("hazard") for place in game.ship_map.values())
    assert [dict(npc["limbs"]) for npc in game.station_crew] == crew
    assert game.player_data["damage"]["burn"] == 0 and not game.player_data["warrant"]
    inventory = game.player_data["inventory"]
    assert ids(inventory) == [TRANSFER_VALVE_ID, GAS_TANK_ID, GAS_TANK_ID]
    assert all(not gas_mix.total_moles(item["attributes"]["contents"]) for item in inventory[1:])


def test_the_first_test_of_each_size_in_a_shift_pays_the_bounty_and_a_dud_pays_nothing():
    game = on_range(hot_bomb(0.5), hot_bomb(0.5), dud())
    credits = game.player_data["credits"]
    for _ in range(3):
        run_test(game)
    assert game.player_data["credits"] == credits + RANGE_BOUNTY["Medium"]
    assert game.player_data["atmos"]["range_paid"] == ["Medium"]
    log = ctx(game)["log"]
    assert [line.split(":")[0] for line in log] == ["Dud", "Medium", "Medium"]
    assert log[-1].endswith("Central Command pays its 200 credit bounty for a first Medium blast.")
    assert not log[0].endswith("blast.")
    assert {row["size"]: row["paid"] for row in ctx(game)["bounties"]} == {"Small": False, "Medium": True,
                                                                          "Large": False}


def test_the_range_log_keeps_the_last_few_tests():
    game = on_range(*[dud() for _ in range(MAX_RANGE_LOG + 1)])
    for _ in range(MAX_RANGE_LOG + 1):
        run_test(game)
    assert len(ctx(game)["log"]) == MAX_RANGE_LOG
    assert all(line.startswith("Dud:") for line in ctx(game)["log"])


def test_a_scientist_in_atmospherics_is_asked_for_a_bomb_test_and_the_range_finishes_it(monkeypatch):
    game = on_range(hot_bomb(0.25), hot_bomb(0.5))
    picks = iter([random_events._bomb_test_event, "Medium"])
    monkeypatch.setattr(random_events.random, "choice", lambda options: next(picks))
    event = build_job_event(game)
    assert (event["title"], event["desc"]) == (
        "Bomb Test", "Central Command wants a Medium blast tested on the Atmospherics test range. Build a transfer "
                     "valve bomb that size and run it there for 200 credits.")
    event["effect"]()
    (duty,) = game.player_data["duties"]
    assert (duty["kind"], duty["room"], duty["size"], duty["reward"], duty["summary"]) == (
        "bomb_test", ATMOSPHERICS_KEY, "Medium", 200, "Test a Medium bomb on the range (200 cr)")
    credits = game.player_data["credits"]
    run_test(game)
    assert len(game.player_data["duties"]) == 1
    assert game.player_data["credits"] == credits + RANGE_BOUNTY["Small"]
    run_test(game)
    assert game.player_data["duties"] == []
    assert game.player_data["credits"] == credits + RANGE_BOUNTY["Small"] + RANGE_BOUNTY["Medium"] + 200
    assert ("Duty Done", "Central Command has its Medium test and pays you 200 credits.") in messages(game)


# --- The pages ---------------------------------------------------------------------------------------------------

def test_the_panels_render(app):
    game = assembly(tank_mix("Plasma", 1, 500), tank_mix("Oxygen", 1))
    add_to_inventory(game.player_data, hot_bomb())
    game.player_data["inventory"][-1]["attributes"]["goes_off_at"] = 50
    with app.test_request_context():
        html = render_template("panels/transfer_valve.html", p=ctx(game))
        assert "Gas Tank: 1000.0 kPa" in html and "Transfer Valve Bomb (armed)" in html
        reopen(game, "bomb_range")
        game.perform("panel.select_bomb", {"index": 3})
        html = render_template("panels/bomb_range.html", p=ctx(game))
        assert "Run Test" in html and "Small: 100 credits" in html and "No tests run yet." in html
        empty = render_template("panels/transfer_valve.html", p={"tanks": [], "picked": [], "has_valve": False,
                                                                  "can_assemble": False, "bombs": [],
                                                                  "feedback": None})
        assert "You carry no Gas Tank." in empty and "You carry no Tank Transfer Valve." in empty


def test_floor_label_leaves_other_items_alone():
    game = new_game()
    assert floor_label(game.player_data, get_item_definition("medkit")) == "Medkit"
