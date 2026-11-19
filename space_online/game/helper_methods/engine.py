"""The Combustion Engine in the Engineering Bay, the station's main power.

It burns a fuel and oxidizer mix in its burn chamber. The chamber gas heats the hot loop, a radiator cools the cold
loop toward space, and the generator between them charges the battery in step with how far apart the two are. The
spent gas goes out to space. Canisters come from Atmospherics down the tube.

player_data["engine"] (see new_engine):
    canisters      BAY_SLOTS slots, each None or a canister as on the Atmospherics rack, whose port is a LINES key or
                   None
    chamber        the burn chamber's gas
    hot, cold      the hot and cold loop temperatures in K
    running        whether the igniter has it lit
    settings       mixer (the fuel line's share of the gas injected, 0-100), injection (0-10) and coolant (0-10)
    coolant_fault  True while the coolant line is cut, which holds the coolant flow at 0
    damage         0 to 100, how badly the chamber is hurt. At 100 it is wrecked until repaired.
"""

import math

from space_online.game.helper_methods import gas_mix
from space_online.game.helper_methods.atmos import (
    CANISTER_FILL,
    blast_hurts,
    connect,
    dispense_into,
    move_canister,
    new_canister,
    port_canister,
)
from space_online.game.helper_methods.hazards import start_hazard
from space_online.game.helper_methods.station_air import LONGEST_SHIFT_SECONDS
from space_online.game.maps.donut import ENGINEERING_KEY
from space_online.game.objects.gases import CANISTER, GASES, ROOM_TEMP

BAY_SLOTS = 4
# line -> (its name on the panel, the role of the gas it feeds, the gas a fresh canister for it holds)
LINES = {"fuel": ("Fuel", "fuel", "Hydrogen"), "oxidizer": ("Oxidizer", "oxidizer", "Oxygen")}
BURN_CHAMBER = {"volume": 100, "rated": 15000}
SETTING_RANGES = {"mixer": 100, "injection": 10, "coolant": 10}
# The NPC Engineer's setting: the clean mix, low injection and full coolant. It never overheats on any mixture.
SAFE_SETTINGS = {"mixer": 40, "injection": 2, "coolant": 10}
CANISTER_MOLES = gas_mix.moles_at(CANISTER_FILL, CANISTER["volume"], ROOM_TEMP)
# Mol a second for each step of injection, so that at the safe setting the starting Oxygen canister lasts the longest
# shift with half as much again in hand.
INJECTION_STEP = CANISTER_MOLES / (1.5 * LONGEST_SHIFT_SECONDS * SAFE_SETTINGS["injection"]
                                   * (1 - SAFE_SETTINGS["mixer"] / 100))
EXHAUST_SHARE = 0.02
# Heat flows in W per K of difference: chamber gas to hot loop, hot loop to cold loop through the generator, and cold
# loop to space through the radiator for each step of coolant flow. The loops' heat capacities are in J per K.
EXCHANGE = 1000
GENERATOR = 200
RADIATOR = 20
HOT_LOOP_CAPACITY = 10_000
COLD_LOOP_CAPACITY = 10_000
HOT_LIMIT = 1000
OUTPUT_CAP = 4.0
# Battery charge in % a minute for each K between the loops: OUTPUT_CAP with the hot loop at its limit and the coolant
# full on, where the gap between the loops is the generator's share of the fall from the limit to space.
OUTPUT_PER_K = OUTPUT_CAP / ((HOT_LIMIT - gas_mix.SPACE_TEMP) * RADIATOR * SETTING_RANGES["coolant"]
                             / (GENERATOR + RADIATOR * SETTING_RANGES["coolant"]))
# % damage a second while running with the hot loop over HOT_LIMIT, and the damage the log and the PDA warn at.
OVERHEAT_DAMAGE = 1.0
DAMAGE_WARNINGS = (50, 80)
# The log warns at this share of the chamber's rating, and a chamber at this many times its rating bursts.
STALL_WARNING = 0.8
BURST_PRESSURE = 2
# The burn is out once a second of it releases less than this.
FLAME_OUT_JOULES = 1000
# A canister is nearly empty with less than a quarter of a full one's gas left.
LOW_MOLES = 0.25 * CANISTER_MOLES
STEP_SECONDS = 1.0
# The hint warns from this share of HOT_LIMIT, and reads a burn within this share of the 2 to 3 ratio as clean.
NEAR_LIMIT = 0.9
CLEAN_BAND = 0.1


def new_engine(running=False):
    canisters = [new_canister(f"E{number}", {gas: 1.0}) for number, (_, _, gas) in enumerate(LINES.values(), 1)]
    for canister, line in zip(canisters, LINES):
        canister["port"] = line
    return {
        "canisters": canisters + [None] * (BAY_SLOTS - len(canisters)),
        "chamber": gas_mix.empty_mix(),
        "hot": ROOM_TEMP,
        "cold": ROOM_TEMP,
        "running": running,
        "settings": dict(SAFE_SETTINGS),
        "coolant_fault": False,
        "damage": 0.0,
    }


