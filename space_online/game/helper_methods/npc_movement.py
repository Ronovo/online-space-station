"""NPC movement: who is posted where, who roams, and how each of them moves on an NPC step.

Posted crew (the holder of each post, a job in a room, see donut.ROOMS) stay at their post and work. They only leave it
now and then: on an errand to another room, after which they come straight back, or to stretch their legs for a
while. Staff Assistants have no post, and the shift's extra crew ("roams") share a job with a post holder but spend
the shift on the move; both wander the hallways and drop into rooms.

Crew who are jailed, asleep, or too badly hurt to work (see health_bands.is_incapacitated) don't move at all.

When the crew shuttle is on its way the crew make for Departures to board it: those who aren't at a post as soon
as it is called, those who are once it docks. A few don't notice and carry on as they were.
"""

import random

from space_online.game.helper_methods.health_bands import change_limb, is_incapacitated
from space_online.game.maps import donut

# Every post as (job, room key), in map order, and each job's post rooms.
POSTS = tuple((job, key) for key, room in donut.ROOMS.items() for job in room.posts)
JOB_POSTS = {job: tuple(key for post_job, key in POSTS if post_job == job) for job, _ in POSTS}

# Chances per NPC step that a posted crew member at their post leaves it.
ERRAND_CHANCE = 0.0125
STROLL_CHANCE = 0.01
# The Captain and Security Guards patrol, so they stroll more often.
PATROL_STROLL_CHANCE = 0.02
PATROL_JOBS = frozenset({"Captain", "Security Guard"})
STROLL_STEPS = 20
NPC_CALL_SUCCESS_CHANCE = 0.75
ROAMER_ROOM_VISIT_CHANCE = 0.25
ROOM_VISIT_TICKS = 5
NPC_EVENT_CHANCE = 0.15
STAY_BEHIND_CHANCE = 0.10

# Rooms NPCs may visit (not Quarters).
VISITABLE_ROOM_KEYS = tuple(key for key in donut.ROOMS if key != donut.QUARTERS_KEY)

# Called with (npc, room_key, game) when an NPC walks into a room, and with (npc) after each wandering step.
ROOM_ENTRY_HOOKS = []
WANDER_HOOKS = []


# --- Lookups -----------------------------------------------------------

def is_posted(npc):
    """Whether this NPC holds a post: a job with a room, and not one of the shift's roaming extras."""
    return npc["job"] in JOB_POSTS and not npc.get("roams")


def can_work(npc):
    """Whether this NPC is free, awake and fit to do anything at all."""
    return not npc.get("in_jail") and not npc["asleep"] and not is_incapacitated(npc)


def crew_named(station_crew, name):
    """The NPC called name, or None. Crew names are unique for a shift."""
    return next((npc for npc in station_crew if npc["name"] == name), None)


def post_holder(station_crew, job_name, room_key=None):
    """The NPC posted as job_name in room_key, or in any of the job's rooms with no room, wherever they are right
    now. None when nobody holds the post."""
    return next((npc for npc in station_crew if npc["job"] == job_name and is_posted(npc)
                 and room_key in (None, npc["post_key"])), None)


def on_duty_npc_for_job(station_crew, job_name, room_key=None):
    """The NPC post_holder finds if they are at their post and able to work, else None."""
    npc = post_holder(station_crew, job_name, room_key)
    return npc if npc is not None and npc["on_duty"] and can_work(npc) else None


def player_holds_post(player_data, job_name, room_key=None):
    """Whether the player holds job_name's post in room_key, or any of its posts with no room. A player in the job
    who has no post_key (one room's job, or one taken on mid-shift) holds every one of its posts."""
    if player_data["job"] != job_name:
        return False
    return room_key is None or player_data["post_key"] in (None, room_key)


def open_post(player_data, station_crew, job_name):
    """The room key of job_name's first post that neither the player nor an NPC holds, else of its first post."""
    rooms = JOB_POSTS[job_name]
    return next((key for key in rooms if not player_holds_post(player_data, job_name, key)
                 and post_holder(station_crew, job_name, key) is None), rooms[0])


def location_for_post(npc):
    """The {'x','y'} location of a posted NPC's post."""
    return donut.location_from_key(npc["post_key"])


def pick_random_hallway_location():
    """A random {'x','y'} location on a plain hallway tile."""
    hallway_keys = [key for key in donut.SHIP_MAP if key not in donut.ROOMS]
    return donut.location_from_key(random.choice(hallway_keys))


def _set_goal(npc, goal, room_key=None):
    npc["npc_goal"] = goal
    npc["npc_goal_room_key"] = room_key


