from types import SimpleNamespace

import pytest
from flask import render_template

from helpers import (
    ctx,
    duty,
    give,
    give_duty,
    in_room,
    item_action,
    job_event,
    labels,
    last_message,
    menu_widgets,
    new_game,
    notes,
    open_station,
)
from space_online.game.helper_methods import artifacts
from space_online.game.helper_methods.artifacts import (
    ARTIFACT_KINDS,
    DEVICES,
    HEALER_MEND,
    HEALER_RECHARGE_SECONDS,
    MAX_STRENGTH,
    OVERLOAD_DAMAGE,
    OVERLOAD_MARGIN,
    TELE_MULTIPLIERS,
    TELE_OFFSET_RANGE,
    WARPER_RECHARGE_SECONDS,
    artifact_of,
    is_unknown_artifact,
    is_usable_artifact,
    mark_analysed,
    new_artifact,
    new_research,
    run_test,
)
from space_online.game.helper_methods import npc_movement
from space_online.game.helper_methods.crew_work import RESEARCH_WORK_SECONDS, tick_crew_work
from space_online.game.helper_methods.errands import DUTY_EXPIRY_SECONDS, tick_duty_expiry
from space_online.game.helper_methods.random_events import build_job_event
from space_online.game.helper_methods.npc_movement import post_holder
from space_online.game.maps.donut import (
    BAR_KEY,
    CHEMISTRY_KEY,
    ENGINEERING_KEY,
    KITCHEN_KEY,
    MEDBAY_KEY,
    RESEARCH_KEY,
    SECURITY_KEY,
    location_from_key,
)
from space_online.game.objects.items import add_to_inventory, get_item_definition
from space_online.game.special_rooms import research
from space_online.game.special_rooms.research import ANALYSIS_REWARD, FINDERS_FEE, MAX_BENCH


def an_artifact(kind="healer", device="heater", threshold=5):
    artifact = new_artifact()
    artifact_of(artifact).update(kind=kind, device=device, threshold=threshold)
    return artifact


def in_lab(department="Science", job="Scientist", post=RESEARCH_KEY):
    game = in_room(RESEARCH_KEY, department, job, post=post)
    game.player_data["research"]["tele"] = {"x": {"m": 2, "c": 3}, "y": {"m": 4, "c": -1}}
    return game


def at_bench(*bench):
    game = in_lab()
    game.player_data["research"]["bench"] = list(bench)
    return open_station(game, "artifact_section", "show_bench")


def at_teleporter(department="Science", job="Scientist"):
    return open_station(in_lab(department, job), "teleporter_room", "show_teleporter")


def test_the_research_lab_is_the_south_door_of_the_science_hall():
    game = new_game("Science", "Scientist")
    game.player_data["location"] = {"x": 3, "y": 6}
    screen = game.view()["screen"]
    assert (screen["name"], screen["grid"][2][1]["label"]) == ("Science Hall", "Research Lab")
    game.perform("game.enter_room", {"room_key": RESEARCH_KEY})
    assert labels(game) == ["Enter the Artifact Section", "Enter the Teleporter Room", "Lock/Unlock Door",
                            "Room Options"]
    game.perform("room.open_station", {"mode": "artifact_section"})
    assert labels(game) == ["Artifact Section", "Artifact Bench (0)", "Back to Station Menu"]
    game.perform("room.open_station", {"mode": "teleporter_room"})
    assert labels(game) == ["Teleporter Room", "Teleporter", "Back to Station Menu"]


@pytest.mark.parametrize("mode, action, panel", [("artifact_section", "room.show_bench", "artifact_bench"),
                                                 ("teleporter_room", "room.show_teleporter", "teleporter")])
def test_each_research_station_opens_only_its_own_panel(mode, action, panel):
    game = in_lab()
    game.perform("room.open_station", {"mode": mode})
    station_actions = [widget["action"] for widget in menu_widgets(game) if widget.get("action")]
    assert station_actions == [action, "room.set_mode"]
    game.perform(action, {})
    assert [opened["type"] for opened in game.ui["panels"]] == [panel]


