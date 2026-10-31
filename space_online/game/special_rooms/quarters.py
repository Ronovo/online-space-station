from space_online.game.helper_methods.ui_panels import choice_handler, panel_action, register_panel
from space_online.game.objects.items import (
    add_to_inventory,
    format_inventory_label,
    remove_one_from_inventory,
)
from space_online.game.special_rooms.shared import SpecialRoomBase, room_action, room_lighting_chrome


class Quarters:
    ROOM_TITLE = "Your Quarters"

    def __init__(self, game):
        self.game = game
        self.player_data = game.player_data

    def view(self):
        style = room_lighting_chrome(self.player_data)
        return {
            "type": "quarters",
            "title": self.ROOM_TITLE,
            "heading": "Your Quarters",
            "description": "A small living quarters with basic amenities." + style["power_desc"],
            "style": style,
            "name": self.player_data["name"],
            "job": self.player_data["job"],
            "credits": self.player_data["credits"],
        }

    perform = SpecialRoomBase.perform

    @room_action
    def bed(self):
        self.game.ask(
            "Bed",
            "Would you like to save your game?",
            [("Yes", "save_game", {}), ("No", None, None)],
        )

    @room_action
    def storage(self):
        self.game.open_panel("storage_locker")

    @room_action
    def computer(self):
        self.game.open_panel("computer")

    @room_action
    def door(self):
        self.game.leave_room()



@choice_handler("save_game")
def save_game(game):
    # Progress is written to the database after every action; the bed just confirms it.
    game.alert("Game Saved", "Your game has been saved successfully.")


@register_panel("storage_locker", "Storage Locker")
def storage_locker_panel(game, state):
    return {
        "locker": [
            {
                "label": format_inventory_label(item),
                "description": item.get("description", ""),
            }
            for item in game.player_data["locker_inventory"]
        ],
        "inventory": [
            {"label": format_inventory_label(item)}
            for item in game.player_data["inventory"]
        ],
    }


def _item_note_name(item):
    return item["name"] + (f" ({item['id']})" if item.get("id") else "")


@panel_action("storage_locker")
def take(game, state, args):
    locker_inventory = game.player_data["locker_inventory"]
    locker_index = int(args["index"])
    if not (0 <= locker_index < len(locker_inventory)):
        game.alert("Error", "Invalid locker item.", kind="error")
        return

    taken_item = locker_inventory.pop(locker_index)
    add_to_inventory(game.player_data, taken_item)
    game.add_note(f"Took {_item_note_name(taken_item)} from locker.")


@panel_action("storage_locker")
def store(game, state, args):
    item_index = int(args["index"])
    if not (0 <= item_index < len(game.player_data.get("inventory", []))):
        game.alert("Error", "Invalid item index.", kind="error")
        return

    note_name = _item_note_name(game.player_data["inventory"][item_index])
    removed = remove_one_from_inventory(game.player_data, item_index)
    if removed is None:  # pragma: no cover - can't fail once the index was checked above
        game.alert("Error", "Could not store the item.", kind="error")
        return

    game.player_data["locker_inventory"].insert(0, removed.copy())
    game.add_note(f"Stored {note_name} in locker.")


@register_panel("computer", "Computer Terminal")
def computer_panel(game, state):
    return {}


@panel_action("computer")
def stock_market(game, state, args):
    game.open_panel("stock_market")
