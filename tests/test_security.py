import pytest

from helpers import new_game
from space_online.game.helper_methods import jail
from space_online.game.helper_methods.jail import arrest_member, is_jailed, security_hallway_location
from space_online.game.special_rooms.security import MAX_REASON_LENGTH
from space_online.game.special_rooms.shared import PLAYER_CREW_INDEX
from space_online.game.maps.donut import SECURITY_KEY, location_from_key


def in_security(department="Civilian", job="Staff Assistant"):
    game = new_game(department, job)
    game.player_data["location"] = location_from_key(SECURITY_KEY)
    return game


def crew_index(game, job):
    return next(i for i, npc in enumerate(game.station_crew) if npc["job"] == job)


def buttons(game):
    return [(w.get("label") or w.get("text"), w.get("action")) for w in game.view()["screen"]["buttons"]]


def panel(game):
    return game.view()["panel"]


def last_message(game):
    return game._messages[-1][1:3]


def station(game, panel_action):
    game.ui["panels"] = []
    game.ui["room_mode"] = "security_station"
    game.perform(f"room.{panel_action}", {})


def test_visitors_can_talk_to_the_guard():
    game = in_security()
    assert buttons(game) == [("Talk to Security Guard", "room.talk_to_guard")]
    game.perform("room.talk_to_guard", {})
    assert last_message(game) == ("Security Guard",
                                  "The security agent waves you away without looking up from the cameras.")


def test_the_guard_collects_a_visitors_fine(monkeypatch):
    game = in_security()
    game.player_data.update(fine_amount=100, fine_reason="Littering")
    monkeypatch.setattr(jail.random, "random", lambda: 0.99)
    game.perform("room.talk_to_guard", {})
    assert last_message(game) == ("Fine Paid", "The security guard collects your unpaid fine of 100 credits.\n"
                                               "Reason: Littering")


def test_nobody_answers_when_the_guard_is_out():
    game = in_security()
    guard = game.station_crew[crew_index(game, "Security Guard")]
    guard.update(on_duty=False, location={"x": 2, "y": 5})
    assert buttons(game)[0] == ("The security guard has stepped away from the office.", None)
    game.perform("room.talk_to_guard", {})
    assert game._messages == []


def test_a_jailed_player_cannot_walk_out():
    game = in_security()
    game.player_data.update(in_jail=True, jail_release_at_seconds=30)
    game.perform("room.exit", {})
    assert last_message(game) == ("In Jail", "You are in jail. Time remaining: 30s.")
    assert game.location_key() == SECURITY_KEY
    game.player_data["in_jail"] = False
    game.perform("room.exit", {})
    assert game.player_data["location"] == security_hallway_location()


def test_the_station_menu():
    game = in_security("Security", "Security Guard")
    assert [label for label, _ in buttons(game)] == ["Enter Security Station", "Lock/Unlock Door", "Room Options"]
    game.perform("room.open_station", {"mode": "security_station"})
    assert [label for label, _ in buttons(game)] == ["View Crew Manifest", "Issue Warrant/Fine", "View Jail",
                                                     "Back to Station Menu"]
    game.perform("room.set_mode", {"mode": "options"})
    assert buttons(game) == [("Back to Station Menu", "room.set_mode")]


def test_visitors_get_no_station():
    game = in_security()
    game.ui["room_mode"] = "security_station"
    for action in ("view_crew_manifest", "show_issue_warrant", "view_jail"):
        game.perform(f"room.{action}", {})
    assert game.ui["panels"] == []
    assert buttons(game) == [("Talk to Security Guard", "room.talk_to_guard")]


def test_the_crew_manifest_tags_the_player_the_wanted_and_the_jailed():
    game = in_security("Security", "Security Guard")
    doctor = game.station_crew[crew_index(game, "Doctor")]
    doctor.update(warrant=True, in_jail=True)
    station(game, "view_crew_manifest")
    departments = {d["name"]: d["members"] for d in panel(game)["ctx"]["departments"]}
    assert departments["SECURITY"] == [{"text": "- Security Guard: Ada (YOU)", "is_player": True}]
    assert departments["MEDICAL"] == [{"text": f"- Doctor: {doctor['name']} [WANTED] [JAILED]", "is_player": False}]
    assert len(departments["CIVILIAN"]) == 2


def charge(game, index, action, **args):
    station(game, "show_issue_warrant")
    game.perform("panel.select", {"index": index})
    game.perform(f"panel.{action}", {})
    if args:
        game.perform("panel.confirm", args)


def test_issuing_and_clearing_a_warrant():
    game = in_security("Security", "Security Guard")
    doctor_index = crew_index(game, "Doctor")
    doctor = game.station_crew[doctor_index]
    charge(game, doctor_index, "issue_warrant")
    assert panel(game)["ctx"] == {"title": "Issue Warrant", "fine": False, "name": doctor["name"],
                                  "max_length": MAX_REASON_LENGTH}
    game.perform("panel.confirm", {"reason": "   "})
    assert last_message(game) == ("Reason Required", "Enter a reason for the warrant.")
    game.perform("panel.confirm", {"reason": " Theft "})
    assert (doctor["warrant"], doctor["warrant_reason"]) == (True, "Theft")
    assert last_message(game) == ("Warrant Issued", f"Warrant issued for {doctor['name']}.\nReason: Theft")
    assert panel(game)["type"] == "issue_warrant"
    game.perform("panel.issue_warrant", {})
    assert last_message(game) == ("Warrant", f"{doctor['name']} already has an active warrant.")
    game.perform("panel.clear_warrant", {})
    assert (doctor["warrant"], doctor["warrant_reason"]) == (False, "")
    game.perform("panel.clear_warrant", {})
    assert last_message(game) == ("Warrant", f"{doctor['name']} does not have a warrant.")


