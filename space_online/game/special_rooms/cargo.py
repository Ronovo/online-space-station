"""The Cargo Bay: the Quartermaster's order console, the crew's public Order Console, the supply counter, and the
export counter.

player_data["cargo"] (see stores.new_cargo) holds the orders on their way, the crew's requests, and what has docked.
"""

import random
import uuid

from space_online.game.helper_methods.artifacts import EXPORT_VALUE, is_usable_artifact
from space_online.game.helper_methods.atmos import CANISTER_SLOTS, move_canister, new_canister
from space_online.game.helper_methods.errands import duty_by_id, finish_duty, open_duties, with_article
from space_online.game.helper_methods.game_clock import format_elapsed, get_elapsed_seconds
from space_online.game.helper_methods.jail import set_warrant
from space_online.game.helper_methods.npc_movement import player_holds_post, post_holder
from space_online.game.helper_methods.stores import add_to_stores, store_of
from space_online.game.helper_methods.ui_panels import current_feedback, panel_action, register_panel, set_feedback
from space_online.game.maps.donut import CARGO_KEY, ROOMS
from space_online.game.objects.food import MUTANT_OF, MUTANT_PRODUCE
from space_online.game.objects.items import add_to_inventory, get_item_definition, item_quantity, item_scanner
from space_online.game.objects.mining_items import ORE_VALUES
from space_online.game.special_rooms.shared import (
    SpecialRoomBase,
    available_npc,
    button,
    npc_contact_widgets,
    register_stand,
    room_action,
    text_line,
    unavailable_text,
)

QUARTERMASTER = "Quartermaster"
QUARTERMASTER_AWAY = "The quartermaster is away from the bay."
CARGO_DELIVERY_SECONDS = 90
# The NPC Quartermaster answers a crew member's request this many game seconds after it is put in.
REQUEST_DECISION_SECONDS_RANGE = (30, 60)
# From a person's third dangerous gas order in a shift, each one may put a warrant out for them.
DANGEROUS_ORDERS_ALLOWED = 2
ORDER_ALERT_CHANCE = 0.5
STOCKPILING = "Stockpiling dangerous gas"
COUNTER_MARKUP = 2
# What the Quartermaster pays Central Command for supplies at the order console.
ORDER_PRICES = {
    "snack": 5,
    "energy_bar": 8,
    "emergency_rations": 15,
    "medkit": 40,
    "fire_extinguisher": 25,
    "repair_tool": 30,
    "basic_tools": 50,
    "watering_can": 25,
    "miracle_grow": 30,
    "pickaxe": 40,
}
# What the Quartermaster pays for a full canister of each dangerous gas, which comes down the tube to Atmospherics.
CANISTER_PRICES = {"Plasma": 150, "Hydrogen": 100, "Nitrous Oxide": 80}
QUARTERMASTER_PRICES = {**ORDER_PRICES, **CANISTER_PRICES}
# What the Quartermaster charges the rest of the crew: supplies over the counter, and anything at the Order Console.
COUNTER_PRICES = {item_id: price * COUNTER_MARKUP for item_id, price in ORDER_PRICES.items()}
REQUEST_PRICES = {item: price * COUNTER_MARKUP for item, price in QUARTERMASTER_PRICES.items()}
PRODUCE_EXPORT_VALUE = 10
MUTANT_EXPORT_VALUE = 60
EXPORT_VALUES = {
    **ORE_VALUES,
    **{item_id: PRODUCE_EXPORT_VALUE for item_id in MUTANT_OF},
    **{item_id: MUTANT_EXPORT_VALUE for item_id in MUTANT_PRODUCE},
}

register_stand("supply_counter", "Supply Counter", "The quartermaster sells supplies from the bay's shelves.",
               COUNTER_PRICES, "the Quartermaster")


def export_value(item):
    """What the export counter pays for one of an item, or 0 for something it doesn't take."""
    if is_usable_artifact(item):
        return EXPORT_VALUE
    return EXPORT_VALUES.get(item.get("id"), 0)


