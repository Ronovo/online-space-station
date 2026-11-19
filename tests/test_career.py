import pytest

from helpers import act, at, ctx, in_room, last_message, new_game, notes, open_station, post, register, start_round
from space_online.game.character_methods.character_creation import (
    JOBS,
    MAX_NAME_LENGTH,
    REQUESTABLE_JOBS,
    STARTING_FILES,
)
from space_online.game.helper_methods.career import (
    HEAD_JOB,
    PAY_INTERVAL_SECONDS,
    REGULAR_JOBS,
    REVIVE_BASE_COST,
    REVIVE_COST_STEP,
    START_JOB,
    TOP_JOB,
    empty_save,
    finish_round,
    job_salary,
    locked_regular_jobs,
    new_career,
    pay_salary,
    revive_cost,
    start_career_shift,
    unlock_job,
    unlocked_jobs,
)
from space_online.game.helper_methods.rounds import ANTAGONIST, CAREER, PEACEFUL
from space_online.game.main import SpaceStationGame
from space_online.game.maps.donut import BRIDGE_KEY, ENGINEERING_KEY, SECURITY_KEY, location_from_key
from space_online.game.objects.weapons import ARMORY_ITEM_IDS
from space_online.webapp import db


def career(**changes):
    return {**new_career("Ada"), **changes}


def save_with_round(a_career, job=START_JOB, survived=True, cause="reached Central Command", seconds=1500,
                    ends_as=None):
    """A save whose career shift, started in job, is over. ends_as is the job the player changed to on the way."""
    shift = start_career_shift(a_career, job)
    shift["round"]["outcome"] = {"survived": survived, "cause": cause, "seconds": seconds}
    shift["job"] = ends_as or job
    return {"career": a_career, "shift": shift, "summary": None}


def test_a_career_starts_at_the_bottom():
    assert new_career("  Ada ") == {"name": "Ada", "credits": JOBS[START_JOB]["credits"], "rounds": 0, "revives": 0,
                                    "unlocked": [], "captain": False, "pick_owed": False, "files": STARTING_FILES}
    assert empty_save() == {"career": None, "shift": None, "summary": None}
    for name, message in (("", "Please enter a character name."), ("x" * (MAX_NAME_LENGTH + 1), "at most")):
        with pytest.raises(ValueError, match=message):
            new_career(name)


def test_every_job_pays_a_tenth_of_its_starting_credits_and_the_ladder_runs_in_pay_order():
    assert (job_salary(START_JOB), job_salary("Bartender"), job_salary("Chef"), job_salary("Botanist"),
            job_salary(TOP_JOB)) == (100, 150, 200, 250, 1000)
    pay = [job_salary(job) for job in (START_JOB, *REGULAR_JOBS, HEAD_JOB, TOP_JOB)]
    assert pay == sorted(pay)
    assert set((START_JOB, *REGULAR_JOBS, HEAD_JOB, TOP_JOB)) == set(JOBS)


def test_a_career_starts_shifts_in_the_jobs_it_has_unlocked():
    assert unlocked_jobs(career()) == [START_JOB]
    assert unlocked_jobs(career(unlocked=["Doctor", "Bartender"])) == [START_JOB, "Bartender", "Doctor"]
    assert locked_regular_jobs(career(unlocked=list(REGULAR_JOBS[1:]))) == [REGULAR_JOBS[0]]
    assert unlocked_jobs(career(unlocked=list(REGULAR_JOBS[1:]))) == [START_JOB, *REGULAR_JOBS[1:]]
    assert unlocked_jobs(career(unlocked=list(REGULAR_JOBS))) == [START_JOB, *REGULAR_JOBS, HEAD_JOB]
    assert unlocked_jobs(career(unlocked=list(REGULAR_JOBS), captain=True)) == [
        START_JOB, *REGULAR_JOBS, HEAD_JOB, TOP_JOB]


def test_a_career_shift_brings_the_careers_credits_and_starts_only_in_an_unlocked_job():
    shift = start_career_shift(career(credits=4321, unlocked=["Chef"]), "Chef")
    assert (shift["name"], shift["job"], shift["credits"], shift["round"]["mode"]) == ("Ada", "Chef", 4321, CAREER)
    assert 1 <= len(shift["threats"]) <= 3
    with pytest.raises(ValueError, match="hasn't unlocked that job"):
        start_career_shift(career(unlocked=["Chef"]), "Doctor")


