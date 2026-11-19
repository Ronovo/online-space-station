"""A round: one shift on the station, from arrival until the crew shuttle reaches Central Command.

player_data["round"] holds:
    mode           CAREER, PEACEFUL or ANTAGONIST
    job_at_start   the job the shift began in
    next_job_event_at  game seconds at which the player's job next brings them something to do
    duties_done, duties_missed  how many duties the player finished and let run out
    paid_through   game seconds the salary has been paid up to, and salary_paid the total so far
    call_at        game seconds at which the Captain calls the shuttle if nothing else has
    resolved_at    game seconds when the last threat was dealt with, or None
    alert          the alert level the station was last told about
    shuttle        state ("idle", "called", "docked" or "transit"), until (when that state ends), called_at,
                   travel (seconds from call to docking), blocked_until (no new call before then), recalls (how
                   many times it has been sent back), wait_logged (the player has been told a call is waiting on
                   blocked_until) and launch_warned (the player has been told the docked shuttle is about to leave)
    aboard         True once the player has boarded the docked shuttle
    section        the shuttle section the player is in while aboard (see special_rooms/shuttle.py)
    strapped       True while the player is strapped into a seat in the shuttle's Common Area
    shuttle_talked {crew name: topic} of the crew who have spoken to the player aboard the shuttle
    flight_event_at  game seconds at which something happens during the flight, or None
    outcome        None while the shift runs, then {"survived", "cause", "seconds"}
"""

import random

from space_online.game.helper_methods.game_clock import format_elapsed, get_elapsed_seconds
from space_online.game.helper_methods.health_bands import LIMBS, change_limb, limb_label
from space_online.game.helper_methods.jail import is_jailed
from space_online.game.helper_methods.npc_movement import (
    can_work,
    crew_aboard,
    post_holder,
    recall_from_shuttle,
    send_to_shuttle,
)
from space_online.game.maps import donut

CAREER = "career"
PEACEFUL = "peaceful"
ANTAGONIST = "antagonist"
MODES = (CAREER, PEACEFUL, ANTAGONIST)
MODE_DESCRIPTIONS = {
    PEACEFUL: "No antagonists, and nothing can kill you: run out of health and you wake up in your Quarters. "
              "Accidents and low oxygen still hurt, and the shuttle still leaves without you. A place to practise.",
    ANTAGONIST: "One to three antagonists, and death ends the round.",
}

SHUTTLE_LOCKOUT_SECONDS = 15 * 60
SHUTTLE_ARRIVAL_SECONDS = 5 * 60
SHUTTLE_URGENT_ARRIVAL_SECONDS = 3 * 60
SHUTTLE_DOCKED_SECONDS = 2 * 60
SHUTTLE_TRANSIT_SECONDS = 60
SHUTTLE_RECALLS_PER_SHIFT = 1
# The Captain ends an uneventful shift at a time picked from this range. Central Command steps in at its end.
SHIFT_END_RANGE_SECONDS = (22 * 60, 37 * 60)
ALL_CLEAR_DELAY_SECONDS = 3 * 60
# The player's job brings them something to do this often.
JOB_EVENT_INTERVAL_RANGE = (2 * 60, 4 * 60)

LAUNCH_WARNING_SECONDS = 15
LAUNCH_THROW_DAMAGE_RANGE = (10, 20)
FLIGHT_EVENT_RANGE_SECONDS = (10, 40)
# The shuttle sections the player boards into, rides in as a prisoner, and rests in.
BOARDING_SECTION = "common"
CELL_SECTION = "security"
BED_SECTION = "medical"

# Called with the game as the shuttle leaves, e.g. by whatever is still loose on the station.
DEPARTURE_HOOKS = []


def new_round(mode, job):
    return {
        "mode": mode,
        "job_at_start": job,
        "next_job_event_at": random.randint(*JOB_EVENT_INTERVAL_RANGE),
        "duties_done": 0,
        "duties_missed": 0,
        "paid_through": 0,
        "salary_paid": 0,
        "call_at": random.randint(*SHIFT_END_RANGE_SECONDS),
        "resolved_at": None,
        "alert": "Green",
        "shuttle": {"state": "idle", "until": None, "called_at": None, "travel": None, "blocked_until": 0,
                    "recalls": 0, "wait_logged": False, "launch_warned": False},
        "aboard": False,
        "section": BOARDING_SECTION,
        "strapped": False,
        "shuttle_talked": {},
        "flight_event_at": None,
        "outcome": None,
    }


def can_die(player_data):
    """Peaceful rounds are practice: nothing in them ends the shift early."""
    return player_data["round"]["mode"] != PEACEFUL


def round_over(player_data):
    return player_data["round"]["outcome"] is not None


