"""The station's air: one mixture for the whole station, which life support keeps fresh from the reservoir.

player_data["atmos"] holds, besides what atmos.py keeps there:
    air        the station's atmosphere, read in STATION_AIR's volume
    reservoir  the gas life support pumps into the air, read in RESERVOIR's volume
    dazed      whether the player is breathing past the Nitrous Oxide limit, so time runs fast for them

Each second the crew breathe Oxygen into Carbon Dioxide, and life support's scrubbers draw off a share of the air
while its pump refills it from the reservoir, both scaled by the life support level. Whatever is in the reservoir is
what the air turns into. Hull breaches vent air to space and fires burn its Oxygen.
"""

import random

from space_online.game.helper_methods import gas_mix
from space_online.game.helper_methods.hazards import HAZARD_ROOM_KEYS, hazard_rooms, room_hazard, start_hazard
from space_online.game.helper_methods.rounds import (
    SHIFT_END_RANGE_SECONDS,
    SHUTTLE_ARRIVAL_SECONDS,
    SHUTTLE_DOCKED_SECONDS,
    SHUTTLE_TRANSIT_SECONDS,
)
from space_online.game.objects.gases import (
    AIR,
    CARBON_DIOXIDE_MAX,
    GAS_TANK,
    GASES,
    NITROUS_OXIDE_MAX,
    OXYGEN_MIN,
    OXYGEN_RICH,
    PLASMA_MAX,
    PRESSURE_MIN,
    ROOM_TEMP,
    STANDARD_PRESSURE,
    STATION_AIR,
)
from space_online.game.objects.items import GAS_TANK_ID, held_items

# (name, gas or None for the total pressure, the limit in kPa, where it is at its worst, what being past it does)
LIMITS = (
    ("Oxygen", "Oxygen", OXYGEN_MIN, 0, "oxygen"),
    ("Carbon Dioxide", "Carbon Dioxide", CARBON_DIOXIDE_MAX, 3 * CARBON_DIOXIDE_MAX, "oxygen"),
    ("Pressure", None, PRESSURE_MIN, 0, "oxygen"),
    ("Plasma", "Plasma", PLASMA_MAX, 10 * PLASMA_MAX, "poison"),
    ("Oxygen-rich", "Oxygen", OXYGEN_RICH, STANDARD_PRESSURE, "rich"),
    ("Nitrous Oxide", "Nitrous Oxide", NITROUS_OXIDE_MAX, STANDARD_PRESSURE, "time"),
)
# The air counts as an emergency once a harmful limit is this far toward its worst.
EMERGENCY_SEVERITY = 0.5

AIR_MOLES = gas_mix.moles_at(STANDARD_PRESSURE, STATION_AIR["volume"], ROOM_TEMP)
FULL_CREW = 19
AIR_LASTS_SECONDS = 120
# Each crew member's breathing, tuned so a full crew takes fresh air down to OXYGEN_MIN in AIR_LASTS_SECONDS.
BREATH_RATE = (gas_mix.moles_at(AIR["Oxygen"] * STANDARD_PRESSURE - OXYGEN_MIN, STATION_AIR["volume"], ROOM_TEMP)
               / (AIR_LASTS_SECONDS * FULL_CREW))
# At this life support level the scrubbers turn the whole air over once every AIR_LASTS_SECONDS, which holds a full
# crew's Oxygen at OXYGEN_MIN: at level 5 and above the air stays breathable, at 4 and below it sags.
KEEPS_UP_LEVEL = 4.75
SCRUB_SHARE = 10 / (KEEPS_UP_LEVEL * AIR_LASTS_SECONDS)
PUMP_RATE = 2 * SCRUB_SHARE * AIR_MOLES
BREACH_VENT_SHARE = 0.01
FIRE_OXYGEN_RATE = 5 * BREATH_RATE
VENT_SHARE = 0.75

LONGEST_SHIFT_SECONDS = (SHIFT_END_RANGE_SECONDS[1] + SHUTTLE_ARRIVAL_SECONDS + SHUTTLE_DOCKED_SECONDS
                         + SHUTTLE_TRANSIT_SECONDS)