def test_a_career_is_paid_its_jobs_salary_every_ten_minutes():
    game = SpaceStationGame(start_career_shift(career(unlocked=["Chef"]), "Chef"))
    pay_salary(at(game, PAY_INTERVAL_SECONDS - 1))
    assert (game.player_data["credits"], game._messages) == (1000, [])
    pay_salary(at(game, PAY_INTERVAL_SECONDS))
    assert game.player_data["credits"] == 1200
    assert last_message(game) == ("Payday", "Your Chef salary has been paid: 200 credits.")
    game.player_data["job"] = "Bartender"
    pay_salary(at(game, 3 * PAY_INTERVAL_SECONDS + 5))
    assert (game.player_data["credits"], game.player_data["round"]["salary_paid"]) == (1500, 500)
    assert game.player_data["round"]["paid_through"] == 3 * PAY_INTERVAL_SECONDS
    assert notes(game)[-1] == "Paid 300 credits in salary."


def test_single_rounds_pay_no_salary():
    game = at(new_game(mode=PEACEFUL), 5 * PAY_INTERVAL_SECONDS)
    pay_salary(game)
    assert game.player_data["credits"] == 1000


def test_no_salary_is_paid_once_the_round_is_over():
    game = SpaceStationGame(save_with_round(career())["shift"])
    pay_salary(at(game, PAY_INTERVAL_SECONDS))
    assert game.player_data["credits"] == 1000


def test_no_salary_is_paid_once_the_shuttle_has_left_the_station():
    game = SpaceStationGame(start_career_shift(career(), START_JOB))
    game.player_data["round"]["shuttle"]["state"] = "transit"
    pay_salary(at(game, 5 * PAY_INTERVAL_SECONDS))
    assert (game.player_data["credits"], game.player_data["round"]["salary_paid"], game._messages) == (1000, 0, [])
    game.player_data["round"]["shuttle"]["state"] = "docked"
    pay_salary(game)
    assert game.player_data["round"]["salary_paid"] == 5 * job_salary(START_JOB)


def test_ending_a_round_in_a_new_job_carries_the_credits_over_and_unlocks_that_job():
    save = save_with_round(career(), ends_as="Chef")
    shift = save["shift"]
    shift["credits"] = 1234.5
    shift["round"].update(salary_paid=200, duties_done=3, duties_missed=1)
    shift["stock_holdings"] = {shift["stock_market"]["companies"][0]["name"]: 2, "Gone Bust": 5}
    price = shift["stock_market"]["companies"][0]["current_value"]
    job_threats = [name for name, *_ in finish_round(save)["threats"]]

    summary = save["summary"]
    assert (save["shift"], len(job_threats) >= 1) == (None, True)
    assert summary["shares"] == round(2 * price, 2)
    assert summary == {
        "mode": CAREER, "name": "Ada", "job": START_JOB, "ended_as": "Chef", "survived": True,
        "cause": "reached Central Command",
        "minutes": 25, "threats": summary["threats"], "salary": 200, "duties_done": 3, "duties_missed": 1,
        "shares": summary["shares"], "credits": round(1234.5 + summary["shares"], 2), "revive_cost": None,
        "career_over": False, "unlocked": ["Chef"], "pick_owed": False,
    }
    assert save["career"] == {"name": "Ada", "credits": summary["credits"], "rounds": 1, "revives": 0,
                              "unlocked": ["Chef"], "captain": False, "pick_owed": False,
                              "files": STARTING_FILES}


def test_a_round_that_ends_without_a_new_job_leaves_a_pick_of_one():
    save = save_with_round(career(unlocked=["Chef"]), job="Chef")
    summary = finish_round(save)
    mine = save["career"]
    assert (summary["job"], summary["ended_as"]) == ("Chef", None)
    assert (summary["unlocked"], summary["pick_owed"], mine["pick_owed"], mine["unlocked"]) == ([], True, True, ["Chef"])
    for job, message in (("Chef", "haven't unlocked yet"), (HEAD_JOB, "haven't unlocked yet"), ("", "haven't")):
        with pytest.raises(ValueError, match=message):
            unlock_job(mine, job)
    unlock_job(mine, "Doctor")
    assert (mine["unlocked"], mine["pick_owed"]) == (["Chef", "Doctor"], False)
    with pytest.raises(ValueError, match="no job to pick"):
        unlock_job(mine, "Miner")


