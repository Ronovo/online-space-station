"""Universal master game clock.

Every timed system in the game (power, oxygen, alcohol, jail, the stock
market, NPC wandering) reads its "now" from a single elapsed-seconds
counter here instead of calling ``datetime.now()`` independently. The
counter starts at 0 for a new game and only ever advances forward.

Each tick adds the real time passed since ``last_real_time`` to
``elapsed_seconds``, up to MAX_TICK_SECONDS, so the shift stands still while
nobody is playing it. Game systems schedule an absolute ``*_at_seconds`` value
against this timer and compute "remaining" as that value minus the current
``elapsed_seconds``.
"""

import time

MAX_TICK_SECONDS = 5.0


def default_game_clock():
    return {
        "elapsed_seconds": 0.0,
        "last_real_time": time.time(),
    }


def advance(player_data):
    """Advance the master timer by the real time elapsed since the last call, up to MAX_TICK_SECONDS.

    Returns (elapsed_seconds, delta_seconds).
    """
    clock = player_data["game_clock"]

    now = time.time()
    delta_seconds = min(MAX_TICK_SECONDS, max(0.0, now - clock["last_real_time"]))
    clock["elapsed_seconds"] += delta_seconds
    clock["last_real_time"] = now

    return clock["elapsed_seconds"], delta_seconds


def pass_time(player_data, seconds):
    """Move the master timer on by the game seconds an action takes, on top of the real time played."""
    player_data["game_clock"]["elapsed_seconds"] += seconds


def seconds_since_last_tick(player_data):
    return time.time() - player_data["game_clock"]["last_real_time"]


def get_elapsed_seconds(player_data):
    return player_data["game_clock"]["elapsed_seconds"]


def format_elapsed(seconds):
    """Format a duration as 'Hh Mm Ss', 'Mm Ss', or 'Ss' (largest units first)."""
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
