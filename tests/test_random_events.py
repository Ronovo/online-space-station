import pytest

from helpers import (
    board_shuttle,
    choose,
    crew,
    drain,
    duty,
    fix_random,
    give,
    give_duty,
    in_room,
    new_game,
    notes,
    stowaway,
)
from space_online.game.character_methods.character_creation import REQUESTABLE_JOBS
from space_online.game.helper_methods import random_events, rounds
from space_online.game.helper_methods.errands import DUTY_EXPIRY_SECONDS, MAX_OPEN_DUTIES, tick_duty_expiry
from space_online.game.helper_methods.hazards import HAZARD_ROOM_KEYS, set_hazard
from space_online.game.helper_methods.jail import is_jailed
from space_online.game.helper_methods.random_events import (
    EVENT_CATEGORIES,
    SOLAR_TRIP_COOLDOWN_SECONDS,
    build_job_event,
)
from space_online.game.helper_methods.jail import LAW_ABIDING_JOBS, PETTY_CRIMES, set_warrant
from space_online.game.helper_methods.power_constants import (
    FAULTABLE_SYSTEMS,
    LOW_POWER_SYSTEM_LEVELS,
    fault_system,
)
from space_online.game.helper_methods.rounds import (
    FLIGHT_EVENT_RANGE_SECONDS,
    JOB_EVENT_INTERVAL_RANGE,
    SHUTTLE_TRANSIT_SECONDS,
    tick_round,
)
from space_online.game.maps.donut import (
    BAR_KEY,
    BOTANY_KEY,
    BRIDGE_KEY,
    DEPARTURES_KEY,
    MEDBAY_KEY,
    ROOMS,
    location_from_key,
)
from space_online.game.objects.botany_items import GROWTH_CLASS_SECONDS, GROWTH_STAGES, planted_from_seed
from space_online.game.objects.chemicals import STORE_REMEDY_IDS
from space_online.game.objects.drinks import COFFEE_RECIPES, MIXED_DRINKS, drink_item
from space_online.game.objects.items import ALL_ITEMS, add_to_inventory, get_item_definition
from space_online.game.special_rooms import bridge
from space_online.game.special_rooms.bridge import LOCKDOWN_DOOR_KEYS

CATEGORY = {event["title"]: event["type"] for event in random_events._static_events(None)}


def by_title(title, pick):
    """A random.choice that takes the event called title from a list of events and sends every other pick to pick."""
    def choice(options):
        options = list(options)
        if options and all(isinstance(option, dict) and "effect" in option for option in options):
            return next(option for option in options if option["title"] == title)
        return pick(options)
    return choice


def prefer(wanted):
    """A pick that takes wanted when it is offered, and the first option otherwise."""
    return lambda options: wanted if wanted in options else options[0]


def recorder(answer=lambda options: options[0]):
    """A stand-in for random.choice, or random.randint, that answers with answer and keeps what each call was
    offered in its offered list."""
    def pick(*offered):
        pick.offered.append(list(offered[0]) if len(offered) == 1 else offered)
        return answer(*offered)
    pick.offered = []
    return pick


def said(lines, title=None):
    """The messages of these drained log lines, only those titled title when one is given."""
    return [line["message"] for line in lines if title in (None, line["title"])]


def jail_crew(game, sparing=()):
    """Jail every crew member whose job is not in sparing, and free the rest."""
    for npc in game.station_crew:
        npc["in_jail"] = npc["job"] not in sparing


def happen(monkeypatch, game, title, pick=lambda options: options[0], randint=lambda low, high: high):
    """Make the hallway or job event called title happen; every other random pick goes through pick and randint."""
    category = CATEGORY.get(title)
    pick_event = by_title(title, pick)

    def choice(options):
        options = list(options)
        if options and all(option in EVENT_CATEGORIES for option in options):
            return category
        return pick_event(options)

    fix_random(monkeypatch, random_events, pick=choice, randint=randint)
    if category:
        random_events.maybe_trigger_hallway_event(game)
    else:
        game.player_data["round"]["next_job_event_at"] = 0
        random_events.tick_job_events(game)
    alerts = drain(game)
    assert [alert["title"] for alert in alerts] == [title]
    return alerts[0]["message"]


def test_most_steps_have_no_event(monkeypatch):
    game = new_game()
    monkeypatch.setattr(random_events.random, "random", lambda: random_events.HALLWAY_EVENT_CHANCE)
    random_events.maybe_trigger_hallway_event(game)
    assert drain(game) == []


def test_found_credits(monkeypatch):
    game = new_game()
    message = happen(monkeypatch, game, "Found Credits")
    assert message == "You found some credits on the floor!\n\nYou gained 200 credits."
    assert game.player_data["credits"] == 1200
    assert notes(game) == ["Found 200 credits. New balance: 1200 credits."]
    assert game.event_messages is None


def test_a_supply_crate_leaves_its_item_on_the_floor_to_pick_up(monkeypatch):
    game = new_game()
    first = next(iter(ALL_ITEMS))
    message = happen(monkeypatch, game, "Supply Crate")
    assert message.endswith(f"You found {ALL_ITEMS[first]['name']}. It's on the floor here.")
    assert ([item["id"] for item in game.floor_here()], game.player_data["inventory"]) == ([first], [])
    game.perform("game.pick_up", {"index": 0})
    assert ([item["id"] for item in game.player_data["inventory"]], game.floor_here()) == ([first], [])


def test_a_market_tip(monkeypatch):
    game = new_game()
    message = happen(monkeypatch, game, "Market Tip")
    tips = [f"Overheard in the hall: {item['text']}." for item in game.market_engine.news]
    assert message.removeprefix("You overheard a market tip.\n\n") in tips
    assert notes(game)[-1].removeprefix("Market Tip: ") in tips


def test_a_market_tip_with_no_news_to_pin_it_on(monkeypatch):
    game = new_game()
    game.market_engine.news = []
    message = happen(monkeypatch, game, "Market Tip")
    assert message.endswith("You heard a stock tip, but there is no market news to pin it on.")
    assert notes(game) == []


