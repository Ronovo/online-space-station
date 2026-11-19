import pytest

from helpers import (
    board_shuttle,
    crew,
    fix_random,
    go,
    labels,
    last_message,
    new_game,
    notes,
    reports,
    seated,
)
from space_online.game.helper_methods import antagonists, jail
from space_online.game.helper_methods.jail import (
    DEFAULT_SENTENCE_SECONDS,
    PETTY_CRIMES,
    add_jail_time,
    arrest_member,
    arrest_wanted_in_room,
    clear_warrant,
    in_shuttle_cell,
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
    set_warrant,
    tick_jail_releases,
)
from space_online.game.helper_methods.npc_movement import crew_aboard
from space_online.game.helper_methods.rounds import ANTAGONIST, PEACEFUL, tick_round
from space_online.game.maps.donut import BAR_KEY, MEDBAY_KEY, location_from_key
from space_online.game.special_rooms import shuttle


def dice(monkeypatch, value):
    monkeypatch.setattr(jail.random, "random", lambda: value)


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
    assert last_message(game) == ("Arrested", "Kara demands your unpaid fine of 50 credits (Littering), but you "
                                              "refuse to pay.\nYou are under arrest!")
    assert game.player_data["credits"] == 1000
    assert "Ada was jailed for refusing to pay a 50-credit fine." in notes(game)


def test_a_player_who_cannot_pay_is_jailed(monkeypatch):
    dice(monkeypatch, 0.99)
    game = new_game()
    game.player_data.update(fine_amount=5000, fine_reason="Arson")
    resolve_fine_with_guard(game.player_data, game=game, is_player=True, guard_name="Kara")
    assert last_message(game) == ("Arrested", "Kara demands your unpaid fine of 5000 credits (Arson), but you "
                                              "cannot pay.\nYou are under arrest for non-payment!")


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
    assert last_message(game) == ("Arrest", message.format(name=doctor["name"]))


def test_a_crew_member_who_pays_has_the_fine_cleared(monkeypatch):
    dice(monkeypatch, 0.99)
    game = new_game()
    doctor = crew(game, "Doctor")
    doctor.update(fine_amount=50, credits=80)
    assert resolve_fine_with_guard(doctor, game=game, guard_name="Kara") == "paid"
    assert (doctor["credits"], doctor["fine_amount"], doctor["fine_reason"]) == (30, 0, "")
    assert last_message(game) == ("Fine Paid", f"Kara collects {doctor['name']}'s unpaid fine of 50 credits.\n"
                                               "Reason: No reason on file")


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
    assert last_message(game) == ("Arrested", "You have been arrested and sent to jail for 5m 0s.")


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
    assert (doctor["on_duty"], doctor["location"]) == (True, location_from_key(MEDBAY_KEY))
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
    assert last_message(game) == ("Arrested", "A security guard found you while you were wanted. You are under "
                                              "arrest!\nCharge: Theft")


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


def answer_arrest(game, choice, label):
    button = next(b for b in choice["buttons"] if b["label"] == label)
    resolve_player_arrest_choice(game, **button["args"])


def test_arresting_a_wanted_crew_member(monkeypatch):
    game, doctor, choice = offered(monkeypatch, bribe=False, place="room")
    assert choice["message"] == (f"You scan the room and spot {doctor['name']} (Doctor).\nThey have an active warrant.\n"
                                 "Charge: Theft\n\nWhat do you do?")
    answer_arrest(game, choice, "Arrest")
    assert is_jailed(doctor)
    assert last_message(game) == ("Arrest", f"You arrest {doctor['name']} in the room and send them to jail.\n"
                                            "Charge: Theft")


def test_taking_a_bribe_clears_the_warrant(monkeypatch):
    game, doctor, choice = offered(monkeypatch, bribe=True, place="call")
    assert "make it worth your while - 20 credits" in choice["message"]
    answer_arrest(game, choice, "Let Go")
    assert (game.player_data["credits"], doctor["warrant"], is_jailed(doctor)) == (5020, False, False)
    assert notes(game)[-1] == f"Accepted a 20-credit bribe from {doctor['name']}, cleared their warrant, and let them go."


