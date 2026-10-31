import pytest

from helpers import new_game, reports
from space_online.game.helper_methods import jail
from space_online.game.helper_methods.jail import (
    DEFAULT_SENTENCE_SECONDS,
    add_jail_time,
    arrest_member,
    arrest_wanted_in_room,
    is_jailed,
    jail_seconds_remaining,
    jailed_away_text,
    members_in_room,
    offer_player_arrest_choice,
    release_member,
    resolve_fine_with_guard,
    resolve_player_arrest_choice,
    security_hallway_location,
    security_room_location,
    tick_jail_releases,
)
from space_online.game.helper_methods.npc_movement import location_for_post
from space_online.game.maps.donut import BAR_KEY, location_from_key


def crew(game, job):
    return next(npc for npc in game.station_crew if npc["job"] == job)


def dice(monkeypatch, value):
    monkeypatch.setattr(jail.random, "random", lambda: value)


def last_message(game):
    return game._messages[-1][2]


def notes(game):
    return [note["text"] for note in game.player_data["notes"]]


def test_a_jailed_crew_member_reads_as_away():
    doctor = crew(new_game(), "Doctor")
    doctor.update(in_jail=True, jail_release_at_seconds=125)
    assert jailed_away_text(doctor, 5) == f"{doctor['name']} is in jail and will be released in 2m 0s."


def test_there_is_nothing_to_collect_without_a_fine_or_from_a_prisoner():
    game = new_game()
    doctor = crew(game, "Doctor")
    assert resolve_fine_with_guard(doctor, game=game) is None
    doctor.update(fine_amount=10, in_jail=True)
    assert resolve_fine_with_guard(doctor, game=game) is None


def test_a_player_who_refuses_a_fine_is_jailed(monkeypatch):
    dice(monkeypatch, 0.0)
    game = new_game()
    game.player_data.update(fine_amount=50, fine_reason="Littering")
    assert resolve_fine_with_guard(game.player_data, game=game, is_player=True, guard_name="Kara") == "jailed"
    assert is_jailed(game.player_data)
    assert last_message(game) == ("Kara demands your unpaid fine of 50 credits (Littering), but you refuse to pay.\n"
                                  "You are under arrest!")
    assert game.player_data["credits"] == 1000
    assert "Ada was jailed for refusing to pay a 50-credit fine." in notes(game)


def test_a_player_who_cannot_pay_is_jailed(monkeypatch):
    dice(monkeypatch, 0.99)
    game = new_game()
    game.player_data.update(fine_amount=5000, fine_reason="Arson")
    resolve_fine_with_guard(game.player_data, game=game, is_player=True, guard_name="Kara")
    assert last_message(game) == ("Kara demands your unpaid fine of 5000 credits (Arson), but you cannot pay.\n"
                                  "You are under arrest for non-payment!")


@pytest.mark.parametrize("roll, credits, message", [
    (0.0, 100, "{name} refuses to pay their 50-credit fine (Littering), even though they have the credits.\n"
               "Kara arrests them."),
    (0.99, 10, "{name} cannot pay their 50-credit fine (Littering).\nKara arrests them for non-payment."),
])
def test_a_crew_member_who_refuses_or_cannot_pay_is_jailed(monkeypatch, roll, credits, message):
    dice(monkeypatch, roll)
    game = new_game()
    doctor = crew(game, "Doctor")
    doctor.update(fine_amount=50, fine_reason="Littering", credits=credits)
    assert resolve_fine_with_guard(doctor, game=game, guard_name="Kara") == "jailed"
    assert is_jailed(doctor)
    assert reports(game) == ["Arrest"]
    assert last_message(game) == message.format(name=doctor["name"])


def test_a_crew_member_who_pays_has_the_fine_cleared(monkeypatch):
    dice(monkeypatch, 0.99)
    game = new_game()
    doctor = crew(game, "Doctor")
    doctor.update(fine_amount=50, credits=80)
    assert resolve_fine_with_guard(doctor, game=game, guard_name="Kara") == "paid"
    assert (doctor["credits"], doctor["fine_amount"], doctor["fine_reason"]) == (30, 0, "")
    assert last_message(game) == f"Kara collects {doctor['name']}'s unpaid fine of 50 credits.\nReason: No reason on file"


