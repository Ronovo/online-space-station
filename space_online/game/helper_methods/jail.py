"""Jail / arrest helpers: sentences, release, and prisoner lookups.

Sentences are tracked as absolute deadlines on the universal master game
clock (``jail_release_at_seconds``) rather than wall-clock timestamps.
Callers pass in the current ``elapsed_seconds`` (see ``game_clock.py``)
so this module never reads the wall clock itself.
"""

import random

from space_online.game.maps import donut
from space_online.game.helper_methods.door_control import can_control_door
from space_online.game.helper_methods.game_clock import format_elapsed, get_elapsed_seconds
from space_online.game.helper_methods.npc_movement import (
    has_post,
    location_for_post,
)
from space_online.game.helper_methods.ui_panels import choice_handler

DEFAULT_SENTENCE_SECONDS = 5 * 60
ADD_TIME_SECONDS = 60
BRIBE_CHANCE = 0.35
BRIBE_MIN_CREDITS = 5
BRIBE_MAX_CREDITS = 50
FINE_REFUSE_CHANCE = 0.15

def can_player_arrest(player_data):
    """Whoever can work the Security door can scan warrants and offer Arrest / Let Go."""
    return can_control_door(player_data, donut.SECURITY_KEY)


def security_room_location():
    return donut.location_from_key(donut.SECURITY_KEY)


def security_hallway_location():
    return donut.location_from_tile(donut.SPECIAL_ROOM_HALLWAY[donut.SECURITY_KEY])


def _reason_text(member, field):
    return member[field].strip() or "No reason on file"


def warrant_reason_text(member):
    return _reason_text(member, "warrant_reason")


def has_fine(member):
    return member["fine_amount"] > 0


def jailed_away_text(member, elapsed_seconds):
    """What someone sees when they look for, or call, a crew member who is locked up."""
    remaining = format_elapsed(jail_seconds_remaining(member, elapsed_seconds))
    return f"{member.get('name', 'They')} is in jail and will be released in {remaining}."


def player_jail_text(player_data):
    remaining = format_elapsed(jail_seconds_remaining(player_data, get_elapsed_seconds(player_data)))
    return f"You are in jail. Time remaining: {remaining}."


def _clear_fine(member):
    member["fine_amount"] = 0
    member["fine_reason"] = ""


def _jail_for_fine(
    member,
    *,
    game,
    is_player,
    guard_name,
    amount,
    reason,
    name,
    elapsed_seconds,
    refuse=False,
):
    """Arrest someone over an unpaid/refused fine. Returns 'jailed'."""
    if is_player:
        jail_message = (f"{guard_name} demands your unpaid fine of {amount:.0f} credits ({reason}), but you "
                        + ("refuse to pay.\nYou are under arrest!" if refuse
                           else "cannot pay.\nYou are under arrest for non-payment!"))
    else:
        jail_message = (f"{name} refuses to pay their {amount:.0f}-credit fine ({reason}), even though they have the "
                        f"credits.\n{guard_name} arrests them." if refuse
                        else f"{name} cannot pay their {amount:.0f}-credit fine ({reason}).\n"
                             f"{guard_name} arrests them for non-payment.")
    note = f"{name} was jailed for {'refusing' if refuse else 'failing'} to pay a {amount:.0f}-credit fine."

    arrest_member(
        member,
        reason=jail_message,
        game=game,
        is_player=is_player,
        show_message=True,
        elapsed_seconds=elapsed_seconds,
    )
    game.add_note(note)
    return "jailed"


def resolve_fine_with_guard(
    member,
    *,
    game,
    is_player=False,
    guard_name="Security",
    elapsed_seconds=0.0,
):
    """Collect an unpaid fine when the member meets a security guard.

    Pays if they can afford it (85% of the time); 15% chance they refuse and
    go to jail even with enough credits. Cannot afford -> jail.
    Returns 'paid', 'jailed', or None if there was no fine.
    """
    if not has_fine(member) or is_jailed(member):
        return None

    amount = member["fine_amount"]
    reason = _reason_text(member, "fine_reason")
    name = member.get("name", "Someone")
    credits = float(member.get("credits", 0) or 0)

    if credits >= amount:
        if random.random() < FINE_REFUSE_CHANCE:
            return _jail_for_fine(
                member,
                game=game,
                is_player=is_player,
                guard_name=guard_name,
                amount=amount,
                reason=reason,
                name=name,
                elapsed_seconds=elapsed_seconds,
                refuse=True,
            )

        member["credits"] = credits - amount
        _clear_fine(member)
        message = (
            f"{guard_name} collects your unpaid fine of {amount:.0f} credits.\n"
            f"Reason: {reason}"
            if is_player
            else (
                f"{guard_name} collects {name}'s unpaid fine of {amount:.0f} credits.\n"
                f"Reason: {reason}"
            )
        )
        game.alert("Fine Paid", message)
        game.add_note(f"{name} paid a {amount:.0f}-credit fine ({reason}).")
        return "paid"

    return _jail_for_fine(
        member,
        game=game,
        is_player=is_player,
        guard_name=guard_name,
        amount=amount,
        reason=reason,
        name=name,
        elapsed_seconds=elapsed_seconds,
        refuse=False,
    )


