"""The random events of walking the hallways, the events each job brings its holder on the clock, and what they do."""

import random

from space_online.game.character_methods.character_creation import REQUESTABLE_JOBS
from space_online.game.helper_methods.artifacts import artifact_of, new_artifact
from space_online.game.helper_methods.bombs import RANGE_BOUNTY
from space_online.game.helper_methods.errands import (
    DUTY_EXPIRY_SECONDS,
    add_duty,
    duties_full,
    open_duties,
    with_article,
)
from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.health_bands import DAMAGE_TYPES, LIMBS, change_limb, limb_label, reduce_damage
from space_online.game.helper_methods.jail import (
    LAW_ABIDING_JOBS,
    PETTY_CRIMES,
    arrest_member,
    set_warrant,
    warrant_reason_text,
    warrants_enforced,
)
from space_online.game.helper_methods.npc_movement import JOB_POSTS, can_work, post_holder
from space_online.game.helper_methods.power_constants import FAULTABLE_SYSTEMS, fault_system, system_name, system_online
from space_online.game.helper_methods.rounds import JOB_EVENT_INTERVAL_RANGE, secured
from space_online.game.helper_methods.shuttle_talk import seated_crew
from space_online.game.helper_methods.stock_market import generate_market_tip
from space_online.game.helper_methods.ui_panels import choice_handler
from space_online.game.helper_methods.window_stock import other_side
from space_online.game.maps.donut import (
    ATMOSPHERICS_KEY,
    BAR_KEY,
    BOTANY_KEY,
    CHEMISTRY_KEY,
    ENGINEERING_KEY,
    KITCHEN_KEY,
    MEDBAY_KEY,
    RESEARCH_KEY,
    ROOMS,
    SECURITY_KEY,
)
from space_online.game.objects.botany_items import refresh_all_planters_growth, seconds_to_mature
from space_online.game.objects.chemicals import STORE_REMEDY_IDS
from space_online.game.objects.drinks import drink_id
from space_online.game.objects.food import PRODUCE
from space_online.game.objects.items import (
    ALL_ITEMS,
    GAS_TANK_ID,
    add_to_inventory,
    carried_or_held,
    get_item_definition,
    held_items,
    inventory_index,
    item_with_article,
    remove_one_from_inventory,
    stack_into,
)
from space_online.game.special_rooms.bar import BAR_COUNTER
from space_online.game.special_rooms.bridge import LOCKDOWN_DOOR_KEYS
from space_online.game.special_rooms.kitchen import KITCHEN_COUNTER
from space_online.game.special_rooms.research import ANALYSIS_REWARD, MAX_BENCH
from space_online.game.special_rooms.service_window import SIDES, window_partner

HALLWAY_EVENT_CHANCE = 0.20
CROP_REQUEST_MIN_REWARD = 50
CROP_REQUEST_MAX_REWARD = 150
ERRAND_MIN_REWARD = 25
ERRAND_MAX_REWARD = 75
ITEM_REQUEST_MIN_REWARD = 60
ITEM_REQUEST_MAX_REWARD = 160
WINDOW_REQUEST_CHANCE = 0.3
WINDOW_REQUEST_MAX = 3
PATIENT_MIN_DAMAGE = 15
PATIENT_MAX_DAMAGE = 35
# No second solar trip within this long of the last one.
SOLAR_TRIP_COOLDOWN_SECONDS = 6 * 60

# (giver job, room key, item id) a crew member may ask the Scientist in Chemistry or the Miner for.
COMPOUND_REQUESTS = (
    ("Doctor", MEDBAY_KEY, "burn_salve"),
    ("Doctor", MEDBAY_KEY, "antitoxin"),
    ("Doctor", MEDBAY_KEY, "healing_gel"),
    ("Doctor", MEDBAY_KEY, "oxygen_tonic"),
    ("Bartender", BAR_KEY, "sober_up"),
    ("Botanist", BOTANY_KEY, "miracle_grow"),
)
SUPPLY_REQUESTS = (
    ("Doctor", MEDBAY_KEY, "medkit"),
    ("Engineer", ENGINEERING_KEY, "fire_extinguisher"),
    ("Engineer", ENGINEERING_KEY, "repair_tool"),
    ("Botanist", BOTANY_KEY, "watering_can"),
    ("Chef", KITCHEN_KEY, "emergency_rations"),
    ("Bartender", BAR_KEY, "snack"),
)
ORE_REQUESTS = (
    ("Engineer", ENGINEERING_KEY, "iron_ore"),
    ("Engineer", ENGINEERING_KEY, "copper_ore"),
    ("Scientist", CHEMISTRY_KEY, "iron_ore"),
    ("Doctor", MEDBAY_KEY, "quartz"),
)
GAS_REQUESTS = (
    ("Doctor", MEDBAY_KEY, GAS_TANK_ID, "Oxygen"),
    ("Engineer", ENGINEERING_KEY, GAS_TANK_ID, "Nitrogen"),
    ("Botanist", BOTANY_KEY, GAS_TANK_ID, "Carbon Dioxide"),
)
EVENT_CATEGORIES = ("good", "neutral", "bad")

