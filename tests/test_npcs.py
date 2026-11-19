import pytest

from helpers import crew, fix_random, hurt_badly, new_game, reports
from space_online.game.character_methods import character_creation
from space_online.game.character_methods.character_creation import EXTRA_CREW_RANGE, UNIQUE_JOBS
from space_online.game.helper_methods import jail, npc_movement
from space_online.game.helper_methods.jail import PETTY_CRIMES, is_jailed
from space_online.game.helper_methods.npc_movement import (
    JOB_POSTS,
    POSTS,
    ROOM_VISIT_TICKS,
    STAY_BEHIND_CHANCE,
    STROLL_STEPS,
    call_npc,
    can_work,
    crew_aboard,
    find_hall_passersby,
    is_posted,
    on_duty_npc_for_job,
    open_post,
    player_holds_post,
    post_holder,
    reassign_npc_post,
    recall_from_shuttle,
    send_to_shuttle,
    step_crew,
)
from space_online.game.maps.donut import (
    ATMOSPHERICS_KEY,
    BAR_KEY,
    BRIDGE_KEY,
    CHEMISTRY_KEY,
    DEPARTURES_KEY,
    KITCHEN_KEY,
    MEDBAY_KEY,
    RESEARCH_KEY,
    ROOMS,
    SECURITY_KEY,
    SHIP_MAP,
    hallway_neighbors,
    location_from_key,
)


def test_the_science_hall_is_one_tile_with_a_lab_door_on_three_sides():
    assert hallway_neighbors(3, 6) == {"west": (3, 5)}
    doors = {room.name: room.button for room in ROOMS.values() if room.hallway == (3, 6)}
    assert doors == {"Atmospherics": (0, 1), "Chemistry Lab": (1, 2), "Research Lab": (2, 1)}
    assert "3,8" not in SHIP_MAP and (CHEMISTRY_KEY, RESEARCH_KEY) == ("3,7", "2,6")


def dice(monkeypatch, roll, **fixed):
    fix_random(monkeypatch, npc_movement, jail, roll=roll, **fixed)


def only(game, *movers):
    """Keep the rest of the crew out of step_crew by marking them jailed."""
    for npc in game.station_crew:
        if npc not in movers:
            npc["in_jail"] = True
    return game


def alone(job):
    """A new game where the crew member with job is the only one step_crew moves. Returns the game and them."""
    game = new_game()
    member = crew(game, job)
    return only(game, member), member


def test_idle_crew_make_for_the_shuttle_at_the_call_and_working_crew_once_it_docks(monkeypatch):
    game = new_game()
    dice(monkeypatch, roll=STAY_BEHIND_CHANCE)
    chef, assistant = crew(game, "Chef"), crew(game, "Staff Assistant")
    send_to_shuttle(game.station_crew, idle_only=True)
    assert (chef["npc_goal"], chef["on_duty"], assistant["npc_goal"]) == (None, True, "board")
    send_to_shuttle(game.station_crew, idle_only=False)
    assert (chef["npc_goal"], chef["on_duty"], chef["location"]) == ("board", False, {"x": 0, "y": 2})

    for _ in range(20):
        step_crew(game)
    assert crew_aboard(game.station_crew) == game.station_crew
    step_crew(game)
    assert chef["location"] == location_from_key(DEPARTURES_KEY)


def test_now_and_then_someone_misses_the_shuttle_call_and_is_not_asked_again(monkeypatch):
    game = new_game()
    dice(monkeypatch, roll=0.0)
    send_to_shuttle(game.station_crew, idle_only=False)
    dice(monkeypatch, roll=0.99)
    send_to_shuttle(game.station_crew, idle_only=False)
    assert all(npc["stays_behind"] and npc["npc_goal"] != "board" for npc in game.station_crew)
    assert crew(game, "Chef")["on_duty"]


def test_crew_who_are_jailed_or_badly_hurt_do_not_walk_to_the_shuttle(monkeypatch):
    game = new_game()
    dice(monkeypatch, roll=0.99)
    chef, doctor = crew(game, "Chef"), hurt_badly(crew(game, "Doctor"))
    chef["in_jail"] = True
    send_to_shuttle(game.station_crew, idle_only=False)
    assert (chef["npc_goal"], doctor["npc_goal"], crew(game, "Miner")["npc_goal"]) == (None, None, "board")


