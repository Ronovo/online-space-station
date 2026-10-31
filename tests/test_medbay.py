from helpers import new_game, reports
from space_online.game.maps.donut import MEDBAY_KEY, location_from_key
from space_online.game.special_rooms.med_bay import build_health_check_report


def in_medbay(department="Civilian", job="Staff Assistant"):
    game = new_game(department, job)
    game.player_data["location"] = location_from_key(MEDBAY_KEY)
    return game


def doctor(game):
    return next(npc for npc in game.station_crew if npc["job"] == "Doctor")


def buttons(game):
    return [(w.get("label") or w.get("text"), w.get("action")) for w in game.view()["screen"]["buttons"]]


def last_message(game):
    return game._messages[-1][1:3]


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
    assert "Recommendation: No immediate medical attention required." in report
    assert "• Some physical activities may be difficult." not in report


def test_the_scan_room_action():
    game = in_medbay()
    game.perform("room.health_check", {})
    assert last_message(game)[0] == "Medical Scan"


def test_the_doctor_finds_nothing_wrong_with_a_healthy_patient():
    game = in_medbay()
    game.perform("room.talk_to_doctor", {})
    assert last_message(game) == ("Doctor", "The doctor examines you. 'You're in perfect health! No treatment needed.'")


def treat(game):
    game.perform("room.talk_to_doctor", {})
    choice = game.view()["choice"]
    game.perform("game.choose", {"id": choice["id"], "index": 0})
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


def test_the_treatment_note_reads_as_sentences():
    game = in_medbay()
    hurt(game.player_data, head=30, burn=20, alcohol=30)
    treat(game)
    assert game.player_data["notes"][-1]["text"] == (
        "Paid 160 credits for medical treatment. Blunt Damage (Head) fully healed. "
        "Other Damage (Burn) fully healed. Sobered up from 30.0% alcohol.")


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
    assert game.player_data["notes"][-1]["text"] == "Paid 40 credits for medical treatment. Sobered up from 40.0% alcohol."


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
    choice = game.view()["choice"]
    game.player_data["limbs"]["head"] = 100
    game.perform("game.choose", {"id": choice["id"], "index": 0})
    assert last_message(game) == ("Doctor", "The doctor examines you. 'You're in perfect health! No treatment needed.'")
    assert game.player_data["credits"] == 1000


def test_no_doctor_no_treatment():
    game = in_medbay()
    away = doctor(game)
    away.update(on_duty=False, location={"x": 2, "y": 5})
    assert buttons(game)[1:] == [("The doctor is currently away from MedBay.", None),
                                 (f"Call {away['name']}", "room.call_npc")]
    game.perform("room.talk_to_doctor", {})
    assert game._messages == [] and game.ui["choices"] == []


def test_visitors_get_no_station():
    game = in_medbay()
    game.ui["room_mode"] = "medbay_station"
    game.perform("room.heal_player", {})
    game.perform("room.show_crew_vitals", {})
    assert game.ui["panels"] == []
    assert buttons(game)[0] == ("Request Health Check", "room.health_check")


def test_nobody_to_see_when_no_one_is_the_doctor():
    game = in_medbay("Administration", "Head of Personnel")
    game.ui["room_mode"] = "options"
    assert buttons(game) == [("Request Health Check", "room.health_check"), ("Back to Station Menu", "room.set_mode")]


def test_the_doctor_heals_their_own_limbs_at_the_station():
    game = in_medbay("Medical", "Doctor")
    hurt(game.player_data, head=40, burn=30)
    game.ui["room_mode"] = "medbay_station"
    assert [label for label, _ in buttons(game)] == ["Heal Injuries", "Check Crew Vitals", "Back to Station Menu"]
    game.perform("room.heal_player", {})
    assert game.player_data["limbs"]["head"] == 100
    assert game.player_data["damage"]["burn"] == 30
    title, message = last_message(game)
    assert title == "Medical Treatment" and "- Head: 40% → 100%" in message
    assert game.player_data["notes"][-1]["text"] == ("Received advanced medical treatment at MedBay Station. "
                                                     "Healed: Head (40% → 100%)")
    game.perform("room.heal_player", {})
    assert len(game.player_data["notes"]) == 1


def test_the_crew_vitals_monitor():
    game = in_medbay("Medical", "Doctor")
    hurt(game.station_crew[0], head=10, chest=10, left_arm=10, burn=90)
    game.ui["room_mode"] = "medbay_station"
    game.perform("room.show_crew_vitals", {})
    ctx = game.view()["panel"]["ctx"]
    assert (ctx["crew"][0]["name"], ctx["crew"][0]["is_player"], ctx["crew"][0]["status"]) == ("Ada", True, "Healthy")
    patient = ctx["crew"][1]
    assert (patient["status"], patient["status_color"]) == ("Critical", "red")
    assert patient["damage"][0] == {"icon": "🔥", "name": "Burn", "value": 90, "color": "red"}
    assert ctx["details"] is False
    game.perform("panel.toggle_details", {})
    assert game.view()["panel"]["ctx"]["details"] is True
    assert reports(game) == []