def is_jailed(member):
    return bool(member.get("in_jail", False))


def jail_seconds_remaining(member, elapsed_seconds=0.0):
    """Return whole seconds left on a sentence, or 0 if not jailed / expired.

    ``elapsed_seconds`` is the current master game clock value (see
    ``game_clock.get_elapsed_seconds``).
    """
    if not is_jailed(member):
        return 0
    release_at = member.get("jail_release_at_seconds")
    if release_at is None:
        return 0
    return max(0, int(release_at - elapsed_seconds))


def members_in_room(station_crew, room_key, *, exclude=None):
    """Return non-jailed NPCs whose location matches room_key."""
    found = []
    for npc in station_crew:
        if exclude is not None and npc is exclude:
            continue
        if is_jailed(npc):
            continue
        if donut.location_key(npc["location"]) == room_key:
            found.append(npc)
    return found


def wanted_in_room(room_key, station_crew, *, exclude=None):
    """Return wanted, non-jailed NPCs currently in room_key (excludes player)."""
    return [
        npc for npc in members_in_room(station_crew, room_key, exclude=exclude)
        if npc.get("warrant", False)
    ]


def fined_in_room(room_key, station_crew, *, exclude=None):
    """Return non-jailed NPCs in room_key who have an unpaid fine."""
    return [
        npc for npc in members_in_room(station_crew, room_key, exclude=exclude)
        if has_fine(npc)
    ]


def arrest_member(
    member, *, reason="", game, is_player=False, show_message=True, elapsed_seconds=0.0
):
    """Send a crew member to jail for the default sentence.

    Returns True if the arrest was applied, False if they were already jailed.
    Warrant stays active until release. ``elapsed_seconds`` is the current
    master game clock value; the release deadline is scheduled relative to it.
    """
    if is_jailed(member):
        return False

    member["in_jail"] = True
    member["jail_release_at_seconds"] = elapsed_seconds + DEFAULT_SENTENCE_SECONDS
    member["location"] = security_room_location()
    member["room_visit_remaining"] = 0
    if has_post(member):
        member["on_duty"] = False

    name = member.get("name", "Someone")
    game.add_note(f"{name} was arrested and sent to jail.")

    if is_player:
        message = reason or (
            f"You have been arrested and sent to jail for "
            f"{format_elapsed(DEFAULT_SENTENCE_SECONDS)}."
        )
        game.handle_player_arrest(message, show_message=show_message)
    elif show_message and reason:
        game.report("Arrest", reason)

    return True


def release_member(member, *, is_player=False, game, show_message=True):
    """Release a prisoner: clear jail state and warrant, place them outside Security."""
    if not is_jailed(member):
        return False

    name = member.get("name", "Someone")
    member["in_jail"] = False
    member["jail_release_at_seconds"] = None
    member["warrant"] = False
    member["warrant_reason"] = ""
    member["room_visit_remaining"] = 0

    if is_player:
        member["location"] = security_hallway_location()
    elif has_post(member):
        location = location_for_post(member.get("job"))
        if location is not None:
            member["on_duty"] = True
            member["location"] = location
        else:  # pragma: no cover - every posted job has a post location
            member["location"] = security_hallway_location()
    else:
        member["location"] = security_hallway_location()

    game.add_note(f"{name} was released from jail.")

    if is_player and show_message:
        game.handle_player_release()

    return True


def add_jail_time(member, elapsed_seconds=0.0, seconds=ADD_TIME_SECONDS):
    """Extend an active sentence. Returns True if time was added."""
    if not is_jailed(member):
        return False

    remaining = jail_seconds_remaining(member, elapsed_seconds)
    member["jail_release_at_seconds"] = elapsed_seconds + remaining + seconds
    return True


def list_prisoners(player_data, station_crew):
    """Return (member, is_player) pairs currently in jail."""
    prisoners = []
    if is_jailed(player_data):
        prisoners.append((player_data, True))
    for npc in station_crew:
        if is_jailed(npc):
            prisoners.append((npc, False))
    return prisoners


def tick_jail_releases(game):
    """Release anyone whose sentence has expired."""
    elapsed_seconds = get_elapsed_seconds(game.player_data)
    for member, is_player in list_prisoners(game.player_data, game.station_crew):
        if jail_seconds_remaining(member, elapsed_seconds) <= 0:
            release_member(member, is_player=is_player, game=game, show_message=is_player)


