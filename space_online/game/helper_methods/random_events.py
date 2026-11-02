"""Hallway random-event catalog, trigger, and effect helpers."""

import random
from space_online.game.helper_methods.health_bands import DAMAGE_TYPES, change_limb, limb_label, reduce_damage

from space_online.game.character_methods.character_creation import REQUESTABLE_JOBS
from space_online.game.helper_methods.door_control import SPECIAL_ROOM_DOORS
from space_online.game.helper_methods.errands import pending_errand, with_article
from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.health_bands import LIMBS
from space_online.game.helper_methods.jail import (
    LAW_ABIDING_JOBS,
    PETTY_CRIMES,
    arrest_member,
    is_jailed,
    set_warrant,
    warrant_reason_text,
)
from space_online.game.helper_methods.npc_movement import any_npc_for_job, find_hall_passersby
from space_online.game.helper_methods.power_constants import FAULTABLE_SYSTEMS, fault_system
from space_online.game.helper_methods.stock_market import generate_market_tip
from space_online.game.maps.donut import BAR_KEY, BOTANY_KEY, ENGINEERING_KEY, MEDBAY_KEY, SECURITY_KEY
from space_online.game.objects.drinks import MIXED_DRINKS
from space_online.game.objects.food import PRODUCE
from space_online.game.objects.items import ALL_ITEMS, add_to_inventory, get_item_definition
from space_online.game.special_rooms.engineering import system_name

HALLWAY_EVENT_CHANCE = 0.20
CROP_REQUEST_MIN_REWARD = 50
CROP_REQUEST_MAX_REWARD = 150
ERRAND_MIN_REWARD = 25
ERRAND_MAX_REWARD = 75
PATIENT_MIN_DAMAGE = 15
PATIENT_MAX_DAMAGE = 35
EVENT_CATEGORIES = ("good", "neutral", "bad", "job")

# A deliver errand with no item brings a random piece of produce.
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

# {suspect} is filled with a crew member's name.
CAPTAIN_REQUESTS = {
    "life_support": "Engineering needs approval to divert power to life support.",
    "lockdown": "Security requests permission to lock down a sector.",
    "power_saving": "Engineering requests permission to switch the station to Power Saving mode.",
    "warrant": "Security requests a warrant for {suspect} on suspicion of smuggling.",
}


def maybe_trigger_hallway_event(game):
    """Roll for a hallway event and trigger one on success."""
    if random.random() < HALLWAY_EVENT_CHANCE:
        trigger_random_event(game)


def _static_events(game):
    """Good / neutral / bad hallway events (job events are built separately)."""
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
            "effect": lambda: add_random_item(game),
        },
        {
            "type": "good",
            "title": "Market Tip",
            "desc": "You overheard a reliable market tip.",
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
            "effect": lambda: combined_effect(
                [
                    lambda: lose_credits(game, random.randint(10, 50)),
                    lambda: damage_limb(game, "head", 5, 10),
                ]
            ),
        },
        {
            "type": "bad",
            "title": "Small Explosion",
            "desc": "A nearby conduit explodes, showering you with hot sparks and debris!",
            "effect": lambda: combined_effect(
                [
                    lambda: damage_random_limb(game, 10, 25),
                    lambda: add_burn_damage(game, 5, 15),
                ]
            ),
        },
        {
            "type": "bad",
            "title": "Slip and Fall",
            "desc": "You slipped on a wet floor and fell hard.",
            "effect": lambda: damage_random_limb(game, 10, 20),
        },
        {
            "type": "bad",
            "title": "Steam Leak",
            "desc": "A pipe bursts, releasing scalding steam that burns your arm!",
            "effect": lambda: combined_effect(
                [
                    lambda: damage_limb(game, "left_arm", 5, 10),
                    lambda: add_burn_damage(game, 15, 30),
                ]
            ),
        },
        {
            "type": "bad",
            "title": "Falling Debris",
            "desc": "A ceiling panel breaks loose and hits your head!",
            "effect": lambda: damage_limb(game, "head", 15, 35),
        },
        {
            "type": "bad",
            "title": "Maintenance Accident",
            "desc": "Your leg gets caught in an open floor grate!",
            "effect": lambda: damage_limb(game, "right_leg", 10, 20),
        },
        {
            "type": "bad",
            "title": "Chemical Spill",
            "desc": "You walk through a chemical spill! Your leg is burned and you feel ill.",
            "effect": lambda: combined_effect(
                [
                    lambda: damage_limb(game, "left_leg", 5, 10),
                    lambda: add_burn_damage(game, 5, 15),
                    lambda: add_poison_damage(game, 10, 20),
                ]
            ),
        },
    ]


