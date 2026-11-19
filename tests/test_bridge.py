import pytest

from helpers import (
    buttons,
    choose,
    crew,
    drain,
    give_duty,
    in_room,
    labels,
    last_message,
    new_game,
    open_station,
    panel,
)
from space_online.game.character_methods.character_creation import REQUESTABLE_JOBS
from space_online.game.helper_methods.crew_work import post_worker
from space_online.game.helper_methods.jail import arrest_member, tick_jail_releases
from space_online.game.helper_methods.npc_movement import JOB_POSTS, post_holder
from space_online.game.special_rooms import bridge
from space_online.game.special_rooms.bridge import ACCESS_DECISION_SECONDS_RANGE
from space_online.game.maps.donut import BAR_KEY, BRIDGE_KEY, ENGINEERING_KEY, location_from_key


def on_bridge(department="Civilian", job="Staff Assistant"):
    return in_room(BRIDGE_KEY, department, job)


def hop_says(monkeypatch, yes):
    monkeypatch.setattr(bridge.random, "random", lambda: 0.0 if yes else 0.99)


def request_job(game, job, by=None, decide_at=30):
    game.player_data["access_request"] = {"requested_job": job, "requester_name": by or game.player_data["name"],
                                          "decide_at": decide_at}


def answer_comes(game, monkeypatch, yes):
    """Let the Head of Personnel's answer to the player's request fall due."""
    hop_says(monkeypatch, yes=yes)
    game.player_data["game_clock"]["elapsed_seconds"] = game.player_data["access_request"]["decide_at"]
    bridge.tick_access_request(game)


def test_visitors_talk_to_leadership():
    game = on_bridge()
    assert buttons(game) == [("Talk to Ship Leadership", "room.talk_to_leadership")]
    game.perform("room.talk_to_leadership", {})
    assert buttons(game) == [("Ship Leadership", None), ("Talk to Captain", "room.talk_to_captain"),
                             ("Talk to HoP", "room.show_hop_talk_menu"), ("Return to Bridge", "room.set_mode")]
    game.perform("room.talk_to_captain", {})
    assert last_message(game) == ("Captain", "The Captain is too busy for your chats.")


def test_leadership_away_from_the_bridge_can_be_called():
    game = on_bridge()
    captain = crew(game, "Captain")
    captain.update(on_duty=False, location={"x": 2, "y": 5})
    game.ui["room_mode"] = "leadership"
    assert buttons(game)[1:3] == [("The Captain is away from the bridge.", None),
                                  (f"Call {captain['name']}", "room.call_npc")]
    game.perform("room.talk_to_captain", {})
    assert game._messages == []


def test_no_leadership_on_the_station():
    game = on_bridge()
    for job in ("Captain", "Head of Personnel"):
        crew(game, job)["job"] = "Staff Assistant"
    game.perform("room.talk_to_leadership", {})
    assert last_message(game) == ("Bridge", "Captain and Department Heads are not in.")
    game.ui["room_mode"] = "leadership"
    assert buttons(game) == [("Ship Leadership", None), ("Return to Bridge", "room.set_mode")]


def test_the_hop_talk_menu_needs_the_hop_in():
    game = on_bridge()
    game.perform("room.show_hop_talk_menu", {})
    assert buttons(game) == [("Head of Personnel", None), ("Access Control", "room.show_access_control"),
                             ("Talk to HoP", "room.resolve_hop_access_request"), ("Return to Bridge", "room.set_mode")]
    crew(game, "Head of Personnel")["on_duty"] = False
    assert buttons(game) == [("Talk to Ship Leadership", "room.talk_to_leadership")]
    game.ui["room_mode"] = "options"
    for action in ("show_hop_talk_menu", "show_access_control", "resolve_hop_access_request"):
        game.perform(f"room.{action}", {})
    assert (game.ui["room_mode"], game.ui["panels"], game._messages) == ("options", [], [])


