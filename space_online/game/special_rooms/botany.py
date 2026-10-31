from space_online.game.helper_methods.game_clock import format_elapsed, get_elapsed_seconds
from space_online.game.helper_methods.ui_panels import choice_handler, panel_action, register_panel
from space_online.game.maps.donut import BOTANY_KEY
from space_online.game.objects.botany_items import (
    BOTANY_SEED_IDS,
    BOTANY_VEND_IDS,
    GROWTH_STAGES,
    MIRACLE_GROW_SPEED_BONUS,
    PLANTERS_PER_ROW,
    PLANTER_ROWS,
    PLENTIFUL_HARVEST_YIELD_MULTIPLIER,
    empty_planter,
    growth_seconds_to_next_stage,
    growth_stage_label,
    refresh_planter_growth,
)
from space_online.game.objects.items import (
    HAND_SIDES,
    add_to_inventory,
    format_inventory_label,
    get_item_definition,
)
from space_online.game.special_rooms.shared import (
    SpecialRoomBase,
    button,
    npc_contact_widgets,
    room_action,
    text_line,
)

# Consumed from the hand on a single successful application.
LIQUID_CONSUMABLE_IDS = {"miracle_grow", "plentiful_harvest", "the_ooze_mutagen"}

# Reusable tools that clear a planter; each maps to a growth_class predicate
# for which plants they're allowed to clear.
TOOL_GROWTH_CLASS_RULES = {
    "trowel": lambda growth_class: growth_class != "tree",
    "chainsaw": lambda growth_class: growth_class == "tree",
}

VEND_FILTERS = (("all", "All"), ("seed", "Seeds"), ("liquid", "Liquids"), ("tool", "Tools"))


class Botany(SpecialRoomBase):
    ROOM_TITLE = "Botany Lab"
    ROOM_HEADING = "Station Botany Lab"
    ROOM_DESCRIPTION = (
        "The botany lab is filled with plants of all varieties. Hydroponic systems line the walls, "
        "and bright grow lights illuminate rows of planters. The air is humid and smells of fresh "
        "soil and vegetation."
    )
    DOOR_KEY = BOTANY_KEY
    STATION_ENTRIES = ({"label": "Enter Botany Station", "mode": "botany_station"},)
    CONTACT_JOBS = ("Botanist",)

    def room_options(self):
        widgets = [button("View Plants", "room.view_plants")]
        widgets += npc_contact_widgets(
            self.game,
            "Botanist",
            talk_label="Talk to Botanist",
            talk_action="talk_to_botanist",
            absent_flavor="The botanist is away from the lab.",
        )
        return widgets + self.back_to_station_menu()

    def mode_buttons(self, mode):
        if mode != "botany_station" or not self.station_allowed(mode):
            return None
        return [
            text_line("Botany Station Controls", style="title"),
            button("Botany Vending Machine", "room.access_botany_vending"),
            button("View Plants", "room.view_plants_station"),
            button("Back to Station Menu", "room.set_mode", mode="menu"),
        ]

    @room_action
    def talk_to_botanist(self):
        self.game.alert("Botanist", "The botanist continues tending to the plants without looking up.")

    @room_action
    def view_plants(self):
        self.game.open_panel("planter_rows", allow_harvest=False)

    @room_action(station="botany_station")
    def view_plants_station(self):
        self.game.open_panel("planter_rows", allow_harvest=True)

    @room_action(station="botany_station")
    def access_botany_vending(self):
        self.game.open_panel("botany_vending")


@register_panel("planter_rows", "View Plants")
def planter_rows_panel(game, state):
    return {"rows": range(PLANTER_ROWS)}


@panel_action("planter_rows")
def choose_row(game, state, args):
    row = int(args["row"])
    if 0 <= row < PLANTER_ROWS:
        game.replace_panel("planter_row", row=row, allow_harvest=state["allow_harvest"])