@pytest.mark.parametrize("title", ["Lost Tourist", "Recycled Air Whiff", "Graffiti Tag"])
def test_flavour_events_change_nothing(monkeypatch, title):
    game = new_game()
    message = happen(monkeypatch, game, title)
    assert "\n\n" not in message
    assert (game.player_data["credits"], notes(game)) == (1000, [])


def test_a_station_announcement(monkeypatch):
    game = new_game()
    message = happen(monkeypatch, game, "Announcement")
    assert message.endswith("The PA system crackles: 'Reminder to all crew: safety protocols must be followed at all "
                            "times.'")


def test_with_the_communication_array_off_the_pa_gives_only_static(monkeypatch):
    game = new_game()
    game.player_data["station_power"]["system_levels"]["communication_array"] = 0
    message = happen(monkeypatch, game, "Announcement")
    assert message.endswith("The PA speakers crackle, but only static comes through.")
    assert "Reminder" not in message


def test_a_maintenance_bot(monkeypatch):
    message = happen(monkeypatch, new_game(), "Bot Moves By", pick=prefer("maintenance"))
    assert message.endswith("A maintenance bot rolls past, scrubbing the floor as it goes.")


def test_a_security_bot_passes_an_honest_player(monkeypatch):
    game = new_game()
    message = happen(monkeypatch, game, "Bot Moves By", pick=prefer("security"))
    assert message.endswith("A security bot scans you briefly and continues on its patrol.")


def test_a_security_bot_arrests_a_wanted_player(monkeypatch):
    game = new_game()
    game.player_data.update(warrant=True, warrant_reason="Smuggling")
    message = happen(monkeypatch, game, "Bot Moves By", pick=prefer("security"))
    assert message.endswith("A security bot locks onto you. You are wanted, and you are under arrest!\n"
                            "Charge: Smuggling")
    assert is_jailed(game.player_data)


def test_a_medical_bot_with_nothing_to_treat(monkeypatch):
    message = happen(monkeypatch, new_game(), "Bot Moves By", pick=prefer("medical"))
    assert message.endswith("A medical bot stops beside you and runs a quick diagnostic.\n"
                            "A medical bot scans you, finds nothing to treat, and rolls away.")


def test_a_medical_bot_heals_a_limb(monkeypatch):
    game = new_game()
    game.player_data["limbs"]["head"] = 50
    message = happen(monkeypatch, game, "Bot Moves By", pick=prefer("medical"))
    assert message.endswith("Your Head was healed by 5% and is now at 55%.")
    assert notes(game) == ["Medical bot healed Head: +5% (from 50% to 55%)"]


def test_a_medical_bot_treats_damage(monkeypatch):
    game = new_game()
    game.player_data["damage"]["poison"] = 3
    message = happen(monkeypatch, game, "Bot Moves By",
                     pick=lambda options: "medical" if "medical" in options else options[-1])
    assert message.endswith("Your poison damage was reduced by 3% (now 0%).")
    assert notes(game) == ["Medical bot treated poison damage: -3% (from 3% to 0%)"]


def test_a_vending_machine_spits_at_you(monkeypatch):
    game = new_game()
    message = happen(monkeypatch, game, "Vending Machine Malfunction", pick=prefer("spit_out"))
    assert message.endswith("The machine violently spits something out at you!\n"
                            "Your Head took 5% damage and is now at 95%.")


@pytest.mark.parametrize("outcome, ending", [
    ("stuck", "You see a snack stuck against the glass, just out of reach."),
    ("free_snack", "The machine clunks and a free snack drops into the tray.\n"
                   "A free Snack drops into the tray. It's on the floor here."),
])
def test_a_vending_machine_sticks_or_pays_out(monkeypatch, outcome, ending):
    game = new_game()
    message = happen(monkeypatch, game, "Vending Machine Malfunction", pick=prefer(outcome))
    assert message.endswith(ending)
    assert game.player_data["inventory"] == []
    assert [item["id"] for item in game.floor_here()] == (["snack"] if outcome == "free_snack" else [])


def test_lost_credits_and_a_bumped_head(monkeypatch):
    game = new_game()
    message = happen(monkeypatch, game, "Lost Credits")
    assert message.endswith("\n\nYou lost 50 credits.\nYour Head took 10% damage and is now at 90%.")
    assert game.player_data["credits"] == 950


def test_losing_more_credits_than_you_carry_reports_what_you_lost(monkeypatch):
    game = new_game()
    game.player_data["credits"] = 20
    message = happen(monkeypatch, game, "Lost Credits")
    assert game.player_data["credits"] == 0
    assert "You lost 20 credits." in message


@pytest.mark.parametrize("title, limbs, damage", [
    ("Small Explosion", {"head": 75}, {"burn": 15}),
    ("Slip and Fall", {"head": 80}, {}),
    ("Steam Leak", {"left_arm": 90}, {"burn": 30}),
    ("Falling Debris", {"head": 65}, {}),
    ("Maintenance Accident", {"right_leg": 80}, {}),
    ("Chemical Spill", {"left_leg": 90}, {"burn": 15, "poison": 20}),
])
def test_bad_events_hurt(monkeypatch, title, limbs, damage):
    game = new_game()
    happen(monkeypatch, game, title)
    for limb, health in limbs.items():
        assert game.player_data["limbs"][limb] == health
    assert {key: value for key, value in game.player_data["damage"].items() if value} == damage


def test_a_steam_leak_scalds_an_arm_without_calling_it_blunt(monkeypatch):
    game = new_game()
    message = happen(monkeypatch, game, "Steam Leak")
    assert "Your Left Arm took 10% damage and is now at 90%." in message
    assert "blunt" not in message.lower()
    assert notes(game)[-2] == "Suffered damage to Left Arm: Took 10% damage (from 100% to 90%)"


