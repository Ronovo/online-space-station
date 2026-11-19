"""Alien artifacts: what the Miner digs up on a planet and the Scientist works out in the Research Lab.

An artifact is an inventory item with the id ARTIFACT_ID whose attributes carry "artifact":
    kind       an ARTIFACT_KINDS key: what it turns out to be
    device     the DEVICES key that sets it off
    threshold  the least strength of that device that does. Much more than that overloads it
    activated  True once a test has set it off, which is what shows what kind it is
    analysed   True once a correct analysis has been filed for it. Only then can it be used
    ready_at   game seconds before which a reusable one is still recharging
    duty       the id of the duty Central Command sent it with, if it came with one
"""

import random

from space_online.game.helper_methods.game_clock import format_elapsed, get_elapsed_seconds
from space_online.game.helper_methods.health_bands import LIMBS, change_limb
from space_online.game.helper_methods.npc_movement import pick_random_hallway_location

ARTIFACT_ID = "alien_artifact"
DEVICES = {"heater": "Heater", "electric": "Electric Box", "impact": "Impact Pad", "xray": "X-ray Scanner"}
MAX_STRENGTH = 10
THRESHOLD_RANGE = (3, 7)
# A test this far over the threshold overloads the artifact, and one this far under it gets a strong reaction.
OVERLOAD_MARGIN = 3
CLOSE_MARGIN = 2
OVERLOAD_DAMAGE = 10
EXPORT_VALUE = 250
HEALER_MEND = 25
HEALER_RECHARGE_SECONDS = 120
WARPER_RECHARGE_SECONDS = 60
POWER_CELL_CHARGE = 25

ARTIFACT_KINDS = {
    "healer": {
        "name": "Healer",
        "shows": "A warm green light spreads from it, and the ache goes out of your hands.",
        "desc": f"Mends every limb by {HEALER_MEND}% when used, then needs a while to recharge.",
    },
    "power_cell": {
        "name": "Power Cell",
        "shows": "It hums, and every light in the lab burns brighter for a moment.",
        "desc": f"Empties itself into the station battery when used: {POWER_CELL_CHARGE}% of a full charge.",
    },
    "warper": {
        "name": "Warper",
        "shows": "The air around it folds, and the bench is suddenly a hand's width to the left.",
        "desc": "Throws whoever uses it to a hallway somewhere else on the station, then needs to recharge.",
    },
}


TELE_MULTIPLIERS = (2, 3, 4)
TELE_OFFSET_RANGE = (-9, 9)


def new_research():
    """A fresh research block for player_data.

    bench  the artifacts waiting in the Research Lab to be worked out
    tele   {"x": {"m", "c"}, "y": {"m", "c"}}: this shift's teleporter calibration (see special_rooms/research)
    """
    return {
        "bench": [],
        "tele": {axis: {"m": random.choice(TELE_MULTIPLIERS), "c": random.randint(*TELE_OFFSET_RANGE)}
                 for axis in ("x", "y")},
    }


def new_artifact():
    """An artifact nobody has worked out yet."""
    return {
        "id": ARTIFACT_ID,
        "name": "Alien Artifact",
        "description": "An object nobody on the station made. The Research Lab can work out what it does.",
        "category": "Artifact",
        "attributes": {"artifact": {
            "kind": random.choice(list(ARTIFACT_KINDS)),
            "device": random.choice(list(DEVICES)),
            "threshold": random.randint(*THRESHOLD_RANGE),
            "activated": False,
            "analysed": False,
            "ready_at": 0,
        }},
        "actions": ["examine", "use", "drop"],
    }


def artifact_of(item):
    """An item's artifact details, or None when it isn't one."""
    return (item.get("attributes") or {}).get("artifact")


def is_unknown_artifact(item):
    details = artifact_of(item)
    return details is not None and not details["analysed"]


def is_usable_artifact(item):
    details = artifact_of(item)
    return details is not None and details["analysed"]


def run_test(artifact, device, strength):
    """Put an artifact under a device at a strength. Returns (outcome, what the scientist sees), where outcome is
    "nothing", "faint", "close", "activated" or "overload"."""
    details = artifact_of(artifact)
    if device != details["device"]:
        return "nothing", f"The {DEVICES[device]} does nothing to it."
    threshold = details["threshold"]
    if strength > threshold + OVERLOAD_MARGIN:
        return "overload", "The artifact shrieks and throws out a pulse that knocks you back. That was far too much."
    if strength >= threshold:
        details["activated"] = True
        return "activated", f"The artifact comes alive. {ARTIFACT_KINDS[details['kind']]['shows']}"
    if strength >= threshold - CLOSE_MARGIN:
        return "close", "The artifact shudders and nearly catches. A little more would do it."
    return "faint", "The artifact gives off a faint hum. This is the right idea, but it needs much more."


def mark_analysed(artifact):
    """Turn a correctly analysed artifact into the named, usable thing it is."""
    details = artifact_of(artifact)
    kind = ARTIFACT_KINDS[details["kind"]]
    details["analysed"] = True
    artifact["name"] = f"{kind['name']} Artifact"
    artifact["description"] = kind["desc"]


def use_artifact(game, artifact):
    """Use an analysed artifact. Returns True when that used it up."""
    player_data = game.player_data
    details = artifact_of(artifact)
    elapsed = get_elapsed_seconds(player_data)
    name = artifact["name"]
    if elapsed < details["ready_at"]:
        game.alert(name, f"It is still recharging. Ready in {format_elapsed(details['ready_at'] - elapsed)}.")
        return False

    if details["kind"] == "power_cell":
        power = player_data["station_power"]
        power["battery_level"] = min(100, power["battery_level"] + POWER_CELL_CHARGE)
        game.add_note(f"Emptied a {name} into the station battery.")
        game.alert(name, f"The cell empties into the station battery and crumbles. Battery: "
                         f"{power['battery_level']:.0f}%.")
        return True
    if details["kind"] == "healer":
        for limb in LIMBS:
            change_limb(player_data, limb, HEALER_MEND)
        details["ready_at"] = elapsed + HEALER_RECHARGE_SECONDS
        game.add_note(f"Used the {name}.")
        game.alert(name, f"Green light washes over you. Every limb mends by {HEALER_MEND}%.")
        return False
    details["ready_at"] = elapsed + WARPER_RECHARGE_SECONDS
    player_data["location"] = pick_random_hallway_location()
    game.reset_view()
    game.add_note(f"Used the {name}.")
    game.alert(name, "The station folds around you, and you are standing somewhere else.")
    return False
