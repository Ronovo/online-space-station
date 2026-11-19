"""Atmospherics: the room's canisters, the Gas Dispenser's stock and the combustion chamber, and the tick that heats,
burns and ruptures them.

player_data["atmos"] (see new_atmos):
    canisters  CANISTER_SLOTS slots, each None or {"label", "mix", "port", "thermo": {"target", "on"}}. port is the
               key in PORTS the canister is connected to, or None.
    stock      {dangerous gas: mol the Gas Dispenser has left this shift}
    chamber    {"mix", "lit", "peak": {"temp", "pressure"} of the burn under way, or None}
    air, reservoir, dazed   the station's air, see station_air
    valve_taken, range_paid  the tank rack's free valve and the test range's bounties, see bombs
"""

import copy
import random

from space_online.game.helper_methods import gas_mix
from space_online.game.helper_methods.hazards import start_hazard
from space_online.game.helper_methods.health_bands import LIMBS, change_limb, limb_label
from space_online.game.helper_methods.station_air import new_air, new_reservoir, tick_air
from space_online.game.maps.donut import ATMOSPHERICS_KEY, location_key
from space_online.game.objects.gases import AIR, CANISTER, DANGEROUS_GASES, GAS_TANK, ROOM_TEMP
from space_online.game.objects.items import GAS_TANK_ID

CANISTER_SLOTS = 6
CANISTER_FILL = 4500
STARTING_CANISTERS = (AIR, AIR, {"Oxygen": 1.0}, {"Nitrogen": 1.0}, {"Plasma": 1.0}, None)
DISPENSER_STOCK = round(2 * gas_mix.moles_at(CANISTER_FILL, CANISTER["volume"], ROOM_TEMP))
CHAMBER = {"volume": 2500, "rated": 15000}
PORTS = {"chamber": "Combustion Chamber Inlet", "reservoir": "Reservoir Port"}
HEATER_RANGE = (100, 800)
HEATER_WATTS = 100_000
RUPTURE_DAMAGE = 20
# A burn is over once a second of it releases less than this.
BURN_OVER_JOULES = 100
# What a Gas Tank needs to count as filled with a gas, for a crew member who asks for one.
REQUEST_PURITY = 0.9
REQUEST_PRESSURE = GAS_TANK["rated"] / 2


def new_canister(number, fractions=None):
    """Canister `number`, filled to CANISTER_FILL at room temperature with `fractions` ({gas: share}), or empty."""
    if fractions:
        mix = gas_mix.mix_of(fractions, gas_mix.moles_at(CANISTER_FILL, CANISTER["volume"], ROOM_TEMP), ROOM_TEMP)
    else:
        mix = gas_mix.empty_mix()
    return {"label": f"Canister {number}", "mix": mix, "port": None, "thermo": {"target": ROOM_TEMP, "on": False}}


def new_atmos():
    return {
        "canisters": [new_canister(number, fractions) for number, fractions in enumerate(STARTING_CANISTERS, 1)],
        "stock": {gas: DISPENSER_STOCK for gas in DANGEROUS_GASES},
        "chamber": {"mix": gas_mix.empty_mix(), "lit": False, "peak": None},
        "air": new_air(),
        "reservoir": new_reservoir(),
        "dazed": False,
        "valve_taken": False,
        "range_paid": [],
    }


def move_canister(from_slots, index, to_slots):
    """Send the canister in from_slots[index] down the tube into the first free slot of to_slots, switching its
    heater off. Returns that slot's index, or None when there is no canister there, it is connected to a port, or
    to_slots has no free slot."""
    canister = from_slots[index]
    if canister is None or canister["port"] or None not in to_slots:
        return None
    free = to_slots.index(None)
    canister["thermo"]["on"] = False
    to_slots[free], from_slots[index] = canister, None
    return free


def dispense_into(atmos, canister, gas, amount):
    """Put `amount` mol of `gas` from the Gas Dispenser into `canister` at room temperature, out of the shift's stock
    when it is a dangerous gas."""
    if gas in atmos["stock"]:
        atmos["stock"][gas] -= amount
    gas_mix.merge(canister["mix"], gas_mix.mix_of({gas: 1}, amount, ROOM_TEMP))


def port_canister(atmos, port):
    """The canister connected to `port`, or None."""
    return next((canister for canister in atmos["canisters"] if canister and canister["port"] == port), None)


def connect(atmos, canister, port):
    """Connect `canister` to `port`, taking off whichever canister was on it, or disconnect it with port None."""
    if port is not None:
        other = port_canister(atmos, port)
        if other is not None:
            other["port"] = None
    canister["port"] = port