def test_damage_tops_out_at_100(monkeypatch):
    game = new_game()
    game.player_data["damage"]["burn"] = 95
    message = happen(monkeypatch, game, "Steam Leak")
    assert game.player_data["damage"]["burn"] == 100
    assert message.endswith("You suffered 30% burn damage! Total burn damage: 100%.")


def test_effects_outside_an_event_report_on_their_own():
    game = new_game()
    random_events.add_credits(game, 5)
    assert drain(game) == [{"title": "Credits Added", "message": "You gained 5 credits.", "kind": "info"}]


def giver(job):
    """A pick that chooses the Staff Assistant errand offered by job, and the first of anything else."""
    return lambda options: next((o for o in options if isinstance(o, dict) and o.get("giver") == job), options[0])


def test_a_staff_assistant_is_sent_to_help_out(monkeypatch):
    game = new_game()
    message = happen(monkeypatch, game, "Job Request")
    assert message == "The Botanist needs water for the planters. Report to the Botany Lab for 75 credits."
    assert duty(game) == {
        "kind": "help", "giver": "Botanist", "room": BOTANY_KEY, "item": None, "label": "water the planters",
        "reward": 75, "summary": "Help the Botanist water the planters in the Botany Lab (75 cr)"}
    assert notes(game) == [message]


@pytest.mark.parametrize("job, item, label, room", [
    ("Doctor", "medkit", "a medkit", "MedBay"),
    ("Bartender", "tomato", "a tomato", "Bar"),
])
def test_a_staff_assistant_is_sent_to_deliver_something(monkeypatch, job, item, label, room):
    game = new_game()
    message = happen(monkeypatch, game, "Job Request", pick=giver(job))
    assert message.endswith(f"Bring {label} to the {room} for 75 credits.")
    errand = duty(game)
    assert (errand["kind"], errand["giver"], errand["item"], errand["label"]) == ("deliver", job, item, label)
    assert errand["summary"] == f"Bring {label} to the {job} in the {room} (75 cr)"


def test_errand_rewards_come_from_their_range(monkeypatch):
    game = new_game()
    randint = recorder(lambda low, high: low)
    happen(monkeypatch, game, "Job Request", randint=randint)
    assert (randint.offered[-1], duty(game)["reward"]) == ((25, 75), 25)


def test_errands_only_come_from_crew_who_are_aboard():
    game = new_game()
    game.player_data["station_crew"] = [npc for npc in game.station_crew if npc["job"] == "Staff Assistant"]
    assert build_job_event(game) is None


@pytest.mark.parametrize("department, job", [
    ("Civilian", "Staff Assistant"), ("Civilian", "Botanist"), ("Civilian", "Bartender"), ("Medical", "Doctor"),
    ("Administration", "Captain"),
])
def test_no_new_duty_while_the_board_is_full(department, job):
    game = new_game(department, job)
    add_to_inventory(game.player_data, get_item_definition("tomato"))
    for _ in range(MAX_OPEN_DUTIES - 1):
        give_duty(game, kind="help", room=BAR_KEY, summary="Busy")
    assert build_job_event(game) is not None
    give_duty(game, kind="help", room=BAR_KEY, summary="Busy")
    assert build_job_event(game) is None


def test_hallway_events_still_happen_while_the_board_is_full(monkeypatch):
    game = new_game()
    for _ in range(MAX_OPEN_DUTIES):
        give_duty(game, kind="help", room=BAR_KEY, summary="Busy")
    assert happen(monkeypatch, game, "Lost Tourist").startswith("A confused visitor")


def test_a_job_brings_its_next_event_on_the_clock_and_not_in_a_fight(monkeypatch):
    game = new_game()
    fix_random(monkeypatch, random_events, randint=lambda low, high: low)
    round_ = game.player_data["round"]
    round_["next_job_event_at"] = 100
    game.player_data["game_clock"]["elapsed_seconds"] = 99
    random_events.tick_job_events(game)
    assert game.player_data["duties"] == []
    game.player_data["game_clock"]["elapsed_seconds"] = 100
    random_events.tick_job_events(game)
    assert len(game.player_data["duties"]) == 1
    assert round_["next_job_event_at"] == 100 + JOB_EVENT_INTERVAL_RANGE[0]
    game.player_data.update(fight={"kind": "monster"})
    game.player_data["game_clock"]["elapsed_seconds"] = 1000
    random_events.tick_job_events(game)
    assert (len(game.player_data["duties"]), round_["next_job_event_at"]) == (1, 1000 + JOB_EVENT_INTERVAL_RANGE[0])


def test_hallway_events_never_bring_job_events(monkeypatch):
    game = new_game()
    pick = recorder()
    fix_random(monkeypatch, random_events, pick=pick, randint=lambda low, high: low)
    random_events.maybe_trigger_hallway_event(game)
    assert pick.offered[0] == ["good", "neutral", "bad"]
    assert game.player_data["duties"] == []


def test_an_engineer_finds_a_system_faulted(monkeypatch):
    game = new_game("Engineering", "Engineer")
    message = happen(monkeypatch, game, "System Fault", pick=prefer("fault"))
    assert message == ("A fault has shut down the Hallway Lighting. Repair it from the Engineering Panel "
                       "with Basic Tools or a Repair Tool.")
    power = game.player_data["station_power"]
    assert (power["faults"], power["system_levels"]["hallway_lighting"]) == (["hallway_lighting"], 0)
    assert notes(game) == ["The Hallway Lighting faulted and needs repairing."]


def fault_everything(game):
    for key in FAULTABLE_SYSTEMS:
        fault_system(game.player_data["station_power"], key)


def test_a_system_switched_off_does_not_fault(monkeypatch):
    game = new_game("Engineering", "Engineer")
    game.player_data["station_power"]["system_levels"]["hallway_lighting"] = 0
    pick = recorder(prefer("fault"))
    happen(monkeypatch, game, "System Fault", pick=pick)
    assert pick.offered[-1] == ["security_systems", "communication_array"]


