import copy
import uuid

from space_online.game.helper_methods import gas_mix
from space_online.game.helper_methods.artifacts import ARTIFACT_ID, is_usable_artifact, use_artifact
from space_online.game.helper_methods.errands import with_article
from space_online.game.helper_methods.health_bands import LIMBS, change_limb, limb_label, reduce_damage
from space_online.game.helper_methods.needs import DEFAULT_FEEDS, DEFAULT_QUENCHES, satisfy
from space_online.game.helper_methods.ui_panels import panel_action, register_panel
from space_online.game.maps.donut import render_map_text
from space_online.game.objects.botany_items import BOTANY_ITEMS
from space_online.game.objects.chemicals import CHEMISTRY_ITEMS
from space_online.game.objects.food import FOOD_ITEMS
from space_online.game.objects.gases import GAS_TANK, STATION_AIR
from space_online.game.objects.mining_items import MINING_ITEMS
from space_online.game.objects.weapons import WEAPON_ITEMS

# Tool IDs that fit inside a Basic Tools set (one of each).
BASIC_TOOLKIT_TOOL_IDS = ("wrench", "screwdriver", "wirecutters")
PDA_ID = "pda"
GAS_TANK_ID = "gas_tank"
GAS_ANALYZER_ID = "gas_analyzer"
TRANSFER_VALVE_ID = "transfer_valve"
BOMB_ID = "transfer_valve_bomb"
NO_SCANNER = "Your PDA has no scanner for this."
NON_STACKABLE_ITEM_IDS = frozenset({"basic_tools", ARTIFACT_ID})

WELCOME_GUIDE_CONTENT = """WELCOME TO SPACE STATION EXPLORER

Welcome to your new home among the stars! This guide will help you get acquainted with life aboard our station.

IMPORTANT TIPS:
- Always follow safety protocols
- Report any unusual activity to Security
- Keep your personal quarters clean and organized
- Get to know your fellow crew members
- Visit the Bar for social interactions
- Check the computer terminal for stock market opportunities

We hope you enjoy your stay and contribute to our thriving community!
"""

# Generated from the map's own coordinate data (see space_online/game/maps/donut.py) so it
# always matches the actual station layout.
STATION_MAP_CONTENT = render_map_text()

