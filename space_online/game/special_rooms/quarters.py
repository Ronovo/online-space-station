from space_online.game.helper_methods.health_bands import LIMBS, change_limb
from space_online.game.helper_methods.rounds import BED_SECTION
from space_online.game.helper_methods.ui_panels import panel_action, register_panel
from space_online.game.maps.donut import QUARTERS_KEY
from space_online.game.objects.items import (
    add_to_inventory,
    format_inventory_label,
    remove_one_from_inventory,
)
from space_online.game.special_rooms.shared import RoomBase, lighting_chrome, room_action


REST_HEAL_PER_MINUTE = 10
SHUTTLE_BED_HEAL_PER_MINUTE = 30


class Quarters(RoomBase):
    ROOM_TITLE = "Your Quarters"

    def view(self):
        style = lighting_chrome(self.player_data)
        return {
            "type": "quarters",
            "title": self.ROOM_TITLE,
            "heading": "Your Quarters",
            "description": "A small living quarters with basic amenities.",
            "light": style["light"],
            "style": style,
            "name": self.player_data["name"],
            "job": self.player_data["job"],
            "credits": self.player_data["credits"],
            "resting": self.player_data["resting"],
        }

    @room_action
    def bed(self):
        toggle_bed(self.game)

    @room_action
    def storage(self):
        self.game.open_panel("storage_locker")

    @room_action
    def computer(self):
        self.game.open_panel("computer")

    @room_action
    def door(self):
        self.game.leave_room()


def toggle_bed(game):
    """Lie down, or get back up. Resting mends limbs on the master clock."""
    resting = not game.player_data["resting"]
    game.player_data["resting"] = resting
    game.alert("Bed", "You lie down to rest. Your limbs will mend while you stay in bed." if resting
               else "You get out of bed.")


def _bed_heal_per_minute(game):
    """How fast the bed the player is in mends them: the Quarters bed, or the shuttle's Medical bed while no
    fight is on. None when they are in neither."""
    player_data = game.player_data
    round_ = player_data["round"]
    if round_["aboard"]:
        in_bed = round_["section"] == BED_SECTION and not player_data["fight"]
        return SHUTTLE_BED_HEAL_PER_MINUTE if in_bed else None
    return REST_HEAL_PER_MINUTE if game.location_key() == QUARTERS_KEY else None


def tick_rest(game, delta_seconds):
    """Mend every hurt limb of a player resting in a bed, at that bed's rate a minute."""
    player_data = game.player_data
    if not player_data["resting"]:
        return
    rate = _bed_heal_per_minute(game)
    if rate is None:
        player_data["resting"] = False
        return
    timers = player_data["damage_timers"]
    mend = timers.get("rest_acc", 0.0) + rate * delta_seconds / 60
    whole = int(mend)
    timers["rest_acc"] = mend - whole
    if whole:
        for limb in LIMBS:
            change_limb(player_data, limb, whole)


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
    game.player_data["locker_inventory"].insert(0, removed.copy())
    game.add_note(f"Stored {note_name} in locker.")


@register_panel("computer", "Computer Terminal")
def computer_panel(game, state):
    return {}


@panel_action("computer")
def stock_market(game, state, args):
    game.open_panel("stock_market")


@panel_action("computer")
def files(game, state, args):
    game.open_panel("files")
