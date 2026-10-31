"""NPC hallway movement: leaving/returning to post, calling NPCs back,
wandering, goal-driven room visits, and hallway-passing detection.

Department-head NPCs (Captain, Head of Personnel, Security Guard, Doctor,
Engineer, Botanist, Bartender) are each tied to a "post" - the special room
for their job. They can randomly leave that post, then choose to wander the
hallway, beeline to another room (stay 2 ticks, then return home), or head
straight back to their station. Staff Assistants have no post; they wander
or visit rooms, then resume wandering.
"""

import random
from collections import deque

from space_online.game.maps import donut
from space_online.game.helper_methods.game_clock import get_elapsed_seconds

# Job -> the donut room key that job's NPC is posted at.
JOB_POST_KEY = {
    "Captain": donut.BRIDGE_KEY,
    "Head of Personnel": donut.BRIDGE_KEY,
    "Security Guard": donut.SECURITY_KEY,
    "Doctor": donut.MEDBAY_KEY,
    "Engineer": donut.ENGINEERING_KEY,
    "Botanist": donut.BOTANY_KEY,
    "Bartender": donut.BAR_KEY,
}

NPC_LEAVE_POST_CHANCE = 0.20
# Captain and Security Guard patrol more often (~25% higher leave chance).
PATROL_LEAVE_POST_CHANCE = 0.25
PATROL_JOBS = frozenset({"Captain", "Security Guard"})
NPC_CALL_SUCCESS_CHANCE = 0.75
NPC_AUTO_RETURN_CHANCE = 0.15
STAFF_ROOM_VISIT_CHANCE = 0.25
ROOM_VISIT_TICKS = 2
NPC_EVENT_CHANCE = 0.15

# Off-duty posted NPC three-way weights (sum to 1.0).
GOAL_WEIGHT_RETURN = NPC_AUTO_RETURN_CHANCE
GOAL_WEIGHT_ROOM = STAFF_ROOM_VISIT_CHANCE
GOAL_WEIGHT_WANDER = 1.0 - GOAL_WEIGHT_RETURN - GOAL_WEIGHT_ROOM

# Rooms NPCs may visit (not Quarters).
VISITABLE_ROOM_KEYS = tuple(
    key for key in donut.SPECIAL_ROOM_HALLWAY if key != donut.QUARTERS_KEY
)


def leave_post_chance_for(npc):
    """Return the per-round chance that this on-duty NPC leaves their post."""
    if npc.get("job") in PATROL_JOBS:
        return PATROL_LEAVE_POST_CHANCE
    return NPC_LEAVE_POST_CHANCE


# --- Lookups -----------------------------------------------------------

def has_post(npc):
    return npc.get("job") in JOB_POST_KEY


def post_key_for_job(job):
    return JOB_POST_KEY.get(job)


def npcs_for_job(station_crew, job_name):
    return [npc for npc in station_crew if npc.get("job") == job_name]


def on_duty_npc_for_job(station_crew, job_name):
    """Return the first NPC holding job_name who is currently on duty, or None."""
    for npc in npcs_for_job(station_crew, job_name):
        if npc.get("in_jail", False):
            continue
        if npc.get("on_duty", True):
            return npc
    return None


def any_npc_for_job(station_crew, job_name):
    """Return the first NPC holding job_name regardless of duty status, or None."""
    npcs = npcs_for_job(station_crew, job_name)
    return npcs[0] if npcs else None


# --- Location helpers ----------------------------------------------------

def location_for_post(job):
    """Return the {'x','y'} location dict for a job's post, or None."""
    post_key = post_key_for_job(job)
    if post_key is None:
        return None
    return donut.location_from_key(post_key)


def _is_hallway_location(location):
    key = donut.location_key(location)
    return key in donut.SHIP_MAP and key not in donut.SPECIAL_ROOM_TILES


def _is_inside_special_room(location):
    return donut.location_key(location) in donut.SPECIAL_ROOM_TILES