def test_a_recall_sends_the_crew_back_to_what_they_were_doing(monkeypatch):
    game = new_game()
    dice(monkeypatch, roll=0.99)
    chef, assistant, miner = crew(game, "Chef"), crew(game, "Staff Assistant"), crew(game, "Miner")
    miner["stays_behind"] = True
    send_to_shuttle(game.station_crew, idle_only=False)
    for _ in range(20):
        step_crew(game)
    recall_from_shuttle(game.station_crew)
    assert (assistant["npc_goal"], assistant["location"]) == (None, {"x": 1, "y": 0})
    assert (chef["npc_goal"], chef["location"], "stays_behind" in miner) == ("return_to_post", {"x": 1, "y": 0}, False)
    for _ in range(3):
        step_crew(game)
    assert (chef["on_duty"], chef["location"]) == (True, location_from_key(KITCHEN_KEY))


def test_a_shift_has_a_holder_for_every_post_two_assistants_and_a_few_extras_who_roam():
    for _ in range(20):
        station_crew = new_game("Medical", "Doctor", extras=True).station_crew
        extras = [npc for npc in station_crew if npc.get("roams")]
        assert EXTRA_CREW_RANGE[0] <= len(extras) <= EXTRA_CREW_RANGE[1]
        assert not {npc["job"] for npc in extras} & {"Doctor", *UNIQUE_JOBS}
        assert all("on_duty" not in npc and not is_posted(npc) for npc in extras)
        holders = [npc for npc in station_crew if is_posted(npc)]
        assert sorted((npc["job"], npc["post_key"]) for npc in holders) == sorted(
            post for post in POSTS if post[0] != "Doctor")
        assert all(npc["on_duty"] and npc["location"] == location_from_key(npc["post_key"]) for npc in holders)
        assert len(station_crew) == len(holders) + 2 + len(extras)
        assert len({npc["name"] for npc in station_crew} | {"Ada"}) == len(station_crew) + 1


def test_a_head_of_personnel_gets_a_captain_and_assistants_to_hand_the_jobs_to(monkeypatch):
    monkeypatch.setattr(character_creation.random, "randint", lambda low, high: high)
    captain, *crew_list = new_game("Administration", "Head of Personnel", extras=True).station_crew
    assert [npc["job"] for npc in crew_list] == ["Staff Assistant"] * (len(POSTS) - 2 + 2 + EXTRA_CREW_RANGE[1])
    assert (captain["job"], captain["post_key"], captain["on_duty"], captain["location"]) == (
        "Captain", BRIDGE_KEY, True, location_from_key(BRIDGE_KEY))


def test_finding_crew_by_job():
    game = new_game(extras=True)
    doctor = crew(game, "Doctor")
    game.station_crew.insert(0, {**doctor, "name": "Extra", "roams": True})
    assert post_holder(game.station_crew, "Doctor") is doctor
    assert on_duty_npc_for_job(game.station_crew, "Doctor") is doctor
    doctor["on_duty"] = False
    assert on_duty_npc_for_job(game.station_crew, "Doctor") is None
    doctor.update(on_duty=True, in_jail=True)
    assert on_duty_npc_for_job(game.station_crew, "Doctor") is None
    hurt_badly(doctor)["in_jail"] = False
    assert (can_work(doctor), on_duty_npc_for_job(game.station_crew, "Doctor")) == (False, None)
    assert post_holder(game.station_crew, "Wizard") is None


def test_a_scientist_is_posted_to_one_lab_and_npc_scientists_hold_the_others():
    for post in JOB_POSTS["Scientist"]:
        game = new_game("Science", "Scientist", post=post)
        assert game.player_data["post_key"] == post
        assert [(line["title"], line["text"]) for line in game.player_data["log"]] == [
            ("Your Post", f"You are posted to the {ROOMS[post].name} this shift.")]
        held = [npc["post_key"] for npc in game.station_crew if npc["job"] == "Scientist" and is_posted(npc)]
        assert held == [key for key in JOB_POSTS["Scientist"] if key != post]


def test_a_scientists_lab_is_picked_at_random(monkeypatch):
    fix_random(monkeypatch, character_creation, pick=lambda options: options[-1], randint=lambda low, high: low)
    assert character_creation.new_shift("Ada", "Scientist")["post_key"] == JOB_POSTS["Scientist"][-1]


