import pytest

from helpers import (
    add_ingredients,
    board_shuttle,
    buttons,
    crew,
    go,
    last_message,
    menu_widgets,
    new_game,
    notes,
    reports,
    stale_air,
    stowaway,
)
from space_online.game.character_methods.character_creation import JOBS
from space_online.game.helper_methods import npc_movement, shuttle_talk
from space_online.game.helper_methods.hazards import set_hazard
from space_online.game.helper_methods.jail import tick_jail_releases
from space_online.game.helper_methods.needs import DEFAULT_QUENCHES
from space_online.game.helper_methods.npc_movement import crew_aboard, step_crew
from space_online.game.helper_methods.power_constants import BATTERY_CRITICAL
from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.oxygen_helper import DEATH_THRESHOLD
from space_online.game.helper_methods.rounds import (
    ALL_CLEAR_DELAY_SECONDS,
    ANTAGONIST,
    JOB_EVENT_INTERVAL_RANGE,
    SHIFT_END_RANGE_SECONDS,
    SHUTTLE_ARRIVAL_SECONDS,
    SHUTTLE_DOCKED_SECONDS,
    SHUTTLE_LOCKOUT_SECONDS,
    SHUTTLE_RECALLS_PER_SHIFT,
    SHUTTLE_TRANSIT_SECONDS,
    SHUTTLE_URGENT_ARRIVAL_SECONDS,
    call_for_red_alert,
    call_shuttle,
    kill_player,
    new_round,
    recall_shuttle,
    round_over,
    shuttle_call_blocked,
    shuttle_recall_blocked,
    shuttle_status,
    tick_round,
)
from space_online.game.maps.donut import (
    BAR_KEY,
    BRIDGE_KEY,
    DEPARTURES_KEY,
    SECURITY_KEY,
    location_from_key,
)
from space_online.game.special_rooms.shuttle import SECTIONS
from space_online.game.special_rooms.quarters import SHUTTLE_BED_HEAL_PER_MINUTE, tick_rest

CALL_AT = 25 * 60


def shift(department="Civilian", job="Staff Assistant", mode="peaceful"):
    game = new_game(department, job, mode)
    game.player_data["round"]["call_at"] = CALL_AT
    return game


def at(game, seconds):
    game.player_data["game_clock"]["elapsed_seconds"] = seconds
    tick_round(game)
    return game


def shuttle(game):
    return game.player_data["round"]["shuttle"]


def outcome(game):
    return game.player_data["round"]["outcome"]


def captain(game):
    return next(npc for npc in game.station_crew if npc["job"] == "Captain")


def in_departures(game):
    game.player_data["location"] = location_from_key(DEPARTURES_KEY)
    return game


def docked(game):
    at(game, CALL_AT)
    return at(game, CALL_AT + SHUTTLE_ARRIVAL_SECONDS)


def test_a_round_ends_its_shift_at_a_time_picked_for_it():
    round_ = new_round(ANTAGONIST, "Chef")
    assert SHIFT_END_RANGE_SECONDS[0] <= round_["call_at"] <= SHIFT_END_RANGE_SECONDS[1]
    assert JOB_EVENT_INTERVAL_RANGE[0] <= round_["next_job_event_at"] <= JOB_EVENT_INTERVAL_RANGE[1]
    assert (round_["mode"], round_["job_at_start"], round_["duties_done"], round_["duties_missed"],
            round_["outcome"]) == (ANTAGONIST, "Chef", 0, 0, None)
    assert round_["shuttle"]["state"] == "idle"


def test_the_captain_calls_the_shuttle_when_the_shift_is_over():
    game = at(shift(), CALL_AT - 1)
    assert (shuttle(game)["state"], shuttle_status(game.player_data)) == ("idle", None)
    at(game, CALL_AT)
    assert (shuttle(game)["state"], shuttle(game)["until"]) == ("called", CALL_AT + SHUTTLE_ARRIVAL_SECONDS)
    message = (f"{captain(game)['name']} (Captain) has called the crew shuttle: the shift is over. "
               "It docks at Departures in 5m 0s.")
    assert last_message(game) == ("Crew Shuttle", message)
    assert notes(game)[-1] == message
    assert shuttle_status(game.player_data) == "Shuttle docks in 5m 0s"
    at(game, CALL_AT + SHUTTLE_ARRIVAL_SECONDS - 1)
    assert (shuttle(game)["state"], shuttle_status(game.player_data)) == ("called", "Shuttle docks in 1s")


def test_central_command_calls_it_when_the_captain_cannot():
    game = shift()
    captain(game)["in_jail"] = True
    at(game, CALL_AT)
    assert last_message(game)[1].startswith("Central Command has called the crew shuttle")
    game = shift()
    game.station_crew.remove(captain(game))
    at(game, CALL_AT)
    assert last_message(game)[1].startswith("Central Command has called the crew shuttle")


@pytest.mark.parametrize("resolved_at, called_at", [
    (600, SHIFT_END_RANGE_SECONDS[0]),
    (SHIFT_END_RANGE_SECONDS[0], SHIFT_END_RANGE_SECONDS[0] + ALL_CLEAR_DELAY_SECONDS),
])
def test_the_shuttle_is_called_once_the_threat_is_dealt_with_but_never_before_a_full_shift(resolved_at, called_at):
    game = shift()
    game.player_data["round"].update(resolved_at=resolved_at, call_at=SHIFT_END_RANGE_SECONDS[1])
    at(game, called_at - 1)
    assert shuttle(game)["state"] == "idle"
    at(game, called_at)
    captain = crew(game, "Captain")["name"]
    assert last_message(game)[1].startswith(
        f"{captain} (Captain) has called the crew shuttle: the threat to the station has been dealt with.")