# What each bad hallway event does, in the order it happens: "credits" (low, high) lost, "limb" (limb, low, high)
# with None for a random limb, and "burn" or "poison" (low, high) damage.
HALLWAY_ACCIDENTS = {
    "Lost Credits": {"credits": (10, 50), "limb": ("head", 5, 10)},
    "Small Explosion": {"limb": (None, 10, 25), "burn": (5, 15)},
    "Slip and Fall": {"limb": (None, 10, 20)},
    "Steam Leak": {"limb": ("left_arm", 5, 10), "burn": (15, 30)},
    "Falling Debris": {"limb": ("head", 15, 35)},
    "Maintenance Accident": {"limb": ("right_leg", 10, 20)},
    "Chemical Spill": {"limb": ("left_leg", 5, 10), "burn": (5, 15), "poison": (10, 20)},
}

# A deliver duty with no item brings a random piece of produce.
STAFF_ASSISTANT_ERRANDS = (
    {"request": "The Botanist needs water for the planters.",
     "giver": "Botanist", "room": BOTANY_KEY, "kind": "help", "label": "water the planters"},
    {"request": "The Engineer needs a hand in Engineering.",
     "giver": "Engineer", "room": ENGINEERING_KEY, "kind": "help", "label": "sort spare parts"},
    {"request": "The Bartender needs an ingredient for a drink.",
     "giver": "Bartender", "room": BAR_KEY, "kind": "deliver"},
    {"request": "The Doctor needs someone to restock bandages.",
     "giver": "Doctor", "room": MEDBAY_KEY, "kind": "deliver", "item": "medkit"},
    {"request": "Security needs help filing paperwork.",
     "giver": "Security Guard", "room": SECURITY_KEY, "kind": "help", "label": "file paperwork"},
)

# {suspect} is filled with a crew member's name, and {room} with the room a lockdown would lock.
CAPTAIN_REQUESTS = {
    "life_support": "Engineering needs approval to divert power to life support.",
    "lockdown": "Security requests permission to lock down the {room}.",
    "power_saving": "Engineering requests permission to switch the station to Power Saving mode.",
    "warrant": "Security requests a warrant for {suspect} on suspicion of smuggling.",
}


def maybe_trigger_hallway_event(game):
    """Roll for a hallway event and trigger one on success."""
    if random.random() < HALLWAY_EVENT_CHANCE:
        trigger_random_event(game)


def _static_events(game):
    """The good, neutral and bad hallway events."""
    return [
        {
            "type": "good",
            "title": "Found Credits",
            "desc": "You found some credits on the floor!",
            "effect": lambda: add_credits(game, random.randint(50, 200)),
        },
        {
            "type": "good",
            "title": "Supply Crate",
            "desc": "You found an unsealed supply crate with useful items.",
            "effect": lambda: leave_random_item(game),
        },
        {
            "type": "good",
            "title": "Market Tip",
            "desc": "You overheard a market tip.",
            "effect": lambda: add_market_knowledge(game),
        },
        {
            "type": "neutral",
            "title": "Lost Tourist",
            "desc": (
                "A confused visitor asks for directions to the bar, "
                "then wanders off the wrong way."
            ),
            "effect": lambda: None,
        },
        {
            "type": "neutral",
            "title": "Recycled Air Whiff",
            "desc": (
                "The vents kick on with a blast of recycled air that smells "
                "faintly of coolant and coffee."
            ),
            "effect": lambda: None,
        },
        {
            "type": "neutral",
            "title": "Graffiti Tag",
            "desc": (
                "Someone has scratched a crude smiley into the wall paneling. "
                "Maintenance will be thrilled."
            ),
            "effect": lambda: None,
        },
        {
            "type": "neutral",
            "title": "Announcement",
            "desc": "The station PA system makes an announcement.",
            "effect": lambda: station_announcement(game),
        },
        {
            "type": "neutral",
            "title": "Bot Moves By",
            "desc": "A station bot rolls past you in the hallway.",
            "effect": lambda: bot_moves_by(game),
        },
        {
            "type": "neutral",
            "title": "Vending Machine Malfunction",
            "desc": "A nearby vending machine sputters and flashes error lights.",
            "effect": lambda: vending_machine_malfunction(game),
        },
        {
            "type": "bad",
            "title": "Lost Credits",
            "desc": (
                "You dropped some credits and couldn't find them all. "
                "You bumped your head looking for them."
            ),
            "effect": lambda: hallway_accident(game, "Lost Credits"),
        },
        {
            "type": "bad",
            "title": "Small Explosion",
            "desc": "A nearby conduit explodes, showering you with hot sparks and debris!",
            "effect": lambda: hallway_accident(game, "Small Explosion"),
        },
        {
            "type": "bad",
            "title": "Slip and Fall",
            "desc": "You slipped on a wet floor and fell hard.",
            "effect": lambda: hallway_accident(game, "Slip and Fall"),
        },
        {
            "type": "bad",
            "title": "Steam Leak",
            "desc": "A pipe bursts, releasing scalding steam that burns your arm!",
            "effect": lambda: hallway_accident(game, "Steam Leak"),
        },
        {
            "type": "bad",
            "title": "Falling Debris",
            "desc": "A ceiling panel breaks loose and hits your head!",
            "effect": lambda: hallway_accident(game, "Falling Debris"),
        },
        {
            "type": "bad",
            "title": "Maintenance Accident",
            "desc": "Your leg gets caught in an open floor grate!",
            "effect": lambda: hallway_accident(game, "Maintenance Accident"),
        },
        {
            "type": "bad",
            "title": "Chemical Spill",
            "desc": "You walk through a chemical spill! Your leg is burned and you feel ill.",
            "effect": lambda: hallway_accident(game, "Chemical Spill"),
        },
    ]