def chamber_pressure(engine):
    return gas_mix.pressure(engine["chamber"], BURN_CHAMBER["volume"])


def coolant_flow(engine):
    return 0 if engine["coolant_fault"] else engine["settings"]["coolant"]


def wrecked(engine):
    return engine["damage"] >= 100


def engine_output(engine):
    """Battery charge in % a minute: in step with the gap between the loops, up to OUTPUT_CAP, and 0 when not
    running."""
    if not engine["running"]:
        return 0.0
    return min(OUTPUT_CAP, OUTPUT_PER_K * max(0.0, engine["hot"] - engine["cold"]))


def _role_moles(mix, role):
    return sum(moles for gas, moles in mix["moles"].items() if GASES[gas]["role"] == role)


def running_low(canister):
    return gas_mix.total_moles(canister["mix"]) < LOW_MOLES


def spare(engine, line):
    """The unconnected canister in the bay holding the most gas for `line`, unless even that one is nearly empty."""
    role = LINES[line][1]
    unconnected = [canister for canister in engine["canisters"] if canister and not canister["port"]]
    best = max(unconnected, key=lambda canister: _role_moles(canister["mix"], role), default=None)
    return best if best is not None and _role_moles(best["mix"], role) >= LOW_MOLES else None


def fit_lines(engine):
    """Connect a spare to each line of a stopped engine whose canister is missing or nearly empty. Returns whether
    every line then has gas to draw."""
    for line in LINES:
        current, fresh = port_canister(engine, line), spare(engine, line)
        if (current is None or running_low(current)) and fresh is not None:
            connect(engine, fresh, line)
    connected = [port_canister(engine, line) for line in LINES]
    return all(canister is not None and gas_mix.total_moles(canister["mix"]) for canister in connected)


def _fillable(canister, gas):
    """Whether a rack canister can be filled with gas for a line: unconnected, and holding nothing but that gas."""
    return canister is not None and not canister["port"] and set(gas_mix.fractions(canister["mix"])) <= {gas}


def send_fresh_canister(atmos, engine):
    """For the first line whose canister is nearly empty with no spare waiting, fill a rack canister with the line's
    gas from the Gas Dispenser and send it down the tube. The canister picked is the emptiest one holding nothing but
    that gas, and a dangerous gas comes out of the shift's stock. Nothing goes that would arrive nearly empty itself.
    Returns (the canister, its gas), or None when no line needs one, the bay is full, no rack canister will do, or the
    stock has run too low to fill one."""
    if None not in engine["canisters"]:
        return None
    rack = atmos["canisters"]
    for line, (_, _, gas) in LINES.items():
        current = port_canister(engine, line)
        if current is None or not running_low(current) or spare(engine, line) is not None:
            continue
        candidates = [index for index, canister in enumerate(rack) if _fillable(canister, gas)]
        if not candidates:
            continue
        index = min(candidates, key=lambda i: gas_mix.total_moles(rack[i]["mix"]))
        canister = rack[index]
        held = gas_mix.total_moles(canister["mix"])
        amount = max(0.0, min(CANISTER_MOLES - held, atmos["stock"].get(gas, math.inf)))
        if held + amount < LOW_MOLES:
            continue
        if amount:
            dispense_into(atmos, canister, gas, amount)
        move_canister(rack, index, engine["canisters"])
        return canister, gas
    return None


def send_back_empty(engine, rack):
    """Send the first nearly empty, unconnected canister in the bay back down the tube to the Atmospherics rack.
    Returns it, or None when there is none or the rack has no free slot."""
    for index, canister in enumerate(engine["canisters"]):
        if canister and not canister["port"] and running_low(canister):
            return canister if move_canister(engine["canisters"], index, rack) is not None else None
    return None


def hint(engine):
    """The one line the panel gives on how the engine is doing, the most urgent first."""
    if engine["coolant_fault"]:
        return "Coolant line cut."
    if chamber_pressure(engine) > STALL_WARNING * BURN_CHAMBER["rated"]:
        return "Pumps stalling."
    if engine["hot"] > NEAR_LIMIT * HOT_LIMIT:
        return "Hot loop near its limit."
    if not engine["running"]:
        return "Not running."
    fuel, oxidizer = _role_moles(engine["chamber"], "fuel"), _role_moles(engine["chamber"], "oxidizer")
    balance = (fuel / gas_mix.FUEL_PARTS) / (oxidizer / gas_mix.OXIDIZER_PARTS) if oxidizer else math.inf
    if balance > 1 + CLEAN_BAND:
        return "Burning rich: unburnt fuel in the exhaust."
    if balance < 1 - CLEAN_BAND:
        return "Burning lean."
    return "Burning clean."


def _inject(engine, seconds):
    settings = engine["settings"]
    total = settings["injection"] * INJECTION_STEP * seconds
    for line, share in (("fuel", settings["mixer"] / 100), ("oxidizer", 1 - settings["mixer"] / 100)):
        canister = port_canister(engine, line)
        if canister is not None:
            gas_mix.merge(engine["chamber"], gas_mix.take(canister["mix"], total * share))