def test_with_every_system_faulted_only_the_solar_array_fails(monkeypatch):
    game = new_game("Engineering", "Engineer")
    fault_everything(game)
    game.player_data["station_power"]["solar_charging"] = True
    happen(monkeypatch, game, "Solar Panels Offline", pick=prefer("fault"))


def test_solar_panels_already_down_are_not_reported_down_again(monkeypatch):
    game = new_game("Engineering", "Engineer")
    game.player_data["station_power"]["solar_charging"] = False
    happen(monkeypatch, game, "System Fault", pick=lambda o: o[0])


def test_an_engineer_with_nothing_left_to_go_wrong_gets_no_event():
    game = new_game("Engineering", "Engineer")
    fault_everything(game)
    game.player_data["station_power"]["solar_charging"] = False
    for key in HAZARD_ROOM_KEYS:
        set_hazard(game.player_data, key, "fire")
    assert build_job_event(game) is None


def botanist_holding(*produce):
    return give(new_game("Civilian", "Botanist"), *produce)


@pytest.mark.parametrize("pick, produce, wanted", [(lambda o: o[0], "apple", "an apple"),
                                                   (lambda o: o[-1], "tomato", "a tomato")])
def test_the_botanist_gets_a_crop_request(monkeypatch, pick, produce, wanted):
    game = botanist_holding("tomato", "apple")
    assert happen(monkeypatch, game, "Crop Request", pick=pick) == (
        f"The Bartender needs {wanted} from the botany lab. Deliver it to the Bar for 150 credits.")
    assert duty(game) == {
        "kind": "deliver", "giver": "Bartender", "room": BAR_KEY, "item": produce, "label": wanted, "reward": 150,
        "summary": f"Bring {wanted} to the Bartender in the Bar (150 cr)"}
    assert notes(game) == [f"Bartender requested {wanted} from botany for 150 credits."]


def test_crop_request_rewards_come_from_their_range(monkeypatch):
    game = botanist_holding("tomato")
    randint = recorder(lambda low, high: low)
    happen(monkeypatch, game, "Crop Request", randint=randint)
    assert (randint.offered[-1], duty(game)["reward"]) == ((50, 150), 50)


def test_the_botanist_gets_no_crop_request_with_no_bartender():
    game = botanist_holding("tomato")
    assert build_job_event(game) is not None
    assert build_job_event(without(game, "Bartender")) is None


def test_the_bartender_gets_a_drink_order(monkeypatch):
    game = new_game("Civilian", "Bartender")
    patron = game.station_crew[0]["name"]
    drink = next(iter(MIXED_DRINKS))
    price = MIXED_DRINKS[drink]["price"]
    message = happen(monkeypatch, game, "Drink Order")
    assert message == f"{patron} orders a {drink}. Mix one and serve it from the Bartender Station for {price} credits."
    assert duty(game) == {"kind": "serve", "room": BAR_KEY, "item": drink, "patron": patron,
                          "reward": price, "summary": f"Serve a {drink} to {patron} ({price} cr)"}
    assert notes(game) == [f"{patron} ordered a {drink} for {price} credits."]


def test_the_doctor_gets_a_patient(monkeypatch):
    game = new_game("Medical", "Doctor")
    patient = game.station_crew[0]
    message = happen(monkeypatch, game, "Patient")
    assert message == (f"{patient['name']} ({patient['job']}) hurt their head in an accident. "
                       "Treat them from Crew Vitals at the MedBay Station.")
    assert patient["limbs"]["head"] == 100 - 35
    assert duty(game) == {"kind": "treat", "room": MEDBAY_KEY, "patient": patient["name"],
                          "summary": f"Treat {patient['name']} from Crew Vitals"}
    assert notes(game) == [f"{patient['name']} was hurt and needs treatment."]


@pytest.mark.parametrize("department, job", [("Medical", "Doctor"), ("Civilian", "Bartender")])
def test_no_patients_or_patrons_when_the_whole_crew_is_jailed(department, job):
    game = new_game(department, job)
    jail_crew(game)
    assert build_job_event(game) is None


def test_a_guard_in_the_hallways_witnesses_a_crime_by_anyone_who_could_do_it(monkeypatch):
    game = new_game("Security", "Security Guard")
    game.player_data["location"] = {"x": 2, "y": 5}
    captain = crew(game, "Captain")
    culprit = next(npc for npc in game.station_crew if npc["job"] not in LAW_ABIDING_JOBS)
    charge = PETTY_CRIMES[0]
    assert happen(monkeypatch, game, "Witness a Crime") == (
        f"You witness a crime! {culprit['name']} is involved. A warrant is out for {charge.lower()}.")
    assert (culprit["warrant"], culprit["warrant_reason"], captain["warrant"]) == (True, charge, False)
    assert notes(game) == [f"Witnessed {culprit['name']} committing {charge.lower()}. A warrant has been issued."]
    for npc in game.station_crew:
        if npc["job"] not in LAW_ABIDING_JOBS:
            set_warrant(npc, charge)
    assert happen(monkeypatch, game, "Witness a Crime") == "You witness a crime! You do not catch who it is."
    assert notes(game)[-1] == "Witnessed a crime; perpetrator unidentified."


def test_a_guard_inside_a_room_witnesses_nothing():
    assert build_job_event(in_room(BAR_KEY, "Security", "Security Guard")) is None


def command_request(monkeypatch, game, request, pick=None):
    """Make a Command Request of the given kind come in. Returns its log line and the duty it put on the board."""
    message = happen(monkeypatch, game, "Command Request", pick=pick or prefer(request))
    return message, game.player_data["duties"][-1]


def answer(game, duty, approve=True):
    game.open_panel("duties")
    game.perform("panel.approve_request" if approve else "panel.deny_request", {"duty_id": duty["id"]})


