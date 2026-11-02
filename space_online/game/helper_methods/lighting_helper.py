"""Shared hallway/room lighting helpers."""

# Battery band -> allowed hallway_lighting range (inclusive)
LIGHTING_BANDS = {
    "normal": (6, 8),
    "dim": (3, 5),
    "emergency": (0, 2),
}


def battery_lighting_band(battery_level):
    """Return the lighting band suggested by battery percent."""
    if battery_level <= 5:
        return "emergency"
    if battery_level <= 15:
        return "dim"
    return "normal"


def clamp_lighting_for_battery(station_power):
    """Clamp hallway_lighting into the battery band when the band changes.

    Engineer overrides stick until the next battery-band transition.
    """
    band = battery_lighting_band(station_power["battery_level"])
    if station_power.get("last_lighting_battery_band") == band:
        return
    station_power["last_lighting_battery_band"] = band
    if "hallway_lighting" in station_power["faults"]:
        return
    low, high = LIGHTING_BANDS[band]
    levels = station_power["system_levels"]
    levels["hallway_lighting"] = max(low, min(high, int(levels["hallway_lighting"])))


def lighting_style(hallway_lighting, place="hallway"):
    """Return bg/fg/power_desc for a hallway_lighting level.

    place should be \"hallway\" or \"room\" for the well-lit sentence.
    """
    level = int(hallway_lighting)
    place_word = "hallway" if place == "hallway" else "room"

    if level <= 2:
        return {
            "bg": "#220000",
            "fg": "#FF5555",
            "power_desc": "\n\nEmergency lighting casts an eerie red glow. Most systems are offline.",
        }
    if level <= 5:
        return {
            "bg": "#111111",
            "fg": "#BBBBBB",
            "power_desc": "\n\nThe lights are dimmed to conserve power.",
        }
    if level >= 9:
        return {
            "bg": "black",
            "fg": "white",
            "power_desc": f"\n\nThis {place_word} is very well lit.",
        }
    return {
        "bg": "black",
        "fg": "white",
        "power_desc": "",
    }


def clamped_station_power(player_data):
    """station_power, with the lighting clamped for the battery level."""
    clamp_lighting_for_battery(player_data["station_power"])
    return player_data["station_power"]
