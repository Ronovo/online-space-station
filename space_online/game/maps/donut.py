"""
The "Donut" station layout: a hollow square ring of hallways with special
rooms sprouting off of it (Bridge, MedBay, Security, Engineering, Bar,
Botany), plus the player's Quarters attached at the hallway junction.
"""

# --- Special room coordinate keys ---
QUARTERS_KEY = "-1,0"
BRIDGE_KEY = "6,0"
MEDBAY_KEY = "0,6"
SECURITY_KEY = "6,6"
ENGINEERING_KEY = "6,3"
BAR_KEY = "-1,3"
BOTANY_KEY = "3,-1"

# Where a new game (or a player who somehow loses their location) starts.
QUARTERS_LOCATION = {"x": -1, "y": 0}


# Map keys are "x,y" strings; locations are {"x", "y"} dicts; tiles are (x, y) tuples.
def tile_key(x, y):
    return f"{x},{y}"


def location_key(location):
    return tile_key(location.get("x"), location.get("y"))


def location_from_key(key):
    x, y = key.split(",")
    return {"x": int(x), "y": int(y)}


def location_from_tile(tile):
    return {"x": tile[0], "y": tile[1]}


# How x and y change for a step in each direction, and where each direction's button sits in a 3x3 nav grid.
DIRECTION_STEPS = {"north": (1, 0), "south": (-1, 0), "east": (0, 1), "west": (0, -1)}
DIRECTION_GRID = {"north": (0, 1), "south": (2, 1), "east": (1, 2), "west": (1, 0)}

# --- Ship map: every tile's name/description/lock state ---
SHIP_MAP = {
    QUARTERS_KEY: {"name": "Quarters", "desc": "Your personal quarters on the station."},
    "0,0": {"name": "Hallway Junction", "desc": "A junction in the hallway. Your quarters are nearby."},
    "1,0": {"name": "North Hallway", "desc": "A long hallway stretching north."},
    "2,0": {"name": "North Hallway", "desc": "A long hallway stretching north."},
    "3,0": {"name": "North Hallway", "desc": "A long hallway stretching north. You notice a door labeled 'Botany Lab' on the west wall."},
    "4,0": {"name": "North Hallway", "desc": "A long hallway stretching north."},
    "5,0": {"name": "North End", "desc": "The northern end of the hallway. The bridge is nearby."},
    "0,1": {"name": "East Hallway", "desc": "A long hallway stretching east."},
    "0,2": {"name": "East Hallway", "desc": "A long hallway stretching east."},
    "0,3": {"name": "Bar Entrance", "desc": "This hallway leads to the station Bar. Soft music can be heard from inside."},
    "0,4": {"name": "East Hallway", "desc": "A long hallway stretching east."},
    "0,5": {"name": "East End", "desc": "The eastern end of the hallway. The medbay is nearby."},

    "5,1": {"name": "Northeast Hallway", "desc": "A hallway connecting the north and east corridors."},
    "5,2": {"name": "Northeast Hallway", "desc": "A hallway connecting the north and east corridors."},
    "5,3": {"name": "Engineering Bay Entrance", "desc": "This hallway leads to the Engineering Bay."},
    "5,4": {"name": "Northeast Hallway", "desc": "A hallway connecting the north and east corridors."},
    "5,5": {"name": "Northeast Corner", "desc": "The far corner of the station. Security is nearby."},

    "4,5": {"name": "East Section", "desc": "A hallway along the eastern side of the station."},
    "3,5": {"name": "East Section", "desc": "A hallway along the eastern side of the station."},
    "2,5": {"name": "East Section", "desc": "A hallway along the eastern side of the station."},
    "1,5": {"name": "East Section", "desc": "A hallway connecting back to the main hallways."},

    BRIDGE_KEY: {"name": "Bridge", "locked": False},
    MEDBAY_KEY: {"name": "MedBay", "locked": False},
    SECURITY_KEY: {"name": "Security", "locked": False},
    ENGINEERING_KEY: {"name": "Engineering Bay", "locked": False},
    BAR_KEY: {"name": "Bar", "locked": False},
    BOTANY_KEY: {"name": "Botany Lab", "locked": False},
}

# Which "x,y" tiles are special-room doors, and what the room is called.
SPECIAL_ROOM_TILES = {
    BRIDGE_KEY: "Bridge",
    MEDBAY_KEY: "MedBay",
    SECURITY_KEY: "Security",
    ENGINEERING_KEY: "Engineering",
    BAR_KEY: "Bar",
    BOTANY_KEY: "Botany",
    QUARTERS_KEY: "Quarters",
}

# Which hallway tile sits directly in front of each special room's door.
SPECIAL_ROOM_HALLWAY = {
    BRIDGE_KEY: (5, 0),
    MEDBAY_KEY: (0, 5),
    SECURITY_KEY: (5, 5),
    ENGINEERING_KEY: (5, 3),
    BAR_KEY: (0, 3),
    BOTANY_KEY: (3, 0),
    QUARTERS_KEY: (0, 0),
}

# Each room's door button on the nav grid of the hallway tile in front of it: its label and (row, col). A door
# always takes a grid cell whose direction is closed on that tile.
ROOM_DOOR_BUTTONS = {
    BRIDGE_KEY: ("Bridge", (0, 1)),
    MEDBAY_KEY: ("MedBay", (1, 2)),
    SECURITY_KEY: ("Security", (0, 1)),
    ENGINEERING_KEY: ("Engineering Bay", (0, 1)),
    BAR_KEY: ("Bar", (2, 1)),
    BOTANY_KEY: ("Botany Lab", (1, 0)),
    QUARTERS_KEY: ("Quarters", (3, 1)),
}


def hallway_neighbors(x, y):
    """The hallway tiles one step from (x, y), by direction. Room doors are entered with a button, not walked to."""
    neighbors = {}
    for direction, (dx, dy) in DIRECTION_STEPS.items():
        key = tile_key(x + dx, y + dy)
        if key in SHIP_MAP and key not in SPECIAL_ROOM_TILES:
            neighbors[direction] = (x + dx, y + dy)
    return neighbors


def get_available_directions(x, y):  # pragma: no cover - nothing calls this
    """Which of north/south/east/west lead to another hallway tile."""
    neighbors = hallway_neighbors(x, y)
    return {direction: direction in neighbors for direction in DIRECTION_STEPS}


# --- Text map rendering ---
_CELL_WIDTH = 12


def render_map_text():
    """Build a readable text version of the map.

    Hallway tiles are drawn as a plain line; special rooms (and Quarters)
    are drawn with their name. Tiles that aren't part of the station are
    left blank, which is what leaves the hollow "donut hole" in the middle.
    """
    xs = []
    ys = []
    for key in SHIP_MAP:
        location = location_from_key(key)
        xs.append(location["x"])
        ys.append(location["y"])

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    lines = ["SPACE STATION EXPLORER - STATION MAP", ""]

    # North (higher x) at the top, east (higher y) to the right, to match the
    # "X North, Y East" location readout shown in the hallway view.
    for x in range(max_x, min_x - 1, -1):
        row_cells = []
        for y in range(min_y, max_y + 1):
            key = tile_key(x, y)
            if key not in SHIP_MAP:
                cell = ""
            else:
                room_name = SPECIAL_ROOM_TILES.get(key)
                cell = room_name if room_name else "-" * _CELL_WIDTH
            row_cells.append(cell.center(_CELL_WIDTH))
        lines.append("".join(row_cells).rstrip())

    lines.append("")
    lines.append("Lines are hallways. Named rooms are the station's special rooms.")

    return "\n".join(lines)
