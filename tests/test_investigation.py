from helpers import crew, fix_random, html, hurt_badly, last_message, new_game, open_station, station, threat
from space_online.game.helper_methods import antagonists, jail
from space_online.game.helper_methods.antagonists import (
    OBJECTIVES,
    THREAT_TYPES,
    new_threats,
    objective_text,
    threat_report,
    tick_threats,
)
from space_online.game.helper_methods.jail import (
    arrest_member,
    is_held,
    is_jailed,
    jailed_away_text,
    tick_jail_releases,
)
from space_online.game.helper_methods.rounds import ANTAGONIST
from space_online.game.maps.donut import SECURITY_KEY, location_from_key


def rolls(monkeypatch, pick=lambda options: options[0]):
    fix_random(monkeypatch, antagonists, pick=pick)


def threats_act(game, seconds):
    """Let every threat whose move is due make it, at the given game second."""
    game.player_data["game_clock"]["elapsed_seconds"] = seconds
    for each in game.player_data["threats"]:
        each["next_act_at"] = 0
    tick_threats(game)


def test_every_threat_is_out_to_do_something_and_a_hurtful_one_is_after_a_crew_member(monkeypatch):
    rolls(monkeypatch)
    monkeypatch.setattr(antagonists.random, "sample", lambda kinds, count: ["Vampire", "Traitor", "Space Pirate"])
    crew_list = new_game().station_crew
    vampire, traitor, pirate = new_threats(ANTAGONIST, crew_list)
    marks = [npc["name"] for npc in crew_list if npc["name"] != vampire["crew_name"]]
    assert vampire["objective"] == {"kind": "hurt", "target": marks[0], "progress": 0}
    assert traitor["objective"] == {"kind": "sabotage", "target": None, "progress": 0}
    assert pirate["objective"] == {"kind": "steal", "target": None, "progress": 0}
    assert {details["objective"] for details in THREAT_TYPES.values()} == set(OBJECTIVES)


def test_a_threat_after_one_crew_member_goes_for_them_while_it_can_reach_them(monkeypatch):
    rolls(monkeypatch)
    game = station()
    mark = crew(game, "Chef")
    alien = threat("Alien", target=mark["name"], reveal_after=9)
    game.player_data["threats"] = [alien]
    threats_act(game, 100)
    assert mark["limbs"]["head"] < 100 and alien["objective"]["progress"] == 1
    mark["in_jail"] = True
    threats_act(game, 200)
    assert (alien["objective"]["progress"], game.station_crew[0]["limbs"]["head"] < 100) == (1, True)
    mark["in_jail"] = False
    threats_act(game, 300)
    assert alien["objective"]["progress"] == 2
    assert objective_text(alien) == f"Out to put {mark['name']} out of action: achieved."


def test_only_the_moves_a_threat_is_after_count_toward_what_it_wants(monkeypatch):
    game = station(threat("Space Pirate", reveal_after=9), threat("Rogue Bot", reveal_after=9),
                   threat("Cultist", target="Nobody Aboard", reveal_after=9))
    pirate, bot, cultist = game.player_data["threats"]
    rolls(monkeypatch)
    threats_act(game, 100)
    assert (pirate["objective"]["progress"], game.player_data["credits"]) == (300, 700)
    assert (bot["objective"]["progress"], cultist["objective"]["progress"]) == (1, 0)
    rolls(monkeypatch, pick=lambda options: options[-1])
    game.player_data["station_power"]["system_levels"]["hallway_lighting"] = 5
    threats_act(game, 200)
    assert (pirate["objective"]["progress"], bot["objective"]["progress"], cultist["objective"]["progress"]) == (
        300, 2, 0)
    assert [text for _, _, text in threat_report(game.player_data)] == [
        "Out to steal 400 credits: foiled.", "Out to cripple the station's systems: foiled.",
        "Out to put Nobody Aboard out of action: foiled."]


def test_every_move_goes_down_as_an_incident_with_who_was_away_from_their_post(monkeypatch):
    rolls(monkeypatch)
    game = station(threat("Rogue Bot", reveal_after=9))
    doctor, assistants = crew(game, "Doctor"), [npc for npc in game.station_crew if npc["job"] == "Staff Assistant"]
    doctor["on_duty"] = False
    crew(game, "Engineer").update(on_duty=False, in_jail=True)
    threats_act(game, 125)
    assert game.player_data["incidents"] == [{
        "at": 125, "where": "Engineering Bay",
        "what": "Someone has sabotaged the Hallway Lighting. It needs repairing from the Engineering Panel.",
        "away": [doctor["name"], *(npc["name"] for npc in assistants)],
    }]