def test_a_command_request_waits_on_the_duties_board_with_no_pop_up(monkeypatch):
    game = new_game("Administration", "Captain")
    game.player_data["station_power"]["system_levels"]["life_support"] = 4
    _, request = command_request(monkeypatch, game, "life_support")
    assert game.view()["choice"] is None
    game.open_panel("duties")
    shown = game.view()["panel"]["ctx"]["duties"]
    assert [(entry["summary"], entry["answer"]) for entry in shown] == [
        ("Engineering needs approval to divert power to life support", True)]
    for action in ("approve_request", "deny_request"):
        game.perform(f"panel.{action}", {"duty_id": "not-a-duty"})
    assert game.player_data["duties"] == [request]


def test_approving_a_command_request_to_power_life_support(monkeypatch):
    game = new_game("Administration", "Captain")
    game.player_data["station_power"]["system_levels"]["life_support"] = 4
    message, request = command_request(monkeypatch, game, "life_support")
    assert message == "Command request: Engineering needs approval to divert power to life support."
    answer(game, request)
    assert game.player_data["station_power"]["system_levels"]["life_support"] == 10
    assert drain(game)[-1]["message"] == "Approved. Life support is now at full power."
    assert notes(game)[-1] == ("Approved: Engineering needs approval to divert power to life support. "
                               "Life support is now at full power.")
    assert (game.player_data["duties"], game.player_data["round"]["duties_done"]) == ([], 1)


def test_denying_a_command_request_changes_nothing(monkeypatch):
    game = new_game("Administration", "Captain")
    _, request = command_request(monkeypatch, game, "power_saving")
    answer(game, request, approve=False)
    assert game.player_data["station_power"]["power_mode"] == "balanced"
    assert notes(game)[-1] == "Denied: Engineering requests permission to switch the station to Power Saving mode."
    assert said(drain(game), "Command Request") == [
        "Denied. Engineering requests permission to switch the station to Power Saving mode."]
    assert (game.player_data["duties"], game.player_data["round"]["duties_done"]) == ([], 1)


def test_approving_power_saving_says_what_it_changed(monkeypatch):
    game = new_game("Administration", "Captain")
    game.player_data["station_power"]["system_levels"].update(life_support=0, security_systems=5)
    _, request = command_request(monkeypatch, game, "power_saving")
    answer(game, request)
    power = game.player_data["station_power"]
    assert (power["power_mode"], power["system_levels"]) == ("low", LOW_POWER_SYSTEM_LEVELS)
    changes = "Life Support 0 to 7, Hallway Lighting 6 to 3, Communication Array 5 to 2."
    assert said(drain(game), "Command Request") == [f"Approved. The station is now in Power Saving mode. {changes}"]
    assert notes(game)[-1].endswith(f"The station is now in Power Saving mode. {changes}")


def test_approving_power_saving_with_the_levels_already_set_to_it_lists_no_change(monkeypatch):
    game = new_game("Administration", "Captain")
    game.player_data["station_power"]["system_levels"].update(LOW_POWER_SYSTEM_LEVELS)
    _, request = command_request(monkeypatch, game, "power_saving")
    answer(game, request)
    assert said(drain(game), "Command Request") == ["Approved. The station is now in Power Saving mode."]


def test_a_lockdown_request_names_its_room_and_approving_locks_that_room(monkeypatch):
    game = new_game("Administration", "Captain")
    for key in LOCKDOWN_DOOR_KEYS[1:]:
        game.ship_map[key]["locked"] = True
    message, request = command_request(monkeypatch, game, "lockdown")
    assert message == "Command request: Security requests permission to lock down the MedBay."
    answer(game, request)
    assert game.ship_map[MEDBAY_KEY]["locked"] and not game.ship_map[BRIDGE_KEY]["locked"]
    assert drain(game)[-1]["message"] == "Approved. The MedBay door is now locked."


def test_a_lockdown_of_a_door_locked_since_says_so_and_locks_nothing_else(monkeypatch):
    game = new_game("Administration", "Captain")
    _, request = command_request(monkeypatch, game, "lockdown")
    room = request["door"]
    game.ship_map[room]["locked"] = True
    unlocked = [key for key in LOCKDOWN_DOOR_KEYS if not game.ship_map[key]["locked"]]
    answer(game, request)
    assert drain(game)[-1]["message"] == f"Approved. The {ROOMS[room].name} door is already locked."
    assert unlocked == [key for key in LOCKDOWN_DOOR_KEYS if not game.ship_map[key]["locked"]]


def test_approving_a_warrant_request(monkeypatch):
    game = new_game("Administration", "Captain")
    suspect = next(npc for npc in game.station_crew if npc["job"] not in LAW_ABIDING_JOBS)
    message, request = command_request(monkeypatch, game, "warrant")
    assert message == f"Command request: Security requests a warrant for {suspect['name']} on suspicion of smuggling."
    answer(game, request)
    assert (suspect["warrant"], suspect["warrant_reason"]) == (True, "Suspected smuggling")
    assert drain(game)[-1]["message"] == f"Approved. A warrant has been issued for {suspect['name']}."


def test_a_warrant_for_someone_wanted_since_or_gone_is_not_issued(monkeypatch):
    game = new_game("Administration", "Captain")
    _, first = command_request(monkeypatch, game, "warrant")
    suspect = next(npc for npc in game.station_crew if npc["name"] == first["suspect"])
    set_warrant(suspect, "Brawling")
    answer(game, first)
    lines = drain(game)
    _, second = command_request(monkeypatch, game, "warrant",
                                pick=lambda options: "warrant" if "warrant" in options else options[-1])
    gone = next(npc for npc in game.station_crew if npc["name"] == second["suspect"])
    game.station_crew.remove(gone)
    answer(game, second)
    lines += drain(game)
    assert suspect["warrant_reason"] == "Brawling"
    assert said(lines, "Command Request") == [
        f"Approved. {suspect['name']} is no longer a suspect.", f"Approved. {gone['name']} is no longer a suspect."]