@pytest.mark.parametrize("department, job, allowed", [("Science", "Scientist", True),
                                                      ("Administration", "Captain", True),
                                                      ("Administration", "Head of Personnel", True),
                                                      ("Civilian", "Staff Assistant", False),
                                                      ("Medical", "Doctor", False)])
def test_both_research_stations_need_science_access(department, job, allowed):
    game = in_lab(department, job)
    for mode, action in (("artifact_section", "show_bench"), ("teleporter_room", "show_teleporter")):
        open_station(game, mode, action)
        assert bool(game.ui["panels"]) is allowed


def test_a_shift_calibrates_its_teleporter_afresh():
    for _ in range(20):
        fresh = new_research()
        assert fresh["bench"] == []
        for axis in ("x", "y"):
            assert fresh["tele"][axis]["m"] in TELE_MULTIPLIERS
            assert TELE_OFFSET_RANGE[0] <= fresh["tele"][axis]["c"] <= TELE_OFFSET_RANGE[1]


def test_a_new_artifact_is_unknown_and_cannot_be_used_until_it_is_analysed():
    artifact = new_artifact()
    details = artifact_of(artifact)
    assert details["kind"] in ARTIFACT_KINDS and details["device"] in DEVICES
    assert (is_unknown_artifact(artifact), is_usable_artifact(artifact)) == (True, False)
    assert artifact_of(get_item_definition("medkit")) is None
    assert not is_unknown_artifact(get_item_definition("medkit")) and not is_usable_artifact({"id": "x"})
    game = new_game()
    add_to_inventory(game.player_data, artifact)
    game.open_panel("inventory")
    game.perform("panel.select", {"index": 0})
    game.perform("panel.actions", {})
    assert [action["name"] for action in ctx(game)["actions"]] == ["drop"]
    mark_analysed(game.player_data["inventory"][0])
    assert [action["name"] for action in ctx(game)["actions"]] == ["use", "drop"]


@pytest.mark.parametrize("device, strength, outcome", [
    ("xray", 5, "nothing"), ("heater", 1, "faint"), ("heater", 3, "close"), ("heater", 4, "close"),
    ("heater", 5, "activated"), ("heater", 5 + OVERLOAD_MARGIN, "activated"),
    ("heater", 5 + OVERLOAD_MARGIN + 1, "overload"),
])
def test_what_a_test_rig_does_to_an_artifact(device, strength, outcome):
    artifact = an_artifact(threshold=5)
    assert run_test(artifact, device, strength)[0] == outcome
    assert artifact_of(artifact)["activated"] == (outcome == "activated")


def test_working_an_artifact_out_at_the_bench(monkeypatch):
    monkeypatch.setattr(research, "random", SimpleNamespace(choice=lambda limbs: limbs[0]))
    game = at_bench(an_artifact("healer", "electric", 4))
    assert ctx(game)["artifacts"] == [{"index": 0, "label": "Artifact 1"}]
    assert (ctx(game)["device"], ctx(game)["strength"], ctx(game)["selected"]) == ("heater", 1, None)
    game.perform("panel.test", {})
    assert ctx(game)["result"] == "Pick an artifact from the bench first."
    game.perform("panel.select_artifact", {"index": 0})
    game.perform("panel.test", {})
    assert ctx(game)["result"] == "Heater at 1: The Heater does nothing to it."
    game.perform("panel.set_device", {"name": "microwave"})
    game.perform("panel.set_device", {"name": "electric"})
    game.perform("panel.set_strength", {"value": "99"})
    assert (ctx(game)["device"], ctx(game)["strength"]) == ("electric", MAX_STRENGTH)
    game.perform("panel.test", {})
    assert ctx(game)["result"].startswith("Electric Box at 10: The artifact shrieks")
    assert game.player_data["limbs"]["head"] == 100 - OVERLOAD_DAMAGE
    assert last_message(game) == ("Artifact Bench", "The artifact's pulse throws you against the wall.")
    game.perform("panel.set_strength", {"value": "4"})
    game.perform("panel.test", {})
    assert ctx(game)["result"] == f"Electric Box at 4: The artifact comes alive. {ARTIFACT_KINDS['healer']['shows']}"
    assert ctx(game)["artifacts"] == [{"index": 0, "label": "Artifact 1 (active)"}]


