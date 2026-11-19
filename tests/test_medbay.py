from helpers import (
    buttons,
    choose,
    crew,
    ctx,
    give_duty,
    in_room,
    labels,
    last_message,
    new_game,
    nobody_covers,
    notes,
    open_station,
    reports,
)
from space_online.game.helper_methods.stores import STARTING_REMEDIES
from space_online.game.helper_methods import npc_movement
from space_online.game.helper_methods.crew_work import CHEMISTRY_WORK_SECONDS
from space_online.game.helper_methods.game_clock import format_elapsed
from space_online.game.special_rooms.med_bay import OUT_OF_REMEDIES
from space_online.game.maps.donut import CHEMISTRY_KEY, MEDBAY_KEY, RESEARCH_KEY
from space_online.game.special_rooms.med_bay import assess_injuries, build_health_check_report


def in_medbay(department="Civilian", job="Staff Assistant"):
    return in_room(MEDBAY_KEY, department, job)


def hurt(player, **values):
    for key, value in values.items():
        if key in player["limbs"]:
            player["limbs"][key] = value
        elif key == "alcohol":
            player["alcohol_percent"] = value
        else:
            player["damage"][key] = value
    return player


def test_visitors_can_get_a_scan_or_see_the_doctor():
    game = in_medbay()
    assert buttons(game) == [("Request Health Check", "room.health_check"), ("Talk to Doctor", "room.talk_to_doctor")]


def test_a_healthy_scan():
    report = build_health_check_report(new_game().player_data)
    assert report.startswith("Health Check Results:\n\nOverall Limb Health: 100.0%\n\nLimb Status:\n- Head: 100% (Healthy)")
    assert "Other Damage:\n- Burn: 0.0% (Clear)\n- Poison: 0.0% (Clear)\n- Oxygen: 0.0% (Clear)" in report
    assert report.endswith("Recommendation: No immediate medical attention required.\n\nNo treatment needed.")
    assert "Detailed Notes" not in report and "Blood Alcohol" not in report
    assert "Estimated Treatment Cost" not in report


def test_a_scan_of_someone_badly_hurt_lists_every_problem_and_its_cost():
    player = hurt(new_game().player_data, head=30, chest=60, burn=20, oxygen=30, alcohol=30)
    report = build_health_check_report(player)
    for line in (
        "Overall Limb Health: 81.7%",
        "- Head: 30% (Critical)",
        "- Chest: 60% (Injured)",
        "Blood Alcohol: 30.0%\n• Intoxication is at or above 25%. Doctor treatment is required to sober up (30 credits).",
        "Recommendation: Medical attention recommended.",
        "• Critical damage detected in Head. Immediate treatment required.",
        "• Moderate trauma detected in Chest. Rest and treatment advised.",
        "• Non-limb damage detected: Burn, Oxygen.",
        "• Oxygen damage is at 30% (at or above 25%). You must be healed by the doctor to fully recover.",
        "• Some physical activities may be difficult.",
        "Estimated Treatment Cost:\n- Blunt: 110 pts × 1 = 110 credits\n- Burn: 20 pts × 3 = 60 credits\n"
        "- Oxygen: 30 pts × 2 = 60 credits\n- Sober up: 30 credits\nTotal: 260 credits\n(Talk to Doctor to receive treatment)",
    ):
        assert line in report, line


def test_a_scan_of_light_oxygen_damage_and_a_little_drink():
    report = build_health_check_report(hurt(new_game().player_data, oxygen=10, alcohol=10))
    assert "• Oxygen damage is at 10% (below 25%). You can rest to restore yourself while life support is functional." in report
    assert "• Alcohol will metabolize over time (about 5% every 2 minutes)." in report
    assert "Sober up" not in report


def test_a_scan_of_heavy_limb_damage_warns_about_movement():
    player = hurt(new_game().player_data, left_leg=0, right_leg=0, left_arm=50)
    report = build_health_check_report(player)
    assert "• Movement and performance significantly impaired." in report
    assert "Recommendation: Medical attention recommended." in report


def test_a_scan_of_a_minor_limb_injury():
    report = build_health_check_report(hurt(new_game().player_data, head=90))
    assert "Detailed Notes:" in report
    assert "Recommendation: Minor injuries only. Treatment is optional." in report
    assert "No immediate medical attention required." not in report
    assert "• Some physical activities may be difficult." not in report
    assert "- Head: 90% (Minor injuries)" in report and "Total: 10 credits" in report


