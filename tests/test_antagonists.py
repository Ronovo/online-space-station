from itertools import count

import pytest

from helpers import at, crew, fix_random, hold, messages, new_game, notes, seated, station, threat
from space_online.game.helper_methods import antagonists, combat
from space_online.game.helper_methods.antagonists import (
    ACTS,
    CREW_ENGAGE_CHANCE,
    MAX_THREATS,
    THREAT_TYPES,
    alert_level,
    new_threats,
    sightings,
    step_threats,
    threat_report,
    threat_score,
    tick_threats,
)
from space_online.game.helper_methods.jail import LAW_ABIDING_JOBS
from space_online.game.helper_methods.power_constants import FAULTABLE_SYSTEMS
from space_online.game.helper_methods.rounds import (
    ANTAGONIST,
    DEPARTURE_HOOKS,
    PEACEFUL,
    SHUTTLE_LOCKOUT_SECONDS,
    SHUTTLE_URGENT_ARRIVAL_SECONDS,
    round_over,
)
from space_online.game.maps.donut import BAR_KEY, DEPARTURES_KEY, location_from_key
from space_online.game.objects.items import add_to_inventory, get_item_definition


def rolls(monkeypatch, **fixed):
    fix_random(monkeypatch, antagonists, combat, **fixed)


def test_a_peaceful_round_has_no_threats():
    game = new_game()
    assert (game.player_data["threats"], new_threats(PEACEFUL, game.station_crew)) == ([], [])
    assert alert_level(game.player_data) == ("Green", "#00FF00")


def test_a_round_has_one_to_three_threats_of_different_kinds():
    for _ in range(20):
        threats = new_game(mode=ANTAGONIST).player_data["threats"]
        kinds = [item["type"] for item in threats]
        assert 1 <= len(threats) <= MAX_THREATS and len(set(kinds)) == len(kinds)
        assert set(kinds) <= set(THREAT_TYPES)


def test_crew_threats_hide_as_a_crew_member_who_does_not_uphold_the_law(monkeypatch):
    game = new_game()
    monkeypatch.setattr(antagonists.random, "sample", lambda kinds, count: ["Vampire", "Wizard", "Traitor"][:count])
    monkeypatch.setattr(antagonists.random, "randint", lambda low, high: high)
    monkeypatch.setattr(antagonists.random, "shuffle", lambda items: None)
    hosts = [npc["name"] for npc in game.station_crew if npc["job"] not in LAW_ABIDING_JOBS]
    vampire, wizard, traitor = new_threats(ANTAGONIST, game.station_crew)
    assert (vampire["crew_name"], vampire["name"]) == (hosts[-1], f"{hosts[-1]} the Vampire")
    assert (wizard["crew_name"], wizard["name"]) == (None, "the Wizard")
    assert traitor["crew_name"] == hosts[-2]
    assert (vampire["starts_at"], wizard["starts_at"]) == (antagonists.FIRST_START_RANGE_SECONDS[1],
                                                           antagonists.LATER_START_RANGE_SECONDS[1])
    assert (vampire["hp"], vampire["acts"], vampire["revealed"], vampire["fate"]) == (55, 0, False, None)


def test_a_crew_threat_with_nobody_to_hide_as_comes_from_outside(monkeypatch):
    guards = [npc for npc in new_game().station_crew if npc["job"] in LAW_ABIDING_JOBS]
    monkeypatch.setattr(antagonists.random, "sample", lambda kinds, count: ["Traitor"])
    monkeypatch.setattr(antagonists.random, "randint", lambda low, high: low)
    (traitor,) = new_threats(ANTAGONIST, guards)
    assert (traitor["crew_name"], traitor["name"]) == (None, "the Traitor")


@pytest.mark.parametrize("acts, revealed, level", [
    (0, False, "Green"), (1, False, "Yellow"), (2, False, "Yellow"), (3, False, "Orange"),
    (1, True, "Orange"), (5, False, "Orange"), (6, False, "Red"), (4, True, "Red"),
])
def test_the_alert_rises_with_what_loose_threats_have_done(acts, revealed, level):
    game = station(threat(acts=acts, revealed=revealed, location={"x": 0, "y": 0}))
    assert alert_level(game.player_data)[0] == level