def _job_event(title, desc, effect):
    return {"type": "job", "title": title, "desc": desc, "effect": effect}


def _room_errand(giver, room, kind, label, reward, item=None):
    """A deliver or help errand, with its Station Status summary."""
    room_name = SPECIAL_ROOM_DOORS[room]["room_name"]
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
    return [npc for npc in game.station_crew if npc.get("name") and not npc.get("in_jail")]


def _hop_event(game):
    if game.player_data.get("access_request"):
        return None
    candidates = [npc for npc in _available_crew(game) if npc.get("job") != "Captain"]
    if not candidates:
        return None
    npc = random.choice(candidates)
    requested_job = random.choice(REQUESTABLE_JOBS)
    requester = npc.get("name", "A crew member")
    desc = (
        f"{requester} ({npc.get('job', 'Crew')}) has submitted an access request "
        f"to become {requested_job}. Review it at the HoP Access Control console."
    )

    def effect():
        game.player_data["access_request"] = {
            "requested_job": requested_job,
            "requester_name": requester,
        }
        game.add_note(
            f"Access request: {requester} requested assignment as {requested_job}."
        )

    return _job_event("Access Request", desc, effect)


def _staff_assistant_event(game):
    offered = [errand for errand in STAFF_ASSISTANT_ERRANDS if any_npc_for_job(game.station_crew, errand["giver"])]
    if not offered:
        return None
    request = random.choice(offered)
    reward = random.randint(ERRAND_MIN_REWARD, ERRAND_MAX_REWARD)
    room_name = SPECIAL_ROOM_DOORS[request["room"]]["room_name"]
    if request["kind"] == "deliver":
        item = request.get("item")
        if item:
            label = with_article(get_item_definition(item)["name"].lower())
        else:
            item, label = _random_produce()
        errand = _room_errand(request["giver"], request["room"], "deliver", label, reward, item)
        desc = f"Job request: {request['request']} Bring {label} to the {room_name} for {reward} credits."
    else:
        errand = _room_errand(request["giver"], request["room"], "help", request["label"], reward)
        desc = f"Job request: {request['request']} Report to the {room_name} for {reward} credits."

    def effect():
        game.player_data["errand"] = errand
        game.add_note(desc)

    return _job_event("Job Request", desc, effect)


def _engineer_event(game):
    power = game.player_data["station_power"]
    working = [key for key in FAULTABLE_SYSTEMS if key not in power["faults"]]
    if not working or random.choice(("solar", "fault")) == "solar":
        desc = (
            "The solar panels have shut down unexpectedly. "
            "They must be restarted from the Engineering Panel."
        )

        def effect():
            power["solar_charging"] = False
            game.add_note("Solar arrays went offline and need to be restarted.")

        return _job_event("Solar Panels Offline", desc, effect)

    system_key = random.choice(working)
    name = system_name(system_key)
    desc = (
        f"The {name} has faulted and shut down. Repair it from the Engineering Panel "
        "with Basic Tools or a Repair Tool."
    )

    def effect():
        fault_system(power, system_key)
        game.add_note(f"The {name} faulted and needs repairing.")

    return _job_event("System Fault", desc, effect)


def _botanist_event(game):
    if any_npc_for_job(game.station_crew, "Bartender") is None:
        return None
    produce_id, label = _random_produce()
    reward = random.randint(CROP_REQUEST_MIN_REWARD, CROP_REQUEST_MAX_REWARD)
    desc = f"The Bartender needs {label} from the botany lab. Deliver it to the Bar for {reward} credits."

    def effect():
        game.player_data["errand"] = _room_errand("Bartender", BAR_KEY, "deliver", label, reward, produce_id)
        game.add_note(f"Bartender requested {label} from botany for {reward} credits.")

    return _job_event("Crop Request", desc, effect)


def _bartender_event(game):
    patrons = _available_crew(game)
    if not patrons:
        return None
    patron = random.choice(patrons)["name"]
    drink = random.choice(list(MIXED_DRINKS))
    price = MIXED_DRINKS[drink]["price"]
    desc = f"{patron} orders {with_article(drink)}. Mix one and serve it from the Bartender Station for {price} credits."

    def effect():
        game.player_data["errand"] = {
            "kind": "serve", "room": BAR_KEY, "item": drink, "patron": patron, "reward": price,
            "summary": f"Serve {with_article(drink)} to {patron} ({price} cr)",
        }
        game.add_note(f"{patron} ordered {with_article(drink)} for {price} credits.")

    return _job_event("Drink Order", desc, effect)


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
        game.player_data["errand"] = {
            "kind": "treat", "room": MEDBAY_KEY, "patient": name, "summary": f"Treat {name} from Crew Vitals",
        }
        game.add_note(f"{name} was hurt and needs treatment.")

    return _job_event("Patient", desc, effect)