ALL_ITEMS = {
    # --- Tools --- 
    "wrench": {
        "id": "wrench",
        "name": "Wrench",
        "description": "Standard tool for fastening and unfastening bolts and nuts. Useful for basic engineering tasks.",
        "category": "Tool",
        "attributes": {},
        "actions": ["examine", "use", "drop"]
    },
    "screwdriver": {
        "id": "screwdriver",
        "name": "Screwdriver", 
        "description": "A multi-head screwdriver for various screw types. Essential for accessing panels and device internals.",
        "category": "Tool",
        "attributes": {},
        "actions": ["examine", "use", "drop"]
    },
    "wirecutters": {
        "id": "wirecutters",
        "name": "Wirecutters",
        "plural": True,
        "description": "Tool for cutting and stripping wires safely. Necessary for electrical work.",
        "category": "Tool",
        "attributes": {},
        "actions": ["examine", "use", "drop"]
    },
    "repair_tool": {
        "id": "repair_tool",
        "name": "Repair Tool",
        "description": "A generic multi-tool for basic repairs.",
        "category": "Tool",
        "attributes": {},
        "actions": ["examine", "use", "drop"]
    },
    "fire_extinguisher": {
        "id": "fire_extinguisher",
        "name": "Fire Extinguisher",
        "description": "A red extinguisher. Puts out a fire in the room you are standing in.",
        "category": "Tool",
        "attributes": {"attack": 8},
        "actions": ["examine", "equip", "drop"]
    },
    "gas_analyzer": {
        "id": GAS_ANALYZER_ID,
        "name": "Gas Analyzer",
        "description": "A hand-held gas analyzer. Use it to read the air where you stand and every Gas Tank you carry.",
        "category": "Tool",
        "attributes": {},
        "actions": ["examine", "use", "drop"]
    },
    "gas_tank": {
        "id": GAS_TANK_ID,
        "name": "Gas Tank",
        "description": (f"A portable {GAS_TANK['volume']} L gas tank, rated to {GAS_TANK['rated']} kPa. Hold it in "
                        "a hand with its valve open to breathe from it through the mask."),
        "category": "Tool",
        "attributes": {"contents": gas_mix.empty_mix(), "valve_open": False},
        "actions": ["examine", "equip", "open_valve", "close_valve", "drop"]
    },
    "transfer_valve": {
        "id": TRANSFER_VALVE_ID,
        "name": "Tank Transfer Valve",
        "description": "A valve that joins two Gas Tanks. Use it to fit two tanks you carry to it, which makes a "
                       "Transfer Valve Bomb.",
        "category": "Tool",
        "attributes": {},
        "actions": ["examine", "use", "drop"]
    },
    "transfer_valve_bomb": {
        "id": BOMB_ID,
        "name": "Transfer Valve Bomb",
        "description": "Two Gas Tanks joined by a transfer valve. Opening the valve pours one tank's gas into the "
                       "other's.",
        "category": "Device",
        "attributes": {"contents": [], "goes_off_at": None, "armed_by": None},
        "actions": ["examine", "use", "open_transfer_valve", "set_timer", "disarm", "drop"]
    },
     "basic_tools": {
        "id": "basic_tools",
        "name": "Basic Tools",
        "plural": True,
        "description": "A set containing a small wrench, screwdriver, and wirecutters.",
        "category": "Tool",
        "attributes": {},
        "actions": ["examine", "use", "drop"]
    },

    "pda": {
        "id": "pda",
        "name": "PDA",
        "description": "Your personal data assistant. Hold it in a hand to open it, or use it on an object to scan something related to your job.",
        "category": "Device",
        "attributes": {},
        "actions": ["examine", "equip", "drop"]
    },

    # --- Books --- 
    "welcome_guide": {
        "id": "welcome_guide",
        "name": "Welcome Guide",
        "description": "A standard issue guide for new arrivals to the station.",
        "category": "Book",
        "attributes": {
            "content": WELCOME_GUIDE_CONTENT
        },
        "actions": ["examine", "read", "drop"]
    },
    "station_map": {
        "id": "station_map",
        "name": "Station Map",
        "description": "A basic layout map of the Space Station Explorer.",
        "category": "Book",
        "attributes": {
            "content": STATION_MAP_CONTENT
        },
        "actions": ["examine", "read", "drop"]
    },
    
    # --- Healing Items ---
    "medkit": {
        "id": "medkit",
        "name": "Medkit",
        "description": "A standard first aid kit.",
        "category": "Healing",
        "attributes": {"heals": {"limbs": 10, "burn": 10, "poison": 10, "oxygen": 10}},
        "actions": ["examine", "use", "drop"]
    },
    "aloe": {
        "id": "aloe",
        "name": "Aloe",
        "description": "A fleshy aloe leaf from the botany lab. Its gel soothes burns.",
        "category": "Healing",
        "attributes": {},
        "actions": ["examine", "use", "drop"]
    },
}

ALL_ITEMS.update(FOOD_ITEMS)
ALL_ITEMS.update(BOTANY_ITEMS)
ALL_ITEMS.update(CHEMISTRY_ITEMS)
ALL_ITEMS.update(MINING_ITEMS)
ALL_ITEMS.update(WEAPON_ITEMS)

DEFAULT_LOCKER_ITEM_IDS = [
    "welcome_guide",
    "station_map",
    "emergency_rations",
    "basic_tools",
    "medkit",
]


