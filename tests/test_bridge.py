import pytest

from helpers import new_game
from space_online.game.character_methods.character_creation import REQUESTABLE_JOBS
from space_online.game.special_rooms import bridge
from space_online.game.special_rooms.shared import PLAYER_CREW_INDEX
from space_online.game.maps.donut import BRIDGE_KEY, ENGINEERING_KEY, location_from_key


def on_bridge(department="Civilian", job="Staff Assistant"):
    game = new_game(department, job)
    game.player_data["location"] = location_from_key(BRIDGE_KEY)
    return game


def crew(game, job):
    return next(npc for npc in game.station_crew if npc["job"] == job)


def crew_index_of(game, job):
    return next(i for i, npc in enumerate(game.station_crew) if npc["job"] == job)


def buttons(game):
    return [(w.get("label") or w.get("text"), w.get("action")) for w in game.view()["screen"]["buttons"]]


def panel(game):
    return game.view()["panel"]


def last_message(game):
    return game._messages[-1][1:3]


def hop_says(monkeypatch, yes):
    monkeypatch.setattr(bridge.random, "random", lambda: 0.0 if yes else 0.99)


def request_job(game, job):
    game.player_data["access_request"] = {"requested_job": job, "requester_name": game.player_data["name"]}


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


def test_requesting_a_job_at_access_control():
    game = on_bridge()
    game.perform("room.show_access_control", {})
    ctx = panel(game)["ctx"]
    assert (ctx["jobs"], ctx["result"]) == (REQUESTABLE_JOBS, {"text": "Select a job to request.", "color": "cyan"})
    game.perform("panel.submit", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "Select a job first."
    game.perform("panel.select", {"job": "Captain"})
    game.perform("panel.select", {"job": "Doctor"})
    assert panel(game)["ctx"]["result"] == {"text": "Ada → Doctor", "color": "white"}
    game.perform("panel.submit", {})
    ctx = panel(game)["ctx"]
    assert (ctx["result"]["color"], ctx["feedback"]["text"]) == ("lightgreen", "Request for Doctor submitted for HoP approval.")
    assert game.player_data["access_request"] == {"requested_job": "Doctor", "requester_name": "Ada"}


def test_a_job_that_cannot_be_requested_is_refused():
    game = on_bridge()
    game.perform("room.show_access_control", {})
    game.ui["panels"][-1]["job"] = "Captain"
    game.perform("panel.submit", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "That job cannot be requested here."
    assert "access_request" not in game.player_data


def test_the_hop_has_nothing_to_decide_without_a_request():
    game = on_bridge()
    game.perform("room.resolve_hop_access_request", {})
    assert last_message(game) == ("Head of Personnel",
                                  "The HoP is busy. Use the Access Control terminal to put in a request.")


def test_the_hop_approves_a_request(monkeypatch):
    game = on_bridge()
    request_job(game, "Doctor")
    hop_says(monkeypatch, yes=True)
    game.perform("room.resolve_hop_access_request", {})
    assert last_message(game) == ("Head of Personnel", "The HoP approved your request. You are now Doctor.")
    assert (game.player_data["job"], game.player_data["subdepartment"]) == ("Doctor", "Doctor")
    assert "access_request" not in game.player_data


def test_the_hop_denies_a_request(monkeypatch):
    game = on_bridge()
    request_job(game, "Doctor")
    hop_says(monkeypatch, yes=False)
    game.perform("room.resolve_hop_access_request", {})
    assert last_message(game) == ("Head of Personnel", "The HoP denied your request for Doctor.")
    assert (game.player_data["job"], game.player_data.get("access_request")) == ("Staff Assistant", None)


def test_a_new_engineer_switches_the_solar_array_on(monkeypatch):
    game = on_bridge()
    game.player_data["station_power"]["solar_charging"] = False
    request_job(game, "Engineer")
    hop_says(monkeypatch, yes=True)
    game.perform("room.resolve_hop_access_request", {})
    assert last_message(game)[1] == "The HoP approved your request. You are now Engineer. Solar arrays are now active."
    assert game.player_data["station_power"]["solar_charging"]


def test_the_hop_approves_a_crew_members_request(monkeypatch):
    game = on_bridge()
    assistant = crew(game, "Staff Assistant")
    game.player_data["access_request"] = {"requested_job": "Engineer", "requester_name": assistant["name"]}
    game.player_data["station_power"]["solar_charging"] = True
    hop_says(monkeypatch, yes=True)
    game.perform("room.resolve_hop_access_request", {})
    assert last_message(game)[1] == (f"The HoP approved {assistant['name']}'s request. {assistant['name']} is now "
                                     "Engineer.")
    assert (assistant["job"], assistant["on_duty"], assistant["location"]) == (
        "Engineer", True, location_from_key(ENGINEERING_KEY))


@pytest.mark.parametrize("access_request, error", [
    ({"requested_job": "Wizard", "requester_name": "Ada"}, "Your access request was invalid and has been cleared."),
    ({"requested_job": "Doctor", "requester_name": "Nobody Here"},
     "The requester is no longer on the station. Request cleared."),
])
def test_requests_that_cannot_be_granted_are_cleared(monkeypatch, access_request, error):
    game = on_bridge()
    game.player_data["access_request"] = access_request
    hop_says(monkeypatch, yes=True)
    game.perform("room.resolve_hop_access_request", {})
    assert last_message(game) == ("Head of Personnel", error)
    assert "access_request" not in game.player_data


def test_the_captains_station():
    game = on_bridge("Administration", "Captain")
    assert [label for label, _ in buttons(game)] == ["Enter Captain's Station", "Enter HoP's Station",
                                                     "Lock/Unlock Door", "Room Options"]
    game.perform("room.open_station", {"mode": "captain_station"})
    assert [label for label, _ in buttons(game)] == ["Captain's Station", "Station Status", "Security Alerts",
                                                     "Crew Manifest", "Back to Bridge Menu"]
    game.perform("room.show_station_status", {})
    assert panel(game)["type"] == "station_status"
    game.ui["panels"] = []
    game.perform("room.show_crew_manifest", {})
    assert panel(game)["type"] == "crew_manifest"


def test_security_alerts_list_the_wanted_still_at_large():
    game = on_bridge("Administration", "Captain")
    game.ui["room_mode"] = "captain_station"
    game.perform("room.security_alerts", {})
    assert last_message(game) == ("Security Alerts", "No security alerts reported.")
    hop, guard = crew(game, "Head of Personnel"), crew(game, "Security Guard")
    hop["warrant"] = True
    guard.update(warrant=True, in_jail=True)
    game.player_data["warrant"] = True
    game.perform("room.security_alerts", {})
    assert last_message(game) == ("Security Alerts", f"Wanted crew at large: Ada, {hop['name']}.")


def test_the_hop_station():
    game = on_bridge("Administration", "Head of Personnel")
    assert [label for label, _ in buttons(game)] == ["Enter HoP's Station", "Lock/Unlock Door", "Room Options"]
    game.perform("room.open_station", {"mode": "hop_station"})
    assert [label for label, _ in buttons(game)] == ["Head of Personnel Station", "Crew Manifest", "Job Assignments",
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


def hop_console(game):
    game.ui["panels"] = []
    game.ui["room_mode"] = "hop_station"
    game.perform("room.show_hop_access_control_console", {})
    return game


def test_the_hop_console_approves_and_denies():
    game = hop_console(on_bridge("Administration", "Head of Personnel"))
    assistant = crew(game, "Staff Assistant")
    assert panel(game)["ctx"] == {"request": None, "feedback": None}
    game.perform("panel.approve", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "No pending request to approve."
    game.perform("panel.deny", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "No pending request to deny."
    game.player_data["access_request"] = {"requested_job": "Bartender", "requester_name": assistant["name"]}
    assert panel(game)["ctx"]["request"] == f"{assistant['name']} → Bartender"
    game.perform("panel.deny", {})
    assert last_message(game) == ("Access Control", "Denied request for Bartender.")
    assert game.ui["panels"] == []
    hop_console(game)
    game.player_data["access_request"] = {"requested_job": "Bartender", "requester_name": assistant["name"]}
    game.perform("panel.approve", {})
    assert last_message(game) == ("Access Control", f"Approved. {assistant['name']} is now Bartender.")
    assert assistant["job"] == "Bartender"


def test_the_hop_console_reports_a_request_it_cannot_grant():
    game = hop_console(on_bridge("Administration", "Head of Personnel"))
    game.player_data["access_request"] = {"requested_job": "Wizard", "requester_name": "Ada"}
    game.perform("panel.approve", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "Your access request was invalid and has been cleared."


def job_assignments(game):
    game.ui["panels"] = []
    game.ui["room_mode"] = "hop_station"
    game.perform("room.show_job_assignments", {})
    return game


def test_the_hop_assigns_jobs_to_crew_but_not_the_captain():
    game = job_assignments(on_bridge("Administration", "Head of Personnel"))
    ctx = panel(game)["ctx"]
    assert "Captain" not in ctx["jobs"]
    assert not any(row["label"].endswith("(Captain)") for row in ctx["rows"])
    assert PLAYER_CREW_INDEX not in [row["index"] for row in ctx["rows"]]
    assert ctx["result"] == {"text": "Select an NPC and a job to confirm.", "color": "cyan"}
    assistant_index = crew_index_of(game, "Staff Assistant")
    assistant = game.station_crew[assistant_index]
    game.perform("panel.select_job", {"job": "Doctor"})
    assert panel(game)["ctx"]["result"]["text"] == "Select an NPC for Doctor."
    game.perform("panel.select_job", {"job": "Wizard"})
    game.perform("panel.select_member", {"index": assistant_index})
    assert panel(game)["ctx"]["result"] == {"text": f"{assistant['name']} → Doctor", "color": "white"}
    game.perform("panel.assign", {})
    ctx = panel(game)["ctx"]
    assert (ctx["result"]["color"], ctx["feedback"]["text"]) == ("lightgreen", f"Assigned {assistant['name']} as Doctor.")
    assert (assistant["job"], assistant["on_duty"]) == ("Doctor", True)


def test_picking_crew_before_a_job():
    game = job_assignments(on_bridge("Administration", "Head of Personnel"))
    assistant_index = crew_index_of(game, "Staff Assistant")
    game.perform("panel.select_member", {"index": assistant_index})
    assert panel(game)["ctx"]["result"] == {"text": f"{game.station_crew[assistant_index]['name']} - select a job.",
                                            "color": "cyan"}


def test_assigning_an_engineer_switches_the_solar_array_on():
    game = job_assignments(on_bridge("Administration", "Head of Personnel"))
    game.player_data["station_power"]["solar_charging"] = False
    assistant_index = crew_index_of(game, "Staff Assistant")
    game.perform("panel.select_member", {"index": assistant_index})
    game.perform("panel.select_job", {"job": "Engineer"})
    game.perform("panel.assign", {})
    assert panel(game)["ctx"]["feedback"]["text"].endswith(" as Engineer. Solar arrays are now active.")


def test_job_assignment_mistakes():
    game = job_assignments(on_bridge("Administration", "Head of Personnel"))
    captain_index = crew_index_of(game, "Captain")
    game.perform("panel.assign", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "Select both an NPC and a job first."
    game.perform("panel.select_member", {"index": captain_index})
    game.perform("panel.select_job", {"job": "Doctor"})
    assert panel(game)["ctx"]["crew_index"] is None
    game.perform("panel.assign", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "Invalid NPC selection."
    game.perform("panel.select_member", {"index": crew_index_of(game, "Staff Assistant")})
    game.ui["panels"][-1]["job"] = "Wizard"
    game.perform("panel.assign", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "Invalid job selection."
    game.ui["panels"][-1]["job"] = "Captain"
    game.perform("panel.assign", {})
    assert panel(game)["ctx"]["feedback"]["text"] == "Only the Captain can assign the Captain role."


def test_a_captain_confirms_before_giving_up_the_only_captaincy():
    game = job_assignments(on_bridge("Administration", "Captain"))
    rows = panel(game)["ctx"]["rows"]
    assert rows[0] == {"index": PLAYER_CREW_INDEX, "label": "Ada (Captain) (YOU)"}
    game.perform("panel.select_member", {"index": PLAYER_CREW_INDEX})
    game.perform("panel.select_job", {"job": "Bartender"})
    assert panel(game)["ctx"]["result"]["text"] == "Ada → Bartender"
    game.perform("panel.assign", {})
    choice = game.view()["choice"]
    assert (choice["title"], game.player_data["job"]) == ("Confirm Reassignment", "Captain")
    game.perform("game.choose", {"id": choice["id"], "index": 0})
    assert game.player_data["job"] == "Bartender"
    assert game.ui["panels"] == []


def test_a_captain_can_promote_crew_to_captain_and_then_step_down_freely():
    game = job_assignments(on_bridge("Administration", "Captain"))
    assistant_index = crew_index_of(game, "Staff Assistant")
    game.perform("panel.select_member", {"index": assistant_index})
    game.perform("panel.select_job", {"job": "Captain"})
    game.perform("panel.assign", {})
    assert game.station_crew[assistant_index]["job"] == "Captain"
    game.perform("panel.select_member", {"index": PLAYER_CREW_INDEX})
    game.perform("panel.select_job", {"job": "Engineer"})
    game.player_data["station_power"]["solar_charging"] = False
    game.perform("panel.assign", {})
    assert game.ui["choices"] == []
    assert (game.player_data["job"], game.player_data["station_power"]["solar_charging"]) == ("Engineer", True)


def test_a_captains_job_request_also_asks_before_leaving_the_station_without_a_captain(monkeypatch):
    game = on_bridge("Administration", "Captain")
    request_job(game, "Bartender")
    hop_says(monkeypatch, yes=True)
    game.ui["room_mode"] = "hop_talk"
    game.perform("room.resolve_hop_access_request", {})
    assert game.player_data["job"] == "Captain"
    assert game.ui["choices"] and game.ui["choices"][0]["title"] == "Confirm Reassignment"
    assert game._messages == []
    game.perform("game.choose", {"id": game.view()["choice"]["id"], "index": 0})
    assert game.player_data["job"] == "Bartender"
    assert "access_request" not in game.player_data
    assert last_message(game) == ("Access Control", "You are now Bartender.")


def test_a_captain_approving_their_own_request_on_the_console_is_asked_too():
    game = hop_console(on_bridge("Administration", "Captain"))
    request_job(game, "Engineer")
    game.player_data["station_power"]["solar_charging"] = False
    game.perform("panel.approve", {})
    assert panel(game)["type"] == "hop_console"
    assert panel(game)["ctx"]["feedback"] is None
    game.perform("game.choose", {"id": game.view()["choice"]["id"], "index": 0})
    assert (game.player_data["job"], game.ui["panels"]) == ("Engineer", [])
    assert last_message(game) == ("Access Control", "You are now Engineer. Solar arrays are now active.")


def test_saying_no_keeps_the_captaincy_and_the_request():
    game = hop_console(on_bridge("Administration", "Captain"))
    request_job(game, "Bartender")
    game.perform("panel.approve", {})
    game.perform("game.choose", {"id": game.view()["choice"]["id"], "index": 1})
    assert game.player_data["job"] == "Captain"
    assert game.player_data["access_request"]["requested_job"] == "Bartender"


def test_a_confirmation_for_a_request_that_has_since_changed_does_nothing():
    game = hop_console(on_bridge("Administration", "Captain"))
    request_job(game, "Bartender")
    game.perform("panel.approve", {})
    choice = game.view()["choice"]
    request_job(game, "Doctor")
    game.perform("game.choose", {"id": choice["id"], "index": 0})
    assert game.player_data["job"] == "Captain"
    assert game.player_data["access_request"]["requested_job"] == "Doctor"


def test_a_captain_with_another_captain_aboard_changes_job_without_being_asked():
    game = hop_console(on_bridge("Administration", "Captain"))
    game.station_crew[0]["job"] = "Captain"
    request_job(game, "Bartender")
    game.perform("panel.approve", {})
    assert (game.player_data["job"], game.ui["choices"]) == ("Bartender", [])


def test_the_hop_cannot_take_the_captaincy_away_through_an_access_request():
    game = hop_console(on_bridge("Administration", "Head of Personnel"))
    captain = crew(game, "Captain")
    game.player_data["access_request"] = {"requested_job": "Staff Assistant", "requester_name": captain["name"]}
    game.perform("panel.approve", {})
    assert captain["job"] == "Captain"
    assert "access_request" not in game.player_data
    assert panel(game)["ctx"]["feedback"]["text"] == (
        "Only the Captain can reassign the current Captain. Request cleared.")


def test_a_captain_can_approve_a_captains_request():
    game = hop_console(on_bridge("Administration", "Captain"))
    other = game.station_crew[0]
    other["job"] = "Captain"
    game.player_data["access_request"] = {"requested_job": "Doctor", "requester_name": other["name"]}
    game.perform("panel.approve", {})
    assert other["job"] == "Doctor"


def test_assign_role_ignores_a_crew_member_who_is_gone():
    game = on_bridge("Administration", "Captain")
    bridge.assign_role(game, 99, "Doctor")
    assert game.player_data["job"] == "Captain"