def end_round(game, survived, cause):
    game.player_data["round"]["outcome"] = {
        "survived": survived,
        "cause": cause,
        "seconds": get_elapsed_seconds(game.player_data),
    }
    game.player_data["fight"] = None
    game.reset_view()


def kill_player(game, cause):
    """End the shift with the player dead. Returns False in a Peaceful round, where nobody dies."""
    if not can_die(game.player_data):
        return False
    end_round(game, False, cause)
    return True


def shuttle_call_blocked(player_data):
    """Why the shuttle can't be called right now, or None when it can."""
    shuttle = player_data["round"]["shuttle"]
    elapsed = get_elapsed_seconds(player_data)
    if shuttle["state"] != "idle":
        return "The crew shuttle has already been called."
    if elapsed < SHUTTLE_LOCKOUT_SECONDS:
        wait = format_elapsed(SHUTTLE_LOCKOUT_SECONDS - elapsed)
        return f"Central Command won't release the shuttle this early in the shift. Try again in {wait}."
    if elapsed < shuttle["blocked_until"]:
        wait = format_elapsed(shuttle["blocked_until"] - elapsed)
        return f"The shuttle was recalled and is still turning around. Try again in {wait}."
    return None


def captain_caller(name):
    return f"{name} (Captain)"


def _working_captain(game):
    """The NPC Captain if they can work, else None."""
    captain = post_holder(game.station_crew, "Captain")
    return captain if captain is not None and can_work(captain) else None


def _npc_caller(game):
    captain = _working_captain(game)
    return "Central Command" if captain is None else captain_caller(captain["name"])


def call_shuttle(game, reason, urgent=False, caller=None):
    """Call the crew shuttle. Returns False when it can't be called yet. An urgent call gets it here sooner."""
    player_data = game.player_data
    if shuttle_call_blocked(player_data):
        return False
    elapsed = get_elapsed_seconds(player_data)
    travel = SHUTTLE_URGENT_ARRIVAL_SECONDS if urgent else SHUTTLE_ARRIVAL_SECONDS
    player_data["round"]["shuttle"].update(state="called", until=elapsed + travel, called_at=elapsed, travel=travel)
    send_to_shuttle(game.station_crew, idle_only=True)
    message = (f"{caller or _npc_caller(game)} has called the crew shuttle: {reason}. "
               f"It docks at Departures in {format_elapsed(travel)}.")
    game.announce("Crew Shuttle", message, kind="warning")
    game.add_note(message)
    return True


def _central_command_calls(game, reason):
    """Call the shuttle without the player asking. While a recalled shuttle is still turning around the call has
    to wait, and the player is told once when it will come."""
    if call_shuttle(game, reason):
        return
    shuttle = game.player_data["round"]["shuttle"]
    wait = shuttle["blocked_until"] - get_elapsed_seconds(game.player_data)
    if wait > 0 and not shuttle["wait_logged"]:
        shuttle["wait_logged"] = True
        game.alert("Crew Shuttle", f"Central Command wants the shuttle; it can be called in {format_elapsed(wait)}.",
                   kind="warning")


def call_for_red_alert(game):
    """The station is at Red alert, so the NPC Captain calls the shuttle if they can work. A player Captain
    decides for themself."""
    if game.player_data["job"] != "Captain" and _working_captain(game) is not None:
        call_shuttle(game, "the station is at Red alert", urgent=True)


def shuttle_recall_blocked(player_data):
    """Why the shuttle can't be recalled right now, or None when it can."""
    shuttle = player_data["round"]["shuttle"]
    if shuttle["state"] != "called":
        return "No shuttle is on its way here."
    if shuttle["recalls"] >= SHUTTLE_RECALLS_PER_SHIFT:
        return "The shuttle has already been recalled this shift. Central Command won't turn it around again."
    if get_elapsed_seconds(player_data) >= shuttle["called_at"] + shuttle["travel"] / 2:
        return "The shuttle is past the halfway point. It can't be recalled now."
    return None


def recall_shuttle(game):
    """Send a called shuttle back. Returns False when shuttle_recall_blocked says it can't be."""
    player_data = game.player_data
    if shuttle_recall_blocked(player_data):
        return False
    shuttle = player_data["round"]["shuttle"]
    shuttle.update(state="idle", until=None, blocked_until=get_elapsed_seconds(player_data) + shuttle["travel"],
                   recalls=shuttle["recalls"] + 1, wait_logged=False)
    recall_from_shuttle(game.station_crew)
    message = "The crew shuttle has been recalled."
    game.announce("Crew Shuttle", message, kind="warning")
    game.add_note(message)
    return True


SHUTTLE_STATUS = {
    "called": "Shuttle docks in {}",
    "docked": "Shuttle leaves in {}",
    "transit": "Central Command in {}",
}