def test_central_command_never_calls_for_the_all_clear_only_at_the_end_of_the_shift():
    game = shift()
    crew(game, "Captain")["in_jail"] = True
    game.player_data["round"].update(resolved_at=600, call_at=SHIFT_END_RANGE_SECONDS[1])
    at(game, SHIFT_END_RANGE_SECONDS[1] - 1)
    assert shuttle(game)["state"] == "idle"
    at(game, SHIFT_END_RANGE_SECONDS[1])
    assert last_message(game)[1].startswith("Central Command has called the crew shuttle: the shift is over.")


def test_nothing_calls_the_shuttle_in_the_first_minutes_of_a_shift():
    game = shift()
    game.player_data["round"]["call_at"] = 0
    at(game, SHUTTLE_LOCKOUT_SECONDS - 1)
    assert shuttle(game)["state"] == "idle"
    assert shuttle_call_blocked(game.player_data) == (
        "Central Command won't release the shuttle this early in the shift. Try again in 1s.")
    assert not call_shuttle(game, "a whim")
    at(game, SHUTTLE_LOCKOUT_SECONDS)
    assert shuttle(game)["state"] == "called"
    assert shuttle_call_blocked(game.player_data) == "The crew shuttle has already been called."


def test_a_player_captain_decides_when_the_shift_ends_until_central_command_steps_in():
    game = at(shift("Administration", "Captain"), CALL_AT)
    game.player_data["round"]["resolved_at"] = 600
    at(game, SHIFT_END_RANGE_SECONDS[1] - 1)
    assert shuttle(game)["state"] == "idle"
    at(game, SHIFT_END_RANGE_SECONDS[1])
    assert last_message(game)[1].startswith("Central Command has called the crew shuttle: the shift has run long.")


def test_an_urgent_call_gets_the_shuttle_here_sooner():
    game = at(shift(), SHUTTLE_LOCKOUT_SECONDS - 1)
    game.player_data["game_clock"]["elapsed_seconds"] = SHUTTLE_LOCKOUT_SECONDS
    assert call_shuttle(game, "the station is at Red alert", urgent=True, caller="Captain Ada")
    assert shuttle(game)["travel"] == SHUTTLE_URGENT_ARRIVAL_SECONDS
    assert last_message(game)[1] == ("Captain Ada has called the crew shuttle: the station is at Red alert. "
                                     "It docks at Departures in 3m 0s.")


def test_recalling_the_shuttle_before_it_is_halfway():
    game = at(shift(), CALL_AT)
    game.player_data["round"]["call_at"] = 10 ** 6
    game.player_data["game_clock"]["elapsed_seconds"] = CALL_AT + SHUTTLE_ARRIVAL_SECONDS / 2 - 1
    assert recall_shuttle(game)
    assert last_message(game) == ("Crew Shuttle", "The crew shuttle has been recalled.")
    assert (shuttle(game)["state"], shuttle(game)["until"]) == ("idle", None)
    assert shuttle_call_blocked(game.player_data) == (
        "The shuttle was recalled and is still turning around. Try again in 5m 0s.")
    assert shuttle_recall_blocked(game.player_data) == "No shuttle is on its way here."
    assert not recall_shuttle(game)
    at(game, CALL_AT + SHUTTLE_ARRIVAL_SECONDS * 2)
    assert shuttle_call_blocked(game.player_data) is None


def test_the_shuttle_cannot_be_recalled_past_halfway():
    game = at(shift(), CALL_AT)
    game.player_data["game_clock"]["elapsed_seconds"] = CALL_AT + SHUTTLE_ARRIVAL_SECONDS / 2
    assert shuttle_recall_blocked(game.player_data) == (
        "The shuttle is past the halfway point. It can't be recalled now.")
    assert not recall_shuttle(game)
    assert shuttle(game)["state"] == "called"


def test_the_shuttle_can_be_recalled_once_a_shift():
    game = at(shift(), CALL_AT)
    game.player_data["round"]["call_at"] = 10 ** 6
    assert recall_shuttle(game)
    assert shuttle(game)["recalls"] == 1
    game.player_data["game_clock"]["elapsed_seconds"] = CALL_AT + SHUTTLE_ARRIVAL_SECONDS
    assert call_shuttle(game, "a second try")
    assert shuttle_recall_blocked(game.player_data) == (
        "The shuttle has already been recalled this shift. Central Command won't turn it around again.")
    assert not recall_shuttle(game)
    assert shuttle(game)["state"] == "called"


def test_the_captain_calls_the_shuttle_urgently_at_red_alert_and_it_can_be_recalled():
    game = at(shift(), SHUTTLE_LOCKOUT_SECONDS - 1)
    call_for_red_alert(game)
    assert shuttle(game)["state"] == "idle"
    game.player_data["game_clock"]["elapsed_seconds"] = SHUTTLE_LOCKOUT_SECONDS
    call_for_red_alert(game)
    assert (shuttle(game)["state"], shuttle(game)["travel"]) == ("called", SHUTTLE_URGENT_ARRIVAL_SECONDS)
    assert last_message(game)[1].startswith(
        f"{captain(game)['name']} (Captain) has called the crew shuttle: the station is at Red alert.")
    assert shuttle_recall_blocked(game.player_data) is None
    assert recall_shuttle(game)


def test_nobody_calls_the_shuttle_at_red_alert_when_the_captain_cannot():
    game = at(shift(), SHUTTLE_LOCKOUT_SECONDS)
    captain(game)["in_jail"] = True
    call_for_red_alert(game)
    assert (shuttle(game)["state"], game._messages) == ("idle", [])
    game.station_crew.remove(captain(game))
    call_for_red_alert(game)
    assert (shuttle(game)["state"], game._messages) == ("idle", [])
    at(game, CALL_AT)
    assert last_message(game)[1].startswith("Central Command has called the crew shuttle: the shift is over.")