def test_a_hidden_crew_threat_has_to_leave_its_post_to_act_so_it_is_always_among_those_away(monkeypatch):
    rolls(monkeypatch)
    game = station()
    host = crew(game, "Bartender")
    game.player_data["threats"] = [threat("Traitor", crew_name=host["name"], reveal_after=9)]
    threats_act(game, 60)
    assert (host["on_duty"], host["npc_goal"]) == (False, "wander")
    assert host["name"] in game.player_data["incidents"][0]["away"]
    host["on_duty"] = True
    threats_act(game, 120)
    assert all(host["name"] in incident["away"] for incident in game.player_data["incidents"])


def test_a_hidden_crew_threat_does_nothing_while_its_host_cannot(monkeypatch):
    rolls(monkeypatch)
    game = station()
    host = crew(game, "Bartender")
    traitor = threat("Traitor", crew_name=host["name"], reveal_after=9)
    game.player_data["threats"] = [traitor]
    hurt_badly(host)
    threats_act(game, 60)
    assert (traitor["acts"], game.player_data["incidents"]) == (0, [])


def test_jailing_the_host_of_a_hidden_threat_ends_it_and_holds_them_for_central_command(monkeypatch):
    rolls(monkeypatch)
    game = station()
    host, chef = crew(game, "Bartender"), crew(game, "Chef")
    traitor = threat("Traitor", crew_name=host["name"], acts=1, reveal_after=9)
    game.player_data["threats"] = [traitor]
    arrest_member(chef, game=game)
    assert (traitor["fate"], is_held(chef)) == (None, False)
    arrest_member(host, game=game)
    assert traitor["fate"] == "found out and jailed before it could strike"
    assert last_message(game) == ("Threat Caught", f"{host['name']} (Bartender) was the Traitor all along. "
                                                   "They are being held for Central Command.")
    assert game.player_data["round"]["resolved_at"] == 0
    game.player_data["game_clock"]["elapsed_seconds"] = 10 ** 6
    tick_jail_releases(game)
    assert (is_jailed(host), is_jailed(chef), is_held(host)) == (True, False, True)
    assert jailed_away_text(host, 0) == f"{host['name']} is in jail, held for Central Command."
    threats_act(game, 10 ** 6)
    assert traitor["acts"] == 1


def test_jailing_the_host_of_a_threat_that_has_shown_itself_or_been_dealt_with_changes_nothing():
    game = station()
    host = crew(game, "Bartender")
    game.player_data["threats"] = [threat("Traitor", crew_name=host["name"], fate="arrested by you",
                                          reveal_after=9)]
    arrest_member(host, game=game)
    assert not is_held(host)


def test_a_held_prisoner_shows_as_held_and_cannot_be_pardoned_or_kept_longer():
    game = station(department="Security", job="Security Guard")
    host = crew(game, "Bartender")
    game.player_data["threats"] = [threat("Traitor", crew_name=host["name"], reveal_after=9)]
    arrest_member(host, game=game)
    game.player_data["location"] = location_from_key(SECURITY_KEY)
    open_station(game, "security_station", "view_jail")
    row = game.view()["panel"]["ctx"]["rows"][0]
    assert row["label"].startswith(f"{host['name']} (Bartender) - held for Central Command | Charge:")
    game.perform("panel.select", {"name": host["name"]})
    for action in ("pardon", "add_time"):
        game.perform(f"panel.{action}", {})
        assert last_message(game) == ("Held", f"{host['name']} is held for Central Command. "
                                              "Their sentence is out of your hands.")
    assert is_jailed(host)


def test_the_incident_log_lists_the_incidents_newest_first(app, monkeypatch):
    rolls(monkeypatch)
    game = station(threat("Rogue Bot", reveal_after=9), department="Security", job="Security Guard")
    game.player_data["location"] = location_from_key(SECURITY_KEY)
    open_station(game, "security_station", "show_incident_log")
    assert "No incidents have been reported this shift." in html(app, game)
    for npc in game.station_crew:
        if npc["job"] == "Staff Assistant":
            npc["in_jail"] = True
    threats_act(game, 65)
    threats_act(game, 200)
    incidents = game.view()["panel"]["ctx"]["incidents"]
    assert [(incident["time"], incident["where"], incident["away"]) for incident in incidents] == [
        ("T+3m", "Engineering Bay", "nobody"), ("T+1m", "Engineering Bay", "nobody")]
    page = html(app, game)
    assert "T+3m, Engineering Bay" in page and "Away from their posts: nobody" in page


def test_every_arrest_runs_the_arrest_hooks(monkeypatch):
    seen = []
    monkeypatch.setattr(jail, "ARREST_HOOKS", [lambda game, member: seen.append(member["name"])])
    game = new_game()
    arrest_member(game.player_data, game=game, is_player=True, show_message=False)
    assert seen == ["Ada"]
