"""Shared power system constants and helpers."""

SYSTEM_NAMES = {
    "life_support": "Life Support",
    "hallway_lighting": "Hallway Lighting",
    "security_systems": "Security Systems",
    "communication_array": "Communication Array",
}

def system_name(system_key):
    return SYSTEM_NAMES[system_key]


# The Balanced power mode, which is also how a new station starts.
BALANCED_SYSTEM_LEVELS = {
    "life_support": 10,
    "hallway_lighting": 6,
    "security_systems": 7,
    "communication_array": 5,
}


def default_station_power():
    """Return a fresh station_power dict for a new game."""
    return {
        "battery_level": 25.0,
        "solar_charging": False,
        "system_levels": dict(BALANCED_SYSTEM_LEVELS),
        "power_mode": "balanced",
        "last_lighting_battery_band": None,
        "faults": [],
        "fault_levels": {},
        "solar_tripped_at": None,
        "dimmed_from": None,
    }


# Systems an equipment fault can knock out. Life support is never one of them.
FAULTABLE_SYSTEMS = ("hallway_lighting", "security_systems", "communication_array")


def system_online(player_data, system_key):
    """Whether a station system has any power going to it."""
    return player_data["station_power"]["system_levels"][system_key] > 0


def fault_system(station_power, system_key):
    """Knock a system out: it stays at 0 until it is repaired from the Engineering Panel, which brings it back to
    the level it had."""
    station_power["faults"].append(system_key)
    station_power["fault_levels"][system_key] = station_power["system_levels"][system_key]
    station_power["system_levels"][system_key] = 0


SYSTEM_POWER_RATES = {
    "life_support": 0.5,
    "hallway_lighting": 0.3,
    "security_systems": 0.3,
    "communication_array": 0.2,
}

LOW_POWER_SYSTEM_LEVELS = {
    "life_support": 7,
    "hallway_lighting": 3,
    "security_systems": 5,
    "communication_array": 2,
}

BATTERY_CRITICAL = 10
BATTERY_LOW = 50
BATTERY_BAND_COLORS = {"outage": "#FF0000", "critical": "#FF0000", "low": "#FFFF00", "normal": "#00FF00"}

LOW_POWER_ALERT = "Warning: Station battery power low. Check power sources."
POWER_OUTAGE_ALERT = "CRITICAL: Station power failure! Life support has shut down. Check power sources."


def battery_band(level):
    """'outage', 'critical', 'low' or 'normal' for a battery percentage."""
    if level <= 0:
        return "outage"
    if level <= BATTERY_CRITICAL:
        return "critical"
    if level <= BATTERY_LOW:
        return "low"
    return "normal"


# % per minute while the solar array is on: the backup to the Combustion Engine, enough to hold Power Saving.
SOLAR_CHARGE_RATE = 0.7


def calculate_discharge(system_levels, elapsed_seconds, rates=SYSTEM_POWER_RATES):
    """Return total battery discharge (% of capacity) for the elapsed interval."""
    minutes = elapsed_seconds / 60
    total = 0.0
    for system, base_rate in rates.items():
        level = system_levels.get(system, 0)
        if level > 0:
            total += base_rate * level / 10.0 * minutes
    return total


def calculate_solar_charge(elapsed_seconds, solar_charging):
    """Return solar charge (% of capacity) for the elapsed interval."""
    if not solar_charging:
        return 0.0
    return (elapsed_seconds / 60) * SOLAR_CHARGE_RATE
