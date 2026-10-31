from types import SimpleNamespace

import pytest

from helpers import new_game, reports
from space_online.game.helper_methods import npc_movement
from space_online.game.helper_methods.jail import is_jailed
from space_online.game.helper_methods.npc_movement import (
    ROOM_VISIT_TICKS,
    any_npc_for_job,
    call_npc,
    find_hall_passersby,
    location_for_post,
    on_duty_npc_for_job,
    reassign_npc_post,
    roll_departures,
    step_wanderers,
)
from space_online.game.maps.donut import (
    BAR_KEY,
    MEDBAY_KEY,
    SECURITY_KEY,
    SPECIAL_ROOM_HALLWAY,
    hallway_neighbors,
    location_from_key,
    location_from_tile,
)


def crew(game, job):
    return next(npc for npc in game.station_crew if npc["job"] == job)


def dice(monkeypatch, roll, pick=lambda options: options[0], randint=lambda low, high: high):
    """Fixes every random draw in npc_movement: random() returns roll, choice() and randint() the given picks."""
    monkeypatch.setattr(npc_movement, "random", SimpleNamespace(random=lambda: roll, choice=pick, randint=randint))


def only(game, *wanderers):
    """Keep the rest of the crew out of step_wanderers by marking them jailed."""
    for npc in game.station_crew:
        if npc not in wanderers:
            npc["in_jail"] = True
    return game


def test_finding_crew_by_job():
    game = new_game()
    doctor = crew(game, "Doctor")
    assert on_duty_npc_for_job(game.station_crew, "Doctor") is doctor
    doctor["on_duty"] = False
    assert on_duty_npc_for_job(game.station_crew, "Doctor") is None
    doctor.update(on_duty=True, in_jail=True)
    assert on_duty_npc_for_job(game.station_crew, "Doctor") is None
    assert any_npc_for_job(game.station_crew, "Doctor") is doctor
    assert any_npc_for_job(game.station_crew, "Wizard") is None


def test_staff_assistants_have_no_post():
    assert location_for_post("Staff Assistant") is None
    assert location_for_post("Doctor") == location_from_key(MEDBAY_KEY)


def test_crew_on_duty_sometimes_leave_their_post(monkeypatch):
    game = new_game()
    doctor, engineer, bartender = crew(game, "Doctor"), crew(game, "Engineer"), crew(game, "Bartender")
    engineer["in_jail"] = True
    bartender["on_duty"] = False
    bartender_at = dict(bartender["location"])
    assistant_at = dict(crew(game, "Staff Assistant")["location"])
    dice(monkeypatch, 0.0)
    roll_departures(game.station_crew)
    assert (doctor["on_duty"], doctor["location"], doctor["npc_goal"]) == (
        False, location_from_tile(SPECIAL_ROOM_HALLWAY[MEDBAY_KEY]), "return_to_post")
    assert engineer["on_duty"] and bartender["location"] == bartender_at
    assert crew(game, "Staff Assistant")["location"] == assistant_at


def test_crew_mostly_stay_at_their_post(monkeypatch):
    game = new_game()
    dice(monkeypatch, 0.99)
    roll_departures(game.station_crew)
    assert all(npc.get("on_duty", True) for npc in game.station_crew)


@pytest.mark.parametrize("roll, goal", [(0.1, "return_to_post"), (0.3, "visit_room"), (0.5, "wander")])
def test_crew_leaving_their_post_pick_a_goal(monkeypatch, roll, goal):
    game = new_game()
    doctor = crew(game, "Doctor")
    dice(monkeypatch, roll)
    npc_movement._send_npc_wandering(doctor)
    assert doctor["npc_goal"] == goal
    if goal == "visit_room":
        assert doctor["npc_goal_room_key"] not in (None, MEDBAY_KEY)


def test_calling_crew_back_to_their_post(monkeypatch):
    doctor = crew(new_game(), "Doctor")
    assert call_npc(doctor) == (True, f"{doctor['name']} is already at their post.")
    doctor.update(on_duty=False, location={"x": 2, "y": 5}, npc_goal="wander")
    dice(monkeypatch, 0.99)
    assert call_npc(doctor) == (False, f"{doctor['name']} doesn't answer. Maybe try calling again later.")
    dice(monkeypatch, 0.0)
    assert call_npc(doctor) == (True, f"{doctor['name']} answers the call and heads back to their post.")
    assert (doctor["on_duty"], doctor["location"], doctor["npc_goal"]) == (True, location_from_key(MEDBAY_KEY), None)


