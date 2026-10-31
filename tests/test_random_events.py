from types import SimpleNamespace

import pytest

from helpers import new_game
from space_online.game.helper_methods import random_events
from space_online.game.helper_methods.jail import is_jailed
from space_online.game.helper_methods.random_events import EVENT_CATEGORIES, build_job_event
from space_online.game.objects.items import ALL_ITEMS

CATEGORY = {event["title"]: event["type"] for event in random_events._static_events(None)}


def happen(monkeypatch, game, title, pick=lambda options: options[0], randint=lambda low, high: high):
    """Trigger the hallway event called title; every other random pick goes through pick and randint."""
    category = CATEGORY.get(title, "job")

    def choice(options):
        options = list(options)
        if options and all(option in EVENT_CATEGORIES for option in options):
            return category
        if options and all(isinstance(option, dict) and "effect" in option for option in options):
            return next(option for option in options if option["title"] == title)
        return pick(options)

    monkeypatch.setattr(random_events, "random", SimpleNamespace(random=lambda: 0.0, choice=choice, randint=randint))
    random_events.maybe_trigger_hallway_event(game)
    alerts = game.drain_alerts()
    assert [alert["title"] for alert in alerts] == [title]
    return alerts[0]["message"]


def notes(game):
    return [note["text"] for note in game.player_data["notes"]]


def test_most_steps_have_no_event(monkeypatch):
    game = new_game()
    monkeypatch.setattr(random_events.random, "random", lambda: random_events.HALLWAY_EVENT_CHANCE)
    random_events.maybe_trigger_hallway_event(game)
    assert game.drain_alerts() == []


def test_found_credits(monkeypatch):
    game = new_game()
    message = happen(monkeypatch, game, "Found Credits")
    assert message == "You found some credits on the floor!\n\nYou gained 200 credits."
    assert game.player_data["credits"] == 1200
    assert notes(game) == ["Found 200 credits. New balance: 1200 credits."]
    assert game.event_messages is None


def test_a_supply_crate(monkeypatch):
    game = new_game()
    first = next(iter(ALL_ITEMS))
    message = happen(monkeypatch, game, "Supply Crate")
    assert message.endswith(f"You found {ALL_ITEMS[first]['name']} and added it to your inventory.")
    assert game.player_data["inventory"][0]["id"] == first


def test_a_market_tip(monkeypatch):
    game = new_game()
    message = happen(monkeypatch, game, "Market Tip")
    assert "\n\nOverheard that " in message
    assert notes(game)[-1].startswith("Market Tip: Overheard that ")


def test_a_market_tip_before_there_is_a_market(monkeypatch):
    game = new_game()
    game.player_data["stock_market"]["companies"] = []
    message = happen(monkeypatch, game, "Market Tip")
    assert message.endswith("You heard a stock tip, but don't understand the market yet.")
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


def bot(kind):
    return lambda options: kind if kind in options else options[0]


def test_a_maintenance_bot(monkeypatch):
    message = happen(monkeypatch, new_game(), "Bot Moves By", pick=bot("maintenance"))
    assert message.endswith("A maintenance bot rolls past, scrubbing the floor as it goes.")


def test_a_security_bot_passes_an_honest_player(monkeypatch):
    game = new_game()
    message = happen(monkeypatch, game, "Bot Moves By", pick=bot("security"))
    assert message.endswith("A security bot scans you briefly and continues on its patrol.")


def test_a_security_bot_arrests_a_wanted_player(monkeypatch):
    game = new_game()
    game.player_data.update(warrant=True, warrant_reason="Smuggling")
    message = happen(monkeypatch, game, "Bot Moves By", pick=bot("security"))
    assert message.endswith("A security bot locks onto you. You are wanted, and you are under arrest!\n"
                            "Charge: Smuggling")
    assert is_jailed(game.player_data)


def test_a_medical_bot_with_nothing_to_treat(monkeypatch):
    message = happen(monkeypatch, new_game(), "Bot Moves By", pick=bot("medical"))
    assert message.endswith("A medical bot stops beside you and runs a quick diagnostic.\n"
                            "A medical bot scans you, finds nothing to treat, and rolls away.")


def test_a_medical_bot_heals_a_limb(monkeypatch):
    game = new_game()
    game.player_data["limbs"]["head"] = 50
    message = happen(monkeypatch, game, "Bot Moves By", pick=bot("medical"))
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
    pick = lambda options: "spit_out" if "spit_out" in options else options[0]
    message = happen(monkeypatch, game, "Vending Machine Malfunction", pick=pick)
    assert message.endswith("The machine violently spits something out at you!\n"
                            "Your Head took 5% blunt damage and is now at 95%.")


