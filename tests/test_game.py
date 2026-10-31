import json

import pytest

from helpers import new_game, reports
from space_online.game.character_methods.character_creation import (
    JOBS,
    MAX_NAME_LENGTH,
    SELECT_DEPARTMENT,
    create_character,
    group_jobs_by_department,
)
from space_online.game.helper_methods.alcohol_helper import ALCOHOL_DECAY_AMOUNT, ALCOHOL_DECAY_SECONDS, apply_alcohol_tick
from space_online.game.helper_methods.door_control import SPECIAL_ROOM_DOORS, can_control_door
from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.jail import security_hallway_location, tick_jail_releases
from space_online.game.helper_methods.oxygen_helper import (
    DEATH_THRESHOLD,
    POST_DEATH_OXYGEN,
    oxygen_damage_for_tick,
)
from space_online.game.main import SpaceStationGame
from space_online.game.helper_methods.random_events import build_job_event
from space_online.game.helper_methods.stock_market import buy, round_credits, sell
from space_online.game.maps import donut
from space_online.game.maps.donut import BRIDGE_KEY, MEDBAY_KEY, QUARTERS_LOCATION
from space_online.game.objects import botany_items
from space_online.game.objects.botany_items import BOTANY_SEED_IDS, GROWTH_STAGES, refresh_planter_growth
from space_online.game.objects.drinks import MAX_GLASS_POURS, add_ingredient
from space_online.game.objects.items import add_to_inventory, get_item_definition, inventory_item_count
from space_online.game.special_rooms.botany import harvest
from space_online.game.special_rooms.bridge import approve
from space_online.game.special_rooms.engineering import _update_system_level
from space_online.game.special_rooms.med_bay import pay_for_healing
from space_online.game.special_rooms.security import confirm, pardon
from space_online.game.special_rooms.shared import MAX_NOTES, PLAYER_CREW_INDEX, add_note


def test_every_job_is_listed_under_exactly_one_department():
    listed = [job for _, jobs in group_jobs_by_department() for job in jobs]
    assert sorted(listed) == sorted(JOBS)


def test_create_character_uses_job_details():
    player = create_character("  Ada  ", "Medical", "Doctor")
    assert player["name"] == "Ada"
    assert player["credits"] == JOBS["Doctor"]["credits"]
    assert player["subdepartment"] == "Doctor"
    assert can_control_door(player, MEDBAY_KEY)
    assert not can_control_door(player, BRIDGE_KEY)


@pytest.mark.parametrize("name, department, job, message", [
    ("", "Civilian", "Staff Assistant", "Please enter a character name."),
    ("x" * (MAX_NAME_LENGTH + 1), "Civilian", "Staff Assistant", "at most"),
    ("Ada", SELECT_DEPARTMENT, "Staff Assistant", "Please select a department."),
    ("Ada", "Civilian", "Engineer", "Please select a job."),
    ("Ada", "Civilian", "Not A Job", "Please select a job."),
])
def test_create_character_rejects_bad_input(name, department, job, message):
    with pytest.raises(ValueError, match=message):
        create_character(name, department, job)


def test_door_control_follows_job():
    captain = create_character("Cap", "Administration", "Captain")
    doctor = create_character("Doc", "Medical", "Doctor")
    assistant = create_character("Sam", "Civilian", "Staff Assistant")

    assert all(can_control_door(captain, key) for key in SPECIAL_ROOM_DOORS)
    assert [key for key in SPECIAL_ROOM_DOORS if can_control_door(doctor, key)] == [MEDBAY_KEY]
    assert not any(can_control_door(assistant, key) for key in SPECIAL_ROOM_DOORS)
    assert not can_control_door(captain, "no-such-door")


def test_inventory_stacks_items_except_basic_tools():
    player = {"inventory": []}
    wrench = get_item_definition("wrench")
    add_to_inventory(player, wrench)
    add_to_inventory(player, wrench)
    assert len(player["inventory"]) == 1
    assert inventory_item_count(player) == 2

    tools = get_item_definition("basic_tools")
    add_to_inventory(player, tools)
    add_to_inventory(player, tools)
    assert len(player["inventory"]) == 3
    assert inventory_item_count(player) == 4