# Enough for the longest shift at level 10, with half as much again in hand.
RESERVOIR_FILL = 1.5 * LONGEST_SHIFT_SECONDS * SCRUB_SHARE * AIR_MOLES
RESERVOIR_LOW = 0.25
# The reservoir counts as tainted while more than this share of it is something other than air.
RESERVOIR_TRACE = 0.005
UPKEEP_MOLES = RESERVOIR_FILL / 2

TANK_FULL = gas_mix.moles_at(GAS_TANK["rated"], GAS_TANK["volume"], ROOM_TEMP)
TANK_LASTS_SECONDS = 300
TANK_BREATH_RATE = TANK_FULL / TANK_LASTS_SECONDS
TANK_LOW = 0.25

N2O_TIME_FACTOR = 4
# The partial pressure of fuel in the air at which a spark sets all of it off.
FLASH_POINT = 1
FLASH_BURN = 20

DAZED_TEXT = "The room swims. Time slips away from you."
CLEAR_TEXT = "Your head clears. Time runs at its proper pace again."
TANK_LOW_TEXT = "Your tank is down to a quarter."
TANK_EMPTY_TEXT = "Your tank is empty. You are breathing the station's air again."


def new_air():
    return gas_mix.standard_air(STATION_AIR["volume"])


def new_reservoir():
    return gas_mix.mix_of(AIR, RESERVOIR_FILL, ROOM_TEMP)


def readings(mix):
    """Each limit as {"name", "gas", "kpa", "low", "past", "severity", "effect"} for a mixture read in the station's
    volume. low is whether the limit is a floor, and severity runs from 0 at the limit to 1 at its worst."""
    rows = []
    for name, gas, limit, worst, effect in LIMITS:
        kpa = (gas_mix.partial_pressure(mix, STATION_AIR["volume"], gas) if gas
               else gas_mix.pressure(mix, STATION_AIR["volume"]))
        severity = (kpa - limit) / (worst - limit)
        rows.append({"name": name, "gas": gas, "kpa": kpa, "low": worst < limit, "past": severity > 0,
                     "severity": min(1.0, severity), "effect": effect})
    return rows


def breath_effects(mix):
    """What breathing `mix` does: the severity of the oxygen and the poison damage it gives (None for none), whether
    it is Oxygen-rich, and whether it makes time slip away."""
    rows = readings(mix)

    def worst(effect):
        return max((row["severity"] for row in rows if row["effect"] == effect and row["past"]), default=None)

    return {"oxygen": worst("oxygen"), "poison": worst("poison"), "rich": worst("rich") is not None,
            "time": worst("time") is not None}


def air_threat(mix):
    """"safe", "damaging" or "emergency" for the harm breathing `mix` does."""
    effects = breath_effects(mix)
    harm = max((severity for severity in (effects["oxygen"], effects["poison"]) if severity is not None), default=None)
    if harm is None:
        return "safe"
    return "emergency" if harm >= EMERGENCY_SEVERITY else "damaging"


def contaminated(mix):
    """Whether a gas that isn't part of air is past its limit in `mix`."""
    return any(row["past"] for row in readings(mix) if row["gas"] and row["gas"] not in AIR)


def reservoir_tainted(reservoir):
    shares = gas_mix.fractions(reservoir)
    return sum(share for gas, share in shares.items() if gas not in AIR) > RESERVOIR_TRACE


def reservoir_share(reservoir):
    """How full the reservoir is, as a share of RESERVOIR_FILL."""
    return gas_mix.total_moles(reservoir) / RESERVOIR_FILL


def tank_on(player_data):
    """The Gas Tank the player is breathing from: one held in a hand with its valve open and gas left, or None."""
    return next((item for item in held_items(player_data)
                 if item["id"] == GAS_TANK_ID and item["attributes"]["valve_open"]
                 and gas_mix.total_moles(item["attributes"]["contents"])), None)


def breath_of(player_data, member):
    """The mixture a crew member breathes, read in the station's volume: the station air, or for a player on a
    tank, the tank's gas at standard pressure as a mask delivers it."""
    tank = tank_on(player_data) if member is player_data else None
    if tank is None:
        return player_data["atmos"]["air"]
    return gas_mix.mix_of(gas_mix.fractions(tank["attributes"]["contents"]), AIR_MOLES, ROOM_TEMP)