def test_the_warrant_list_shows_who_is_wanted_or_fined():
    game = in_security("Security", "Security Guard")
    game.player_data.update(warrant=True, fine_amount=12.4)
    station(game, "show_issue_warrant")
    assert panel(game)["ctx"]["rows"][0] == {"index": PLAYER_CREW_INDEX,
                                             "label": "Ada (Security Guard) (YOU) [WANTED] [FINE: 12]"}


def test_a_charge_needs_someone_selected():
    game = in_security("Security", "Security Guard")
    station(game, "show_issue_warrant")
    game.perform("panel.select", {"index": 99})
    for action in ("issue_warrant", "issue_fine", "clear_warrant"):
        game.perform(f"panel.{action}", {})
    assert [m[1:3] for m in game._messages] == [("No Selection", "Select a crew member first.")] * 3
    assert panel(game)["ctx"]["selected"] is None


@pytest.mark.parametrize("amount, message", [
    ("lots", ("Invalid Amount", "Enter a valid credit amount.")),
    ("0", ("Invalid Amount", "Fine amount must be greater than zero.")),
    ("-5", ("Invalid Amount", "Fine amount must be greater than zero.")),
    ("nan", ("Invalid Amount", "Fine amount must be greater than zero.")),
    ("inf", ("Invalid Amount", "Fine amount must be greater than zero.")),
])
def test_a_fine_needs_a_positive_amount(amount, message):
    game = in_security("Security", "Security Guard")
    charge(game, crew_index(game, "Doctor"), "issue_fine", reason="Speeding", amount=amount)
    assert last_message(game) == message
    assert panel(game)["type"] == "charge"


def test_fines_add_up_and_keep_every_reason():
    game = in_security("Security", "Security Guard")
    doctor_index = crew_index(game, "Doctor")
    doctor = game.station_crew[doctor_index]
    charge(game, doctor_index, "issue_fine", reason="Speeding", amount=" 50 ")
    assert (doctor["fine_amount"], doctor["fine_reason"]) == (50, "Speeding")
    game.perform("panel.issue_fine", {})
    assert panel(game)["ctx"]["title"] == "Issue Fine"
    game.perform("panel.confirm", {"reason": "Littering", "amount": "25"})
    assert (doctor["fine_amount"], doctor["fine_reason"]) == (75, "Speeding; Littering")
    assert last_message(game) == ("Fine Issued", f"Fine issued for {doctor['name']}.\nAmount: 25 credits\n"
                                                 "Reason: Littering\nTotal owed: 75 credits")


def test_a_fine_on_top_of_one_without_a_reason_takes_the_new_reason():
    game = in_security("Security", "Security Guard")
    doctor_index = crew_index(game, "Doctor")
    doctor = game.station_crew[doctor_index]
    doctor.update(fine_amount=10, fine_reason="")
    charge(game, doctor_index, "issue_fine", reason="x" * 300, amount="5")
    assert (doctor["fine_amount"], doctor["fine_reason"]) == (15, "x" * MAX_REASON_LENGTH)


def test_a_charge_form_for_someone_who_is_gone_closes():
    game = in_security("Security", "Security Guard")
    station(game, "show_issue_warrant")
    game.open_panel("charge", crew_index=99, kind="warrant")
    game.perform("panel.confirm", {"reason": "Theft"})
    assert game._messages == []
    assert panel(game)["type"] == "issue_warrant"


def test_the_jail_lists_prisoners_and_their_time():
    game = in_security("Security", "Security Guard")
    doctor_index = crew_index(game, "Doctor")
    doctor = game.station_crew[doctor_index]
    doctor["warrant_reason"] = "Theft"
    arrest_member(doctor, game=game)
    station(game, "view_jail")
    assert panel(game)["ctx"] == {"rows": [{"index": doctor_index, "label": f"{doctor['name']} (Doctor) - 5m 0s "
                                                                            "remaining | Charge: Theft"}],
                                  "selected": None}
    game.perform("panel.select", {"index": doctor_index})
    game.perform("panel.add_time", {})
    assert last_message(game) == ("Add Time", f"Added 1 minute to {doctor['name']}'s sentence.")
    assert doctor["jail_release_at_seconds"] == 360
    game.perform("panel.pardon", {})
    assert last_message(game) == ("Pardon", f"{doctor['name']} has been pardoned and released from jail.")
    assert not is_jailed(doctor)


def test_the_jail_lists_a_jailed_player_too():
    game = in_security("Security", "Security Guard")
    arrest_member(game.player_data, game=game, is_player=True, show_message=False)
    station(game, "view_jail")
    assert panel(game)["ctx"]["rows"][0]["label"].startswith("Ada (Security Guard) (YOU) - 5m 0s remaining")


def test_only_prisoners_can_be_pardoned_or_kept_longer():
    game = in_security("Security", "Security Guard")
    station(game, "view_jail")
    game.perform("panel.select", {"index": crew_index(game, "Doctor")})
    game.perform("panel.pardon", {})
    game.perform("panel.add_time", {})
    assert [m[1:3] for m in game._messages] == [("No Selection", "Select a prisoner first.")] * 2


def test_prisoners_cannot_sign_pardons():
    game = in_security("Security", "Security Guard")
    doctor_index = crew_index(game, "Doctor")
    arrest_member(game.station_crew[doctor_index], game=game)
    game.player_data["in_jail"] = True
    station(game, "view_jail")
    game.perform("panel.select", {"index": doctor_index})
    game.perform("panel.pardon", {})
    assert last_message(game) == ("Pardon", "Prisoners can't sign pardons.")
    assert is_jailed(game.station_crew[doctor_index])