def _planter_card(planter, index, elapsed_seconds, allow_harvest):
    card = {
        "index": index,
        "title": f"Planter {index + 1}: {planter['plant']}" if planter["occupied"] else f"Planter {index + 1}: Empty",
        "occupied": planter["occupied"],
        "buffs": [],
        "can_harvest": False,
    }
    if not planter.get("occupied"):
        card.update(stage="Status: Empty", stage_color="white", time="This planter is ready for seeds.", time_color="gray")
        return card

    growth_stage = refresh_planter_growth(planter, elapsed_seconds)
    if (planter.get("miracle_grow") or 0.0) > 0:
        card["buffs"].append(("Miracle Grow", "#90EE90"))
    if int(planter.get("yield_multiplier") or 1) > 1:
        card["buffs"].append(("Plentiful Harvest", "#FFD700"))
    if planter.get("ooze_applied"):
        card["buffs"].append(("The Ooze", "#7CFC00"))

    if planter.get("dead"):
        card.update(
            stage="Status: Dead", stage_color="red",
            time="Needs to be cleared with a Trowel or Chainsaw.", time_color="red",
        )
        return card

    needs_water = growth_stage < GROWTH_STAGES and not planter.get("watered")
    card.update(
        stage=(
            f"Stage: {growth_stage_label(growth_stage)} ({growth_stage}/{GROWTH_STAGES})"
            + (" - needs water" if needs_water else "")
        ),
        stage_color="orange" if needs_water else "white",
    )
    if growth_stage >= GROWTH_STAGES:
        card.update(time="Ready to harvest", time_color="lightgreen", can_harvest=allow_harvest)
    else:
        next_in = growth_seconds_to_next_stage(
            planter.get("planted_at_seconds"),
            planter.get("growth_class"),
            elapsed_seconds,
            planter.get("miracle_grow") or 0.0,
        )
        card.update(time=f"Next stage in {format_elapsed(next_in)}", time_color="cyan")
    return card


@register_panel("planter_row", "Viewing Plants")
def planter_row_panel(game, state):
    row = state["row"]
    allow_harvest = state["allow_harvest"]
    planters = game.player_data["botany"]["planters"]
    elapsed_seconds = get_elapsed_seconds(game.player_data)
    start = row * PLANTERS_PER_ROW

    hand_buttons = []
    if allow_harvest:
        hands = game.player_data["hands"]
        for side, label in HAND_SIDES:
            held = hands.get(side)
            hand_buttons.append({
                "side": side,
                "label": f"Use {held.get('name', 'Item')}" if isinstance(held, dict) else f"Use {label}",
            })

    return {
        "title": f"Viewing Plants - Row {row + 1}",
        "row_number": row + 1,
        "cards": [
            _planter_card(planters[i], i, elapsed_seconds, allow_harvest)
            for i in range(start, start + PLANTERS_PER_ROW)
        ],
        "hand_buttons": hand_buttons,
    }


@panel_action("planter_row")
def back(game, state, args):
    game.replace_panel("planter_rows", allow_harvest=state["allow_harvest"])


@panel_action("planter_row", "hands")
def open_hands(game, state, args):
    game.open_panel("hands")


def _row_planter(game, state, args):
    """(index, planter) for a planter in this panel's row, or (None, None)."""
    index = int(args["index"])
    start = state["row"] * PLANTERS_PER_ROW
    if not (start <= index < start + PLANTERS_PER_ROW):
        return None, None
    return index, game.player_data["botany"]["planters"][index]


@panel_action("planter_row")
def harvest(game, state, args):
    """Harvest a mature planter into inventory and clear it (station View Plants only)."""
    if not state["allow_harvest"]:
        return
    planter_index, planter = _row_planter(game, state, args)
    if planter is None or not planter.get("occupied") or planter.get("dead"):
        return

    growth_stage = refresh_planter_growth(planter, get_elapsed_seconds(game.player_data))
    if growth_stage < GROWTH_STAGES:
        game.alert("Not Ready", f"Planter {planter_index + 1} is not ready to harvest yet.")
        return

    produces_id = planter.get("produces")

    produce = get_item_definition(produces_id) if produces_id else None
    if not produce:  # pragma: no cover - every seed produces a known item
        game.alert("Harvest Failed", "Could not resolve the produce for this plant.", kind="error")
        return

    yield_multiplier = max(1, int(planter.get("yield_multiplier") or 1))
    produce["quantity"] = yield_multiplier
    add_to_inventory(game.player_data, produce)
    plant_name = planter.get("plant") or produce.get("name", "produce")
    game.player_data["botany"]["planters"][planter_index] = empty_planter()
    game.add_note(
        f"Harvested {yield_multiplier}x {produce.get('name', plant_name)} from planter {planter_index + 1}."
    )