def test_nothing_calls_the_shuttle_at_red_alert_for_a_player_captain():
    game = at(shift("Administration", "Captain"), SHUTTLE_LOCKOUT_SECONDS)
    crew(game, "Head of Personnel")["job"] = "Captain"
    call_for_red_alert(game)
    assert (shuttle(game)["state"], game._messages) == ("idle", [])


def test_a_player_captains_recall_at_red_alert_stands_until_the_shift_runs_long():
    game = at(shift("Administration", "Captain"), SHUTTLE_LOCKOUT_SECONDS)
    assert call_shuttle(game, "the Captain has ended the shift", urgent=True, caller="Ada (Captain)")
    game.player_data["game_clock"]["elapsed_seconds"] += 10
    assert recall_shuttle(game)
    at(game, shuttle(game)["blocked_until"])
    call_for_red_alert(game)
    assert shuttle(game)["state"] == "idle"
    at(game, SHIFT_END_RANGE_SECONDS[1])
    assert last_message(game)[1].startswith("Central Command has called the crew shuttle: the shift has run long.")


def test_a_call_that_is_due_while_the_shuttle_turns_around_says_when_it_will_come():
    game = at(shift("Administration", "Captain"), SHIFT_END_RANGE_SECONDS[1] - 60)
    assert call_shuttle(game, "the Captain has ended the shift")
    assert recall_shuttle(game)
    at(game, SHIFT_END_RANGE_SECONDS[1] - 1)
    assert last_message(game)[1] == "The crew shuttle has been recalled."
    at(game, SHIFT_END_RANGE_SECONDS[1])
    assert last_message(game) == ("Crew Shuttle", "Central Command wants the shuttle; it can be called in 4m 0s.")
    lines = len(game._messages)
    at(game, SHIFT_END_RANGE_SECONDS[1] + 1)
    assert len(game._messages) == lines
    at(game, SHIFT_END_RANGE_SECONDS[1] + 4 * 60)
    assert last_message(game)[1].startswith("Central Command has called the crew shuttle: the shift has run long.")


def test_departures_is_by_the_junction_and_says_where_the_shuttle_is():
    game = shift()
    game.player_data["location"] = {"x": 1, "y": 0}
    assert game.view()["screen"]["grid"][1][0] == {"label": "Departures", "action": "game.enter_room",
                                                   "args": {"room_key": DEPARTURES_KEY}}
    game.perform("game.enter_room", {"room_key": DEPARTURES_KEY})
    assert buttons(game) == [("No shuttle has been called. The Captain calls it from the Bridge.", None)]
    game.perform("room.board", {})
    assert not game.player_data["round"]["aboard"]
    at(game, CALL_AT)
    assert buttons(game) == [("Shuttle docks in 5m 0s", None)]


def test_board_the_shuttle_joins_the_lounge_menu_only_once_the_shuttle_is_in():
    game = in_departures(shift())
    assert [action for _, action in buttons(game)] == [None]
    at(game, CALL_AT)
    assert [action for _, action in buttons(game)] == [None]
    docked(game)
    assert [action for _, action in buttons(game)] == [None, "room.board"]


def test_the_crew_board_as_the_shuttle_comes_and_the_jailed_are_marched_aboard(monkeypatch):
    monkeypatch.setattr(npc_movement.random, "random", lambda: 0.99)
    game = in_departures(shift())
    chef, assistant, miner = (crew(game, job) for job in ("Chef", "Staff Assistant", "Miner"))
    at(game, CALL_AT)
    assert (assistant["npc_goal"], chef["npc_goal"]) == ("board", None)
    assert recall_shuttle(game)
    assert assistant["npc_goal"] is None

    game = docked(in_departures(shift()))
    chef, miner = (crew(game, job) for job in ("Chef", "Miner"))
    assert chef["npc_goal"] == "board"
    miner["in_jail"] = True
    chef["npc_goal"] = None
    for _ in range(20):
        step_crew(game)
    game.perform("room.board", {})
    game.perform("room.strap", {})
    at(game, CALL_AT + SHUTTLE_ARRIVAL_SECONDS + SHUTTLE_DOCKED_SECONDS)
    size = len(game.station_crew)
    assert last_message(game) == ("Crew Shuttle", f"The shuttle pulls away from the station with {size - 1} of the "
                                                  f"{size} crew aboard. Central Command in 1m 0s.")
    assert miner["location"] == location_from_key(DEPARTURES_KEY)


def test_boarding_the_docked_shuttle_and_riding_it_to_central_command():
    game = docked(in_departures(shift()))
    assert last_message(game) == ("Crew Shuttle", "The crew shuttle has docked at Departures. It leaves in 2m 0s. "
                                                  "Board it there.")
    assert buttons(game) == [("Shuttle leaves in 2m 0s", None), ("Board the Shuttle", "room.board")]
    game.perform("room.board", {})
    screen = game.view()["screen"]
    assert (screen["title"], screen["heading"]) == ("Crew Shuttle", "Crew Shuttle Common Area")
    assert buttons(game) == [("Shuttle leaves in 2m 0s", None), ("Strap In", "room.strap"),
                             ("Talk to the Crew", "room.talk_to_crew"), ("Go to Medical Bay", "room.go_to"),
                             ("Go to Break Room", "room.go_to"), ("Step Off the Shuttle", "room.step_off")]
    assert notes(game)[-1] == "Boarded the crew shuttle."
    game.perform("room.strap", {})

    at(game, CALL_AT + SHUTTLE_ARRIVAL_SECONDS + SHUTTLE_DOCKED_SECONDS)
    assert last_message(game) == ("Crew Shuttle", f"The shuttle pulls away from the station with 0 of the "
                                                  f"{len(game.station_crew)} crew aboard. Central Command in 1m 0s.")
    assert buttons(game) == [("Central Command in 1m 0s", None), ("Unstrap", "room.strap"),
                             ("Talk to the Crew", "room.talk_to_crew"), ("Unstrap to get up.", None)]
    game.perform("room.strap", {})
    game.perform("room.step_off", {})
    assert game.player_data["round"]["aboard"]
    assert not round_over(game.player_data)

    at(game, CALL_AT + SHUTTLE_ARRIVAL_SECONDS + SHUTTLE_DOCKED_SECONDS + SHUTTLE_TRANSIT_SECONDS)
    assert outcome(game) == {"survived": True, "cause": "reached Central Command",
                             "seconds": get_elapsed_seconds(game.player_data)}