def test_filing_the_right_analysis_pays_and_hands_the_artifact_over():
    game = at_bench(an_artifact("power_cell", "xray", 4))
    game.perform("panel.file_analysis", {"kind": "healer", "device": "xray"})
    assert ctx(game)["result"] == "Pick an artifact from the bench first."
    game.perform("panel.select_artifact", {"index": 0})
    game.perform("panel.file_analysis", {"kind": "healer", "device": "heater"})
    assert ctx(game)["result"] == ("Central Command sends the form back. Wrong: what it is and what sets it off.")
    game.perform("panel.file_analysis", {"kind": "power_cell", "device": "heater"})
    assert ctx(game)["result"] == "Central Command sends the form back. Wrong: what sets it off."
    game.perform("panel.file_analysis", {"kind": "power_cell", "device": "xray"})
    found = game.player_data["inventory"][0]
    assert (found["name"], is_usable_artifact(found), game.player_data["research"]["bench"]) == (
        "Power Cell Artifact", True, [])
    assert game.player_data["credits"] == 4500 + ANALYSIS_REWARD
    assert last_message(game) == ("Artifact Bench", "Central Command accepts your analysis of the Power Cell Artifact "
                                                    f"and pays you {ANALYSIS_REWARD} credits.")
    assert (ctx(game)["selected"], ctx(game)["artifacts"]) == (None, [])


def test_an_analysis_central_command_asked_for_is_a_duty_done():
    game = at_bench(an_artifact())
    give_duty(game, kind="analyse", room=RESEARCH_KEY, reward=ANALYSIS_REWARD, summary="Analyse it")
    game.perform("panel.select_artifact", {"index": 0})
    game.perform("panel.file_analysis", {"kind": "healer", "device": "heater"})
    assert (game.player_data["duties"], game.player_data["round"]["duties_done"]) == ([], 1)
    assert (last_message(game)[0], game.player_data["credits"]) == ("Duty Done", 4500 + ANALYSIS_REWARD)


def test_central_command_sends_the_research_scientist_artifacts_while_the_bench_has_room(monkeypatch):
    game = new_game("Science", "Scientist", post=RESEARCH_KEY)
    event = job_event(monkeypatch, game, randint=lambda low, high: low)
    assert event["title"] == "Artifact Delivery"
    event["effect"]()
    assert len(game.player_data["research"]["bench"]) == 1
    assert duty(game) == {"kind": "analyse", "room": RESEARCH_KEY, "reward": ANALYSIS_REWARD,
                          "summary": f"Analyse an artifact on the bench ({ANALYSIS_REWARD} cr)"}
    game.player_data["research"]["bench"] = [an_artifact()] * MAX_BENCH
    assert build_job_event(game) is None


def test_anyone_can_leave_an_artifact_on_the_bench_for_a_finders_fee():
    game = in_lab("Supply", "Miner")
    assert labels(game) == ["Talk to Scientist"]
    game.perform("room.leave_artifact", {})
    add_to_inventory(game.player_data, new_artifact())
    assert labels(game)[0] == "Leave an Artifact on the Bench"
    game.perform("room.leave_artifact", {})
    assert (len(game.player_data["research"]["bench"]), game.player_data["inventory"]) == (1, [])
    assert game.player_data["credits"] == 3000 + FINDERS_FEE
    assert last_message(game)[1].endswith(f"finder's fee of {FINDERS_FEE} credits.")
    game.player_data["research"]["bench"] = [an_artifact()] * MAX_BENCH
    add_to_inventory(game.player_data, new_artifact())
    game.perform("room.leave_artifact", {})
    assert last_message(game) == ("Research Lab",
                                  "The bench is full. The artifacts on it have to be worked out first.")
    game.perform("room.talk_to_scientist", {})
    assert last_message(game)[0] == "Scientist"