def test_the_scan_room_action():
    game = in_medbay()
    game.perform("room.health_check", {})
    assert last_message(game) == ("Medical Scan", build_health_check_report(game.player_data))


def test_the_doctor_finds_nothing_wrong_with_a_healthy_patient():
    game = in_medbay()
    game.perform("room.talk_to_doctor", {})
    assert last_message(game) == ("Doctor", "The doctor examines you. 'You're in perfect health! No treatment needed.'")


def treat(game):
    game.perform("room.talk_to_doctor", {})
    choice = game.view()["choice"]
    choose(game, choice["buttons"][0])
    return choice


def test_paying_the_doctor_heals_everything_and_sobers_you_up():
    game = in_medbay()
    hurt(game.player_data, head=30, burn=20, alcohol=30)
    game.player_data["damage_timers"]["alcohol_decay_acc"] = 50.0
    choice = treat(game)
    assert choice["buttons"] == ["Yes (160 credits)", "No"]
    assert choice["message"].startswith("The doctor examines you.\n\nLimb Status:")
    assert "Blood Alcohol: 30.0%" in choice["message"]
    assert choice["message"].endswith("Total: 160 credits\n\nWould you like to proceed with treatment?")
    player = game.player_data
    assert (player["credits"], player["limbs"]["head"], player["damage"]["burn"], player["alcohol_percent"]) == (
        840, 100, 0, 0)
    assert player["damage_timers"]["alcohol_decay_acc"] == 0.0
    assert last_message(game) == ("Treatment Complete", "You pay 160 credits. The doctor treats you.\n\nHealed:\n"
                                  "- Blunt damage: Head\n- Other damage: Burn\n- Intoxication cleared (was 30.0%).\n"
                                  "\nYou feel much better now.")
    assert notes(game)[-1] == ("Paid 160 credits for medical treatment. Blunt Damage (Head) fully healed. "
                               "Other Damage (Burn) fully healed. Sobered up from 30.0% alcohol.")


def test_a_bill_that_changed_while_you_decided_names_both_prices():
    game = in_medbay()
    hurt(game.player_data, head=30, oxygen=20)
    game.perform("room.talk_to_doctor", {})
    choice = game.view()["choice"]
    game.player_data["damage"]["oxygen"] = 0
    choose(game, choice["buttons"][0])
    quoted = int(choice["buttons"][0].removeprefix("Yes (").removesuffix(" credits)"))
    charged = 1000 - game.player_data["credits"]
    assert charged < quoted
    assert last_message(game)[1].startswith(
        f"You pay {charged} credits (quoted {quoted}; your condition changed). The doctor treats you.")
    assert notes(game)[-1].startswith(
        f"Paid {charged} credits (quoted {quoted}; your condition changed) for medical treatment.")


def test_the_doctor_charges_for_injuries_without_sobering_a_light_drinker():
    game = in_medbay()
    hurt(game.player_data, poison=5, alcohol=10)
    treat(game)
    assert (game.player_data["credits"], game.player_data["alcohol_percent"]) == (990, 10)
    assert last_message(game)[1] == ("You pay 10 credits. The doctor treats you.\n\nHealed:\n- Other damage: Poison\n"
                                     "\nYou feel much better now.")


def test_sobering_up_alone():
    game = in_medbay()
    hurt(game.player_data, alcohol=40)
    treat(game)
    assert last_message(game)[1] == ("You pay 40 credits. The doctor treats you.\n\n"
                                     "- Intoxication cleared (was 40.0%).\n\nYou feel much better now.")
    assert notes(game)[-1] == "Paid 40 credits for medical treatment. Sobered up from 40.0% alcohol."


def test_treatment_needs_the_credits():
    game = in_medbay()
    hurt(game.player_data, head=0)
    game.player_data["credits"] = 50
    treat(game)
    assert last_message(game) == ("Doctor", "You don't have enough credits for treatment. Come back when you can afford it.")
    assert game.player_data["limbs"]["head"] == 0


def test_the_doctor_charges_for_how_you_are_when_you_say_yes():
    game = in_medbay()
    hurt(game.player_data, head=90)
    game.perform("room.talk_to_doctor", {})
    game.player_data["limbs"]["head"] = 100
    choose(game, "Yes (10 credits)")
    assert last_message(game) == ("Doctor", "The doctor examines you. 'You're in perfect health! No treatment needed.'")
    assert game.player_data["credits"] == 1000