def test_aboard_the_shuttle_you_can_only_step_back_off():
    game = docked(in_departures(shift()))
    game.perform("room.board", {})
    game.perform("room.exit", {})
    assert last_message(game) == ("Crew Shuttle", "You are aboard the shuttle. Step off it first.")
    game.perform("room.toggle_door", {})
    assert game.player_data["location"] == location_from_key(DEPARTURES_KEY)
    game.perform("room.step_off", {})
    assert not game.player_data["round"]["aboard"]
    game.perform("room.exit", {})
    assert game.player_data["location"] == {"x": 1, "y": 0}


def test_missing_the_shuttle_means_being_left_behind_even_in_a_peaceful_round():
    game = docked(shift(mode="peaceful"))
    at(game, CALL_AT + SHUTTLE_ARRIVAL_SECONDS + SHUTTLE_DOCKED_SECONDS)
    assert (outcome(game)["survived"], outcome(game)["cause"]) == (False, "left behind when the shuttle departed")
    assert round_over(game.player_data)


def test_a_prisoner_rides_in_the_shuttles_cell_and_still_reaches_central_command():
    game = docked(shift())
    game.player_data.update(in_jail=True, jail_release_at_seconds=CALL_AT + SHUTTLE_ARRIVAL_SECONDS + 150)
    limbs = dict(game.player_data["limbs"])
    departs = CALL_AT + SHUTTLE_ARRIVAL_SECONDS + SHUTTLE_DOCKED_SECONDS
    at(game, departs)
    player = game.player_data
    assert (player["in_jail"], player["round"]["aboard"], shuttle(game)["state"]) == (True, True, "transit")
    assert (player["location"], player["round"]["section"]) == (location_from_key(DEPARTURES_KEY), "security")
    assert ("Crew Shuttle", "Security marches you aboard the shuttle in cuffs and locks you in its cell.",
            "info") in game._messages
    assert player["limbs"] == limbs

    game.player_data["game_clock"]["elapsed_seconds"] = departs + 40
    assert game.view()["screen"]["heading"] == "Crew Shuttle Security"
    assert buttons(game) == [("Central Command in 20s", None), ("The Cell", None), ("The cell is empty.", None),
                             ("You are locked in the cell.", None)]
    for action, args in (("room.exit", {}), ("room.go_to", {"section": "common"})):
        game.perform(action, args)
        assert (last_message(game), player["round"]["section"]) == (("Crew Shuttle", "You are locked in the cell."),
                                                                    "security")
    game.perform("room.scan_passengers", {})
    assert last_message(game) == ("Crew Shuttle", "You are locked in the cell.")
    tick_jail_releases(game)
    assert (player["in_jail"], player["location"]) == (True, location_from_key(DEPARTURES_KEY))

    at(game, departs + SHUTTLE_TRANSIT_SECONDS)
    assert (outcome(game)["survived"], outcome(game)["cause"]) == (True, "reached Central Command")


def test_the_shuttle_does_not_arrive_in_the_middle_of_a_fight():
    game = docked(in_departures(shift()))
    game.perform("room.board", {})
    at(game, CALL_AT + SHUTTLE_ARRIVAL_SECONDS + SHUTTLE_DOCKED_SECONDS)
    stowaway(game)
    at(game, 10 ** 6)
    assert not round_over(game.player_data)
    game.player_data["fight"] = None
    at(game, 10 ** 6)
    assert outcome(game)["survived"]


def test_nothing_happens_once_the_round_is_over():
    game = docked(shift())
    at(game, CALL_AT + SHUTTLE_ARRIVAL_SECONDS + SHUTTLE_DOCKED_SECONDS)
    over = dict(outcome(game))
    location = dict(game.player_data["location"])
    game.player_data["game_clock"]["last_real_time"] -= 600
    game.tick()
    at(game, 10 ** 6)
    game.perform("game.move", {"direction": "north"})
    assert (outcome(game), game.player_data["location"]) == (over, location)


def test_nobody_dies_in_a_peaceful_round():
    game = shift()
    assert not kill_player(game, "a bad day")
    assert not round_over(game.player_data)


@pytest.mark.parametrize("mode", ["antagonist", "career"])
def test_dying_ends_the_round(mode):
    game = shift(mode=mode)
    game.player_data["fight"] = {"kind": "threat"}
    assert kill_player(game, "killed by the Wizard")
    assert (outcome(game)["survived"], outcome(game)["cause"]) == (False, "killed by the Wizard")
    assert game.player_data["fight"] is None


def test_running_out_of_oxygen_kills_outside_a_peaceful_round():
    game = stale_air(shift(mode="antagonist"))
    game.player_data["threats"] = []
    game.player_data["damage"]["oxygen"] = DEATH_THRESHOLD - 1
    game.check_life_support_status(600)
    assert (outcome(game)["survived"], outcome(game)["cause"]) == (False, "died when the oxygen ran out")


def captains_station(game):
    game.player_data["location"] = location_from_key(BRIDGE_KEY)
    game.ui["room_mode"] = "captain_station"
    return game