def test_a_scientist_gets_no_fee_for_the_bench_and_visitors_get_no_station():
    game = in_lab()
    add_to_inventory(game.player_data, new_artifact())
    game.perform("room.set_mode", {"mode": "options"})
    game.perform("room.leave_artifact", {})
    assert (game.player_data["credits"], last_message(game)[1]) == (4500, "You set the artifact down on the bench.")
    chemistry_scientist = in_lab(post=CHEMISTRY_KEY)
    add_to_inventory(chemistry_scientist.player_data, new_artifact())
    chemistry_scientist.perform("room.set_mode", {"mode": "options"})
    chemistry_scientist.perform("room.leave_artifact", {})
    assert chemistry_scientist.player_data["credits"] == 4500
    visitor = in_lab("Supply", "Miner")
    visitor.ui["room_mode"] = "artifact_section"
    assert labels(visitor) == ["Talk to Scientist"]
    for action in ("show_bench", "show_teleporter"):
        visitor.perform(f"room.{action}", {})
    assert visitor.ui["panels"] == []
    post_holder(visitor.station_crew, "Scientist", RESEARCH_KEY)["on_duty"] = False
    visitor.perform("room.talk_to_scientist", {})
    assert visitor._messages == []


def test_each_science_lab_talks_to_and_calls_its_own_scientist(monkeypatch):
    game = in_lab(post=CHEMISTRY_KEY)
    game.perform("room.set_mode", {"mode": "options"})
    assert labels(game) == ["Talk to Scientist", "Back to Station Menu"]
    researcher = post_holder(game.station_crew, "Scientist", RESEARCH_KEY)
    researcher.update(on_duty=False, location={"x": 2, "y": 5})
    assert labels(game) == ["The scientist is away from the lab.", f"Call {researcher['name']}",
                            "Back to Station Menu"]
    monkeypatch.setattr(npc_movement.random, "random", lambda: 0.0)
    game.perform("room.call_npc", {"job": "Scientist"})
    assert (researcher["on_duty"], researcher["location"]) == (True, location_from_key(RESEARCH_KEY))
    own_lab = in_lab(post=RESEARCH_KEY)
    own_lab.perform("room.set_mode", {"mode": "options"})
    assert labels(own_lab) == ["Back to Station Menu"]
    own_lab.perform("room.call_npc", {"job": "Scientist"})
    assert own_lab._messages == []


def test_the_npc_scientist_in_research_works_through_the_bench():
    game = new_game()
    researcher = post_holder(game.station_crew, "Scientist", RESEARCH_KEY)
    game.player_data["crew_work"] = {key: 10 ** 9 for key in (MEDBAY_KEY, ENGINEERING_KEY, KITCHEN_KEY, BAR_KEY)}
    game.player_data["game_clock"]["elapsed_seconds"] = RESEARCH_WORK_SECONDS
    tick_crew_work(game)
    assert game._messages == []
    game.player_data["research"]["bench"] = [an_artifact("warper")]
    game.player_data["game_clock"]["elapsed_seconds"] = 2 * RESEARCH_WORK_SECONDS
    tick_crew_work(game)
    assert game.player_data["research"]["bench"] == []
    assert last_message(game) == ("Research Lab",
                                  f"{researcher['name']} has worked out an artifact from the bench: a Warper.")


def analysed(kind):
    artifact = an_artifact(kind)
    mark_analysed(artifact)
    return artifact


def test_a_healer_mends_every_limb_and_then_has_to_recharge():
    game = new_game()
    game.player_data["limbs"].update(head=50, chest=90)
    add_to_inventory(game.player_data, analysed("healer"))
    item_action(game, 0, "use")
    assert (game.player_data["limbs"]["head"], game.player_data["limbs"]["chest"]) == (50 + HEALER_MEND, 100)
    item_action(game, 0, "use")
    assert last_message(game) == ("Healer Artifact", "It is still recharging. Ready in 2m 0s.")
    game.player_data["game_clock"]["elapsed_seconds"] = HEALER_RECHARGE_SECONDS
    item_action(game, 0, "use")
    assert game.player_data["limbs"]["head"] == 100 and len(game.player_data["inventory"]) == 1


