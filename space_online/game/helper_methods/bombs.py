"""Tank transfer valve bombs: two Gas Tanks joined by a valve. Opening the valve pours the two tanks' gas together.
Hot fuel meeting an oxidizer burns, and the blast is graded by how far past the tanks' rated pressure the burn takes
the gas. The same gas rules as every other container decide it.

A Transfer Valve Bomb's attributes hold:
    contents     the two tanks' mixtures
    goes_off_at  game seconds at which its timer runs out, or None while it isn't armed
    armed_by     the name of whoever armed it, or None

player_data["atmos"] holds, besides what atmos.py and station_air.py keep there:
    valve_taken  whether the tank rack's free Tank Transfer Valve has gone this shift
    range_paid   the blast sizes Central Command has paid the test range bounty for this shift
"""

import copy
import random
import uuid

from space_online.game.helper_methods import gas_mix
from space_online.game.helper_methods.antagonists import ACTS, THREAT_TYPES, _resolve, loose_threats
from space_online.game.helper_methods.errands import finish_duty, open_duties
from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.hazards import HAZARD_ROOM_KEYS, start_hazard
from space_online.game.helper_methods.health_bands import LIMBS, change_limb, limb_label
from space_online.game.helper_methods.jail import set_warrant
from space_online.game.helper_methods.rounds import kill_player
from space_online.game.helper_methods.ui_panels import (
    choice_handler,
    current_feedback,
    panel_action,
    register_panel,
    set_feedback,
)
from space_online.game.maps import donut
from space_online.game.objects.gases import GAS_TANK, ROOM_TEMP
from space_online.game.objects.items import (
    BOMB_ID,
    GAS_TANK_ID,
    TRANSFER_VALVE_ID,
    _item_at,
    add_to_inventory,
    format_inventory_label,
    get_item_definition,
    inventory_index,
    item_action,
    remove_one_from_inventory,
    stack_into,
)

BOMB_VOLUME = 2 * GAS_TANK["volume"]
# (size, times the tanks' rated pressure the gas reaches), biggest first. Two tanks at their rating that only mix,
# without burning, can read a little over 1x, so the smallest blast starts well clear of it.
BLAST_SIZES = (("Large", 8), ("Medium", 4), ("Small", 1.5), ("Dud", 0))
TIMER_SECONDS = (10, 30, 60)
# A Dud whose gas is at least this hot scalds whoever is holding it.
DUD_HOT_TEMP = 360
# (burn %, limb %) a blast does to the player and to the crew caught in it. One random limb takes the limb damage.
PLAYER_HARM = {"Dud": (5, 0), "Small": (15, 20), "Medium": (40, 50), "Large": (60, 80)}
CREW_HARM = {"Small": (0, 20), "Medium": (40, 50)}
# The share of its full health a revealed antagonist caught in a blast loses.
THREAT_HIT = {"Small": 0.25, "Medium": 0.5, "Large": 1.0}
RANGE_BOUNTY = {"Small": 100, "Medium": 200, "Large": 400}
MAX_RANGE_LOG = 5
CRIME = "Unauthorized detonation"
# The Traitor's bomb: hot Plasma and Oxygen, each tank at this share of its rating, which makes a Medium blast.
PLANTED_TIMER = 60
PLANTED_FILL = 0.5
PLANTED_FUEL_TEMP = 500


def new_bomb(mixes):
    """A Transfer Valve Bomb holding the two mixtures, with a uid to find it by."""
    bomb = get_item_definition(BOMB_ID)
    bomb["uid"] = uuid.uuid4().hex
    bomb["attributes"]["contents"] = mixes
    return bomb


def planted_bomb(game, armed_by):
    """The Traitor's bomb, armed with PLANTED_TIMER seconds on it."""
    kpa = PLANTED_FILL * GAS_TANK["rated"]
    bomb = new_bomb([
        gas_mix.mix_of({"Plasma": 1}, gas_mix.moles_at(kpa, GAS_TANK["volume"], PLANTED_FUEL_TEMP), PLANTED_FUEL_TEMP),
        gas_mix.mix_of({"Oxygen": 1}, gas_mix.moles_at(kpa, GAS_TANK["volume"], ROOM_TEMP), ROOM_TEMP),
    ])
    _arm(game, bomb, PLANTED_TIMER, armed_by)
    return bomb


def _arm(game, bomb, seconds, armed_by):
    bomb["attributes"].update(goes_off_at=get_elapsed_seconds(game.player_data) + seconds, armed_by=armed_by)


def _parts(bomb, keep_gas):
    """The valve and the two Gas Tanks a bomb is made of, the tanks emptied unless keep_gas."""
    tanks = []
    for mix in bomb["attributes"]["contents"]:
        tank = get_item_definition(GAS_TANK_ID)
        tank["attributes"]["contents"] = mix if keep_gas else gas_mix.empty_mix()
        tanks.append(tank)
    return [get_item_definition(TRANSFER_VALVE_ID), *tanks]