def _step_outside(npc):
    """Put an NPC who is inside a room on the hallway tile in front of its door."""
    room = donut.ROOMS.get(donut.location_key(npc["location"]))
    if room is not None:
        npc["location"] = donut.location_from_tile(room.hallway)
    npc["room_visit_remaining"] = 0


def _pick_visit_room_key(npc):
    """A visitable room that isn't one of the posts of this NPC's job."""
    own_posts = JOB_POSTS.get(npc["job"], ())
    return random.choice([key for key in VISITABLE_ROOM_KEYS if key not in own_posts])


# --- Posts ---------------------------------------------------------------

def _return_to_post(npc):
    npc["on_duty"] = True
    npc["location"] = location_for_post(npc)
    npc["room_visit_remaining"] = 0
    npc["stroll_remaining"] = 0
    _set_goal(npc, None)


def _leave_post(npc, goal, room_key=None):
    npc["on_duty"] = False
    _step_outside(npc)
    _set_goal(npc, goal, room_key)
    npc["stroll_remaining"] = STROLL_STEPS if goal == "wander" else 0


def _maybe_leave_post(npc):
    """A posted NPC at work sometimes heads off on an errand to another room, or just goes for a walk."""
    roll = random.random()
    stroll_chance = PATROL_STROLL_CHANCE if npc["job"] in PATROL_JOBS else STROLL_CHANCE
    if roll < ERRAND_CHANCE:
        _leave_post(npc, "visit_room", _pick_visit_room_key(npc))
    elif roll < ERRAND_CHANCE + stroll_chance:
        _leave_post(npc, "wander")


def send_for_a_walk(npc):
    """Send a posted NPC who is at their post off it for a while."""
    _leave_post(npc, "wander")


def call_npc(npc):
    """Try to call a posted NPC back to their post. Callers handle a jailed or incapacitated NPC first.
    Returns (success, message).
    """
    name = npc["name"]
    if npc["on_duty"]:
        return True, f"{name} is already at their post."
    if random.random() < NPC_CALL_SUCCESS_CHANCE:
        _return_to_post(npc)
        return True, f"{name} answers the call and heads back to their post."
    return False, f"{name} doesn't answer. Maybe try calling again later."


def reassign_npc_post(game, npc, new_job):
    """Settle an NPC into a job they were just given (call it after setting npc["job"]).

    A job with a post puts them at its open_post, on duty, and ends any roaming. A job without one sets them
    wandering. A jailed NPC stays in the cell and goes to the post when released.
    """
    npc.pop("roams", None)
    posted = new_job in JOB_POSTS
    npc["post_key"] = open_post(game.player_data, [other for other in game.station_crew if other is not npc],
                                new_job) if posted else None
    if npc.get("in_jail"):
        return
    if posted:
        _return_to_post(npc)
        return
    npc.pop("on_duty", None)
    npc["room_visit_remaining"] = 0
    npc["location"] = pick_random_hallway_location()
    _pick_roamer_goal(npc)


# --- Walking -------------------------------------------------------------

def _is_hallway_location(location):
    key = donut.location_key(location)
    return key in donut.SHIP_MAP and key not in donut.ROOMS


def _beeline_one_step(npc, target):
    """Move one hallway step toward the target tile. Returns True once the NPC is standing on it."""
    _step_outside(npc)
    if not _is_hallway_location(npc["location"]):
        npc["location"] = pick_random_hallway_location()
    step = donut.step_toward((npc["location"]["x"], npc["location"]["y"]), target)
    npc["location"] = donut.location_from_tile(step)
    return step == target


def _wander_one_step(npc):
    """Move one random step along the hallways, then let whatever watches wanderers have its say."""
    location = npc["location"]
    if not _is_hallway_location(location):
        npc["location"] = pick_random_hallway_location()
    else:
        neighbors = list(donut.hallway_neighbors(location["x"], location["y"]).values())
        npc["location"] = donut.location_from_tile(random.choice(neighbors))
    if random.random() < NPC_EVENT_CHANCE:
        _apply_silent_npc_event(npc)
    for hook in WANDER_HOOKS:
        hook(npc)


def _apply_silent_npc_event(npc):
    """A wandering NPC picks up a small knock, shakes one off, or neither. Nothing is said about it."""
    outcome = random.choice(["minor_injury", "minor_heal", "nothing"])
    limbs = npc["limbs"]
    if outcome == "minor_injury":
        change_limb(npc, random.choice(list(limbs)), -random.randint(2, 8))
    elif outcome == "minor_heal":
        injured = [limb for limb, health in limbs.items() if health < 100]
        if injured:
            change_limb(npc, random.choice(injured), random.randint(2, 8))


