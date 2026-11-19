import pytest

from helpers import buttons, crew, duty_id, give_duty, in_room, labels, last_message, notes, open_station, panel
from space_online.game.helper_methods import jail
from space_online.game.helper_methods.jail import MAX_FINE, arrest_member, is_jailed, security_hallway_location
from space_online.game.special_rooms.security import MAX_REASON_LENGTH
from space_online.game.maps.donut import SECURITY_KEY


def in_security(department="Civilian", job="Staff Assistant"):
    return in_room(SECURITY_KEY, department, job)


def security_console(game, panel_action):
    return open_station(game, "security_station", panel_action)


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
    guard = crew(game, "Security Guard")
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
    assert labels(game) == ["Enter Security Station", "Lock/Unlock Door", "Room Options"]
    game.perform("room.open_station", {"mode": "security_station"})
    assert labels(game) == ["View Crew Manifest", "Issue Warrant/Fine", "View Jail", "Incident Log", "Armory",
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
    doctor = crew(game, "Doctor")
    doctor.update(warrant=True, in_jail=True)
    security_console(game, "view_crew_manifest")
    departments = {d["name"]: d["members"] for d in panel(game)["ctx"]["departments"]}
    assert departments["SECURITY"] == [{"text": "- Security Guard: Ada (YOU)", "is_player": True}]
    assert departments["MEDICAL"] == [{"text": f"- Doctor: {doctor['name']} [WANTED] [JAILED]", "is_player": False}]
    assert [m["text"].split(":")[0] for m in departments["CIVILIAN"]] == [
        "- Staff Assistant", "- Staff Assistant", "- Bartender", "- Chef", "- Botanist"]


def charge(game, name, action, **args):
    security_console(game, "show_issue_warrant")
    game.perform("panel.select", {"name": name})
    game.perform(f"panel.{action}", {})
    if args:
        game.perform("panel.confirm", args)


def test_issuing_and_clearing_a_warrant():
    game = in_security("Security", "Security Guard")
    doctor = crew(game, "Doctor")
    charge(game, doctor["name"], "issue_warrant")
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
    security_console(game, "show_issue_warrant")
    assert panel(game)["ctx"]["rows"][0] == {"name": "Ada",
                                             "label": "Ada (Security Guard) (YOU) [WANTED] [FINE: 12]"}


def test_a_charge_needs_someone_selected():
    game = in_security("Security", "Security Guard")
    security_console(game, "show_issue_warrant")
    game.perform("panel.select", {"name": "Nobody"})
    for action in ("issue_warrant", "issue_fine", "clear_warrant"):
        game.perform(f"panel.{action}", {})
    assert [m[:2] for m in game._messages] == [("No Selection", "Select a crew member first.")] * 3
    assert panel(game)["ctx"]["selected"] is None


@pytest.mark.parametrize("amount", ["lots", "0", "-5", "nan", "inf", "0.001", "1e300", "2.5", "1001", ""])
def test_a_fine_is_a_whole_number_of_credits_up_to_the_cap(amount):
    game = in_security("Security", "Security Guard")
    doctor = crew(game, "Doctor")
    charge(game, doctor["name"], "issue_fine", reason="Speeding", amount=amount)
    assert last_message(game) == ("Invalid Amount", f"Enter a whole number of credits from 1 to {MAX_FINE}.")
    assert (panel(game)["type"], doctor["fine_amount"]) == ("charge", 0)


@pytest.mark.parametrize("amount", [1, MAX_FINE])
def test_a_fine_from_one_credit_to_the_cap_is_issued(amount):
    game = in_security("Security", "Security Guard")
    doctor = crew(game, "Doctor")
    charge(game, doctor["name"], "issue_fine", reason="Speeding", amount=str(amount))
    assert doctor["fine_amount"] == amount


def test_fines_never_add_up_past_the_cap():
    game = in_security("Security", "Security Guard")
    doctor = crew(game, "Doctor")
    charge(game, doctor["name"], "issue_fine", reason="Speeding", amount=str(MAX_FINE - 10))
    game.perform("panel.issue_fine", {})
    game.perform("panel.confirm", {"reason": "Littering", "amount": "50"})
    assert doctor["fine_amount"] == MAX_FINE


def test_fines_add_up_and_keep_every_reason():
    game = in_security("Security", "Security Guard")
    doctor = crew(game, "Doctor")
    charge(game, doctor["name"], "issue_fine", reason="Speeding", amount=" 50 ")
    assert (doctor["fine_amount"], doctor["fine_reason"]) == (50, "Speeding")
    game.perform("panel.issue_fine", {})
    assert panel(game)["ctx"]["title"] == "Issue Fine"
    game.perform("panel.confirm", {"reason": "Littering", "amount": "25"})
    assert (doctor["fine_amount"], doctor["fine_reason"]) == (75, "Speeding; Littering")
    assert last_message(game) == ("Fine Issued", f"Fine issued for {doctor['name']}.\nAmount: 25 credits\n"
                                                 "Reason: Littering\nTotal owed: 75 credits")


def test_a_fine_on_top_of_one_without_a_reason_takes_the_new_reason():
    game = in_security("Security", "Security Guard")
    doctor = crew(game, "Doctor")
    doctor.update(fine_amount=10, fine_reason="")
    charge(game, doctor["name"], "issue_fine", reason="x" * 300, amount="5")
    assert (doctor["fine_amount"], doctor["fine_reason"]) == (15, "x" * MAX_REASON_LENGTH)


def test_a_charge_form_for_someone_who_is_gone_closes():
    game = in_security("Security", "Security Guard")
    security_console(game, "show_issue_warrant")
    game.open_panel("charge", crew_name="Nobody", kind="warrant")
    game.perform("panel.confirm", {"reason": "Theft"})
    assert game._messages == []
    assert panel(game)["type"] == "issue_warrant"


def test_the_jail_lists_prisoners_and_their_time():
    game = in_security("Security", "Security Guard")
    doctor = crew(game, "Doctor")
    doctor["warrant_reason"] = "Theft"
    arrest_member(doctor, game=game)
    security_console(game, "view_jail")
    assert panel(game)["ctx"] == {"rows": [{"name": doctor["name"], "label": f"{doctor['name']} (Doctor) - 5m 0s "
                                                                               "remaining | Charge: Theft"}],
                                  "selected": None}
    game.perform("panel.select", {"name": doctor["name"]})
    game.perform("panel.add_time", {})
    assert last_message(game) == ("Add Time", f"Added 1 minute to {doctor['name']}'s sentence.")
    assert doctor["jail_release_at_seconds"] == 360
    game.perform("panel.pardon", {})
    assert last_message(game) == ("Pardon", f"{doctor['name']} has been pardoned and released from jail.")
    assert not is_jailed(doctor)


def test_the_jail_lists_a_jailed_player_too():
    game = in_security("Security", "Security Guard")
    arrest_member(game.player_data, game=game, is_player=True, show_message=False)
    security_console(game, "view_jail")
    assert panel(game)["ctx"]["rows"][0]["label"].startswith("Ada (Security Guard) (YOU) - 5m 0s remaining")


def test_only_prisoners_can_be_pardoned_or_kept_longer():
    game = in_security("Security", "Security Guard")
    security_console(game, "view_jail")
    game.perform("panel.select", {"name": crew(game, "Doctor")["name"]})
    game.perform("panel.pardon", {})
    game.perform("panel.add_time", {})
    assert [m[:2] for m in game._messages] == [("No Selection", "Select a prisoner first.")] * 2


def test_prisoners_cannot_sign_pardons():
    game = in_security("Security", "Security Guard")
    doctor = crew(game, "Doctor")
    arrest_member(doctor, game=game)
    game.player_data["in_jail"] = True
    security_console(game, "view_jail")
    game.perform("panel.select", {"name": doctor["name"]})
    game.perform("panel.pardon", {})
    assert last_message(game) == ("Pardon", "Prisoners can't sign pardons.")
    assert is_jailed(doctor)


def paperwork(game):
    give_duty(game, kind="help", giver="Security Guard", room=SECURITY_KEY, item=None, label="file paperwork",
              reward=40, summary="Help out")
    return game


HELP = ("Help the Security Guard file paperwork", "room.complete_duty")


def test_helping_out_on_a_duty_pays_the_reward():
    game = paperwork(in_security())
    assert buttons(game)[0] == HELP
    game.perform("room.complete_duty", {"duty_id": duty_id(game)})
    assert (game.player_data["credits"], game.player_data["duties"]) == (1040, [])
    assert last_message(game) == ("Duty Done", "You file paperwork. The Security Guard pays you 40 credits.")
    assert notes(game)[-1] == "Helped the Security Guard file paperwork for 40 credits."


def test_a_duty_shows_under_room_options_for_whoever_runs_the_room():
    game = paperwork(in_security("Administration", "Captain"))
    assert HELP not in buttons(game)
    game.perform("room.set_mode", {"mode": "options"})
    assert buttons(game)[0] == HELP


def test_a_player_cannot_put_out_a_warrant_for_themself():
    game = in_security("Security", "Security Guard")
    charge(game, "Ada", "issue_warrant", reason="Testing the system")
    assert last_message(game) == ("Warrant Refused", "You can't issue a warrant for yourself.")
    assert (game.player_data["warrant"], panel(game)["type"]) == (False, "charge")


def test_a_warrant_the_player_writes_is_marked_as_theirs():
    game = in_security("Security", "Security Guard")
    doctor = crew(game, "Doctor")
    charge(game, doctor["name"], "issue_warrant", reason="Theft")
    assert (doctor["warrant"], doctor["warrant_by_player"]) == (True, True)