@item_scanner("Quartermaster")
def price_reading(item):
    """What Central Command sells an item for, what the counter charges, and what the export counter pays."""
    prices = []
    if item.get("id") in ORDER_PRICES:
        prices.append(f"Orders for {ORDER_PRICES[item['id']]} credits.")
        prices.append(f"Sells over the counter for {COUNTER_PRICES[item['id']]} credits.")
    if export_value(item):
        prices.append(f"Exports for {export_value(item)} credits.")
    return " ".join(prices) or "Central Command neither sells nor buys this."


NOTHING_TO_EXPORT = "You have nothing the export counter takes. It buys ore, produce and analysed artifacts."


def exports_carried(player_data):
    """{item name: count} of what the player carries that the export counter takes."""
    counts = {}
    for item in player_data["inventory"]:
        if export_value(item):
            counts[item["name"]] = counts.get(item["name"], 0) + item_quantity(item)
    return counts


def sell_exports(game, name=None):
    """Sell what the player carries that the export counter takes: everything, or only the items called name. Ore
    goes up to the station stores."""
    player_data = game.player_data
    sold = [item for item in player_data["inventory"] if export_value(item) and name in (None, item["name"])]
    if not sold:
        game.alert("Export Counter", NOTHING_TO_EXPORT)
        return
    total = sum(export_value(item) * item_quantity(item) for item in sold)
    listed = ", ".join(f"{item_quantity(item)} {item['name']}" for item in sold)
    for item in sold:
        if store_of(item["id"]) == "ore":
            add_to_stores(player_data, item["id"], item_quantity(item))
    player_data["inventory"][:] = [item for item in player_data["inventory"]
                                   if not any(item is gone for gone in sold)]
    player_data["credits"] += total
    game.add_note(f"Sold {listed} at the export counter for {total} credits.")
    game.alert("Export Counter", f"You sell {listed} for {total} credits.")


def goods_name(item):
    """What Central Command calls a supply, by item id, or a canister of gas, by gas."""
    return f"Canister of {item}" if item in CANISTER_PRICES else get_item_definition(item)["name"]


def _goods(prices):
    return [{"id": item, "name": goods_name(item), "price": price} for item, price in prices.items()]


def place_order(game, item, price, request_id=None):
    """Charge the player price and order item from Central Command. A canister of dangerous gas goes on record."""
    player_data = game.player_data
    cargo = player_data["cargo"]
    player_data["credits"] -= price
    order = {"item": item, "arrives_at": get_elapsed_seconds(player_data) + CARGO_DELIVERY_SECONDS}
    if request_id:
        order["request"] = request_id
    if item in CANISTER_PRICES:
        cargo["gas_orders"] += 1
        order["number"] = CANISTER_SLOTS + cargo["gas_orders"]
        _record_gas_order(game, item)
    cargo["orders"].append(order)
    game.add_note(f"Ordered {with_article(goods_name(item))} from Central Command for {price} credits.")


def _record_gas_order(game, gas):
    """Write a dangerous gas order into the Incident Log. Past DANGEROUS_ORDERS_ALLOWED in a shift, it may put a
    warrant out for the buyer."""
    player_data = game.player_data
    name = player_data["name"]
    player_data["incidents"].append({"at": get_elapsed_seconds(player_data), "where": ROOMS[CARGO_KEY].name,
                                     "what": f"{name} ordered a canister of {gas} from Central Command.",
                                     "away": None})
    if (player_data["cargo"]["gas_orders"] <= DANGEROUS_ORDERS_ALLOWED or player_data["warrant"]
            or random.random() >= ORDER_ALERT_CHANCE):
        return
    set_warrant(player_data, STOCKPILING)
    if player_data["job"] == "Security Guard":
        game.page("Warrant", f"{name} is wanted: {STOCKPILING}.")


def quartermaster_absence(game):
    """Why the crew's requests wait on the Quartermaster, or None while an NPC Quartermaster works the Cargo Bay."""
    if available_npc(game, QUARTERMASTER, CARGO_KEY):
        return None
    npc = post_holder(game.station_crew, QUARTERMASTER, CARGO_KEY)
    if npc is None:
        return "Nobody holds the Quartermaster's post."
    return unavailable_text(game, npc, QUARTERMASTER, CARGO_KEY) or QUARTERMASTER_AWAY