def test_a_command_request_already_on_the_board_is_not_asked_again_until_it_is_answered(monkeypatch):
    game = new_game("Administration", "Captain")
    _, first = command_request(monkeypatch, game, "power_saving")
    pick = recorder()
    _, second = command_request(monkeypatch, game, "lockdown", pick=pick)
    assert "power_saving" not in pick.offered[0] and second["request"] != "power_saving"
    answer(game, first, approve=False)
    answer(game, second, approve=False)
    drain(game)
    pick = recorder()
    command_request(monkeypatch, game, "lockdown", pick=pick)
    assert "power_saving" in pick.offered[0]


def test_a_missed_command_request_ends_in_one_period(monkeypatch):
    game = new_game("Administration", "Captain")
    _, request = command_request(monkeypatch, game, "power_saving")
    game.player_data["game_clock"]["elapsed_seconds"] = request["expires_at"]
    tick_duty_expiry(game)
    assert drain(game)[-1]["message"] == ("You ran out of time: Engineering requests permission to switch the station "
                                          "to Power Saving mode.")
    assert (game.player_data["duties"], game.player_data["round"]["duties_missed"]) == ([], 1)


def test_no_warrant_request_without_a_suspect(monkeypatch):
    game = new_game("Administration", "Captain")
    jail_crew(game, sparing=LAW_ABIDING_JOBS)
    pick = recorder()
    happen(monkeypatch, game, "Command Request", pick=pick)
    assert pick.offered[0] == ["lockdown", "power_saving"]


def test_the_hop_gets_an_access_request_from_the_crew(monkeypatch):
    game = new_game("Administration", "Head of Personnel")
    requester = next(npc for npc in game.station_crew if npc["job"] != "Captain")
    message = happen(monkeypatch, game, "Access Request")
    assert message.startswith(f"{requester['name']} ({requester['job']}) has submitted an access request to become ")
    assert game.player_data["access_request"]["requester_name"] == requester["name"]


def test_the_captain_never_asks_the_hop_for_another_job(monkeypatch):
    game = new_game("Administration", "Head of Personnel")
    pick = recorder()
    happen(monkeypatch, game, "Access Request", pick=pick)
    assert all(npc["job"] != "Captain" for npc in pick.offered[0])
    assert any(npc["job"] == "Captain" for npc in game.station_crew)


def test_the_hop_gets_no_new_request_while_one_waits_or_nobody_is_free():
    game = new_game("Administration", "Head of Personnel")
    game.player_data["access_request"] = {"requested_job": "Doctor", "requester_name": "Someone"}
    assert build_job_event(game) is None
    del game.player_data["access_request"]
    jail_crew(game)
    assert build_job_event(game) is None


def test_nobody_asks_the_hop_for_the_job_they_already_hold(monkeypatch):
    game = new_game("Administration", "Head of Personnel")
    pick = recorder()
    happen(monkeypatch, game, "Access Request", pick=pick)
    requester, jobs = pick.offered[0][0], pick.offered[1]
    assert requester["job"] not in jobs and len(jobs) == len(REQUESTABLE_JOBS) - 1


def errands_offered(monkeypatch, game):
    pick = recorder()
    happen(monkeypatch, game, "Job Request", pick=pick)
    return [errand.get("item") for errand in pick.offered[0]]


def test_the_doctor_only_asks_a_staff_assistant_for_a_medkit_they_have(monkeypatch):
    game = new_game()
    locker = game.player_data["locker_inventory"]
    assert "medkit" in errands_offered(monkeypatch, game)
    game.player_data["locker_inventory"] = [item for item in locker if item.get("id") != "medkit"]
    assert "medkit" not in errands_offered(monkeypatch, game)
    add_to_inventory(game.player_data, get_item_definition("medkit"))
    assert "medkit" in errands_offered(monkeypatch, game)


@pytest.mark.parametrize("state, comes", [("idle", True), ("called", True), ("docked", False), ("transit", False)])
def test_no_job_event_once_the_shuttle_has_docked(monkeypatch, state, comes):
    game = new_game()
    fix_random(monkeypatch, random_events, randint=lambda low, high: low)
    round_ = game.player_data["round"]
    round_["shuttle"]["state"] = state
    round_["next_job_event_at"] = 0
    random_events.tick_job_events(game)
    assert (bool(game.player_data["duties"]), round_["next_job_event_at"]) == (comes, JOB_EVENT_INTERVAL_RANGE[0])


def captain_requests(monkeypatch, game):
    """The Command Requests the Captain could be sent right now."""
    pick = recorder()
    fix_random(monkeypatch, random_events, pick=pick, randint=lambda low, high: low)
    event = build_job_event(game)
    return pick.offered[0] if event else []


def without(game, job):
    game.player_data["station_crew"] = [npc for npc in game.station_crew if npc["job"] != job]
    return game


def test_life_support_is_only_asked_for_when_it_is_low_and_an_engineer_is_aboard(monkeypatch):
    game = new_game("Administration", "Captain")
    assert "life_support" not in captain_requests(monkeypatch, game)
    game.player_data["station_power"]["system_levels"]["life_support"] = 4
    assert "life_support" in captain_requests(monkeypatch, game)
    assert "life_support" not in captain_requests(monkeypatch, without(game, "Engineer"))


def test_power_saving_is_only_asked_for_once_and_with_an_engineer_aboard(monkeypatch):
    game = new_game("Administration", "Captain")
    assert "power_saving" in captain_requests(monkeypatch, game)
    game.player_data["station_power"]["power_mode"] = "low"
    assert "power_saving" not in captain_requests(monkeypatch, game)
    game.player_data["station_power"]["power_mode"] = "balanced"
    assert "power_saving" not in captain_requests(monkeypatch, without(game, "Engineer"))


def test_a_lockdown_is_only_asked_for_with_a_door_left_to_lock_and_a_guard_aboard(monkeypatch):
    game = new_game("Administration", "Captain")
    assert "lockdown" in captain_requests(monkeypatch, game)
    for key in LOCKDOWN_DOOR_KEYS:
        game.ship_map[key]["locked"] = True
    assert "lockdown" not in captain_requests(monkeypatch, game)
    game.ship_map[MEDBAY_KEY]["locked"] = False
    assert "lockdown" not in captain_requests(monkeypatch, without(game, "Security Guard"))