@panel_action("planter_row")
def use_hand(game, state, args):
    """Apply whatever is held in a hand to a planter."""
    if not state["allow_harvest"]:
        return
    planter_index, planter = _row_planter(game, state, args)
    if planter is None:
        return
    hand_side = args["side"]
    hands = game.player_data["hands"]
    if hand_side not in hands:
        return
    item = hands.get(hand_side)
    if not isinstance(item, dict):
        game.alert("Empty Hand", f"Your {hand_side} hand is empty.")
        return

    planters = game.player_data["botany"]["planters"]
    item_id = item.get("id")
    item_name = item.get("name", "item")

    if item_id in BOTANY_SEED_IDS:
        if planter.get("occupied"):
            game.alert(
                "Planter Occupied",
                f"Planter {planter_index + 1} already has a plant in it. Choose an empty planter.",
            )
            return

        attrs = item.get("attributes") or {}
        planters[planter_index] = {
            **empty_planter(),
            "occupied": True,
            "plant": attrs.get("plant_name") or item_name,
            "seed_id": item_id,
            "produces": attrs.get("produces"),
            "growth_class": attrs.get("growth_class") or "crop",
            "planted_at_seconds": get_elapsed_seconds(game.player_data),
            "growth_stage": 1,
        }
        hands[hand_side] = None
        game.add_note(f"Planted {item_name} in planter {planter_index + 1} using your {hand_side} hand.")
        return

    if not planter.get("occupied"):
        game.alert("Nothing Planted", "There is nothing planted in this planter.")
        return

    if item_id == "watering_can" or item_id in LIQUID_CONSUMABLE_IDS:
        if planter.get("dead"):
            game.alert(
                "Plant Dead",
                "This plant has died. It needs to be cleared with a Trowel or Chainsaw.",
            )
            return

    if item_id == "watering_can":
        planter["watered"] = True
        game.add_note(f"Watered planter {planter_index + 1}.")
        return

    if item_id in LIQUID_CONSUMABLE_IDS:
        if item_id == "miracle_grow":
            planter["miracle_grow"] = MIRACLE_GROW_SPEED_BONUS
            game.add_note(f"Applied Miracle Grow to planter {planter_index + 1}.")
        elif item_id == "plentiful_harvest":
            planter["yield_multiplier"] = PLENTIFUL_HARVEST_YIELD_MULTIPLIER
            game.add_note(f"Applied Plentiful Harvest to planter {planter_index + 1}.")
        else:
            planter["ooze_applied"] = True
            game.add_note(f'Applied "The Ooze" Mutagen to planter {planter_index + 1}.')
            game.alert("Mutation", "The Plant does not mutate.")
        hands[hand_side] = None
        return

    if item_id in TOOL_GROWTH_CLASS_RULES:
        if not TOOL_GROWTH_CLASS_RULES[item_id](planter.get("growth_class")):
            wrong_hint = "Use a Chainsaw on trees." if item_id == "trowel" else "Use a Trowel on non-tree plants."
            game.alert("Wrong Tool", f"The {item_name} can't clear this plant. {wrong_hint}")
            return

        game.ask(
            "Clear Planter",
            f"Clear planter {planter_index + 1} with the {item_name}? The plant will be lost.",
            [
                ("Yes", "clear_planter", {"index": planter_index, "item_name": item_name}),
                ("No", None, None),
            ],
        )
        return

    game.alert("Cannot Use", f"The {item_name} can't be used on planters.")


@choice_handler("clear_planter")
def clear_planter(game, index, item_name):
    planters = game.player_data["botany"]["planters"]
    if 0 <= index < len(planters):
        planters[index] = empty_planter()
        game.add_note(f"Cleared planter {index + 1} with the {item_name}.")


@register_panel("botany_vending", "Botany Vending Machine")
def botany_vending_panel(game, state):
    kind = state.get("filter", "all")
    available = []
    for item_id in BOTANY_VEND_IDS:
        item = get_item_definition(item_id)
        if not item:  # pragma: no cover - every vended id is in the item data
            continue
        vend_kinds = (item.get("attributes") or {}).get("vend_kinds") or []
        if kind == "all" or kind in vend_kinds:
            available.append({"id": item_id, "name": item["name"]})
    return {
        "filters": VEND_FILTERS,
        "filter": kind,
        "available": available,
        "owned": [
            format_inventory_label(item)
            for item in game.player_data["inventory"]
            if isinstance(item, dict) and item.get("id") in BOTANY_VEND_IDS
        ],
    }


@panel_action("botany_vending", "filter")
def vending_filter(game, state, args):
    if args["kind"] in dict(VEND_FILTERS):
        state["filter"] = args["kind"]


@panel_action("botany_vending", "get")
def get_vending_item(game, state, args):
    """Get an item from the botany vending machine into inventory."""
    item_id = args["item_id"]
    item = get_item_definition(item_id) if item_id in BOTANY_VEND_IDS else None
    if not item:
        return
    add_to_inventory(game.player_data, item)
    game.add_note(f"Acquired {item['name']} from the botany vending machine.")