def _answer_requests(game):
    """The NPC Quartermaster answers every request that is due while they can work the Cargo Bay: ordered when the
    requester can pay, denied when they can't, on the log and the PDA."""
    player_data = game.player_data
    elapsed = get_elapsed_seconds(player_data)
    due = [request for request in player_data["cargo"]["requests"]
           if request["status"] == "waiting" and elapsed >= request["decide_at"]]
    if not due or quartermaster_absence(game):
        return
    for request in due:
        name, price = with_article(goods_name(request["item"])), request["price"]
        if player_data["credits"] < price:
            request.update(status="denied", reason=f"you can't pay the {price} credits it costs")
            message = f"The Quartermaster denied your request for {name}: {request['reason']}."
        else:
            request["status"] = "ordered"
            place_order(game, request["item"], price, request["id"])
            message = (f"The Quartermaster approved your request for {name} and charged you {price} credits. It "
                       f"docks at the Cargo Bay in {format_elapsed(CARGO_DELIVERY_SECONDS)}.")
        game.alert(QUARTERMASTER, message)
        game.page(QUARTERMASTER, message)


def _unload(cargo, order):
    """Put a docked order where it waits: a canister for the tube to Atmospherics, a crew request for its requester,
    and anything else for the Quartermaster."""
    item, request_id = order["item"], order.get("request")
    if request_id:
        cargo["requests"] = [request for request in cargo["requests"] if request["id"] != request_id]
    if item in CANISTER_PRICES:
        cargo["canisters"].append(new_canister(order["number"], {item: 1.0}))
    elif request_id:
        cargo["pickups"].append(item)
    else:
        cargo["arrived"].append(item)


def _dock_orders(game):
    cargo = game.player_data["cargo"]
    elapsed = get_elapsed_seconds(game.player_data)
    due = [order for order in cargo["orders"] if elapsed >= order["arrives_at"]]
    if not due:
        return
    cargo["orders"] = [order for order in cargo["orders"] if order not in due]
    for order in due:
        _unload(cargo, order)
    names = ", ".join(goods_name(order["item"]) for order in due)
    game.announce("Cargo Bay", f"A supply pod has docked at the Cargo Bay with {names}.")


def _send_canisters(game):
    """Send the canisters waiting at the Cargo Bay down the tube into free slots on the Atmospherics Canister Rack."""
    held = game.player_data["cargo"]["canisters"]
    for index, canister in enumerate(held):
        free = move_canister(held, index, game.player_data["atmos"]["canisters"])
        if free is None:
            break
        game.announce("Atmospherics", f"{canister['label']} comes down the tube from the Cargo Bay into slot "
                                      f"{free + 1} of the Canister Rack.")
    held[:] = [canister for canister in held if canister]


def tick_cargo(game):
    """Let the Quartermaster answer the crew's requests, dock every order whose supply pod has arrived, and send
    docked canisters on to Atmospherics."""
    _answer_requests(game)
    _dock_orders(game)
    _send_canisters(game)


