import random

from space_online.game.helper_methods.mixing import MixingStation, register_mixing_station
from space_online.game.maps.donut import BAR_KEY
from space_online.game.objects.drinks import (
    AVAILABLE_INGREDIENTS,
    DRINKS_MENU,
    MAX_GLASS_POURS,
    MIXED_DRINKS,
    drink_item,
    is_drink_alcoholic,
    mix_drink,
    mixer_shelf,
)
from space_online.game.objects.items import item_scanner
from space_online.game.special_rooms.service import ServiceCounter, ServiceRoom, register_service_menu
from space_online.game.helper_methods.window_stock import window_supply
from space_online.game.special_rooms.service_window import register_window_side
from space_online.game.special_rooms.shared import button, room_action

CONVERSATIONS = [
    "You chat with a group of engineers about the latest station upgrades.",
    "A security officer shares stories about past incidents on the station.",
    "You overhear some interesting gossip about the captain's leadership style.",
    "A doctor tells you about a strange medical case they recently handled.",
    "Several crew members are discussing the latest sports match from Earth.",
    "You find yourself in a philosophical debate about space exploration with a scientist.",
]


@item_scanner("Bartender")
def drink_reading(item):
    """What a drink is mixed from. The things it is mixed from read as themselves."""
    if item.get("category") != "Drink":
        return "Not a drink."
    recipe = MIXED_DRINKS.get(item["name"])
    if recipe is None:
        return f"Plain {item['name']}. Nothing is mixed into it."
    return f"Mixed from {', '.join(recipe['ingredients'])}."


def _drink_categories(basic_drinks, mixed_drinks):
    all_drinks = {**basic_drinks, **mixed_drinks}
    return {
        "All Drinks": all_drinks,
        "Basic Drinks": basic_drinks,
        "Mixed Drinks": mixed_drinks,
        "Alcoholic": {n: d for n, d in all_drinks.items() if is_drink_alcoholic(n, d)},
        "Non-Alcoholic": {n: d for n, d in all_drinks.items() if not is_drink_alcoholic(n, d)},
    }


BAR_COUNTER = register_service_menu(ServiceCounter(
    job="Bartender",
    room=BAR_KEY,
    place="bar",
    noun="drink",
    menu_panel="drink_menu",
    menu_title="Drink Menu",
    stock_key="bar_mixed_stock",
    basics=DRINKS_MENU,
    made=MIXED_DRINKS,
    categories=_drink_categories,
    make_verb="Mix",
    pour="pour",
    poured="Poured",
    build_item=drink_item,
))

MIXER = register_mixing_station(MixingStation(
    panel="mixer",
    title="Bartender's Drink Mixer",
    name="Mixer",
    container="glass",
    container_label="Mixing Glass",
    mix_label="Mix Drink",
    idle_text="Mix ingredients to create a drink",
    capacity=MAX_GLASS_POURS,
    shelf=mixer_shelf,
    mix=mix_drink,
    supplies=(window_supply("bar"),),
    book="recipes",
))

register_window_side(
    "bar",
    job="Bartender",
    place="bar",
    gives=sorted(set(DRINKS_MENU) | set(AVAILABLE_INGREDIENTS)),
    wants=("Celery", "Sugar", "Salt", "Herbs"),
)


class Bar(ServiceRoom):
    ROOM_TITLE = "Bar"
    ROOM_HEADING = "Station Bar"
    ROOM_DESCRIPTION = (
        "The station's bar is lively and well-furnished. A long counter runs along one wall, "
        "with shelves of drinks behind it. Tables and chairs are scattered about, and soft music "
        "plays in the background. A service window opens onto the kitchen next door."
    )
    DOOR_KEY = BAR_KEY
    STATION_ENTRIES = ({"label": "Enter Bartender Station", "mode": ServiceRoom.STATION_MODE},)
    CONTACT_POSTS = {"Bartender": DOOR_KEY}
    COUNTER = BAR_COUNTER
    STATION = MIXER
    WINDOW_SIDE = "bar"
    ORDER_LABEL = "Order Drinks"
    MAKE_LABEL = "Mix Drinks"
    SERVE_LABEL = "Serve Regular Drinks"

    def extra_options(self):
        return [button("Socialize", "room.socialize")]

    @room_action
    def socialize(self):
        self.game.alert("Socializing", random.choice(CONVERSATIONS))
