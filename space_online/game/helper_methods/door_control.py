from space_online.game.maps.donut import ROOMS

ACCESS_ERROR = "Unable to access door control system."


def can_control_door(player_data, door_key):
    room = ROOMS.get(door_key)
    return room is not None and player_data.get("subdepartment", "") in room.access


def toggle_door_lock(game, door_key):
    player_data = game.player_data
    ship_map = player_data["ship_map"]
    if not can_control_door(player_data, door_key):
        game.alert("Door Control", ACCESS_ERROR)
        return False

    locked = not ship_map[door_key]["locked"]
    ship_map[door_key]["locked"] = locked
    game.alert("Door Control", f"The {ROOMS[door_key].name} door has been {'locked' if locked else 'unlocked'}.")
    return True