def test_a_threat_that_has_been_dealt_with_no_longer_counts():
    game = station(threat(acts=9, fate="destroyed by you"), threat("Alien", acts=1))
    assert (threat_score(game.player_data), alert_level(game.player_data)[0]) == (1, "Yellow")


def test_a_threat_waits_for_its_time_then_acts_in_secret(monkeypatch):
    game = station(threat("Alien", starts_at=300, next_act_at=300))
    rolls(monkeypatch)
    tick_threats(at(game, 299))
    assert (game.player_data["threats"][0]["acts"], game._messages) == (0, [])
    tick_threats(at(game, 300))
    victim = game.station_crew[0]
    assert messages(game) == [("Station Incident", f"{victim['name']} was found badly hurt."),
                              ("Station Alert", "The station is now at Yellow alert.")]
    assert victim["limbs"]["head"] == 100 - antagonists.VICTIM_LIMB_RANGE[1]
    acted = game.player_data["threats"][0]
    assert (acted["acts"], acted["next_act_at"], acted["revealed"]) == (
        1, 300 + antagonists.ACT_GAP_RANGE_SECONDS[1], False)
    assert notes(game)[-1] == f"{victim['name']} was found badly hurt."


def test_what_each_kind_of_move_does(monkeypatch):
    game = station(threat())
    rolls(monkeypatch)
    wizard = game.player_data["threats"][0]
    victim = game.station_crew[0]
    power = game.player_data["station_power"]

    assert ACTS["poison"](game, wizard) == (f"{victim['name']} has been poisoned.", "Bridge")
    victim["location"] = {"x": 0, "y": 3}
    assert ACTS["burn"](game, wizard) == (f"{victim['name']} was found badly burned again.", "Bar Entrance")
    assert (victim["damage"]["poison"], victim["damage"]["burn"]) == (20, 20)

    assert ACTS["sabotage"](game, wizard) == (
        "Someone has sabotaged the Hallway Lighting. It needs repairing from the Engineering Panel.", "Engineering Bay")
    assert power["faults"] == [FAULTABLE_SYSTEMS[0]]

    framed = next(npc for npc in game.station_crew if npc["job"] not in LAW_ABIDING_JOBS)
    assert ACTS["frame"](game, wizard) == (
        f"A warrant has gone out for {framed['name']} for sabotage, on evidence nobody can trace.", "Security")
    assert (framed["warrant"], framed["warrant_reason"]) == (True, "Sabotage (anonymous tip)")

    power["system_levels"]["hallway_lighting"] = 5
    assert ACTS["dim"](game, wizard) == ("The lights flicker and dim across the station.", "the hallways")
    assert power["system_levels"]["hallway_lighting"] == 2

    assert ACTS["steal"](game, wizard) == ("300 credits have vanished from your account.", "your quarters")
    assert game.player_data["credits"] == 700


def test_dimming_remembers_the_lighting_from_before_the_first_dim():
    game = station(threat("Cultist"))
    cultist = game.player_data["threats"][0]
    power = game.player_data["station_power"]
    power["system_levels"]["hallway_lighting"] = 6
    ACTS["dim"](game, cultist)
    ACTS["dim"](game, cultist)
    assert (power["system_levels"]["hallway_lighting"], power["dimmed_from"]) == (1, 6)
    assert ACTS["dim"](game, cultist) is None
    assert power["dimmed_from"] == 6


def test_a_move_that_has_nothing_left_to_do_passes_quietly(monkeypatch):
    game = station(threat("Rogue Bot"))
    rolls(monkeypatch)
    bot = game.player_data["threats"][0]
    power = game.player_data["station_power"]
    power["faults"] = list(FAULTABLE_SYSTEMS)
    power["solar_charging"] = True
    assert ACTS["sabotage"](game, bot) == ("Someone has cut the engine's coolant line.", "Engineering Bay")
    assert game.player_data["engine"]["coolant_fault"]
    assert ACTS["sabotage"](game, bot) == ("The solar array has been shut down from outside Engineering.",
                                           "Engineering Bay")
    assert ACTS["sabotage"](game, bot) is None
    power["system_levels"]["hallway_lighting"] = 1
    assert ACTS["dim"](game, bot) is None
    game.player_data["credits"] = 0
    assert ACTS["steal"](game, bot) is None
    for npc in game.station_crew:
        npc["warrant"] = True
    assert ACTS["frame"](game, bot) is None
    game.player_data["station_crew"] = []
    assert (ACTS["maul"](game, bot), ACTS["poison"](game, bot)) == (None, None)

    tick_threats(game)
    assert (bot["acts"], messages(game)) == (1, [("Station Alert", "The station is now at Yellow alert.")])