def blast_of(bomb):
    """What opening the valve would do, without doing it: {"size", "temp", "pressure", "mix"} once the merged gas
    has burned out."""
    mix = gas_mix.empty_mix()
    for side in bomb["attributes"]["contents"]:
        gas_mix.merge(mix, copy.deepcopy(side))
    gas_mix.burn_out(mix)
    over = gas_mix.rupture(mix, BOMB_VOLUME, GAS_TANK["rated"])
    size = next(name for name, times in BLAST_SIZES if over >= times)
    return {"size": size, "temp": mix["temp"], "pressure": gas_mix.pressure(mix, BOMB_VOLUME), "mix": mix}


def _threat_loose(player_data):
    return any(threat["revealed"] for threat in loose_threats(player_data))


def _hurt(member, size, harm):
    """Burn a member and hurt one random limb by harm[size]. Returns (burn total, limb, limb total)."""
    burn, limb_damage = harm[size]
    member["damage"]["burn"] = min(100, member["damage"]["burn"] + burn)
    limb = random.choice(LIMBS)
    _, total = change_limb(member, limb, -limb_damage)
    return member["damage"]["burn"], limb, total


def _hit_player(game, size, temp):
    if size == "Dud" and temp < DUD_HOT_TEMP:
        return
    if size == "Large" and kill_player(game, "killed by a transfer valve bomb"):
        return
    burn, limb, total = _hurt(game.player_data, size, PLAYER_HARM)
    message = f"The blast burns you. Burn damage: {burn}%."
    if PLAYER_HARM[size][1]:
        message += f" It catches your {limb_label(limb).lower()}, which is at {total}%."
    game.alert("Explosion", message, kind="error")


def _crew_dies(game, npc):
    """Remove a crew member killed in a blast. One who was secretly a threat takes it with them."""
    game.station_crew.remove(npc)
    message = f"{npc['name']} ({npc['job']}) was killed in the blast."
    game.announce("Explosion", message, kind="error")
    game.add_note(message)
    for threat in game.player_data["threats"]:
        if threat["crew_name"] == npc["name"] and not threat["revealed"] and threat["fate"] is None:
            _resolve(game, threat, "killed by a bomb before it was found out")


def _hit_crew(game, size, where):
    for npc in [npc for npc in game.station_crew if donut.location_key(npc["location"]) == where]:
        if size == "Large":
            _crew_dies(game, npc)
        else:
            _hurt(npc, size, CREW_HARM)


def _hit_threats(game, size, where):
    for threat in loose_threats(game.player_data):
        if not threat["revealed"] or donut.location_key(threat["location"]) != where:
            continue
        threat["hp"] -= round(THREAT_HIT[size] * THREAT_TYPES[threat["type"]]["hp"])
        if threat["hp"] > 0:
            message = f"The blast catches {threat['name']}, which is hurt but still loose."
        else:
            _resolve(game, threat, "destroyed by a bomb")
            message = f"The blast destroys {threat['name']}."
        game.announce("Explosion", message, kind="warning")
        game.add_note(message)


def detonate(game, bomb, where):
    """Open a bomb's valve at a map key. A Dud vents its gas into the station's air and leaves its valve and empty
    tanks on the floor. A real blast sets a fire in a room (a hull breach when Large) and hits everyone there. A bomb
    the player armed that goes off while no revealed threat is loose puts a warrant out for them."""
    player_data = game.player_data
    blast = blast_of(bomb)
    size = blast["size"]
    by_player = bomb["attributes"]["armed_by"] == player_data["name"]
    place = game.ship_map[where]["name"]
    if size == "Dud":
        gas_mix.merge(player_data["atmos"]["air"], blast["mix"])
        for part in _parts(bomb, keep_gas=False):
            stack_into(player_data["floor"].setdefault(where, []), part)
        message = (f"A transfer valve bomb fizzles in the {place}: a Dud at {blast['temp']:.0f} K and "
                   f"{blast['pressure']:.0f} kPa. Its gas hisses out into the station's air.")
    else:
        message = (f"A transfer valve bomb goes off in the {place}: a {size} blast at {blast['temp']:.0f} K and "
                   f"{blast['pressure']:.0f} kPa.")
    if by_player and _threat_loose(player_data):
        message += " With a threat loose on the station, Security lets it pass."
    elif by_player:
        set_warrant(player_data, CRIME)
        message += " No threat is loose on the station, so it was unauthorized: there is a warrant out for you."
    game.alert("Explosion", message, kind="error" if size != "Dud" else "warning")
    game.add_note(message)
    if size != "Dud":
        if where in HAZARD_ROOM_KEYS:
            start_hazard(game, where, "breach" if size == "Large" else "fire")
        _hit_crew(game, size, where)
        _hit_threats(game, size, where)
    if donut.location_key(player_data["location"]) == where and not player_data["mining"]["expedition"]:
        _hit_player(game, size, blast["temp"])