def test_no_doctor_no_treatment():
    game = in_medbay()
    away = crew(game, "Doctor")
    away.update(on_duty=False, location={"x": 2, "y": 5})
    assert buttons(game)[1:] == [("The doctor is currently away from MedBay.", None),
                                 (f"Call {away['name']}", "room.call_npc")]
    game.perform("room.talk_to_doctor", {})
    assert game._messages == [] and game.ui["choices"] == []


def test_visitors_get_no_station():
    game = in_medbay()
    open_station(game, "medbay_station", "heal_player")
    game.perform("room.show_crew_vitals", {})
    assert game.ui["panels"] == []
    assert buttons(game)[0] == ("Request Health Check", "room.health_check")


def test_nobody_to_see_when_no_one_is_the_doctor():
    game = in_medbay("Administration", "Head of Personnel")
    game.ui["room_mode"] = "options"
    assert buttons(game) == [("Request Health Check", "room.health_check"), ("Back to Station Menu", "room.set_mode")]


def test_the_doctor_heals_all_their_own_injuries_at_the_station():
    game = in_medbay("Medical", "Doctor")
    hurt(game.player_data, head=40, burn=30, poison=12)
    game.ui["room_mode"] = "medbay_station"
    assert labels(game) == [
        f"Remedies in stock: {STARTING_REMEDIES}. Next one in {format_elapsed(CHEMISTRY_WORK_SECONDS)}.",
        "Heal Injuries", "Check Crew Vitals", "Back to Station Menu"]
    game.perform("room.heal_player", {})
    assert game.player_data["stores"]["remedies"] == STARTING_REMEDIES - 1
    assert game.player_data["limbs"]["head"] == 100
    assert game.player_data["damage"] == {"burn": 0, "poison": 0, "oxygen": 0}
    title, message = last_message(game)
    assert title == "Medical Treatment"
    assert all(line in message for line in ("- Head: 40% → 100%", "- Burn: 30% → 0%", "- Oxygen: 0% → 0%"))
    assert notes(game)[-1] == ("Received advanced medical treatment at MedBay Station. "
                               "Healed: Head (40% → 100%), Burn (30% → 0%), Poison (12% → 0%)")
    game.perform("room.heal_player", {})
    assert last_message(game) == ("Medical Treatment", "You have nothing that needs treating.")
    assert (len(notes(game)), game.player_data["stores"]["remedies"]) == (1, STARTING_REMEDIES - 1)


def test_every_treatment_uses_a_remedy_and_none_can_be_given_without_one():
    game = in_medbay("Medical", "Doctor")
    game.player_data["stores"]["remedies"] = 0
    hurt(game.player_data, head=40)
    patient = hurt(game.station_crew[0], head=40)
    credits = patient["credits"]
    open_station(game, "medbay_station", "heal_player")
    assert last_message(game) == ("Medical Treatment", OUT_OF_REMEDIES)
    crew_vitals(game)
    game.perform("panel.treat", {"name": patient["name"]})
    assert last_message(game) == ("Treatment", OUT_OF_REMEDIES)
    assert (game.player_data["limbs"]["head"], patient["limbs"]["head"], patient["credits"]) == (40, 40, credits)
    game.player_data["stores"]["remedies"] = 1
    game.perform("panel.treat", {"name": patient["name"]})
    assert (patient["limbs"]["head"], game.player_data["stores"]["remedies"]) == (100, 0)


def test_the_npc_doctor_cannot_treat_a_visitor_without_a_remedy():
    game = in_medbay()
    game.player_data["stores"]["remedies"] = 0
    hurt(game.player_data, head=80)
    treat(game)
    assert last_message(game) == ("Doctor", OUT_OF_REMEDIES)
    assert (game.player_data["credits"], game.player_data["limbs"]["head"]) == (1000, 80)
    game.player_data["stores"]["remedies"] = 2
    treat(game)
    assert (game.player_data["limbs"]["head"], game.player_data["stores"]["remedies"]) == (100, 1)


def test_the_crew_vitals_monitor():
    game = in_medbay("Medical", "Doctor")
    hurt(game.station_crew[0], head=10, chest=10, left_arm=10, burn=90)
    vitals = crew_vitals(game)
    assert (vitals["crew"][0]["name"], vitals["crew"][0]["is_player"], vitals["crew"][0]["status"]) == (
        "Ada", True, "Healthy")
    patient = vitals["crew"][1]
    assert (patient["status"], patient["status_color"]) == ("Critical", "red")
    assert patient["damage"][0] == {"icon": "🔥", "name": "Burn", "value": 90, "color": "red"}
    assert vitals["details"] is False
    game.perform("panel.toggle_details", {})
    assert ctx(game)["details"] is True
    assert reports(game) == []


