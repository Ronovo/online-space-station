import pytest

from helpers import tank_mix
from space_online.game.helper_methods.gas_mix import (
    GAS_CONSTANT,
    SPACE_TEMP,
    add_heat,
    burn,
    burn_out,
    can_burn,
    empty_mix,
    fractions,
    heat_capacity,
    merge,
    mix_of,
    moles_at,
    partial_pressure,
    pressure,
    readout,
    rupture,
    standard_air,
    take,
    total_moles,
)
from space_online.game.objects.gases import AIR, CANISTER, GAS_TANK, GASES, ROOM_TEMP, STANDARD_PRESSURE


def fuel_mix(fuel_share, total=100, temp=ROOM_TEMP, fuel="Plasma", oxidizer="Oxygen", **extra):
    mix = mix_of({fuel: fuel_share, oxidizer: 1 - fuel_share}, total, temp)
    mix["moles"].update(extra)
    return mix


def heat_energy(mix):
    return heat_capacity(mix) * mix["temp"]


def transfer_valve(fuel_tank, oxidizer_tank):
    """Opens the valve between two tanks: no spark, so it only goes off if the merged gas is hot enough."""
    merge(fuel_tank, oxidizer_tank)
    burn_out(fuel_tank)
    return rupture(fuel_tank, 2 * GAS_TANK["volume"], GAS_TANK["rated"])


def test_every_fuel_has_ignition_and_energy_and_every_oxidizer_a_strength():
    for gas in GASES.values():
        if gas["role"] == "fuel":
            assert gas["ignition"] > 0 and gas["energy"] > 0
        if gas["role"] == "oxidizer":
            assert 0 < gas["strength"] <= 1
    assert sum(AIR.values()) == pytest.approx(1)


def test_pressure_is_in_kpa_from_litres():
    assert pressure(mix_of({"Oxygen": 1}, 1, 1000), GAS_CONSTANT) == pytest.approx(1000)


def test_a_full_canister_at_room_temperature_is_about_its_rated_pressure():
    moles = 3700
    assert pressure(mix_of(AIR, moles, ROOM_TEMP), CANISTER["volume"]) == pytest.approx(CANISTER["rated"], rel=0.01)


def test_moles_at_fills_a_container_to_that_pressure():
    moles = moles_at(4500, CANISTER["volume"], 300)
    assert pressure(mix_of(AIR, moles, 300), CANISTER["volume"]) == pytest.approx(4500)


def test_standard_air_is_breathable_air_at_standard_pressure_in_any_volume():
    for volume in (70, 1000):
        air = standard_air(volume)
        assert fractions(air) == pytest.approx(AIR)
        assert (pressure(air, volume), air["temp"]) == (pytest.approx(STANDARD_PRESSURE), 293)


def test_pressure_doubles_with_moles_temperature_and_half_the_volume():
    base = pressure(mix_of(AIR, 100, ROOM_TEMP), 1000)
    assert pressure(mix_of(AIR, 200, ROOM_TEMP), 1000) == pytest.approx(2 * base)
    assert pressure(mix_of(AIR, 100, 2 * ROOM_TEMP), 1000) == pytest.approx(2 * base)
    assert pressure(mix_of(AIR, 100, ROOM_TEMP), 500) == pytest.approx(2 * base)


def test_partial_pressure_is_each_gas_share_of_the_pressure():
    air = mix_of(AIR, 100, ROOM_TEMP)
    whole = pressure(air, 1000)
    assert partial_pressure(air, 1000, "Oxygen") == pytest.approx(0.21 * whole)
    assert partial_pressure(air, 1000, "Plasma") == 0


def test_fractions_and_heat_capacity():
    air = mix_of(AIR, 100, ROOM_TEMP)
    assert fractions(air) == pytest.approx(AIR)
    assert heat_capacity(air) == pytest.approx(100 * 20)
    assert fractions(empty_mix()) == {}
    assert total_moles(empty_mix()) == 0