def _step_outside(npc, room_key):
    """Put the NPC on the hallway tile in front of room_key, or anywhere on the hallway if it has none."""
    hallway_tile = donut.SPECIAL_ROOM_HALLWAY.get(room_key)
    npc["location"] = donut.location_from_tile(hallway_tile) if hallway_tile else pick_random_hallway_location()


def _set_goal(npc, goal, room_key=None):
    npc["npc_goal"] = goal
    npc["npc_goal_room_key"] = room_key


def pick_random_hallway_location():
    """Return a random {'x','y'} location on a plain hallway tile (no special rooms)."""
    hallway_keys = [key for key in donut.SHIP_MAP if key not in donut.SPECIAL_ROOM_TILES]
    return donut.location_from_key(random.choice(hallway_keys))


def _clear_npc_goal(npc):
    _set_goal(npc, None)


# --- Goal selection --------------------------------------------------------

def _pick_visit_room_key(npc):
    """Choose a visitable room other than this NPC's own post."""
    own_post = post_key_for_job(npc.get("job")) if has_post(npc) else None
    choices = [key for key in VISITABLE_ROOM_KEYS if key != own_post]
    if not choices:  # pragma: no cover - there is always another room to visit
        choices = list(VISITABLE_ROOM_KEYS)
    return random.choice(choices)


def _pick_posted_npc_goal(npc):
    """Three-way roll: wander / visit room / return to station."""
    roll = random.random()
    if roll < GOAL_WEIGHT_RETURN:
        _set_goal(npc, "return_to_post")
    elif roll < GOAL_WEIGHT_RETURN + GOAL_WEIGHT_ROOM:
        _set_goal(npc, "visit_room", _pick_visit_room_key(npc))
    else:
        _set_goal(npc, "wander")


def _pick_staff_assistant_goal(npc):
    """Two-way roll: visit room (0.25) or wander (0.75)."""
    if random.random() < STAFF_ROOM_VISIT_CHANCE:
        _set_goal(npc, "visit_room", _pick_visit_room_key(npc))
    else:
        _set_goal(npc, "wander")


# --- Leaving post ----------------------------------------------------------

def _send_npc_wandering(npc):
    """Mark a posted NPC as off duty, place them outside their door, pick a goal."""
    npc["on_duty"] = False
    _step_outside(npc, post_key_for_job(npc.get("job")))
    npc["room_visit_remaining"] = 0
    _pick_posted_npc_goal(npc)


def roll_departures(station_crew):
    """Randomly send on-duty posted NPCs away from their post."""
    for npc in station_crew:
        if npc.get("in_jail", False):
            continue
        if not has_post(npc):
            continue
        if not npc.get("on_duty", True):
            continue
        if random.random() < leave_post_chance_for(npc):
            _send_npc_wandering(npc)


# --- Returning to post -----------------------------------------------------

def _return_to_post(npc):
    npc["on_duty"] = True
    location = location_for_post(npc.get("job"))
    if location is not None:  # pragma: no branch - every NPC sent back to its post has one
        npc["location"] = location
    npc["room_visit_remaining"] = 0
    _clear_npc_goal(npc)


def call_npc(npc, elapsed_seconds=0.0):
    """Attempt to call an off-duty NPC back to their post. Callers handle a jailed NPC first.
    Returns (success, message).
    """
    name = npc.get("name", "They")
    if npc.get("on_duty", True):
        return True, f"{name} is already at their post."

    if random.random() < NPC_CALL_SUCCESS_CHANCE:
        _return_to_post(npc)
        return True, f"{name} answers the call and heads back to their post."

    return False, f"{name} doesn't answer. Maybe try calling again later."


def reassign_npc_post(npc, new_job):
    """Move an NPC to their new job's post right after their job changes.

    Call this after mutating npc["job"] = new_job. If the new job has a post,
    the NPC immediately reports there (on duty), even if they were away from
    their old post. If the new job has no post (e.g. Staff Assistant), they
    become a wanderer instead.
    """
    if location_for_post(new_job) is not None:
        _return_to_post(npc)
    else:
        npc.pop("on_duty", None)
        npc["room_visit_remaining"] = 0
        npc["location"] = pick_random_hallway_location()
        _pick_staff_assistant_goal(npc)