def get_item_definition(item_id):
    """Returns a deep copy of the item definition from the master dictionary."""
    if item_id not in ALL_ITEMS:
        return None
    item = copy.deepcopy(ALL_ITEMS[item_id])
    if item_id == "basic_tools":
        item["attributes"]["contents"] = [copy.deepcopy(ALL_ITEMS[tool_id]) for tool_id in BASIC_TOOLKIT_TOOL_IDS]
    return item


def item_quantity(item):
    """Return quantity for an inventory entry. A held item, or one fresh from its definition, has none: it is 1."""
    return item.get("quantity", 1)


def inventory_item_count(player_data):
    """Total number of items in inventory, summing stack quantities."""
    total = 0
    for item in player_data["inventory"]:
        total += item_quantity(item)
    return total


def format_inventory_label(item):
    """Display name with optional ' x N' when stacked."""
    qty = item_quantity(item)
    return f"{item['name']} x {qty}" if qty > 1 else item["name"]


def _is_non_stackable(item):
    """Container items must not stack - each has its own contents."""
    if item.get("id") in NON_STACKABLE_ITEM_IDS:
        return True
    attrs = item.get("attributes") or {}
    return "contents" in attrs


def stack_into(items, item):
    """Add an item to a list of items, stacking by id when possible.

    Returns the entry that was updated or appended.
    """
    inventory = items
    item_copy = dict(item)
    if "attributes" in item:
        item_copy["attributes"] = copy.deepcopy(item["attributes"])
    add_qty = item_quantity(item_copy)
    item_copy["quantity"] = add_qty
    item_id = item_copy.get("id")

    if item_id and not _is_non_stackable(item_copy):
        for existing in inventory:
            if existing.get("id") == item_id and not _is_non_stackable(existing):
                existing["quantity"] = item_quantity(existing) + add_qty
                return existing

    inventory.append(item_copy)
    return item_copy


def add_to_inventory(player_data, item):
    """Add an item to the inventory. Returns the inventory entry that was updated or appended."""
    return stack_into(player_data["inventory"], item)


def inventory_index(player_data, item_id):
    """The index of the first inventory entry with item_id, or None."""
    return next((index for index, item in enumerate(player_data["inventory"]) if item.get("id") == item_id), None)


def remove_one_from_inventory(player_data, index):
    """Remove one unit from inventory at index. Returns the removed unit dict or None."""
    inventory = player_data["inventory"]
    if not (0 <= index < len(inventory)):
        return None

    entry = inventory[index]
    qty = item_quantity(entry)
    if qty > 1:
        entry["quantity"] = qty - 1
        removed = dict(entry)
        removed["quantity"] = 1
        return removed

    return inventory.pop(index)


def build_default_locker_inventory():
    return [get_item_definition(item_id) for item_id in DEFAULT_LOCKER_ITEM_IDS]


HAND_SIDES = (("left", "Left Hand"), ("right", "Right Hand"))


def item_with_article(item):
    """'a medkit', 'some emergency rations': an item's name in lower case after its article."""
    name = item["name"].lower()
    return f"some {name}" if item.get("plural") else with_article(name)


def held_items(player_data):
    """The items in the player's hands."""
    return [player_data["hands"][side] for side, _ in HAND_SIDES if player_data["hands"][side]]


def holding(player_data, item_id):
    """Whether one of the player's hands holds this item."""
    return any(item["id"] == item_id for item in held_items(player_data))


def carried_or_held(player_data, item_ids):
    """The first item in the inventory or a hand whose id is one of item_ids, or None."""
    for item in player_data["inventory"] + held_items(player_data):
        if item.get("id") in item_ids:
            return item
    return None


def has_tool(player_data, tool_id):
    """Whether the player has a tool to hand: carried, held, or still inside a Basic Tools set they carry."""
    if carried_or_held(player_data, (tool_id,)):
        return True
    toolkit = carried_or_held(player_data, ("basic_tools",))
    return toolkit is not None and any(tool["id"] == tool_id for tool in toolkit["attributes"]["contents"])