def test_time_left_in_jail():
    member = {"in_jail": False, "jail_release_at_seconds": 500}
    assert jail_seconds_remaining(member, 100) == 0
    member["in_jail"] = True
    assert jail_seconds_remaining(member, 100.5) == 399
    assert jail_seconds_remaining(member, 900) == 0
    member["jail_release_at_seconds"] = None
    assert jail_seconds_remaining(member, 100) == 0


def test_members_in_a_room_leave_out_prisoners_and_the_one_asking():
    game = new_game()
    bartender = crew(game, "Bartender")
    doctor = crew(game, "Doctor")
    engineer = crew(game, "Engineer")
    doctor["location"] = location_from_key(BAR_KEY)
    engineer.update(location=location_from_key(BAR_KEY), in_jail=True)
    assert {npc["name"] for npc in members_in_room(game.station_crew, BAR_KEY)} == {bartender["name"], doctor["name"]}
    assert members_in_room(game.station_crew, BAR_KEY, exclude=bartender) == [doctor]


def test_an_arrest_takes_a_posted_crew_member_off_duty_once():
    game = new_game()
    doctor = crew(game, "Doctor")
    assert arrest_member(doctor, reason="Caught.", game=game, elapsed_seconds=10)
    assert (doctor["on_duty"], doctor["location"], doctor["jail_release_at_seconds"]) == (
        False, security_room_location(), 10 + DEFAULT_SENTENCE_SECONDS)
    assert reports(game) == ["Arrest"]
    assert not arrest_member(doctor, reason="Again.", game=game)
    assert reports(game) == ["Arrest"]


def test_an_arrest_without_a_reason_is_quiet_for_crew_and_explained_to_the_player():
    game = new_game()
    arrest_member(crew(game, "Doctor"), game=game)
    assert game._messages == []
    arrest_member(game.player_data, game=game, is_player=True)
    assert last_message(game) == "You have been arrested and sent to jail for 5m 0s."


def test_release_puts_each_prisoner_back(monkeypatch):
    game = new_game()
    doctor = crew(game, "Doctor")
    assistant = crew(game, "Staff Assistant")
    assert not release_member(doctor, game=game)
    for member in (doctor, assistant, game.player_data):
        member.update(warrant=True, warrant_reason="Theft")
        arrest_member(member, game=game, is_player=member is game.player_data)
        release_member(member, game=game, is_player=member is game.player_data)
        assert (member["in_jail"], member["warrant"], member["warrant_reason"]) == (False, False, "")
    assert (doctor["on_duty"], doctor["location"]) == (True, location_for_post("Doctor"))
    assert assistant["location"] == security_hallway_location()
    assert game.player_data["location"] == security_hallway_location()
    assert reports(game)[-1] == "Released"


def test_extra_time_adds_to_what_is_left():
    member = {"in_jail": False, "jail_release_at_seconds": None}
    assert not add_jail_time(member, 100)
    member.update(in_jail=True, jail_release_at_seconds=200)
    assert add_jail_time(member, 100)
    assert member["jail_release_at_seconds"] == 260


def test_finished_sentences_end_on_the_tick():
    game = new_game()
    doctor = crew(game, "Doctor")
    engineer = crew(game, "Engineer")
    arrest_member(doctor, game=game)
    arrest_member(engineer, game=game, elapsed_seconds=1000)
    arrest_member(game.player_data, game=game, is_player=True, show_message=False)
    game.player_data["game_clock"]["elapsed_seconds"] = DEFAULT_SENTENCE_SECONDS
    tick_jail_releases(game)
    assert (is_jailed(doctor), is_jailed(engineer), is_jailed(game.player_data)) == (False, True, False)
    assert reports(game) == ["Released"]


