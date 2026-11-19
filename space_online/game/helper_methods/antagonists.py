"""Antagonists: the threats that turn up during a round, what they do, and how the station answers.

player_data["threats"] lists the round's threats. Each holds:
    type         a THREAT_TYPES key
    crew_name    the crew member who is secretly it, or None for an outsider
    name         what it is called once it has shown itself, as it reads mid-sentence ("the Wizard")
    starts_at    game seconds at which it makes its first move
    next_act_at  game seconds of its next move
    acts         how many moves it has made, and reveal_after how many it makes before it attacks openly
    revealed     True once everyone knows who or what it is
    hp, attack, extra, humanoid   its fighting numbers, as combat enemies have them
    location     where it was last seen, once revealed
    objective    {"kind": an OBJECTIVES key, "target": the crew member it is after or None, "progress"}
    fate         None while it is loose, then how it ended
    hurt         the names of the crew it has already attacked

player_data["incidents"] lists what the threats have done, for whoever investigates: each has at (game seconds),
where, what, and away, the crew who were off their posts at the time. A crew threat is always one of them, so
whoever is away for every incident is worth a warrant: jailing a hidden threat ends it before it strikes. Cargo
records each order of dangerous gas there too, with away None, which the away count leaves out.
"""

import random

from space_online.game.helper_methods import gas_mix
from space_online.game.helper_methods.combat import capitalized, register_fight, start_fight
from space_online.game.helper_methods.door_control import can_control_door
from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.health_bands import LIMBS, change_limb
from space_online.game.helper_methods.jail import ARREST_HOOKS, LAW_ABIDING_JOBS, is_jailed, set_warrant
from space_online.game.helper_methods.npc_movement import (
    can_work,
    crew_aboard,
    crew_named,
    is_posted,
    pick_random_hallway_location,
    send_for_a_walk,
)
from space_online.game.helper_methods.power_constants import FAULTABLE_SYSTEMS, fault_system, system_name
from space_online.game.helper_methods.rounds import (
    DEPARTURE_HOOKS,
    PEACEFUL,
    call_for_red_alert,
    kill_player,
    round_over,
)
from space_online.game.helper_methods.station_air import RESERVOIR_FILL
from space_online.game.helper_methods.ui_panels import register_panel
from space_online.game.maps import donut
from space_online.game.objects.gases import ROOM_TEMP

# "acts" are the ACTS a threat picks from, and "objective" the OBJECTIVES entry it is out to achieve. A crew threat
# hides as a crew member until it shows itself.
THREAT_TYPES = {
    "Traitor": {"crew": True, "hp": 45, "attack": (6, 12), "extra": None, "humanoid": True,
                "acts": ("sabotage", "sabotage", "frame", "contaminate", "bomb"), "objective": "sabotage"},
    "Vampire": {"crew": True, "hp": 55, "attack": (8, 14), "extra": None, "humanoid": True,
                "acts": ("maul",), "objective": "hurt"},
    "Changeling": {"crew": True, "hp": 50, "attack": (7, 13), "extra": ("poison", 5), "humanoid": True,
                   "acts": ("poison", "frame"), "objective": "hurt"},
    "Cultist": {"crew": True, "hp": 40, "attack": (6, 11), "extra": ("burn", 4), "humanoid": True,
                "acts": ("burn", "dim"), "objective": "hurt"},
    "Wizard": {"crew": False, "hp": 45, "attack": (8, 15), "extra": ("burn", 6), "humanoid": True,
               "acts": ("burn", "dim"), "objective": "hurt"},
    "Alien": {"crew": False, "hp": 60, "attack": (10, 18), "extra": None, "humanoid": False,
              "acts": ("maul",), "objective": "hurt"},
    "Space Pirate": {"crew": False, "hp": 50, "attack": (8, 14), "extra": None, "humanoid": True,
                     "acts": ("steal", "maul"), "objective": "steal"},
    "Rogue Bot": {"crew": False, "hp": 55, "attack": (7, 13), "extra": None, "humanoid": False,
                  "acts": ("sabotage", "dim"), "objective": "sabotage"},
}