def confirm(game, index=0):
    choice = game.view()["choice"]
    game.perform("game.choose", {"id": choice["id"], "index": index})


def test_a_player_captain_calls_and_recalls_the_shuttle_from_the_bridge():
    game = captains_station(shift("Administration", "Captain"))
    assert ("Call Crew Shuttle", "room.call_shuttle") in buttons(game)
    game.perform("room.call_shuttle", {})
    assert last_message(game)[1].startswith("Central Command won't release the shuttle this early")
    game.perform("room.recall_shuttle", {})
    assert last_message(game) == ("Crew Shuttle", "No shuttle is on its way here.")

    game.player_data["game_clock"]["elapsed_seconds"] = SHUTTLE_LOCKOUT_SECONDS
    game.perform("room.call_shuttle", {})
    assert game.view()["choice"]["buttons"] == ["Call It", "Not Yet"]
    confirm(game, index=1)
    assert shuttle(game)["state"] == "idle"
    game.perform("room.call_shuttle", {})
    confirm(game)
    assert (shuttle(game)["state"], shuttle(game)["travel"]) == ("called", SHUTTLE_ARRIVAL_SECONDS)
    assert last_message(game)[1].startswith("Ada (Captain) has called the crew shuttle: the Captain has ended the shift.")
    assert ("Recall Crew Shuttle", "room.recall_shuttle") in buttons(game)
    game.perform("room.recall_shuttle", {})
    assert game.view()["choice"]["buttons"] == ["Recall It", "Not Yet"]
    confirm(game, index=1)
    assert shuttle(game)["state"] == "called"
    game.perform("room.recall_shuttle", {})
    confirm(game)
    assert (shuttle(game)["state"], last_message(game)[1]) == ("idle", "The crew shuttle has been recalled.")


def test_a_shuttle_that_cannot_be_recalled_shows_why_where_the_button_was():
    game = captains_station(shift("Administration", "Captain"))
    game.player_data["game_clock"]["elapsed_seconds"] = SHUTTLE_LOCKOUT_SECONDS
    shuttle(game)["recalls"] = SHUTTLE_RECALLS_PER_SHIFT
    assert call_shuttle(game, "a whim")
    blocked = "The shuttle has already been recalled this shift. Central Command won't turn it around again."
    assert (blocked, None) in buttons(game)
    assert not any(action in ("room.call_shuttle", "room.recall_shuttle") for _, action in buttons(game))
    game.perform("room.recall_shuttle", {})
    assert (last_message(game), game.ui["choices"]) == (("Crew Shuttle", blocked), [])


def test_a_recall_confirmed_too_late_says_so():
    game = captains_station(shift("Administration", "Captain"))
    game.player_data["game_clock"]["elapsed_seconds"] = SHUTTLE_LOCKOUT_SECONDS
    assert call_shuttle(game, "a whim")
    game.perform("room.recall_shuttle", {})
    game.player_data["game_clock"]["elapsed_seconds"] += SHUTTLE_ARRIVAL_SECONDS / 2
    confirm(game)
    assert shuttle(game)["state"] == "called"
    assert last_message(game) == ("Crew Shuttle", "The shuttle is past the halfway point. It can't be recalled now.")


def test_only_the_captain_can_call_the_shuttle():
    game = captains_station(shift("Administration", "Head of Personnel"))
    game.player_data["game_clock"]["elapsed_seconds"] = SHUTTLE_LOCKOUT_SECONDS
    game.perform("room.call_shuttle", {})
    game.perform("room.recall_shuttle", {})
    assert (game.ui["choices"], game._messages) == ([], [])


def test_station_status_reports_the_shuttle():
    game = at(shift("Administration", "Captain"), SHIFT_END_RANGE_SECONDS[1])
    game.open_panel("station_status")
    alerts = [alert["text"] for alert in game.view()["panel"]["ctx"]["alerts"]]
    assert "Crew shuttle: Shuttle docks in 5m 0s" in alerts
    assert not any(text.startswith("Station alert level") for text in alerts)


# --- Aboard the shuttle --------------------------------------------------------

DEPARTS = CALL_AT + SHUTTLE_ARRIVAL_SECONDS + SHUTTLE_DOCKED_SECONDS
ASSISTANT = ("Civilian", "Staff Assistant")
GUARD = ("Security", "Security Guard")
CAPTAIN = ("Administration", "Captain")
HOP = ("Administration", "Head of Personnel")


def aboard(job=ASSISTANT):
    return board_shuttle(shift(*job), called_at=CALL_AT)


def section(game):
    return game.player_data["round"]["section"]


def strap(game):
    game.perform("room.strap", {})
    return game


def depart(game):
    return at(game, DEPARTS)


def seat(*npcs):
    for npc in npcs:
        npc["location"] = location_from_key(DEPARTURES_KEY)


def only_crew(game, count):
    """Keep the first count crew members, settled where they are with no goal, so a test knows who is where."""
    del game.station_crew[count:]
    for npc in game.station_crew:
        npc["npc_goal"] = None
        npc.pop("stays_behind", None)
    return game.station_crew


def test_boarding_puts_the_player_on_their_feet_in_the_common_area():
    game = docked(in_departures(shift()))
    game.player_data["round"].update(section="medical", strapped=True)
    game.perform("room.board", {})
    assert (section(game), game.player_data["round"]["strapped"]) == ("common", False)
    assert game.view()["screen"]["description"].startswith("Rows of harnessed seats run down the cabin")