def _item_rows(game, keep=lambda item: True):
    """The inventory rows a panel lists: index and label of each item keep() allows."""
    return [{"index": index, "label": format_inventory_label(item)}
            for index, item in enumerate(game.player_data["inventory"]) if keep(item)]


def _item_at(game, index, item_id=None):
    """Inventory entry at index, or None if missing or no longer the expected item."""
    inventory = game.player_data["inventory"]
    if index is None or not (0 <= index < len(inventory)):
        return None
    item = inventory[index]
    if item_id is not None and item.get("id") != item_id:
        return None
    return item


def _selected_item(game, state):
    return _item_at(game, state.get("selected"), state.get("selected_id"))


def _select_item(game, state, args, predicate=None):
    index = int(args["index"])
    item = _item_at(game, index)
    if item is not None and (predicate is None or predicate(item)):
        state["selected"] = index
        state["selected_id"] = item.get("id")


USABLE_ITEM_IDS = ("aloe", "basic_tools", GAS_ANALYZER_ID, TRANSFER_VALVE_ID, BOMB_ID)
ALOE_BURN_RELIEF = 10


def tank_readout(item):
    """The gauge line of a Gas Tank: pressure, temperature and each gas."""
    return gas_mix.readout(item["attributes"]["contents"], GAS_TANK["volume"])


def _heals(item):
    """What a remedy treats: {"limbs" | a damage type | "alcohol": amount}, or None for any other item."""
    return (item.get("attributes") or {}).get("heals")


def heals_text(item):
    """'Burn 30, Limbs 15' for what an item heals, or '' when it heals nothing."""
    return ", ".join(f"{target.title()} {amount}" for target, amount in (_heals(item) or {}).items())


# job -> fn(item) -> the line the job's PDA reads off an inventory item.
ITEM_SCANNERS = {}


def item_scanner(job):
    """Register fn(item) as what the PDA of someone in this job reads off an item."""
    def decorator(fn):
        ITEM_SCANNERS[job] = fn
        return fn
    return decorator


def _offered(item, action):
    """Whether an item's menu offers one of its actions: Use only on items that have a use, and only the valve
    action that changes a Gas Tank's valve."""
    if action == "use":
        return item.get("id") in USABLE_ITEM_IDS or _heals(item) or is_usable_artifact(item)
    if action in ("open_valve", "close_valve"):
        return item["attributes"]["valve_open"] == (action == "close_valve")
    if action in ("set_timer", "disarm"):
        return (item["attributes"]["goes_off_at"] is None) == (action == "set_timer")
    return True


def _other_actions(item):
    """The actions an item's menu offers: those with a handler that _offered allows."""
    return [action for action in item.get("actions", []) if action in _ITEM_ACTION_HANDLERS and _offered(item, action)]


def _is_equippable(item):
    return "equip" in item.get("actions", [])


def _hand_rows(player_data):
    hands = player_data["hands"]
    rows = []
    for side, label in HAND_SIDES:
        held = hands.get(side)
        rows.append({
            "side": side,
            "label": label,
            "held": held["name"] if held else None,
        })
    return rows


def _unequip(game, side):
    """Return a held item from hand back into inventory."""
    hands = game.player_data["hands"]
    item = hands[side]
    if item is None:
        return
    add_to_inventory(game.player_data, item)
    hands[side] = None
    game.add_note(f"Unequipped the {item.get('name', 'item')} from your {side} hand.")


def _equip_to_hand(game, index, item_id, side):
    """Move one inventory unit into the given hand slot. Returns True on success."""
    hands = game.player_data["hands"]
    if side not in hands:
        return False
    if hands.get(side) is not None:
        game.alert(
            "Hand Occupied",
            f"Your {side} hand is already holding something. Unequip it first.",
        )
        return False

    if _item_at(game, index, item_id) is None:
        game.alert("Error", "Invalid item index for equip.", kind="error")
        return False

    removed = remove_one_from_inventory(game.player_data, index)
    removed.pop("quantity", None)
    hands[side] = removed
    game.add_note(f"Equipped the {removed.get('name', 'item')} to your {side} hand.")
    return True


