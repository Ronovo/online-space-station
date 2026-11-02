"""Errands: the one job task a player has waiting at a time.

player_data["errand"] holds it, or is missing when there is none. Every errand has:
    kind     "deliver" (bring item to the giver), "help" (report to the giver), "serve" (Bartender
             serves a mixed drink to patron) or "treat" (Doctor treats patient from Crew Vitals)
    room     the door key of the room it is done in
    summary  one line for Station Status
plus, by kind: giver (job), item, label, reward, patron, patient.
"""

ROOM_ERRAND_KINDS = ("deliver", "help")


def with_article(name):
    """'a tomato', 'an Old Fashioned': name after its indefinite article."""
    return f"{'an' if name[0].lower() in 'aeiou' else 'a'} {name}"


def pending_errand(player_data):
    return player_data.get("errand")


def finish_errand(game, note, message, reward=0):
    """Pay reward, clear the errand, and tell the player."""
    game.player_data["credits"] += reward
    game.player_data.pop("errand", None)
    game.add_note(note)
    game.alert("Errand Complete", message)