def test_a_power_cell_empties_into_the_station_battery_and_is_gone():
    game = new_game()
    game.player_data["station_power"]["battery_level"] = 90
    add_to_inventory(game.player_data, analysed("power_cell"))
    item_action(game, 0, "use")
    assert (game.player_data["station_power"]["battery_level"], game.player_data["inventory"]) == (100, [])
    assert last_message(game)[1].endswith("Battery: 100%.")


def test_a_warper_throws_you_to_a_hallway_somewhere(monkeypatch):
    monkeypatch.setattr(artifacts, "pick_random_hallway_location", lambda: {"x": 2, "y": 5})
    game = new_game()
    add_to_inventory(game.player_data, analysed("warper"))
    item_action(game, 0, "use")
    assert (game.player_data["location"], game.ui["panels"]) == ({"x": 2, "y": 5}, [])
    assert artifact_of(game.player_data["inventory"][0])["ready_at"] == WARPER_RECHARGE_SECONDS


def test_two_beacon_sends_per_axis_are_enough_to_work_the_calibration_out():
    game = at_teleporter()
    game.perform("panel.beacon", {"x": "10", "y": "10"})
    game.perform("panel.beacon", {"x": "20", "y": "30"})
    assert ctx(game)["log"] == ["X 20, Y 30: the beacon reports 8.5 North, 7.75 East.",
                                "X 10, Y 10: the beacon reports 3.5 North, 2.75 East."]
    assert (ctx(game)["x"], ctx(game)["y"]) == ("20", "30")


def test_the_console_wants_whole_numbers_and_a_floor_to_aim_at():
    game = at_teleporter()
    for action in ("scan", "beacon", "send_me", "send_item", "receive"):
        game.perform(f"panel.{action}", {"x": "two", "y": "3"})
    assert ctx(game)["log"] == ["The console wants a whole number for X and for Y."] * 5
    game.perform("panel.scan", {"x": "4", "y": "0"})
    game.perform("panel.send_me", {"x": "99", "y": "99"})
    assert ctx(game)["log"][:2] == [
        "X 99, Y 99: the pad stays dark. There is no floor at those coordinates.",
        "X 4, Y 0: the pad stays dark. There is no floor at those coordinates."]
    game.perform("panel.scan", {"x": "3", "y": "-1"})
    assert ctx(game)["log"][0] == "X 3, Y -1: the scanner reads solid floor."
    assert len(ctx(game)["log"]) == research.MAX_TELE_LOG
    assert game.location_key() == RESEARCH_KEY


def test_sending_yourself_lands_you_anywhere_with_a_floor_locked_or_not():
    game = at_teleporter()
    game.ship_map[SECURITY_KEY]["locked"] = True
    game.perform("panel.send_me", {"x": str(2 * 6 + 3), "y": str(4 * 6 - 1)})
    assert (game.location_key(), game.ui["panels"]) == (SECURITY_KEY, [])
    assert last_message(game) == ("Teleporter", "The lab folds away, and you are standing in the Security Office.")
    assert notes(game)[-1] == "Teleported to the Security Office."


def test_sending_an_item_leaves_it_on_the_floor_there_and_receiving_brings_it_back():
    game = give(at_teleporter(), "wrench", "snack")
    bar = {"x": str(2 * -1 + 3), "y": str(4 * 3 - 1)}
    assert ctx(game)["pad_items"] == [{"index": 0, "label": "Wrench"}, {"index": 1, "label": "Snack"}]
    game.perform("panel.send_item", {**bar, "item": "1"})
    game.perform("panel.send_item", {**bar, "item": "7"})
    assert [item["id"] for item in game.player_data["floor"][BAR_KEY]] == ["snack"]
    assert ctx(game)["log"][:2] == ["Put something on the pad first.", "X 1, Y 11: the Snack vanishes from the pad."]
    game.perform("panel.receive", bar)
    game.perform("panel.receive", bar)
    assert [item["id"] for item in game.player_data["inventory"]] == ["wrench", "snack"]
    assert BAR_KEY not in game.player_data["floor"]
    assert ctx(game)["log"][:2] == ["X 1, Y 11: nothing comes back. There is nothing lying there.",
                                    "X 1, Y 11: Snack appears on the pad."]