@register_panel("inventory", "Inventory")
def inventory_panel(game, state):
    selected = _selected_item(game, state)
    return {
        "hands": _hand_rows(game.player_data),
        "item_rows": _item_rows(game),
        "selected": state.get("selected") if selected else None,
        "can_examine": selected is not None,
        "can_act": selected is not None and bool(_other_actions(selected)),
        "can_scan": selected is not None and holding(game.player_data, PDA_ID),
    }


@panel_action("inventory")
def select(game, state, args):
    _select_item(game, state, args)


@panel_action("inventory")
def examine(game, state, args):
    item = _selected_item(game, state)
    if item is None:
        game.alert("Error", "Could not identify the selected item.", kind="error")
        return
    item_name = item.get("name", "Unknown Item")
    text = item.get("description", "No description available.")
    if item.get("id") == GAS_TANK_ID:
        tank = gas_mix.pressure(item["attributes"]["contents"], GAS_TANK["volume"])
        text += f" Its gauge reads {tank:.1f} kPa."
    elif item.get("id") == BOMB_ID:
        text += " Its two tanks' gauges read " + " and ".join(
            f"{gas_mix.pressure(mix, GAS_TANK['volume']):.1f} kPa" for mix in item["attributes"]["contents"]) + "."
    game.add_note(f"Examined the {item_name}.")
    game.alert(f"Examine: {item_name}", text)


@panel_action("inventory")
def scan(game, state, args):
    """Read the selected item with the PDA in the player's hand. What it reads depends on their job."""
    item = _selected_item(game, state)
    if item is None or not holding(game.player_data, PDA_ID):
        return
    scanner = ITEM_SCANNERS.get(game.player_data["job"])
    game.alert(f"PDA Scan: {item['name']}", scanner(item) if scanner else NO_SCANNER)


@panel_action("inventory")
def actions(game, state, args):
    item = _selected_item(game, state)
    if item is None:
        game.alert("Error", "Cannot perform actions on this item.", kind="error")
        return
    if not _other_actions(item):
        game.alert("No Actions", f"No special actions available for {item.get('name', 'Item')}.")
        return
    game.open_panel("item_actions", index=state["selected"], item_id=item.get("id"))


@register_panel("item_actions", "Actions")
def item_actions_panel(game, state):
    item = _item_at(game, state["index"], state["item_id"])
    if item is None:
        return None
    return {
        "title": f"Actions: {item.get('name', 'Item')}",
        "actions": [
            {"name": action, "label": action.replace("_", " ").title()} for action in _other_actions(item)
        ],
    }


@panel_action("item_actions")
def item_action(game, state, args):
    item = _item_at(game, state["index"], state["item_id"])
    name = args["name"]
    if item is None or name not in _other_actions(item):
        return
    _ITEM_ACTION_HANDLERS[name](game, state, item)


def _read_item(game, state, item):
    game.add_note(f"Read the {item.get('name', 'Readable Item')}.")
    game.open_panel("read_item", index=state["index"], item_id=state["item_id"])


def _drop_item(game, state, item):
    """Put one of the item down where the player is standing. It stays there until it is picked up."""
    dropped = remove_one_from_inventory(game.player_data, state["index"])
    stack_into(game.floor_here(), dropped)
    game.close_panel("item_actions")
    game.add_note(f"Dropped the {item['name']}.")
    game.alert("Drop", f"You put the {item['name']} down. It will stay here.")