def _due(item, elapsed):
    if item.get("id") != BOMB_ID:
        return False
    goes_off_at = item["attributes"]["goes_off_at"]
    return goes_off_at is not None and elapsed >= goes_off_at


def tick_bombs(game):
    """Set off every armed bomb whose time is up: on the floor where it lies, and in the inventory where the player
    stands."""
    player_data = game.player_data
    elapsed = get_elapsed_seconds(player_data)
    places = [(player_data["inventory"], donut.location_key(player_data["location"])),
              *((items, key) for key, items in list(player_data["floor"].items()))]
    for items, where in places:
        for bomb in [item for item in items if _due(item, elapsed)]:
            items.remove(bomb)
            detonate(game, bomb, where)


def floor_label(player_data, item):
    """An item's label where it lies on the floor, with the seconds left on an armed bomb."""
    label = format_inventory_label(item)
    if item.get("id") == BOMB_ID and item["attributes"]["goes_off_at"] is not None:
        left = max(0, round(item["attributes"]["goes_off_at"] - get_elapsed_seconds(player_data)))
        label += f" (ticking: {left} s)"
    return label


def _carried_bomb(game, uid):
    return next((item for item in game.player_data["inventory"] if item.get("uid") == uid), None)


@item_action("open_transfer_valve")
def _ask_open(game, state, item):
    game.close_panel("item_actions")
    game.ask("Open the Valve", "Open the transfer valve with the bomb in your hands? Its gases mix at once.",
             [("Open It", "open_bomb_valve", {"uid": item["uid"]}), ("Leave It", None, None)])


@choice_handler("open_bomb_valve")
def open_bomb_valve(game, uid):
    bomb = _carried_bomb(game, uid)
    if bomb is None:
        return
    game.player_data["inventory"].remove(bomb)
    bomb["attributes"]["armed_by"] = game.player_data["name"]
    game.add_note("Opened a transfer valve bomb's valve.")
    detonate(game, bomb, donut.location_key(game.player_data["location"]))


@item_action("set_timer")
def _ask_timer(game, state, item):
    game.close_panel("item_actions")
    game.ask("Set Timer", "How long until the valve opens? Drop the bomb and walk away before then.",
             [*((f"{seconds} seconds", "set_bomb_timer", {"uid": item["uid"], "seconds": seconds})
                for seconds in TIMER_SECONDS), ("Cancel", None, None)])


@choice_handler("set_bomb_timer")
def set_bomb_timer(game, uid, seconds):
    bomb = _carried_bomb(game, uid)
    if bomb is None or seconds not in TIMER_SECONDS:
        return
    _arm(game, bomb, seconds, game.player_data["name"])
    message = f"You set the bomb's timer. The valve opens in {seconds} seconds."
    game.add_note(message)
    game.alert("Transfer Valve Bomb", message, kind="warning")


@item_action("disarm")
def _disarm(game, state, item):
    item["attributes"].update(goes_off_at=None, armed_by=None)
    game.close_panel("item_actions")
    game.add_note("Disarmed a transfer valve bomb.")
    game.alert("Transfer Valve Bomb", "You stop the timer. The bomb is safe until someone arms it again.")


def _plant_bomb(game, threat):
    """The Traitor leaves a timed bomb on the floor of a random room."""
    room_key = random.choice(HAZARD_ROOM_KEYS)
    stack_into(game.player_data["floor"].setdefault(room_key, []), planted_bomb(game, threat["name"]))
    name = donut.ROOMS[room_key].name
    return f"A device has been found ticking in the {name}.", name


ACTS["bomb"] = _plant_bomb


# --- The transfer valve panel ---------------------------------------------------------------------------------------

def _inventory_rows(game, item_id):
    return [(index, item) for index, item in enumerate(game.player_data["inventory"]) if item.get("id") == item_id]


def _tank_label(tank):
    """A Gas Tank's pressure only, as examining it reads."""
    return f"Gas Tank: {gas_mix.pressure(tank['attributes']['contents'], GAS_TANK['volume']):.1f} kPa"


def _picked(game, state):
    """The carried Gas Tanks picked for the valve, by inventory index."""
    return [index for index in state.get("picked", []) if _item_at(game, index, GAS_TANK_ID)]


