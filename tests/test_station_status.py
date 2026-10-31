import pytest

from helpers import new_game
from space_online.game.helper_methods.station_status import collect_station_status
from space_online.game.maps.donut import BAR_KEY, MEDBAY_KEY


def status(game):
    return collect_station_status(game.player_data, game.station_crew)


def alert_texts(game):
    return [(alert["text"], alert["severity"]) for alert in status(game)["alerts"]]


def test_a_new_station_reads_nominal_apart_from_its_low_battery():
    game = new_game()
    game.player_data["station_power"]["battery_level"] = 80
    report = status(game)
    assert (report["overall"], report["overall_color"], report["alerts"]) == ("NOMINAL", "#00FF00", [])
    assert report["power"]["oxygen_threat"] == "safe"
    assert [s["status"] for s in report["power"]["systems"]] == ["Online"] * 4
    crew = report["crew"]
    assert (crew["complement"], crew["healthy"], crew["away"]) == (len(game.station_crew) + 1, crew["complement"], 0)
    assert report["facilities"]["botany_total"] > 0
    assert report["elapsed_display"] == "0s"


def test_a_low_battery_is_a_caution():
    game = new_game()
    game.player_data["station_power"]["battery_level"] = 30
    assert status(game)["overall"] == "CAUTION"
    assert alert_texts(game) == [("Battery low (30%)", "caution")]


def test_life_support_off_is_an_oxygen_emergency():
    game = new_game()
    power = game.player_data["station_power"]
    power.update(battery_level=5)
    power["system_levels"]["life_support"] = 0
    game.player_data["damage"]["oxygen"] = 40
    game.player_data["announcements"] = [{"text": "Evacuate!", "type": "emergency"},
                                         {"text": "Life Support offline: oxygen emergency active", "type": "emergency"},
                                         {"text": "Party in the bar", "type": "social"}]
    report = status(game)
    assert report["overall"] == "CRITICAL"
    assert report["power"]["systems"][0] == {"name": "Life Support", "level": 0, "status": "Offline",
                                             "status_color": "#FF0000"}
    assert alert_texts(game) == [
        ("Life Support offline: oxygen emergency active", "critical"),
        ("Battery critical (5%)", "critical"),
        ("Oxygen stress affecting 1 crew", "critical"),
        ("Evacuate!", "critical"),
    ]


def test_degraded_life_support_and_injuries_are_cautions():
    game = new_game()
    game.player_data["station_power"]["battery_level"] = 80
    game.player_data["station_power"]["system_levels"]["life_support"] = 3
    game.station_crew[0]["limbs"].update(head=0, chest=0)
    game.station_crew[1]["damage"]["oxygen"] = 30
    assert status(game)["overall"] == "CAUTION"
    assert alert_texts(game) == [("Life Support degraded (Lv 3): oxygen damage active", "caution"),
                                 ("1 crew injured", "caution"),
                                 ("Oxygen stress affecting 1 crew", "caution")]


def test_critical_crew_outrank_injured_crew():
    game = new_game()
    game.player_data["station_power"]["battery_level"] = 80
    for limb in game.station_crew[0]["limbs"]:
        game.station_crew[0]["limbs"][limb] = 10
    game.station_crew[1]["limbs"].update(head=0, chest=0)
    report = status(game)
    assert (report["overall"], report["crew"]["critical"], report["crew"]["injured"]) == ("CRITICAL", 1, 1)
    assert alert_texts(game) == [("1 crew in critical condition", "critical")]


def test_security_matters_are_listed():
    game = new_game()
    game.player_data["station_power"]["battery_level"] = 80
    captain, hop, guard = game.station_crew[:3]
    captain.update(warrant=True, warrant_reason="")
    hop.update(in_jail=True, fine_reason="Unpaid")
    guard.update(in_jail=True)
    game.player_data.update(fine_amount=20, fine_reason="")
    report = status(game)
    assert report["security"]["details"] == [
        {"name": captain["name"], "reason": "unknown", "kind": "wanted"},
        {"name": hop["name"], "reason": "Unpaid", "kind": "jailed"},
        {"name": guard["name"], "reason": "detained", "kind": "jailed"},
        {"name": "Ada", "reason": "unpaid fine (20 cr)", "kind": "fine"},
    ]
    assert (report["crew"]["on_duty"], report["crew"]["away"]) == (report["crew"]["complement"] - 2, 2)
    assert ("1 wanted crew on station", "caution") in alert_texts(game)
    assert ("2 crew currently jailed", "caution") in alert_texts(game)
    assert report["overall"] == "CAUTION"


def test_a_fine_reads_in_whole_credits():
    game = new_game()
    game.player_data.update(fine_amount=50.0, fine_reason="Speeding")
    assert status(game)["security"]["details"] == [{"name": "Ada", "reason": "Speeding (50 cr)", "kind": "fine"}]


def test_crew_away_from_their_post_count_as_away():
    game = new_game()
    game.station_crew[0]["on_duty"] = False
    assert status(game)["crew"]["away"] == 1


def test_locked_rooms_and_access_requests_are_cautions():
    game = new_game()
    game.player_data["station_power"]["battery_level"] = 80
    game.ship_map[BAR_KEY]["locked"] = True
    game.ship_map[MEDBAY_KEY]["locked"] = True
    game.player_data["access_request"] = {"requester_name": "", "requested_job": "Doctor"}
    assert alert_texts(game) == [("Locked rooms: MedBay, Bar", "caution"),
                                 ("Pending access request: Unknown → Doctor", "caution")]
    assert status(game)["facilities"]["locked_rooms"] == ["MedBay", "Bar"]


@pytest.mark.parametrize("access_request", [None, {"requested_job": None}])
def test_an_empty_access_request_is_no_alert(access_request):
    game = new_game()
    game.player_data["station_power"]["battery_level"] = 80
    game.player_data["access_request"] = access_request
    assert alert_texts(game) == []


def test_the_status_panel_opens_on_the_same_report():
    game = new_game()
    game.open_panel("station_status")
    assert game.view()["panel"]["ctx"]["overall"] == status(game)["overall"]