def _drink_item(game, state, item):
    item_name = item.get("name", "drink")
    attributes = item.get("attributes", {})
    alcoholic = attributes.get("alcoholic", False)
    alcohol_content = attributes.get("alcohol_content", 0)

    remove_one_from_inventory(game.player_data, state["index"])
    game.close_panel("item_actions")
    thirst = satisfy(game.player_data, "thirst", attributes.get("quenches", DEFAULT_QUENCHES))

    if alcoholic:
        game.player_data["alcohol_percent"] += alcohol_content
        alc = game.player_data["alcohol_percent"]
        game.add_note(f"Drank the {item_name}. Alcohol is now {alc:.1f}%.")
        game.alert("Drink", f"You finish the {item_name}.\nThirst: {thirst:.0f}%\nAlcohol: {alc:.1f}%")
    else:
        game.add_note(f"Drank the {item_name}.")
        game.alert("Drink", f"You finish the {item_name}.\nThirst: {thirst:.0f}%")


def _eat_item(game, state, item):
    item_name = item.get("name", "food")
    remove_one_from_inventory(game.player_data, state["index"])
    game.close_panel("item_actions")
    hunger = satisfy(game.player_data, "hunger", item.get("attributes", {}).get("feeds", DEFAULT_FEEDS))
    mended = _apply_heals(game.player_data, _heals(item) or {})
    game.add_note(f"Ate the {item_name}.")
    game.alert("Eat", "\n".join([f"You eat the {item_name}.", f"Hunger: {hunger:.0f}%", *mended]))


def _use_item(game, state, item):
    """Use a remedy, aloe, an analysed artifact or the Gas Analyzer, open the transfer valve's panel from a valve or a
    bomb, or open a basic_tools container."""
    if is_usable_artifact(item):
        game.close_panel("item_actions")
        if use_artifact(game, item):
            remove_one_from_inventory(game.player_data, state["index"])
    elif _heals(item):
        _use_remedy(game, state, item)
    elif item["id"] == "aloe":
        _use_aloe(game, state)
    elif item["id"] == GAS_ANALYZER_ID:
        _use_analyzer(game)
    elif item["id"] in (TRANSFER_VALVE_ID, BOMB_ID):
        game.close_panel("item_actions")
        game.open_panel("transfer_valve")
    else:
        uid = item.setdefault("uid", uuid.uuid4().hex)
        game.close_panel("item_actions")
        game.open_panel("basic_tools", uid=uid)


def _apply_heals(player_data, heals):
    """Treat what a remedy's heals cover and return a 'before → after' line for each thing it changed."""
    lines = []
    for target, amount in heals.items():
        if target == "limbs":
            for limb in LIMBS:
                if player_data["limbs"][limb] < 100:
                    before, after = change_limb(player_data, limb, amount)
                    lines.append(f"{limb_label(limb)}: {before}% → {after}%")
        elif target == "alcohol":
            before = player_data["alcohol_percent"]
            if before > 0:
                player_data["alcohol_percent"] = max(0, before - amount)
                lines.append(f"Alcohol: {before:.1f}% → {player_data['alcohol_percent']:.1f}%")
        elif player_data["damage"][target] > 0:
            before, after = reduce_damage(player_data, target, amount)
            lines.append(f"{target.title()}: {before}% → {after}%")
    return lines


def _use_remedy(game, state, item):
    """Treat whatever the remedy heals; it is only used up when it treated something."""
    name = item["name"]
    lines = _apply_heals(game.player_data, _heals(item))
    if not lines:
        game.alert(name, f"You have nothing for the {name.lower()} to treat. It is not needed.")
        return
    remove_one_from_inventory(game.player_data, state["index"])
    game.close_panel("item_actions")
    game.add_note(f"Used {with_article(name.lower())}.")
    game.alert(name, f"You use the {name.lower()}:\n\n" + "\n".join(lines))


def _use_aloe(game, state):
    """Soothe burns by ALOE_BURN_RELIEF; the aloe is kept when there are none."""
    player_data = game.player_data
    if player_data["damage"]["burn"] <= 0:
        game.alert("Aloe", "You have no burns for the aloe to soothe.")
        return
    before, after = reduce_damage(player_data, "burn", ALOE_BURN_RELIEF)
    remove_one_from_inventory(player_data, state["index"])
    game.close_panel("item_actions")
    game.add_note("Used an aloe leaf on your burns.")
    game.alert("Aloe", f"The aloe soothes your burns.\n\nBurn: {before}% → {after}%")


