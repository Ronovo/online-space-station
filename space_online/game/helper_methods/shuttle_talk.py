"""Talk to the Crew aboard the shuttle: each crew member in the seats says one thing about how the shift went.

TOPICS are tried in order, and each is said at most once a trip. A crew member with nothing left to say about the
shift talks about their own job instead (JOB_LINES).
"""

import random

from space_online.game.helper_methods.antagonists import loose_threats
from space_online.game.helper_methods.combat import capitalized
from space_online.game.helper_methods.errands import counted
from space_online.game.helper_methods.hazards import HAZARDS, hazard_rooms
from space_online.game.helper_methods.jail import is_jailed
from space_online.game.helper_methods.npc_movement import crew_aboard
from space_online.game.helper_methods.power_constants import BATTERY_CRITICAL
from space_online.game.maps import donut

JOB_LINES = {
    "Staff Assistant": "Another shift of fetching and carrying. At least these seats are comfortable.",
    "Engineer": "I spent half the shift with my head in a power conduit. I can still hear it humming.",
    "Security Guard": "I'll be writing up reports all the way to Central Command.",
    "Doctor": "I patched up more bruises today than I can count. Try not to add to them on the way home.",
    "Captain": "Another shift for the log. Central Command will want a full report.",
    "Bartender": "I poured drinks all shift. I could do with one myself.",
    "Head of Personnel": "So many access requests. Everyone wants a job they aren't trained for.",
    "Chef": "The kitchen is spotless. Well, it will be once the next shift cleans it.",
    "Scientist": "One of those artifacts hummed at me all shift. I'm glad to be away from it.",
    "Miner": "There's good ore down on that planet. Shame about the wildlife.",
    "Quartermaster": "The cargo books balance, more or less. Don't tell Central Command about the less.",
    "Botanist": "I hope the next shift remembers to water the planters.",
}


def _threat_loose(game):
    loose = [threat for threat in loose_threats(game.player_data) if threat["revealed"]]
    if loose:
        return f"{capitalized(loose[0]['name'])} is still out there somewhere. I won't relax until we're away."
    return None


def _threat_dealt_with(game):
    if game.player_data["round"]["resolved_at"] is not None:
        return "Security says whatever was loose on the station has been dealt with. Not a moment too soon."
    return None


def _incident(game):
    incidents = game.player_data["incidents"]
    if incidents:
        return f"I read the Incident Log before we left. The last entry: {incidents[-1]['what']}"
    return None


def _hazard(game):
    hazards = hazard_rooms(game.player_data)
    if hazards:
        room_key, kind = hazards[0]
        return (f"Did anyone deal with the {HAZARDS[kind]['name']} in the {donut.ROOMS[room_key].name}? "
                "We're leaving it behind either way.")
    return None


def _battery(game):
    if game.player_data["station_power"]["battery_level"] <= BATTERY_CRITICAL:
        return "The battery is nearly flat. Whoever has the next shift is in for a dark one."
    return None


def _life_support(game):
    if game.player_data["station_power"]["system_levels"]["life_support"] <= 0:
        return "Life support is down back there. I could taste the air going stale."
    return None


def _missing_crew(game):
    aboard = crew_aboard(game.station_crew)
    missing = [npc for npc in game.station_crew if npc not in aboard]
    if missing:
        return f"Has anyone seen {missing[0]['name']}? I thought they'd be on this shuttle."
    return None


def _player_warrant(game):
    if game.player_data["warrant"]:
        return "Word is there's a warrant out on you. Keep your head down at Central Command."
    return None


def _duties_done(game):
    done = game.player_data["round"]["duties_done"]
    if done:
        return f"I heard you got {counted(done, 'job')} done this shift. Not bad."
    return None


def _duties_missed(game):
    missed = game.player_data["round"]["duties_missed"]
    if missed:
        return f"I heard {counted(missed, 'job')} went undone on your watch. It happens."
    return None


TOPICS = (
    ("threat_loose", _threat_loose),
    ("threat_dealt_with", _threat_dealt_with),
    ("incident", _incident),
    ("hazard", _hazard),
    ("battery", _battery),
    ("life_support", _life_support),
    ("missing_crew", _missing_crew),
    ("player_warrant", _player_warrant),
    ("duties_done", _duties_done),
    ("duties_missed", _duties_missed),
)


def seated_crew(game):
    """The crew aboard in the seats: everyone aboard but the prisoners in the cell."""
    return [npc for npc in crew_aboard(game.station_crew) if not is_jailed(npc)]


def talk_to_crew(game):
    """One crew member in the seats who hasn't spoken yet this trip says something."""
    talked = game.player_data["round"]["shuttle_talked"]
    waiting = [npc for npc in seated_crew(game) if npc["name"] not in talked]
    if not waiting:
        game.alert("Crew Shuttle", "Nobody has anything more to say.")
        return
    speaker = random.choice(waiting)
    used = set(talked.values())
    topic, line = "job", JOB_LINES[speaker["job"]]
    for key, line_of in TOPICS:
        said = None if key in used else line_of(game)
        if said:
            topic, line = key, said
            break
    talked[speaker["name"]] = topic
    game.alert("Crew Shuttle", f"{speaker['name']}, the {speaker['job']}, says: \"{line}\"")