def test_the_teleporter_and_bench_screens(app):
    game = at_teleporter()
    with app.test_request_context():
        page = render_template("game/screen.html", view=game.view())
        assert "Nothing sent yet." in page and "Security Office: 6 North, 6 East" in page and "disabled" in page
        give(game, "wrench")
        game.perform("panel.beacon", {"x": "3", "y": "-1"})
        page = render_template("game/screen.html", view=game.view())
        assert "the beacon reports 0 North, 0 East." in page and '<option value="0">Wrench</option>' in page
        bench = at_bench()
        assert "The bench is empty." in render_template("game/screen.html", view=bench.view())
        bench.player_data["research"]["bench"] = [an_artifact()]
        page = render_template("game/screen.html", view=bench.view())
    assert "Artifact 1" in page and "X-ray Scanner" in page and "File Analysis" in page
    assert " selected>" not in page


def test_a_form_sent_back_keeps_its_answers_for_the_next_try(app):
    bench = at_bench(an_artifact("power_cell", "xray", 4))
    bench.perform("panel.select_artifact", {"index": 0})
    bench.perform("panel.file_analysis", {"kind": "warper", "device": "impact"})
    assert ctx(bench)["filed"] == {"kind": "warper", "device": "impact"}
    with app.test_request_context():
        page = render_template("game/screen.html", view=bench.view())
    assert '<option value="warper" selected>' in page and '<option value="impact" selected>' in page
    assert page.count(" selected>") == 2


def sent_by_central_command(game, kind="healer", device="heater"):
    """Have Central Command send an artifact with its analyse duty. Returns the artifact."""
    build_job_event(game)["effect"]()
    artifact = game.player_data["research"]["bench"][-1]
    artifact_of(artifact).update(kind=kind, device=device)
    return artifact


def test_an_artifact_filed_in_time_is_its_own_duty_done():
    game = at_bench()
    sent_by_central_command(game)
    give_duty(game, kind="analyse", room=RESEARCH_KEY, reward=ANALYSIS_REWARD, summary="Another")
    game.perform("panel.select_artifact", {"index": 0})
    game.perform("panel.file_analysis", {"kind": "healer", "device": "heater"})
    assert [duty["summary"] for duty in game.player_data["duties"]] == ["Another"]
    assert game.player_data["credits"] == 4500 + ANALYSIS_REWARD


def test_an_artifact_filed_after_its_duty_ran_out_pays_half_and_one_from_the_mines_pays_in_full():
    game = at_bench()
    sent_by_central_command(game)
    game.player_data["game_clock"]["elapsed_seconds"] = DUTY_EXPIRY_SECONDS
    tick_duty_expiry(game)
    game.player_data["research"]["bench"].append(an_artifact("power_cell", "xray"))
    game.perform("panel.select_artifact", {"index": 0})
    game.perform("panel.file_analysis", {"kind": "healer", "device": "heater"})
    assert game.player_data["credits"] == 4500 + ANALYSIS_REWARD // 2
    assert last_message(game) == ("Artifact Bench", "Central Command accepts your late analysis of the Healer Artifact "
                                                    f"and pays you {ANALYSIS_REWARD // 2} credits, half the usual, as "
                                                    "its duty was missed.")
    late_note = f"Analysed a Healer Artifact late, for {ANALYSIS_REWARD // 2} credits."
    assert notes(game)[-1] == late_note
    game.perform("panel.select_artifact", {"index": 0})
    game.perform("panel.file_analysis", {"kind": "power_cell", "device": "xray"})
    assert game.player_data["credits"] == 4500 + ANALYSIS_REWARD // 2 + ANALYSIS_REWARD