def _enter_room(npc, room_key, game):
    npc["location"] = donut.location_from_key(room_key)
    npc["room_visit_remaining"] = ROOM_VISIT_TICKS
    for hook in ROOM_ENTRY_HOOKS:
        hook(npc, room_key, game)


def _pursue_visit_room(npc, game):
    """Walk to the goal room's door and go in."""
    room = donut.ROOMS.get(npc["npc_goal_room_key"])
    if room is None:
        _set_goal(npc, "wander")
    elif _beeline_one_step(npc, room.hallway):
        _enter_room(npc, npc["npc_goal_room_key"], game)


def _pick_roamer_goal(npc):
    if random.random() < ROAMER_ROOM_VISIT_CHANCE:
        _set_goal(npc, "visit_room", _pick_visit_room_key(npc))
    else:
        _set_goal(npc, "wander")


def _step_away_from_post(npc, game):
    """One step for a posted NPC who is off duty: finish the errand or the walk, then head back."""
    goal = npc["npc_goal"]
    if goal == "visit_room" and npc["room_visit_remaining"] > 0:
        npc["room_visit_remaining"] -= 1
        if npc["room_visit_remaining"] <= 0:
            _step_outside(npc)
            _set_goal(npc, "return_to_post")
    elif goal == "visit_room":
        _pursue_visit_room(npc, game)
    elif goal == "wander" and npc["stroll_remaining"] > 0:
        npc["stroll_remaining"] -= 1
        _wander_one_step(npc)
    elif _beeline_one_step(npc, donut.ROOMS[npc["post_key"]].hallway):
        _return_to_post(npc)


def _step_roamer(npc, game):
    """One step for crew with no post to go back to: drop into rooms, otherwise wander."""
    if npc["room_visit_remaining"] > 0:
        npc["room_visit_remaining"] -= 1
        if npc["room_visit_remaining"] <= 0:
            _step_outside(npc)
            _set_goal(npc, None)
        return
    if not npc["npc_goal"]:
        _pick_roamer_goal(npc)
    if npc["npc_goal"] == "visit_room":
        _pursue_visit_room(npc, game)
    else:
        _wander_one_step(npc)
        _pick_roamer_goal(npc)


def _at_post(npc):
    return is_posted(npc) and npc["on_duty"]


def send_to_shuttle(station_crew, idle_only):
    """Tell the crew to board the shuttle: with idle_only just those who aren't at a post. Each is asked once, and
    now and then one doesn't notice and stays behind."""
    for npc in station_crew:
        if (not can_work(npc) or npc["npc_goal"] == "board" or npc.get("stays_behind")
                or (idle_only and _at_post(npc))):
            continue
        if random.random() < STAY_BEHIND_CHANCE:
            npc["stays_behind"] = True
        else:
            hurry_to_shuttle(npc)


def hurry_to_shuttle(npc):
    """Send a crew member off to board the shuttle, whether or not they noticed the call."""
    npc.pop("stays_behind", None)
    _leave_post(npc, "board", donut.DEPARTURES_KEY)


def recall_from_shuttle(station_crew):
    """The shuttle isn't coming after all: everyone on their way to it goes back to what they were doing."""
    for npc in station_crew:
        npc.pop("stays_behind", None)
        if npc["npc_goal"] == "board":
            _step_outside(npc)
            _set_goal(npc, "return_to_post" if is_posted(npc) else None)


def crew_aboard(station_crew):
    """The crew waiting in Departures, who are aboard the shuttle when it leaves."""
    return [npc for npc in station_crew if donut.location_key(npc["location"]) == donut.DEPARTURES_KEY]


def _step_boarding(npc):
    """Walk to the Departures door and go in. Once there, stay."""
    if npc not in crew_aboard([npc]) and _beeline_one_step(npc, donut.ROOMS[donut.DEPARTURES_KEY].hallway):
        npc["location"] = donut.location_from_key(donut.DEPARTURES_KEY)


def step_crew(game):
    """Move every NPC who is free and fit to move by one NPC step."""
    for npc in game.station_crew:
        if not can_work(npc):
            continue
        if npc["npc_goal"] == "board":
            _step_boarding(npc)
        elif not is_posted(npc):
            _step_roamer(npc, game)
        elif npc["on_duty"]:
            _maybe_leave_post(npc)
        else:
            _step_away_from_post(npc, game)


# --- Hallway encounters ----------------------------------------------------

def find_hall_passersby(player_data, station_crew):
    """The NPCs out in the hallways who are on the player's tile."""
    here = donut.location_key(player_data["location"])
    return [npc for npc in station_crew
            if can_work(npc)
            and not _at_post(npc)
            and npc["room_visit_remaining"] <= 0
            and donut.location_key(npc["location"]) == here]