def test_game_ticks_renders_and_saves_as_json():
    game = SpaceStationGame(create_character("Ada", "Civilian", "Staff Assistant"))
    game.player_data["game_clock"]["last_real_time"] -= 5
    game.tick()
    assert game.player_data["game_clock"]["elapsed_seconds"] >= 5
    view = game.view()
    assert view["title"]
    assert view["redirect"] is None
    json.dumps(game.to_save_data())


def test_oxygen_damage_adds_up_over_short_ticks():
    short = create_character("Ada", "Civilian", "Staff Assistant")
    total = sum(oxygen_damage_for_tick(short, 0, 1.0) for _ in range(120))
    once = oxygen_damage_for_tick(create_character("Bo", "Civilian", "Staff Assistant"), 0, 120.0)
    assert once > 0
    assert abs(total - once) <= 1


def test_running_out_of_oxygen_sends_the_player_back_to_quarters():
    game = new_game()
    game.player_data["station_power"]["system_levels"]["life_support"] = 0
    game.player_data["damage"]["oxygen"] = DEATH_THRESHOLD - 1
    game.player_data["location"] = donut.location_from_tile(donut.SPECIAL_ROOM_HALLWAY[MEDBAY_KEY])
    game.check_life_support_status(600, get_elapsed_seconds(game.player_data))
    assert game.player_data["damage"]["oxygen"] == POST_DEATH_OXYGEN
    assert game.player_data["location"] == QUARTERS_LOCATION


def test_life_support_already_at_zero_is_not_announced_again():
    game = new_game("Engineering", "Engineer")
    _update_system_level(game, "life_support", 0)
    game.player_data.pop("announcements")
    _update_system_level(game, "life_support", 0)
    assert "announcements" not in game.player_data


def test_the_battery_running_flat_causes_an_outage():
    game = new_game()
    power = game.player_data["station_power"]
    power["solar_charging"] = False
    power["battery_level"] = 0.01
    game._tick_power(600)
    assert power["battery_level"] == 0
    assert "Power Outage" in reports(game)
    game._tick_power(600)
    assert reports(game).count("Power Outage") == 1


def test_walking_never_steps_onto_a_room_door():
    game = new_game()
    for room_key, (hx, hy) in donut.SPECIAL_ROOM_HALLWAY.items():
        room = donut.location_from_key(room_key)
        for direction, (dx, dy) in donut.DIRECTION_STEPS.items():
            if (hx + dx, hy + dy) == (room["x"], room["y"]):
                game.player_data["location"] = {"x": hx, "y": hy}
                game.move(direction)
                assert game.player_data["location"] == {"x": hx, "y": hy}


def test_a_locked_door_does_not_keep_the_player_in():
    game = new_game()
    game.player_data["location"] = donut.location_from_key(MEDBAY_KEY)
    game.ship_map[MEDBAY_KEY]["locked"] = True
    game.perform("room.exit", {})
    hx, hy = donut.SPECIAL_ROOM_HALLWAY[MEDBAY_KEY]
    assert game.player_data["location"] == {"x": hx, "y": hy}


def test_a_finished_sentence_releases_the_player():
    game = new_game()
    game.player_data.update(in_jail=True, warrant=True, jail_release_at_seconds=0)
    game.player_data["location"] = donut.location_from_key(donut.SECURITY_KEY)
    tick_jail_releases(game)
    assert game.player_data["in_jail"] is False
    assert game.player_data["warrant"] is False
    assert game.player_data["location"] == security_hallway_location()


def test_fines_add_up_with_their_reasons():
    game = new_game("Security", "Security Guard")
    state = {"crew_index": PLAYER_CREW_INDEX, "kind": "fine"}
    confirm(game, state, {"reason": "loitering", "amount": "10"})
    confirm(game, state, {"reason": "littering", "amount": "5"})
    assert game.player_data["fine_amount"] == 15
    assert game.player_data["fine_reason"] == "loitering; littering"


def test_buying_and_selling_shares_moves_credits_and_holdings():
    game = new_game()
    company = game.market_engine.companies[0]
    company.current_value = 1.23
    state = {"selected": company.name}
    credits = game.player_data["credits"]
    buy(game, state, {"shares": "3"})
    assert game.player_data["stock_holdings"] == {company.name: 3}
    assert game.player_data["credits"] == round_credits(credits - 3.69)
    sell(game, state, {"shares": "4"})
    assert game.player_data["stock_holdings"] == {company.name: 3}
    sell(game, state, {"shares": "3"})
    assert game.player_data["stock_holdings"] == {}
    assert game.player_data["credits"] == credits