def _security_event(game):
    suspects = [npc for npc in find_hall_passersby(game.player_data, game.station_crew)
                if npc.get("job") not in LAW_ABIDING_JOBS and not npc.get("warrant")]
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
    suspects = [npc for npc in _available_crew(game)
                if npc.get("job") not in LAW_ABIDING_JOBS and not npc.get("warrant")]
    requests = [key for key in CAPTAIN_REQUESTS if key != "warrant" or suspects]
    request = random.choice(requests)
    suspect = random.choice(suspects)["name"] if request == "warrant" else None
    text = CAPTAIN_REQUESTS[request].format(suspect=suspect)
    desc = f"Command request: {text}"

    def effect():
        game.add_note(desc)
        game.ask(
            "Command Request",
            f"{text}\n\nApprove this request?",
            [
                ("Approve", "approve_command_request", {"request": request, "text": text, "suspect": suspect}),
                ("Deny", "deny_command_request", {"text": text}),
            ],
        )

    return _job_event("Command Request", desc, effect)


JOB_EVENT_BUILDERS = {
    "Head of Personnel": _hop_event,
    "Staff Assistant": _staff_assistant_event,
    "Engineer": _engineer_event,
    "Botanist": _botanist_event,
    "Bartender": _bartender_event,
    "Doctor": _doctor_event,
    "Security Guard": _security_event,
    "Captain": _captain_event,
}

# These jobs' events give an errand, so none rolls while one is waiting.
ERRAND_JOBS = frozenset({"Staff Assistant", "Botanist", "Bartender", "Doctor"})


def build_job_event(game):
    """Build the single job-category event for the player's current role, or None."""
    job = game.player_data["job"]
    if job in ERRAND_JOBS and pending_errand(game.player_data):
        return None
    return JOB_EVENT_BUILDERS[job](game)


def _events_by_category(game):
    """Group static events by type and attach the player's job event."""
    by_type = {category: [] for category in EVENT_CATEGORIES}
    for event in _static_events(game):
        by_type[event["type"]].append(event)

    job_event = build_job_event(game)
    if job_event is not None:
        by_type["job"].append(job_event)

    return by_type


def trigger_random_event(game):
    """Pick a category, then an event in that category, and show a combined popup."""
    by_type = _events_by_category(game)
    available = [cat for cat in EVENT_CATEGORIES if by_type.get(cat)]
    if not available:  # pragma: no cover - there is always an event to pick
        return

    category = random.choice(available)

    event = random.choice(by_type[category])

    game.event_messages = []
    try:
        event["effect"]()
        body = event["desc"]
        if game.event_messages:
            body = body + "\n\n" + "\n".join(game.event_messages)
        game.alert(event["title"], body)
    finally:
        game.event_messages = None


def _report_effect(game, title, message):
    """Show an effect popup, or buffer the message during a random event."""
    if game.event_messages is not None:
        game.event_messages.append(message)
    else:
        game.report(title, message)


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


def combined_effect(effect_functions):
    for effect_fn in effect_functions:
        effect_fn()


def damage_random_limb(game, min_damage, max_damage):
    limb = random.choice(list(game.player_data["limbs"].keys()))
    damage_limb(game, limb, min_damage, max_damage)


def damage_limb(game, limb, min_damage, max_damage):
    damage = random.randint(min_damage, max_damage)
    before, after = change_limb(game.player_data, limb, -damage)
    limb_name = limb_label(limb)
    _report_effect(game, "Blunt Injury", f"Your {limb_name} took {damage}% blunt damage and is now at {after}%.")
    game.add_note(f"Suffered blunt damage to {limb_name}: Took {damage}% damage (from {before}% to {after}%)")


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


def add_market_knowledge(game):
    """Add market knowledge to the player - reveals a tip about a stock."""
    message = generate_market_tip(game.player_data["stock_market"].get("companies", []))
    if message is None:
        _report_effect(
            game,
            "Market Tip",
            "You heard a stock tip, but don't understand the market yet.",
        )
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
        if is_jailed(game.player_data):
            _report_effect(  # pragma: no cover - jailed players can't walk, and walking is what triggers events
                game,
                "Security Bot",
                "A security bot rolls past your cell without stopping.",
            )
        elif game.player_data.get("warrant", False):
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


def add_snack(game):
    add_to_inventory(game.player_data, get_item_definition("snack"))
    _report_effect(
        game,
        "Free Snack",
        "You found a free Snack and added it to your inventory.",
    )
    game.add_note("Found a Snack from a vending machine and added it to inventory.")


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
        add_snack(game)