def _use_analyzer(game):
    """Read the station's air, every Gas Tank the player carries or holds, and each tank on a bomb they carry into the
    log."""
    carried = game.player_data["inventory"] + held_items(game.player_data)
    lines = [f"The air here: {gas_mix.readout(game.player_data['atmos']['air'], STATION_AIR['volume'])}"]
    lines += [f"Gas Tank: {tank_readout(item)}" for item in carried if item.get("id") == GAS_TANK_ID]
    lines += [f"Bomb tank {side}: {gas_mix.readout(mix, GAS_TANK['volume'])}"
              for item in carried if item.get("id") == BOMB_ID
              for side, mix in enumerate(item["attributes"]["contents"], 1)]
    game.close_panel("item_actions")
    game.add_note("Read the gas analyzer: " + " ".join(lines))
    game.alert("Gas Analyzer", "\n".join(lines))


def _equip_item(game, state, item):
    game.open_panel("equip_hand", index=state["index"], item_id=state["item_id"])


def _set_valve(open_valve):
    def handler(game, state, item):
        item["attributes"]["valve_open"] = open_valve
        game.close_panel("item_actions")
        game.alert("Gas Tank", "You open the tank's valve. Hold it in a hand to breathe from it." if open_valve
                   else "You close the tank's valve.")
    return handler


_ITEM_ACTION_HANDLERS = {
    "read": _read_item,
    "drop": _drop_item,
    "drink": _drink_item,
    "eat": _eat_item,
    "use": _use_item,
    "equip": _equip_item,
    "open_valve": _set_valve(True),
    "close_valve": _set_valve(False),
}


def item_action(name):
    """Register fn(game, state, item) as the handler of an item action that another module defines."""
    def decorator(fn):
        _ITEM_ACTION_HANDLERS[name] = fn
        return fn
    return decorator


@register_panel("read_item", "Reading")
def read_item_panel(game, state):
    item = _item_at(game, state["index"], state["item_id"])
    if item is None:
        return None
    item_name = item.get("name", "Readable Item")
    return {
        "title": f"Reading: {item_name}",
        "name": item_name,
        "content": item.get("attributes", {}).get("content", "[No content found]"),
        "is_map": item.get("id") == "station_map",
    }


@register_panel("equip_hand", "Equip")
def equip_hand_panel(game, state):
    item = _item_at(game, state["index"], state["item_id"])
    if item is None:
        return None
    item_name = item.get("name", "this item")
    return {"title": f"Equip: {item_name}", "item_name": item_name, "sides": HAND_SIDES}


@panel_action("equip_hand")
def choose(game, state, args):
    game.close_panel("equip_hand")
    if _equip_to_hand(game, state["index"], state["item_id"], args["side"]):
        game.close_panel("item_actions")


@register_panel("hands", "Hands")
def hands_panel(game, state):
    selected = _selected_item(game, state)
    rows = _hand_rows(game.player_data)
    for row in rows:
        row["can_equip"] = row["held"] is None and selected is not None
    return {
        "hands": rows,
        "item_rows": _item_rows(game, _is_equippable),
        "selected": state.get("selected") if selected else None,
    }


@panel_action("hands", "select")
def hands_select(game, state, args):
    _select_item(game, state, args, predicate=_is_equippable)


@panel_action("hands", "equip")
def hands_equip(game, state, args):
    item = _selected_item(game, state)
    if item is None or not _is_equippable(item):
        return
    if _equip_to_hand(game, state["selected"], state["selected_id"], args["side"]):
        state.pop("selected", None)
        state.pop("selected_id", None)


@panel_action("inventory")
@panel_action("hands")
def unequip(game, state, args):
    _unequip(game, args["side"])