# --- Pathfinding / beeline -------------------------------------------------

def _hallway_neighbor_tiles(x, y, ship_map):
    """Return adjacent hallway tiles reachable from (x, y)."""
    return list(donut.hallway_neighbors(x, y).values())


def _beeline_one_step(npc, target_xy, ship_map):
    """Move one hallway step toward target_xy. Returns True if already there."""
    location = npc["location"]
    if _is_inside_special_room(location):
        _step_outside(npc, donut.location_key(location))
        location = npc["location"]

    if not _is_hallway_location(location):
        npc["location"] = pick_random_hallway_location()
        location = npc["location"]

    start = (location["x"], location["y"])
    target = (int(target_xy[0]), int(target_xy[1]))
    if start == target:
        return True

    # BFS for shortest path; store parent pointers to reconstruct first step.
    queue = deque([start])
    parents = {start: None}
    found = False
    while queue:  # pragma: no branch - the hallway ring is connected, so the target is always found
        current = queue.popleft()
        if current == target:
            found = True
            break
        for neighbor in _hallway_neighbor_tiles(current[0], current[1], ship_map):
            if neighbor not in parents:
                parents[neighbor] = current
                queue.append(neighbor)

    if not found:  # pragma: no cover - the hallway ring is connected, so the target is always found
        _wander_one_step(npc, ship_map)
        return False

    # Walk back from target to find the step after start.
    step = target
    while parents[step] is not None and parents[step] != start:
        step = parents[step]
    npc["location"] = donut.location_from_tile(step)
    return step == target


# --- Wandering ---------------------------------------------------------

def _wander_one_step(npc, ship_map):
    """Move a wandering NPC one random valid step along the hallway ring."""
    location = npc.get("location")
    if not _is_hallway_location(location) or donut.location_key(location) not in ship_map:
        npc["location"] = pick_random_hallway_location()
        return

    neighbors = list(donut.hallway_neighbors(location["x"], location["y"]).values())
    if neighbors:  # pragma: no branch - every hallway tile has a neighbour
        npc["location"] = donut.location_from_tile(random.choice(neighbors))


def _apply_silent_npc_event(npc):
    """Apply a minor, silent stat change to a wandering NPC (no popup/log)."""
    limbs = npc.get("limbs")
    if not limbs:
        return

    outcome = random.choice(["minor_injury", "minor_heal", "nothing"])
    if outcome == "minor_injury":
        limb = random.choice(list(limbs.keys()))
        damage = random.randint(2, 8)
        limbs[limb] = max(0, limbs[limb] - damage)
    elif outcome == "minor_heal":
        injured = [limb for limb, health in limbs.items() if health < 100]
        if injured:
            limb = random.choice(injured)
            heal = random.randint(2, 8)
            limbs[limb] = min(100, limbs[limb] + heal)


def _maybe_trigger_silent_event(npc):
    if random.random() < NPC_EVENT_CHANCE:
        _apply_silent_npc_event(npc)


def _enter_room(npc, room_key, game):
    npc["location"] = donut.location_from_key(room_key)
    npc["room_visit_remaining"] = ROOM_VISIT_TICKS

    if npc.get("job") == "Security Guard":
        # jail imports this module, so it is imported here rather than at the top.
        from space_online.game.helper_methods.jail import (
            arrest_wanted_in_room,
            fined_in_room,
            resolve_fine_with_guard,
        )

        player_data = game.player_data
        elapsed_seconds = get_elapsed_seconds(player_data)
        guard_name = npc.get("name", "A security guard")

        if donut.location_key(player_data["location"]) == room_key:
            resolve_fine_with_guard(player_data, game=game, is_player=True, guard_name=guard_name,
                                    elapsed_seconds=elapsed_seconds)
        for other in fined_in_room(room_key, game.station_crew, exclude=npc):
            resolve_fine_with_guard(other, game=game, is_player=False, guard_name=guard_name,
                                    elapsed_seconds=elapsed_seconds)

        arrest_wanted_in_room(room_key, game, npc, elapsed_seconds)