def pump_rate(player_data):
    """The most the pump moves from the reservoir into the air each second at the current life support level."""
    return PUMP_RATE * player_data["station_power"]["system_levels"]["life_support"] / 10


def vent_station(player_data):
    """Dump VENT_SHARE of the station's air to space. The pump refills it from the reservoir."""
    gas_mix.take(player_data["atmos"]["air"], VENT_SHARE * gas_mix.total_moles(player_data["atmos"]["air"]))


def time_factor(game):
    """How many times as fast game time runs for the player: N2O_TIME_FACTOR while their breath is past the Nitrous
    Oxide limit, else 1. The log says so when that starts and when it stops."""
    atmos = game.player_data["atmos"]
    dazed = breath_effects(breath_of(game.player_data, game.player_data))["time"]
    if dazed != atmos["dazed"]:
        atmos["dazed"] = dazed
        game.alert("Nitrous Oxide", DAZED_TEXT if dazed else CLEAR_TEXT, kind="warning" if dazed else "info")
    return N2O_TIME_FACTOR if dazed else 1


def _breathe_tank(game, tank, seconds):
    contents = tank["attributes"]["contents"]
    before = gas_mix.total_moles(contents)
    gas_mix.take(contents, TANK_BREATH_RATE * seconds)
    after = gas_mix.total_moles(contents)
    if not after:
        game.alert("Gas Tank", TANK_EMPTY_TEXT, kind="warning")
    elif before > TANK_LOW * TANK_FULL >= after:
        game.alert("Gas Tank", TANK_LOW_TEXT, kind="warning")


def _flash(game, air):
    """Fuel in the air meets a spark: it all burns at once, burning everyone, and starts a fire somewhere."""
    gas_mix.burn_out(air, spark=True)
    for member in [game.player_data, *game.station_crew]:
        member["damage"]["burn"] = min(100, member["damage"]["burn"] + FLASH_BURN)
    message = (f"The fuel in the station's air catches a spark and flashes into flame. Everyone is burned. "
               f"Burn damage: {game.player_data['damage']['burn']}%.")
    game.alert("Station Air", message, kind="error")
    game.add_note(message)
    safe = [key for key in HAZARD_ROOM_KEYS if not room_hazard(game.player_data, key)]
    if safe:
        start_hazard(game, random.choice(safe), "fire")


def _fuel_kpa(air):
    return sum(gas_mix.partial_pressure(air, STATION_AIR["volume"], gas)
               for gas in air["moles"] if GASES[gas]["role"] == "fuel")


def tick_air(game, delta_seconds):
    """Run the station's air for delta_seconds: hazards, breathing, the scrubbers and the pump."""
    player_data = game.player_data
    air = player_data["atmos"]["air"]
    hazards = [kind for _, kind in hazard_rooms(player_data)]
    gas_mix.take(air, gas_mix.total_moles(air) * min(1.0, BREACH_VENT_SHARE * hazards.count("breach") * delta_seconds))
    gas_mix.convert(air, "Oxygen", "Carbon Dioxide", FIRE_OXYGEN_RATE * hazards.count("fire") * delta_seconds)
    if ("fire" in hazards or "wiring" in hazards) and _fuel_kpa(air) >= FLASH_POINT:
        _flash(game, air)

    tank = tank_on(player_data)
    if tank is not None:
        _breathe_tank(game, tank, delta_seconds)
    breathers = len(game.station_crew) + (0 if tank else 1)
    gas_mix.convert(air, "Oxygen", "Carbon Dioxide", BREATH_RATE * breathers * delta_seconds)

    level = player_data["station_power"]["system_levels"]["life_support"]
    gas_mix.take(air, gas_mix.total_moles(air) * min(1.0, SCRUB_SHARE * level / 10 * delta_seconds))
    shortfall = gas_mix.moles_at(STANDARD_PRESSURE, STATION_AIR["volume"], air["temp"]) - gas_mix.total_moles(air)
    if shortfall > 0:
        gas_mix.merge(air, gas_mix.take(player_data["atmos"]["reservoir"],
                                        min(shortfall, pump_rate(player_data) * delta_seconds)))

    asleep = breath_effects(air)["time"]
    for npc in game.station_crew:
        npc["asleep"] = asleep