def _find_toolkit(game, uid):
    """Return (index, item) of the Basic Tools set with this uid, or (None, None)."""
    for index, item in enumerate(game.player_data["inventory"]):
        if item.get("uid") == uid:
            return index, item
    return None, None


@register_panel("basic_tools", "Basic Tools")
def basic_tools_panel(game, state):
    _, toolkit = _find_toolkit(game, state["uid"])
    if toolkit is None:
        return None
    contents = toolkit["attributes"]["contents"]
    selected = state.get("selected")
    return {
        "contents": [tool["name"] for tool in contents],
        "selected": selected if selected is not None and selected < len(contents) else None,
    }


@panel_action("basic_tools", "select")
def basic_tools_select(game, state, args):
    state["selected"] = int(args["index"])


@panel_action("basic_tools")
def pull_out(game, state, args):
    _, toolkit = _find_toolkit(game, state["uid"])
    if toolkit is None:
        return
    contents = toolkit["attributes"]["contents"]
    if not contents:
        game.alert("Basic Tools", "The set is empty.")
        return
    idx = state.get("selected")
    if idx is None or not (0 <= idx < len(contents)):
        game.alert("Basic Tools", "Select a tool to pull out.")
        return
    tool = contents.pop(idx)
    state.pop("selected", None)
    add_to_inventory(game.player_data, tool)
    game.add_note(f"Pulled the {tool['name']} out of the Basic Tools set.")


def _put_back_candidates(game, contents):
    """Inventory (index, item) tools that fit an empty slot in the set."""
    present_ids = {tool["id"] for tool in contents}
    return [
        (inv_idx, inv_item)
        for inv_idx, inv_item in enumerate(game.player_data["inventory"])
        if inv_item.get("id") in BASIC_TOOLKIT_TOOL_IDS
        and inv_item.get("id") not in present_ids
    ]


@panel_action("basic_tools")
def put_back(game, state, args):
    _, toolkit = _find_toolkit(game, state["uid"])
    if toolkit is None:
        return
    if not _put_back_candidates(game, toolkit["attributes"]["contents"]):
        game.alert(
            "Put Back",
            "No matching tools in your inventory to put back\n"
            "(or those slots are already filled).",
        )
        return
    game.open_panel("put_back_tools", uid=state["uid"])


@register_panel("put_back_tools", "Put Back Tool")
def put_back_tools_panel(game, state):
    _, toolkit = _find_toolkit(game, state["uid"])
    if toolkit is None:
        return None
    candidates = _put_back_candidates(game, toolkit["attributes"]["contents"])
    return {
        "tools": [{"index": idx, "label": format_inventory_label(item)} for idx, item in candidates],
        "selected": state.get("selected"),
    }


@panel_action("put_back_tools", "select")
def put_back_select(game, state, args):
    _select_item(game, state, args)


@panel_action("put_back_tools")
def confirm(game, state, args):
    _, toolkit = _find_toolkit(game, state["uid"])
    if toolkit is None:
        return
    contents = toolkit["attributes"]["contents"]
    if state.get("selected") is None:
        game.alert("Put Back", "Select a tool first.")
        return

    inv_idx, item_id = state["selected"], state.get("selected_id")
    candidate_indices = {idx for idx, _ in _put_back_candidates(game, contents)}
    present_now = {tool["id"] for tool in contents}
    if item_id in present_now:
        game.alert("Put Back", "That tool slot is already filled.")
        game.close_panel("put_back_tools")
        return
    if inv_idx not in candidate_indices or _item_at(game, inv_idx, item_id) is None:
        game.alert("Error", "Inventory changed. Try again.", kind="error")
        game.close_panel("put_back_tools")
        return

    removed = remove_one_from_inventory(game.player_data, inv_idx)
    tool_entry = copy.deepcopy(removed)
    tool_entry.pop("quantity", None)
    contents.append(tool_entry)
    game.add_note(f"Put the {tool_entry['name']} back into the Basic Tools set.")
    game.close_panel("put_back_tools")