def test_the_last_regular_job_unlocks_head_of_personnel_with_it():
    save = save_with_round(career(unlocked=list(REGULAR_JOBS[:-1])), ends_as=REGULAR_JOBS[-1])
    assert finish_round(save)["unlocked"] == [REGULAR_JOBS[-1], HEAD_JOB]


def test_a_round_started_as_head_of_personnel_unlocks_captain_and_then_there_is_nothing_left():
    save = save_with_round(career(unlocked=list(REGULAR_JOBS)), job=HEAD_JOB)
    summary = finish_round(save)
    assert (summary["unlocked"], summary["pick_owed"], save["career"]["captain"]) == ([TOP_JOB], False, True)
    save = save_with_round(save["career"], job=TOP_JOB)
    summary = finish_round(save)
    assert (summary["unlocked"], summary["pick_owed"]) == ([], False)


def test_dying_costs_more_each_time_and_the_round_still_counts():
    assert (revive_cost(career()), revive_cost(career(revives=2))) == (
        REVIVE_BASE_COST, REVIVE_BASE_COST + 2 * REVIVE_COST_STEP)
    save = save_with_round(career(credits=7000, revives=1), survived=False, cause="killed by the Wizard",
                           ends_as="Bartender")
    summary = finish_round(save)
    assert (summary["survived"], summary["revive_cost"], summary["credits"], summary["career_over"]) == (
        False, 6000, 1000, False)
    assert summary["unlocked"] == ["Bartender"]
    assert save["career"] == {"name": "Ada", "credits": 1000, "rounds": 1, "revives": 2, "unlocked": ["Bartender"],
                              "captain": False, "pick_owed": False, "files": STARTING_FILES}


def test_dying_without_the_credits_to_be_revived_ends_the_career():
    save = save_with_round(career(credits=4999), survived=False, cause="left behind when the shuttle departed")
    summary = finish_round(save)
    assert (save["career"], save["shift"]) == (None, None)
    assert (summary["career_over"], summary["revive_cost"], summary["unlocked"], summary["pick_owed"]) == (
        True, None, [], False)


def test_a_single_round_leaves_the_career_alone():
    mine = career(credits=2500, rounds=3, unlocked=["Chef"])
    shift = new_game("Medical", "Doctor", ANTAGONIST).player_data
    shift["round"]["outcome"] = {"survived": False, "cause": "killed by the Alien", "seconds": 61}
    save = {"career": dict(mine), "shift": shift, "summary": None}
    summary = finish_round(save)
    assert (save["career"], save["shift"]) == (mine, None)
    assert (summary["mode"], summary["minutes"], summary["unlocked"], summary["career_over"]) == (
        ANTAGONIST, 1, [], False)


def test_access_control_offers_a_career_every_job_it_can_be_given_locked_or_not():
    game = SpaceStationGame(start_career_shift(career(), START_JOB))
    game.player_data["location"] = location_from_key(BRIDGE_KEY)
    game.open_panel("access_request")
    assert game.view()["panel"]["ctx"]["jobs"] == REQUESTABLE_JOBS
    game.perform("panel.select", {"job": TOP_JOB})
    assert game.view()["panel"]["ctx"]["selected"] is None
    game.perform("panel.select", {"job": "Doctor"})
    game.perform("panel.submit", {})
    assert game.player_data["access_request"]["requested_job"] == "Doctor"


def test_security_issues_its_kit_from_the_armory_and_the_fabricator_makes_the_rest():
    game = open_station(in_room(SECURITY_KEY, "Security", "Security Guard"), "security_station", "open_armory")
    assert [item["id"] for item in game.player_data["inventory"]] == list(ARMORY_ITEM_IDS)
    assert last_message(game) == ("Armory", "You take the Stun Baton and Handcuffs and Energy Sword from the "
                                            "Security armory. Equip them from Hands to use them.")
    game.perform("room.open_armory", {})
    assert last_message(game) == ("Armory", "You already have everything the armory issues.")

    fabricating = in_room(ENGINEERING_KEY, "Security", "Security Guard")
    fabricating.perform("room.access_fabricator", {})
    fabricating.perform("panel.category", {"name": "Weapon"})
    assert ctx(fabricating)["item_names"] == ["Crowbar (2 ore)", "Combat Knife (3 ore)", "Fire Axe (4 ore)"]

    visitor = open_station(in_room(SECURITY_KEY), "security_station", "open_armory")
    assert visitor.player_data["inventory"] == []