def test_merging_keeps_total_moles_and_heat_energy():
    hot_plasma = mix_of({"Plasma": 1}, 10, 600)
    cold_air = mix_of(AIR, 50, 250)
    moles_before = total_moles(hot_plasma) + total_moles(cold_air)
    energy_before = heat_energy(hot_plasma) + heat_energy(cold_air)
    merge(hot_plasma, cold_air)
    assert total_moles(hot_plasma) == pytest.approx(moles_before)
    assert heat_energy(hot_plasma) == pytest.approx(energy_before)
    assert 250 < hot_plasma["temp"] < 600


def test_merging_into_a_vacuum_takes_the_other_temperature():
    vacuum = empty_mix()
    merge(vacuum, mix_of(AIR, 10, ROOM_TEMP))
    assert vacuum["temp"] == pytest.approx(ROOM_TEMP)
    nothing = empty_mix()
    merge(nothing, empty_mix())
    assert nothing == empty_mix()


def test_take_leaves_the_proportions_unchanged():
    mix = fuel_mix(0.4, Nitrogen=25)
    before = fractions(mix)
    taken = take(mix, 50)
    assert total_moles(taken) == pytest.approx(50)
    assert total_moles(mix) == pytest.approx(75)
    assert fractions(mix) == pytest.approx(before)
    assert fractions(taken) == pytest.approx(before)
    assert taken["temp"] == mix["temp"]


def test_taking_more_than_there_is_empties_it():
    mix = mix_of(AIR, 10, ROOM_TEMP)
    taken = take(mix, 50)
    assert total_moles(taken) == pytest.approx(10)
    assert mix["moles"] == {}
    assert take(mix, 5)["moles"] == {}


def test_heat_raises_the_temperature_by_joules_over_heat_capacity():
    air = mix_of(AIR, 100, ROOM_TEMP)
    add_heat(air, 2000 * 50)
    assert air["temp"] == pytest.approx(ROOM_TEMP + 50)


def test_cooling_never_goes_below_space():
    air = mix_of(AIR, 100, ROOM_TEMP)
    add_heat(air, -10 ** 9)
    assert air["temp"] == SPACE_TEMP


def test_a_vacuum_holds_no_heat():
    vacuum = empty_mix()
    add_heat(vacuum, 10 ** 6)
    assert vacuum["temp"] == SPACE_TEMP


def test_readout_shows_pressure_temperature_and_each_gas():
    air = mix_of(AIR, 100, ROOM_TEMP)
    assert readout(air, 1000) == f"{pressure(air, 1000):.1f} kPa, 293 K: Oxygen 21.0%, Nitrogen 79.0%"
    assert readout(empty_mix(), 70) == "0.0 kPa, 3 K: Empty"


def test_a_cold_mix_does_not_burn_without_a_spark_and_does_with_one():
    mix = fuel_mix(0.4)
    assert not can_burn(mix)
    assert burn(mix, 1) == 0
    assert mix == fuel_mix(0.4)
    assert can_burn(mix, spark=True)
    assert burn(mix, 1, spark=True) > 0
    assert mix["temp"] > ROOM_TEMP


def test_plasma_lights_on_its_own_at_its_ignition_temperature():
    assert not can_burn(fuel_mix(0.4, temp=GASES["Plasma"]["ignition"] - 1))
    assert can_burn(fuel_mix(0.4, temp=GASES["Plasma"]["ignition"]))


def test_fuel_or_oxidizer_alone_does_not_burn():
    assert not can_burn(mix_of({"Plasma": 1}, 10, 1000), spark=True)
    assert not can_burn(mix_of({"Oxygen": 0.5, "Nitrogen": 0.5}, 10, 1000), spark=True)


def test_a_burn_uses_fuel_and_oxidizer_two_to_three_and_makes_carbon_dioxide():
    mix = fuel_mix(0.5, **{"Carbon Dioxide": 10})
    burn(mix, 1, spark=True)
    fuel_used = 50 - mix["moles"]["Plasma"]
    oxidizer_used = 50 - mix["moles"]["Oxygen"]
    assert fuel_used > 0
    assert oxidizer_used / fuel_used == pytest.approx(3 / 2)
    assert mix["moles"]["Carbon Dioxide"] == pytest.approx(10 + fuel_used + oxidizer_used)