def test_the_hop_approves_a_pending_request():
    game = new_game("Administration", "Head of Personnel")
    game.player_data["access_request"] = {"requested_job": "Doctor", "requester_name": "Ada"}
    approve(game, {}, {})
    assert game.player_data["job"] == "Doctor"
    assert "access_request" not in game.player_data


def test_alcohol_wears_off_over_time():
    player = create_character("Ada", "Civilian", "Staff Assistant")
    player["alcohol_percent"] = 3 * ALCOHOL_DECAY_AMOUNT
    apply_alcohol_tick(player, 2 * ALCOHOL_DECAY_SECONDS + 1)
    assert player["alcohol_percent"] == ALCOHOL_DECAY_AMOUNT
    apply_alcohol_tick(player, ALCOHOL_DECAY_SECONDS)
    assert player["alcohol_percent"] == 0
    assert player["damage_timers"]["alcohol_decay_acc"] == 0


def test_the_doctor_charges_for_treatment():
    game = new_game()
    game.player_data["limbs"]["head"] = 60
    game.player_data["credits"] = 100
    pay_for_healing(game)
    assert game.player_data["limbs"]["head"] == 100
    assert game.player_data["credits"] == 60


def test_restoring_life_support_clears_the_emergency_announcement():
    game = SpaceStationGame(create_character("Ada", "Engineering", "Engineer"))
    _update_system_level(game, "life_support", 0)
    assert game.player_data["announcements"]
    _update_system_level(game, "life_support", 10)
    assert "announcements" not in game.player_data


def test_notes_keep_only_the_newest():
    player = create_character("Ada", "Civilian", "Staff Assistant")
    for n in range(MAX_NOTES + 5):
        add_note(player, f"note {n}")
    assert len(player["notes"]) == MAX_NOTES
    assert player["notes"][-1]["text"] == f"note {MAX_NOTES + 4}"


@pytest.mark.parametrize("due, stage, dead", [(2, 2, False), (4, 2, True)])
def test_one_watering_carries_a_plant_through_one_stage(monkeypatch, due, stage, dead):
    monkeypatch.setattr(botany_items, "compute_growth_stage", lambda *args: due)
    planter = {"occupied": True, "planted_at_seconds": 0, "growth_stage": 1, "watered": True, "growth_class": "fast"}
    assert refresh_planter_growth(planter, 999) == stage
    assert planter.get("dead", False) is dead
    assert planter["watered"] is False


def test_a_jailed_player_cannot_pardon_anyone():
    game = SpaceStationGame(create_character("Ada", "Security", "Security Guard"))
    game.player_data["in_jail"] = True
    pardon(game, {"selected": -1}, {})
    assert game.player_data["in_jail"] is True


def test_an_invalid_location_goes_back_to_quarters():
    game = SpaceStationGame(create_character("Ada", "Civilian", "Staff Assistant"))
    game.player_data["location"] = {"x": 999, "y": 999}
    game._normalize_location()
    assert game.player_data["location"] == QUARTERS_LOCATION


def test_the_mixer_glass_has_a_limit():
    game = SpaceStationGame(create_character("Ada", "Civilian", "Bartender"))
    state = {"selected_ingredient": "Vodka", "glass": ["Vodka"] * MAX_GLASS_POURS}
    add_ingredient(game, state, {})
    assert len(state["glass"]) == MAX_GLASS_POURS


def test_the_botanist_is_only_asked_for_crops_botany_grows():
    game = SpaceStationGame(create_character("Ada", "Civilian", "Botanist"))
    crops = {seed.removesuffix("_seeds") for seed in BOTANY_SEED_IDS}
    for _ in range(20):
        event = build_job_event(game)
        assert any(f" {crop} " in event["desc"] for crop in crops)


def test_a_mature_planter_harvests_into_inventory():
    game = new_game()
    planters = game.player_data["botany"]["planters"]
    planters[0].update(occupied=True, produces="tomato", growth_stage=GROWTH_STAGES, yield_multiplier=2)
    harvest(game, {"row": 0, "allow_harvest": True}, {"index": 0})
    assert [(item["id"], item["quantity"]) for item in game.player_data["inventory"]] == [("tomato", 2)]
    assert planters[0]["occupied"] is False
