"""Duties: the job tasks waiting on the player, up to MAX_OPEN_DUTIES at a time.

player_data["duties"] lists them. Every duty has:
    id          what the client names it by
    kind        "deliver" (bring item to the giver), "help" (report to the giver), "serve" (Bartender or Chef
                serves a made item to patron), "treat" (Doctor treats patient from Crew Vitals), "analyse"
                (a Scientist files an analysis), "bomb_test" (a Scientist runs a bomb of a size on the Atmospherics
                test range) or "command" (the Captain approves or denies a request on the Duties panel)
    room        the door key of the room it is done in, or None for one done from anywhere
    summary     one line for the Duties panel and Station Status
    expires_at  game seconds after which it is missed
plus, by kind: giver (job), item, label, reward, patron, patient, size (the blast a "bomb_test" wants), and for
"command" the request, its text and the suspect or door it names. A deliver duty with a gas wants its item, a Gas Tank, filled with that gas. A
Quartermaster's Supply Request is marked approved once they have ordered it at the Order Console.

player_data["round"] counts duties_done and duties_missed for the shift report.
"""

import uuid

from space_online.game.helper_methods.game_clock import format_elapsed, get_elapsed_seconds
from space_online.game.helper_methods.ui_panels import register_panel

ROOM_ERRAND_KINDS = ("deliver", "help")
MAX_OPEN_DUTIES = 3
DUTY_EXPIRY_SECONDS = 6 * 60


def with_article(name):
    """'a tomato', 'an Old Fashioned': name after its indefinite article."""
    return f"{'an' if name[0].lower() in 'aeiou' else 'a'} {name}"


def counted(count, noun):
    """'1 share', '3 shares': count with its noun, plural unless the count is one."""
    return f"{count} {noun}{'' if count == 1 else 's'}"


def open_duties(player_data, kinds=None, room=None):
    """The duties waiting, optionally only those of the given kinds done in the given room."""
    return [duty for duty in player_data["duties"]
            if (kinds is None or duty["kind"] in kinds) and (room is None or duty["room"] == room)]


def duty_by_id(player_data, duty_id):
    return next((duty for duty in player_data["duties"] if duty["id"] == duty_id), None)


def duties_full(player_data):
    return len(player_data["duties"]) >= MAX_OPEN_DUTIES


def duties_button(player_data):
    """The Duties button's label, with how many duties are open."""
    open_count = len(player_data["duties"])
    return f"Duties ({open_count})" if open_count else "Duties"


def add_duty(player_data, lasts=DUTY_EXPIRY_SECONDS, **duty):
    """Put a new duty on the board, to run out in lasts seconds. Returns it."""
    duty.update(id=uuid.uuid4().hex[:12], expires_at=get_elapsed_seconds(player_data) + lasts)
    player_data["duties"].append(duty)
    return duty


def leave_duties_behind(game):
    """Clear the board after a job change. The duties belonged to the old job, so none counts as missed."""
    player_data = game.player_data
    if player_data["duties"]:
        player_data["duties"] = []
        game.alert("Duties", "Your open duties stay with your old job.")


def record_duty_done(player_data):
    player_data["round"]["duties_done"] += 1


def finish_duty(game, duty, note, message, reward=0):
    """Pay reward, take the duty off the board, and tell the player."""
    player_data = game.player_data
    player_data["credits"] += reward
    player_data["duties"].remove(duty)
    record_duty_done(player_data)
    game.add_note(note)
    game.alert("Duty Done", message)


def tick_duty_expiry(game):
    """Take every duty whose time has run out off the board and count it as missed."""
    player_data = game.player_data
    elapsed = get_elapsed_seconds(player_data)
    for duty in [duty for duty in player_data["duties"] if elapsed >= duty["expires_at"]]:
        player_data["duties"].remove(duty)
        player_data["round"]["duties_missed"] += 1
        message = f"You ran out of time: {duty['summary']}."
        game.alert("Duty Missed", message, kind="warning")
        game.add_note(message)


@register_panel("duties", "Duties")
def duties_panel(game, state):
    player_data = game.player_data
    elapsed = get_elapsed_seconds(player_data)
    round_ = player_data["round"]
    return {
        "job": player_data["job"],
        "duties": [{"id": duty["id"], "summary": duty["summary"], "left": format_elapsed(duty["expires_at"] - elapsed),
                    "answer": duty["kind"] == "command"}
                   for duty in player_data["duties"]],
        "done": round_["duties_done"],
        "missed": round_["duties_missed"],
    }