def user_id(app):
    with app.app_context():
        return db.get_user_by_name("pilot")["id"]


def change_save(app, change):
    def run(save, ui_state):
        change(save)
        return True, save, ui_state

    with app.app_context():
        assert db.update_character(user_id(app), run)


def load(app):
    with app.app_context():
        return db.load_save(user_id(app))[0]


SURVIVED = {"survived": True, "cause": "reached Central Command", "seconds": 1500}


def start_career(client, name="Ada"):
    register(client)
    return post(client, "/career/new", name=name)


def end_shift(client, app, change):
    """Make change to the save, then tick so the game finds the shift over."""
    change_save(app, change)
    return act(client, action="tick")


def test_starting_a_career_from_the_lobby(client, app):
    register(client)
    assert post(client, "/career/new", name="").headers["Location"] == "/"
    assert b"Please enter a character name." in client.get("/").data
    post(client, "/career/new", name="Persistent Pat")
    assert load(app)["career"]["name"] == "Persistent Pat"
    post(client, "/career/new", name="Twin")
    lobby = client.get("/").data
    assert b"You already have a career." in lobby and b"Persistent Pat" in lobby and b"Twin" not in lobby
    assert b'<li class="ladder-open">' in lobby and b'<li class="ladder-locked">' in lobby
    assert b"5000 credits if you die" in lobby and b"Start Shift" in lobby and b"Delete Career" in lobby
    assert b'value="Persistent Pat"' in lobby


def test_the_lobby_lists_the_unlocked_jobs_then_folds_the_locked_ones_under_them(client, app):
    start_career(client)
    lobby = client.get("/").data.decode()
    ladder = lobby[lobby.index('<ol class="ladder">'):lobby.index("</details>")]
    unlocked, _, locked = ladder.partition("<details>")
    assert "Staff Assistant" in unlocked and "Bartender" not in unlocked and "ladder-locked" not in unlocked
    assert "Show 11 locked jobs" in locked and all(job in locked for job in ("Bartender", "Chef", "Captain"))
    assert "Staff Assistant" not in locked and "ladder-open" not in locked
    assert ">Unlocked<" not in ladder and ">Locked<" not in ladder

    change_save(app, lambda save: save["career"].update(unlocked=list(REGULAR_JOBS), captain=True))
    assert "locked jobs" not in client.get("/").data.decode()


def test_a_career_shift_takes_an_unlocked_job_and_cannot_be_abandoned(client, app):
    start_career(client)
    assert start_round(client, job="Doctor", mode="career").headers["Location"] == "/"
    assert b"Your career hasn&#39;t unlocked that job yet." in client.get("/").data
    assert start_round(client, job=START_JOB, mode="career").headers["Location"] == "/play"
    assert load(app)["shift"]["round"]["mode"] == CAREER
    lobby = client.get("/").data
    assert b"Round in Progress" in lobby and b"Abandon Round" not in lobby and b"Start Shift" not in lobby
    post(client, "/round/abandon")
    assert b"A career shift can&#39;t be abandoned." in client.get("/").data
    assert load(app)["shift"] is not None


def test_abandoning_a_single_round(client, app):
    register(client)
    post(client, "/round/abandon")
    assert b"You have no round in progress." in client.get("/").data
    start_round(client, mode="antagonist")
    post(client, "/round/abandon")
    assert load(app)["shift"] is None
    assert b"Start Round" in client.get("/").data


def test_the_round_ending_sends_the_player_to_the_shift_report(client, app):
    register(client)
    assert client.get("/round/summary").headers["Location"] == "/"
    post(client, "/career/new", name="Ada")
    assert client.get("/round/summary").headers["Location"] == "/"
    start_round(client, mode="career")

    def end(save):
        save["shift"]["round"].update(outcome=SURVIVED, salary_paid=200)
        save["shift"]["job"] = "Bartender"

    assert end_shift(client, app, end).get_json() == {"redirect": "/round/summary"}
    saved = load(app)
    assert (saved["shift"], saved["career"]["rounds"], saved["summary"]["unlocked"]) == (None, 1, ["Bartender"])
    report = client.get("/round/summary").data
    for text in (b"You made it.", b"Reached Central Command", b"200 credits", b"0 done, 0 missed",
                 b"Ada, Staff Assistant (ended the shift as Bartender)",
                 b"Unlocked: Bartender, paying 150 credits every 10 minutes."):
        assert text in report, text
    assert b"Pick one to unlock" not in report
    assert client.get("/play").headers["Location"] == "/"
    assert start_round(client, job="Bartender", mode="career").headers["Location"] == "/play"
    assert load(app)["summary"] is None