# What a threat is out to do: the acts that count toward it, how much of them it takes, and how the shift report
# puts it. A "hurt" objective is after one crew member, and only what is done to them counts.
OBJECTIVES = {
    "sabotage": {"acts": ("sabotage", "dim", "contaminate", "bomb"), "goal": 3, "text": "cripple the station's systems"},
    "hurt": {"acts": ("maul", "poison", "burn"), "goal": 2, "text": "put {target} out of action"},
    "steal": {"acts": ("steal",), "goal": 400, "text": "steal 400 credits"},
}

MAX_THREATS = 3
FIRST_START_RANGE_SECONDS = (5 * 60, 12 * 60)
LATER_START_RANGE_SECONDS = (10 * 60, 25 * 60)
ACT_GAP_RANGE_SECONDS = (180, 300)
REVEAL_AFTER_RANGE = (3, 4)
# The charge on a framed crew member's warrant. Its wording is the tell: no real warrant reads like it.
FRAME_CHARGE = "Sabotage (anonymous tip)"
# A threat that has shown itself counts this much toward the alert on top of its moves.
REVEAL_SCORE = 2
# (score needed, level, colour), highest first.
ALERT_LEVELS = ((6, "Red", "#FF0000"), (3, "Orange", "#FF9900"), (1, "Yellow", "#FFFF00"), (0, "Green", "#00FF00"))

# Each crew move there is this chance that Security or the Captain catches up with a revealed threat.
CREW_ENGAGE_CHANCE = 0.05
CREW_HIT_RANGE = (8, 16)
CREW_HURT_RANGE = (5, 15)
VICTIM_LIMB_RANGE = (15, 30)
VICTIM_DAMAGE = 20
STEAL_RANGE = (100, 300)
LIGHTS_DIMMED_BY = 3
COOLANT_LINE = "coolant_line"
# What a Traitor who can work the Atmospherics station pumps into the life support reservoir, and how much.
CONTAMINANTS = ("Plasma", "Carbon Dioxide")
CONTAMINATE_MOLES = RESERVOIR_FILL / 4
# Aboard the shuttle, a threat that goes for a crew member loses this share of its full health for every crew
# member aboard who can fight back, up to the most they can take off it at once.
SHUTTLE_CREW_HIT = 0.05
SHUTTLE_CREW_HIT_MAX = 0.60


def new_threats(mode, station_crew):
    """The threats for a round: none in a Peaceful one, otherwise one to MAX_THREATS of different types."""
    if mode == PEACEFUL:
        return []
    threats = []
    hosts = [npc for npc in station_crew if npc["job"] not in LAW_ABIDING_JOBS]
    random.shuffle(hosts)
    for index, kind in enumerate(random.sample(list(THREAT_TYPES), random.randint(1, MAX_THREATS))):
        details = THREAT_TYPES[kind]
        host = hosts.pop() if details["crew"] and hosts else None
        starts_at = random.randint(*(LATER_START_RANGE_SECONDS if index else FIRST_START_RANGE_SECONDS))
        marks = [npc["name"] for npc in station_crew if npc is not host]
        target = random.choice(marks) if details["objective"] == "hurt" and marks else None
        threats.append({
            "type": kind,
            "crew_name": host["name"] if host else None,
            "name": f"{host['name']} the {kind}" if host else f"the {kind}",
            "starts_at": starts_at,
            "next_act_at": starts_at,
            "acts": 0,
            "reveal_after": random.randint(*REVEAL_AFTER_RANGE),
            "revealed": False,
            "hp": details["hp"],
            "attack": details["attack"],
            "extra": details["extra"],
            "humanoid": details["humanoid"],
            "location": None,
            "objective": {"kind": details["objective"], "target": target, "progress": 0},
            "fate": None,
            "hurt": [],
        })
    return threats


def loose_threats(player_data):
    """The threats that have made a move and haven't been dealt with."""
    return [threat for threat in player_data["threats"] if threat["acts"] and threat["fate"] is None]


def _fighting_player(player_data, threat):
    """Whether the player is fighting this threat right now. Until that is settled it does nothing else."""
    fight = player_data["fight"]
    return bool(fight) and fight["kind"] == "threat" and player_data["threats"][fight["threat"]] is threat


def threat_score(player_data):
    return sum(threat["acts"] + (REVEAL_SCORE if threat["revealed"] else 0) for threat in loose_threats(player_data))


