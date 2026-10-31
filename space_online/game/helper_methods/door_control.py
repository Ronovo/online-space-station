from space_online.game.maps.donut import (
    BRIDGE_KEY,
    MEDBAY_KEY,
    SECURITY_KEY,
    ENGINEERING_KEY,
    BAR_KEY,
    BOTANY_KEY,
)

SPECIAL_ROOM_DOORS = {
    BRIDGE_KEY: {
        "room_name": "Bridge",
        "permission": frozenset({"Captain", "HoP"}),
    },
    MEDBAY_KEY: {
        "room_name": "MedBay",
        "permission": frozenset({"Captain", "HoP", "Doctor"}),
    },
    SECURITY_KEY: {
        "room_name": "Security",
        "permission": frozenset({"Captain", "Security"}),
    },
    ENGINEERING_KEY: {
        "room_name": "Engineering Bay",
        "permission": frozenset({"Captain", "HoP", "Engineer"}),
    },
    BAR_KEY: {
        "room_name": "Bar",
        "permission": frozenset({"Captain", "HoP", "Bar"}),
    },
    BOTANY_KEY: {
        "room_name": "Botany Lab",
        "permission": frozenset({"Captain", "HoP", "Botany"}),
    },
}

ACCESS_ERROR = "Unable to access door control system."


def can_control_door(player_data, door_key):
    door = SPECIAL_ROOM_DOORS.get(door_key)
    if not door:
        return False
    return player_data.get("subdepartment", "") in door.get("permission", frozenset())


def is_door_locked(player_data, door_key):  # pragma: no cover - nothing calls this
    return player_data.get("ship_map", {}).get(door_key, {}).get("locked", False)


def toggle_door_lock(game, door_key):
    player_data = game.player_data
    ship_map = player_data.get("ship_map", {})
    if not can_control_door(player_data, door_key) or door_key not in ship_map:
        game.alert("Door Control", ACCESS_ERROR)
        return False

    room_name = SPECIAL_ROOM_DOORS[door_key]["room_name"]
    locked = not ship_map[door_key]["locked"]
    ship_map[door_key]["locked"] = locked
    message = f"The {room_name} door has been {'locked' if locked else 'unlocked'}."

    game.alert("Door Control", message)
    return True
