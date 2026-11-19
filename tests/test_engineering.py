import pytest

from helpers import buttons, crew, give, in_room, labels, last_message, notes, open_station, panel, reports
from space_online.game.helper_methods.game_clock import format_elapsed
from space_online.game.helper_methods.oxygen_helper import (
    LIFE_SUPPORT_DAMAGE_BEGIN_TITLE,
    OXYGEN_DEPLETION_FOLLOWUP_TITLE,
)
from space_online.game.helper_methods.station_air import AIR_LASTS_SECONDS
from space_online.game.helper_methods.lighting_helper import clamp_lighting_for_battery
from space_online.game.helper_methods.power_constants import BALANCED_SYSTEM_LEVELS, fault_system
from space_online.game.helper_methods.stores import STARTING_ORE
from space_online.game.maps.donut import ENGINEERING_KEY
from space_online.game.objects.items import get_item_definition
from space_online.game.special_rooms.engineering import POWER_MODE_LEVELS, repair_system


def in_engineering(department="Civilian", job="Staff Assistant"):
    return in_room(ENGINEERING_KEY, department, job)


def engineering_panel(game):
    return open_station(game, "engineering_station", "access_engineering_panel")


def levels(game):
    return game.player_data["station_power"]["system_levels"]


def test_visitors_can_fabricate_and_talk_to_the_engineer():
    game = in_engineering()
    assert buttons(game) == [("Access Fabricator", "room.access_fabricator"),
                             ("Talk to Engineer", "room.talk_to_engineer")]
    game.perform("room.talk_to_engineer", {})
    assert last_message(game) == ("Engineer", "The engineer barely glances up from the console. 'Kinda busy here.'")


def test_the_engineer_works_the_station():
    game = in_engineering("Engineering", "Engineer")
    assert labels(game) == ["Enter Engineering Station", "Lock/Unlock Door", "Room Options"]
    game.perform("room.open_station", {"mode": "engineering_station"})
    assert buttons(game) == [("Engineering Station Controls", None), ("Engineering Panel", "room.access_engineering_panel"),
                             ("Combustion Engine", "room.access_combustion_engine"),
                             ("Back to Station Menu", "room.set_mode")]
    game.perform("room.access_engineering_panel", {})
    assert panel(game)["type"] == "engineering_panel"
    game.ui["panels"] = []
    game.perform("room.set_mode", {"mode": "options"})
    assert buttons(game) == [("Access Fabricator", "room.access_fabricator"), ("Back to Station Menu", "room.set_mode")]


def test_visitors_cannot_open_the_engineering_panel():
    game = engineering_panel(in_engineering())
    assert game.ui["panels"] == []
    assert buttons(game)[0] == ("Access Fabricator", "room.access_fabricator")


def fabricator(game):
    game.perform("room.access_fabricator", {})
    return panel(game)["ctx"]


def test_fabricating_an_item():
    game = in_engineering()
    ctx = fabricator(game)
    assert (ctx["categories"], ctx["category"], ctx["item_names"]) == (
        ["Tool", "Book", "Weapon"], "Tool", ["Wrench (1 ore)", "Screwdriver (1 ore)", "Wirecutters (1 ore)",
                                             "Repair Tool (2 ore)", "Fire Extinguisher (1 ore)",
                                             "Basic Tools (3 ore)", "Gas Analyzer (2 ore)",
                                                 "Tank Transfer Valve (3 ore)"])
    assert ctx["ore"] == STARTING_ORE
    game.perform("panel.select", {"index": 5})
    game.perform("panel.create", {})
    assert game.player_data["stores"]["ore"] == STARTING_ORE - 3
    assert game.player_data["inventory"][0]["id"] == "basic_tools"
    assert len(game.player_data["inventory"][0]["attributes"]["contents"]) == 3
    assert panel(game)["ctx"]["feedback"]["text"] == "'Basic Tools' created successfully."
    assert notes(game)[-1] == "Fabricated a Basic Tools (basic_tools) in Engineering."


