import json

import pytest

from helpers import new_game
from space_online.game.character_methods.character_creation import (
    JOBS,
    MAX_NAME_LENGTH,
    group_jobs_by_department,
    new_shift,
)
from space_online.game.helper_methods.alcohol_helper import ALCOHOL_DECAY_AMOUNT, ALCOHOL_DECAY_SECONDS, apply_alcohol_tick
from space_online.game.helper_methods.door_control import can_control_door
from space_online.game.maps.donut import LOCKABLE_ROOM_KEYS
from space_online.game.helper_methods.oxygen_helper import damage_for_tick
from space_online.game.main import SpaceStationGame
from space_online.game.helper_methods.random_events import build_job_event
from space_online.game.maps import donut
from space_online.game.maps.donut import DEPARTURES_KEY, MEDBAY_KEY
from space_online.game.objects import botany_items
from space_online.game.objects.botany_items import BOTANY_SEED_IDS
from space_online.game.objects.items import get_item_definition
from space_online.game.special_rooms.bridge import approve
from space_online.game.special_rooms.engineering import set_system_level
from space_online.game.special_rooms.shared import MAX_NOTES, add_note


def test_every_job_is_listed_under_exactly_one_department():
    listed = [job for _, jobs in group_jobs_by_department() for job in jobs]
    assert sorted(listed) == sorted(JOBS)


def test_a_shift_starts_with_the_jobs_details():
    player = new_shift("  Ada  ", "Doctor")
    assert player["name"] == "Ada"
    assert player["credits"] == JOBS["Doctor"]["credits"]
    assert player["subdepartment"] == "Doctor"


@pytest.mark.parametrize("name, job, message", [
    ("   ", "Staff Assistant", "Please enter a character name."),
    ("x" * (MAX_NAME_LENGTH + 1), "Staff Assistant", "at most"),
    ("Ada", "Not A Job", "Please select a job."),
])
def test_a_shift_rejects_a_bad_name_or_job(name, job, message):
    with pytest.raises(ValueError, match=message):
        new_shift(name, job)


def test_door_control_follows_job():
    captain = new_shift("Cap", "Captain")
    doctor = new_shift("Doc", "Doctor")
    assistant = new_shift("Sam", "Staff Assistant")

    assert [key for key in LOCKABLE_ROOM_KEYS if not can_control_door(captain, key)] == [DEPARTURES_KEY]
    assert [key for key in LOCKABLE_ROOM_KEYS if can_control_door(doctor, key)] == [MEDBAY_KEY]
    assert not any(can_control_door(assistant, key) for key in LOCKABLE_ROOM_KEYS)
    assert not can_control_door(captain, "no-such-door")


def test_game_ticks_renders_and_saves_as_json():
    game = SpaceStationGame(new_shift("Ada", "Staff Assistant"))
    game.player_data["game_clock"]["last_real_time"] -= 5
    game.tick()
    assert game.player_data["game_clock"]["elapsed_seconds"] >= 5
    view = game.view()
    assert view["title"] == "Your Quarters"
    assert view["redirect"] is None
    json.dumps(game.to_save_data())


def test_breathing_damage_adds_up_over_short_ticks():
    short = {}
    total = sum(damage_for_tick(short, "oxygen_damage_acc", 1, 1.0) for _ in range(120))
    once = damage_for_tick({}, "oxygen_damage_acc", 1, 120.0)
    assert once > 0
    assert abs(total - once) <= 1


def test_life_support_already_at_zero_is_not_announced_again():
    game = new_game("Engineering", "Engineer")
    set_system_level(game, "life_support", 0)
    game.player_data.pop("announcements")
    set_system_level(game, "life_support", 0)
    assert "announcements" not in game.player_data


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


def test_the_hop_approves_a_pending_request():
    game = new_game("Administration", "Head of Personnel")
    game.player_data["access_request"] = {"requested_job": "Doctor", "requester_name": "Ada"}
    approve(game, {}, {})
    assert game.player_data["job"] == "Doctor"
    assert "access_request" not in game.player_data


def test_alcohol_wears_off_over_time():
    player = new_shift("Ada", "Staff Assistant")
    player["alcohol_percent"] = 3 * ALCOHOL_DECAY_AMOUNT
    apply_alcohol_tick(player, 2 * ALCOHOL_DECAY_SECONDS + 1)
    assert player["alcohol_percent"] == ALCOHOL_DECAY_AMOUNT
    apply_alcohol_tick(player, ALCOHOL_DECAY_SECONDS)
    assert player["alcohol_percent"] == 0
    assert player["damage_timers"]["alcohol_decay_acc"] == 0


def test_notes_keep_only_the_newest():
    player = new_shift("Ada", "Staff Assistant")
    for n in range(MAX_NOTES + 5):
        add_note(player, f"note {n}")
    assert len(player["notes"]) == MAX_NOTES
    assert player["notes"][-1]["text"] == f"note {MAX_NOTES + 4}"


def test_the_botanist_is_only_asked_for_crops_botany_grows():
    game = SpaceStationGame(new_shift("Ada", "Botanist"))
    planters = game.player_data["botany"]["planters"]
    for planter, seed in zip(planters, BOTANY_SEED_IDS):
        planter.update(botany_items.planted_from_seed(get_item_definition(seed), 0))
    crops = {seed.removesuffix("_seeds") for seed in BOTANY_SEED_IDS}
    for _ in range(20):
        event = build_job_event(game)
        assert any(f" {crop} " in event["desc"] for crop in crops)