def _job_event(title, desc, effect):
    return {"type": "job", "title": title, "desc": desc, "effect": effect}


def _room_errand(giver, room, kind, label, reward, item=None):
    """The fields of a deliver or help duty, with its summary."""
    room_name = ROOMS[room].name
    if kind == "deliver":
        summary = f"Bring {label} to the {giver} in the {room_name} ({reward} cr)"
    else:
        summary = f"Help the {giver} {label} in the {room_name} ({reward} cr)"
    return {"kind": kind, "giver": giver, "room": room, "item": item, "label": label, "reward": reward,
            "summary": summary}


def _random_produce():
    """(item_id, 'a tomato') for a random piece of food produce."""
    produce_id = random.choice(list(PRODUCE))
    return produce_id, with_article(PRODUCE[produce_id]["name"].lower())


def _available_crew(game):
    return [npc for npc in game.station_crew if can_work(npc)]


def _hop_event(game):
    if game.player_data.get("access_request"):
        return None
    candidates = [npc for npc in _available_crew(game) if npc.get("job") != "Captain"]
    if not candidates:
        return None
    npc = random.choice(candidates)
    requested_job = random.choice([job for job in REQUESTABLE_JOBS if job != npc["job"]])
    requester = npc.get("name", "A crew member")
    desc = (
        f"{requester} ({npc.get('job', 'Crew')}) has submitted an access request "
        f"to become {requested_job}. Review it at the HoP Access Control console."
    )

    def effect():
        game.player_data["access_request"] = {
            "requested_job": requested_job,
            "requester_name": requester,
            "decide_at": None,
        }
        game.add_note(
            f"Access request: {requester} requested assignment as {requested_job}."
        )

    return _job_event("Access Request", desc, effect)


def _can_bring(player_data, item_id):
    """Whether the player carries item_id or has one in their Quarters locker."""
    return (carried_or_held(player_data, (item_id,)) is not None
            or any(item.get("id") == item_id for item in player_data["locker_inventory"]))


def _staff_assistant_event(game):
    player_data = game.player_data
    offered = [errand for errand in STAFF_ASSISTANT_ERRANDS if post_holder(game.station_crew, errand["giver"])
               and ("item" not in errand or _can_bring(player_data, errand["item"]))]
    if not offered:
        return None
    request = random.choice(offered)
    reward = random.randint(ERRAND_MIN_REWARD, ERRAND_MAX_REWARD)
    room_name = ROOMS[request["room"]].name
    if request["kind"] == "deliver":
        item = request.get("item")
        if item:
            label = item_with_article(get_item_definition(item))
        else:
            item, label = _random_produce()
        errand = _room_errand(request["giver"], request["room"], "deliver", label, reward, item)
        desc = f"{request['request']} Bring {label} to the {room_name} for {reward} credits."
    else:
        errand = _room_errand(request["giver"], request["room"], "help", request["label"], reward)
        desc = f"{request['request']} Report to the {room_name} for {reward} credits."

    def effect():
        add_duty(game.player_data, **errand)
        game.add_note(desc)

    return _job_event("Job Request", desc, effect)


def _engineer_event(game):
    power = game.player_data["station_power"]
    working = [key for key in FAULTABLE_SYSTEMS if key not in power["faults"] and power["system_levels"][key] > 0]
    elapsed = get_elapsed_seconds(game.player_data)
    tripped_at = power["solar_tripped_at"]
    solar = power["solar_charging"] and (tripped_at is None or elapsed - tripped_at >= SOLAR_TRIP_COOLDOWN_SECONDS)
    troubles = (["solar"] if solar else []) + (["fault"] if working else [])
    if not troubles:
        return None
    trouble = random.choice(troubles)
    if trouble == "solar":
        desc = (
            "The solar panels have shut down unexpectedly. "
            "They must be restarted from the Engineering Panel."
        )

        def effect():
            power.update(solar_charging=False, solar_tripped_at=elapsed)
            game.add_note("Solar arrays went offline and need to be restarted.")

        return _job_event("Solar Panels Offline", desc, effect)

    system_key = random.choice(working)
    name = system_name(system_key)
    desc = (
        f"A fault has shut down the {name}. Repair it from the Engineering Panel "
        "with Basic Tools or a Repair Tool."
    )

    def effect():
        fault_system(power, system_key)
        game.add_note(f"The {name} faulted and needs repairing.")

    return _job_event("System Fault", desc, effect)


def _produce_on_hand(player_data):
    """{produce id: seconds until the player can have it} for the produce they carry or are growing."""
    elapsed = get_elapsed_seconds(player_data)
    waits = {}
    for planter in refresh_all_planters_growth(player_data, elapsed):
        if planter["occupied"] and not planter["dead"] and not planter["tended_by"] and planter["produces"] in PRODUCE:
            wait = seconds_to_mature(planter, elapsed)
            waits[planter["produces"]] = min(wait, waits.get(planter["produces"], wait))
    for item in player_data["inventory"] + held_items(player_data):
        if item.get("id") in PRODUCE:
            waits[item["id"]] = 0
    return waits