def alert_level(player_data):
    """(level, colour) for the station alert, which rises with what the loose threats have done."""
    score = threat_score(player_data)
    return next((level, color) for needed, level, color in ALERT_LEVELS if score >= needed)


def sightings(player_data):
    """A line for each revealed threat still loose, saying where it was last seen."""
    return [f"{capitalized(threat['name'])} was last seen in the "
            f"{donut.SHIP_MAP[donut.location_key(threat['location'])]['name']}."
            for threat in loose_threats(player_data) if threat["revealed"]]


def objective_text(threat):
    """What a threat was out to do and whether it managed it, for the shift report."""
    objective = threat["objective"]
    details = OBJECTIVES[objective["kind"]]
    achieved = objective["progress"] >= details["goal"]
    return f"Out to {details['text'].format(target=objective['target'])}: {'achieved' if achieved else 'foiled'}."


def threat_report(player_data):
    """(what it was, how it ended, what it was after) for each of the round's threats, for the shift summary."""
    report = []
    for threat in player_data["threats"]:
        if threat["fate"]:
            fate = threat["fate"]
        elif not threat["acts"]:
            fate = "never made a move"
        elif threat["revealed"]:
            fate = "still at large when the shuttle left"
        else:
            fate = "was never found out"
        report.append((capitalized(threat["name"]), fate, objective_text(threat)))
    return report


def _victims(game, threat):
    return [npc for npc in game.station_crew if not is_jailed(npc) and npc["name"] != threat["crew_name"]]


def _pick_victim(game, threat):
    """Who a threat goes for: the crew member its objective is after while it can reach them, otherwise anyone.
    Returns None when there is nobody."""
    victims = _victims(game, threat)
    mark = crew_named(victims, threat["objective"]["target"])
    return mark or (random.choice(victims) if victims else None)


def _place_name(member):
    return donut.SHIP_MAP[donut.location_key(member["location"])]["name"]


def _hurt_victim(victim):
    change_limb(victim, random.choice(LIMBS), -random.randint(*VICTIM_LIMB_RANGE))


# Every act returns (what happened, where), or None when there was nothing for it to do.
def _hurt_before(threat, victim):
    """Whether threat has attacked victim before, remembering that it has now."""
    before = victim["name"] in threat["hurt"]
    if not before:
        threat["hurt"].append(victim["name"])
    return before


def _maul(game, threat):
    victim = _pick_victim(game, threat)
    if victim is None:
        return None
    _hurt_victim(victim)
    what = "was attacked again" if _hurt_before(threat, victim) else "was found badly hurt"
    return f"{victim['name']} {what}.", _place_name(victim)


def _afflict(dtype, found):
    def act(game, threat):
        victim = _pick_victim(game, threat)
        if victim is None:
            return None
        victim["damage"][dtype] = min(100, victim["damage"][dtype] + VICTIM_DAMAGE)
        again = " again" if _hurt_before(threat, victim) else ""
        return f"{victim['name']} {found}{again}.", _place_name(victim)
    return act


def _sabotage(game, threat):
    """Fault a working system or cut the Combustion Engine's coolant line, picked at random, and failing those shut
    the solar array down."""
    power, engine = game.player_data["station_power"], game.player_data["engine"]
    targets = [key for key in FAULTABLE_SYSTEMS if key not in power["faults"]]
    if not engine["coolant_fault"]:
        targets.append(COOLANT_LINE)
    if targets:
        system_key = random.choice(targets)
        if system_key == COOLANT_LINE:
            engine["coolant_fault"] = True
            return "Someone has cut the engine's coolant line.", "Engineering Bay"
        fault_system(power, system_key)
        return (f"Someone has sabotaged the {system_name(system_key)}. It needs repairing from the Engineering Panel.",
                "Engineering Bay")
    if power["solar_charging"]:
        power["solar_charging"] = False
        return "The solar array has been shut down from outside Engineering.", "Engineering Bay"
    return None


def _contaminate(game, threat):
    host = _host(game, threat)
    if host is None or not can_control_door(host, donut.ATMOSPHERICS_KEY):
        return None
    gas = random.choice(CONTAMINANTS)
    gas_mix.merge(game.player_data["atmos"]["reservoir"], gas_mix.mix_of({gas: 1}, CONTAMINATE_MOLES, ROOM_TEMP))
    return "Someone has tampered with the life support reservoir.", donut.ROOMS[donut.ATMOSPHERICS_KEY].name