def test_a_hidden_crew_member_shows_itself_by_attacking(monkeypatch):
    game = station()
    host = crew(game, "Bartender")
    game.player_data["threats"] = [threat("Vampire", crew_name=host["name"], acts=2)]
    rolls(monkeypatch)
    monkeypatch.setattr(antagonists, "pick_random_hallway_location", lambda: {"x": 0, "y": 3})
    tick_threats(game)
    vampire = game.player_data["threats"][0]
    assert host not in game.station_crew
    victim = game.station_crew[0]
    message = (f"{victim['name']} was attacked in the Bar Entrance! {host['name']} (Bartender) is the Vampire. "
               "Security is hunting them.")
    assert messages(game) == [("Threat Revealed", message), ("Station Alert", "The station is now at Orange alert.")]
    assert (vampire["revealed"], vampire["location"], vampire["acts"]) == (True, {"x": 0, "y": 3}, 3)
    assert victim["limbs"]["head"] < 100
    assert sightings(game.player_data) == [f"{host['name']} the Vampire was last seen in the Bar Entrance."]


def test_an_outsider_shows_itself_too_even_with_nobody_left_to_attack(monkeypatch):
    game = station(threat(acts=2))
    game.player_data["station_crew"] = []
    rolls(monkeypatch)
    monkeypatch.setattr(antagonists, "pick_random_hallway_location", lambda: {"x": 0, "y": 3})
    tick_threats(game)
    assert messages(game) == [("Threat Revealed", "There has been an attack in the Bar Entrance! The Wizard is aboard. "
                                                 "Security is hunting them."),
                              ("Station Alert", "The station is now at Orange alert.")]


def test_a_revealed_threat_keeps_making_moves_in_the_open(monkeypatch):
    game = station(threat("Alien", acts=3, revealed=True, location={"x": 5, "y": 5}))
    rolls(monkeypatch)
    tick_threats(game)
    victim = game.station_crew[0]
    assert messages(game) == [("Station Incident",
                               f"The Alien strikes again. {victim['name']} was found badly hurt."),
                              ("Station Alert", "The station is now at Red alert.")]


def test_red_alert_calls_the_shuttle_urgently_once_the_lockout_is_over(monkeypatch):
    game = station(threat(acts=6, next_act_at=10 ** 6))
    rolls(monkeypatch)
    tick_threats(at(game, SHUTTLE_LOCKOUT_SECONDS - 1))
    shuttle = game.player_data["round"]["shuttle"]
    assert shuttle["state"] == "idle"
    tick_threats(at(game, SHUTTLE_LOCKOUT_SECONDS))
    assert (shuttle["state"], shuttle["travel"]) == ("called", SHUTTLE_URGENT_ARRIVAL_SECONDS)
    assert "the station is at Red alert" in messages(game)[-1][1]


def test_threats_stop_when_the_round_is_over(monkeypatch):
    game = station(threat())
    rolls(monkeypatch)
    game.player_data["round"]["outcome"] = {"survived": True, "cause": "", "seconds": 0}
    tick_threats(game)
    assert game.player_data["threats"][0]["acts"] == 0


def revealed(kind="Wizard", **changes):
    return threat(kind, **{"acts": 3, "revealed": True, "location": {"x": 5, "y": 5}, "next_act_at": 10 ** 6,
                           **changes})


def test_a_revealed_threat_roams_the_hallways(monkeypatch):
    game = station(revealed(), threat("Alien", acts=1))
    rolls(monkeypatch, roll=CREW_ENGAGE_CHANCE)
    step_threats(game)
    wizard, alien = game.player_data["threats"]
    assert wizard["location"] in ({"x": 4, "y": 5}, {"x": 5, "y": 4})
    assert (alien["location"], wizard["hp"]) == (None, 45)


