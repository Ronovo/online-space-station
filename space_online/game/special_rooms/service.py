"""Service rooms: the Bar and the Kitchen.

Both make things at a mixing station into a stock, sell those and their basics from a menu, serve crew
orders from the stock, and pass ingredients to each other through the service window.
"""

import functools
from dataclasses import dataclass
from typing import Callable

from space_online.game.helper_methods.errands import duty_by_id, finish_duty, open_duties, with_article
from space_online.game.helper_methods.mixing import take_from_stock
from space_online.game.helper_methods.ui_panels import panel_action, register_panel
from space_online.game.objects.items import add_to_inventory
from space_online.game.special_rooms.shared import (
    SpecialRoomBase,
    available_npc,
    button,
    npc_contact_widgets,
    room_action,
)


@dataclass(frozen=True)
class ServiceCounter:
    job: str
    room: str
    place: str
    noun: str
    menu_panel: str
    menu_title: str
    stock_key: str
    basics: dict  # always on the menu
    made: dict  # on the menu while in stock
    categories: Callable  # (basics, made items in stock) -> {category: items}
    make_verb: str
    pour: str
    poured: str
    build_item: Callable  # (name, details) -> inventory item


def _menu_categories(counter, player_data):
    stock = player_data[counter.stock_key]
    in_stock = {name: counter.made[name] for name, qty in stock.items() if qty > 0 and name in counter.made}
    return counter.categories(dict(counter.basics), in_stock)


def _menu_category(counter, game, state):
    categories = _menu_categories(counter, game.player_data)
    return state.get("category", next(iter(categories))), categories


def _menu_items(counter, game, state):
    category, categories = _menu_category(counter, game, state)
    return categories.get(category, {})


def _on_the_house(counter, player_data):
    """Whoever holds the counter's job eats and drinks free at it."""
    return player_data["job"] == counter.job


def _menu_context(counter, game, state):
    stock = game.player_data[counter.stock_key]
    category, categories = _menu_category(counter, game, state)
    items = categories.get(category, {})
    free = _on_the_house(counter, game.player_data)
    rows = []
    for name, details in items.items():
        price = "free" if free else f"{details['price']} credits"
        quantity = f" (Qty: {stock.get(name, 0)})" if name in counter.made else ""
        rows.append({"name": name, "label": f"{name}{quantity} - {price}"})

    selected = state.get("selected")
    if selected not in items:
        selected = None
    return {
        "labels": counter,
        "credits": game.player_data["credits"],
        "categories": list(categories),
        "category": category,
        "rows": rows,
        "selected": selected,
        "description": items[selected]["desc"] if selected else f"Select a {counter.noun} to see its description",
    }


def _menu_pick_category(counter, game, state, args):
    if args["name"] in _menu_categories(counter, game.player_data):
        state["category"] = args["name"]
        state.pop("selected", None)


def _menu_select(counter, game, state, args):
    if args["name"] in _menu_items(counter, game, state):
        state["selected"] = args["name"]


def _menu_order(counter, game, state, args):
    player_data = game.player_data
    name = state.get("selected")
    details = _menu_items(counter, game, state).get(name)
    if not details:
        game.alert("Selection Needed", f"Please select a {counter.noun} first")
        return

    price = 0 if _on_the_house(counter, player_data) else details["price"]
    if player_data["credits"] < price:
        game.alert("Insufficient Credits", f"You don't have enough credits to order {name}.")
        return

    if name in counter.made:
        stock = player_data[counter.stock_key]
        take_from_stock(stock, name)
        if name not in stock:
            state.pop("selected", None)

    player_data["credits"] -= price
    add_to_inventory(player_data, counter.build_item(name, details))

    if not price:
        game.add_note(f"{counter.poured} {with_article(name)} on the house. Added to inventory.")
        game.alert("Order Successful", f"You {counter.pour} yourself {with_article(name)} on the house. "
                                       f"It has been added to your inventory.")
        return
    game.add_note(f"Purchased {name} at the {counter.place} for {price} credits. Added to inventory.")
    game.alert(
        "Order Successful",
        f"You've ordered {with_article(name)} for {price} credits. It has been added to your inventory.",
    )


def register_service_menu(counter):
    register_panel(counter.menu_panel, counter.menu_title, template="service_menu")(
        functools.partial(_menu_context, counter))
    for name, action in (("category", _menu_pick_category), ("select", _menu_select), ("order", _menu_order)):
        panel_action(counter.menu_panel, name)(functools.partial(action, counter))
    return counter


def _orders(counter, player_data):
    """The crew orders waiting to be served at this counter."""
    return open_duties(player_data, ("serve",), counter.room)


class ServiceRoom(SpecialRoomBase):
    COUNTER = None
    STATION = None
    STATION_MODE = "service_station"
    WINDOW_SIDE = ""
    ORDER_LABEL = ""
    MAKE_LABEL = ""
    SERVE_LABEL = ""

    def extra_options(self):
        return []

    def station_extras(self):
        return []

    def room_options(self):
        counter = self.COUNTER
        widgets = npc_contact_widgets(
            self.game,
            counter.job,
            self.DOOR_KEY,
            talk_label=self.ORDER_LABEL,
            talk_action="show_menu",
            absent_flavor=f"The {counter.job.lower()} is away from the {counter.place}.",
        )
        return widgets + self.extra_options() + self.back_to_station_menu()

    def mode_buttons(self, mode):
        if mode != self.STATION_MODE or not self.station_allowed(mode):
            return None
        widgets = [
            button(self.MAKE_LABEL, "room.show_mixer"),
            button("View Recipes", "room.show_recipes"),
            button(self.SERVE_LABEL, "room.show_menu"),
            button("Service Window", "room.show_window"),
            *self.station_extras(),
        ]
        widgets += [button(f"Serve {order['item']} to {order['patron']}", "room.serve_order", duty_id=order["id"])
                    for order in _orders(self.COUNTER, self.player_data)]
        return widgets + [button("Back to Station Menu", "room.set_mode", mode="menu")]

    @room_action
    def show_menu(self):
        """Order from the menu (the counter's NPC present) or serve from it (at the station)."""
        if available_npc(self.game, self.COUNTER.job, self.DOOR_KEY) or self.station_allowed(self.STATION_MODE):
            self.game.open_panel(self.COUNTER.menu_panel)

    @room_action(station=STATION_MODE)
    def show_mixer(self):
        self.game.open_panel(self.STATION.panel)

    @room_action(station=STATION_MODE)
    def show_recipes(self):
        self.game.open_panel(self.STATION.book)

    @room_action(station=STATION_MODE)
    def show_window(self):
        self.game.open_panel("service_window", side=self.WINDOW_SIDE)

    @room_action(station=STATION_MODE)
    def serve_order(self, duty_id):
        """Serve a crew order from the stock, for the item's price."""
        counter = self.COUNTER
        order = duty_by_id(self.player_data, duty_id)
        if order not in _orders(counter, self.player_data):
            return
        name, patron, reward = order["item"], order["patron"], order["reward"]
        stock = self.player_data[counter.stock_key]
        if stock.get(name, 0) <= 0:
            self.game.alert("Not in Stock", f"There's no {name} ready. {counter.make_verb} one first.")
            return
        take_from_stock(stock, name)
        finish_duty(self.game, order, f"Served {with_article(name)} to {patron} for {reward} credits.",
                    f"You serve {patron} {with_article(name)}. They pay you {reward} credits.", reward)