@pytest.mark.parametrize("job, allowed", [
    (ASSISTANT, ["medical", "break_room"]),
    (GUARD, ["command", "medical", "security", "break_room"]),
    (CAPTAIN, ["command", "medical", "security", "break_room"]),
    (HOP, ["command", "medical", "break_room"]),
])
def test_who_can_go_into_each_section(job, allowed):
    game = aboard(job)
    assert [w["args"]["section"] for w in menu_widgets(game) if w.get("action") == "room.go_to"] == allowed
    for key, entry in SECTIONS.items():
        go(game, key)
        assert section(game) == (key if key in allowed else "common")
        if key in allowed:
            screen = game.view()["screen"]
            assert (screen["title"], screen["heading"]) == ("Crew Shuttle", f"Crew Shuttle {entry.name}")
            assert buttons(game)[-1] == ("Back to the Common Area", "room.go_to")
            game.perform("room.exit", {})
            assert section(game) == "common"


def test_the_sections_are_reached_through_the_common_area():
    game = go(aboard(CAPTAIN), "medical")
    for elsewhere in ("break_room", "medical", "the_cargo_hold"):
        go(game, elsewhere)
        assert section(game) == "medical"
    assert section(go(game, "common")) == "common"


def test_a_section_only_takes_its_own_actions():
    game = aboard(CAPTAIN)
    for action in ("lie_down", "coffee_machine", "head_count", "scan_passengers", "toggle_door"):
        game.perform(f"room.{action}", {})
    assert (game.player_data["resting"], game.ui["panels"], game.ship_map[DEPARTURES_KEY]["locked"]) == (
        False, [], False)
    go(game, "medical")
    messages = len(game._messages)
    for action in ("strap", "talk_to_crew", "step_off"):
        game.perform(f"room.{action}", {})
    assert (game.player_data["round"]["strapped"], game.player_data["round"]["aboard"]) == (False, True)
    assert len(game._messages) == messages


def test_the_lounge_has_none_of_the_shuttles_actions():
    game = docked(in_departures(shift()))
    messages = len(game._messages)
    for action, args in (("strap", {}), ("talk_to_crew", {}), ("go_to", {"section": "medical"})):
        game.perform(f"room.{action}", args)
    assert (game.player_data["round"]["strapped"], section(game), len(game._messages)) == (False, "common", messages)


def test_step_off_only_works_from_the_common_area_and_not_strapped_in():
    game = go(aboard(), "medical")
    assert ("Step Off the Shuttle", "room.step_off") not in buttons(game)
    game.perform("room.step_off", {})
    assert game.player_data["round"]["aboard"]

    strap(go(game, "common"))
    assert last_message(game) == ("Crew Shuttle", "You strap into a seat.")
    assert buttons(game)[-1] == ("Unstrap to get up.", None)
    game.perform("room.step_off", {})
    go(game, "medical")
    assert (game.player_data["round"]["aboard"], section(game)) == (True, "common")
    assert last_message(game) == ("Crew Shuttle", "Unstrap to get up.")

    strap(game)
    assert last_message(game) == ("Crew Shuttle", "You unstrap from your seat.")
    game.perform("room.step_off", {})
    assert not game.player_data["round"]["aboard"]


def test_the_shuttle_warns_once_before_it_leaves():
    game = aboard()
    warning = ("Crew Shuttle", "The shuttle leaves in 15 seconds. Take your seats.", "warning")
    at(game, DEPARTS - 16)
    assert warning not in game._messages
    at(game, DEPARTS - 15)
    assert game._messages[-1] == warning
    at(game, DEPARTS - 5)
    assert game._messages.count(warning) == 1


def lie_down(game):
    go(game, "medical").perform("room.lie_down", {})
    return game


@pytest.mark.parametrize("secure", [strap, lie_down])
def test_a_player_strapped_in_or_in_the_bed_rides_out_the_launch(secure):
    game = secure(aboard())
    limbs = dict(game.player_data["limbs"])
    depart(game)
    assert game.player_data["limbs"] == limbs
    assert not any("throws you across the cabin" in message for _, message, _ in game._messages)


def test_launching_without_strapping_in_hurts_one_limb_even_in_a_peaceful_round():
    game = aboard()
    depart(game)
    hurt = {limb: health for limb, health in game.player_data["limbs"].items() if health < 100}
    ((limb, health),) = hurt.items()
    assert 80 <= health <= 90
    assert last_message(game) == ("Crew Shuttle", "You weren't strapped in, and the launch throws you across the "
                                                  f"cabin. Your {limb.replace('_', ' ').title()} took {100 - health}% "
                                                  f"damage and is now at {health}%.")
    assert not round_over(game.player_data)


def test_after_launch_the_player_can_unstrap_and_walk_the_sections_but_not_step_off():
    game = strap(depart(strap(aboard())))
    assert ("Step Off the Shuttle", "room.step_off") not in buttons(game)
    game.perform("room.step_off", {})
    assert section(go(game, "break_room")) == "break_room"
    assert game.player_data["round"]["aboard"]


# --- Common Area: Talk to the Crew ----------------------------------------------

def talking(monkeypatch, job=ASSISTANT):
    """Aboard with the whole crew in the seats. The first crew member who hasn't spoken is the one who does."""
    monkeypatch.setattr(shuttle_talk.random, "choice", lambda options: options[0])
    game = aboard(job)
    seat(*game.station_crew)
    return game


def talk(game):
    game.perform("room.talk_to_crew", {})
    return last_message(game)


def said_by(npc, line):
    return "Crew Shuttle", f"{npc['name']}, the {npc['job']}, says: \"{line}\""


def loose(revealed=True, fate=None):
    return {"name": "the Alien", "crew_name": None, "acts": 3, "revealed": revealed, "fate": fate}