def _level(capacity, other):
    """The J per K that would bring two bodies of these heat capacities level: the smaller, in series."""
    return capacity * other / (capacity + other)


def _move_heat(engine, seconds):
    """Chamber gas to the hot loop, the hot loop to the cold loop, and the cold loop to space. No flow in a step goes
    past bringing its two ends level."""
    chamber = engine["chamber"]
    gas_capacity = gas_mix.heat_capacity(chamber)
    if gas_capacity:
        joules = (chamber["temp"] - engine["hot"]) * min(EXCHANGE * seconds, _level(gas_capacity, HOT_LOOP_CAPACITY))
        gas_mix.add_heat(chamber, -joules)
        engine["hot"] += joules / HOT_LOOP_CAPACITY
    joules = (engine["hot"] - engine["cold"]) * min(GENERATOR * seconds,
                                                    _level(HOT_LOOP_CAPACITY, COLD_LOOP_CAPACITY))
    engine["hot"] -= joules / HOT_LOOP_CAPACITY
    engine["cold"] += joules / COLD_LOOP_CAPACITY
    joules = (engine["cold"] - gas_mix.SPACE_TEMP) * min(RADIATOR * coolant_flow(engine) * seconds,
                                                         COLD_LOOP_CAPACITY)
    engine["cold"] -= joules / COLD_LOOP_CAPACITY


def step_engine(engine, seconds):
    """Run the engine's physics for `seconds`: inject, burn, move heat, exhaust, and wear the chamber while it runs
    with the hot loop over its limit. The pumps stall while the chamber is over its rating. Returns the joules the burn
    released."""
    chamber = engine["chamber"]
    stalled = chamber_pressure(engine) > BURN_CHAMBER["rated"]
    if engine["running"] and not stalled:
        _inject(engine, seconds)
    joules = gas_mix.burn(chamber, seconds, spark=engine["running"])
    _move_heat(engine, seconds)
    if not stalled:
        gas_mix.take(chamber, gas_mix.total_moles(chamber) * min(1.0, EXHAUST_SHARE * seconds))
    if engine["running"] and engine["hot"] > HOT_LIMIT:
        engine["damage"] = min(100.0, engine["damage"] + OVERHEAT_DAMAGE * seconds)
    return joules


def _warn(game, message, kind="warning"):
    game.alert("Combustion Engine", message, kind=kind)


def _fail(game, engine):
    """The wrecked chamber shuts the engine down: a fire in the Engineering Bay, or a burst with a hull breach that
    catches a player in the room when it was past BURST_PRESSURE times its rating."""
    burst = gas_mix.rupture(engine["chamber"], BURN_CHAMBER["volume"], BURN_CHAMBER["rated"]) >= BURST_PRESSURE
    engine["running"] = False
    engine["chamber"] = gas_mix.empty_mix()
    if burst:
        message = ("The combustion chamber bursts and tears a hole in the hull. The engine is dead until it is "
                   f"repaired.{blast_hurts(game, ENGINEERING_KEY)}")
    else:
        message = "The combustion chamber gives out. The engine shuts down until it is repaired."
    _warn(game, message, kind="error")
    game.add_note(message)
    start_hazard(game, ENGINEERING_KEY, "breach" if burst else "fire")


def _report(game, engine, before, joules, seconds):
    """Log what one step changed: warnings on the way to a failure, then the failure itself."""
    rated = BURN_CHAMBER["rated"]
    pressure = chamber_pressure(engine)
    if before["pressure"] <= STALL_WARNING * rated < pressure:
        _warn(game, f"Chamber pressure is past {STALL_WARNING:.0%} of its {rated} kPa rating. The pumps stall over "
                    "it.")
    if before["pressure"] <= rated < pressure:
        _warn(game, f"The pumps stall: the chamber is over {rated} kPa. Injection and exhaust stop until it drops.")
    if before["hot"] <= HOT_LIMIT < engine["hot"]:
        _warn(game, f"The hot loop is over its {HOT_LIMIT} K limit. The chamber takes damage while the engine runs.")
    for level in DAMAGE_WARNINGS:
        if before["damage"] < level <= engine["damage"]:
            _warn(game, f"The combustion chamber is at {level}% damage.")
    if engine["running"] and joules < FLAME_OUT_JOULES * seconds:
        engine["running"] = False
        _warn(game, "The engine flames out: there is nothing left in the chamber to burn.")
        game.add_note("The combustion engine flamed out.")
    if before["damage"] < 100 <= engine["damage"]:
        _fail(game, engine)


def tick_engine(game, delta_seconds):
    """Run the engine for delta_seconds, a step of at most STEP_SECONDS at a time."""
    engine = game.player_data["engine"]
    steps = max(1, math.ceil(delta_seconds / STEP_SECONDS))
    for _ in range(steps):
        before = {"pressure": chamber_pressure(engine), "hot": engine["hot"], "damage": engine["damage"]}
        joules = step_engine(engine, delta_seconds / steps)
        _report(game, engine, before, joules, delta_seconds / steps)
