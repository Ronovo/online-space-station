"""Atmospherics: the gases, the breathable mix, and the containers that hold gas.
Heat capacity is in J per mol per K, ignition in K, energy in J per mol of fuel burned, volume in litres
and rated pressure in kPa."""

# An oxidizer's strength is the share of the fuel's energy a burn releases when it is the oxidizer.
GASES = {
    "Oxygen": {"role": "oxidizer", "heat_capacity": 20, "strength": 1.0},
    "Nitrogen": {"role": "inert", "heat_capacity": 20},
    "Carbon Dioxide": {"role": "inert", "heat_capacity": 30},
    "Plasma": {"role": "fuel", "heat_capacity": 200, "ignition": 373, "energy": 300_000},
    "Hydrogen": {"role": "fuel", "heat_capacity": 100, "ignition": 850, "energy": 150_000},
    "Nitrous Oxide": {"role": "oxidizer", "heat_capacity": 40, "strength": 0.6},
}

AIR = {"Oxygen": 0.21, "Nitrogen": 0.79}
STANDARD_PRESSURE = 101.3
ROOM_TEMP = 293
DANGEROUS_GASES = ("Plasma", "Hydrogen", "Nitrous Oxide")

CANISTER = {"volume": 1000, "rated": 9000}
GAS_TANK = {"volume": 70, "rated": 1000}
STATION_AIR = {"volume": 2500}
RESERVOIR = {"volume": 4000, "rated": 9000}

# What is safe to breathe, as partial pressures (the total pressure for PRESSURE_MIN) in kPa.
OXYGEN_MIN = 16
CARBON_DIOXIDE_MAX = 10
PRESSURE_MIN = 50
PLASMA_MAX = 1
OXYGEN_RICH = 30
NITROUS_OXIDE_MAX = 5