TOPIC_LINES = [
    (lambda game: game.player_data.update(threats=[loose()]),
     "The Alien is still out there somewhere. I won't relax until we're away."),
    (lambda game: game.player_data["round"].update(resolved_at=600),
     "Security says whatever was loose on the station has been dealt with. Not a moment too soon."),
    (lambda game: game.player_data["incidents"].append({"at": 60, "where": "Bar", "what": "Ann was found badly hurt.",
                                                        "away": []}),
     "I read the Incident Log before we left. The last entry: Ann was found badly hurt."),
    (lambda game: set_hazard(game.player_data, BAR_KEY, "fire"),
     "Did anyone deal with the fire in the Bar? We're leaving it behind either way."),
    (lambda game: game.player_data["station_power"].update(battery_level=BATTERY_CRITICAL),
     "The battery is nearly flat. Whoever has the next shift is in for a dark one."),
    (lambda game: game.player_data["station_power"]["system_levels"].update(life_support=0),
     "Life support is down back there. I could taste the air going stale."),
    (lambda game: game.player_data["round"].update(duties_done=1),
     "I heard you got 1 job done this shift. Not bad."),
    (lambda game: game.player_data["round"].update(duties_done=3),
     "I heard you got 3 jobs done this shift. Not bad."),
    (lambda game: game.player_data["round"].update(duties_missed=2),
     "I heard 2 jobs went undone on your watch. It happens."),
    (lambda game: game.player_data.update(warrant=True),
     "Word is there's a warrant out on you. Keep your head down at Central Command."),
]


@pytest.mark.parametrize("happened, line", TOPIC_LINES)
def test_the_crew_talk_about_what_happened_on_the_shift(monkeypatch, happened, line):
    game = talking(monkeypatch)
    happened(game)
    assert talk(game) == said_by(game.station_crew[0], line)


def test_the_crew_wonder_where_someone_is_and_ignore_threats_nobody_has_seen(monkeypatch):
    game = talking(monkeypatch)
    game.player_data["threats"] = [loose(revealed=False)]
    missing = game.station_crew[-1]
    missing["location"] = location_from_key(BAR_KEY)
    assert talk(game) == said_by(game.station_crew[0],
                                 f"Has anyone seen {missing['name']}? I thought they'd be on this shuttle.")


def test_every_job_has_something_to_say():
    assert set(shuttle_talk.JOB_LINES) == set(JOBS)


def test_each_crew_member_speaks_once_and_each_topic_comes_up_once(monkeypatch):
    game = talking(monkeypatch)
    first, second, third = only_crew(game, 3)
    game.player_data["warrant"] = True
    game.player_data["round"]["duties_done"] = 2
    assert [talk(game) for _ in range(4)] == [
        said_by(first, TOPIC_LINES[-1][1]),
        said_by(second, "I heard you got 2 jobs done this shift. Not bad."),
        said_by(third, shuttle_talk.JOB_LINES[third["job"]]),
        ("Crew Shuttle", "Nobody has anything more to say."),
    ]


def test_crew_in_the_cell_or_left_behind_say_nothing(monkeypatch):
    game = talking(monkeypatch)
    prisoner, behind, seated = only_crew(game, 3)
    prisoner["in_jail"] = True
    behind["location"] = location_from_key(BAR_KEY)
    assert talk(game)[1].startswith(f"{seated['name']}, the {seated['job']}, says: ")
    assert talk(game) == ("Crew Shuttle", "Nobody has anything more to say.")


def test_talking_works_strapped_in_and_in_flight(monkeypatch):
    game = strap(talking(monkeypatch))
    depart(game)
    speaker = game.station_crew[0]
    assert talk(game)[1].startswith(f"{speaker['name']}, the {speaker['job']}, says: ")


# --- Command: Head Count ---------------------------------------------------------

def head_count(game):
    go(game, "command").perform("room.head_count", {})
    return [(row["text"], row["page"]) for row in game.view()["panel"]["ctx"]["rows"]]


def test_the_head_count_lists_where_every_crew_member_is():
    game = aboard(HOP)
    seated, coming, missed, jailed, celled, hurt = crew = only_crew(game, 6)
    seat(seated, celled)
    coming["npc_goal"] = "board"
    missed["stays_behind"] = True
    jailed.update(in_jail=True, location=location_from_key(SECURITY_KEY))
    celled["in_jail"] = True
    hurt["limbs"] = {limb: 30 for limb in hurt["limbs"]}
    where = ["aboard", "on the way", "hasn't noticed the call", "in the station's jail", "in the shuttle's cell",
             "too hurt to move"]
    assert head_count(game) == [(f"{npc['name']} ({npc['job']}): {place}", place == "hasn't noticed the call")
                                for npc, place in zip(crew, where)]

    game.ui["panels"] = []
    go(game, "common")
    depart(strap(game))
    strap(game)
    where = ["aboard", "left behind", "left behind", "in the shuttle's cell", "in the shuttle's cell", "left behind"]
    assert head_count(game) == [(f"{npc['name']} ({npc['job']}): {place}", False) for npc, place in zip(crew, where)]


def test_paging_a_crew_member_who_missed_the_call_gets_them_aboard():
    game = aboard(HOP)
    captain_npc = next(npc for npc in only_crew(game, 14) if npc["job"] == "Captain")
    captain_npc["stays_behind"] = True
    head_count(game)
    game.perform("panel.page", {"name": captain_npc["name"]})
    assert (captain_npc["npc_goal"], "stays_behind" in captain_npc) == ("board", False)
    assert last_message(game) == ("Head Count", f"You page {captain_npc['name']}. They drop what they are doing and "
                                                "head for Departures.")
    for _ in range(30):
        step_crew(game)
    game.ui["panels"] = []
    depart(strap(go(game, "common")))
    assert captain_npc in crew_aboard(game.station_crew)