def test_a_longer_burn_uses_more_fuel():
    short, long = fuel_mix(0.4), fuel_mix(0.4)
    burn(short, 1, spark=True)
    burn(long, 5, spark=True)
    assert long["moles"]["Plasma"] < short["moles"]["Plasma"]


@pytest.mark.parametrize("fuel", ["Plasma", "Hydrogen"])
@pytest.mark.parametrize("seconds", [1, 5])
def test_the_clean_ratio_burns_hotter_than_rich_or_lean(fuel, seconds):
    clean, rich, lean = (fuel_mix(share, fuel=fuel) for share in (0.4, 0.6, 0.2))
    for mix in (clean, rich, lean):
        burn(mix, seconds, spark=True)
    assert clean["temp"] > rich["temp"]
    assert clean["temp"] > lean["temp"]


def test_burning_out_a_rich_mix_leaves_fuel_and_a_lean_one_leaves_oxidizer():
    clean, rich, lean = fuel_mix(0.4), fuel_mix(0.6), fuel_mix(0.2)
    for mix in (clean, rich, lean):
        burn_out(mix, spark=True)
        assert not can_burn(mix, spark=True)
    assert set(clean["moles"]) == {"Carbon Dioxide"}
    assert "Plasma" in rich["moles"] and "Oxygen" not in rich["moles"]
    assert "Oxygen" in lean["moles"] and "Plasma" not in lean["moles"]
    assert clean["temp"] > rich["temp"] and clean["temp"] > lean["temp"]


def test_nitrogen_soaks_up_heat_so_a_diluted_burn_ends_cooler():
    plain, diluted = fuel_mix(0.4), fuel_mix(0.4, Nitrogen=100)
    plain_joules = burn_out(plain, spark=True)
    assert burn_out(diluted, spark=True) == pytest.approx(plain_joules)
    assert diluted["temp"] < plain["temp"]


def test_hydrogen_burns_cooler_than_plasma():
    plasma, hydrogen = fuel_mix(0.4), fuel_mix(0.4, fuel="Hydrogen")
    burn_out(plasma, spark=True)
    burn_out(hydrogen, spark=True)
    assert hydrogen["temp"] < plasma["temp"]


def test_nitrous_oxide_releases_less_than_oxygen():
    oxygen, nitrous = fuel_mix(0.4), fuel_mix(0.4, oxidizer="Nitrous Oxide")
    assert burn_out(nitrous, spark=True) < burn_out(oxygen, spark=True)
    assert nitrous["temp"] < oxygen["temp"]


def test_burning_plasma_heats_hydrogen_until_it_burns_too():
    mix = mix_of({"Plasma": 0.1, "Hydrogen": 0.1, "Oxygen": 0.8}, 100, GASES["Plasma"]["ignition"])
    burn_out(mix)
    assert "Plasma" not in mix["moles"]
    assert "Hydrogen" not in mix["moles"]


def test_rupture_is_zero_at_the_rated_pressure_and_above_zero_past_it():
    volume, rated = GAS_TANK["volume"], GAS_TANK["rated"]
    at_rated = rated * volume / (GAS_CONSTANT * ROOM_TEMP)
    assert rupture(mix_of(AIR, at_rated, ROOM_TEMP), volume, rated) == 0
    assert rupture(mix_of(AIR, at_rated * 1.01, ROOM_TEMP), volume, rated) > 0
    assert rupture(mix_of(AIR, at_rated * 3, ROOM_TEMP), volume, rated) == pytest.approx(3)


def test_a_transfer_valve_needs_hot_plasma_to_go_off():
    assert transfer_valve(tank_mix("Plasma", 0.9), tank_mix("Oxygen", 0.9)) == 0
    assert transfer_valve(tank_mix("Plasma", 0.9, 500), tank_mix("Oxygen", 0.9)) > 1


def test_a_transfer_valve_blast_grows_with_how_full_the_tanks_are():
    blasts = [transfer_valve(tank_mix("Plasma", fill, 500), tank_mix("Oxygen", fill))
              for fill in (0.25, 0.5, 1.0)]
    assert 1 < blasts[0] < blasts[1] < blasts[2]
    assert blasts[2] > 2 * blasts[0]