def test_security_and_the_captain_wear_a_revealed_threat_down(monkeypatch):
    game = station(revealed())
    rolls(monkeypatch)
    responder = next(npc for npc in game.station_crew if npc["job"] in LAW_ABIDING_JOBS)
    step_threats(game)
    wizard = game.player_data["threats"][0]
    assert (wizard["hp"], responder["limbs"]["head"], wizard["fate"]) == (45 - 16, 85, None)
    step_threats(game)
    step_threats(game)
    assert wizard["fate"] == f"arrested by {responder['name']}"
    assert messages(game)[-1] == ("Security Report",
                                  f"{responder['name']} ({responder['job']}) has arrested the Wizard.")
    assert game.player_data["round"]["resolved_at"] == 0
    assert alert_level(game.player_data)[0] == "Green"
    hp = wizard["hp"]
    step_threats(game)
    assert wizard["hp"] == hp


def test_the_crew_destroy_what_cannot_be_arrested_and_the_round_goes_on_while_others_are_loose(monkeypatch):
    game = station(revealed("Alien", hp=10), threat("Traitor", acts=1))
    rolls(monkeypatch)
    step_threats(game)
    alien = game.player_data["threats"][0]
    assert alien["fate"].startswith("destroyed by ")
    assert game.player_data["round"]["resolved_at"] is None


def test_nobody_responds_without_security_or_a_captain(monkeypatch):
    game = station(revealed())
    game.player_data["station_crew"] = [npc for npc in game.station_crew if npc["job"] not in LAW_ABIDING_JOBS]
    rolls(monkeypatch)
    step_threats(game)
    assert game.player_data["threats"][0]["hp"] == 45


def test_a_revealed_threat_on_your_hallway_tile_attacks_you(monkeypatch):
    game = station(revealed(location={"x": 1, "y": 0}))
    game.player_data["location"] = {"x": 0, "y": 0}
    rolls(monkeypatch, roll=1.0)
    game.perform("game.move", {"direction": "north"})
    fight = game.player_data["fight"]
    assert (fight["kind"], fight["threat"], fight["enemy"]["name"], fight["enemy"]["hp"]) == (
        "threat", 0, "the Wizard", 45)
    assert fight["log"] == ["The Wizard is here, and comes straight at you!"]
    assert game._messages == []


def test_a_threat_elsewhere_on_the_station_leaves_you_alone(monkeypatch):
    game = station(revealed(location={"x": 5, "y": 5}), threat("Alien", acts=1))
    game.player_data["location"] = {"x": 0, "y": 0}
    rolls(monkeypatch, roll=1.0)
    game.perform("game.move", {"direction": "north"})
    assert (game.player_data["fight"], game.player_data["location"]) == (None, {"x": 1, "y": 0})


def test_threats_walking_onto_your_tile_attack_too_but_rooms_are_safe(monkeypatch):
    game = station(revealed(location={"x": 5, "y": 4}))
    fix_random(monkeypatch, antagonists, roll=1.0, pick=lambda options: (5, 5))
    game.player_data["location"] = location_from_key(BAR_KEY)
    step_threats(game)
    assert game.player_data["fight"] is None
    game.player_data["location"] = {"x": 5, "y": 5}
    step_threats(game)
    assert game.player_data["fight"]["enemy"]["name"] == "the Wizard"
    game.player_data["fight"]["log"] = ["still fighting"]
    step_threats(game)
    assert game.player_data["fight"]["log"] == ["still fighting"]


def duel(monkeypatch, kind="Wizard", **hands):
    game = station(revealed(kind, location={"x": 0, "y": 0}), department="Security", job="Security Guard")
    game.player_data["location"] = {"x": 0, "y": 0}
    hold(game, **hands)
    rolls(monkeypatch, randint=lambda low, high: low)
    antagonists.check_threat_encounter(game)
    return game


def test_beating_a_threat_arrests_or_destroys_it(monkeypatch):
    game = duel(monkeypatch, left="energy_sword", right="fire_axe")
    game.perform("fight.attack", {})
    game.perform("fight.attack", {})
    wizard = game.player_data["threats"][0]
    assert (game.player_data["fight"], wizard["fate"]) == (None, "beaten and arrested by you")
    assert messages(game)[-1] == ("Threat Dealt With", "You have beaten and arrested the Wizard.")
    assert game.player_data["round"]["resolved_at"] == 0

    game = duel(monkeypatch, "Alien", left="energy_sword", right="fire_axe")
    game.perform("fight.attack", {})
    game.perform("fight.attack", {})
    assert game.player_data["threats"][0]["fate"] == "destroyed by you"