def _frame(game, threat):
    innocents = [npc for npc in _victims(game, threat)
                 if npc["job"] not in LAW_ABIDING_JOBS and not npc.get("warrant")]
    if not innocents:
        return None
    innocent = random.choice(innocents)
    set_warrant(innocent, FRAME_CHARGE)
    return f"A warrant has gone out for {innocent['name']} for sabotage, on evidence nobody can trace.", "Security"


def _dim(game, threat):
    """Lower the hallway lighting, remembering the level it had before the first dim for the Engineer to restore."""
    power = game.player_data["station_power"]
    levels = power["system_levels"]
    if levels["hallway_lighting"] <= 1:
        return None
    if power["dimmed_from"] is None:
        power["dimmed_from"] = levels["hallway_lighting"]
    levels["hallway_lighting"] = max(1, levels["hallway_lighting"] - LIGHTS_DIMMED_BY)
    return "The lights flicker and dim across the station.", "the hallways"


def _steal(game, threat):
    credits = game.player_data["credits"]
    taken = min(credits, random.randint(*STEAL_RANGE))
    if taken <= 0:
        return None
    game.player_data["credits"] = credits - taken
    return f"{taken:.0f} credits have vanished from your account.", "your quarters"


# bombs.py adds "bomb", the Traitor's timed bomb.
ACTS = {
    "maul": _maul,
    "poison": _afflict("poison", "has been poisoned"),
    "burn": _afflict("burn", "was found badly burned"),
    "sabotage": _sabotage,
    "frame": _frame,
    "contaminate": _contaminate,
    "dim": _dim,
    "steal": _steal,
}


def _reveal(game, threat):
    """The threat attacks someone in the open. A crew threat leaves the crew: it is now hunted on its own."""
    crew = game.station_crew
    host = crew_named(crew, threat["crew_name"])
    if host is not None:
        crew.remove(host)
    threat["revealed"] = True
    threat["location"] = pick_random_hallway_location()
    where = donut.SHIP_MAP[donut.location_key(threat["location"])]["name"]
    victim = _pick_victim(game, threat)
    if victim is not None:
        _hurt_victim(victim)
        attacked = f"{victim['name']} was attacked in the {where}!"
    else:
        attacked = f"There has been an attack in the {where}!"
    unmasked = (f"{host['name']} ({host['job']}) is the {threat['type']}." if host
                else f"{capitalized(threat['name'])} is aboard.")
    message = f"{attacked} {unmasked} Security is hunting them."
    game.announce("Threat Revealed", message, kind="error")
    game.add_note(message)


def _host(game, threat):
    """The crew member a hidden threat is passing as, or None for an outsider or one that has shown itself."""
    return None if threat["revealed"] else crew_named(game.station_crew, threat["crew_name"])


def _crew_away(game, host):
    """The crew who are off their posts right now. A hidden threat's host has to be one of them to do anything,
    so a host who is at their post steps away from it first."""
    if host is not None and is_posted(host) and host["on_duty"]:
        send_for_a_walk(host)
    return [npc["name"] for npc in game.station_crew if can_work(npc) and not (is_posted(npc) and npc["on_duty"])]


def _count_toward_objective(threat, act, target_reachable, stolen):
    objective = threat["objective"]
    if act not in OBJECTIVES[objective["kind"]]["acts"]:
        return
    if objective["kind"] == "steal":
        objective["progress"] += stolen
    elif objective["kind"] != "hurt" or target_reachable:
        objective["progress"] += 1


def _act(game, threat):
    """One move: an attack in the open once it has made enough quiet ones, otherwise something from its list,
    which goes down as an incident and counts toward what the threat is out to do."""
    if not threat["revealed"] and threat["acts"] >= threat["reveal_after"]:
        _reveal(game, threat)
        return
    player_data = game.player_data
    act = random.choice(THREAT_TYPES[threat["type"]]["acts"])
    credits = player_data["credits"]
    target_reachable = crew_named(_victims(game, threat), threat["objective"]["target"]) is not None
    done = ACTS[act](game, threat)
    if not done:
        return
    message, where = done
    _count_toward_objective(threat, act, target_reachable, credits - player_data["credits"])
    player_data["incidents"].append({"at": get_elapsed_seconds(player_data), "where": where, "what": message,
                                     "away": _crew_away(game, _host(game, threat))})
    if threat["revealed"]:
        message = f"{capitalized(threat['name'])} strikes again. {message}"
    game.announce("Station Incident", message, kind="warning")
    game.add_note(message)


