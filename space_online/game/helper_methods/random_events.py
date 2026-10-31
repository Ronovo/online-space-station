"""Hallway random-event catalog, trigger, and effect helpers."""

import random
from space_online.game.helper_methods.health_bands import DAMAGE_TYPES, change_limb, limb_label, reduce_damage

from space_online.game.character_methods.character_creation import REQUESTABLE_JOBS
from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.jail import arrest_member, is_jailed, warrant_reason_text
from space_online.game.helper_methods.npc_movement import find_hall_passersby
from space_online.game.helper_methods.stock_market import generate_market_tip
from space_online.game.objects.botany_items import BOTANY_SEED_IDS
from space_online.game.objects.items import ALL_ITEMS, add_to_inventory, get_item_definition

HALLWAY_EVENT_CHANCE = 0.20
EVENT_CATEGORIES = ("good", "neutral", "bad", "job")

STAFF_ASSISTANT_REQUESTS = [
    "The Botanist needs water for the planters.",
    "The Captain needs a hand in Engineering.",
    "The Bartender needs an ingredient for a drink.",
    "The Doctor needs someone to restock bandages.",
    "Security needs help filing paperwork.",
]

CAPTAIN_REQUESTS = [
    "Medbay requests authorization for emergency surgery supplies.",
    "Engineering needs approval to divert power to life support.",
    "Security requests permission to lock down a sector.",
    "A department head wants a private briefing.",
    "Cargo bay reports a missing shipment and needs orders.",
]


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


def build_job_event(game):
    """Build the single job-category event for the player's current role."""
    job = game.player_data["job"]
    if job == "Head of Personnel":
        if game.player_data.get("access_request"):
            return None
        crew = game.station_crew
        candidates = [npc for npc in crew
                      if npc.get("name") and not npc.get("in_jail") and npc.get("job") != "Captain"]
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

        return {
            "type": "job",
            "title": "Access Request",
            "desc": desc,
            "effect": effect,
        }

    if job == "Staff Assistant":
        request = random.choice(STAFF_ASSISTANT_REQUESTS)
        desc = f"Job request: {request}"

        def effect():
            game.add_note(desc)

        return {
            "type": "job",
            "title": "Job Request",
            "desc": desc,
            "effect": effect,
        }

    if job == "Engineer":
        desc = (
            "The solar panels have shut down unexpectedly. "
            "They must be restarted from the Engineering Panel."
        )

        def effect():
            power = game.player_data["station_power"]
            power["solar_charging"] = False
            game.add_note("Solar arrays went offline and need to be restarted.")

        return {
            "type": "job",
            "title": "Solar Panels Offline",
            "desc": desc,
            "effect": effect,
        }

    if job == "Botanist":
        crop = random.choice(BOTANY_SEED_IDS).removesuffix("_seeds")
        article = "an" if crop[0] in "aeiou" else "a"
        desc = f"The Bartender needs {article} {crop} from the botany lab."

        def effect():
            game.add_note(f"Bartender requested {article} {crop} from botany.")

        return {
            "type": "job",
            "title": "Crop Request",
            "desc": desc,
            "effect": effect,
        }

    if job == "Security Guard":
        crew = game.station_crew
        passersby = find_hall_passersby(game.player_data, crew)
        if passersby:
            culprit = random.choice(passersby)
            name = culprit.get("name", "A crew member")
            desc = f"You witness a crime! {name} is involved."
            note = f"Witnessed a crime involving {name}."
        else:
            desc = "You witness a crime! You do not catch who it is."
            note = "Witnessed a crime; perpetrator unidentified."

        def effect():
            game.add_note(note)

        return {
            "type": "job",
            "title": "Witness a Crime",
            "desc": desc,
            "effect": effect,
        }

    if job == "Captain":
        request = random.choice(CAPTAIN_REQUESTS)
        desc = f"Command request: {request}"

        def effect():
            game.add_note(desc)

        return {
            "type": "job",
            "title": "Command Request",
            "desc": desc,
            "effect": effect,
        }

    return None


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