def test_security_can_stun_and_handcuff_a_threat(monkeypatch):
    game = duel(monkeypatch, left="stun_baton")
    add_to_inventory(game.player_data, get_item_definition("handcuffs"))
    game.perform("fight.stun", {})
    game.perform("fight.cuff", {})
    assert game.player_data["threats"][0]["fate"] == "handcuffed and arrested by you"
    assert threat_report(game.player_data)[0][:2] == ("The Wizard", "handcuffed and arrested by you")


def test_losing_to_a_threat_kills_you(monkeypatch):
    game = duel(monkeypatch)
    game.player_data["limbs"] = {limb: combat.DEFEAT_HEALTH for limb in game.player_data["limbs"]}
    game.perform("fight.attack", {})
    outcome = game.player_data["round"]["outcome"]
    assert (round_over(game.player_data), outcome["survived"], outcome["cause"]) == (
        True, False, "killed by the Wizard")
    assert threat_report(game.player_data)[0][:2] == ("The Wizard", "killed you")


def test_a_fight_aboard_the_shuttle_in_flight_cannot_be_waited_out(monkeypatch):
    game = duel(monkeypatch)
    game.player_data["round"]["shuttle"]["state"] = "transit"
    hits = count()
    rolls(monkeypatch, pick=lambda limbs: limbs[next(hits) % len(limbs)])
    for turn in range(1, 100):
        combat.tick_fight(at(game, turn * combat.TRANSIT_ENEMY_TURN_SECONDS))
        if round_over(game.player_data):
            break
    assert (turn > 1, game.player_data["round"]["outcome"]["cause"]) == (True, "killed by the Wizard")


AT_THE_SHUTTLE_DOOR = {"x": 1, "y": 0}


def shuttle_leaves(game):
    (hook,) = [hook for hook in DEPARTURE_HOOKS if hook.__module__ == antagonists.__name__]
    hook(game)


def picks(*indexes):
    """A random.choice that takes these positions in turn: 0 is the player when a threat picks who to go for."""
    order = iter(indexes)
    return lambda options: options[next(order)]


def test_a_revealed_threat_makes_for_the_shuttle_door_once_it_has_docked(monkeypatch):
    game = station(revealed())
    game.player_data["round"]["shuttle"]["state"] = "docked"
    rolls(monkeypatch, roll=CREW_ENGAGE_CHANCE)
    step_threats(game)
    assert game.player_data["threats"][0]["location"] == {"x": 5, "y": 4}
    for _ in range(8):
        step_threats(game)
    assert game.player_data["threats"][0]["location"] == AT_THE_SHUTTLE_DOOR
    step_threats(game)
    assert game.player_data["threats"][0]["location"] == AT_THE_SHUTTLE_DOOR


def test_threats_that_do_not_make_the_shuttle_are_left_behind(monkeypatch):
    rolls(monkeypatch)
    game = station()
    host = crew(game, "Chef")
    game.player_data["threats"] = [threat(acts=0), threat("Alien", fate="destroyed by you", acts=3), revealed("Vampire"),
                                   threat("Rogue Bot", acts=2), threat("Traitor", crew_name=host["name"], acts=1)]
    shuttle_leaves(game)
    assert game.player_data["fight"] is None
    assert [fate for _, fate, _ in threat_report(game.player_data)] == [
        "never made a move", "destroyed by you", "left behind on the station",
        "left behind on the station without being found out", "left behind on the station without being found out"]


def test_a_threat_at_the_shuttle_door_is_aboard_and_fights_you_at_full_health_when_it_picks_you_first(monkeypatch):
    rolls(monkeypatch)
    game = station(revealed(location=AT_THE_SHUTTLE_DOOR))
    shuttle_leaves(game)
    assert game.player_data["fight"]["log"] == ["The Wizard has slipped aboard the shuttle, and comes straight at you!"]
    assert game.player_data["fight"]["enemy"]["hp"] == THREAT_TYPES["Wizard"]["hp"]

    game = station(revealed(location=AT_THE_SHUTTLE_DOOR))
    seated(game, "Chef", "Miner")
    shuttle_leaves(game)
    assert (game.player_data["fight"]["enemy"]["hp"], len(game.station_crew)) == (THREAT_TYPES["Wizard"]["hp"], 15)


