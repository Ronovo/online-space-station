import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from helpers import crew, hurt_badly, last_message, new_game, nobody_covers, only_working, pda_messages, reports
from space_online.game.helper_methods import crew_work
from space_online.game.helper_methods.crew_work import (
    BOTANIST_WORK_SECONDS,
    CHEMISTRY_WORK_SECONDS,
    DOCTOR_WORK_SECONDS,
    ENGINEER_WORK_SECONDS,
    RESEARCH_WORK_SECONDS,
    next_work_in,
    post_worker,
    tick_crew_work,
)
from space_online.game.helper_methods.artifacts import new_artifact
from space_online.game.helper_methods.health_bands import is_incapacitated
from space_online.game.helper_methods.npc_movement import post_holder
from space_online.game.helper_methods.power_constants import fault_system
from space_online.game.special_rooms.shared import available_npc, incapacitated_text
from space_online.game.helper_methods.station_status import collect_station_status
from space_online.game.helper_methods.stores import STARTING_REMEDIES
from space_online.game.maps.donut import (
    BOTANY_KEY,
    BRIDGE_KEY,
    CHEMISTRY_KEY,
    ENGINEERING_KEY,
    MEDBAY_KEY,
    RESEARCH_KEY,
    SECURITY_KEY,
    location_from_key,
)
from space_online.game.special_rooms.botany import announce_planter_changes


