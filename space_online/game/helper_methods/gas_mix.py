"""Gas mixtures: pressure, mixing, transfer, heating, combustion and rupture.
A mixture is {"moles": {gas: mol}, "temp": kelvin}. Every container that holds gas uses these rules,
with its own volume in litres and rated pressure in kPa."""

from space_online.game.objects.gases import AIR, GASES, ROOM_TEMP, STANDARD_PRESSURE

GAS_CONSTANT = 8.314
SPACE_TEMP = 2.7
FUEL_PARTS = 2
OXIDIZER_PARTS = 3
BURN_SHARE_PER_SECOND = 0.2


def empty_mix():
    return {"moles": {}, "temp": SPACE_TEMP}


def mix_of(fractions, moles, temp):
    """`moles` of gas split by `fractions` ({gas: share}), e.g. mix_of(AIR, 100, 293.15)."""
    return {"moles": {gas: share * moles for gas, share in fractions.items()}, "temp": temp}


def total_moles(mix):
    return sum(mix["moles"].values())


def fractions(mix):
    total = total_moles(mix)
    return {gas: moles / total for gas, moles in mix["moles"].items()} if total else {}


def heat_capacity(mix):
    """J per K for the whole mixture."""
    return sum(moles * GASES[gas]["heat_capacity"] for gas, moles in mix["moles"].items())


def pressure(mix, volume):
    """kPa: with R in J per mol per K and the volume in litres, nRT / V comes out in kPa."""
    return total_moles(mix) * GAS_CONSTANT * mix["temp"] / volume


def moles_at(kpa, volume, temp):
    """The moles that fill `volume` litres to `kpa` at `temp` kelvin."""
    return kpa * volume / (GAS_CONSTANT * temp)


def standard_air(volume):
    """Breathable air filling `volume` litres at standard pressure and room temperature."""
    return mix_of(AIR, moles_at(STANDARD_PRESSURE, volume, ROOM_TEMP), ROOM_TEMP)


def partial_pressure(mix, volume, gas):
    return mix["moles"].get(gas, 0) * GAS_CONSTANT * mix["temp"] / volume


def _add(mix, gas, moles):
    """Changes one gas's moles, dropping the gas once none is left."""
    remaining = mix["moles"].get(gas, 0) + moles
    if remaining > 0:
        mix["moles"][gas] = remaining
    else:
        mix["moles"].pop(gas, None)


def merge(into, other):
    """Pours `other` into `into`. The temperature settles at the heat-capacity-weighted average."""
    into_capacity, other_capacity = heat_capacity(into), heat_capacity(other)
    if into_capacity + other_capacity:
        into["temp"] = ((into_capacity * into["temp"] + other_capacity * other["temp"])
                        / (into_capacity + other_capacity))
    for gas, moles in other["moles"].items():
        _add(into, gas, moles)


def take(mix, moles):
    """Removes up to `moles` from `mix` in its own proportions and returns them as a new mixture."""
    total = total_moles(mix)
    share = min(1.0, moles / total) if total else 0.0
    taken = {"moles": {}, "temp": mix["temp"]}
    for gas, amount in list(mix["moles"].items()):
        _add(taken, gas, amount * share)
        _add(mix, gas, -amount * share)
    return taken


def convert(mix, gas, into, moles):
    """Turns up to `moles` of `gas` into the gas `into`, mole for mole."""
    turned = min(moles, mix["moles"].get(gas, 0))
    _add(mix, gas, -turned)
    _add(mix, into, turned)


def add_heat(mix, joules):
    """Heats (or with negative joules, cools) the mixture. An empty one holds no heat."""
    capacity = heat_capacity(mix)
    if capacity:
        mix["temp"] = max(SPACE_TEMP, mix["temp"] + joules / capacity)


def readout(mix, volume):
    """The line every gauge shows: pressure, temperature and each gas as a percentage."""
    shares = fractions(mix)
    gases = ", ".join(f"{gas} {shares[gas]:.1%}" for gas in GASES if gas in shares) or "Empty"
    return f"{pressure(mix, volume):.1f} kPa, {mix['temp']:.0f} K: {gases}"


def _burning_fuels(mix, spark):
    return {gas: moles for gas, moles in mix["moles"].items()
            if GASES[gas]["role"] == "fuel" and (spark or mix["temp"] >= GASES[gas]["ignition"])}


def _oxidizers(mix):
    return {gas: moles for gas, moles in mix["moles"].items() if GASES[gas]["role"] == "oxidizer"}


def can_burn(mix, spark=False):
    """True when there is an oxidizer and a fuel that is at its ignition temperature or has a spark."""
    return bool(_burning_fuels(mix, spark)) and bool(_oxidizers(mix))


def _react(mix, share, spark):
    """Burns `share` of what can react in the 2 fuel : 3 oxidizer ratio and returns the joules released."""
    fuels, oxidizers = _burning_fuels(mix, spark), _oxidizers(mix)
    fuel, oxidizer = sum(fuels.values()), sum(oxidizers.values())
    # Each side's burnt share is worked out against the other side, so the limiting one reaches exactly 0.
    fuel_share = share * min(1.0, (oxidizer / OXIDIZER_PARTS) / (fuel / FUEL_PARTS))
    oxidizer_share = share * min(1.0, (fuel / FUEL_PARTS) / (oxidizer / OXIDIZER_PARTS))
    strength = sum(moles * GASES[gas]["strength"] for gas, moles in oxidizers.items()) / oxidizer
    joules = sum(moles * fuel_share * GASES[gas]["energy"] for gas, moles in fuels.items()) * strength
    for gas, moles in fuels.items():
        _add(mix, gas, -moles * fuel_share)
    for gas, moles in oxidizers.items():
        _add(mix, gas, -moles * oxidizer_share)
    _add(mix, "Carbon Dioxide", fuel * fuel_share + oxidizer * oxidizer_share)
    add_heat(mix, joules)
    return joules


def burn(mix, seconds, spark=False):
    """Burns for `seconds` and returns the joules released. Each second a share of what can react does."""
    if not can_burn(mix, spark):
        return 0.0
    return _react(mix, 1 - (1 - BURN_SHARE_PER_SECOND) ** seconds, spark)


def burn_out(mix, spark=False):
    """Burns everything that will react, all at once, and returns the joules released."""
    joules = 0.0
    while can_burn(mix, spark):
        joules += _react(mix, 1.0, spark)
    return joules


def rupture(mix, volume, rated):
    """0 within the rated pressure, otherwise how many times the rated pressure the gas is at."""
    over = pressure(mix, volume) / rated
    return over if over > 1 else 0.0