def test_a_hidden_threat_is_aboard_when_the_crew_member_it_hides_as_boarded(monkeypatch):
    rolls(monkeypatch)
    game = station()
    (host,) = seated(game, "Chef")
    game.player_data["threats"] = [threat("Traitor", crew_name=host["name"], acts=1)]
    shuttle_leaves(game)
    traitor = game.player_data["threats"][0]
    assert game.player_data["fight"]["log"] == [
        f"As the shuttle pulls away, {host['name']} the Traitor turns on the crew. It was among you all along!"]
    assert (traitor["revealed"], traitor["location"], host in game.station_crew) == (
        True, game.player_data["location"], False)


def test_a_threat_that_goes_for_the_crew_first_kills_them_and_reaches_you_hurt(monkeypatch):
    game = station(revealed(location=AT_THE_SHUTTLE_DOOR))
    chef, miner, doctor = seated(game, "Chef", "Miner", "Doctor")
    doctor["limbs"] = {limb: 10 for limb in doctor["limbs"]}
    aboard = [member for member in game.station_crew if member in (chef, miner, doctor)]
    rolls(monkeypatch, pick=picks(1 + aboard.index(miner), 0))
    shuttle_leaves(game)
    killed = f"The Wizard goes for {miner['name']} (Miner) aboard the shuttle and kills them."
    assert messages(game) == [("Crew Shuttle", killed)]
    assert notes(game)[-1] == killed
    assert (miner in game.station_crew, chef in game.station_crew) == (False, True)
    fight = game.player_data["fight"]
    assert fight["log"] == [f"The Wizard turns from {miner['name']} to you, hurt from the fight!"]
    assert fight["enemy"]["hp"] == 45 - round(45 * 2 * antagonists.SHUTTLE_CREW_HIT) == 41


def test_enough_crew_aboard_bring_a_threat_down_before_it_reaches_you_and_the_next_one_moves(monkeypatch):
    game = station(revealed(location=AT_THE_SHUTTLE_DOOR), revealed("Space Pirate", location=AT_THE_SHUTTLE_DOOR))
    for member in game.station_crew:
        member["location"] = location_from_key(DEPARTURES_KEY)
    first, second = game.station_crew[:2]
    rolls(monkeypatch, pick=picks(1, 1, 0))
    shuttle_leaves(game)
    wizard, pirate = game.player_data["threats"]
    assert (wizard["fate"], wizard["hp"]) == ("brought down by the crew aboard the shuttle",
                                              45 - 2 * round(45 * antagonists.SHUTTLE_CREW_HIT_MAX))
    assert messages(game) == [
        ("Crew Shuttle", f"The Wizard goes for {first['name']} ({first['job']}) aboard the shuttle and kills them."),
        ("Crew Shuttle", f"The Wizard goes for {second['name']} ({second['job']}) aboard the shuttle and kills them. "
                         "The rest of the crew bring it down."),
    ]
    assert (pirate["fate"], game.player_data["fight"]["enemy"]["name"]) == (None, "the Space Pirate")
    assert game.player_data["fight"]["log"] == [
        "The Space Pirate has slipped aboard the shuttle, and comes straight at you!"]


def test_the_shift_summary_says_what_became_of_each_threat():
    game = station(threat(acts=0), threat("Alien", acts=2), revealed("Vampire"),
                   threat("Cultist", acts=4, fate="arrested by Alex Chen"))
    assert threat_report(game.player_data) == [
        ("The Wizard", "never made a move", "Out to put None out of action: foiled."),
        ("The Alien", "was never found out", "Out to put None out of action: foiled."),
        ("The Vampire", "still at large when the shuttle left", "Out to put None out of action: foiled."),
        ("The Cultist", "arrested by Alex Chen", "Out to put None out of action: foiled."),
    ]