def test_crew_work_imports_on_its_own():
    result = subprocess.run([sys.executable, "-c", "import space_online.game.helper_methods.crew_work"],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def at(game, seconds):
    game.player_data["game_clock"]["elapsed_seconds"] = seconds
    tick_crew_work(game)
    return game


def test_a_posts_work_is_done_by_its_holder_while_they_are_there():
    game = new_game()
    engineer = crew(game, "Engineer")
    assert post_worker(game, "Engineer", ENGINEERING_KEY) is engineer
    engineer["on_duty"] = False
    assert post_worker(game, "Engineer", ENGINEERING_KEY) is None


@pytest.mark.parametrize("out_of_action", ["jailed", "hurt", "gone"])
def test_the_captain_covers_a_post_nobody_can_work(out_of_action):
    game = new_game()
    engineer, captain = crew(game, "Engineer"), crew(game, "Captain")
    if out_of_action == "jailed":
        engineer["in_jail"] = True
    elif out_of_action == "hurt":
        hurt_badly(engineer)
    else:
        game.station_crew.remove(engineer)
    assert post_worker(game, "Engineer", ENGINEERING_KEY) is captain


def test_the_head_of_personnel_covers_only_the_rooms_they_have_access_to():
    game = new_game()
    hop = crew(game, "Head of Personnel")
    crew(game, "Captain")["in_jail"] = True
    crew(game, "Engineer")["in_jail"] = True
    crew(game, "Security Guard")["in_jail"] = True
    assert post_worker(game, "Engineer", ENGINEERING_KEY) is hop
    assert post_worker(game, "Security Guard", SECURITY_KEY) is None
    assert post_worker(game, "Captain", BRIDGE_KEY) is hop
    hop["on_duty"] = False
    assert post_worker(game, "Engineer", ENGINEERING_KEY) is None


def test_nobody_covers_the_players_own_post():
    game = new_game("Engineering", "Engineer")
    assert post_worker(game, "Engineer", ENGINEERING_KEY) is None


def science_game(post):
    """A Scientist's game posted to post, with an artifact on the bench and only the science labs at work."""
    game = new_game("Science", "Scientist", post=post)
    game.player_data["research"]["bench"].append(new_artifact())
    return at(only_working(game, "Scientist"), max(CHEMISTRY_WORK_SECONDS, RESEARCH_WORK_SECONDS))


def test_a_player_scientist_leaves_only_their_own_labs_work_undone():
    game = science_game(CHEMISTRY_KEY)
    assert post_worker(game, "Scientist", CHEMISTRY_KEY) is None
    assert post_worker(game, "Scientist", RESEARCH_KEY) is post_holder(game.station_crew, "Scientist", RESEARCH_KEY)
    assert (game.player_data["stores"]["remedies"], game.player_data["research"]["bench"]) == (STARTING_REMEDIES, [])
    assert next_work_in(game, "Scientist", CHEMISTRY_KEY) is None

    game = science_game(RESEARCH_KEY)
    assert post_worker(game, "Scientist", RESEARCH_KEY) is None
    assert game.player_data["stores"]["remedies"] == STARTING_REMEDIES + 1
    assert len(game.player_data["research"]["bench"]) == 1


def test_the_captain_covers_a_science_lab_whose_scientist_is_out():
    game = new_game()
    post_holder(game.station_crew, "Scientist", RESEARCH_KEY)["in_jail"] = True
    assert post_worker(game, "Scientist", RESEARCH_KEY) is crew(game, "Captain")
    assert post_worker(game, "Scientist", CHEMISTRY_KEY) is post_holder(game.station_crew, "Scientist", CHEMISTRY_KEY)


def test_the_doctor_puts_the_worst_hurt_back_on_their_feet_one_at_a_time():
    game = new_game()
    doctor, chef, miner = crew(game, "Doctor"), crew(game, "Chef"), crew(game, "Miner")
    hurt_badly(chef)
    hurt_badly(miner)["limbs"]["head"] = 0
    crew(game, "Bartender")["limbs"]["head"] = 60
    at(game, DOCTOR_WORK_SECONDS - 1)
    assert is_incapacitated(miner)
    at(game, DOCTOR_WORK_SECONDS)
    assert (is_incapacitated(miner), is_incapacitated(chef)) == (False, True)
    assert last_message(game) == ("MedBay", f"{doctor['name']} treats {miner['name']} (Miner), who is fit for work again.")
    at(game, DOCTOR_WORK_SECONDS + 1)
    assert is_incapacitated(chef)
    at(game, 2 * DOCTOR_WORK_SECONDS)
    assert not is_incapacitated(chef)
    assert crew(game, "Bartender")["limbs"]["head"] == 60
    at(game, 3 * DOCTOR_WORK_SECONDS)
    assert reports(game) == ["MedBay", "MedBay"]


def test_a_doctor_who_is_down_is_treated_by_whoever_covers_medbay():
    game = new_game()
    doctor = hurt_badly(crew(game, "Doctor"))
    at(game, DOCTOR_WORK_SECONDS)
    assert not is_incapacitated(doctor)
    captain = crew(game, "Captain")["name"]
    assert last_message(game)[1] == (f"With no Doctor on duty, Captain {captain} treats {doctor['name']} (Doctor), "
                                     "who is fit for work again.")


def test_with_the_player_as_the_doctor_the_hurt_wait_for_the_player():
    game = new_game("Medical", "Doctor")
    chef = hurt_badly(crew(game, "Chef"))
    at(game, DOCTOR_WORK_SECONDS)
    assert is_incapacitated(chef) and game._messages == []


def test_the_engineer_repairs_faults_and_restarts_the_solar_array():
    game = new_game()
    engineer = crew(game, "Engineer")
    power = game.player_data["station_power"]
    fault_system(power, "security_systems")
    power["solar_charging"] = False
    at(game, ENGINEER_WORK_SECONDS)
    assert (power["faults"], power["system_levels"]["security_systems"], power["solar_charging"]) == ([], 7, False)
    assert last_message(game) == ("Engineering", f"{engineer['name']} repairs the Security Systems.")
    at(game, 2 * ENGINEER_WORK_SECONDS)
    assert power["solar_charging"]
    assert last_message(game) == ("Engineering", f"{engineer['name']} restarts the solar array.")
    at(game, 3 * ENGINEER_WORK_SECONDS)
    assert reports(game) == ["Engineering", "Engineering"]


def test_an_engineer_who_is_out_fixes_nothing_until_someone_covers():
    game = new_game()
    crew(game, "Engineer")["in_jail"] = True
    nobody_covers(game)
    power = game.player_data["station_power"]
    power["solar_charging"] = False
    at(game, ENGINEER_WORK_SECONDS)
    assert not power["solar_charging"]
    crew(game, "Captain")["on_duty"] = True
    at(game, 2 * ENGINEER_WORK_SECONDS)
    assert power["solar_charging"]


def dimmed(game, before=6, now=1):
    power = game.player_data["station_power"]
    power["system_levels"]["hallway_lighting"] = now
    power["dimmed_from"] = before
    return power


def test_the_engineer_restores_dimmed_lighting_and_reports_it_to_security():
    game = new_game()
    engineer = crew(game, "Engineer")
    power = game.player_data["station_power"]
    power["system_levels"]["hallway_lighting"] = 2
    at(game, ENGINEER_WORK_SECONDS)
    assert (power["system_levels"]["hallway_lighting"], reports(game)) == (2, [])

    dimmed(game)
    at(game, 2 * ENGINEER_WORK_SECONDS)
    assert (power["system_levels"]["hallway_lighting"], power["dimmed_from"]) == (6, None)
    assert last_message(game) == ("Engineering", f"{engineer['name']} restores the hallway lighting and reports to "
                                                 "Security that someone tampered with it.")
    assert pda_messages(game) == []


def test_a_player_security_guard_hears_about_the_tampering_on_their_pda():
    game = new_game("Security", "Security Guard")
    dimmed(game)
    at(game, ENGINEER_WORK_SECONDS)
    assert pda_messages(game) == [("Engineering", crew_work.TAMPERED_LIGHTS_PAGE)]


def test_dimmed_lighting_waits_while_the_engineer_is_out():
    game = new_game()
    crew(game, "Engineer")["in_jail"] = True
    nobody_covers(game)
    power = dimmed(game)
    at(game, ENGINEER_WORK_SECONDS)
    assert (power["system_levels"]["hallway_lighting"], power["dimmed_from"]) == (1, 6)
    crew(game, "Captain")["on_duty"] = True
    at(game, 2 * ENGINEER_WORK_SECONDS)
    assert power["system_levels"]["hallway_lighting"] == 6


def test_crew_too_hurt_to_work_cannot_be_talked_to_or_called():
    game = new_game()
    doctor = hurt_badly(crew(game, "Doctor"))
    game.player_data["location"] = location_from_key(MEDBAY_KEY)
    assert available_npc(game, "Doctor", MEDBAY_KEY) is None
    widgets = game.view()["screen"]["buttons"]
    assert incapacitated_text(doctor) in [widget.get("text") for widget in widgets]
    game.perform("room.call_npc", {"job": "Doctor"})
    assert last_message(game) == ("Hurt", f"{doctor['name']} is too badly hurt to work and needs a doctor.")


def botanist_game(player_job="Staff Assistant"):
    return only_working(new_game("Civilian", player_job), "Botanist")


def planters(game):
    return game.player_data["botany"]["planters"]


def occupied(game):
    return [p for p in planters(game) if p["occupied"]]


def test_the_npc_botanist_plants_and_a_visitor_sees_it_growing():
    game = botanist_game()
    for turn in range(1, 5):
        at(game, turn * BOTANIST_WORK_SECONDS)
    assert len(occupied(game)) == 4 and not any(p["dead"] for p in planters(game))
    assert {p["tended_by"] for p in occupied(game)} == {"npc"}
    game.player_data["location"] = location_from_key(BOTANY_KEY)
    game.perform("room.view_plants", {})
    game.perform("panel.choose_row", {"row": 0})
    ctx = game.view()["panel"]["ctx"]
    assert ctx["cards"][0]["title"] != "Planter 1: Empty"
    assert ctx["cards"][0]["title"].startswith("Planter 1: ") and ctx["hand_buttons"] == []
    assert "Sprouting" in ctx["cards"][0]["stage"]
    assert not any(card["can_harvest"] for card in ctx["cards"])
    assert not game._messages and not game.player_data["pda"]["messages"]


def test_the_npc_botanist_harvests_into_the_kitchen_and_replants():
    game = botanist_game()
    produce = game.player_data["stores"]["produce"]
    produce.update(Tomato=0, Potato=8, Carrot=8, Apple=8)
    at(game, BOTANIST_WORK_SECONDS)
    first = planters(game)[0]
    assert first["produces"] == "tomato" and first["growth_class"] == "fruiting"
    produce.update(Tomato=8, Potato=0)
    at(game, 2 * BOTANIST_WORK_SECONDS)
    assert planters(game)[1]["produces"] == "potato" and planters(game)[1]["growth_class"] == "crop"
    for turn in range(3, 14):
        at(game, turn * BOTANIST_WORK_SECONDS)
    produce.update(Potato=0, Tomato=0)
    for turn in range(14, 40):
        at(game, turn * BOTANIST_WORK_SECONDS)
    assert not any(p["dead"] for p in planters(game))
    assert len(occupied(game)) > 4
    assert produce["Potato"] > 0


def test_a_dead_npc_planting_is_cleared_and_replanted():
    game = botanist_game()
    at(game, BOTANIST_WORK_SECONDS)
    planters(game)[0]["dead"] = True
    at(game, 2 * BOTANIST_WORK_SECONDS)
    assert not planters(game)[0]["dead"] and planters(game)[0]["planted_at_seconds"] == 2 * BOTANIST_WORK_SECONDS


def test_the_npc_botanist_leaves_a_planting_by_the_player_alone():
    game = botanist_game()
    planters(game)[0].update(occupied=True, plant="Wheat", seed_id="wheat_seeds", produces="wheat",
                             growth_class="crop", planted_at_seconds=0, growth_stage=5)
    at(game, BOTANIST_WORK_SECONDS)
    assert planters(game)[0]["plant"] == "Wheat" and planters(game)[1]["tended_by"] == "npc"


def test_a_player_botanist_leaves_the_planters_alone():
    game = botanist_game("Botanist")
    at(game, 10 * BOTANIST_WORK_SECONDS)
    assert not occupied(game)


def test_a_captain_covers_a_jailed_botanists_planters():
    game = botanist_game()
    crew(game, "Botanist")["in_jail"] = True
    at(game, BOTANIST_WORK_SECONDS)
    assert len(occupied(game)) == 1


def test_npc_planters_raise_no_alerts_and_do_not_count_as_thirsty():
    game = botanist_game()
    for turn in range(1, 20):
        at(game, turn * BOTANIST_WORK_SECONDS)
        announce_planter_changes(game)
    assert not game._messages and not game.player_data["notes"]
    assert collect_station_status(game.player_data, game.station_crew)["facilities"]["botany_thirsty"] == 0
    planters(game)[0]["watered"] = False
    assert collect_station_status(game.player_data, game.station_crew)["facilities"]["botany_thirsty"] == 0


def away_botanist(monkeypatch, roll):
    monkeypatch.setattr(crew_work, "random", SimpleNamespace(random=lambda: roll))
    game = botanist_game()
    at(game, BOTANIST_WORK_SECONDS)
    crew(game, "Botanist")["in_jail"] = True
    nobody_covers(game)
    return game


def test_an_away_botanist_pages_once_per_thirsty_planter_per_stage(monkeypatch):
    game = away_botanist(monkeypatch, 0.0)
    assert not pda_messages(game)
    planters(game)[0]["watered"] = False
    at(game, 2 * BOTANIST_WORK_SECONDS)
    assert pda_messages(game) == [("Botany", "Could someone water planter 1? I'm away from the lab.")]
    at(game, 3 * BOTANIST_WORK_SECONDS)
    assert len(pda_messages(game)) == 1


def test_an_away_botanist_does_not_page_when_the_roll_fails(monkeypatch):
    game = away_botanist(monkeypatch, 0.99)
    planters(game)[0]["watered"] = False
    at(game, 2 * BOTANIST_WORK_SECONDS)
    assert not pda_messages(game)


def test_an_away_botanist_does_not_page_about_a_watered_planter(monkeypatch):
    game = away_botanist(monkeypatch, 0.0)
    at(game, 2 * BOTANIST_WORK_SECONDS)
    assert not pda_messages(game)


def test_the_npc_botanist_plants_nothing_when_every_planter_is_taken():
    game = botanist_game()
    for planter in planters(game):
        planter.update(occupied=True, plant="Wheat", produces="wheat", planted_at_seconds=0, growth_stage=1)
    at(game, BOTANIST_WORK_SECONDS)
    assert {p["tended_by"] for p in planters(game)} == {None}