def crew_vitals(game):
    return ctx(open_station(game, "medbay_station", "show_crew_vitals"))


def test_injured_crew_can_be_treated_and_pay_for_it():
    game = in_medbay("Medical", "Doctor")
    patient = hurt(game.station_crew[0], head=80, burn=10)
    rows = crew_vitals(game)["crew"]
    assert [row["can_treat"] for row in rows[:3]] == [False, True, False]
    credits, cost = patient["credits"], 20 + 10 * 3
    game.perform("panel.treat", {"name": patient["name"]})
    assert (patient["limbs"]["head"], patient["damage"]["burn"]) == (100, 0)
    assert (patient["credits"], game.player_data["credits"]) == (credits - cost, 7500 + cost)
    assert last_message(game) == ("Treatment", f"You treat {patient['name']}. They pay you {cost} credits.")
    assert notes(game)[-1] == f"Treated {patient['name']} for {cost} credits."


def test_a_patient_pays_only_what_they_have_and_healthy_or_missing_crew_need_nothing():
    game = in_medbay("Medical", "Doctor")
    patient = hurt(game.station_crew[0], head=0)
    patient["credits"] = 30
    crew_vitals(game)
    for name in (game.station_crew[1]["name"], "Nobody"):
        game.perform("panel.treat", {"name": name})
    assert game._messages == []
    game.perform("panel.treat", {"name": patient["name"]})
    assert (patient["credits"], game.player_data["credits"], patient["limbs"]["head"]) == (0, 7530, 100)


def test_treating_the_patient_from_a_duty_completes_it():
    game = in_medbay("Medical", "Doctor")
    patient = hurt(game.station_crew[1], chest=50)
    bystander = hurt(game.station_crew[0], chest=90)
    give_duty(game, kind="treat", room=MEDBAY_KEY, patient=patient["name"], summary="Treat them")
    crew_vitals(game)
    game.perform("panel.treat", {"name": bystander["name"]})
    assert len(game.player_data["duties"]) == 1
    game.perform("panel.treat", {"name": patient["name"]})
    assert game.player_data["duties"] == []
    assert last_message(game) == ("Duty Done", f"You treat {patient['name']}. They pay you 50 credits.")
    assert bystander["limbs"]["chest"] == 100


def test_nobody_labelled_healthy_can_be_treated_or_billed():
    game = in_medbay("Medical", "Doctor")
    hurt(game.station_crew[0], head=99)
    hurt(game.station_crew[1], poison=1)
    rows = crew_vitals(game)["crew"]
    assert [row["status"] for row in rows[1:3]] == ["Minor injuries", "Minor injuries"]
    assert [row["can_treat"] for row in rows[1:3]] == [True, True]
    for row, member in zip(rows[1:], game.station_crew):
        if row["status"] == "Healthy":
            assert not row["can_treat"] and assess_injuries(member)["total_cost"] == 0


def scientist(game, room_key=CHEMISTRY_KEY):
    return npc_movement.post_holder(game.station_crew, "Scientist", room_key)


def test_a_doctor_can_call_an_away_scientist_back_and_then_sees_when_the_next_remedy_comes(monkeypatch):
    game = in_medbay("Medical", "Doctor")
    game.ui["room_mode"] = "medbay_station"
    nobody_covers(game)
    away, researcher = scientist(game), scientist(game, RESEARCH_KEY)
    for npc in (away, researcher):
        npc.update(on_duty=False, location={"x": 2, "y": 5})
    assert buttons(game)[:3] == [(f"Remedies in stock: {STARTING_REMEDIES}.", None),
                                 ("The scientist is away from the Chemistry Lab.", None),
                                 (f"Call {away['name']}", "room.call_npc")]
    monkeypatch.setattr(npc_movement.random, "random", lambda: 0.0)
    game.perform("room.call_npc", {"job": "Scientist"})
    assert (away["on_duty"], researcher["on_duty"]) == (True, False)
    game.player_data["game_clock"]["elapsed_seconds"] = 30
    assert buttons(game)[0] == (f"Remedies in stock: {STARTING_REMEDIES}. Next one in "
                                f"{format_elapsed(CHEMISTRY_WORK_SECONDS - 30)}.", None)
    assert ("Call", "room.call_npc") not in [(label[:4], action) for label, action in buttons(game)]