def test_requesting_a_job_at_access_control(monkeypatch):
    game = on_bridge()
    game.perform("room.show_access_control", {})
    ctx = panel(game)["ctx"]
    assert (ctx["jobs"], ctx["result"]) == (REQUESTABLE_JOBS, {"text": "Select a job to request.", "color": "cyan"})
    game.perform("panel.submit", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "Select a job first."
    game.perform("panel.select", {"job": "Captain"})
    game.perform("panel.select", {"job": "Doctor"})
    assert panel(game)["ctx"]["result"] == {"text": "Ada → Doctor", "color": "white"}
    monkeypatch.setattr(bridge.random, "randint", lambda low, high: low)
    game.perform("panel.submit", {})
    ctx = panel(game)["ctx"]
    assert (ctx["result"], ctx["feedback"]["text"]) == ({"text": bridge.ACCESS_PENDING, "color": "cyan"},
                                                        "Request for Doctor submitted for HoP approval.")
    assert game.player_data["access_request"] == {"requested_job": "Doctor", "requester_name": "Ada",
                                                  "decide_at": ACCESS_DECISION_SECONDS_RANGE[0]}


def test_the_hop_has_nothing_to_decide_without_a_request():
    game = on_bridge()
    game.perform("room.resolve_hop_access_request", {})
    assert last_message(game) == ("Head of Personnel",
                                  "The HoP is busy. Use the Access Control terminal to put in a request.")


def test_talking_to_the_hop_about_a_request_waits_for_the_pda(monkeypatch):
    game = on_bridge()
    request_job(game, "Doctor")
    hop_says(monkeypatch, yes=True)
    game.perform("room.resolve_hop_access_request", {})
    assert last_message(game) == ("Head of Personnel", "The HoP will answer your request on your PDA.")
    assert game.player_data["job"] == "Staff Assistant"


def test_the_hop_approves_a_request_on_the_pda_once_it_is_due(monkeypatch):
    game = on_bridge()
    request_job(game, "Doctor")
    hop_says(monkeypatch, yes=True)
    game.player_data["game_clock"]["elapsed_seconds"] = 29
    bridge.tick_access_request(game)
    assert (game.player_data["job"], game._messages) == ("Staff Assistant", [])
    answer_comes(game, monkeypatch, yes=True)
    approved = "The HoP approved your request. You are now Doctor."
    assert last_message(game) == ("Head of Personnel", approved)
    assert approved in [message["text"] for message in game.player_data["pda"]["messages"]]
    assert (game.player_data["job"], game.player_data["subdepartment"]) == ("Doctor", "Doctor")
    assert "access_request" not in game.player_data


def test_the_hop_answers_only_once_they_can_work(monkeypatch):
    game = on_bridge()
    request_job(game, "Doctor")
    hop = crew(game, "Head of Personnel")
    hop.update(in_jail=True, jail_release_at_seconds=10 ** 6)
    answer_comes(game, monkeypatch, yes=True)
    assert (game.player_data["job"], game._messages) == ("Staff Assistant", [])
    hop["in_jail"] = False
    bridge.tick_access_request(game)
    assert game.player_data["job"] == "Doctor"


def test_the_hop_denies_a_request(monkeypatch):
    game = on_bridge()
    request_job(game, "Doctor")
    game.perform("room.show_access_control", {})
    assert panel(game)["ctx"]["result"]["text"] == bridge.ACCESS_PENDING
    answer_comes(game, monkeypatch, yes=False)
    assert last_message(game) == ("Head of Personnel", "The HoP denied your request for Doctor.")
    assert panel(game)["ctx"]["result"] == {"text": "Select a job to request.", "color": "cyan"}
    assert (game.player_data["job"], game.player_data.get("access_request")) == ("Staff Assistant", None)


def test_a_new_engineer_switches_the_solar_array_on(monkeypatch):
    game = on_bridge()
    game.player_data["station_power"]["solar_charging"] = False
    request_job(game, "Engineer")
    answer_comes(game, monkeypatch, yes=True)
    assert last_message(game)[1] == "The HoP approved your request. You are now Engineer. Solar arrays are now active."
    assert game.player_data["station_power"]["solar_charging"]


def test_the_npc_hop_leaves_a_crew_members_request_to_the_player(monkeypatch):
    game = on_bridge("Administration", "Head of Personnel")
    assistant = crew(game, "Staff Assistant")
    request_job(game, "Engineer", assistant["name"], decide_at=None)
    hop_says(monkeypatch, yes=True)
    bridge.tick_access_request(game)
    assert (assistant["job"], game._messages) == ("Staff Assistant", [])


def test_the_captains_station():
    game = on_bridge("Administration", "Captain")
    assert labels(game) == ["Enter Captain's Station", "Enter HoP's Station",
                                                     "Lock/Unlock Door", "Room Options"]
    game.perform("room.open_station", {"mode": "captain_station"})
    assert labels(game) == ["Captain's Station", "Station Status", "Security Alerts",
                                                     "Incident Log", "Crew Manifest", "Call Crew Shuttle",
                                                     "Back to Bridge Menu"]
    game.perform("room.show_incident_log", {})
    assert panel(game)["type"] == "incident_log"
    game.ui["panels"] = []
    game.perform("room.show_station_status", {})
    assert panel(game)["type"] == "station_status"
    game.ui["panels"] = []
    game.perform("room.show_crew_manifest", {})
    assert panel(game)["type"] == "crew_manifest"


def test_security_alerts_list_the_wanted_still_at_large():
    game = on_bridge("Administration", "Captain")
    open_station(game, "captain_station", "security_alerts")
    assert last_message(game) == ("Security Alerts", "No security alerts reported.")
    hop, guard = crew(game, "Head of Personnel"), crew(game, "Security Guard")
    hop["warrant"] = True
    guard.update(warrant=True, in_jail=True)
    game.player_data["warrant"] = True
    game.perform("room.security_alerts", {})
    assert last_message(game) == ("Security Alerts", f"Wanted crew at large: Ada, {hop['name']}.")


def test_the_hop_station():
    game = on_bridge("Administration", "Head of Personnel")
    assert labels(game) == ["Enter HoP's Station", "Lock/Unlock Door", "Room Options"]
    game.perform("room.open_station", {"mode": "hop_station"})
    assert labels(game) == ["Head of Personnel Station", "Crew Manifest", "Job Assignments",
                                                     "Access Control", "Back to Bridge Menu"]
    game.perform("room.open_station", {"mode": "captain_station"})
    game.perform("room.show_station_status", {})
    assert (game.ui["room_mode"], game.ui["panels"]) == ("hop_station", [])
    game.perform("room.show_crew_manifest", {})
    assert panel(game)["type"] == "crew_manifest"


def test_visitors_get_no_manifest():
    game = on_bridge()
    game.perform("room.show_crew_manifest", {})
    assert game.ui["panels"] == []


def at_hop_station(game, action):
    return open_station(game, "hop_station", action)


def test_the_hop_console_approves_and_denies():
    game = at_hop_station(on_bridge("Administration", "Head of Personnel"), "show_hop_access_control_console")
    assistant = crew(game, "Staff Assistant")
    assert panel(game)["ctx"] == {"request": None, "feedback": None}
    game.perform("panel.approve", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "No pending request to approve."
    game.perform("panel.deny", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "No pending request to deny."
    request_job(game, "Bartender", assistant["name"], decide_at=None)
    assert panel(game)["ctx"]["request"] == f"{assistant['name']} → Bartender"
    game.perform("panel.deny", {})
    assert last_message(game) == ("Access Control", "Denied request for Bartender.")
    assert game.ui["panels"] == []
    at_hop_station(game, "show_hop_access_control_console")
    request_job(game, "Bartender", assistant["name"], decide_at=None)
    game.perform("panel.approve", {})
    assert last_message(game) == ("Access Control", f"Approved. {assistant['name']} is now Bartender.")
    assert assistant["job"] == "Bartender"


def test_the_hop_console_reports_a_request_it_cannot_grant():
    game = at_hop_station(on_bridge("Administration", "Head of Personnel"), "show_hop_access_control_console")
    request_job(game, "Wizard", decide_at=None)
    game.perform("panel.approve", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "Your access request was invalid and has been cleared."


def test_the_hop_console_clears_a_request_from_someone_no_longer_aboard():
    game = at_hop_station(on_bridge("Administration", "Head of Personnel"), "show_hop_access_control_console")
    assistant = crew(game, "Staff Assistant")
    request_job(game, "Bartender", assistant["name"], decide_at=None)
    game.station_crew.remove(assistant)
    game.perform("panel.approve", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "The requester is no longer on the station. Request cleared."
    assert "access_request" not in game.player_data


def test_the_hop_assigns_jobs_to_crew_but_not_the_captain():
    game = at_hop_station(on_bridge("Administration", "Head of Personnel"), "show_job_assignments")
    ctx = panel(game)["ctx"]
    assert "Captain" not in ctx["jobs"]
    assert not any(row["label"].endswith("(Captain)") for row in ctx["rows"])
    assert "Ada" not in [row["name"] for row in ctx["rows"]]
    assert ctx["result"] == {"text": "Select an NPC and a job to confirm.", "color": "cyan"}
    assistant = crew(game, "Staff Assistant")
    game.perform("panel.select_job", {"job": "Doctor"})
    assert panel(game)["ctx"]["result"]["text"] == "Select an NPC for Doctor."
    game.perform("panel.select_job", {"job": "Wizard"})
    game.perform("panel.select_member", {"name": assistant["name"]})
    assert panel(game)["ctx"]["result"] == {"text": f"{assistant['name']} → Doctor", "color": "white"}
    game.perform("panel.assign", {})
    ctx = panel(game)["ctx"]
    assert (ctx["result"]["color"], ctx["feedback"]["text"]) == ("lightgreen", f"Assigned {assistant['name']} as Doctor.")
    assert (assistant["job"], assistant["on_duty"]) == ("Doctor", True)


def test_picking_crew_before_a_job():
    game = at_hop_station(on_bridge("Administration", "Head of Personnel"), "show_job_assignments")
    assistant = crew(game, "Staff Assistant")
    game.perform("panel.select_member", {"name": assistant["name"]})
    assert panel(game)["ctx"]["result"] == {"text": f"{assistant['name']} - select a job.",
                                            "color": "cyan"}


def test_assigning_an_engineer_switches_the_solar_array_on():
    game = at_hop_station(on_bridge("Administration", "Head of Personnel"), "show_job_assignments")
    game.player_data["station_power"]["solar_charging"] = False
    assistant = crew(game, "Staff Assistant")
    game.perform("panel.select_member", {"name": assistant["name"]})
    game.perform("panel.select_job", {"job": "Engineer"})
    game.perform("panel.assign", {})
    assert panel(game)["ctx"]["feedback"]["text"].endswith(" as Engineer. Solar arrays are now active.")


def test_job_assignment_mistakes():
    game = at_hop_station(on_bridge("Administration", "Head of Personnel"), "show_job_assignments")
    game.perform("panel.assign", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "Select both an NPC and a job first."
    game.perform("panel.select_member", {"name": crew(game, "Captain")["name"]})
    game.perform("panel.select_job", {"job": "Doctor"})
    assert panel(game)["ctx"]["crew_name"] is None
    game.perform("panel.assign", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "Invalid NPC selection."
    game.perform("panel.select_member", {"name": crew(game, "Staff Assistant")["name"]})
    game.ui["panels"][-1]["job"] = "Wizard"
    game.perform("panel.assign", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "Invalid job selection."
    game.ui["panels"][-1]["job"] = "Captain"
    game.perform("panel.assign", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "Only the Captain can assign the Captain role."


def test_a_captain_confirms_before_giving_up_the_only_captaincy():
    game = at_hop_station(on_bridge("Administration", "Captain"), "show_job_assignments")
    rows = panel(game)["ctx"]["rows"]
    assert rows[0] == {"name": "Ada", "label": "Ada (Captain) (YOU)"}
    game.perform("panel.select_member", {"name": "Ada"})
    game.perform("panel.select_job", {"job": "Bartender"})
    assert panel(game)["ctx"]["result"]["text"] == "Ada → Bartender"
    game.perform("panel.assign", {})
    choice = game.view()["choice"]
    assert (choice["title"], game.player_data["job"]) == ("Confirm Reassignment", "Captain")
    choose(game, "Yes")
    assert game.player_data["job"] == "Bartender"
    assert game.ui["panels"] == []


def assign(game, name, job):
    game.perform("panel.select_member", {"name": name})
    game.perform("panel.select_job", {"job": job})
    game.perform("panel.assign", {})


def test_a_captain_who_makes_someone_else_captain_steps_down_to_staff_assistant():
    game = at_hop_station(on_bridge("Administration", "Captain"), "show_job_assignments")
    assistant = crew(game, "Staff Assistant")
    assign(game, assistant["name"], "Captain")
    assert game.view()["choice"]["message"] == ("Ada is the Captain and will become a Staff Assistant. Continue?")
    choose(game, "No")
    assert (assistant["job"], game.player_data["job"]) == ("Staff Assistant", "Captain")
    assign(game, assistant["name"], "Captain")
    choose(game, "Yes")
    assert (assistant["job"], game.player_data["job"]) == ("Captain", "Staff Assistant")
    assert drain(game)[-1]["message"] == f"{assistant['name']} is now the Captain. Ada is now a Staff Assistant."
    assert game.ui["panels"] == []


def test_there_is_only_ever_one_head_of_personnel():
    game = at_hop_station(on_bridge("Administration", "Captain"), "show_job_assignments")
    hop, chef = crew(game, "Head of Personnel"), crew(game, "Chef")
    assign(game, chef["name"], "Head of Personnel")
    assert game.view()["choice"]["message"] == (
        f"{hop['name']} is the Head of Personnel and will become a Staff Assistant. Continue?")
    choose(game, "Yes")
    assert [member["job"] for member in (hop, chef)] == ["Staff Assistant", "Head of Personnel"]
    assert sum(member["job"] == "Head of Personnel" for member in (game.player_data, *game.station_crew)) == 1
    assert drain(game)[-1]["message"] == (f"{chef['name']} is now the Head of Personnel. "
                                          f"{hop['name']} is now a Staff Assistant.")


@pytest.mark.parametrize("job", ["Head of Personnel", "Doctor", "Engineer", "Security Guard"])
def test_taking_a_key_job_away_asks_first(job):
    game = at_hop_station(on_bridge("Administration", "Captain"), "show_job_assignments")
    member = crew(game, job)
    assign(game, member["name"], "Bartender")
    assert game.view()["choice"]["message"] == f"{member['name']} will no longer be the {job}. Continue?"
    choose(game, "No")
    assert member["job"] == job and drain(game) == []
    assign(game, member["name"], "Bartender")
    choose(game, "Yes")
    assert member["job"] == "Bartender"
    assert drain(game)[-1] == {"title": "Job Assignment", "message": f"{member['name']} is now a Bartender.",
                               "kind": "info"}


def test_a_captain_stepping_down_always_asks():
    game = at_hop_station(on_bridge("Administration", "Captain"), "show_job_assignments")
    crew(game, "Staff Assistant")["job"] = "Captain"
    assign(game, "Ada", "Engineer")
    assert game.view()["choice"]["message"] == "You are about to give up the Captain's post. Continue?"
    game.player_data["station_power"]["solar_charging"] = False
    choose(game, "Yes")
    assert (game.player_data["job"], game.player_data["station_power"]["solar_charging"]) == ("Engineer", True)


def test_an_ordinary_assignment_needs_no_confirmation_and_is_logged():
    game = at_hop_station(on_bridge("Administration", "Captain"), "show_job_assignments")
    chef = crew(game, "Chef")
    assign(game, chef["name"], "Chef")
    assert game.ui["choices"] == [] and drain(game)[-1]["message"] == f"{chef['name']} is now a Chef."
    assign(game, chef["name"], "Bartender")
    assert (game.ui["choices"], chef["job"]) == ([], "Bartender")


def test_a_captains_job_request_also_asks_before_leaving_the_station_without_a_captain(monkeypatch):
    game = on_bridge("Administration", "Captain")
    request_job(game, "Bartender")
    answer_comes(game, monkeypatch, yes=True)
    assert game.player_data["job"] == "Captain"
    assert game.ui["choices"] and game.ui["choices"][0]["title"] == "Confirm Reassignment"
    assert game._messages == []
    choose(game, "Yes")
    assert game.player_data["job"] == "Bartender"
    assert "access_request" not in game.player_data
    assert last_message(game) == ("Access Control", "You are now Bartender.")


def test_a_captain_approving_their_own_request_on_the_console_is_asked_too():
    game = at_hop_station(on_bridge("Administration", "Captain"), "show_hop_access_control_console")
    request_job(game, "Engineer")
    game.player_data["station_power"]["solar_charging"] = False
    game.perform("panel.approve", {})
    assert panel(game)["type"] == "hop_console"
    assert panel(game)["ctx"]["feedback"] is None
    choose(game, "Yes")
    assert (game.player_data["job"], game.ui["panels"]) == ("Engineer", [])
    assert last_message(game) == ("Access Control", "You are now Engineer. Solar arrays are now active.")


def test_saying_no_keeps_the_captaincy_and_the_request():
    game = at_hop_station(on_bridge("Administration", "Captain"), "show_hop_access_control_console")
    request_job(game, "Bartender")
    game.perform("panel.approve", {})
    choose(game, "No")
    assert game.player_data["job"] == "Captain"
    assert game.player_data["access_request"]["requested_job"] == "Bartender"


def test_a_confirmation_for_a_request_that_has_since_changed_does_nothing():
    game = at_hop_station(on_bridge("Administration", "Captain"), "show_hop_access_control_console")
    request_job(game, "Bartender")
    game.perform("panel.approve", {})
    choice = game.view()["choice"]
    request_job(game, "Doctor")
    game.perform("game.choose", {"id": choice["id"], "index": 0})
    assert game.player_data["job"] == "Captain"
    assert game.player_data["access_request"]["requested_job"] == "Doctor"


def test_a_captain_with_another_captain_aboard_changes_job_without_being_asked():
    game = at_hop_station(on_bridge("Administration", "Captain"), "show_hop_access_control_console")
    game.station_crew[0]["job"] = "Captain"
    request_job(game, "Bartender")
    game.perform("panel.approve", {})
    assert (game.player_data["job"], game.ui["choices"]) == ("Bartender", [])


def test_the_hop_cannot_take_the_captaincy_away_through_an_access_request():
    game = at_hop_station(on_bridge("Administration", "Head of Personnel"), "show_hop_access_control_console")
    captain = crew(game, "Captain")
    request_job(game, "Staff Assistant", captain["name"], decide_at=None)
    game.perform("panel.approve", {})
    assert captain["job"] == "Captain"
    assert "access_request" not in game.player_data
    assert panel(game)["ctx"]["feedback"]["text"] == (
        "Only the Captain can reassign the current Captain. Request cleared.")


def test_a_captain_can_approve_a_captains_request():
    game = at_hop_station(on_bridge("Administration", "Captain"), "show_hop_access_control_console")
    other = game.station_crew[0]
    other["job"] = "Captain"
    request_job(game, "Doctor", other["name"], decide_at=None)
    game.perform("panel.approve", {})
    assert other["job"] == "Doctor"


def test_assign_role_ignores_a_crew_member_who_is_gone():
    game = on_bridge("Administration", "Captain")
    bridge.assign_role(game, 99, "Doctor")
    assert game.player_data["job"] == "Captain"


def test_a_new_job_leaves_the_old_jobs_duties_behind():
    game = new_game("Administration", "Captain")
    give_duty(game, kind="help", room=BAR_KEY, summary="Busy")
    give_duty(game, kind="help", room=BAR_KEY, summary="Busier")
    game.open_panel("job_assignment")
    bridge.assign_role(game, game.player_data["name"], "Engineer")
    assert (game.player_data["duties"], game.player_data["round"]["duties_missed"]) == ([], 0)
    assert {"title": "Duties", "message": "Your open duties stay with your old job.", "kind": "info"} in drain(game)
    give_duty(game, kind="help", room=BAR_KEY, summary="Busy")
    chef = crew(game, "Chef")
    game.open_panel("job_assignment")
    bridge.assign_role(game, chef["name"], "Bartender")
    assert len(game.player_data["duties"]) == 1


def test_a_jailed_crew_member_given_a_new_job_stays_jailed_and_takes_the_post_on_release():
    game = at_hop_station(on_bridge("Administration", "Captain"), "show_job_assignments")
    chef = crew(game, "Chef")
    arrest_member(chef, reason="Brawling", game=game)
    cell, release_at = chef["location"], chef["jail_release_at_seconds"]
    assign(game, chef["name"], "Bartender")
    assert (chef["job"], chef["in_jail"], chef["location"], chef["jail_release_at_seconds"]) == (
        "Bartender", True, cell, release_at)
    assert panel(game)["ctx"]["feedback"]["text"] == (
        f"Assigned {chef['name']} as Bartender. They take up the post when released.")
    game.player_data["game_clock"]["elapsed_seconds"] = release_at
    tick_jail_releases(game)
    assert (chef["in_jail"], chef["on_duty"], chef["location"]) == (False, True, location_from_key(BAR_KEY))


def test_a_player_scientist_made_engineer_holds_the_engineer_post(monkeypatch):
    game = new_game("Science", "Scientist")
    assert post_worker(game, "Engineer", ENGINEERING_KEY) is crew(game, "Engineer")
    request_job(game, "Engineer")
    answer_comes(game, monkeypatch, yes=True)
    assert (game.player_data["job"], game.player_data["post_key"]) == ("Engineer", None)
    assert post_worker(game, "Engineer", ENGINEERING_KEY) is None


@pytest.mark.parametrize("free_lab", [None, 1])
def test_a_player_made_scientist_takes_one_lab_and_the_other_labs_keep_working(monkeypatch, free_lab):
    game = new_game()
    labs = JOB_POSTS["Scientist"]
    if free_lab is not None:
        game.station_crew.remove(post_holder(game.station_crew, "Scientist", labs[free_lab]))
    request_job(game, "Scientist")
    answer_comes(game, monkeypatch, yes=True)
    taken = labs[free_lab or 0]
    assert game.player_data["post_key"] == taken
    assert [post_worker(game, "Scientist", lab) for lab in labs] == [
        None if lab == taken else post_holder(game.station_crew, "Scientist", lab) for lab in labs]
