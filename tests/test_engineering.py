import pytest

from helpers import new_game, reports
from space_online.game.helper_methods.oxygen_helper import (
    LIFE_SUPPORT_DAMAGE_BEGIN_TITLE,
    OXYGEN_DEPLETION_FOLLOWUP_TITLE,
    OXYGEN_DEPLETION_GRACE_SECONDS,
)
from space_online.game.helper_methods.power_constants import BALANCED_SYSTEM_LEVELS
from space_online.game.maps.donut import ENGINEERING_KEY, location_from_key
from space_online.game.special_rooms.engineering import POWER_MODE_LEVELS


def in_engineering(department="Civilian", job="Staff Assistant"):
    game = new_game(department, job)
    game.player_data["location"] = location_from_key(ENGINEERING_KEY)
    return game


def buttons(game):
    return [(w.get("label") or w.get("text"), w.get("action")) for w in game.view()["screen"]["buttons"]]


def panel(game):
    return game.view()["panel"]


def last_message(game):
    return game._messages[-1][1:3]


def engineering_panel(game):
    game.ui["panels"] = []
    game.ui["room_mode"] = "engineering_station"
    game.perform("room.access_engineering_panel", {})
    return game


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
    assert [label for label, _ in buttons(game)] == ["Enter Engineering Station", "Lock/Unlock Door", "Room Options"]
    game.perform("room.open_station", {"mode": "engineering_station"})
    assert buttons(game) == [("Engineering Station Controls", None), ("Engineering Panel", "room.access_engineering_panel"),
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
        ["Tool", "Book"], "Tool", ["Wrench", "Screwdriver", "Wirecutters", "Basic Tools"])
    game.perform("panel.select", {"index": 3})
    game.perform("panel.create", {})
    assert game.player_data["inventory"][0]["id"] == "basic_tools"
    assert len(game.player_data["inventory"][0]["attributes"]["contents"]) == 3
    assert panel(game)["ctx"]["feedback"]["text"] == "'Basic Tools' created successfully."
    assert game.player_data["notes"][-1]["text"] == "Fabricated a Basic Tools (basic_tools) in Engineering."


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


@pytest.mark.parametrize("mode", ["balanced", "high", "low", "emergency"])
def test_power_modes_set_every_system(mode):
    game = engineering_panel(in_engineering("Engineering", "Engineer"))
    game.perform("panel.set_power_mode", {"mode": mode})
    assert (game.player_data["station_power"]["power_mode"], levels(game)) == (mode, POWER_MODE_LEVELS[mode])


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


def test_switching_life_support_off_announces_a_grace_period():
    game = engineering_panel(in_engineering("Engineering", "Engineer"))
    game.player_data["game_clock"]["elapsed_seconds"] = 100
    game.perform("panel.set_level", {"system": "life_support", "value": "0"})
    assert panel(game)["type"] == "oxygen_announcement"
    assert game.player_data["damage_timers"]["oxygen_depletion"] == {
        "active": True, "damage_starts_at_seconds": 100 + OXYGEN_DEPLETION_GRACE_SECONDS}
    assert len(game.player_data["announcements"]) == 1
    game.perform("panel.acknowledge", {})
    assert reports(game) == [OXYGEN_DEPLETION_FOLLOWUP_TITLE]
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
    assert reports(game) == []


def test_lowering_life_support_into_the_damage_range_warns():
    game = engineering_panel(in_engineering("Engineering", "Engineer"))
    game.perform("panel.set_level", {"system": "life_support", "value": "4"})
    game.perform("panel.set_level", {"system": "life_support", "value": "3"})
    assert reports(game) == [LIFE_SUPPORT_DAMAGE_BEGIN_TITLE]