def _resolve(game, threat, fate):
    threat["fate"] = fate
    player_data = game.player_data
    if all(other["fate"] for other in player_data["threats"]):
        player_data["round"]["resolved_at"] = get_elapsed_seconds(player_data)


def tick_threats(game):
    """Let every threat whose time has come make its move, announce a change of alert level, and call the shuttle
    once the alert is Red."""
    player_data = game.player_data
    if round_over(player_data):
        return
    elapsed = get_elapsed_seconds(player_data)
    for threat in player_data["threats"]:
        host = _host(game, threat)
        if (threat["fate"] is None and elapsed >= threat["next_act_at"]
                and not _fighting_player(player_data, threat) and (host is None or can_work(host))):
            _act(game, threat)
            threat["acts"] += 1
            threat["next_act_at"] = elapsed + random.randint(*ACT_GAP_RANGE_SECONDS)
    level = alert_level(player_data)[0]
    if level != player_data["round"]["alert"]:
        player_data["round"]["alert"] = level
        game.announce("Station Alert", f"The station is now at {level} alert.", kind="warning")
    if level == "Red":
        call_for_red_alert(game)


def _crew_responds(game, threat):
    """Security or the Captain catches up with a revealed threat and wears it down, at a cost."""
    responders = [npc for npc in game.station_crew if npc["job"] in LAW_ABIDING_JOBS and can_work(npc)]
    if not responders or random.random() >= CREW_ENGAGE_CHANCE:
        return
    responder = random.choice(responders)
    threat["hp"] -= random.randint(*CREW_HIT_RANGE)
    change_limb(responder, random.choice(LIMBS), -random.randint(*CREW_HURT_RANGE))
    if threat["hp"] <= 0:
        outcome = "arrested" if threat["humanoid"] else "destroyed"
        _resolve(game, threat, f"{outcome} by {responder['name']}")
        message = f"{responder['name']} ({responder['job']}) has {outcome} {threat['name']}."
        game.announce("Security Report", message)
        game.add_note(message)


SHUTTLE_DOOR = donut.ROOMS[donut.DEPARTURES_KEY].hallway


def step_threats(game):
    """Move every revealed threat one hallway step, let the crew respond, and see if it has found the player. Once
    the shuttle has docked they make for its door."""
    for threat in loose_threats(game.player_data):
        if not threat["revealed"] or _fighting_player(game.player_data, threat):
            continue
        tile = (threat["location"]["x"], threat["location"]["y"])
        if game.player_data["round"]["shuttle"]["state"] == "docked":
            step = donut.step_toward(tile, SHUTTLE_DOOR)
        else:
            step = random.choice(list(donut.hallway_neighbors(*tile).values()))
        threat["location"] = donut.location_from_tile(step)
        _crew_responds(game, threat)
    check_threat_encounter(game)


def _fight(game, threat, intro):
    enemy = {key: threat[key] for key in ("name", "hp", "attack", "extra", "humanoid")}
    start_fight(game, "threat", enemy, intro, threat=game.player_data["threats"].index(threat))


def check_threat_encounter(game):
    """A revealed threat on the player's hallway tile attacks them."""
    player_data = game.player_data
    if player_data["fight"] or round_over(player_data) or game.current_room_name() is not None:
        return
    here = donut.location_key(player_data["location"])
    for threat in loose_threats(player_data):
        if threat["revealed"] and donut.location_key(threat["location"]) == here:
            _fight(game, threat, f"{capitalized(threat['name'])} is here, and comes straight at you!")
            return


def _won(game, fight, how):
    threat = game.player_data["threats"][fight["threat"]]
    if how == "cuffed":
        outcome = "handcuffed and arrested"
    else:
        outcome = "beaten and arrested" if threat["humanoid"] else "destroyed"
    _resolve(game, threat, f"{outcome} by you")
    message = f"You have {outcome} {threat['name']}."
    game.alert("Threat Dealt With", message)
    game.add_note(message)
    if game.player_data["round"]["shuttle"]["state"] == "transit":
        _next_aboard(game)