def test_station_status_carries_the_alert_and_the_sightings():
    game = station(revealed(acts=4))
    game.open_panel("station_status")
    alerts = {alert["text"]: alert["severity"] for alert in game.view()["panel"]["ctx"]["alerts"]}
    assert alerts["Station alert level: Red"] == "critical"
    assert alerts["The Wizard was last seen in the Northeast Corner."] == "critical"
    game.player_data["game_clock"]["elapsed_seconds"] = 754
    status = game.view()["status"]
    assert (status["alert"], status["alert_color"], status["clock"], status["sightings"]) == (
        "Red", "#FF0000", "12m", ["The Wizard was last seen in the Northeast Corner."])

    game = station(threat(acts=1))
    game.open_panel("station_status")
    alerts = {alert["text"]: alert["severity"] for alert in game.view()["panel"]["ctx"]["alerts"]}
    assert alerts["Station alert level: Yellow"] == "caution"


def test_stowaways_are_fought_one_after_another(monkeypatch):
    game = duel(monkeypatch, left="energy_sword", right="fire_axe")
    game.player_data["threats"].append(revealed("Space Pirate"))
    game.player_data["round"]["shuttle"]["state"] = "transit"
    game.perform("fight.attack", {})
    game.perform("fight.attack", {})
    wizard, pirate = game.player_data["threats"]
    assert wizard["fate"] == "beaten and arrested by you"
    assert game.player_data["fight"]["enemy"]["name"] == "the Space Pirate"
    assert game.player_data["fight"]["log"] == [
        "The Space Pirate has slipped aboard the shuttle, and comes straight at you!"]


def test_a_threat_you_are_fighting_does_nothing_else_until_that_is_settled(monkeypatch):
    game = duel(monkeypatch)
    wizard = game.player_data["threats"][0]
    wizard["next_act_at"] = 0
    rolls(monkeypatch)
    step_threats(game)
    tick_threats(game)
    assert (wizard["location"], wizard["hp"], wizard["acts"], wizard["fate"]) == ({"x": 0, "y": 0}, 45, 3, None)


def test_unmasking_a_crew_threat_leaves_everyone_else_who_they_were(monkeypatch):
    game = station(department="Security", job="Security Guard")
    host, doctor = crew(game, "Chef"), crew(game, "Doctor")
    game.player_data["threats"] = [threat("Traitor", crew_name=host["name"], acts=2)]
    doctor["warrant"] = True
    game.player_data["location"] = dict(doctor["location"])
    game.scan_room_for_warrants("0,6")
    rolls(monkeypatch)
    tick_threats(game)
    assert host not in game.station_crew
    choice = game.view()["choice"]
    game.perform("game.choose", {"id": choice["id"], "index": 0})
    assert doctor["in_jail"]


def test_each_change_of_alert_level_is_announced_once(monkeypatch):
    game = station(threat(acts=0, next_act_at=10 ** 6))
    wizard = game.player_data["threats"][0]
    tick_threats(game)
    assert messages(game) == []
    wizard["acts"] = 1
    tick_threats(game)
    tick_threats(game)
    wizard["acts"] = 3
    tick_threats(game)
    wizard["fate"] = "arrested by you"
    tick_threats(game)
    assert [message for title, message in messages(game) if title == "Station Alert"] == [
        "The station is now at Yellow alert.", "The station is now at Orange alert.", "The station is now at Green alert."]


def test_an_alert_change_is_not_heard_with_the_communication_array_off(monkeypatch):
    game = station(threat(acts=3, next_act_at=10 ** 6))
    game.player_data["station_power"]["system_levels"]["communication_array"] = 0
    tick_threats(game)
    assert (game.player_data["round"]["alert"], messages(game)) == ("Orange", [])


def test_a_second_attack_on_the_same_crew_member_says_again(monkeypatch):
    game = station(threat())
    rolls(monkeypatch)
    wizard = game.player_data["threats"][0]
    first, other = game.station_crew[0], game.station_crew[1]
    assert ACTS["maul"](game, wizard)[0] == f"{first['name']} was found badly hurt."
    assert ACTS["maul"](game, wizard)[0] == f"{first['name']} was attacked again."
    assert ACTS["poison"](game, wizard)[0] == f"{first['name']} has been poisoned again."
    rolls(monkeypatch, pick=lambda options: options[1])
    assert ACTS["maul"](game, wizard)[0] == f"{other['name']} was found badly hurt."