def _exit_visited_room_to_hallway(npc):
    """Place the NPC on the hallway tile outside their current room."""
    _step_outside(npc, donut.location_key(npc["location"]))
    npc["room_visit_remaining"] = 0


def _tick_room_visit(npc, after_visit):
    """Count down an in-room visit; when it ends, step out to the hallway and run after_visit(npc)."""
    npc["room_visit_remaining"] -= 1
    if npc["room_visit_remaining"] <= 0:
        _exit_visited_room_to_hallway(npc)
        after_visit(npc)


def _head_back_to_post(npc):
    _set_goal(npc, "return_to_post")


def _pursue_visit_room(npc, ship_map, game):
    """Beeline to goal room; enter when at the door."""
    room_key = npc.get("npc_goal_room_key")
    if not room_key:
        npc["npc_goal"] = "wander"
        return

    location = npc["location"]
    current_key = donut.location_key(location)
    if current_key == room_key and npc.get("room_visit_remaining", 0) > 0:  # pragma: no cover - _step_wanderer handles an NPC already in the room first
        return

    hallway_tile = donut.SPECIAL_ROOM_HALLWAY.get(room_key)
    if not hallway_tile:
        npc["npc_goal"] = "wander"
        return

    arrived = _beeline_one_step(npc, hallway_tile, ship_map)
    if arrived:
        _enter_room(npc, room_key, game)


def _pursue_return_to_post(npc, ship_map):
    """Beeline to post hallway door, then clock in on duty."""
    hallway_tile = donut.SPECIAL_ROOM_HALLWAY.get(post_key_for_job(npc.get("job")))
    if not hallway_tile:  # pragma: no cover - every posted job has a door
        _return_to_post(npc)
        return

    arrived = _beeline_one_step(npc, hallway_tile, ship_map)
    if arrived:
        _return_to_post(npc)


def _step_wanderer(npc, ship_map, pick_goal, after_visit, game):
    """Advance a wandering NPC by one round: finish a room visit, head for its goal, or take a random step.

    Off-duty posted NPCs and Staff Assistants differ only in how they pick a goal and what they do
    after a visit.
    """
    goal = npc.get("npc_goal")
    if (
        goal == "visit_room"
        and npc.get("room_visit_remaining", 0) > 0
        and donut.location_key(npc["location"]) == npc.get("npc_goal_room_key")
    ):
        _tick_room_visit(npc, after_visit)
        return

    if not goal:
        pick_goal(npc)
        goal = npc.get("npc_goal")
    if goal == "visit_room":
        _pursue_visit_room(npc, ship_map, game)
        return
    if goal == "return_to_post":
        _pursue_return_to_post(npc, ship_map)
        return

    _wander_one_step(npc, ship_map)
    _maybe_trigger_silent_event(npc)
    pick_goal(npc)


def step_wanderers(game):
    """Advance every wandering NPC (off-duty posted NPCs + Staff Assistants)."""
    for npc in game.station_crew:
        if npc.get("in_jail", False):
            continue
        if has_post(npc):
            if npc.get("on_duty", True):
                continue
            pick_goal, after_visit = _pick_posted_npc_goal, _head_back_to_post
        else:
            pick_goal, after_visit = _pick_staff_assistant_goal, _clear_npc_goal
        _step_wanderer(npc, game.ship_map, pick_goal, after_visit, game)


# --- Hallway encounters ----------------------------------------------------

def find_hall_passersby(player_data, station_crew):
    """Return wandering NPCs whose location matches the player's current tile."""
    location = player_data["location"]
    player_tile = (location.get("x"), location.get("y"))

    passersby = []
    for npc in station_crew:
        if npc.get("in_jail", False):
            continue
        if has_post(npc) and npc.get("on_duty", True):
            continue
        if npc.get("room_visit_remaining", 0) > 0:
            continue

        npc_location = npc["location"]
        npc_tile = (npc_location.get("x"), npc_location.get("y"))
        if npc_tile == player_tile:
            passersby.append(npc)

    return passersby