def _botanist_event(game):
    """The Bartender asks for produce the player has or is growing, with time to grow it."""
    waits = _produce_on_hand(game.player_data)
    if post_holder(game.station_crew, "Bartender") is None or not waits:
        return None
    produce_id = random.choice(sorted(waits))
    label = with_article(PRODUCE[produce_id]["name"].lower())
    reward = random.randint(CROP_REQUEST_MIN_REWARD, CROP_REQUEST_MAX_REWARD)
    desc = f"The Bartender needs {label} from the botany lab. Deliver it to the Bar for {reward} credits."

    def effect():
        add_duty(game.player_data, lasts=waits[produce_id] + DUTY_EXPIRY_SECONDS,
                 **_room_errand("Bartender", BAR_KEY, "deliver", label, reward, produce_id))
        game.add_note(f"Bartender requested {label} from botany for {reward} credits.")

    return _job_event("Crop Request", desc, effect)


def _window_request_event(game, side):
    """The crew member on the other side of the service window asks the player's side for an ingredient.

    It is a favour, not a duty: nothing is paid and it never runs out.
    """
    asking = other_side(side)
    job = SIDES[asking].job
    requests = game.player_data["service_window"]["requests"][asking]
    if requests or window_partner(game, side) is None:
        return None
    ingredient = random.choice(SIDES[asking].wants)
    amount = random.randint(1, WINDOW_REQUEST_MAX)
    desc = (f"The {job} asks for {amount} {ingredient} at the service window. "
            f"Put it on the window from the {SIDES[side].job} Station when you can.")

    def effect():
        requests[ingredient] = amount
        game.add_note(f"The {job} asked for {amount} {ingredient} at the service window.")

    return _job_event("Window Request", desc, effect)


def _order_event(game, counter, title):
    """A crew member orders something made at counter, served from its stock for the menu price."""
    patrons = _available_crew(game)
    if not patrons:
        return None
    patron = random.choice(patrons)["name"]
    item = random.choice(list(counter.made))
    price = counter.made[item]["price"]
    desc = (f"{patron} orders {with_article(item)}. {counter.make_verb} one and serve it from the "
            f"{counter.job} Station for {price} credits.")

    def effect():
        add_duty(game.player_data, kind="serve", room=counter.room, item=item, patron=patron, reward=price,
                 summary=f"Serve {with_article(item)} to {patron} ({price} cr)")
        game.add_note(f"{patron} ordered {with_article(item)} for {price} credits.")

    return _job_event(title, desc, effect)


def _service_event(game, counter, side, title):
    """A Bartender's or Chef's job event: usually an order, sometimes a request through the service window."""
    if random.random() >= 1 - WINDOW_REQUEST_CHANCE:
        request = _window_request_event(game, side)
        if request:
            return request
    return _order_event(game, counter, title)


def _bartender_event(game):
    return _service_event(game, BAR_COUNTER, "bar", "Drink Order")


def _chef_event(game):
    return _service_event(game, KITCHEN_COUNTER, "kitchen", "Food Order")


def _item_request_event(game, title, requests):
    """A crew member asks for one of requests ((giver job, room key, item id[, gas]), ...), delivered for a reward.
    A request with a gas wants the item, a Gas Tank, filled with that gas."""
    offered = [request for request in requests if post_holder(game.station_crew, request[0], request[1])]
    if not offered:
        return None
    giver, room, item, *gas = random.choice(offered)
    label = item_with_article(get_item_definition(item)) + (f" of {gas[0]}" if gas else "")
    reward = random.randint(ITEM_REQUEST_MIN_REWARD, ITEM_REQUEST_MAX_REWARD)
    room_name = ROOMS[room].name
    desc = f"The {giver} needs {label}. Deliver it to the {room_name} for {reward} credits."

    def effect():
        add_duty(game.player_data, **_room_errand(giver, room, "deliver", label, reward, item),
                 **({"gas": gas[0]} if gas else {}))
        game.add_note(f"The {giver} requested {label} for {reward} credits.")

    return _job_event(title, desc, effect)


def _compound_request_event(game):
    return _item_request_event(game, "Compound Request", COMPOUND_REQUESTS)


def _miner_event(game):
    return _item_request_event(game, "Ore Request", ORE_REQUESTS)


def _gas_request_event(game):
    return _item_request_event(game, "Gas Request", GAS_REQUESTS)


def _bomb_test_event(game):
    """Central Command wants a blast of one size tested on the Atmospherics test range."""
    size = random.choice(list(RANGE_BOUNTY))
    reward = RANGE_BOUNTY[size]
    desc = (f"Central Command wants a {size} blast tested on the Atmospherics test range. Build a transfer valve "
            f"bomb that size and run it there for {reward} credits.")

    def effect():
        add_duty(game.player_data, kind="bomb_test", room=ATMOSPHERICS_KEY, size=size, reward=reward,
                 summary=f"Test a {size} bomb on the range ({reward} cr)")
        game.add_note(f"Central Command asked for a {size} bomb test for {reward} credits.")

    return _job_event("Bomb Test", desc, effect)


def _atmospherics_event(game):
    return random.choice((_gas_request_event, _bomb_test_event))(game)


def _quartermaster_event(game):
    return _item_request_event(game, "Supply Request", SUPPLY_REQUESTS)


