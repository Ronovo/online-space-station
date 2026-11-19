import pytest

from helpers import fill_air, give_duty, new_game, stale_air
from space_online.game.helper_methods.power_constants import fault_system
from space_online.game.helper_methods.station_status import collect_station_status
from space_online.game.maps.donut import BAR_KEY, MEDBAY_KEY


def status(game):
    return collect_station_status(game.player_data, game.station_crew)


def steady(game):
    game.player_data["station_power"]["battery_level"] = 80
    return game


def alert_texts(game):
    return [(alert["text"], alert["severity"]) for alert in status(game)["alerts"]]


def test_a_new_station_reads_nominal_apart_from_its_low_battery():
    game = steady(new_game())
    report = status(game)
    assert (report["overall"], report["overall_color"], report["alerts"]) == ("NOMINAL", "#00FF00", [])
    assert report["power"]["oxygen_threat"] == "safe"
    assert [s["status"] for s in report["power"]["systems"]] == ["Online"] * 4
    crew = report["crew"]
    assert (crew["complement"], crew["healthy"], crew["away"]) == (len(game.station_crew) + 1, crew["complement"], 0)
    assert report["facilities"]["botany_total"] == 16
    assert report["elapsed_display"] == "0s"


def test_a_low_battery_is_a_caution():
    game = new_game()
    game.player_data["station_power"]["battery_level"] = 30
    assert status(game)["overall"] == "CAUTION"
    assert alert_texts(game) == [("Battery low (30%)", "caution")]


def test_unbreathable_air_is_an_emergency():
    game = stale_air(new_game())
    power = game.player_data["station_power"]
    power.update(battery_level=5)
    power["system_levels"]["life_support"] = 0
    game.player_data["damage"]["oxygen"] = 40
    game.player_data["announcements"] = [{"text": "Evacuate!", "type": "emergency"},
                                         {"text": "Station air unbreathable: breathing emergency active",
                                          "type": "emergency"},
                                         {"text": "Party in the bar", "type": "social"}]
    report = status(game)
    assert report["overall"] == "CRITICAL"
    assert report["power"]["oxygen_threat"] == "emergency"
    assert report["power"]["systems"][0] == {"name": "Life Support", "level": 0, "status": "Offline",
                                             "status_color": "#FF0000"}
    assert alert_texts(game) == [
        ("Station air unbreathable: breathing emergency active", "critical"),
        ("Battery critical (5%)", "critical"),
        ("Oxygen stress affecting 1 crew", "critical"),
        ("Evacuate!", "critical"),
    ]


def test_unhealthy_air_and_injuries_are_cautions():
    game = steady(fill_air(new_game(), {"Oxygen": 0.21, "Nitrogen": 0.64, "Carbon Dioxide": 0.15}))
    game.station_crew[0]["limbs"].update(head=0, chest=0)
    game.station_crew[1]["damage"]["oxygen"] = 30
    assert status(game)["overall"] == "CAUTION"
    assert status(game)["power"]["oxygen_threat"] == "damaging"
    assert alert_texts(game) == [("Station air unhealthy: breathing damage active", "caution"),
                                 ("1 crew injured", "caution"),
                                 ("Oxygen stress affecting 1 crew", "caution")]


def test_critical_crew_outrank_injured_crew():
    game = steady(new_game())
    for limb in game.station_crew[0]["limbs"]:
        game.station_crew[0]["limbs"][limb] = 10
    game.station_crew[1]["limbs"].update(head=0, chest=0)
    report = status(game)
    assert (report["overall"], report["crew"]["critical"], report["crew"]["injured"]) == ("CRITICAL", 1, 1)
    assert alert_texts(game) == [("1 crew in critical condition", "critical")]


def test_security_matters_are_listed():
    game = steady(new_game())
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
    game = steady(new_game())
    game.ship_map[BAR_KEY]["locked"] = True
    game.ship_map[MEDBAY_KEY]["locked"] = True
    game.player_data["access_request"] = {"requester_name": "", "requested_job": "Doctor"}
    assert alert_texts(game) == [("Locked rooms: MedBay, Bar", "caution"),
                                 ("Pending access request: Unknown → Doctor", "caution")]
    assert status(game)["facilities"]["locked_rooms"] == ["MedBay", "Bar"]


def test_a_waiting_duty_is_a_caution():
    game = steady(new_game("Civilian", "Botanist"))
    give_duty(game, kind="treat", room=MEDBAY_KEY, patient="Sam", summary="Treat Sam from Crew Vitals")
    assert alert_texts(game) == [("Duty waiting: Treat Sam from Crew Vitals", "caution")]
    assert status(game)["overall"] == "CAUTION"


def test_faulted_systems_show_and_are_a_caution():
    game = steady(new_game())
    power = game.player_data["station_power"]
    fault_system(power, "communication_array")
    fault_system(power, "security_systems")
    report = status(game)
    assert [(s["name"], s["status"], s["status_color"]) for s in report["power"]["systems"]][2:] == [
        ("Security Systems", "Fault", "#FF9900"), ("Communication Array", "Fault", "#FF9900")]
    assert alert_texts(game) == [("System fault: Security Systems, Communication Array", "caution")]
    assert report["overall"] == "CAUTION"


def test_thirsty_and_dead_plants_are_counted_and_cautions():
    game = steady(new_game("Civilian", "Botanist"))
    planters = game.player_data["botany"]["planters"]
    base = {"occupied": True, "plant": "Potato", "growth_class": "crop", "planted_at_seconds": 0}
    planters[0].update(base, growth_stage=1)
    planters[1].update(base, growth_stage=1, watered=True)
    planters[2].update(base, growth_stage=1, dead=True)
    report = status(game)
    assert (report["overall"], report["facilities"]["botany_thirsty"], report["facilities"]["botany_dead"]) == (
        "CAUTION", 1, 1)
    assert alert_texts(game) == [("Botany planters needing water: 1", "caution"),
                                 ("Botany planters with dead plants: 1", "caution")]


@pytest.mark.parametrize("access_request", [None, {"requested_job": None}])
def test_an_empty_access_request_is_no_alert(access_request):
    game = steady(new_game())
    game.player_data["access_request"] = access_request
    assert alert_texts(game) == []


def test_minor_injuries_are_counted_apart_from_the_healthy_and_raise_no_warning():
    game = steady(new_game())
    game.station_crew[0]["limbs"]["head"] = 90
    crew = status(game)["crew"]
    assert (crew["healthy"], crew["minor"], crew["injured"], crew["critical"]) == (crew["complement"] - 1, 1, 0, 0)
    assert status(game)["alerts"] == []
