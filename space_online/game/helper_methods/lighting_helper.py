"""Shared hallway/room lighting helpers."""

# Battery band -> allowed hallway_lighting range (inclusive)
LIGHTING_BANDS = {
    "normal": (6, 8),
    "dim": (3, 5),
    "emergency": (0, 2),
}


# At or below these battery percentages the lights go to emergency lighting, or dim.
EMERGENCY_LIGHTING_BATTERY = 5
DIM_LIGHTING_BATTERY = 15


def battery_lighting_band(battery_level):
    """Return the lighting band suggested by battery percent."""
    if battery_level <= EMERGENCY_LIGHTING_BATTERY:
        return "emergency"
    if battery_level <= DIM_LIGHTING_BATTERY:
        return "dim"
    return "normal"


def _in_band(band, level):
    low, high = LIGHTING_BANDS[band]
    return max(low, min(high, int(level)))


def clamp_lighting_for_battery(station_power):
    """Clamp hallway_lighting into the battery band when the band changes.

    Engineer overrides stick until the next battery-band transition. While the lighting is faulted nothing is
    recorded, so a band change during the fault is applied on the first call after the repair. The level the lights
    had before an antagonist dimmed them is clamped too, so restoring it brings them back where they would have been.
    """
    if "hallway_lighting" in station_power["faults"]:
        return
    band = battery_lighting_band(station_power["battery_level"])
    if station_power.get("last_lighting_battery_band") == band:
        return
    station_power["last_lighting_battery_band"] = band
    levels = station_power["system_levels"]
    levels["hallway_lighting"] = _in_band(band, levels["hallway_lighting"])
    if station_power["dimmed_from"] is not None:
        station_power["dimmed_from"] = _in_band(band, station_power["dimmed_from"])


def lighting_style(hallway_lighting, place="hallway"):
    """Return bg/fg and the lighting sentence (light) for a hallway_lighting level.

    place should be \"hallway\" or \"room\" for the well-lit sentence.
    """
    level = int(hallway_lighting)
    place_word = "hallway" if place == "hallway" else "room"

    if level <= 2:
        return {
            "bg": "#220000",
            "fg": "#FF5555",
            "light": "Emergency lighting casts an eerie red glow. Most systems are offline.",
        }
    if level <= 5:
        return {
            "bg": "#111111",
            "fg": "#BBBBBB",
            "light": "The lights are dimmed to conserve power.",
        }
    if level >= 9:
        return {
            "bg": "black",
            "fg": "white",
            "light": f"This {place_word} is very well lit.",
        }
    return {
        "bg": "black",
        "fg": "white",
        "light": "",
    }