def test_a_guard_entering_a_room_arrests_the_wanted_there_but_not_themself():
    game = new_game()
    bartender = crew(game, "Bartender")
    guard = crew(game, "Security Guard")
    doctor = crew(game, "Doctor")
    engineer = crew(game, "Engineer")
    for member in (guard, doctor, engineer, game.player_data):
        member["location"] = location_from_key(BAR_KEY)
    for member in (guard, doctor, game.player_data):
        member.update(warrant=True, warrant_reason="Theft")
    arrest_wanted_in_room(BAR_KEY, game, guard, 0)
    assert [is_jailed(m) for m in (bartender, guard, doctor, engineer, game.player_data)] == [
        False, False, True, False, True]
    assert last_message(game) == "A security guard found you while you were wanted. You are under arrest!\nCharge: Theft"


def test_a_player_stays_free_when_a_guard_checks_another_room():
    game = new_game()
    game.player_data.update(warrant=True)
    arrest_wanted_in_room(BAR_KEY, game, crew(game, "Security Guard"), 0)
    assert not is_jailed(game.player_data)


def test_only_security_is_offered_an_arrest_of_someone_wanted():
    game = new_game()
    doctor = crew(game, "Doctor")
    doctor["warrant"] = True
    assert not offer_player_arrest_choice(game, doctor)
    security = new_game("Security", "Security Guard")
    assert not offer_player_arrest_choice(security, crew(security, "Doctor"))


def offered(monkeypatch, bribe, place="hall"):
    game = new_game("Security", "Security Guard")
    rolls = iter([0.0 if bribe else 0.99])
    monkeypatch.setattr(jail.random, "random", lambda: next(rolls))
    monkeypatch.setattr(jail.random, "randint", lambda low, high: 20)
    doctor = crew(game, "Doctor")
    doctor.update(warrant=True, warrant_reason="Theft")
    assert offer_player_arrest_choice(game, doctor, place=place)
    return game, doctor, game.ui["choices"][0]


def choose(game, choice, label):
    button = next(b for b in choice["buttons"] if b["label"] == label)
    resolve_player_arrest_choice(game, **button["args"])


def test_arresting_a_wanted_crew_member(monkeypatch):
    game, doctor, choice = offered(monkeypatch, bribe=False, place="room")
    assert choice["message"] == (f"You scan the room and spot {doctor['name']} (Doctor).\nThey have an active warrant.\n"
                                 "Charge: Theft\n\nWhat do you do?")
    choose(game, choice, "Arrest")
    assert is_jailed(doctor)
    assert last_message(game) == f"You arrest {doctor['name']} in the room and send them to jail.\nCharge: Theft"


def test_taking_a_bribe_clears_the_warrant(monkeypatch):
    game, doctor, choice = offered(monkeypatch, bribe=True, place="call")
    assert "make it worth your while - 20 credits" in choice["message"]
    choose(game, choice, "Let Go")
    assert (game.player_data["credits"], doctor["warrant"], is_jailed(doctor)) == (5020, False, False)
    assert notes(game)[-1] == f"Accepted a 20-credit bribe from {doctor['name']}, cleared their warrant, and let them go."


def test_letting_someone_go_without_a_bribe_keeps_the_warrant(monkeypatch):
    game, doctor, choice = offered(monkeypatch, bribe=False, place="somewhere else")
    choose(game, choice, "Let Go")
    assert doctor["warrant"]
    assert last_message(game) == f"You wave {doctor['name']} on. They disappear down the hallway."
    assert notes(game)[-1] == f"Let wanted crew member {doctor['name']} go in the hallway."


def test_a_choice_that_no_longer_applies_does_nothing(monkeypatch):
    game, doctor, choice = offered(monkeypatch, bribe=False)
    doctor["warrant"] = False
    choose(game, choice, "Arrest")
    resolve_player_arrest_choice(game, crew_index=99, choice="arrest", place="hall", bribe_amount=None)
    assert not is_jailed(doctor)
    assert game._messages == []