def test_letting_someone_go_without_a_bribe_keeps_the_warrant(monkeypatch):
    game, doctor, choice = offered(monkeypatch, bribe=False, place="somewhere else")
    answer_arrest(game, choice, "Let Go")
    assert doctor["warrant"]
    assert last_message(game) == ("Let Go", f"You wave {doctor['name']} on. They disappear down the hallway.")
    assert notes(game)[-1] == f"Let wanted crew member {doctor['name']} go in the hallway."


def test_a_choice_that_no_longer_applies_does_nothing(monkeypatch):
    game, doctor, choice = offered(monkeypatch, bribe=False)
    doctor["warrant"] = False
    answer_arrest(game, choice, "Arrest")
    resolve_player_arrest_choice(game, crew_name="Nobody", choice="arrest", place="hall", bribe_amount=None)
    assert not is_jailed(doctor)
    assert game._messages == []


def test_time_in_jail_settles_the_fine(monkeypatch):
    game = new_game()
    player = game.player_data
    player.update(fine_amount=5000, fine_reason="Littering")
    assert resolve_fine_with_guard(player, game=game, is_player=True) == "jailed"
    assert (player["fine_amount"], player["fine_reason"]) == (0, "")
    release_member(player, is_player=True, game=game)
    assert resolve_fine_with_guard(player, game=game, is_player=True) is None


def test_a_guard_cannot_reach_a_player_who_is_off_the_station_floor():
    game = new_game()
    player = game.player_data
    player["location"] = location_from_key(BAR_KEY)
    assert jail.player_in_room(player, BAR_KEY)
    assert not jail.player_in_room(player, "6,2")
    for field, value in (("fight", {"kind": "monster"}), ("mining", {"expedition": {"planet": 0}})):
        before = player[field]
        player[field] = value
        assert not jail.player_in_room(player, BAR_KEY)
        player[field] = before
    player["round"]["aboard"] = True
    assert not jail.player_in_room(player, BAR_KEY)


def bribe_offered(monkeypatch, game, member):
    monkeypatch.setattr(jail.random, "random", lambda: 0.0)
    monkeypatch.setattr(jail.random, "randint", lambda low, high: 20)
    assert offer_player_arrest_choice(game, member)
    return game.ui["choices"][-1]["buttons"][1]["args"]["bribe_amount"] is not None


def test_nobody_offers_a_bribe_over_a_warrant_the_player_wrote(monkeypatch):
    game = new_game("Security", "Security Guard")
    doctor = crew(game, "Doctor")
    set_warrant(doctor, "Theft", by_player=True)
    assert not bribe_offered(monkeypatch, game, doctor)
    clear_warrant(doctor)
    set_warrant(doctor, "Theft")
    assert bribe_offered(monkeypatch, game, doctor)


def test_an_antagonists_host_never_offers_a_bribe(monkeypatch):
    game = new_game("Security", "Security Guard", mode=ANTAGONIST)
    fix_random(monkeypatch, antagonists, randint=lambda low, high: low)
    game.player_data["threats"] = antagonists.new_threats(ANTAGONIST, game.station_crew)
    host = next(npc for npc in game.station_crew if npc["name"] == game.player_data["threats"][0]["crew_name"])
    set_warrant(host, PETTY_CRIMES[0])
    assert not bribe_offered(monkeypatch, game, host)


# --- The crew shuttle: Security watches the passengers and holds prisoners in the cell -------

GUARD = ("Security", "Security Guard")
CAPTAIN = ("Administration", "Captain")
HOP = ("Administration", "Head of Personnel")


def aboard(job=GUARD, mode=PEACEFUL):
    return board_shuttle(new_game(*job, mode=mode))


def scan_and_choose(game, choice):
    go(go(game, "common"), "security").perform("room.scan_passengers", {})
    message = game.ui["choices"][0]["message"]
    game.perform("game.choose", {"id": game.ui["choices"][0]["id"], "index": 0 if choice == "arrest" else 1})
    return message


def hidden_threat(host):
    return {"type": "Changeling", "crew_name": host["name"], "name": f"{host['name']} the Changeling", "acts": 1,
            "revealed": False, "fate": None}


