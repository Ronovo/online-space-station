"""Hunger and thirst.

player_data["needs"] holds hunger and thirst, each from 0 (satisfied) to 100. Both climb on the master clock; food
brings hunger down and a drink brings thirst down. A need at 100 wears the player's limbs down until it is met.
"""

import random

from space_online.game.helper_methods.health_bands import LIMBS, change_limb

NEED_PER_MINUTE = {"hunger": 4, "thirst": 5}
NEED_WARNING = 60
NEED_WARNINGS = {
    "hunger": ("You are getting hungry. The Kitchen serves food.",
               "You are starving. Eat something before it wears you down."),
    "thirst": ("You are getting thirsty. The Bar serves drinks.",
               "You are parched. Drink something before it wears you down."),
}
STARVING_HURT_SECONDS = 30
STARVING_DAMAGE = 2
# What food and drink do for an item that doesn't say.
DEFAULT_FEEDS = 20
DEFAULT_QUENCHES = 40


def new_needs():
    return {need: 0 for need in NEED_PER_MINUTE}


def satisfy(player_data, need, amount):
    """Bring a need down by amount. Returns where that leaves it."""
    needs = player_data["needs"]
    needs[need] = max(0, needs[need] - amount)
    return needs[need]


def tick_needs(game, delta_seconds):
    """Let hunger and thirst climb, say so as each gets serious, and hurt a player who has let one run out."""
    player_data = game.player_data
    needs = player_data["needs"]
    for need, per_minute in NEED_PER_MINUTE.items():
        before = needs[need]
        needs[need] = min(100, before + per_minute * delta_seconds / 60)
        early, late = NEED_WARNINGS[need]
        if before < 100 <= needs[need]:
            game.alert(need.title(), late, kind="error")
        elif before < NEED_WARNING <= needs[need]:
            game.alert(need.title(), early, kind="warning")

    timers = player_data["damage_timers"]
    if max(needs.values()) < 100:
        timers["needs_acc"] = 0.0
        return
    timers["needs_acc"] = timers.get("needs_acc", 0.0) + delta_seconds
    while timers["needs_acc"] >= STARVING_HURT_SECONDS:
        timers["needs_acc"] -= STARVING_HURT_SECONDS
        change_limb(player_data, random.choice(LIMBS), -STARVING_DAMAGE)