def test_a_new_job_moves_crew_to_its_post_or_sets_them_wandering(monkeypatch):
    game = new_game()
    assistant = crew(game, "Staff Assistant")
    assistant["job"] = "Doctor"
    reassign_npc_post(assistant, "Doctor")
    assert (assistant["on_duty"], assistant["location"]) == (True, location_from_key(MEDBAY_KEY))
    dice(monkeypatch, 0.99)
    assistant["job"] = "Staff Assistant"
    reassign_npc_post(assistant, "Staff Assistant")
    assert "on_duty" not in assistant
    assert assistant["npc_goal"] == "wander"


def test_wanderers_take_one_step_along_the_hallway(monkeypatch):
    game = new_game()
    assistant = crew(game, "Staff Assistant")
    only(game, assistant)
    assistant.update(location={"x": 0, "y": 1}, npc_goal="wander")
    dice(monkeypatch, 0.99)
    step_wanderers(game)
    assert (assistant["location"]["x"], assistant["location"]["y"]) in hallway_neighbors(0, 1).values()


def test_a_wanderer_off_the_hallway_is_put_back_on_it(monkeypatch):
    game = new_game()
    assistant = crew(game, "Staff Assistant")
    only(game, assistant)
    assistant.update(location={"x": 40, "y": 40}, npc_goal="wander")
    dice(monkeypatch, 0.99)
    step_wanderers(game)
    location = assistant["location"]
    assert hallway_neighbors(location["x"], location["y"])


def test_crew_visit_a_room_and_come_back_out(monkeypatch):
    game = new_game()
    doctor = crew(game, "Doctor")
    only(game, doctor)
    doctor.update(on_duty=False, location={"x": 0, "y": 2}, npc_goal="visit_room", npc_goal_room_key=BAR_KEY)
    dice(monkeypatch, 0.99)
    step_wanderers(game)
    assert (doctor["location"], doctor["room_visit_remaining"]) == (location_from_key(BAR_KEY), ROOM_VISIT_TICKS)
    for _ in range(ROOM_VISIT_TICKS):
        step_wanderers(game)
    assert doctor["location"] == {"x": 0, "y": 3}
    assert doctor["npc_goal"] == "return_to_post"


def test_a_staff_assistant_forgets_their_goal_after_a_visit(monkeypatch):
    game = new_game()
    assistant = crew(game, "Staff Assistant")
    only(game, assistant)
    assistant.update(location=location_from_key(BAR_KEY), npc_goal="visit_room", npc_goal_room_key=BAR_KEY,
                     room_visit_remaining=1)
    step_wanderers(game)
    assert (assistant["location"], assistant["npc_goal"]) == ({"x": 0, "y": 3}, None)


def test_crew_walk_the_shortest_way_back_to_their_post():
    game = new_game()
    guard = crew(game, "Security Guard")
    only(game, guard)
    guard.update(on_duty=False, location={"x": 5, "y": 3}, npc_goal="return_to_post")
    step_wanderers(game)
    assert guard["location"] == {"x": 5, "y": 4}
    step_wanderers(game)
    assert (guard["on_duty"], guard["location"]) == (True, location_from_key(SECURITY_KEY))


def test_crew_already_at_their_door_clock_straight_in():
    game = new_game()
    guard = crew(game, "Security Guard")
    only(game, guard)
    guard.update(on_duty=False, location={"x": 5, "y": 5}, npc_goal="return_to_post")
    step_wanderers(game)
    assert (guard["on_duty"], guard["location"]) == (True, location_from_key(SECURITY_KEY))


def test_crew_heading_somewhere_step_out_of_the_room_they_are_in_first():
    game = new_game()
    guard = crew(game, "Security Guard")
    only(game, guard)
    guard.update(on_duty=False, location=location_from_key(BAR_KEY), npc_goal="return_to_post")
    step_wanderers(game)
    assert guard["location"] == {"x": 0, "y": 4}