def test_scanning_the_passengers_arrests_the_wanted_into_the_shuttles_cell(monkeypatch):
    dice(monkeypatch, 0.99)
    game = aboard()
    (chef,) = seated(game, "Chef")
    set_warrant(chef, "Brawling")
    message = scan_and_choose(game, "arrest")
    assert message == (f"You scan the passengers and spot {chef['name']} (Chef).\nThey have an active warrant.\n"
                       "Charge: Brawling\n\nWhat do you do?")
    assert last_message(game) == ("Arrest", f"You arrest {chef['name']} and lock them in the shuttle's cell.\n"
                                            "Charge: Brawling")
    assert (is_jailed(chef), in_shuttle_cell(chef), chef in crew_aboard(game.station_crew)) == (True, True, True)
    assert labels(game)[1:4] == ["The Cell", f"{chef['name']} (Chef): Brawling", "Scan the Passengers"]


def test_letting_a_passenger_go_leaves_them_in_their_seat(monkeypatch):
    dice(monkeypatch, 0.99)
    game = aboard()
    (chef,) = seated(game, "Chef")
    set_warrant(chef, "Brawling")
    scan_and_choose(game, "let_go")
    assert last_message(game) == ("Let Go", f"You look the other way. {chef['name']} stays in their seat.")
    assert not is_jailed(chef)


def test_a_scan_that_finds_nobody_says_so():
    game = go(aboard(CAPTAIN), "security")
    assert labels(game)[1:3] == ["The Cell", "The cell is empty."]
    game.perform("room.scan_passengers", {})
    assert last_message(game) == ("Scan the Passengers", "The scan turns up nobody to arrest.")


def test_a_passenger_who_cannot_pay_a_fine_goes_to_the_shuttles_cell(monkeypatch):
    dice(monkeypatch, 0.99)
    game = go(aboard(), "security")
    (chef,) = seated(game, "Chef")
    chef.update(fine_amount=50, fine_reason="Littering", credits=0)
    game.perform("room.scan_passengers", {})
    assert (in_shuttle_cell(chef), last_message(game)[1].endswith("arrests them for non-payment.")) == (True, True)


def test_a_prisoner_in_the_shuttles_cell_is_not_released_when_their_time_runs_out():
    game = aboard()
    celled, jailed = seated(game, "Chef")[0], crew(game, "Doctor")
    for prisoner in (celled, jailed):
        prisoner.update(in_jail=True, jail_release_at_seconds=0)
    jailed["location"] = security_room_location()
    tick_jail_releases(game)
    assert (is_jailed(celled), is_jailed(jailed)) == (True, False)


def test_the_stations_prisoners_ride_in_the_shuttles_cell():
    game = aboard()
    doctor = crew(game, "Doctor")
    doctor.update(in_jail=True, jail_release_at_seconds=10 ** 6, location=security_room_location(),
                  warrant_reason="Smuggling")
    game.perform("room.strap", {})
    game.player_data["game_clock"]["elapsed_seconds"] = game.player_data["round"]["shuttle"]["until"]
    tick_round(game)
    game.perform("room.strap", {})
    assert f"{doctor['name']} (Doctor): Smuggling" in labels(go(game, "security"))


@pytest.mark.parametrize("job, watches", [(GUARD, True), (CAPTAIN, True), (HOP, False)])
def test_only_security_and_the_captain_watch_the_passengers_and_issue_warrants(job, watches):
    game = go(aboard(job), "command")
    (chef,) = seated(game, "Staff Assistant")
    shown = labels(game)
    assert ("Watch the Passengers" in shown, "Issue a Warrant" in shown) == (watches, watches)
    if not watches:
        messages = len(game._messages)
        for action, args in (("watch_passengers", {}), ("choose_suspect", {}),
                             ("issue_warrant", {"crew_name": chef["name"]})):
            game.perform(f"room.{action}", args)
        assert (len(game._messages), game.ui["room_mode"], chef["warrant"]) == (messages, "menu", False)


def watch(game):
    game.perform("room.watch_passengers", {})
    return last_message(game)