def test_any_other_job_has_no_lab_of_its_own_and_a_scientist_in_every_lab():
    game = new_game("Medical", "Doctor")
    assert (game.player_data["post_key"], game.player_data["log"]) == (None, [])
    assert all(post_holder(game.station_crew, "Scientist", key) for key in JOB_POSTS["Scientist"])


def test_staff_assistants_have_no_post():
    game = new_game()
    assert (crew(game, "Staff Assistant")["post_key"], crew(game, "Doctor")["post_key"]) == (None, MEDBAY_KEY)


def test_the_scientist_has_a_post_in_each_science_lab():
    assert JOB_POSTS["Scientist"] == (CHEMISTRY_KEY, RESEARCH_KEY, ATMOSPHERICS_KEY)
    assert JOB_POSTS["Doctor"] == (MEDBAY_KEY,)


def test_a_job_with_two_rooms_gets_a_holder_in_each():
    game = new_game()
    chemistry = post_holder(game.station_crew, "Scientist", CHEMISTRY_KEY)
    research = post_holder(game.station_crew, "Scientist", RESEARCH_KEY)
    assert chemistry is not research
    assert (chemistry["location"], research["location"]) == (location_from_key(CHEMISTRY_KEY),
                                                              location_from_key(RESEARCH_KEY))
    assert post_holder(game.station_crew, "Scientist") is chemistry
    assert post_holder(game.station_crew, "Doctor", RESEARCH_KEY) is None
    research["on_duty"] = False
    assert on_duty_npc_for_job(game.station_crew, "Scientist", RESEARCH_KEY) is None
    assert on_duty_npc_for_job(game.station_crew, "Scientist", CHEMISTRY_KEY) is chemistry


def test_each_holder_of_a_job_with_two_rooms_returns_to_their_own(monkeypatch):
    game = new_game()
    scientists = [post_holder(game.station_crew, "Scientist", key) for key in (CHEMISTRY_KEY, RESEARCH_KEY)]
    for scientist in scientists:
        scientist.update(on_duty=False, location={"x": 0, "y": 1}, npc_goal="return_to_post")
    only(game, *scientists)
    dice(monkeypatch, 0.99)
    for _ in range(40):
        step_crew(game)
    assert [(npc["on_duty"], npc["location"]) for npc in scientists] == [
        (True, location_from_key(CHEMISTRY_KEY)), (True, location_from_key(RESEARCH_KEY))]


def test_the_player_holds_their_own_post_and_every_post_of_a_job_with_one():
    scientist = new_game("Science", "Scientist", post=RESEARCH_KEY).player_data
    assert (player_holds_post(scientist, "Scientist", RESEARCH_KEY), player_holds_post(scientist, "Scientist"),
            player_holds_post(scientist, "Scientist", CHEMISTRY_KEY), player_holds_post(scientist, "Doctor")) == (
        True, True, False, False)
    doctor = new_game("Medical", "Doctor").player_data
    assert (doctor["post_key"], player_holds_post(doctor, "Doctor", MEDBAY_KEY)) == (None, True)
    doctor["job"] = "Scientist"
    assert player_holds_post(doctor, "Scientist", CHEMISTRY_KEY) and player_holds_post(doctor, "Scientist",
                                                                                         RESEARCH_KEY)


def test_a_new_post_is_the_first_one_nobody_holds():
    game = new_game("Science", "Scientist", post=CHEMISTRY_KEY)
    assert open_post(game.player_data, game.station_crew, "Scientist") == CHEMISTRY_KEY
    game.station_crew.remove(post_holder(game.station_crew, "Scientist", RESEARCH_KEY))
    assert open_post(game.player_data, game.station_crew, "Scientist") == RESEARCH_KEY
    assert open_post(game.player_data, game.station_crew, "Doctor") == MEDBAY_KEY


def test_crew_stay_at_their_post_most_of_the_time(monkeypatch):
    game = new_game()
    dice(monkeypatch, npc_movement.ERRAND_CHANCE + npc_movement.PATROL_STROLL_CHANCE)
    step_crew(game)
    assert all(npc["on_duty"] for npc in game.station_crew if is_posted(npc))