def test_picking_a_job_after_a_shift_that_ended_without_a_new_one(client, app):
    register(client)
    assert post(client, "/career/unlock", job="Doctor").headers["Location"] == "/"
    assert b"Start a career first." in client.get("/").data
    post(client, "/career/new", name="Ada")
    start_round(client, mode="career")
    end_shift(client, app, lambda save: save["shift"]["round"].update(outcome=SURVIVED))
    report = client.get("/round/summary").data
    assert b"Pick one to unlock" in report and b"There was nothing new to unlock." not in report
    lobby = client.get("/").data
    assert b"Pick one to unlock" in lobby and b'<option value="Doctor">' in lobby
    post(client, "/career/unlock", job="Captain")
    assert b"Pick one of the jobs you haven&#39;t unlocked yet." in client.get("/").data
    post(client, "/career/unlock", job="Doctor")
    mine = load(app)["career"]
    assert (mine["unlocked"], mine["pick_owed"]) == (["Doctor"], False)
    assert b"Pick one to unlock" not in client.get("/").data
    assert start_round(client, job="Doctor", mode="career").headers["Location"] == "/play"


def test_the_round_ending_on_the_play_page_goes_to_the_report_too(client, app):
    register(client)
    start_round(client, mode="antagonist")

    def end(save):
        save["shift"]["round"]["outcome"] = {"survived": False, "cause": "killed by the Alien", "seconds": 300}
        save["shift"]["stock_holdings"] = {save["shift"]["stock_market"]["companies"][0]["name"]: 1}

    change_save(app, end)
    assert client.get("/play").headers["Location"] == "/round/summary"
    report = client.get("/round/summary").data
    for text in (b"You did not make it.", b"Killed by the Alien", b"cashed out for",
                 b"This was a single round. Nothing from it is kept."):
        assert text in report, text
    assert b"ended the shift as" not in report


def test_the_report_for_a_career_that_ended_and_for_a_revival(client, app):
    start_career(client)
    start_round(client, mode="career")

    def die(save):
        save["shift"]["round"]["outcome"] = {"survived": False, "cause": "killed by the Wizard", "seconds": 600}
        save["shift"]["threats"] = []

    end_shift(client, app, lambda save: (save["shift"].update(credits=9000), die(save)))
    report = client.get("/round/summary").data
    assert b"for 5000 credits" in report and b"There were no antagonists this round." in report
    assert load(app)["career"]["revives"] == 1

    start_round(client, mode="career")
    end_shift(client, app, lambda save: (save["shift"].update(credits=10), die(save)))
    report = client.get("/round/summary").data
    assert b"You could not pay to be revived. This career is over." in report
    assert load(app)["career"] is None
    assert b"Start Career" in client.get("/").data


def test_a_career_round_with_nothing_left_to_unlock(client, app):
    start_career(client)
    change_save(app, lambda save: save["career"].update(unlocked=list(REGULAR_JOBS), captain=True))
    start_round(client, job=TOP_JOB, mode="career")
    end_shift(client, app, lambda save: save["shift"]["round"].update(outcome=SURVIVED))
    assert b"There was nothing new to unlock." in client.get("/round/summary").data


def test_starting_a_career_says_so_and_opens_the_career_panel(client):
    response = start_career(client)
    assert response.headers["Location"] == "/?panel=career"
    lobby = client.get(response.headers["Location"]).data.decode()
    assert "Career started. Pick a job and start your first shift." in lobby
    assert 'class="lobby-block hidden" id="lobby-chooser"' in lobby
    assert 'class="lobby-block" data-lobby-panel="career"' in lobby
    assert 'class="lobby-block" id="lobby-chooser"' in client.get("/").data.decode()


def test_home_says_a_career_is_over_until_a_new_one_starts(client, app):
    start_career(client)
    save = save_with_round(career(credits=0), survived=False, cause="killed by the Wizard")

    def career_ends(stored):
        stored.update(save)
        finish_round(stored)

    change_save(app, career_ends)
    lobby = client.get("/").data.decode()
    assert "<h2>Career Over</h2>" in lobby
    assert "Ada's career ended: killed by the Wizard, with no credits left for a revive." in lobby
    post(client, "/career/new", name="Bea")
    assert "Career Over" not in client.get("/").data.decode()