def test_no_command_request_when_none_makes_sense(monkeypatch):
    game = without(without(new_game("Administration", "Captain"), "Engineer"), "Security Guard")
    jail_crew(game, sparing=LAW_ABIDING_JOBS)
    assert captain_requests(monkeypatch, game) == []
    assert build_job_event(game) is None


def test_no_crop_request_with_nothing_in_hand_or_growing():
    game = new_game("Civilian", "Botanist")
    planters = game.player_data["botany"]["planters"]
    planters[0].update(planted_from_seed(get_item_definition("tomato_seeds"), 0), tended_by="npc")
    planters[1].update(planted_from_seed(get_item_definition("potato_seeds"), 0), dead=True)
    planters[2].update(planted_from_seed(get_item_definition("aloe_seeds"), 0))
    assert build_job_event(game) is None


def test_a_crop_request_for_produce_in_hand_runs_out_as_usual(monkeypatch):
    game = botanist_holding("carrot")
    happen(monkeypatch, game, "Crop Request")
    assert (duty(game)["item"], game.player_data["duties"][0]["expires_at"]) == ("carrot", DUTY_EXPIRY_SECONDS)


def test_a_crop_request_for_a_growing_plant_lasts_until_it_is_ripe_and_then_as_usual(monkeypatch):
    game = new_game("Civilian", "Botanist")
    planter = game.player_data["botany"]["planters"][0]
    planter.update(planted_from_seed(get_item_definition("apple_seeds"), 0), watered=True)
    stage = GROWTH_CLASS_SECONDS["tree"]
    game.player_data["game_clock"]["elapsed_seconds"] = 100
    happen(monkeypatch, game, "Crop Request")
    ripe_at = (GROWTH_STAGES - 1) * stage
    assert (duty(game)["item"], game.player_data["duties"][0]["expires_at"]) == (
        "apple", ripe_at + DUTY_EXPIRY_SECONDS)


def test_a_crop_request_for_a_ripe_plant_runs_out_as_usual(monkeypatch):
    game = new_game("Civilian", "Botanist")
    planter = game.player_data["botany"]["planters"][0]
    planter.update(planted_from_seed(get_item_definition("potato_seeds"), 0), growth_stage=GROWTH_STAGES)
    game.player_data["game_clock"]["elapsed_seconds"] = GROWTH_STAGES * GROWTH_CLASS_SECONDS["crop"]
    happen(monkeypatch, game, "Crop Request")
    assert game.player_data["duties"][0]["expires_at"] == (
        GROWTH_STAGES * GROWTH_CLASS_SECONDS["crop"] + DUTY_EXPIRY_SECONDS)


def test_the_solar_array_trips_at_most_once_in_its_cooldown(monkeypatch):
    game = new_game("Engineering", "Engineer")
    power = game.player_data["station_power"]
    pick = recorder()
    power["solar_charging"] = True
    happen(monkeypatch, game, "Solar Panels Offline", pick=pick)
    assert (power["solar_charging"], power["solar_tripped_at"]) == (False, 0)
    power["solar_charging"] = True
    game.player_data["game_clock"]["elapsed_seconds"] = SOLAR_TRIP_COOLDOWN_SECONDS - 1
    happen(monkeypatch, game, "System Fault", pick=pick)
    assert pick.offered[1] == ["fault"]
    game.player_data["game_clock"]["elapsed_seconds"] = SOLAR_TRIP_COOLDOWN_SECONDS
    assert happen(monkeypatch, game, "Solar Panels Offline", pick=pick).startswith("The solar panels have shut down")


# --- The in-flight event -----------------------------------------------------------

def flying(strapped=True, seat=0):
    """A game in its shuttle's flight, with the first seat crew members aboard, unhurt and nothing logged yet."""
    game = board_shuttle(new_game())
    for npc in game.station_crew[:seat]:
        npc["location"] = location_from_key(DEPARTURES_KEY)
    game.player_data["round"]["strapped"] = strapped
    game.player_data["game_clock"]["elapsed_seconds"] = game.player_data["round"]["shuttle"]["until"]
    tick_round(game)
    game.player_data["limbs"] = {limb: 100 for limb in game.player_data["limbs"]}
    drain(game)
    return game


def in_flight(monkeypatch, game, title, pick=lambda options: options[0], roll=0.0):
    """Make the in-flight event called title happen; every other random pick goes through pick and roll."""
    fix_random(monkeypatch, random_events, roll=roll, pick=by_title(title, pick))
    game.player_data["game_clock"]["elapsed_seconds"] = game.player_data["round"]["flight_event_at"]
    random_events.tick_flight_event(game)
    return drain(game)


def test_one_thing_happens_on_the_flight_at_a_time_picked_as_the_shuttle_leaves():
    game = flying()
    round_ = game.player_data["round"]
    departed = round_["shuttle"]["until"] - SHUTTLE_TRANSIT_SECONDS
    low, high = FLIGHT_EVENT_RANGE_SECONDS
    assert departed + low <= round_["flight_event_at"] <= departed + high
    game.player_data["game_clock"]["elapsed_seconds"] = round_["flight_event_at"] - 1
    random_events.tick_flight_event(game)
    assert drain(game) == []
    game.player_data["game_clock"]["elapsed_seconds"] = round_["flight_event_at"]
    random_events.tick_flight_event(game)
    assert len(drain(game)) == 1
    assert round_["flight_event_at"] is None
    random_events.tick_flight_event(game)
    assert drain(game) == []


def test_nothing_happens_on_the_flight_while_the_shuttle_is_docked():
    game = board_shuttle(new_game())
    drain(game)
    assert game.player_data["round"]["flight_event_at"] is None
    random_events.tick_flight_event(game)
    assert drain(game) == []