def test_crew_heading_somewhere_from_off_the_map_rejoin_the_hallway(monkeypatch):
    game = new_game()
    guard = crew(game, "Security Guard")
    only(game, guard)
    guard.update(on_duty=False, location={"x": 40, "y": 40}, npc_goal="return_to_post")
    dice(monkeypatch, 0.99, pick=lambda options: options[-1])
    step_wanderers(game)
    assert hallway_neighbors(guard["location"]["x"], guard["location"]["y"])


@pytest.mark.parametrize("room_key", [None, "9,9"])
def test_a_visit_without_a_room_to_go_to_turns_into_wandering(room_key):
    game = new_game()
    assistant = crew(game, "Staff Assistant")
    only(game, assistant)
    assistant.update(location={"x": 0, "y": 1}, npc_goal="visit_room", npc_goal_room_key=room_key)
    step_wanderers(game)
    assert assistant["npc_goal"] == "wander"


def test_a_guard_visiting_a_room_collects_fines_and_arrests_the_wanted(monkeypatch):
    game = new_game()
    guard = crew(game, "Security Guard")
    doctor = crew(game, "Doctor")
    engineer = crew(game, "Engineer")
    only(game, guard)
    guard.update(on_duty=False, location={"x": 0, "y": 2}, npc_goal="visit_room", npc_goal_room_key=BAR_KEY)
    for member in (doctor, engineer, game.player_data):
        member["location"] = location_from_key(BAR_KEY)
    doctor.update(in_jail=False, fine_amount=30)
    engineer.update(in_jail=False, warrant=True, warrant_reason="Sabotage")
    game.player_data.update(fine_amount=40)
    monkeypatch.setattr(npc_movement.random, "random", lambda: 0.99)
    step_wanderers(game)
    assert (doctor["fine_amount"], game.player_data["fine_amount"]) == (0, 0)
    assert is_jailed(engineer)
    assert reports(game) == ["Fine Paid", "Fine Paid", "Arrest"]


def test_a_guard_visiting_a_room_leaves_a_player_elsewhere_alone():
    game = new_game()
    guard = crew(game, "Security Guard")
    only(game, guard)
    guard.update(on_duty=False, location={"x": 0, "y": 2}, npc_goal="visit_room", npc_goal_room_key=BAR_KEY)
    game.player_data.update(fine_amount=40, warrant=True)
    step_wanderers(game)
    assert (game.player_data["fine_amount"], is_jailed(game.player_data)) == (40, False)


def test_wandering_crew_sometimes_get_hurt_or_heal(monkeypatch):
    member = new_game().station_crew[0]
    events = iter(["minor_injury", "head", "minor_heal", "head", "nothing"])
    dice(monkeypatch, 0.0, pick=lambda options: next(events), randint=lambda low, high: 5)
    for _ in range(3):
        npc_movement._maybe_trigger_silent_event(member)
    assert member["limbs"]["head"] == 100
    npc_movement._apply_silent_npc_event({"name": "No body"})


def test_healing_skips_crew_who_are_not_hurt(monkeypatch):
    member = new_game().station_crew[0]
    dice(monkeypatch, 0.0, pick=lambda options: "minor_heal")
    npc_movement._apply_silent_npc_event(member)
    assert set(member["limbs"].values()) == {100}


def test_only_wanderers_on_the_players_tile_pass_by():
    game = new_game()
    game.player_data["location"] = {"x": 0, "y": 1}
    doctor, engineer, bartender = crew(game, "Doctor"), crew(game, "Engineer"), crew(game, "Bartender")
    assistants = [npc for npc in game.station_crew if npc["job"] == "Staff Assistant"]
    for npc in (doctor, engineer, bartender, *assistants):
        npc["location"] = {"x": 0, "y": 1}
    engineer["on_duty"] = False
    bartender.update(on_duty=False, in_jail=True)
    assistants[0]["room_visit_remaining"] = 1
    assistants[1]["location"] = {"x": 0, "y": 2}
    assert find_hall_passersby(game.player_data, game.station_crew) == [engineer]