def shuttle_status(player_data):
    """One line on where the shuttle is, or None while it hasn't been called."""
    shuttle = player_data["round"]["shuttle"]
    if shuttle["state"] == "idle":
        return None
    remaining = max(0, shuttle["until"] - get_elapsed_seconds(player_data))
    return SHUTTLE_STATUS[shuttle["state"]].format(format_elapsed(remaining))


def _due_reason(game, elapsed):
    """Why the shuttle should be called now on the clock alone, or None."""
    round_ = game.player_data["round"]
    if game.player_data["job"] == "Captain":
        return "the shift has run long" if elapsed >= SHIFT_END_RANGE_SECONDS[1] else None
    resolved = round_["resolved_at"]
    if (resolved is not None and _working_captain(game) is not None
            and elapsed >= max(resolved + ALL_CLEAR_DELAY_SECONDS, SHIFT_END_RANGE_SECONDS[0])):
        return "the threat to the station has been dealt with"
    if elapsed >= round_["call_at"]:
        return "the shift is over"
    return None


def _dock(game, elapsed):
    game.player_data["round"]["shuttle"].update(state="docked", until=elapsed + SHUTTLE_DOCKED_SECONDS)
    send_to_shuttle(game.station_crew, idle_only=False)
    game.announce("Crew Shuttle", "The crew shuttle has docked at Departures. It leaves in "
                                f"{format_elapsed(SHUTTLE_DOCKED_SECONDS)}. Board it there.", kind="warning")


def secured(player_data):
    """Whether the player aboard is held in place through a jolt: strapped into a seat, lying in a bed (resting
    only lasts while the player is in one) or locked in the cell."""
    return player_data["round"]["strapped"] or player_data["resting"] or is_jailed(player_data)


def _throw_loose_player(game):
    """A player who isn't secured as the shuttle pulls away is thrown across the cabin and hurts a limb."""
    if secured(game.player_data):
        return
    limb = random.choice(LIMBS)
    damage = random.randint(*LAUNCH_THROW_DAMAGE_RANGE)
    _, after = change_limb(game.player_data, limb, -damage)
    message = (f"You weren't strapped in, and the launch throws you across the cabin. Your {limb_label(limb)} "
               f"took {damage}% damage and is now at {after}%.")
    game.alert("Crew Shuttle", message, kind="warning")
    game.add_note(message)


def _depart(game, elapsed):
    round_ = game.player_data["round"]
    player = game.player_data
    if is_jailed(player):
        player["location"] = donut.location_from_key(donut.DEPARTURES_KEY)
        round_.update(aboard=True, section=CELL_SECTION, strapped=False)
        game.alert("Crew Shuttle", "Security marches you aboard the shuttle in cuffs and locks you in its cell.")
    if not round_["aboard"]:
        end_round(game, False, "left behind when the shuttle departed")
        return
    crew = game.station_crew
    for npc in crew:
        if is_jailed(npc):
            npc["location"] = donut.location_from_key(donut.DEPARTURES_KEY)
    round_["shuttle"].update(state="transit", until=elapsed + SHUTTLE_TRANSIT_SECONDS)
    game.reset_view()
    game.alert("Crew Shuttle", f"The shuttle pulls away from the station with {len(crew_aboard(crew))} of the "
                                f"{len(crew)} crew aboard. Central Command in "
                                f"{format_elapsed(SHUTTLE_TRANSIT_SECONDS)}.")
    _throw_loose_player(game)
    for hook in DEPARTURE_HOOKS:
        hook(game)
    round_["flight_event_at"] = None if player["fight"] else elapsed + random.randint(*FLIGHT_EVENT_RANGE_SECONDS)


def _arrive(game, elapsed):
    """Reaching Central Command ends the shift, once any fight aboard is over."""
    if not game.player_data["fight"]:
        end_round(game, True, "reached Central Command")


_SHUTTLE_STEPS = {"called": _dock, "docked": _depart, "transit": _arrive}


def tick_round(game):
    """Call the shuttle when the shift is due to end, and move it along once it is on its way."""
    player_data = game.player_data
    if round_over(player_data):
        return
    elapsed = get_elapsed_seconds(player_data)
    shuttle = player_data["round"]["shuttle"]
    if shuttle["state"] == "idle":
        reason = _due_reason(game, elapsed)
        if reason:
            _central_command_calls(game, reason)
    elif elapsed >= shuttle["until"]:
        _SHUTTLE_STEPS[shuttle["state"]](game, elapsed)
    elif (shuttle["state"] == "docked" and not shuttle["launch_warned"]
          and shuttle["until"] - elapsed <= LAUNCH_WARNING_SECONDS):
        shuttle["launch_warned"] = True
        game.alert("Crew Shuttle", f"The shuttle leaves in {LAUNCH_WARNING_SECONDS} seconds. Take your seats.",
                   kind="warning")