def test_paging_needs_the_communication_array():
    game = aboard(HOP)
    missed = only_crew(game, 1)[0]
    missed["stays_behind"] = True
    game.player_data["station_power"]["system_levels"]["communication_array"] = 0
    head_count(game)
    game.perform("panel.page", {"name": missed["name"]})
    assert last_message(game) == ("No Signal", "The Communication Array is down. Nobody can be called.")
    assert (missed["npc_goal"], missed["stays_behind"]) == (None, True)


def test_only_the_crew_who_missed_the_call_can_be_paged_and_only_while_docked():
    game = aboard(HOP)
    seated, missed = only_crew(game, 2)
    seat(seated)
    missed["stays_behind"] = True
    head_count(game)
    messages = len(game._messages)
    for name in (seated["name"], "Nobody At All"):
        game.perform("panel.page", {"name": name})
    assert (seated["npc_goal"], len(game._messages)) == (None, messages)

    game.player_data["game_clock"]["elapsed_seconds"] = DEPARTS
    game.player_data["round"]["shuttle"]["state"] = "transit"
    game.perform("panel.page", {"name": missed["name"]})
    assert missed["npc_goal"] is None


def test_the_head_count_only_opens_from_command():
    game = aboard(HOP)
    missed = only_crew(game, 1)[0]
    missed["stays_behind"] = True
    game.open_panel("shuttle_head_count")
    game.perform("panel.page", {"name": missed["name"]})
    assert (missed["npc_goal"], game.view()["panel"]) == (None, None)


# --- Medical: the bed ----------------------------------------------------------------

def test_the_shuttle_bed_mends_limbs_fast_and_leaves_other_damage_alone():
    game = lie_down(aboard())
    assert last_message(game) == ("Bed", "You lie down to rest. Your limbs will mend while you stay in bed.")
    assert buttons(game)[1:] == [("Get Up", "room.lie_down"), ("Get up to leave the bed.", None)]
    player = game.player_data
    player["limbs"].update(head=50, left_leg=95)
    player["damage"].update(burn=20, poison=20, oxygen=20)
    credits, inventory = player["credits"], list(player["inventory"])
    tick_rest(game, 60)
    assert (player["limbs"]["head"], player["limbs"]["left_leg"]) == (50 + SHUTTLE_BED_HEAL_PER_MINUTE, 100)
    assert player["damage"] == {"burn": 20, "poison": 20, "oxygen": 20}
    assert (player["credits"], player["inventory"], player["resting"]) == (credits, inventory, True)


def test_getting_up_is_needed_to_leave_the_bed():
    game = lie_down(aboard())
    go(game, "common")
    assert (section(game), last_message(game)) == ("medical", ("Crew Shuttle", "Get up to leave the bed."))
    game.perform("room.lie_down", {})
    assert last_message(game) == ("Bed", "You get out of bed.")
    assert section(go(game, "common")) == "common"


@pytest.mark.parametrize("away", [
    lambda game: game.player_data["round"].update(section="common"),
    lambda game: game.player_data["round"].update(aboard=False),
    stowaway,
])
def test_leaving_the_medical_bay_stepping_off_or_a_fight_ends_the_rest(away):
    game = lie_down(aboard())
    game.player_data["limbs"]["head"] = 50
    away(game)
    tick_rest(game, 60)
    assert (game.player_data["resting"], game.player_data["limbs"]["head"]) == (False, 50)


# --- Break Room: the coffee machine -------------------------------------------------

def brew(game, *ingredients):
    add_ingredients(game, *ingredients)
    game.perform("panel.mix", {})
    return game.view()["panel"]["ctx"]["result"]


def test_the_coffee_machine_brews_coffee_from_grounds_and_water():
    game = go(aboard(), "break_room")
    game.perform("room.coffee_machine", {})
    panel = game.view()["panel"]
    assert (panel["template"], panel["title"], panel["ctx"]["ingredients"]) == (
        "mixer", "Coffee Machine", ["Coffee Grounds", "Water"])
    assert brew(game, "Water", "Water") == {"text": "The water runs through clear. It needs coffee grounds.",
                                            "color": "orange"}
    assert brew(game, "Coffee Grounds") == {"text": "The grounds scorch on the hot plate. It needs water.",
                                            "color": "orange"}
    assert game.player_data["inventory"] == []
    assert brew(game, "Coffee Grounds", "Water", "Water")["text"] == ("The machine gurgles and fills a cup. You take "
                                                                      "a coffee.")
    assert last_message(game) == ("Coffee Machine", "The machine is full.")
    (coffee,) = game.player_data["inventory"]
    assert (coffee["id"], coffee["category"], coffee["attributes"]) == (
        "drink_coffee", "Drink", {"alcoholic": False, "alcohol_content": 0, "quenches": DEFAULT_QUENCHES})


def test_coffee_drinks_like_any_other_drink():
    game = go(aboard(), "break_room")
    game.perform("room.coffee_machine", {})
    brew(game, "Coffee Grounds", "Water")
    game.player_data["needs"]["thirst"] = 80
    game.ui["panels"] = []
    game.open_panel("inventory")
    game.perform("panel.select", {"index": 0})
    game.perform("panel.actions", {})
    game.perform("panel.item_action", {"name": "drink"})
    assert (game.player_data["needs"]["thirst"], game.player_data["inventory"]) == (80 - DEFAULT_QUENCHES, [])


def test_the_coffee_machine_has_a_card_taped_to_it():
    game = go(aboard(), "break_room")
    game.perform("room.coffee_machine", {})
    game.perform("panel.recipes", {})
    panel = game.view()["panel"]
    assert (panel["template"], panel["title"]) == ("recipes", "Card Taped to the Coffee Machine")
    assert panel["ctx"]["sections"] == [{"title": "COFFEE", "recipes": [
        {"name": "Coffee", "ingredients": "Coffee Grounds, Water", "price": None,
         "desc": "A cup of hot black coffee from the shuttle's machine."}]}]