@register_panel("transfer_valve", "Tank Transfer Valve")
def transfer_valve_panel(game, state):
    valve = inventory_index(game.player_data, TRANSFER_VALVE_ID)
    bombs = _inventory_rows(game, BOMB_ID)
    if valve is None and not bombs:
        return None
    picked = _picked(game, state)
    return {
        "tanks": [{"index": index, "label": _tank_label(tank)} for index, tank in _inventory_rows(game, GAS_TANK_ID)],
        "picked": picked,
        "has_valve": valve is not None,
        "can_assemble": valve is not None and len(picked) == 2,
        "bombs": [{"index": index, "label": format_inventory_label(bomb),
                   "armed": bomb["attributes"]["goes_off_at"] is not None} for index, bomb in bombs],
        "feedback": current_feedback(state),
    }


@panel_action("transfer_valve")
def pick_tank(game, state, args):
    """Pick a tank for one of the valve's two sides, or put a picked one back. A third pick replaces the first."""
    index = int(args["index"])
    picked = _picked(game, state)
    if index in picked:
        picked.remove(index)
    elif _item_at(game, index, GAS_TANK_ID):
        picked = (picked + [index])[-2:]
    state["picked"] = picked


@panel_action("transfer_valve")
def assemble(game, state, args):
    player_data = game.player_data
    valve = inventory_index(player_data, TRANSFER_VALVE_ID)
    picked = _picked(game, state)
    if valve is None or len(picked) != 2:
        set_feedback(state, "Pick two Gas Tanks you carry, and carry a Tank Transfer Valve.", "orange")
        return
    mixes = [player_data["inventory"][index]["attributes"]["contents"] for index in picked]
    for index in sorted([valve, *picked], reverse=True):
        remove_one_from_inventory(player_data, index)
    add_to_inventory(player_data, new_bomb(mixes))
    state["picked"] = []
    game.add_note("Assembled a transfer valve bomb.")
    set_feedback(state, "You fit both tanks to the valve. The Transfer Valve Bomb is in your inventory.")


@panel_action("transfer_valve")
def take_apart(game, state, args):
    bomb = _item_at(game, int(args["index"]), BOMB_ID)
    if bomb is None or bomb["attributes"]["goes_off_at"] is not None:
        set_feedback(state, "Disarm the bomb before you take it apart.", "orange")
        return
    game.player_data["inventory"].remove(bomb)
    for part in _parts(bomb, keep_gas=True):
        add_to_inventory(game.player_data, part)
    state["picked"] = []
    game.add_note("Took a transfer valve bomb apart.")
    set_feedback(state, "You take the tanks off the valve.")


# --- The test range -------------------------------------------------------------------------------------------------

@register_panel("bomb_range", "Test Range")
def bomb_range_panel(game, state):
    selected = _item_at(game, state.get("selected"), BOMB_ID)
    paid = game.player_data["atmos"]["range_paid"]
    return {
        "bombs": [{"index": index, "label": format_inventory_label(bomb)}
                  for index, bomb in _inventory_rows(game, BOMB_ID)],
        "selected": state.get("selected") if selected else None,
        "bounties": [{"size": size, "credits": credits, "paid": size in paid} for size, credits in RANGE_BOUNTY.items()],
        "log": state.get("log", []),
        "feedback": current_feedback(state),
    }


@panel_action("bomb_range")
def select_bomb(game, state, args):
    state["selected"] = int(args["index"])


def _pay_bounty(game, size):
    """Central Command's bounty for the first test of each blast size in a shift. Returns the line for the log."""
    paid = game.player_data["atmos"]["range_paid"]
    if size not in RANGE_BOUNTY or size in paid:
        return ""
    paid.append(size)
    game.player_data["credits"] += RANGE_BOUNTY[size]
    return f" Central Command pays its {RANGE_BOUNTY[size]} credit bounty for a first {size} blast."


@panel_action("bomb_range")
def run_test(game, state, args):
    """Set the picked bomb off on the range, where it harms nothing: it is used up, and its valve and empty tanks
    come back."""
    player_data = game.player_data
    bomb = _item_at(game, state.get("selected"), BOMB_ID)
    if bomb is None:
        set_feedback(state, "Pick a Transfer Valve Bomb you carry first.", "orange")
        return
    player_data["inventory"].remove(bomb)
    state.pop("selected")
    for part in _parts(bomb, keep_gas=False):
        add_to_inventory(player_data, part)
    blast = blast_of(bomb)
    size = blast["size"]
    line = (f"{size}: peaked at {blast['temp']:.0f} K and {blast['pressure']:.0f} kPa, "
            f"{blast['pressure'] / GAS_TANK['rated']:.1f}x the tanks' rating.")
    line += _pay_bounty(game, size)
    state["log"] = ([line] + state.get("log", []))[:MAX_RANGE_LOG]
    game.add_note(f"Ran a bomb on the test range: {line}")
    duty = next((duty for duty in open_duties(player_data, ("bomb_test",)) if duty["size"] == size), None)
    if duty is not None:
        message = f"Central Command has its {size} test and pays you {duty['reward']} credits."
        finish_duty(game, duty, f"Tested a {size} bomb on the range.", message, duty["reward"])