def test_the_fabricator_needs_ore_from_the_station_stores_and_books_are_free():
    game = in_engineering()
    game.player_data["stores"]["ore"] = 2
    fabricator(game)
    game.perform("panel.select", {"index": 5})
    game.perform("panel.create", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "Not enough ore in the station stores: a Basic Tools takes 3."
    assert (game.player_data["inventory"], game.player_data["stores"]["ore"]) == ([], 2)
    game.perform("panel.category", {"name": "Book"})
    assert panel(game)["ctx"]["item_names"] == ["Welcome Guide", "Station Map"]
    game.perform("panel.select", {"index": 0})
    game.perform("panel.create", {})
    assert (game.player_data["inventory"][0]["id"], game.player_data["stores"]["ore"]) == ("welcome_guide", 2)


def test_examining_a_fabricator_item_keeps_the_text_up():
    game = in_engineering()
    fabricator(game)
    game.perform("panel.category", {"name": "Book"})
    game.perform("panel.select", {"index": 1})
    game.perform("panel.examine", {})
    feedback = panel(game)["ctx"]["feedback"]
    assert feedback["text"].startswith("Examine: ") and feedback["until"] is None


def test_the_fabricator_needs_an_item_picked():
    game = in_engineering()
    fabricator(game)
    game.perform("panel.create", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "Please select a category and an item."
    game.perform("panel.select", {"index": 9})
    assert panel(game)["ctx"]["selected"] is None
    game.perform("panel.examine", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "Please select a category and an item to examine."
    game.perform("panel.category", {"name": "Weapons"})
    assert panel(game)["ctx"]["category"] == "Tool"
    assert game.player_data["inventory"] == []


def test_the_engineering_panel_reads_the_battery_and_systems():
    game = engineering_panel(in_engineering("Engineering", "Engineer"))
    power = game.player_data["station_power"]
    power.update(battery_level=8.0, solar_charging=False)
    levels(game).update(life_support=0, hallway_lighting=3, security_systems=8)
    ctx = panel(game)["ctx"]
    assert (ctx["battery_status"], ctx["battery_icon"], ctx["battery_color"]) == ("Critical power level", "⚠️", "#FF0000")
    systems = {s["key"]: s for s in ctx["systems"]}
    assert (systems["life_support"]["online"], systems["life_support"]["draw"]) == (
        False, {"text": "Power draw: None (System OFF)", "color": "#FF0000"})
    assert systems["hallway_lighting"]["draw"] == {"text": "Power draw: 0.09% per minute", "color": "#00FF00"}
    assert systems["communication_array"]["draw"]["color"] == "#FFAA00"
    assert systems["security_systems"]["draw"]["color"] == "#FF5500"


@pytest.mark.parametrize("battery, status, icon", [(30.0, "Low power mode", "🔋"), (80.0, "Normal operation", "🔋")])
def test_battery_status_above_critical(battery, status, icon):
    game = engineering_panel(in_engineering("Engineering", "Engineer"))
    game.player_data["station_power"]["battery_level"] = battery
    ctx = panel(game)["ctx"]
    assert (ctx["battery_status"], ctx["battery_icon"]) == (status, icon)


def test_switching_the_solar_array():
    game = engineering_panel(in_engineering("Engineering", "Engineer"))
    game.perform("panel.toggle_solar", {})
    assert last_message(game) == ("Solar Control", "Solar arrays activated. Batteries now charging from solar power.")
    game.perform("panel.toggle_solar", {})
    assert last_message(game) == ("Solar Control", "Solar arrays deactivated. Battery charging stopped.")
    assert panel(game)["ctx"]["solar"] is False


def test_setting_a_system_level_stays_within_0_and_10():
    game = engineering_panel(in_engineering("Engineering", "Engineer"))
    game.perform("panel.set_level", {"system": "hallway_lighting", "value": "7"})
    game.perform("panel.set_level", {"system": "hallway_lighting", "value": "11"})
    game.perform("panel.set_level", {"system": "warp_drive", "value": "5"})
    assert levels(game)["hallway_lighting"] == 7
    assert "warp_drive" not in levels(game)


def test_a_power_mode_sets_every_system():
    game = engineering_panel(in_engineering("Engineering", "Engineer"))
    game.perform("panel.set_power_mode", {"mode": "emergency"})
    assert (game.player_data["station_power"]["power_mode"], levels(game)) == (
        "emergency", {"life_support": 10, "hallway_lighting": 1, "security_systems": 3, "communication_array": 1})


@pytest.mark.parametrize("action, args", [("panel.set_level", {"system": "hallway_lighting", "value": "2"}),
                                          ("panel.set_power_mode", {"mode": "emergency"})])
def test_lighting_set_from_the_panel_is_no_longer_a_dim_to_undo(action, args):
    game = engineering_panel(in_engineering("Engineering", "Engineer"))
    power = game.player_data["station_power"]
    power["dimmed_from"] = 6
    game.perform("panel.set_level", {"system": "security_systems", "value": "4"})
    assert power["dimmed_from"] == 6
    game.perform(action, args)
    assert power["dimmed_from"] is None


def test_repairing_faulted_lighting_keeps_the_dim_to_undo():
    game = faulted(in_engineering(), "hallway_lighting")
    game.player_data["station_power"]["dimmed_from"] = 6
    repair_system(game, "hallway_lighting")
    assert game.player_data["station_power"]["dimmed_from"] == 6


def test_an_unknown_power_mode_changes_nothing():
    game = engineering_panel(in_engineering("Engineering", "Engineer"))
    game.perform("panel.set_power_mode", {"mode": "overdrive"})
    assert (game.player_data["station_power"]["power_mode"], levels(game)) == ("balanced", BALANCED_SYSTEM_LEVELS)


def test_the_panel_controls_check_clearance_even_with_the_panel_open():
    game = in_engineering()
    power = game.player_data["station_power"]
    solar = power["solar_charging"]
    game.open_panel("engineering_panel")
    game.perform("panel.toggle_solar", {})
    game.perform("panel.set_level", {"system": "life_support", "value": "0"})
    game.perform("panel.set_power_mode", {"mode": "high"})
    assert (power["solar_charging"], power["power_mode"], power["system_levels"]) == (
        solar, "balanced", BALANCED_SYSTEM_LEVELS)


def test_switching_life_support_off_announces_how_long_the_air_will_last():
    game = engineering_panel(in_engineering("Engineering", "Engineer"))
    game.perform("panel.set_level", {"system": "life_support", "value": "0"})
    assert panel(game)["type"] == "oxygen_announcement"
    assert len(game.player_data["announcements"]) == 1
    game.perform("panel.acknowledge", {})
    assert reports(game) == [OXYGEN_DEPLETION_FOLLOWUP_TITLE]
    assert f"The air will last about {format_elapsed(AIR_LASTS_SECONDS)}" in last_message(game)[1]
    assert panel(game)["type"] == "engineering_panel"


def test_the_announcement_is_made_once():
    game = engineering_panel(in_engineering("Engineering", "Engineer"))
    game.perform("panel.set_level", {"system": "life_support", "value": "0"})
    game.ui["panels"].pop()
    game.perform("panel.set_level", {"system": "life_support", "value": "0"})
    levels(game)["life_support"] = 3
    game.perform("panel.set_level", {"system": "life_support", "value": "0"})
    assert len(game.player_data["announcements"]) == 1
    assert [panel["type"] for panel in game.ui["panels"]] == ["engineering_panel"]


def test_turning_life_support_back_on_ends_the_announcement():
    game = engineering_panel(in_engineering("Engineering", "Engineer"))
    game.perform("panel.set_level", {"system": "life_support", "value": "0"})
    game.ui["panels"].pop()
    game.perform("panel.set_level", {"system": "life_support", "value": "8"})
    assert "announcements" not in game.player_data
    assert game.ui["announcement_active"] is False
    assert last_message(game) == ("Engineering Panel", "Life Support back on at level 8.")


def test_lowering_life_support_to_where_the_pumps_cant_keep_up_warns_once():
    game = engineering_panel(in_engineering("Engineering", "Engineer"))
    game.perform("panel.set_level", {"system": "life_support", "value": "5"})
    assert reports(game) == []
    game.perform("panel.set_level", {"system": "life_support", "value": "4"})
    game.perform("panel.set_level", {"system": "life_support", "value": "3"})
    assert reports(game) == [LIFE_SUPPORT_DAMAGE_BEGIN_TITLE]


def faulted(game, system="security_systems"):
    fault_system(game.player_data["station_power"], system)
    return game


def test_a_faulted_system_shows_on_the_panel_and_stays_off():
    game = engineering_panel(faulted(in_engineering("Engineering", "Engineer")))
    system = next(s for s in panel(game)["ctx"]["systems"] if s["key"] == "security_systems")
    assert (system["faulted"], system["value"], system["online"]) == (True, 0, False)
    game.perform("panel.set_level", {"system": "security_systems", "value": "5"})
    assert last_message(game) == ("System Fault", "Security Systems is faulted. Repair it before powering it back up.")
    game.perform("panel.set_level", {"system": "security_systems", "value": "0"})
    game.perform("panel.set_power_mode", {"mode": "high"})
    assert levels(game)["security_systems"] == 0
    assert levels(game)["communication_array"] == POWER_MODE_LEVELS["high"]["communication_array"]


def test_repairing_needs_tools_and_a_wrench_alone_is_not_enough():
    game = engineering_panel(faulted(in_engineering("Engineering", "Engineer")))
    give(game, "wrench")
    game.perform("panel.repair", {"system": "security_systems"})
    assert last_message(game) == ("Repair", "You need Basic Tools or a Repair Tool to repair the Security Systems.")
    assert game.player_data["station_power"]["faults"] == ["security_systems"]


@pytest.mark.parametrize("where", ["inventory", "hand"])
def test_repairing_with_tools_brings_the_system_back_at_the_level_it_had(where):
    game = engineering_panel(in_engineering("Engineering", "Engineer"))
    game.perform("panel.set_level", {"system": "security_systems", "value": "4"})
    faulted(game)
    if where == "inventory":
        give(game, "basic_tools")
    else:
        game.player_data["hands"]["right"] = get_item_definition("repair_tool")
    game.perform("panel.set_power_mode", {"mode": "low"})
    game.perform("panel.repair", {"system": "security_systems"})
    name = "Basic Tools" if where == "inventory" else "Repair Tool"
    power = game.player_data["station_power"]
    assert (power["faults"], power["fault_levels"], levels(game)["security_systems"]) == ([], {}, 4)
    assert last_message(game) == ("Repair", f"You repair the Security Systems with the {name}. It is back online.")
    assert notes(game)[-1] == f"Repaired the Security Systems with the {name}."


def test_only_faulted_systems_are_repaired_and_only_with_clearance():
    game = give(faulted(in_engineering()), "repair_tool")
    game.open_panel("engineering_panel")
    game.perform("panel.repair", {"system": "security_systems"})
    game.perform("panel.repair", {"system": "life_support"})
    assert (game.player_data["station_power"]["faults"], game._messages) == (["security_systems"], [])


def test_faulted_lighting_ignores_the_battery_lighting_bands():
    game = faulted(in_engineering(), "hallway_lighting")
    power = game.player_data["station_power"]
    band = power["last_lighting_battery_band"]
    power["battery_level"] = 80
    clamp_lighting_for_battery(power)
    assert (power["system_levels"]["hallway_lighting"], power["last_lighting_battery_band"]) == (0, band)


def test_a_battery_band_crossed_while_lighting_is_faulted_is_applied_after_the_repair():
    game = in_engineering()
    power = game.player_data["station_power"]
    power.update(battery_level=50, last_lighting_battery_band="normal")
    power["system_levels"]["hallway_lighting"] = 7
    faulted(game, "hallway_lighting")
    power["battery_level"] = 4.5
    clamp_lighting_for_battery(power)
    repair_system(game, "hallway_lighting")
    assert power["system_levels"]["hallway_lighting"] == 7
    clamp_lighting_for_battery(power)
    assert (power["system_levels"]["hallway_lighting"], power["last_lighting_battery_band"]) == (2, "emergency")


def test_the_engineer_only_talks_when_they_are_in():
    game = in_engineering()
    crew(game, "Engineer")["on_duty"] = False
    game.perform("room.talk_to_engineer", {})
    assert game._messages == []


def test_switching_a_system_off_or_back_on_is_logged_and_other_moves_are_not():
    game = engineering_panel(in_engineering("Engineering", "Engineer"))
    game.perform("panel.set_level", {"system": "security_systems", "value": "4"})
    assert reports(game) == []
    game.perform("panel.set_level", {"system": "security_systems", "value": "0"})
    assert last_message(game) == ("Engineering Panel", "Security Systems switched off.")
    game.perform("panel.set_level", {"system": "security_systems", "value": "6"})
    assert last_message(game) == ("Engineering Panel", "Security Systems back on at level 6.")
    assert reports(game) == ["Engineering Panel", "Engineering Panel"]


def test_switching_categories_clears_what_the_fabricator_last_said():
    game = in_engineering()
    fabricator(game)
    game.perform("panel.select", {"index": 0})
    game.perform("panel.examine", {})
    assert panel(game)["ctx"]["feedback"] is not None
    game.perform("panel.category", {"name": "Book"})
    assert panel(game)["ctx"]["feedback"] is None