def _artifact_delivery_event(game):
    """Central Command sends an artifact up to be worked out, while there is room for it on the bench."""
    bench = game.player_data["research"]["bench"]
    if len(bench) >= MAX_BENCH:
        return None
    desc = ("Central Command has sent up an artifact it can't make sense of. It is on the bench in the Research "
            f"Lab. Work out what it is and what sets it off for {ANALYSIS_REWARD} credits.")

    def effect():
        artifact = new_artifact()
        duty = add_duty(game.player_data, kind="analyse", room=RESEARCH_KEY, reward=ANALYSIS_REWARD,
                        summary=f"Analyse an artifact on the bench ({ANALYSIS_REWARD} cr)")
        artifact_of(artifact)["duty"] = duty["id"]
        bench.append(artifact)
        game.add_note("Central Command sent an artifact to the Research Lab for analysis.")

    return _job_event("Artifact Delivery", desc, effect)


def _doctor_event(game):
    patients = _available_crew(game)
    if not patients:
        return None
    patient = random.choice(patients)
    name = patient["name"]
    limb = random.choice(LIMBS)
    damage = random.randint(PATIENT_MIN_DAMAGE, PATIENT_MAX_DAMAGE)
    desc = (
        f"{name} ({patient.get('job', 'Crew')}) hurt their {limb_label(limb).lower()} in an accident. "
        "Treat them from Crew Vitals at the MedBay Station."
    )

    def effect():
        change_limb(patient, limb, -damage)
        add_duty(game.player_data, kind="treat", room=MEDBAY_KEY, patient=name,
                 summary=f"Treat {name} from Crew Vitals")
        game.add_note(f"{name} was hurt and needs treatment.")

    return _job_event("Patient", desc, effect)


def _suspects(game):
    """Crew who could be up to no good: free to act, not in a law-abiding job, and not already wanted."""
    return [npc for npc in _available_crew(game) if npc.get("job") not in LAW_ABIDING_JOBS and not npc.get("warrant")]


def _security_event(game):
    """A Guard out in the hallways sees a crime and who did it."""
    if game.current_room_name() is not None:
        return None
    suspects = _suspects(game)
    if not suspects:
        desc = "You witness a crime! You do not catch who it is."

        def effect():
            game.add_note("Witnessed a crime; perpetrator unidentified.")

        return _job_event("Witness a Crime", desc, effect)

    culprit = random.choice(suspects)
    name = culprit.get("name", "A crew member")
    charge = random.choice(PETTY_CRIMES)
    desc = f"You witness a crime! {name} is involved. A warrant is out for {charge.lower()}."

    def effect():
        set_warrant(culprit, charge)
        game.add_note(f"Witnessed {name} committing {charge.lower()}. A warrant has been issued.")

    return _job_event("Witness a Crime", desc, effect)


def _captain_event(game):
    """A department asks the Captain to approve something. It waits on the Duties board for Approve or Deny."""
    suspects = _suspects(game)
    power = game.player_data["station_power"]
    engineer = post_holder(game.station_crew, "Engineer") is not None
    unlocked = [key for key in LOCKDOWN_DOOR_KEYS if not game.ship_map[key]["locked"]]
    can_ask = {
        "life_support": engineer and power["system_levels"]["life_support"] < 10,
        "power_saving": engineer and power["power_mode"] != "low",
        "lockdown": post_holder(game.station_crew, "Security Guard") is not None and bool(unlocked),
        "warrant": bool(suspects),
    }
    already_open = {duty["request"] for duty in open_duties(game.player_data, ("command",))}
    requests = [key for key in CAPTAIN_REQUESTS if can_ask[key] and key not in already_open]
    if not requests:
        return None
    request = random.choice(requests)
    suspect = random.choice(suspects)["name"] if request == "warrant" else None
    door = random.choice(unlocked) if request == "lockdown" else None
    text = CAPTAIN_REQUESTS[request].format(suspect=suspect, room=ROOMS[door].name if door else None)
    desc = f"Command request: {text}"

    def effect():
        add_duty(game.player_data, kind="command", room=None, reward=0, summary=text.rstrip("."), request=request,
                 text=text,
                 suspect=suspect, door=door)
        game.add_note(desc)

    return _job_event("Command Request", desc, effect)


# The events each science lab brings the Scientist posted to it, by room key.
LAB_EVENT_BUILDERS = {
    CHEMISTRY_KEY: _compound_request_event,
    RESEARCH_KEY: _artifact_delivery_event,
    ATMOSPHERICS_KEY: _atmospherics_event,
}


def _scientist_event(game):
    """The event of the lab the player is posted to this shift, or of any of the Scientist's labs for one who holds
    them all. A lab with no events of its own brings none."""
    room_key = game.player_data["post_key"] or random.choice(JOB_POSTS["Scientist"])
    builder = LAB_EVENT_BUILDERS.get(room_key)
    return builder(game) if builder else None


JOB_EVENT_BUILDERS = {
    "Head of Personnel": _hop_event,
    "Staff Assistant": _staff_assistant_event,
    "Engineer": _engineer_event,
    "Botanist": _botanist_event,
    "Bartender": _bartender_event,
    "Chef": _chef_event,
    "Scientist": _scientist_event,
    "Miner": _miner_event,
    "Quartermaster": _quartermaster_event,
    "Doctor": _doctor_event,
    "Security Guard": _security_event,
    "Captain": _captain_event,
}

# These jobs' events put a duty on the board, so none comes while the board is full.
DUTY_JOBS = frozenset({"Staff Assistant", "Botanist", "Bartender", "Chef", "Scientist", "Miner", "Doctor",
                       "Quartermaster", "Captain"})