class Cargo(SpecialRoomBase):
    ROOM_TITLE = "Cargo Bay"
    ROOM_HEADING = "Station Cargo Bay"
    ROOM_DESCRIPTION = (
        "The cargo bay is stacked to the ceiling with crates. A conveyor runs to the pod dock at the far end, "
        "and a counter by the door does a steady trade."
    )
    DOOR_KEY = CARGO_KEY
    STATION_ENTRIES = ({"label": "Enter Cargo Station", "mode": "cargo_station"},)
    CONTACT_POSTS = {"Quartermaster": DOOR_KEY}

    @property
    def cargo(self):
        return self.player_data["cargo"]

    def room_options(self):
        widgets = npc_contact_widgets(
            self.game,
            QUARTERMASTER,
            self.DOOR_KEY,
            talk_label="Buy Supplies",
            talk_action="buy_supplies",
            absent_flavor=QUARTERMASTER_AWAY,
        )
        if not player_holds_post(self.player_data, QUARTERMASTER):
            pickups = self.cargo["pickups"]
            widgets.append(button("Order Console", "room.show_order_request"))
            if pickups:
                widgets.append(button(f"Collect Your Order ({len(pickups)})", "room.collect_order"))
        widgets += self.back_to_station_menu()
        if available_npc(self.game, QUARTERMASTER, self.DOOR_KEY):
            widgets += self.export_counter()
        return widgets

    def export_counter(self):
        """A sell button for each kind of thing carried that the counter takes, then Sell All. It comes last in the
        menu because its length changes with what is carried."""
        carried = exports_carried(self.player_data)
        if not carried:
            return [text_line("Export Counter", style="title"), text_line(NOTHING_TO_EXPORT, style="italic")]
        return [text_line("Export Counter", style="title"),
                *(button(f"Sell {count} {name}", "room.sell_export", name=name) for name, count in carried.items()),
                button("Sell All", "room.sell_exports")]

    def mode_buttons(self, mode):
        if mode != "cargo_station" or not self.station_allowed(mode):
            return None
        return [
            text_line("Cargo Station", style="title"),
            text_line(f"Orders on the way: {len(self.cargo['orders'])}", style="italic"),
            button("Order Supplies", "room.show_orders"),
            button(f"Collect Deliveries ({len(self.cargo['arrived'])})", "room.collect_deliveries"),
            button("Back to Station Menu", "room.set_mode", mode="menu"),
            *self.export_counter(),
        ]

    @room_action
    def buy_supplies(self):
        if available_npc(self.game, QUARTERMASTER, self.DOOR_KEY):
            self.game.open_panel("supply_counter")

    @room_action
    def sell_exports(self):
        if available_npc(self.game, QUARTERMASTER, self.DOOR_KEY) or self.station_allowed("cargo_station"):
            sell_exports(self.game)

    @room_action
    def sell_export(self, name):
        if available_npc(self.game, QUARTERMASTER, self.DOOR_KEY) or self.station_allowed("cargo_station"):
            sell_exports(self.game, name)

    @room_action(station="cargo_station")
    def show_orders(self):
        self.game.open_panel("cargo_orders")

    @room_action
    def show_order_request(self):
        if not player_holds_post(self.player_data, QUARTERMASTER):
            self.game.open_panel("order_request")

    def _take_off_conveyor(self, key):
        """Hand over everything in cargo[key] that has docked."""
        items = self.cargo[key]
        if not items:
            self.game.alert("Cargo Bay", "Nothing has docked yet.")
            return
        names = ", ".join(get_item_definition(item_id)["name"] for item_id in items)
        for item_id in items:
            add_to_inventory(self.player_data, get_item_definition(item_id))
        self.cargo[key] = []
        self.add_note(f"Collected {names} from the Cargo Bay.")
        self.game.alert("Cargo Bay", f"You take {names} off the conveyor.")

    @room_action(station="cargo_station")
    def collect_deliveries(self):
        self._take_off_conveyor("arrived")

    @room_action
    def collect_order(self):
        self._take_off_conveyor("pickups")


def _held_canisters(cargo):
    return [f"{canister['label']} waits at the Cargo Bay. Clear a slot on the Atmospherics Canister Rack and it goes "
            "down the tube." for canister in cargo["canisters"]]


def _supply_duties(player_data):
    """The crew's Supply Requests on a Quartermaster's board."""
    return [duty for duty in open_duties(player_data, ("deliver",)) if duty["item"] in ORDER_PRICES]


@register_panel("cargo_orders", "Order Console")
def cargo_orders_panel(game, state):
    cargo = game.player_data["cargo"]
    elapsed = get_elapsed_seconds(game.player_data)
    return {
        "credits": game.player_data["credits"],
        "minutes": format_elapsed(CARGO_DELIVERY_SECONDS),
        "goods": _goods(QUARTERMASTER_PRICES),
        "orders": [{"name": goods_name(order["item"]),
                    "left": format_elapsed(order["arrives_at"] - elapsed)} for order in cargo["orders"]],
        "requests": [{"id": duty["id"], "text": f"The {duty['giver']} needs {duty['label']} ({duty['reward']} cr)",
                      "price": ORDER_PRICES[duty["item"]], "approved": bool(duty.get("approved"))}
                     for duty in _supply_duties(game.player_data)],
        "held": _held_canisters(cargo),
        "feedback": current_feedback(state),
    }