def test_a_tell_only_ever_points_at_a_real_host(monkeypatch):
    game = go(aboard(mode=ANTAGONIST), "command")
    chef, doctor = seated(game, "Chef", "Doctor")
    monkeypatch.setattr(shuttle.random, "choice", lambda options: options[0])

    monkeypatch.setattr(shuttle.random, "random", lambda: 0.0)
    game.player_data["threats"] = []
    assert watch(game) == ("Watch the Passengers", shuttle.ODD_LINES[0].format(name=doctor["name"]))
    game.player_data["threats"] = [hidden_threat(chef)]
    assert watch(game) == ("Watch the Passengers", shuttle.TELLS[0].format(name=chef["name"]))

    monkeypatch.setattr(shuttle.random, "random", lambda: shuttle.TELL_CHANCE)
    assert watch(game) == ("Watch the Passengers", shuttle.INNOCENT_LINES[0].format(name=doctor["name"]))
    doctor["location"] = security_room_location()
    assert watch(game) == ("Watch the Passengers", shuttle.INNOCENT_LINES[0].format(name=chef["name"]))


def test_watching_needs_someone_in_the_seats_and_the_shuttle_docked():
    game = go(aboard(), "command")
    assert watch(game) == ("Watch the Passengers", "The seats are empty.")
    seated(game, "Chef")
    game.player_data["round"]["shuttle"]["state"] = "transit"
    messages = len(game._messages)
    game.perform("room.watch_passengers", {})
    assert ("Watch the Passengers" not in labels(game), len(game._messages)) == (True, messages)


def warrant_on(game, npc):
    game.perform("room.choose_suspect", {})
    assert f"{npc['name']} ({npc['job']})" in labels(game)
    game.perform("room.issue_warrant", {"crew_name": npc["name"]})


def test_a_warrant_on_the_host_and_a_scan_end_the_threat_before_the_shuttle_leaves(monkeypatch):
    dice(monkeypatch, 0.99)
    game = go(aboard(mode=ANTAGONIST), "command")
    (chef,) = seated(game, "Chef")
    game.player_data["threats"] = [hidden_threat(chef)]
    warrant_on(game, chef)
    assert (chef["warrant_reason"], chef["warrant_by_player"], game.ui["room_mode"]) == (
        "Suspicious behaviour aboard the shuttle", True, "menu")
    assert last_message(game) == ("Warrant Issued", f"Warrant issued for {chef['name']}.\n"
                                                    "Reason: Suspicious behaviour aboard the shuttle")
    scan_and_choose(game, "arrest")
    assert (game.player_data["threats"][0]["fate"], chef["held"]) == ("found out and jailed before it could strike",
                                                                       True)


def test_a_warrant_on_an_innocent_jails_them_and_changes_nothing_else(monkeypatch):
    dice(monkeypatch, 0.99)
    game = go(aboard(mode=ANTAGONIST), "command")
    chef, doctor = seated(game, "Chef", "Doctor")
    game.player_data["threats"] = [hidden_threat(chef)]
    credits = game.player_data["credits"]
    warrant_on(game, doctor)
    scan_and_choose(game, "arrest")
    assert (in_shuttle_cell(doctor), doctor.get("held"), game.player_data["threats"][0]["fate"]) == (True, None, None)
    assert game.player_data["credits"] == credits


def test_the_warrant_list_leaves_out_the_wanted_and_can_be_cancelled():
    game = go(aboard(), "command")
    game.perform("room.choose_suspect", {})
    assert labels(game)[-3:] == ["Nobody in the seats to put a warrant on.", "Cancel", "Back to the Common Area"]
    game.perform("room.choose_suspect", {})
    assert game.ui["room_mode"] == "menu"

    chef, doctor = seated(game, "Chef", "Doctor")
    set_warrant(chef, "Brawling")
    game.perform("room.choose_suspect", {})
    assert f"{chef['name']} (Chef)" not in labels(game) and f"{doctor['name']} (Doctor)" in labels(game)
    for name in (chef["name"], "Nobody At All"):
        game.perform("room.issue_warrant", {"crew_name": name})
    assert (chef["warrant_reason"], game.ui["room_mode"]) == ("Brawling", "warrant")