def build_job_event(game):
    """The next event for the player's current job, or None when it has nothing for them right now."""
    job = game.player_data["job"]
    if job in DUTY_JOBS and duties_full(game.player_data):
        return None
    return JOB_EVENT_BUILDERS[job](game)


def tick_job_events(game):
    """Bring the player's job its next event when one is due. A fight, or the shuttle at the dock or in flight,
    puts it off until the next one is due."""
    player_data = game.player_data
    round_ = player_data["round"]
    elapsed = get_elapsed_seconds(player_data)
    if elapsed < round_["next_job_event_at"]:
        return
    round_["next_job_event_at"] = elapsed + random.randint(*JOB_EVENT_INTERVAL_RANGE)
    leaving = round_["shuttle"]["state"] in ("docked", "transit")
    event = None if player_data["fight"] or leaving else build_job_event(game)
    if event is not None:
        _run_event(game, event)

# What each of the remedies Chemistry makes for MedBay treats, as a crew member taken ill during the flight has it.
FLIGHT_AILMENTS = {
    "burn_salve": "has scalded their hands on the coffee machine",
    "antitoxin": "is doubled over with food poisoning",
    "oxygen_tonic": "can't catch their breath",
    "healing_gel": "has wrenched a knee in their harness",
}
FLIGHT_REMEDY_REWARD_RANGE = (30, 80)
TURBULENCE_DAMAGE_RANGE = (5, 15)
LOOSE_CARGO_KNOCK_CHANCE = 0.5
LOOSE_CARGO_DAMAGE_RANGE = (5, 10)
COFFEE_ID = drink_id("Coffee")


def _flight_event(title, desc, effect):
    return {"type": "flight", "title": title, "desc": desc, "effect": effect}


def _turbulence(game):
    """Throws about a player who isn't secured, and spills the coffee they carry."""
    def effect():
        player_data = game.player_data
        if secured(player_data):
            _report_effect(game, "Turbulence", "You are held fast and ride it out.")
            return
        damage_random_limb(game, *TURBULENCE_DAMAGE_RANGE)
        coffee = inventory_index(player_data, COFFEE_ID)
        if coffee is not None:
            remove_one_from_inventory(player_data, coffee)
            _report_effect(game, "Turbulence", "Your coffee goes everywhere.")

    return _flight_event("Turbulence", "The shuttle bucks and drops through a patch of turbulence.", effect)


def _taken_ill(game):
    """A crew member in the seats is taken ill. The player can give them the remedy for it, if they carry one."""
    seated = seated_crew(game)
    if not seated:
        return None
    npc = random.choice(seated)
    remedy = random.choice(STORE_REMEDY_IDS)
    desc = f"{npc['name']} ({npc['job']}) {FLIGHT_AILMENTS[remedy]}."
    args = {"crew_name": npc["name"], "remedy": remedy}

    def effect():
        carried = inventory_index(game.player_data, remedy) is not None
        give = [("Give Them a Remedy", "flight_give_remedy", args)] if carried else []
        game.ask("Taken Ill", f"{desc} What do you do?",
                 give + [("Leave It to the Medics", "flight_leave_to_medics", args)])

    return _flight_event("Taken Ill", desc, effect)


@choice_handler("flight_give_remedy")
def give_remedy(game, crew_name, remedy):
    index = inventory_index(game.player_data, remedy)
    if index is None:
        return
    remove_one_from_inventory(game.player_data, index)
    reward = random.randint(*FLIGHT_REMEDY_REWARD_RANGE)
    game.player_data["credits"] += reward
    message = (f"You give {crew_name} your {get_item_definition(remedy)['name']}. They feel better at once and pay "
               f"you {reward} credits.")
    game.alert("Taken Ill", message)
    game.add_note(message)


@choice_handler("flight_leave_to_medics")
def leave_to_medics(game, crew_name, remedy):
    """Leave it to the medics, wondering what would have helped when the player had nothing that would."""
    message = f"You leave {crew_name} to the shuttle's medics."
    if inventory_index(game.player_data, remedy) is None:
        message += f" Maybe if I had {with_article(get_item_definition(remedy)['name'])}, I could have helped them."
    game.alert("Taken Ill", message)


def _loose_cargo(game):
    desc = "A crate breaks loose from the cargo netting and slides down the aisle toward you."

    def effect():
        game.ask("Loose Cargo", f"{desc} What do you do?",
                 [("Grab It", "flight_grab_cargo", None), ("Let It Slide", "flight_let_cargo_slide", None)])

    return _flight_event("Loose Cargo", desc, effect)


@choice_handler("flight_grab_cargo")
def grab_cargo(game):
    """Grab the crate for what is in it, at the risk of a knock from it."""
    if random.random() < LOOSE_CARGO_KNOCK_CHANCE:
        damage_random_limb(game, *LOOSE_CARGO_DAMAGE_RANGE)
    add_random_item(game)


@choice_handler("flight_let_cargo_slide")
def let_cargo_slide(game):
    game.alert("Loose Cargo", "You let it slide. It thuds against the bulkhead and stays there.")


def _radio_call(game):
    desc = "Central Command comes over the shuttle's radio and asks how the shift went."

    def effect():
        game.ask("Central Command", desc, [("It Went Well", "flight_radio_answer", {"well": True}),
                                           ("It Was Rough", "flight_radio_answer", {"well": False})])

    return _flight_event("Central Command", desc, effect)