def _order(game, state, item):
    """Order item at the Quartermaster's price. Returns whether it was ordered."""
    name, price = with_article(goods_name(item)), QUARTERMASTER_PRICES[item]
    if game.player_data["credits"] < price:
        set_feedback(state, f"You don't have the {price} credits {name} costs.", "orange")
        return False
    place_order(game, item, price)
    set_feedback(state, f"Ordered {name}. Its supply pod docks in {format_elapsed(CARGO_DELIVERY_SECONDS)}.")
    return True


@panel_action("cargo_orders")
def order(game, state, args):
    if args["item_id"] in QUARTERMASTER_PRICES:
        _order(game, state, args["item_id"])


def _open_supply_request(game, args):
    """The Supply Request duty args names, while it is still waiting on an answer, or None."""
    duty = duty_by_id(game.player_data, args.get("duty_id"))
    return duty if duty in _supply_duties(game.player_data) and not duty.get("approved") else None


@panel_action("cargo_orders")
def approve(game, state, args):
    """Order what a Supply Request asks for. The duty stays on the board until it is delivered."""
    duty = _open_supply_request(game, args)
    if duty is not None and _order(game, state, duty["item"]):
        duty["approved"] = True


@panel_action("cargo_orders")
def deny(game, state, args):
    """Turn a Supply Request down, which takes it off the board as a duty done."""
    duty = _open_supply_request(game, args)
    if duty is not None:
        finish_duty(game, duty, f"Denied the {duty['giver']}'s request for {duty['label']}.",
                    f"You deny the {duty['giver']}'s request for {duty['label']}.")


def _request_status(request, orders, elapsed):
    if request["status"] == "waiting":
        return "Waiting on the Quartermaster"
    if request["status"] == "denied":
        return f"Denied: {request['reason']}"
    order = next(order for order in orders if order.get("request") == request["id"])
    return f"On its way, docks in {format_elapsed(order['arrives_at'] - elapsed)}"


@register_panel("order_request", "Order Console")
def order_request_panel(game, state):
    """The crew's Order Console: a request for anything Central Command sells, which the Quartermaster answers."""
    player_data = game.player_data
    if player_holds_post(player_data, QUARTERMASTER):
        return None
    cargo = player_data["cargo"]
    elapsed = get_elapsed_seconds(player_data)
    waiting = any(request["status"] == "waiting" for request in cargo["requests"])
    return {
        "credits": player_data["credits"],
        "minutes": format_elapsed(CARGO_DELIVERY_SECONDS),
        "goods": _goods(REQUEST_PRICES),
        "requests": [{"name": goods_name(request["item"]),
                      "status": _request_status(request, cargo["orders"], elapsed)} for request in cargo["requests"]]
                    + [{"name": goods_name(item), "status": "Ready to collect at the Cargo Bay"}
                       for item in cargo["pickups"]],
        "absent": quartermaster_absence(game) if waiting else None,
        "held": _held_canisters(cargo),
        "feedback": current_feedback(state),
    }


@panel_action("order_request", "request")
def request_supply(game, state, args):
    item = args["item_id"]
    if item not in REQUEST_PRICES:
        return
    player_data = game.player_data
    price = REQUEST_PRICES[item]
    player_data["cargo"]["requests"].append({
        "id": uuid.uuid4().hex[:12],
        "item": item,
        "requester": player_data["name"],
        "price": price,
        "decide_at": get_elapsed_seconds(player_data) + random.randint(*REQUEST_DECISION_SECONDS_RANGE),
        "status": "waiting",
    })
    set_feedback(state, f"Requested {with_article(goods_name(item))} for {price} credits. The Quartermaster answers "
                        "on your PDA.")
