import random

from space_online.game.objects.drinks import DRINKS_MENU, MIXED_DRINKS, is_drink_alcoholic
from space_online.game.objects.items import add_to_inventory
from space_online.game.special_rooms.shared import (
    SpecialRoomBase,
    available_npc,
    button,
    npc_contact_widgets,
    room_action,
)
from space_online.game.helper_methods.ui_panels import panel_action, register_panel
from space_online.game.maps.donut import BAR_KEY

DRINK_MENU_CATEGORIES = ("All Drinks", "Basic Drinks", "Mixed Drinks", "Alcoholic", "Non-Alcoholic")

CONVERSATIONS = [
    "You chat with a group of engineers about the latest station upgrades.",
    "A security officer shares stories about past incidents on the station.",
    "You overhear some interesting gossip about the captain's leadership style.",
    "A doctor tells you about a strange medical case they recently handled.",
    "Several crew members are discussing the latest sports match from Earth.",
    "You find yourself in a philosophical debate about space exploration with a scientist.",
]


class Bar(SpecialRoomBase):
    ROOM_TITLE = "Bar"
    ROOM_HEADING = "Station Bar"
    ROOM_DESCRIPTION = (
        "The station's bar is lively and well-furnished. A long counter runs along one wall, "
        "with shelves of drinks behind it. Tables and chairs are scattered about, and soft music "
        "plays in the background."
    )
    DOOR_KEY = BAR_KEY
    STATION_ENTRIES = ({"label": "Enter Bartender Station", "mode": "bartender"},)
    CONTACT_JOBS = ("Bartender",)

    def room_options(self):
        widgets = npc_contact_widgets(
            self.game,
            "Bartender",
            talk_label="Order Drinks",
            talk_action="show_drink_menu",
            absent_flavor="The bartender is away from the bar.",
        )
        widgets.append(button("Socialize", "room.socialize"))
        return widgets + self.back_to_station_menu()

    def mode_buttons(self, mode):
        if mode != "bartender" or not self.station_allowed(mode):
            return None
        return [
            button("Mix Drinks", "room.show_drink_mixer"),
            button("View Recipes", "room.show_recipes"),
            button("Serve Regular Drinks", "room.show_drink_menu"),
            button("Back to Station Menu", "room.set_mode", mode="menu"),
        ]

    @room_action
    def show_drink_menu(self):
        """Order from the menu (bartender NPC present) or serve it (bartender station)."""
        if available_npc(self.game, "Bartender") or self.station_allowed("bartender"):
            self.game.open_panel("drink_menu")

    @room_action
    def socialize(self):
        self.game.alert("Socializing", random.choice(CONVERSATIONS))

    @room_action(station="bartender")
    def show_drink_mixer(self):
        self.game.open_panel("mixer")

    @room_action(station="bartender")
    def show_recipes(self):
        self.game.open_panel("recipes")


def _drink_categories(player_data):
    stock = player_data["bar_mixed_stock"]
    basic_drinks = dict(DRINKS_MENU)
    mixed_drinks = {
        name: MIXED_DRINKS[name]
        for name, qty in stock.items()
        if qty > 0 and name in MIXED_DRINKS
    }
    all_drinks = {**basic_drinks, **mixed_drinks}
    return {
        "All Drinks": all_drinks,
        "Basic Drinks": basic_drinks,
        "Mixed Drinks": mixed_drinks,
        "Alcoholic": {n: d for n, d in all_drinks.items() if is_drink_alcoholic(n, d)},
        "Non-Alcoholic": {n: d for n, d in all_drinks.items() if not is_drink_alcoholic(n, d)},
    }


def _current_drinks(game, state):
    category = state.get("category", "All Drinks")
    return _drink_categories(game.player_data).get(category, {})


@register_panel("drink_menu", "Drink Menu")
def drink_menu_panel(game, state):
    stock = game.player_data["bar_mixed_stock"]
    drinks = _current_drinks(game, state)
    rows = []
    for drink, details in drinks.items():
        if drink in MIXED_DRINKS:
            label = f"{drink} (Qty: {stock.get(drink, 0)}) - {details['price']} credits"
        else:
            label = f"{drink} - {details['price']} credits"
        rows.append({"name": drink, "label": label})

    selected = state.get("selected")
    if selected not in drinks:
        selected = None
    return {
        "credits": game.player_data["credits"],
        "categories": DRINK_MENU_CATEGORIES,
        "category": state.get("category", "All Drinks"),
        "drinks": rows,
        "selected": selected,
        "description": drinks[selected]["desc"] if selected else "Select a drink to see its description",
    }


@panel_action("drink_menu", "category")
def drink_menu_category(game, state, args):
    if args["name"] in DRINK_MENU_CATEGORIES:
        state["category"] = args["name"]
        state.pop("selected", None)


@panel_action("drink_menu", "select")
def drink_menu_select(game, state, args):
    if args["name"] in _current_drinks(game, state):
        state["selected"] = args["name"]


@panel_action("drink_menu")
def order(game, state, args):
    player_data = game.player_data
    drink_name = state.get("selected")
    drink_details = _current_drinks(game, state).get(drink_name)
    if not drink_details:
        game.alert("Selection Needed", "Please select a drink first")
        return

    stock = player_data["bar_mixed_stock"]
    if drink_name in MIXED_DRINKS and stock.get(drink_name, 0) <= 0:  # pragma: no cover - a mixed drink with no stock isn't on the menu
        game.alert(
            "Out of Stock",
            f"{drink_name} is not available. Mix one at the bartender station first.",
        )
        return

    if player_data["credits"] < drink_details["price"]:
        game.alert("Insufficient Credits", f"You don't have enough credits to order {drink_name}.")
        return

    if drink_name in MIXED_DRINKS:
        stock[drink_name] -= 1
        if stock[drink_name] <= 0:
            del stock[drink_name]
            state.pop("selected", None)

    player_data["credits"] -= drink_details["price"]

    alcoholic = is_drink_alcoholic(drink_name, drink_details)
    add_to_inventory(player_data, {
        "id": f"drink_{drink_name.lower().replace(' ', '_')}",
        "name": drink_name,
        "description": drink_details["desc"],
        "category": "Drink",
        "attributes": {
            "alcoholic": alcoholic,
            "alcohol_content": drink_details.get("alcohol_content", 0),
        },
        "actions": ["examine", "drink", "drop"],
    })

    game.add_note(
        f"Purchased {drink_name} at the bar for {drink_details['price']} credits. Added to inventory."
    )
    game.alert(
        "Order Successful",
        f"You've ordered a {drink_name} for {drink_details['price']} credits. "
        f"It has been added to your inventory.",
    )