@choice_handler("flight_radio_answer")
def radio_answer(game, well):
    game.alert("Central Command", "You tell Central Command the shift went well. They log it and sign off." if well
               else "You tell Central Command it was a rough shift. They promise a full debrief and sign off.")


FLIGHT_EVENT_BUILDERS = (_turbulence, _taken_ill, _loose_cargo, _radio_call)


def tick_flight_event(game):
    """Once during the flight, at the time picked as the shuttle left, something happens aboard. There is none on a
    flight with a fight aboard."""
    round_ = game.player_data["round"]
    at = round_["flight_event_at"]
    if at is None or get_elapsed_seconds(game.player_data) < at:
        return
    round_["flight_event_at"] = None
    if game.player_data["fight"]:
        return
    events = [event for event in (build(game) for build in FLIGHT_EVENT_BUILDERS) if event]
    _run_event(game, random.choice(events))


def trigger_random_event(game):
    """Pick a category, then one of its hallway events, and make it happen."""
    category = random.choice(EVENT_CATEGORIES)
    _run_event(game, random.choice([event for event in _static_events(game) if event["type"] == category]))


def _health_and_floor(game):
    player_data = game.player_data
    return (dict(player_data["limbs"]), dict(player_data["damage"]),
            len(player_data["floor"].get(game.location_key(), [])))


def _needs_attention(before, after):
    """Whether an event hurt the player or left something on the floor at their feet."""
    (limbs, damage, floor), (limbs_now, damage_now, floor_now) = before, after
    return (any(limbs_now[limb] < health for limb, health in limbs.items())
            or any(damage_now.get(kind, 0) > amount for kind, amount in damage.items()) or floor_now > floor)


def _run_event(game, event):
    """Apply an event and log it as one line: its description, then whatever its effects reported. One that hurt the
    player or left something at their feet goes to the PDA too."""
    before = _health_and_floor(game)
    game.event_messages = []
    try:
        event["effect"]()
        body = event["desc"]
        if game.event_messages:
            body = body + "\n\n" + "\n".join(game.event_messages)
        game.alert(event["title"], body)
        if _needs_attention(before, _health_and_floor(game)):
            game.page(event["title"], body)
    finally:
        game.event_messages = None


def _report_effect(game, title, message):
    """Log what an effect did, or hold it for the event it is part of to log with its own line."""
    if game.event_messages is not None:
        game.event_messages.append(message)
    else:
        game.alert(title, message)


def _add_damage_type(game, damage_key, label, min_damage, max_damage):
    damage = random.randint(min_damage, max_damage)
    original_damage = game.player_data["damage"].get(damage_key, 0)
    game.player_data["damage"][damage_key] = min(100, original_damage + damage)
    total = game.player_data["damage"][damage_key]
    _report_effect(
        game,
        f"{label} Damage",
        f"You suffered {damage}% {label.lower()} damage! Total {label.lower()} damage: {total}%.",
    )
    game.add_note(
        f"Suffered {label.lower()} damage: Took {damage}% damage (total now {total}%)"
    )


def add_burn_damage(game, min_damage, max_damage):
    _add_damage_type(game, "burn", "Burn", min_damage, max_damage)


def add_poison_damage(game, min_damage, max_damage):
    _add_damage_type(game, "poison", "Poison", min_damage, max_damage)


def hallway_accident(game, title):
    """Do to the player what HALLWAY_ACCIDENTS says the bad hallway event called title does."""
    hurts = HALLWAY_ACCIDENTS[title]
    if "credits" in hurts:
        lose_credits(game, random.randint(*hurts["credits"]))
    limb, low, high = hurts["limb"]
    if limb is None:
        damage_random_limb(game, low, high)
    else:
        damage_limb(game, limb, low, high)
    if "burn" in hurts:
        add_burn_damage(game, *hurts["burn"])
    if "poison" in hurts:
        add_poison_damage(game, *hurts["poison"])


def damage_random_limb(game, min_damage, max_damage):
    limb = random.choice(list(game.player_data["limbs"].keys()))
    damage_limb(game, limb, min_damage, max_damage)


def damage_limb(game, limb, min_damage, max_damage):
    damage = random.randint(min_damage, max_damage)
    before, after = change_limb(game.player_data, limb, -damage)
    limb_name = limb_label(limb)
    _report_effect(game, "Injury", f"Your {limb_name} took {damage}% damage and is now at {after}%.")
    game.add_note(f"Suffered damage to {limb_name}: Took {damage}% damage (from {before}% to {after}%)")


def add_credits(game, amount):
    game.player_data["credits"] += amount
    _report_effect(game, "Credits Added", f"You gained {amount} credits.")
    game.add_note(
        f"Found {amount} credits. New balance: {game.player_data['credits']} credits."
    )


def lose_credits(game, amount):
    old_credits = game.player_data["credits"]
    game.player_data["credits"] = max(0, old_credits - amount)
    lost = old_credits - game.player_data["credits"]
    _report_effect(game, "Credits Lost", f"You lost {lost} credits.")
    game.add_note(
        f"Lost {lost} credits. New balance: {game.player_data['credits']} credits."
    )


def add_random_item(game):
    """Add a random item (using item definitions) to the player's inventory."""
    item_id = random.choice(list(ALL_ITEMS))
    item_def = get_item_definition(item_id)
    add_to_inventory(game.player_data, item_def)
    item_name = item_def.get("name", "an item")
    _report_effect(
        game,
        "Item Found",
        f"You found {item_name} and added it to your inventory.",
    )

    game.add_note(f"Found {item_name} ({item_id}) and added it to inventory.")


