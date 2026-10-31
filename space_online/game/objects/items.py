
import copy
from space_online.game.helper_methods.health_bands import DAMAGE_TYPES, LIMBS, change_limb, limb_label, reduce_damage
import uuid

from space_online.game.helper_methods.ui_panels import choice_handler, panel_action, register_panel
from space_online.game.maps.donut import render_map_text
from space_online.game.objects.botany_items import BOTANY_ITEMS
from space_online.game.objects.food import FOOD_ITEMS

# Tool IDs that fit inside a Basic Tools set (one of each).
BASIC_TOOLKIT_TOOL_IDS = ("wrench", "screwdriver", "wirecutters")
NON_STACKABLE_ITEM_IDS = frozenset({"basic_tools"})

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
     "basic_tools": {
        "id": "basic_tools",
        "name": "Basic Tools",
        "description": "A set containing a small wrench, screwdriver, and wirecutters.",
        "category": "Tool",
        "attributes": {},
        "actions": ["examine", "use", "drop"]
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
        "attributes": {},
        "actions": ["examine", "use", "drop"]
    },
}

ALL_ITEMS.update(FOOD_ITEMS)
ALL_ITEMS.update(BOTANY_ITEMS)

DEFAULT_LOCKER_ITEM_IDS = [
    "welcome_guide",
    "station_map",
    "emergency_rations",
    "basic_tools",
    "medkit",
]


def _default_basic_tools_contents():
    """Fresh copies of the tools that ship inside a Basic Tools set."""
    contents = []
    for tool_id in BASIC_TOOLKIT_TOOL_IDS:
        if tool_id in ALL_ITEMS:  # pragma: no branch - every Basic Tools tool is in the item data
            contents.append(copy.deepcopy(ALL_ITEMS[tool_id]))
    return contents


def get_item_definition(item_id):
    """Returns a deep copy of the item definition from the master dictionary."""
    if item_id not in ALL_ITEMS:
        return None
    item = copy.deepcopy(ALL_ITEMS[item_id])
    if item_id == "basic_tools":
        attrs = item.setdefault("attributes", {})
        if "contents" not in attrs:  # pragma: no branch - the item data's Basic Tools never lists its contents
            attrs["contents"] = _default_basic_tools_contents()
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


def add_to_inventory(player_data, item):
    """Add an item to inventory, stacking by id when possible.

    Returns the inventory entry that was updated or appended.
    """
    inventory = player_data["inventory"]
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


USABLE_ITEM_IDS = ("medkit", "basic_tools")


def _other_actions(item):
    """The actions an item's menu offers: those with a handler, and Use only on items that have a use."""
    return [action for action in item.get("actions", [])
            if action in _ITEM_ACTION_HANDLERS and (action != "use" or item.get("id") in USABLE_ITEM_IDS)]


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
    if removed is None:  # pragma: no cover - can't fail once _item_at has found the item
        game.alert("Error", "Could not equip that item.", kind="error")
        return False

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
    game.add_note(f"Examined the {item_name}.")
    game.alert(f"Examine: {item_name}", item.get("description", "No description available."))


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
            {"name": action, "label": action.capitalize()} for action in _other_actions(item)
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
    game.ask(
        "Confirm Drop",
        f"Are you sure you want to drop the {item.get('name', 'item')}? It will be gone forever!",
        [("Yes", "drop_item", {"index": state["index"], "item_id": state["item_id"]}), ("No", None, None)],
    )


@choice_handler("drop_item")
def drop_item_confirmed(game, index, item_id):
    item = _item_at(game, index, item_id)
    if item is None:
        return
    remove_one_from_inventory(game.player_data, index)
    game.close_panel("item_actions")
    game.add_note(f"Dropped the {item.get('name', 'item')}.")


def _drink_item(game, state, item):
    item_name = item.get("name", "drink")
    attributes = item.get("attributes", {})
    alcoholic = attributes.get("alcoholic", False)
    alcohol_content = attributes.get("alcohol_content", 0)

    remove_one_from_inventory(game.player_data, state["index"])
    game.close_panel("item_actions")

    if alcoholic:
        game.player_data["alcohol_percent"] += alcohol_content
        alc = game.player_data["alcohol_percent"]
        game.add_note(f"Drank the {item_name}. Alcohol is now {alc:.1f}%.")
        game.alert("Drink", f"You finish the {item_name}.\nAlcohol: {alc:.1f}%")
    else:
        game.add_note(f"Drank the {item_name}.")
        game.alert("Drink", f"You finish the {item_name}.")


def _eat_item(game, state, item):
    item_name = item.get("name", "food")
    remove_one_from_inventory(game.player_data, state["index"])
    game.close_panel("item_actions")
    game.add_note(f"Ate the {item_name}.")
    game.alert("Eat", f"You eat the {item_name}.")


def _use_item(game, state, item):
    """Use a medkit, or open a basic_tools container (the USABLE_ITEM_IDS)."""
    if item["id"] == "medkit":
        _use_medkit(game, state)
    else:
        uid = item.setdefault("uid", uuid.uuid4().hex)
        game.close_panel("item_actions")
        game.open_panel("basic_tools", uid=uid)


def _use_medkit(game, state):
    """Heal injured limbs (+10%) and positive burn/poison/oxygen (-10%); consume on success."""
    player_data = game.player_data
    injured_limbs = [limb for limb in LIMBS if player_data["limbs"][limb] < 100]
    injured_damage = [key for key in DAMAGE_TYPES if player_data["damage"][key] > 0]

    if not injured_limbs and not injured_damage:
        game.alert("Medkit", "You are already at full health. The medkit is not needed.")
        return

    summary_lines = []
    for limb in injured_limbs:
        before, after = change_limb(player_data, limb, 10)
        summary_lines.append(f"{limb_label(limb)}: {before}% → {after}%")
    for key in injured_damage:
        before, after = reduce_damage(player_data, key, 10)
        summary_lines.append(f"{key.title()}: {before}% → {after}%")

    remove_one_from_inventory(game.player_data, state["index"])
    game.close_panel("item_actions")
    game.add_note("Used a medkit.")
    game.alert("Medkit", "You use the medkit:\n\n" + "\n".join(summary_lines))


def _equip_item(game, state, item):
    game.open_panel("equip_hand", index=state["index"], item_id=state["item_id"])


_ITEM_ACTION_HANDLERS = {
    "read": _read_item,
    "drop": _drop_item,
    "drink": _drink_item,
    "eat": _eat_item,
    "use": _use_item,
    "equip": _equip_item,
}


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
    if selected is not None and not _is_equippable(selected):  # pragma: no cover - the hands panel only ever selects equippable items
        selected = None
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


def _tool_name(tool):
    return tool["name"]


@register_panel("basic_tools", "Basic Tools")
def basic_tools_panel(game, state):
    _, toolkit = _find_toolkit(game, state["uid"])
    if toolkit is None:
        return None
    contents = toolkit["attributes"]["contents"]
    selected = state.get("selected")
    return {
        "contents": [_tool_name(tool) for tool in contents],
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
    game.add_note(f"Pulled the {_tool_name(tool)} out of the Basic Tools set.")


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
    game.add_note(f"Put the {_tool_name(tool_entry)} back into the Basic Tools set.")
    game.close_panel("put_back_tools")