def _lost(game, fight):
    threat = game.player_data["threats"][fight["threat"]]
    kill_player(game, f"killed by {threat['name']}")
    threat["fate"] = "killed you"


def _made_the_shuttle(game, threat):
    """A threat in the open has to have reached the shuttle's door. A hidden one is aboard if its host is."""
    if threat["revealed"]:
        return (threat["location"]["x"], threat["location"]["y"]) == SHUTTLE_DOOR
    return bool(crew_aboard(filter(None, [_host(game, threat)])))


def hidden_hosts_aboard(game):
    """The crew aboard the shuttle who are secretly a loose threat, which turns on the crew once it leaves."""
    return [_host(game, threat) for threat in loose_threats(game.player_data)
            if not threat["revealed"] and _made_the_shuttle(game, threat)]


def _shuttle_leaves(game):
    """Every loose threat that didn't make the shuttle stays on the station. The rest are aboard."""
    for threat in loose_threats(game.player_data):
        if not _made_the_shuttle(game, threat):
            threat["fate"] = ("left behind on the station" if threat["revealed"]
                              else "left behind on the station without being found out")
    _next_aboard(game)


def _next_aboard(game):
    """The next threat aboard the shuttle makes its move. It goes for anyone aboard, the player or the crew. A
    crew member it goes for dies, and the rest of the crew hurt it for that. When it goes for the player, they
    fight it with whatever health it has left."""
    loose = loose_threats(game.player_data)
    if not loose:
        return
    threat = loose[0]
    crew = game.station_crew
    name = capitalized(threat["name"])
    if threat["revealed"]:
        intro = f"{name} has slipped aboard the shuttle, and comes straight at you!"
    else:
        crew.remove(_host(game, threat))
        threat["revealed"] = True
        threat["location"] = dict(game.player_data["location"])
        intro = f"As the shuttle pulls away, {threat['name']} turns on the crew. It was among you all along!"

    full_health = THREAT_TYPES[threat["type"]]["hp"]
    while True:
        aboard = crew_aboard(crew)
        victim = random.choice([None, *aboard])
        if victim is None:
            break
        fighting_back = sum(can_work(npc) for npc in aboard)
        crew.remove(victim)
        threat["hp"] -= round(full_health * min(SHUTTLE_CREW_HIT_MAX, SHUTTLE_CREW_HIT * fighting_back))
        message = f"{name} goes for {victim['name']} ({victim['job']}) aboard the shuttle and kills them."
        if threat["hp"] <= 0:
            _resolve(game, threat, "brought down by the crew aboard the shuttle")
            message += " The rest of the crew bring it down."
        game.alert("Crew Shuttle", message, kind="warning")
        game.add_note(message)
        if threat["fate"]:
            _next_aboard(game)
            return
        intro = f"{name} turns from {victim['name']} to you, hurt from the fight!"
    _fight(game, threat, intro)


def _host_jailed(game, member):
    """Jailing the crew member a hidden threat is passing as ends that threat before it strikes."""
    threat = next((threat for threat in game.player_data["threats"]
                   if threat["crew_name"] == member["name"] and not threat["revealed"] and threat["fate"] is None),
                  None)
    if threat is None:
        return
    member["held"] = True
    _resolve(game, threat, "found out and jailed before it could strike")
    message = (f"{member['name']} ({member['job']}) was the {threat['type']} all along. "
               "They are being held for Central Command.")
    game.announce("Threat Caught", message)
    game.add_note(message)


@register_panel("incident_log", "Incident Log")
def incident_log_panel(game, state):
    return {"incidents": [{"time": f"T+{int(incident['at'] // 60)}m", "where": incident["where"],
                           "what": incident["what"],
                           "away": None if incident["away"] is None else ", ".join(incident["away"]) or "nobody"}
                          for incident in reversed(game.player_data["incidents"])]}


register_fight("threat", _won, _lost)
ARREST_HOOKS.append(_host_jailed)
DEPARTURE_HOOKS.append(_shuttle_leaves)