def test_a_posted_crew_member_sometimes_runs_an_errand_to_another_room_and_comes_straight_back(monkeypatch):
    game, doctor = alone("Doctor")
    dice(monkeypatch, 0.0, pick=lambda rooms: BAR_KEY)
    step_crew(game)
    assert (doctor["on_duty"], doctor["location"], doctor["npc_goal"], doctor["npc_goal_room_key"]) == (
        False, {"x": 0, "y": 5}, "visit_room", BAR_KEY)
    step_crew(game)
    step_crew(game)
    assert (doctor["location"], doctor["room_visit_remaining"]) == (location_from_key(BAR_KEY), ROOM_VISIT_TICKS)
    for _ in range(ROOM_VISIT_TICKS):
        step_crew(game)
    assert (doctor["location"], doctor["npc_goal"]) == ({"x": 0, "y": 3}, "return_to_post")
    for _ in range(2):
        step_crew(game)
    assert (doctor["on_duty"], doctor["location"], doctor["npc_goal"]) == (True, location_from_key(MEDBAY_KEY), None)


@pytest.mark.parametrize("job, roll, leaves", [
    ("Doctor", npc_movement.ERRAND_CHANCE, True),
    ("Doctor", npc_movement.ERRAND_CHANCE + npc_movement.STROLL_CHANCE, False),
    ("Security Guard", npc_movement.ERRAND_CHANCE + npc_movement.STROLL_CHANCE, True),
])
def test_now_and_then_crew_just_leave_for_a_walk_and_patrols_do_it_more(monkeypatch, job, roll, leaves):
    game, member = alone(job)
    dice(monkeypatch, roll)
    step_crew(game)
    assert (member["on_duty"], member["npc_goal"]) == ((False, "wander") if leaves else (True, None))


def test_a_walk_lasts_a_while_and_then_ends_back_at_the_post(monkeypatch):
    game, doctor = alone("Doctor")
    dice(monkeypatch, npc_movement.ERRAND_CHANCE)
    step_crew(game)
    assert doctor["stroll_remaining"] == STROLL_STEPS
    dice(monkeypatch, 0.99, pick=lambda options: sorted(options)[0])
    for _ in range(STROLL_STEPS):
        step_crew(game)
        assert not doctor["on_duty"] and hallway_neighbors(doctor["location"]["x"], doctor["location"]["y"])
    for _ in range(12):
        step_crew(game)
    assert (doctor["on_duty"], doctor["location"]) == (True, location_from_key(MEDBAY_KEY))


def test_calling_crew_back_to_their_post(monkeypatch):
    doctor = crew(new_game(), "Doctor")
    assert call_npc(doctor) == (True, f"{doctor['name']} is already at their post.")
    doctor.update(on_duty=False, location={"x": 2, "y": 5}, npc_goal="wander", stroll_remaining=9)
    dice(monkeypatch, 0.99)
    assert call_npc(doctor) == (False, f"{doctor['name']} doesn't answer. Maybe try calling again later.")
    dice(monkeypatch, 0.0)
    assert call_npc(doctor) == (True, f"{doctor['name']} answers the call and heads back to their post.")
    assert (doctor["on_duty"], doctor["location"], doctor["npc_goal"], doctor["stroll_remaining"]) == (
        True, location_from_key(MEDBAY_KEY), None, 0)


def test_a_new_job_moves_crew_to_its_post_or_sets_them_wandering(monkeypatch):
    game = new_game()
    assistant = crew(game, "Staff Assistant")
    assistant.update(job="Doctor", roams=True)
    reassign_npc_post(game, assistant, "Doctor")
    assert (assistant["on_duty"], assistant["location"], is_posted(assistant), assistant["post_key"]) == (
        True, location_from_key(MEDBAY_KEY), True, MEDBAY_KEY)
    dice(monkeypatch, 0.99)
    assistant["job"] = "Staff Assistant"
    reassign_npc_post(game, assistant, "Staff Assistant")
    assert ("on_duty" in assistant, assistant["post_key"]) == (False, None)
    assert assistant["npc_goal"] == "wander"


def test_a_new_scientist_goes_to_the_lab_nobody_holds():
    game = new_game("Science", "Scientist", post=CHEMISTRY_KEY)
    researcher = post_holder(game.station_crew, "Scientist", RESEARCH_KEY)
    researcher["job"] = "Staff Assistant"
    reassign_npc_post(game, researcher, "Staff Assistant")
    assistant = crew(game, "Staff Assistant")
    assistant["job"] = "Scientist"
    reassign_npc_post(game, assistant, "Scientist")
    assert (assistant["post_key"], assistant["location"]) == (RESEARCH_KEY, location_from_key(RESEARCH_KEY))


