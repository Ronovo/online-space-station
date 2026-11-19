"""Room hazards: a hull breach, a fire or bad wiring in one room, until someone deals with it.

player_data["ship_map"][room key]["hazard"] names the hazard in that room, or is None.
player_data["hazards"]["next_at"] is the game second at which the next one breaks out.

A hazard hurts the player for as long as they stand in the room and clears the room's crew out of it, so the post
there does no work (the Engineer stays on to fix their own). It is dealt with from inside the room with the right
tool, or by the NPC Engineer in time.
"""

import random

from space_online.game.helper_methods import gas_mix
from space_online.game.helper_methods.errands import record_duty_done
from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.health_bands import LIMBS, change_limb, limb_label
from space_online.game.maps.donut import DEPARTURES_KEY, QUARTERS_KEY, ROOMS, location_key
from space_online.game.objects.gases import OXYGEN_RICH, STATION_AIR
from space_online.game.objects.items import get_item_definition, has_tool

HAZARDS = {
    "breach": {
        "name": "hull breach",
        "starts": "A hull breach has opened in the {room}. The air is venting out.",
        "here": "The air is screaming out through a breach in the hull.",
        "tool": "wrench",
        "fix": "Seal the Breach",
        "fixed": "You bolt a patch over the breach with the {tool}. The air holds.",
        "damage": "oxygen",
        "hurts": "You gasp for air in the thin atmosphere. Oxygen damage: {total}%.",
    },
    "fire": {
        "name": "fire",
        "starts": "A fire has broken out in the {room}.",
        "here": "Part of the room is on fire, and the smoke is thick.",
        "tool": "fire_extinguisher",
        "fix": "Put Out the Fire",
        "fixed": "You smother the fire with the {tool}.",
        "damage": "burn",
        "hurts": "The fire burns you. Burn damage: {total}%.",
    },
    "wiring": {
        "name": "electrical fault",
        "starts": "The wiring in the {room} has shorted and is arcing across the room.",
        "here": "Bare wires are arcing across the room.",
        "tool": "wirecutters",
        "fix": "Cut the Live Wires",
        "fixed": "You cut out the shorted wiring with the {tool}.",
        "damage": None,
        "hurts": "A live wire catches your {limb}. It is at {total}%.",
    },
}

HAZARD_INTERVAL_RANGE = (4 * 60, 7 * 60)
HAZARD_HURT_SECONDS = 10
HAZARD_DAMAGE = 6
# A fire burns hotter while the station's air is Oxygen-rich.
RICH_FIRE_DAMAGE = 10
# A hazard on its own never quite kills: it leaves the last of the damage to whatever else is wrong.
HAZARD_DAMAGE_CAP = 95
HAZARD_ROOM_KEYS = tuple(key for key in ROOMS if key not in (QUARTERS_KEY, DEPARTURES_KEY))


def new_hazards():
    return {"next_at": random.randint(*HAZARD_INTERVAL_RANGE)}


def room_hazard(player_data, room_key):
    """The kind of hazard in a room, or None."""
    return player_data["ship_map"][room_key].get("hazard")


def hazard_rooms(player_data):
    """[(room key, kind)] for every room with a hazard."""
    return [(key, room_hazard(player_data, key)) for key in HAZARD_ROOM_KEYS if room_hazard(player_data, key)]


def set_hazard(player_data, room_key, kind):
    player_data["ship_map"][room_key]["hazard"] = kind


def start_hazard(game, room_key, kind):
    """Break a hazard out in a room and tell the station."""
    set_hazard(game.player_data, room_key, kind)
    message = HAZARDS[kind]["starts"].format(room=ROOMS[room_key].name)
    game.announce("Hazard", message, kind="warning")
    game.add_note(message)


def start_random_hazard(game):
    """Break a random hazard out in a room that doesn't have one. Returns (room key, kind), or None if all do."""
    safe = [key for key in HAZARD_ROOM_KEYS if not room_hazard(game.player_data, key)]
    if not safe:
        return None
    room_key, kind = random.choice(safe), random.choice(list(HAZARDS))
    start_hazard(game, room_key, kind)
    return room_key, kind


def clear_hazard(player_data, room_key):
    set_hazard(player_data, room_key, None)


def fix_hazard(game, room_key):
    """The player deals with the hazard in the room they are standing in, given the tool for it."""
    player_data = game.player_data
    kind = room_hazard(player_data, room_key)
    if kind is None:
        return
    hazard = HAZARDS[kind]
    tool = get_item_definition(hazard["tool"])["name"]
    if not has_tool(player_data, hazard["tool"]):
        game.alert("Hazard", f"You need a {tool} to deal with the {hazard['name']}.", kind="warning")
        return
    clear_hazard(player_data, room_key)
    if player_data["job"] == "Engineer":
        record_duty_done(player_data)
    message = hazard["fixed"].format(tool=tool.lower())
    game.alert("Hazard", message)
    game.add_note(message)


def _hit(player_data, kind):
    """How much one hit of a hazard does."""
    rich = gas_mix.partial_pressure(player_data["atmos"]["air"], STATION_AIR["volume"], "Oxygen") > OXYGEN_RICH
    return RICH_FIRE_DAMAGE if kind == "fire" and rich else HAZARD_DAMAGE


def _hurt_player(game, kind):
    player_data = game.player_data
    hazard = HAZARDS[kind]
    if hazard["damage"]:
        damage = player_data["damage"]
        damage[hazard["damage"]] = max(damage[hazard["damage"]],
                                       min(HAZARD_DAMAGE_CAP, damage[hazard["damage"]] + _hit(player_data, kind)))
        message = hazard["hurts"].format(total=damage[hazard["damage"]])
    else:
        limb = random.choice(LIMBS)
        _, total = change_limb(player_data, limb, -HAZARD_DAMAGE)
        message = hazard["hurts"].format(limb=limb_label(limb).lower(), total=total)
    game.alert("Hazard", message, kind="warning")


def tick_hazards(game, delta_seconds):
    """Break out the next hazard when it is due, and hurt a player who is standing in one."""
    player_data = game.player_data
    elapsed = get_elapsed_seconds(player_data)
    state = player_data["hazards"]
    if elapsed >= state["next_at"]:
        state["next_at"] = elapsed + random.randint(*HAZARD_INTERVAL_RANGE)
        start_random_hazard(game)

    timers = player_data["damage_timers"]
    here = location_key(player_data["location"])
    kind = room_hazard(player_data, here) if here in HAZARD_ROOM_KEYS else None
    if kind is None or player_data["mining"]["expedition"]:
        timers["hazard_acc"] = 0.0
        return
    timers["hazard_acc"] = timers.get("hazard_acc", 0.0) + delta_seconds
    while timers["hazard_acc"] >= HAZARD_HURT_SECONDS:
        timers["hazard_acc"] -= HAZARD_HURT_SECONDS
        _hurt_player(game, kind)