def _leave_on_floor(game, item_id, title, message, note):
    """Put one item_id on the floor where the player stands, to be picked up, and report it."""
    stack_into(game.floor_here(), get_item_definition(item_id))
    _report_effect(game, title, message)
    game.add_note(note)


def leave_random_item(game):
    """Leave a random item on the floor where the player stands."""
    item_id = random.choice(list(ALL_ITEMS))
    name = get_item_definition(item_id).get("name", "an item")
    _leave_on_floor(game, item_id, "Item Found", f"You found {name}. It's on the floor here.",
                    f"Found {name} ({item_id}) on the floor.")


def add_market_knowledge(game):
    """Add market knowledge to the player - reveals a tip about a stock."""
    message = generate_market_tip(game.market_engine.news)
    if message is None:
        _report_effect(game, "Market Tip", "You heard a stock tip, but there is no market news to pin it on.")
        return

    _report_effect(game, "Market Tip", message)
    game.add_note(f"Market Tip: {message}")


def station_announcement(game):
    announcements = [
        "Reminder to all crew: safety protocols must be followed at all times.",
        "The cafeteria is now serving special meal rations.",
        "Maintenance is scheduled in Sector 7 shortly.",
        "All personnel are reminded to report suspicious activity to security.",
        "The crew meeting is postponed until further notice.",
        "Environmental controls are being recalibrated. Expect minor temperature fluctuations.",
    ]

    if not system_online(game.player_data, "communication_array"):
        _report_effect(game, "Station Announcement", "The PA speakers crackle, but only static comes through.")
        return
    announcement = random.choice(announcements)
    _report_effect(
        game,
        "Station Announcement",
        f"The PA system crackles: '{announcement}'",
    )


def heal_limb(game, limb, min_heal, max_heal):
    original, new_health = change_limb(game.player_data, limb, random.randint(min_heal, max_heal))
    limb_name = limb_label(limb)
    healed = new_health - original

    _report_effect(
        game,
        "Medical Treatment",
        f"Your {limb_name} was healed by {healed}% and is now at {new_health}%.",
    )
    game.add_note(
        f"Medical bot healed {limb_name}: +{healed}% "
        f"(from {original}% to {new_health}%)"
    )


def heal_damage_type(game, damage_key, min_heal, max_heal):
    original, new_value = reduce_damage(game.player_data, damage_key, random.randint(min_heal, max_heal))
    label = damage_key.title()
    healed = original - new_value

    _report_effect(
        game,
        "Medical Treatment",
        f"Your {label.lower()} damage was reduced by {healed}% "
        f"(now {new_value}%).",
    )
    game.add_note(
        f"Medical bot treated {label.lower()} damage: -{healed}% "
        f"(from {original}% to {new_value}%)"
    )


def medical_bot_heal(game):
    """Heal one random damaged limb or damage type by 1-5%."""
    candidates = []

    for limb, health in game.player_data["limbs"].items():
        if health < 100:
            candidates.append(("limb", limb))

    for damage_key in DAMAGE_TYPES:
        if game.player_data["damage"][damage_key] > 0:
            candidates.append(("damage", damage_key))

    if not candidates:
        _report_effect(
            game,
            "Medical Bot",
            "A medical bot scans you, finds nothing to treat, and rolls away.",
        )
        return

    choice = random.choice(candidates)
    if choice[0] == "limb":
        heal_limb(game, choice[1], 1, 5)
    else:
        heal_damage_type(game, choice[1], 1, 5)


def bot_moves_by(game):
    bot = random.choice(["maintenance", "security", "medical"])

    if bot == "maintenance":
        _report_effect(
            game,
            "Maintenance Bot",
            "A maintenance bot rolls past, scrubbing the floor as it goes.",
        )
    elif bot == "security":
        if game.player_data["warrant"] and warrants_enforced(game.player_data):
            message = ("A security bot locks onto you. You are wanted, and you are under arrest!\n"
                       f"Charge: {warrant_reason_text(game.player_data)}")
            _report_effect(game, "Security Bot", message)
            arrest_member(
                game.player_data,
                reason=message,
                game=game,
                is_player=True,
                show_message=False,
                elapsed_seconds=get_elapsed_seconds(game.player_data),
            )
        else:
            _report_effect(
                game,
                "Security Bot",
                "A security bot scans you briefly and continues on its patrol.",
            )
    else:
        _report_effect(
            game,
            "Medical Bot",
            "A medical bot stops beside you and runs a quick diagnostic.",
        )
        medical_bot_heal(game)


def leave_snack(game):
    _leave_on_floor(game, "snack", "Free Snack", "A free Snack drops into the tray. It's on the floor here.",
                    "Found a Snack from a vending machine on the floor.")


def vending_machine_malfunction(game):
    outcome = random.choice(["spit_out", "stuck", "free_snack"])

    if outcome == "spit_out":
        _report_effect(
            game,
            "Vending Machine",
            "The machine violently spits something out at you!",
        )
        damage_random_limb(game, 1, 5)
    elif outcome == "stuck":
        _report_effect(
            game,
            "Vending Machine",
            "You see a snack stuck against the glass, just out of reach.",
        )
    else:
        _report_effect(
            game,
            "Vending Machine",
            "The machine clunks and a free snack drops into the tray.",
        )
        leave_snack(game)