def test_roamers_take_one_step_along_the_hallway(monkeypatch):
    game, assistant = alone("Staff Assistant")
    assistant.update(location={"x": 0, "y": 1}, npc_goal="wander")
    dice(monkeypatch, 0.99)
    step_crew(game)
    assert (assistant["location"]["x"], assistant["location"]["y"]) in hallway_neighbors(0, 1).values()


def test_an_extra_in_a_posted_job_roams_like_a_staff_assistant(monkeypatch):
    game = new_game()
    extra = crew(game, "Staff Assistant")
    extra.update(job="Engineer", roams=True, location={"x": 0, "y": 1})
    only(game, extra)
    dice(monkeypatch, 0.99)
    step_crew(game)
    assert (extra["location"]["x"], extra["location"]["y"]) in hallway_neighbors(0, 1).values()
    assert "on_duty" not in extra


def test_a_roamer_off_the_hallway_is_put_back_on_it(monkeypatch):
    game, assistant = alone("Staff Assistant")
    assistant.update(location={"x": 40, "y": 40}, npc_goal="wander")
    dice(monkeypatch, 0.99)
    step_crew(game)
    location = assistant["location"]
    assert hallway_neighbors(location["x"], location["y"])


def test_a_roamer_drops_into_a_room_and_forgets_the_goal_after_the_visit(monkeypatch):
    game, assistant = alone("Staff Assistant")
    assistant.update(location={"x": 0, "y": 3}, npc_goal=None)
    dice(monkeypatch, 0.0, pick=lambda rooms: BAR_KEY)
    step_crew(game)
    assert (assistant["location"], assistant["room_visit_remaining"]) == (location_from_key(BAR_KEY), ROOM_VISIT_TICKS)
    for _ in range(ROOM_VISIT_TICKS):
        step_crew(game)
    assert (assistant["location"], assistant["npc_goal"]) == ({"x": 0, "y": 3}, None)


def test_crew_walk_the_shortest_way_back_to_their_post():
    game, guard = alone("Security Guard")
    guard.update(on_duty=False, location={"x": 5, "y": 3}, npc_goal="return_to_post")
    step_crew(game)
    assert guard["location"] == {"x": 5, "y": 4}
    step_crew(game)
    assert (guard["on_duty"], guard["location"]) == (True, location_from_key(SECURITY_KEY))


def test_crew_already_at_their_door_clock_straight_in():
    game, guard = alone("Security Guard")
    guard.update(on_duty=False, location={"x": 5, "y": 5}, npc_goal="return_to_post")
    step_crew(game)
    assert (guard["on_duty"], guard["location"]) == (True, location_from_key(SECURITY_KEY))


def test_crew_heading_somewhere_step_out_of_the_room_they_are_in_first():
    game, guard = alone("Security Guard")
    guard.update(on_duty=False, location=location_from_key(BAR_KEY), npc_goal="return_to_post")
    step_crew(game)
    assert guard["location"] == {"x": 0, "y": 4}


def test_crew_heading_somewhere_from_off_the_map_rejoin_the_hallway(monkeypatch):
    game, guard = alone("Security Guard")
    guard.update(on_duty=False, location={"x": 40, "y": 40}, npc_goal="return_to_post")
    dice(monkeypatch, 0.99, pick=lambda options: options[-1])
    step_crew(game)
    assert hallway_neighbors(guard["location"]["x"], guard["location"]["y"])


@pytest.mark.parametrize("room_key", [None, "9,9"])
def test_a_visit_without_a_room_to_go_to_turns_into_wandering(room_key):
    game, assistant = alone("Staff Assistant")
    assistant.update(location={"x": 0, "y": 1}, npc_goal="visit_room", npc_goal_room_key=room_key)
    step_crew(game)
    assert assistant["npc_goal"] == "wander"


def test_the_jailed_and_the_badly_hurt_do_not_move():
    game = new_game()
    assistant, doctor = crew(game, "Staff Assistant"), crew(game, "Doctor")
    assistant.update(location={"x": 0, "y": 1}, npc_goal="wander")
    hurt_badly(assistant)
    only(game, assistant)
    step_crew(game)
    assert assistant["location"] == {"x": 0, "y": 1}
    assert doctor["on_duty"]


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
    dice(monkeypatch, 0.99)
    step_crew(game)
    assert (doctor["fine_amount"], game.player_data["fine_amount"]) == (0, 0)
    assert is_jailed(engineer)
    assert reports(game) == ["Fine Paid", "Fine Paid", "Arrest"]