def test_a_fight_aboard_takes_the_place_of_the_flight_event(monkeypatch):
    game = flying()
    stowaway(game)
    game.player_data["game_clock"]["elapsed_seconds"] = 10 ** 6
    random_events.tick_flight_event(game)
    assert (game.player_data["round"]["flight_event_at"], drain(game)) == (None, [])

    monkeypatch.setattr(rounds, "DEPARTURE_HOOKS", [stowaway])
    assert flying().player_data["round"]["flight_event_at"] is None


def coffee(game):
    add_to_inventory(game.player_data, drink_item("Coffee", COFFEE_RECIPES["Coffee"]))


def test_turbulence_spares_a_player_who_is_strapped_in(monkeypatch):
    game = flying()
    coffee(game)
    assert said(in_flight(monkeypatch, game, "Turbulence")) == [
        "The shuttle bucks and drops through a patch of turbulence.\n\nYou are held fast and ride it out."]
    assert (set(game.player_data["limbs"].values()), len(game.player_data["inventory"])) == ({100}, 1)


@pytest.mark.parametrize("carrying, spilled", [(True, "\nYour coffee goes everywhere."), (False, "")])
def test_turbulence_throws_a_player_who_is_up_and_spills_their_coffee(monkeypatch, carrying, spilled):
    game = flying(strapped=False)
    if carrying:
        coffee(game)
    assert said(in_flight(monkeypatch, game, "Turbulence")) == [
        "The shuttle bucks and drops through a patch of turbulence.\n\nYour Head took 15% damage and is now "
        f"at 85%.{spilled}"]
    assert game.player_data["inventory"] == []


def test_giving_a_crew_member_taken_ill_the_remedy_they_need(monkeypatch):
    game = flying(seat=1)
    patient = game.station_crew[0]
    add_to_inventory(game.player_data, get_item_definition("antitoxin"))
    credits = game.player_data["credits"]
    assert said(in_flight(monkeypatch, game, "Taken Ill", pick=prefer("antitoxin"))) == [
        f"{patient['name']} ({patient['job']}) is doubled over with food poisoning."]
    assert game.view()["choice"]["buttons"] == ["Give Them a Remedy", "Leave It to the Medics"]
    choose(game, "Give Them a Remedy")
    assert said(drain(game)) == [
        f"You give {patient['name']} your Antitoxin. They feel better at once and pay you 80 credits."]
    assert (game.player_data["credits"], game.player_data["inventory"]) == (credits + 80, [])


@pytest.mark.parametrize("remedy, hint", [
    ("antitoxin", " Maybe if I had an Antitoxin, I could have helped them."),
    ("burn_salve", " Maybe if I had a Burn Salve, I could have helped them."),
])
def test_leaving_them_to_the_medics_wonders_what_would_have_helped(monkeypatch, remedy, hint):
    game = flying(seat=1)
    patient = game.station_crew[0]
    in_flight(monkeypatch, game, "Taken Ill", pick=prefer(remedy))
    assert game.view()["choice"]["buttons"] == ["Leave It to the Medics"]
    choose(game, "Leave It to the Medics")
    assert said(drain(game)) == [f"You leave {patient['name']} to the shuttle's medics.{hint}"]


def test_leaving_them_to_the_medics_with_the_remedy_in_hand_gives_no_hint(monkeypatch):
    game = flying(seat=1)
    add_to_inventory(game.player_data, get_item_definition("healing_gel"))
    in_flight(monkeypatch, game, "Taken Ill", pick=prefer("healing_gel"))
    choose(game, "Leave It to the Medics")
    assert said(drain(game)) == [f"You leave {game.station_crew[0]['name']} to the shuttle's medics."]
    assert len(game.player_data["inventory"]) == 1


def test_a_remedy_given_away_before_the_answer_is_not_given_twice(monkeypatch):
    game = flying(seat=1)
    add_to_inventory(game.player_data, get_item_definition("oxygen_tonic"))
    in_flight(monkeypatch, game, "Taken Ill", pick=prefer("oxygen_tonic"))
    game.player_data["inventory"] = []
    credits = game.player_data["credits"]
    choose(game, "Give Them a Remedy")
    assert (drain(game), game.player_data["credits"]) == ([], credits)


def test_nobody_is_taken_ill_with_nobody_in_the_seats():
    game = flying()
    game.station_crew[0].update(location=location_from_key(DEPARTURES_KEY), in_jail=True)
    assert random_events._taken_ill(game) is None


def test_every_remedy_has_an_ailment_it_treats():
    assert set(random_events.FLIGHT_AILMENTS) == set(STORE_REMEDY_IDS)


@pytest.mark.parametrize("roll, hurt", [(0.0, ["Injury", "Item Found"]), (0.99, ["Item Found"])])
def test_grabbing_loose_cargo_gets_an_item_and_maybe_a_knock(monkeypatch, roll, hurt):
    game = flying()
    assert said(in_flight(monkeypatch, game, "Loose Cargo", roll=roll)) == [
        "A crate breaks loose from the cargo netting and slides down the aisle toward you."]
    choose(game, "Grab It")
    assert [line["title"] for line in drain(game)] == hurt
    assert len(game.player_data["inventory"]) == 1


def test_letting_loose_cargo_slide(monkeypatch):
    game = flying()
    in_flight(monkeypatch, game, "Loose Cargo")
    choose(game, "Let It Slide")
    assert said(drain(game)) == ["You let it slide. It thuds against the bulkhead and stays there."]
    assert game.player_data["inventory"] == []


@pytest.mark.parametrize("label, reply", [
    ("It Went Well", "You tell Central Command the shift went well. They log it and sign off."),
    ("It Was Rough", "You tell Central Command it was a rough shift. They promise a full debrief and sign off."),
])
def test_central_command_asks_how_the_shift_went(monkeypatch, label, reply):
    game = flying()
    assert [line["title"] for line in in_flight(monkeypatch, game, "Central Command")] == ["Central Command"]
    choose(game, label)
    assert said(drain(game)) == [reply]