def poured(into, other):
    """What `into` would hold with `other` poured in, leaving both as they are."""
    result = copy.deepcopy(into)
    gas_mix.merge(result, other)
    return result


def tank_holds(item, gas):
    """Whether an item is a Gas Tank filled with `gas`: REQUEST_PURITY of it, at REQUEST_PRESSURE or more."""
    if item.get("id") != GAS_TANK_ID:
        return False
    mix = item["attributes"]["contents"]
    return (gas_mix.fractions(mix).get(gas, 0) >= REQUEST_PURITY
            and gas_mix.pressure(mix, GAS_TANK["volume"]) >= REQUEST_PRESSURE)


def tank_index(player_data, gas):
    """The inventory index of the first Gas Tank filled with `gas`, or None."""
    return next((index for index, item in enumerate(player_data["inventory"]) if tank_holds(item, gas)), None)


def blast_hurts(game, room_key):
    """A rupture's blast takes RUPTURE_DAMAGE off a random limb of the player when they are in room_key. Returns the
    sentence that says so, with a leading space, or ""."""
    if location_key(game.player_data["location"]) != room_key:
        return ""
    limb = random.choice(LIMBS)
    _, total = change_limb(game.player_data, limb, -RUPTURE_DAMAGE)
    return f" The blast catches your {limb_label(limb).lower()}. It is at {total}%."


def burst_if_over(game, container, spec, name):
    """Rupture `container` ({"mix", ...}) when its gas is past spec's rated pressure: the gas is lost, Atmospherics
    gets a fire (if it held fuel and oxidizer, or was burning) or a hull breach, and a player in the room is hurt.
    Returns whether it burst."""
    mix = container["mix"]
    if not gas_mix.rupture(mix, spec["volume"], spec["rated"]):
        return False
    kind = "fire" if container.get("lit") or gas_mix.can_burn(mix, spark=True) else "breach"
    container["mix"] = gas_mix.empty_mix()
    message = (f"{name} ruptures with a bang at {gas_mix.pressure(mix, spec['volume']):.0f} kPa. Its gas is lost."
               f"{blast_hurts(game, ATMOSPHERICS_KEY)}")
    game.alert("Atmospherics", message, kind="warning")
    game.add_note(message)
    start_hazard(game, ATMOSPHERICS_KEY, kind)
    return True


def burst_chamber_if_over(game):
    chamber = game.player_data["atmos"]["chamber"]
    if burst_if_over(game, chamber, CHAMBER, "The combustion chamber"):
        chamber["lit"], chamber["peak"] = False, None
        return True
    return False


def light_chamber(chamber):
    mix = chamber["mix"]
    chamber["lit"] = True
    chamber["peak"] = {"temp": mix["temp"], "pressure": gas_mix.pressure(mix, CHAMBER["volume"])}


def _run_thermo(canister, seconds):
    """Move a canister's temperature toward its heater/freezer's target by at most HEATER_WATTS a second."""
    mix = canister["mix"]
    needed = (canister["thermo"]["target"] - mix["temp"]) * gas_mix.heat_capacity(mix)
    limit = HEATER_WATTS * seconds
    gas_mix.add_heat(mix, max(-limit, min(limit, needed)))


def _tick_chamber(game, seconds):
    chamber = game.player_data["atmos"]["chamber"]
    mix = chamber["mix"]
    if not chamber["lit"] and gas_mix.can_burn(mix):
        light_chamber(chamber)
    if not chamber["lit"]:
        return
    joules = gas_mix.burn(mix, seconds, spark=True)
    peak = chamber["peak"]
    peak["temp"] = max(peak["temp"], mix["temp"])
    peak["pressure"] = max(peak["pressure"], gas_mix.pressure(mix, CHAMBER["volume"]))
    if burst_chamber_if_over(game) or joules >= BURN_OVER_JOULES * seconds:
        return
    chamber["lit"], chamber["peak"] = False, None
    message = f"The burn is over. It peaked at {peak['temp']:.0f} K and {peak['pressure']:.1f} kPa."
    game.alert("Combustion Chamber", message)
    game.add_note(message)


def tick_atmos(game, delta_seconds):
    """Run the heater/freezer, burn whatever is hot enough to burn, rupture whatever is over its rating, and run the
    station's air."""
    for canister in game.player_data["atmos"]["canisters"]:
        if canister is None:
            continue
        if canister["thermo"]["on"]:
            _run_thermo(canister, delta_seconds)
        gas_mix.burn(canister["mix"], delta_seconds)
        burst_if_over(game, canister, CANISTER, canister["label"])
    _tick_chamber(game, delta_seconds)
    tick_air(game, delta_seconds)