def test_other_crew_walking_into_a_room_arrest_nobody():
    game = new_game()
    doctor, engineer = crew(game, "Doctor"), crew(game, "Engineer")
    only(game, doctor)
    doctor.update(on_duty=False, location={"x": 0, "y": 2}, npc_goal="visit_room", npc_goal_room_key=BAR_KEY)
    engineer.update(in_jail=False, warrant=True, location=location_from_key(BAR_KEY))
    step_crew(game)
    assert not is_jailed(engineer)


def test_a_guard_visiting_a_room_leaves_a_player_elsewhere_alone():
    game, guard = alone("Security Guard")
    guard.update(on_duty=False, location={"x": 0, "y": 2}, npc_goal="visit_room", npc_goal_room_key=BAR_KEY)
    game.player_data.update(fine_amount=40, warrant=True)
    step_crew(game)
    assert (game.player_data["fine_amount"], is_jailed(game.player_data)) == (40, False)


def test_wandering_crew_sometimes_get_hurt_or_heal(monkeypatch):
    member = new_game().station_crew[0]
    events = iter(["minor_injury", "head", "minor_heal", "head", "nothing"])
    dice(monkeypatch, 0.0, pick=lambda options: next(events), randint=lambda low, high: 5)
    npc_movement._apply_silent_npc_event(member)
    assert member["limbs"]["head"] == 95
    npc_movement._apply_silent_npc_event(member)
    npc_movement._apply_silent_npc_event(member)
    assert member["limbs"]["head"] == 100


def test_healing_skips_crew_who_are_not_hurt(monkeypatch):
    member = new_game().station_crew[0]
    dice(monkeypatch, 0.0, pick=lambda options: "minor_heal")
    npc_movement._apply_silent_npc_event(member)
    assert set(member["limbs"].values()) == {100}


def test_wandering_crew_sometimes_commit_petty_crimes(monkeypatch):
    game = new_game()
    by_job = {npc["job"]: npc for npc in game.station_crew}
    dice(monkeypatch, 0.0, pick=lambda options: options[-1])
    for job in ("Doctor", "Captain", "Security Guard"):
        jail._maybe_commit_petty_crime(by_job[job])
    assert (by_job["Doctor"]["warrant"], by_job["Doctor"]["warrant_reason"]) == (True, PETTY_CRIMES[-1])
    assert not by_job["Captain"]["warrant"] and not by_job["Security Guard"]["warrant"]
    by_job["Doctor"]["warrant_reason"] = "Brawling"
    jail._maybe_commit_petty_crime(by_job["Doctor"])
    assert by_job["Doctor"]["warrant_reason"] == "Brawling"


def test_crimes_are_rare_and_happen_on_a_wandering_step(monkeypatch):
    game, assistant = alone("Staff Assistant")
    assistant.update(location={"x": 0, "y": 1}, npc_goal="wander")
    dice(monkeypatch, jail.NPC_CRIME_CHANCE)
    step_crew(game)
    assert assistant["warrant"] is False
    dice(monkeypatch, 0.0, pick=lambda options: "nothing" if "nothing" in options else options[0])
    assistant["npc_goal"] = "wander"
    monkeypatch.setattr(npc_movement, "ROAMER_ROOM_VISIT_CHANCE", -1)
    step_crew(game)
    assert assistant["warrant"] is True


def test_only_crew_out_in_the_hallway_on_the_players_tile_pass_by():
    game = new_game()
    game.player_data["location"] = {"x": 0, "y": 1}
    doctor, engineer, bartender, chef = (crew(game, job) for job in ("Doctor", "Engineer", "Bartender", "Chef"))
    assistants = [npc for npc in game.station_crew if npc["job"] == "Staff Assistant"]
    for npc in (doctor, engineer, bartender, chef, *assistants):
        npc["location"] = {"x": 0, "y": 1}
    engineer["on_duty"] = False
    bartender.update(on_duty=False, in_jail=True)
    hurt_badly(chef)["on_duty"] = False
    assistants[0]["room_visit_remaining"] = 1
    assistants[1]["location"] = {"x": 0, "y": 2}
    assert find_hall_passersby(game.player_data, game.station_crew) == [engineer]
