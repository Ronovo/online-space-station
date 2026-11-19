"""
The "Donut" station layout: a hollow square ring of hallways with special
rooms sprouting off of it (Bridge, MedBay, Security, Engineering, Bar,
Kitchen, Botany, Mining Bay, Cargo Bay, Departures), the player's Quarters attached at the hallway
junction, and the Science Hall off the east side, with doors to Atmospherics, Chemistry and the Research Lab.
"""

from collections import deque
from typing import NamedTuple

# --- Special room coordinate keys ---
QUARTERS_KEY = "-1,0"
BRIDGE_KEY = "6,0"
MEDBAY_KEY = "0,6"
SECURITY_KEY = "6,6"
ENGINEERING_KEY = "6,3"
BAR_KEY = "-1,3"
BOTANY_KEY = "3,-1"
KITCHEN_KEY = "-1,2"
CHEMISTRY_KEY = "3,7"
MINING_KEY = "6,2"
CARGO_KEY = "6,1"
RESEARCH_KEY = "2,6"
DEPARTURES_KEY = "1,-1"
ATMOSPHERICS_KEY = "4,6"

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
    "1,0": {"name": "Departures Entrance", "desc": "This hallway leads to Departures, where the crew shuttle docks."},
    "2,0": {"name": "North Hallway", "desc": "A long hallway stretching north."},
    "3,0": {"name": "North Hallway", "desc": "A long hallway stretching north. You notice a door labeled 'Botany Lab' on the west wall."},
    "4,0": {"name": "North Hallway", "desc": "A long hallway stretching north."},
    "5,0": {"name": "North End", "desc": "The northern end of the hallway. The bridge is nearby."},
    "0,1": {"name": "East Hallway", "desc": "A long hallway stretching east."},
    "0,2": {"name": "Kitchen Entrance", "desc": "This hallway leads to the station Kitchen. Something smells good."},
    "0,3": {"name": "Bar Entrance", "desc": "This hallway leads to the station Bar. Soft music can be heard from inside."},
    "0,4": {"name": "East Hallway", "desc": "A long hallway stretching east."},
    "0,5": {"name": "East End", "desc": "The eastern end of the hallway. The medbay is nearby."},

    "5,1": {"name": "Cargo Bay Entrance", "desc": "This hallway leads to the Cargo Bay. Crates are stacked along the wall."},
    "5,2": {"name": "Mining Bay Entrance", "desc": "This hallway leads to the Mining Bay. The floor hums underfoot."},
    "5,3": {"name": "Engineering Bay Entrance", "desc": "This hallway leads to the Engineering Bay."},
    "5,4": {"name": "Northeast Hallway", "desc": "A hallway connecting the north and east corridors."},
    "5,5": {"name": "Northeast Corner", "desc": "The far corner of the station. Security is nearby."},

    "4,5": {"name": "East Section", "desc": "A hallway along the eastern side of the station."},
    "3,5": {"name": "East Section", "desc": "A hallway along the eastern side of the station. The Science Hall is to the east."},
    "2,5": {"name": "East Section", "desc": "A hallway along the eastern side of the station."},
    "1,5": {"name": "East Section", "desc": "A hallway connecting back to the main hallways."},

    "3,6": {"name": "Science Hall", "desc": "A bright, quiet hall with three sealed lab doors: Atmospherics to the north, Chemistry to the east and the Research Lab to the south. The main hallway is back to the west."},

}


class Room(NamedTuple):
    """One special room.

    room      the short name its room class is registered under
    name      what the room is called on doors, maps and in messages
    hallway   the hallway tile in front of its door
    button    (row, col) of its door button on that tile's nav grid, a cell whose direction is closed there
    access    the subdepartments that work its door and stations
    posts     the jobs with a post in it. A job may have posts in several rooms
    """
    room: str
    name: str
    hallway: tuple
    button: tuple
    access: frozenset = frozenset()
    posts: tuple = ()


ROOMS = {
    BRIDGE_KEY: Room("Bridge", "Bridge", (5, 0), (0, 1), frozenset({"Captain", "HoP"}),
                     ("Captain", "Head of Personnel")),
    MEDBAY_KEY: Room("MedBay", "MedBay", (0, 5), (1, 2), frozenset({"Captain", "HoP", "Doctor"}), ("Doctor",)),
    SECURITY_KEY: Room("Security", "Security Office", (5, 5), (0, 1), frozenset({"Captain", "Security"}),
                       ("Security Guard",)),
    ENGINEERING_KEY: Room("Engineering", "Engineering Bay", (5, 3), (0, 1),
                          frozenset({"Captain", "HoP", "Engineer"}), ("Engineer",)),
    BAR_KEY: Room("Bar", "Bar", (0, 3), (2, 1), frozenset({"Captain", "HoP", "Bar"}), ("Bartender",)),
    BOTANY_KEY: Room("Botany", "Botany Lab", (3, 0), (1, 0), frozenset({"Captain", "HoP", "Botany"}), ("Botanist",)),
    KITCHEN_KEY: Room("Kitchen", "Kitchen", (0, 2), (2, 1), frozenset({"Captain", "HoP", "Kitchen"}), ("Chef",)),
    CHEMISTRY_KEY: Room("Chemistry", "Chemistry Lab", (3, 6), (1, 2), frozenset({"Captain", "HoP", "Science"}),
                        ("Scientist",)),
    MINING_KEY: Room("Mining", "Mining Bay", (5, 2), (0, 1), frozenset({"Captain", "HoP", "Mining"}), ("Miner",)),
    CARGO_KEY: Room("Cargo", "Cargo Bay", (5, 1), (0, 1), frozenset({"Captain", "HoP", "Cargo"}),
                    ("Quartermaster",)),
    RESEARCH_KEY: Room("Research", "Research Lab", (3, 6), (2, 1), frozenset({"Captain", "HoP", "Science"}),
                       ("Scientist",)),
    ATMOSPHERICS_KEY: Room("Atmospherics", "Atmospherics", (3, 6), (0, 1), frozenset({"Captain", "HoP", "Science"}),
                           ("Scientist",)),
    DEPARTURES_KEY: Room("Departures", "Departures", (1, 0), (1, 0)),
    QUARTERS_KEY: Room("Quarters", "Quarters", (0, 0), (2, 1)),
}

SHIP_MAP.update({key: {"name": room.name, "locked": False, "hazard": None}
                 for key, room in ROOMS.items() if key != QUARTERS_KEY})

LOCKABLE_ROOM_KEYS = tuple(key for key in ROOMS if key != QUARTERS_KEY)
SPECIAL_ROOM_TILES = {key: room.room for key, room in ROOMS.items()}
SPECIAL_ROOM_HALLWAY = {key: room.hallway for key, room in ROOMS.items()}


def step_toward(start, target):
    """The hallway tile one step from start along the shortest way to target, or start itself once it is there."""
    if start == target:
        return start
    # Breadth-first search out from the target, so each tile's parent is its next step toward it.
    parents = {target: None}
    queue = deque([target])
    while start not in parents:
        current = queue.popleft()
        for neighbor in hallway_neighbors(*current).values():
            if neighbor not in parents:
                parents[neighbor] = current
                queue.append(neighbor)
    return parents[start]


def hallway_neighbors(x, y):
    """The hallway tiles one step from (x, y), by direction. Room doors are entered with a button, not walked to."""
    neighbors = {}
    for direction, (dx, dy) in DIRECTION_STEPS.items():
        key = tile_key(x + dx, y + dy)
        if key in SHIP_MAP and key not in SPECIAL_ROOM_TILES:
            neighbors[direction] = (x + dx, y + dy)
    return neighbors


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
