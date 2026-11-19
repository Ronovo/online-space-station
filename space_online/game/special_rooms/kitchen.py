from space_online.game.helper_methods.mixing import MixingStation, Supply, register_mixing_station
from space_online.game.maps.donut import KITCHEN_KEY
from space_online.game.objects.dishes import (
    DISHES,
    FOOD_MENU,
    MAX_PAN_INGREDIENTS,
    PANTRY_INGREDIENTS,
    cook_dish,
    stove_shelf,
)
from space_online.game.helper_methods.needs import DEFAULT_FEEDS
from space_online.game.objects.items import heals_text, item_scanner
from space_online.game.special_rooms.service import ServiceCounter, ServiceRoom, register_service_menu
from space_online.game.helper_methods.window_stock import window_supply
from space_online.game.special_rooms.service_window import register_window_side
from space_online.game.special_rooms.shared import button, room_action, send_produce_to_kitchen


# How much of the player's hunger a cooked dish and a ready-made basic take away.
DISH_FEEDS = 70
BASIC_FEEDS = 35


@item_scanner("Chef")
def edible_reading(item):
    """Whether an item can be eaten, and what eating it does."""
    if "eat" not in item.get("actions", []):
        return "Not edible."
    reading = f"Edible. Feeds {item['attributes'].get('feeds', DEFAULT_FEEDS)}% of your hunger."
    mends = heals_text(item)
    return f"{reading} Mends: {mends}." if mends else reading


def _food_categories(basics, dishes):
    return {"All Food": {**basics, **dishes}, "Basics": basics, "Dishes": dishes}


def _food_item(name, details):
    return {
        "id": f"dish_{name.lower().replace(' ', '_')}",
        "name": name,
        "description": details["desc"],
        "category": "Food",
        "attributes": {"feeds": DISH_FEEDS if name in DISHES else BASIC_FEEDS},
        "actions": ["examine", "eat", "drop"],
    }


KITCHEN_COUNTER = register_service_menu(ServiceCounter(
    job="Chef",
    room=KITCHEN_KEY,
    place="kitchen",
    noun="dish",
    menu_panel="food_menu",
    menu_title="Food Menu",
    stock_key="kitchen_stock",
    basics=FOOD_MENU,
    made=DISHES,
    categories=_food_categories,
    make_verb="Cook",
    pour="plate",
    poured="Plated",
    build_item=_food_item,
))


def _use_produce(game, name):
    game.player_data["stores"]["produce"][name] -= 1


STOVE = register_mixing_station(MixingStation(
    panel="stove",
    title="Chef's Stove",
    name="Stove",
    container="pan",
    container_label="Pan",
    mix_label="Cook Dish",
    idle_text="Add ingredients to the pan and cook a dish",
    capacity=MAX_PAN_INGREDIENTS,
    shelf=stove_shelf,
    mix=cook_dish,
    supplies=(
        window_supply("kitchen"),
        Supply(key="Botany", heading="From the Botany Lab",
               counts=lambda game: game.player_data["stores"]["produce"], take=_use_produce),
    ),
    book="kitchen_recipes",
))

register_window_side(
    "kitchen",
    job="Chef",
    place="kitchen",
    gives=PANTRY_INGREDIENTS,
    wants=("Beer", "Wine", "Rum", "Brandy"),
)


class Kitchen(ServiceRoom):
    ROOM_TITLE = "Kitchen"
    ROOM_HEADING = "Station Kitchen"
    ROOM_DESCRIPTION = (
        "The station's kitchen is all steel counters and hanging pans. A stove hisses in the corner, "
        "the pantry shelves are stacked to the ceiling, and a service window opens onto the bar next door."
    )
    DOOR_KEY = KITCHEN_KEY
    STATION_ENTRIES = ({"label": "Enter Chef Station", "mode": ServiceRoom.STATION_MODE},)
    CONTACT_POSTS = {"Chef": DOOR_KEY}
    COUNTER = KITCHEN_COUNTER
    STATION = STOVE
    WINDOW_SIDE = "kitchen"
    ORDER_LABEL = "Order Food"
    MAKE_LABEL = "Cook Dishes"
    SERVE_LABEL = "Serve Food"

    def station_extras(self):
        return [button("Stock the Kitchen", "room.stock_kitchen")]

    @room_action(station=ServiceRoom.STATION_MODE)
    def stock_kitchen(self):
        """Send the produce the player carries to the kitchen's stores, for the stove."""
        send_produce_to_kitchen(self.game)