def arrest_wanted_in_room(room_key, game, guard, elapsed_seconds):
    """Arrest the wanted crew, and the player, a guard finds in room_key."""
    player_data = game.player_data
    wanted = [(npc, False) for npc in members_in_room(game.station_crew, room_key, exclude=guard)]
    if donut.location_key(player_data["location"]) == room_key:
        wanted.append((player_data, True))
    for member, is_player in wanted:
        if not member.get("warrant") or is_jailed(member):
            continue
        charge = warrant_reason_text(member)
        found = ("A security guard found you while you were wanted. You are under arrest!" if is_player
                 else f"{member.get('name', 'A crew member')} was arrested by security and sent to jail.")
        arrest_member(member, reason=f"{found}\nCharge: {charge}", game=game, is_player=is_player,
                      show_message=True, elapsed_seconds=elapsed_seconds)


_ARREST_PLACE_TEXT = {
    "room": {
        "lines": "You scan the room and spot {name} ({job}).\nThey have an active warrant.\nCharge: {charge}",
        "arrest": "You arrest {name} in the room and send them to jail.\nCharge: {charge}",
        "let_go_note": "Let wanted crew member {name} go after scanning a room.",
        "let_go_plain": "You look the other way. {name} stays in the room.",
    },
    "call": {
        "lines": (
            "{name} ({job}) answers your call and arrives.\n"
            "Your scan shows they have an active warrant.\nCharge: {charge}"
        ),
        "arrest": "You arrest {name} after calling them back and send them to jail.\nCharge: {charge}",
        "let_go_note": "Let wanted crew member {name} go after calling them back.",
        "let_go_plain": "You look the other way. {name} remains at their post.",
    },
    "hall": {
        "lines": "You stop {name} ({job}) in the hall.\nThey have an active warrant.\nCharge: {charge}",
        "arrest": "You arrest {name} in the hallway and send them to jail.\nCharge: {charge}",
        "let_go_note": "Let wanted crew member {name} go in the hallway.",
        "let_go_plain": "You wave {name} on. They disappear down the hallway.",
    },
}


def _arrest_choice_eligible(player_data, npc):
    return (
        can_player_arrest(player_data)
        and not is_jailed(player_data)
        and not is_jailed(npc)
        and npc.get("warrant", False)
    )


def offer_player_arrest_choice(game, npc, *, place="hall"):
    """Ask a Security Guard or Captain player to Arrest or Let Go a wanted crew member.

    place: 'hall', 'room', or 'call'. Returns True if a choice was queued.
    """
    if not _arrest_choice_eligible(game.player_data, npc):
        return False

    text = _ARREST_PLACE_TEXT.get(place, _ARREST_PLACE_TEXT["hall"])
    name = npc.get("name", "A crew member")
    fields = {"name": name, "job": npc.get("job", "Crew"), "charge": warrant_reason_text(npc)}
    bribe_amount = None
    if random.random() < BRIBE_CHANCE:
        bribe_amount = random.randint(BRIBE_MIN_CREDITS, BRIBE_MAX_CREDITS)

    lines = [text["lines"].format(**fields)]
    if bribe_amount is not None:
        lines.append(
            f'{name} leans in and whispers, "Look the other way and I\'ll make it '
            f'worth your while - {bribe_amount} credits."'
        )
    lines.append("\nWhat do you do?")

    crew_index = game.station_crew.index(npc)
    common = {"crew_index": crew_index, "place": place, "bribe_amount": bribe_amount}
    game.ask(
        "Wanted Crew",
        "\n".join(lines),
        [
            ("Arrest", "resolve_arrest_choice", dict(common, choice="arrest")),
            ("Let Go", "resolve_arrest_choice", dict(common, choice="let_go")),
        ],
    )
    return True


@choice_handler("resolve_arrest_choice")
def resolve_player_arrest_choice(game, crew_index, choice, place, bribe_amount):
    if not (0 <= crew_index < len(game.station_crew)):
        return
    npc = game.station_crew[crew_index]
    if not _arrest_choice_eligible(game.player_data, npc):
        return

    text = _ARREST_PLACE_TEXT.get(place, _ARREST_PLACE_TEXT["hall"])
    name = npc.get("name", "A crew member")
    fields = {"name": name, "charge": warrant_reason_text(npc)}

    if choice == "arrest":
        arrest_member(
            npc,
            reason=text["arrest"].format(**fields),
            game=game,
            is_player=False,
            show_message=True,
            elapsed_seconds=get_elapsed_seconds(game.player_data),
        )
        return

    if bribe_amount is not None:
        game.player_data["credits"] = game.player_data.get("credits", 0) + bribe_amount
        npc["warrant"] = False
        npc["warrant_reason"] = ""
        game.alert(
            "Let Go",
            f"You look the other way. {name} slips you {bribe_amount} credits and hurries off.\n"
            "Their warrant has been quietly cleared.",
        )
        game.add_note(
            f"Accepted a {bribe_amount}-credit bribe from {name}, "
            "cleared their warrant, and let them go."
        )
    else:
        game.alert("Let Go", text["let_go_plain"].format(**fields))
        game.add_note(text["let_go_note"].format(**fields))