@pytest.mark.parametrize("outcome, ending", [
    ("stuck", "You see a snack stuck against the glass, just out of reach."),
    ("free_snack", "The machine clunks and a free snack drops into the tray.\n"
                   "You found a free Snack and added it to your inventory."),
])
def test_a_vending_machine_sticks_or_pays_out(monkeypatch, outcome, ending):
    game = new_game()
    message = happen(monkeypatch, game, "Vending Machine Malfunction", pick=lambda options: outcome)
    assert message.endswith(ending)
    assert [item["id"] for item in game.player_data["inventory"]] == (["snack"] if outcome == "free_snack" else [])


def test_lost_credits_and_a_bumped_head(monkeypatch):
    game = new_game()
    message = happen(monkeypatch, game, "Lost Credits")
    assert message.endswith("\n\nYou lost 50 credits.\nYour Head took 10% blunt damage and is now at 90%.")
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


def test_damage_tops_out_at_100(monkeypatch):
    game = new_game()
    game.player_data["damage"]["burn"] = 95
    message = happen(monkeypatch, game, "Steam Leak")
    assert game.player_data["damage"]["burn"] == 100
    assert message.endswith("You suffered 30% burn damage! Total burn damage: 100%.")


def test_effects_outside_an_event_report_on_their_own():
    game = new_game()
    random_events.add_credits(game, 5)
    assert game.drain_alerts() == [{"title": "Credits Added", "message": "You gained 5 credits.", "kind": "info"}]


@pytest.mark.parametrize("department, job, title, ending", [
    ("Civilian", "Staff Assistant", "Job Request", "Job request: The Botanist needs water for the planters."),
    ("Administration", "Captain", "Command Request",
     "Command request: Medbay requests authorization for emergency surgery supplies."),
])
def test_job_requests_go_in_the_notes(monkeypatch, department, job, title, ending):
    game = new_game(department, job)
    assert happen(monkeypatch, game, title) == ending
    assert notes(game) == [ending]


def test_an_engineer_finds_the_solar_array_down(monkeypatch):
    game = new_game("Engineering", "Engineer")
    game.player_data["station_power"]["solar_charging"] = True
    happen(monkeypatch, game, "Solar Panels Offline")
    assert game.player_data["station_power"]["solar_charging"] is False


@pytest.mark.parametrize("pick, wanted", [(lambda o: o[0], "a tomato"), (lambda o: o[-1], "an apple")])
def test_the_botanist_gets_a_crop_request(monkeypatch, pick, wanted):
    game = new_game("Civilian", "Botanist")
    assert happen(monkeypatch, game, "Crop Request", pick=pick) == f"The Bartender needs {wanted} from the botany lab."


def test_a_guard_witnesses_a_crime_with_or_without_a_culprit(monkeypatch):
    game = new_game("Security", "Security Guard")
    game.player_data["location"] = {"x": 2, "y": 5}
    for npc in game.station_crew:
        npc["location"] = {"x": 0, "y": 1}
    assert happen(monkeypatch, game, "Witness a Crime") == "You witness a crime! You do not catch who it is."
    culprit = game.station_crew[-1]
    culprit["location"] = {"x": 2, "y": 5}
    assert happen(monkeypatch, game, "Witness a Crime") == f"You witness a crime! {culprit['name']} is involved."
    assert notes(game) == ["Witnessed a crime; perpetrator unidentified.",
                           f"Witnessed a crime involving {culprit['name']}."]


def test_the_hop_gets_an_access_request_from_the_crew(monkeypatch):
    game = new_game("Administration", "Head of Personnel")
    requester = next(npc for npc in game.station_crew if npc["job"] != "Captain")
    message = happen(monkeypatch, game, "Access Request")
    assert message.startswith(f"{requester['name']} ({requester['job']}) has submitted an access request to become ")
    assert game.player_data["access_request"]["requester_name"] == requester["name"]


def test_the_captain_never_asks_the_hop_for_another_job(monkeypatch):
    game = new_game("Administration", "Head of Personnel")
    offered = []
    happen(monkeypatch, game, "Access Request", pick=lambda options: offered.append(options) or options[0])
    assert all(npc["job"] != "Captain" for npc in offered[0])
    assert any(npc["job"] == "Captain" for npc in game.station_crew)


def test_the_hop_gets_no_new_request_while_one_waits_or_nobody_is_free():
    game = new_game("Administration", "Head of Personnel")
    game.player_data["access_request"] = {"requested_job": "Doctor", "requester_name": "Someone"}
    assert build_job_event(game) is None
    del game.player_data["access_request"]
    for npc in game.station_crew:
        npc["in_jail"] = True
    assert build_job_event(game) is None


@pytest.mark.parametrize("department, job", [("Medical", "Doctor"), ("Civilian", "Bartender")])
def test_some_jobs_have_no_job_event(monkeypatch, department, job):
    game = new_game(department, job)
    assert build_job_event(game) is None
    assert happen(monkeypatch, game, "Lost Tourist").startswith("A confused visitor")
