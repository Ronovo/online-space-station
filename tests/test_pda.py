import re
import time

import pytest
from markupsafe import escape

from helpers import feedback, give_duty, html, messages, new_game, pda_messages, pure, tank_item
from space_online.game.character_methods.character_creation import JOBS, STARTING_FILES, new_shift
from space_online.game.helper_methods import random_events
from space_online.game.helper_methods.career import finish_round, new_career, start_career_shift
from space_online.game.helper_methods.errands import finish_duty, tick_duty_expiry
from space_online.game.helper_methods.hazards import set_hazard
from space_online.game.helper_methods.jail import set_warrant
from space_online.game.helper_methods.npc_movement import post_holder
from space_online.game.helper_methods.pda import (
    BROADCAST_PRESETS,
    JOB_GUIDES,
    MAX_BROADCAST_CHARS,
    MAX_FILE_CHARS,
    MAX_MESSAGES,
    MAX_OWN_FILES,
    STATION_GUIDES,
    guide_titles,
    send,
    tick_pda_needs,
    unread_count,
)
from space_online.game.helper_methods.power_constants import BATTERY_CRITICAL, fault_system
from space_online.game.maps.donut import BOTANY_KEY, CHEMISTRY_KEY, ENGINEERING_KEY, RESEARCH_KEY, location_from_key
from space_online.game.objects.botany_items import empty_planter
from space_online.game.objects.drinks import DRINKS_MENU, MIXED_DRINKS, drink_item
from space_online.game.objects.items import NO_SCANNER, add_to_inventory, get_item_definition
from space_online.webapp.wiki import PAGES, file_text, page_slug, render_markdown


def playing(job, pda="left", post=CHEMISTRY_KEY):
    """A game in job. A Scientist is posted to post."""
    return new_game(JOBS[job]["department"], job, pda=pda, post=post if job == "Scientist" else None)


def shown_panel(game):
    view = game.view()["panel"]
    return (view["type"], view["ctx"]) if view else None


def posted(game, job):
    return post_holder(game.station_crew, job)


# --- The item and its menu ---------------------------------------------------------

def test_everyone_starts_a_shift_carrying_a_pda_and_it_opens_only_from_a_hand():
    game = playing("Staff Assistant", pda="carried")
    assert [item["name"] for item in game.player_data["inventory"]] == ["PDA"]
    assert game.view()["pda"] is None
    game.perform("game.pda", {})
    assert shown_panel(game) is None

    game.open_panel("hands")
    game.perform("panel.select", {"index": 0})
    game.perform("panel.equip", {"side": "right"})
    game.perform("game.close_panel", {})
    assert game.view()["pda"] == "PDA"
    game.perform("game.pda", {})
    assert shown_panel(game) == ("pda", {"name": "Ada", "job": "Staff Assistant", "unread": 0, "app": None,
                                   "orders": True})


def test_the_order_console_opens_from_the_pda_for_everyone_but_the_quartermaster(app):
    game = playing("Botanist")
    game.perform("game.pda", {})
    assert ">Order Console</button>" in html(app, game)
    game.perform("panel.orders", {})
    assert shown_panel(game)[0] == "order_request"

    quartermaster = playing("Quartermaster")
    quartermaster.perform("game.pda", {})
    assert shown_panel(quartermaster)[1]["orders"] is False
    assert ">Order Console</button>" not in html(app, quartermaster)
    quartermaster.perform("panel.orders", {})
    assert shown_panel(quartermaster)[0] == "pda"
    assert [state["type"] for state in quartermaster.ui["panels"]] == ["pda"]


def test_the_pda_button_counts_unread_messages_and_the_menu_shuts_when_the_pda_leaves_the_hand():
    game = playing("Staff Assistant")
    send(game.player_data, "Kitchen", "Out of carrots.")
    assert game.view()["pda"] == "PDA (1)"
    game.perform("game.pda", {})
    assert shown_panel(game)[1]["unread"] == 1
    game.player_data["hands"]["left"] = None
    assert (shown_panel(game), game.ui["panels"]) == (None, [])


def test_the_inbox_shows_the_newest_first_and_marks_what_was_unread_once():
    game = playing("Staff Assistant")
    send(game.player_data, "Kitchen", "Out of carrots.")
    game.player_data["game_clock"]["elapsed_seconds"] = 125
    send(game.player_data, "MedBay", "Out of remedies.")
    game.perform("game.pda", {})
    game.perform("panel.messages", {})
    assert shown_panel(game) == ("pda_messages", {"messages": [
        {"time": "T+2m", "subject": "MedBay", "text": "Out of remedies.", "new": True},
        {"time": "T+0m", "subject": "Kitchen", "text": "Out of carrots.", "new": True}]})
    assert unread_count(game.player_data) == 0
    game.perform("game.close_panel", {})
    send(game.player_data, "Bar", "Out of limes.")
    game.perform("panel.messages", {})
    assert [(message["subject"], message["new"]) for message in shown_panel(game)[1]["messages"]] == [
        ("Bar", True), ("MedBay", False), ("Kitchen", False)]


def test_the_pda_keeps_only_its_newest_messages():
    game = playing("Staff Assistant")
    for number in range(MAX_MESSAGES + 2):
        send(game.player_data, "Test", str(number))
    assert [text for _, text in pda_messages(game)] == [str(number) for number in range(2, MAX_MESSAGES + 2)]


# --- Messages from the job ------------------------------------------------------------

def test_duties_and_job_events_stay_off_the_pda():
    game = playing("Botanist", pda=False)
    random_events._run_event(game, {"type": "job", "title": "Crop Request", "desc": "The Bartender needs a tomato.",
                                    "effect": lambda: None})
    random_events._run_event(game, {"type": "good", "title": "Lucky Find", "desc": "A coin.", "effect": lambda: None})
    give_duty(game, kind="help", room=BOTANY_KEY, summary="Help out")
    give_duty(game, kind="help", room=BOTANY_KEY, summary="Sweep up")
    finish_duty(game, game.player_data["duties"][0], "note", "You help out.")
    game.player_data["game_clock"]["elapsed_seconds"] = 10 ** 6
    tick_duty_expiry(game)
    assert pda_messages(game) == []


def test_an_event_that_hurts_you_or_drops_something_at_your_feet_reaches_the_pda():
    game = playing("Botanist", pda=False)

    def hurt():
        game.player_data["limbs"]["head"] -= 5
        random_events._report_effect(game, "Injury", "Your Head took 5% damage.")

    def burn():
        game.player_data["damage"]["burn"] += 3

    def drop():
        game.floor_here().append({"id": "snack", "quantity": 1})

    def heal():
        game.player_data["limbs"]["head"] += 5

    for title, effect in (("Debris", hurt), ("Steam", burn), ("Crate", drop), ("Medical Bot", heal)):
        random_events._run_event(game, {"type": "bad", "title": title, "desc": f"{title}.", "effect": effect})
    assert pda_messages(game) == [("Debris", "Debris.\n\nYour Head took 5% damage."), ("Steam", "Steam."),
                                  ("Crate", "Crate.")]


def wizard_shows_itself(game):
    game.player_data["threats"].append({"name": "the Wizard", "revealed": True, "acts": 1, "fate": None})


NEEDS = [
    ("Miner", lambda game: game.player_data["stores"].update(ore=2),
     [("Engineering", "The fabricator is almost out of ore. Send some up from the Mining Bay.")]),
    ("Botanist", lambda game: game.player_data["stores"]["produce"].update(Tomato=0),
     [("Kitchen", "The kitchen is out of tomato. Send some from the Botany Lab.")]),
    ("Scientist", lambda game: game.player_data["stores"].update(remedies=1),
     [("MedBay", "MedBay is almost out of remedies. Send some from Chemistry.")]),
    ("Doctor", lambda game: posted(game, "Chef")["limbs"].update(dict.fromkeys(posted(game, "Chef")["limbs"], 0)),
     [("Crew Vitals", "{Chef} is in critical condition.")]),
    ("Quartermaster", lambda game: game.player_data["cargo"]["arrived"].append("medkit"),
     [("Cargo Bay", "A supply pod has docked. Collect it at the Cargo Bay.")]),
    ("Security Guard", lambda game: (set_warrant(posted(game, "Chef"), "theft"), wizard_shows_itself(game)),
     [("Warrant", "{Chef} is wanted: theft."), ("Alert", "The Wizard is loose on the station.")]),
    ("Engineer", lambda game: (fault_system(game.player_data["station_power"], "security_systems"),
                               set_hazard(game.player_data, ENGINEERING_KEY, "fire"),
                               game.player_data["station_power"].update(battery_level=BATTERY_CRITICAL,
                                                                        dimmed_from=6, solar_charging=False)),
     [("Power", "A fault has shut down the Security Systems."), ("Hazard", "Fire in the Engineering Bay."),
      ("Power", "The station battery is critically low."),
      ("Power", "The solar panels are offline. Restart them from the Engineering Panel."),
      ("Power", "Someone has dimmed the hallway lighting.")]),
    ("Head of Personnel", lambda game: game.player_data.update(access_request={
        "requested_job": "Miner", "requester_name": "Morgan Yu", "decide_at": None}),
     [("Access Request", "Morgan Yu has asked to become Miner. Review it at Access Control on the Bridge.")]),
    ("Bartender", lambda game: game.player_data["service_window"]["requests"]["kitchen"].update(Lime=2),
     [("Service Window", "The Chef asks for 2 Lime at the service window.")]),
    ("Chef", lambda game: game.player_data["service_window"]["requests"]["bar"].update(Egg=1),
     [("Service Window", "The Bartender asks for 1 Egg at the service window.")]),
]


@pytest.mark.parametrize("job, trouble, expected", NEEDS, ids=[job for job, *_ in NEEDS])
def test_each_job_is_told_once_when_something_it_looks_after_needs_it(job, trouble, expected):
    game = playing(job, pda=False)
    game.player_data["station_power"]["solar_charging"] = True
    tick_pda_needs(game)
    assert pda_messages(game) == []
    trouble(game)
    tick_pda_needs(game)
    tick_pda_needs(game)
    chef = (posted(game, "Chef") or {}).get("name")
    assert pda_messages(game) == [(subject, text.format(Chef=chef)) for subject, text in expected]


def test_a_need_that_comes_back_is_sent_again_and_other_jobs_hear_nothing():
    game = playing("Miner", pda=False)
    stores = game.player_data["stores"]
    for ore in (0, 20, 1):
        stores["ore"] = ore
        tick_pda_needs(game)
    assert [subject for subject, _ in pda_messages(game)] == ["Engineering", "Engineering"]

    for job, post in (("Staff Assistant", None), ("Scientist", RESEARCH_KEY)):
        game = playing(job, pda=False, post=post)
        game.player_data["stores"].update(ore=0, remedies=0)
        tick_pda_needs(game)
        assert pda_messages(game) == []


def test_the_master_clock_checks_what_the_job_needs():
    game = playing("Scientist", pda=False)
    game.player_data["stores"]["remedies"] = 0
    game.player_data["game_clock"]["last_real_time"] = time.time() - 2
    game.tick()
    assert ("MedBay", "MedBay is almost out of remedies. Send some from Chemistry.") in pda_messages(game)


# --- Scanning ---------------------------------------------------------------------------

def scan(game, item):
    """Scan an item from the inventory panel and return the log line it wrote."""
    game.player_data["inventory"] = []
    add_to_inventory(game.player_data, item if isinstance(item, dict) else get_item_definition(item))
    game.ui["panels"] = []
    game._messages = []
    game.open_panel("inventory")
    game.perform("panel.select", {"index": 0})
    game.perform("panel.scan", {})
    return messages(game)


SCREWDRIVER = drink_item("Screwdriver", MIXED_DRINKS["Screwdriver"])
VODKA = drink_item("Vodka", DRINKS_MENU["Vodka"])
HYDROGEN_TANK = tank_item(pure("Hydrogen", 12))
SCANS = [
    ("Chef", "tomato", "Edible. Feeds 20% of your hunger."),
    ("Chef", "blood_tomato", "Edible. Feeds 40% of your hunger. Mends: Poison 15."),
    ("Chef", "wrench", "Not edible."),
    ("Chef", HYDROGEN_TANK, "Not edible."),
    ("Bartender", SCREWDRIVER, "Mixed from Vodka, Orange Juice."),
    ("Bartender", VODKA, "Plain Vodka. Nothing is mixed into it."),
    ("Bartender", "tomato", "Not a drink."),
    ("Scientist", "aloe", "The processor makes Aloe Extract of it."),
    ("Scientist", "aloe_extract", "Goes into the beaker as Aloe Extract."),
    ("Scientist", "burn_salve", "A compound of Aloe Extract, Sodium, Water. Treats: Burn 30."),
    ("Scientist", SCREWDRIVER, "Goes into the beaker as Ethanol. Alcohol: 2%."),
    ("Scientist", "wrench", "No chemical properties on record."),
    ("Scientist", HYDROGEN_TANK, "417.6 kPa, 293 K: Hydrogen 100.0%"),
    ("Quartermaster", "medkit", "Orders for 40 credits. Sells over the counter for 80 credits."),
    ("Quartermaster", "gold_ore", "Exports for 60 credits."),
    ("Quartermaster", "wrench", "Central Command neither sells nor buys this."),
    ("Staff Assistant", "tomato", NO_SCANNER),
]


@pytest.mark.parametrize("job, item, reading", SCANS)
def test_a_held_pda_reads_an_inventory_item_as_the_job_knows_it(job, item, reading):
    name = item["name"] if isinstance(item, dict) else get_item_definition(item)["name"]
    assert scan(playing(job), item) == [(f"PDA Scan: {name}", reading)]


def test_scanning_takes_the_pda_in_a_hand_and_an_item_selected():
    game = playing("Chef", pda="carried")
    game.open_panel("inventory")
    game.perform("panel.select", {"index": 0})
    assert shown_panel(game)[1]["can_scan"] is False
    game.perform("panel.scan", {})
    assert messages(game) == []

    game = playing("Chef")
    add_to_inventory(game.player_data, get_item_definition("tomato"))
    game.open_panel("inventory")
    assert shown_panel(game)[1]["can_scan"] is False
    game.perform("panel.scan", {})
    assert messages(game) == []
    game.perform("panel.select", {"index": 0})
    assert shown_panel(game)[1]["can_scan"] is True


def show_planters(game, *planted):
    """Open the first planter row at the Botany Station with these planters in it."""
    game.player_data["location"] = location_from_key(BOTANY_KEY)
    potato = {**empty_planter(), "occupied": True, "plant": "Potato", "seed_id": "potato_seeds",
              "produces": "potato", "growth_class": "crop", "planted_at_seconds": 0, "growth_stage": 1}
    for index, changes in enumerate(planted):
        game.player_data["botany"]["planters"][index] = {**potato, **changes}
    game.open_panel("planter_row", row=0, allow_harvest=True)
    return game


def test_a_botanists_pda_reads_a_planter():
    game = show_planters(playing("Botanist"), {},
                    {"ooze_applied": True, "yield_multiplier": 2, "miracle_grow": 0.5, "watered": True},
                    {"dead": True})
    for index in range(4):
        game.perform("panel.use_hand", {"index": index, "side": "left"})
    assert messages(game) == [
        ("PDA Scan: Planter 1", "Potato. Stage: Seedling (1/5) - needs water. Next stage in 3m 0s. Yield: 1. "
                                "No mutation chance."),
        ("PDA Scan: Planter 2", "Potato. Stage: Seedling (1/5). Next stage in 1m 30s. Miracle Grow. "
                                "Plentiful Harvest. The Ooze. Yield: 2. Mutation chance: 35%."),
        ("PDA Scan: Planter 3", "Potato. Status: Dead. Needs to be cleared with a Trowel or Chainsaw."),
        ("PDA Scan: Planter 4", "Empty. Ready for seeds."),
    ]
    assert game.player_data["hands"]["left"]["id"] == "pda"


def test_nobody_elses_pda_reads_a_planter():
    game = show_planters(playing("Captain"), {})
    game.perform("panel.use_hand", {"index": 0, "side": "left"})
    assert messages(game) == [("PDA Scan: Planter 1", NO_SCANNER)]


# --- Job apps ---------------------------------------------------------------------------

@pytest.mark.parametrize("job, label, opens", [
    ("Engineer", "Power Readout", "power_readout"), ("Doctor", "Crew Vitals", "crew_vitals"),
    ("Security Guard", "Scan Crew", "scan_crew"), ("Head of Personnel", "Access Control", "hop_console"),
    ("Captain", "Broadcast", "broadcast"), ("Miner", "Ore Log", "ore_log"), ("Staff Assistant", None, "pda"),
])
def test_the_menu_offers_the_jobs_own_app_and_opens_it(job, label, opens):
    game = playing(job)
    game.perform("game.pda", {})
    assert shown_panel(game)[1]["app"] == label
    game.perform("panel.app", {})
    assert game.ui["panels"][-1]["type"] == opens


def test_the_engineers_readout_shows_power_and_hazards():
    game = playing("Engineer")
    game.player_data["station_power"]["battery_level"] = 40
    set_hazard(game.player_data, ENGINEERING_KEY, "breach")
    game.open_panel("power_readout")
    readout = shown_panel(game)[1]
    assert (readout["power"]["battery_level"], readout["power"]["battery_band"]) == (40, "Low")
    assert [system["name"] for system in readout["power"]["systems"]] == [
        "Life Support", "Hallway Lighting", "Security Systems", "Communication Array"]
    assert readout["hazards"] == ["Hull breach in the Engineering Bay"]


def test_the_doctors_pda_shows_vitals_but_treating_takes_medbay():
    game = playing("Doctor")
    patient = posted(game, "Chef")
    patient["limbs"]["head"] = 20
    game.perform("game.pda", {})
    game.perform("panel.app", {})
    row = next(row for row in shown_panel(game)[1]["crew"] if row["name"] == patient["name"])
    assert (row["status"], row["can_treat"]) == ("Minor injuries", False)
    remedies = game.player_data["stores"]["remedies"]
    game.perform("panel.treat", {"name": patient["name"]})
    assert (patient["limbs"]["head"], game.player_data["stores"]["remedies"]) == (20, remedies)


def test_a_guard_scans_the_crew_standing_with_them():
    game = playing("Security Guard")
    chef, miner = posted(game, "Chef"), posted(game, "Miner")
    chef["location"] = dict(game.player_data["location"])
    game.open_panel("scan_crew")
    assert shown_panel(game) == ("scan_crew", {"crew": [{"name": chef["name"], "job": "Chef"}]})
    game.perform("panel.scan", {"name": miner["name"]})
    assert messages(game) == []
    game.perform("panel.scan", {"name": chef["name"]})
    assert messages(game) == [(f"PDA Scan: {chef['name']}",
                          "Chef. No warrant or fine on record. No incidents on record this shift.")]


def test_a_scan_reads_the_record_and_how_often_they_were_away_for_an_incident():
    game = playing("Security Guard")
    chef = posted(game, "Chef")
    chef["location"] = dict(game.player_data["location"])
    set_warrant(chef, "theft")
    chef.update(fine_amount=50, fine_reason="littering")
    game.player_data["incidents"] = [{"away": [chef["name"]]}, {"away": []}, {"away": [chef["name"], "Someone"]},
                                     {"away": None}]
    game.open_panel("scan_crew")
    game.perform("panel.scan", {"name": chef["name"]})
    assert messages(game)[0][1] == ("Chef. Wanted: theft. Owes a fine of 50 credits. "
                               "Away from their post for 2 of this shift's 3 incidents.")


def broadcast(game, **args):
    game.ui["panels"] = []
    game._messages = []
    game.open_panel("broadcast")
    game.perform("panel.send", args)
    return feedback(game), messages(game)


def test_the_captain_broadcasts_a_preset_or_their_own_words_through_the_communication_array():
    game = playing("Captain")
    game.open_panel("broadcast")
    assert shown_panel(game) == ("broadcast", {"presets": BROADCAST_PRESETS, "max": MAX_BROADCAST_CHARS,
                                               "feedback": None})
    assert broadcast(game, text=BROADCAST_PRESETS[0]) == (
        "Broadcast sent.", [("Captain's Broadcast", "All hands, return to your posts.")])
    assert broadcast(game, text="  Party  in\nthe Bar  ") == (
        "Broadcast sent.", [("Captain's Broadcast", "Party in the Bar")])
    assert broadcast(game, text="x" * (MAX_BROADCAST_CHARS + 50))[1] == [
        ("Captain's Broadcast", "x" * MAX_BROADCAST_CHARS)]
    assert broadcast(game) == ("Type a message or pick one.", [])
    assert broadcast(game, text="   ") == ("Type a message or pick one.", [])

    game.player_data["station_power"]["system_levels"]["communication_array"] = 0
    assert broadcast(game, text="Hello") == ("The Communication Array is down. Nothing goes out.", [])


# --- Stocks -----------------------------------------------------------------------------

def test_the_pda_shows_the_market_but_does_not_trade():
    game = playing("Staff Assistant")
    game.market_engine.companies[0].current_value = 100.0
    company = game.market_engine.companies[0].name
    game.perform("game.pda", {})
    game.perform("panel.stocks", {})
    game.perform("panel.select", {"name": company})
    kind, market = shown_panel(game)
    assert (kind, market["read_only"], market["detail"]["name"]) == ("stock_market", True, company)
    credits = game.player_data["credits"]
    game.perform("panel.buy", {"shares": "1"})
    assert (game.player_data["credits"], game.player_data["stock_holdings"], messages(game)) == (credits, {}, [])

    game.ui["panels"] = []
    game.open_panel("stock_market")
    game.perform("panel.select", {"name": company})
    game.perform("panel.buy", {"shares": "1"})
    assert (shown_panel(game)[1]["read_only"], game.player_data["stock_holdings"]) == (False, {company: 1})


# --- Files ------------------------------------------------------------------------------

def test_the_guide_folder_follows_the_job_and_every_file_in_it_is_a_wiki_page():
    assert guide_titles("Botanist") == ("Botanist", "Botany", "Station Stores", "PDA", "Getting Started",
                                        "The Station", "Duties and Job Events", "Health", "Hazards",
                                        "Items and Hands")
    assert guide_titles("Staff Assistant") == ("Staff Assistant", *STATION_GUIDES)
    assert set(JOB_GUIDES) < set(JOBS)
    for job in JOBS:
        titles = guide_titles(job)
        assert len(set(titles)) == len(titles)
        for title in titles:
            assert page_slug(title) in PAGES, title


def computer(game):
    game.ui["panels"] = []
    game.open_panel("computer")
    game.perform("panel.files", {})
    return game


def test_the_computer_lists_the_guide_and_the_files_you_wrote():
    game = computer(playing("Chef", pda=False))
    game.player_data["files"] = {"home/b.txt": "B", "home/a.txt": "A"}
    kind, files = shown_panel(game)
    assert (kind, files["read_only"], files["feedback"]) == ("files", False, None)
    assert files["guide"][:2] == [{"path": "guide/Chef.md", "name": "Chef.md"},
                                  {"path": "guide/Kitchen.md", "name": "Kitchen.md"}]
    assert files["home"] == [{"path": "home/a.txt", "name": "a.txt"}, {"path": "home/b.txt", "name": "b.txt"}]


def test_writing_reading_editing_and_deleting_a_file_at_the_computer():
    game = computer(playing("Chef", pda=False))
    game.perform("panel.new", {"name": " shopping list.txt "})
    assert shown_panel(game) == ("file_edit", {"name": "shopping list.txt", "guide": None, "text": "",
                                         "title": "Editing shopping list.txt", "max": MAX_FILE_CHARS,
                                         "feedback": None})
    game.perform("panel.save", {"text": "eggs\r\nflour"})
    assert game.player_data["files"] == {**STARTING_FILES, "home/shopping list.txt": "eggs\nflour"}
    assert shown_panel(game)[0] == "files"

    game.perform("panel.open", {"path": "home/shopping list.txt"})
    chef_guides = [f"{title}.md" for title in guide_titles("Chef")]
    assert shown_panel(game) == ("file", {"name": "shopping list.txt", "guide": None, "text": "eggs\nflour",
                                    "title": "shopping list.txt", "read_only": False, "editable": True,
                                    "links": chef_guides, "back": False})
    game.perform("panel.edit", {})
    game.perform("panel.save", {"text": "eggs"})
    assert (shown_panel(game)[0], shown_panel(game)[1]["text"]) == ("file", "eggs")
    game.perform("panel.remove", {})
    assert (shown_panel(game)[0], game.player_data["files"]) == ("files", STARTING_FILES)


@pytest.mark.parametrize("name, complaint", [
    ("", "A file name is 1 to 40 letters, digits, spaces, dots, hyphens or underscores."),
    ("a/b", "A file name is 1 to 40 letters, digits, spaces, dots, hyphens or underscores."),
    ("x" * 41, "A file name is 1 to 40 letters, digits, spaces, dots, hyphens or underscores."),
    ("mine.txt", "You already have a file called mine.txt."),
    ("new.txt", f"Your home folder is full. It holds {MAX_OWN_FILES} files."),
])
def test_a_new_file_needs_a_plain_name_that_is_free_and_room_in_the_folder(name, complaint):
    game = computer(playing("Chef", pda=False))
    game.player_data["files"] = {"home/mine.txt": "", "guide/Kitchen.md": ""}
    if name == "new.txt":
        game.player_data["files"].update({f"home/{number}": "" for number in range(MAX_OWN_FILES - 1)})
    before = dict(game.player_data["files"])
    game.perform("panel.new", {"name": name})
    assert (shown_panel(game)[0], feedback(game), game.player_data["files"]) == (
        "files", complaint, before)


def test_a_file_that_is_too_long_is_not_saved():
    game = computer(playing("Chef", pda=False))
    game.perform("panel.new", {"name": "long.txt"})
    game.perform("panel.save", {"text": "x" * (MAX_FILE_CHARS + 1)})
    assert feedback(game) == f"A file holds {MAX_FILE_CHARS} characters. This is {MAX_FILE_CHARS + 1}."
    assert game.player_data["files"] == {**STARTING_FILES, "home/long.txt": ""}
    game.perform("panel.save", {"text": "x" * MAX_FILE_CHARS})
    assert game.player_data["files"] == {**STARTING_FILES, "home/long.txt": "x" * MAX_FILE_CHARS}


def test_a_guide_file_can_only_be_read_even_at_the_computer():
    game = computer(playing("Chef", pda=False))
    game.perform("panel.open", {"path": "guide/Kitchen.md"})
    assert shown_panel(game) == ("file", {"name": "Kitchen.md", "guide": "Kitchen", "text": None, "title": "Kitchen.md",
                                    "read_only": False, "editable": False,
                                    "links": [f"{title}.md" for title in guide_titles("Chef")], "back": False})
    for action, args in (("panel.edit", {}), ("panel.remove", {})):
        game.perform(action, args)
        assert shown_panel(game)[0] == "file", action
    game.ui["panels"].append({"type": "file_edit", "path": "guide/Kitchen.md"})
    assert shown_panel(game)[0] == "file"
    game.perform("game.close_panel", {})
    game.perform("panel.delete", {"path": "guide/Kitchen.md"})
    assert game.player_data["files"] == STARTING_FILES


@pytest.mark.parametrize("path", ["guide/Botany.md", "home/missing.txt", "guide/../home/x", "secrets/x"])
def test_only_your_own_files_and_your_jobs_guide_open(path):
    game = computer(playing("Chef", pda=False))
    game.player_data["files"] = {"secrets/x": "hidden"}
    game.perform("panel.open", {"path": path})
    assert shown_panel(game)[0] == "files"


def test_a_guide_file_shuts_when_a_new_job_takes_it_out_of_the_folder():
    game = computer(playing("Chef", pda=False))
    game.perform("panel.open", {"path": "guide/Kitchen.md"})
    assert shown_panel(game)[0] == "file"
    game.player_data["job"] = "Miner"
    assert shown_panel(game)[0] == "files"


def test_the_pda_only_reads_files():
    game = playing("Chef")
    game.player_data["files"] = {"home/mine.txt": "Mine"}
    game.perform("game.pda", {})
    game.perform("panel.files", {})
    assert shown_panel(game)[1]["read_only"] is True
    game.perform("panel.new", {"name": "other.txt"})
    game.perform("panel.delete", {"path": "home/mine.txt"})
    assert shown_panel(game)[0] == "files"

    for path in ("home/mine.txt", "guide/Kitchen.md"):
        game.perform("panel.open", {"path": path})
        assert (shown_panel(game)[0], shown_panel(game)[1]["read_only"], shown_panel(game)[1]["editable"]) == (
            "file", True, False)
        game.perform("panel.edit", {})
        game.perform("panel.remove", {})
        assert shown_panel(game)[0] == "file"
        game.perform("game.close_panel", {})
    assert game.player_data["files"] == {"home/mine.txt": "Mine"}


def test_deleting_your_own_file_from_the_files_list_at_the_computer():
    game = computer(playing("Chef", pda=False))
    game.player_data["files"] = {"home/a.txt": "A", "home/b.txt": "B"}
    game.perform("panel.delete", {"path": "home/a.txt"})
    assert (shown_panel(game)[0], game.player_data["files"]) == ("files", {"home/b.txt": "B"})
    assert shown_panel(game)[1]["home"] == [{"path": "home/b.txt", "name": "b.txt"}]
    for path in ("guide/Kitchen.md", "home/missing.txt", ""):
        game.perform("panel.delete", {"path": path})
    assert game.player_data["files"] == {"home/b.txt": "B"}


def test_a_careers_files_come_into_every_shift_and_go_back_when_the_round_ends():
    career = {**new_career("Ada"), "files": {"home/log.txt": "Shift one"}}
    shift = start_career_shift(career, "Staff Assistant")
    assert shift["files"] == {"home/log.txt": "Shift one"}
    shift["files"]["home/log.txt"] = "Shift two"
    shift["files"]["home/new.txt"] = "New"
    assert career["files"] == {"home/log.txt": "Shift one"}

    shift["round"]["outcome"] = {"survived": True, "cause": "reached Central Command", "seconds": 600}
    save = {"career": career, "shift": shift, "summary": None}
    finish_round(save)
    assert save["career"]["files"] == {"home/log.txt": "Shift two", "home/new.txt": "New"}
    assert new_shift("Ada", "Staff Assistant")["files"] == new_career("Bo")["files"] == STARTING_FILES


# --- Screens ----------------------------------------------------------------------------

def test_the_pda_button_is_on_every_screen_while_the_pda_is_in_a_hand(app):
    button = 'data-action="game.pda" data-args=\'{}\'>PDA (1)</button>'
    for pda, shown in (("left", True), ("carried", False)):
        game = playing("Staff Assistant", pda=pda)
        send(game.player_data, "Test", "Hello")
        assert (button in html(app, game)) is shown
        game.player_data["location"] = {"x": 0, "y": 0}
        assert (button in html(app, game)) is shown
        game.player_data["location"] = location_from_key(BOTANY_KEY)
        assert (button in html(app, game)) is shown


def system_menu_rows(page):
    menu = page.split('class="stack system-menu"', 1)[1]
    return [re.findall(r">([^<>]+)</button>", row) for row in menu.split('<div class="button-row">')[1:]]


def test_the_duties_button_counts_the_open_duties_on_every_screen(app):
    for location in (None, {"x": 0, "y": 0}, location_from_key(BOTANY_KEY)):
        game = playing("Staff Assistant")
        if location:
            game.player_data["location"] = location
        assert ">Duties</button>" in html(app, game)
        give_duty(game, kind="command", room=None, summary="Lock down the Bar?")
        give_duty(game, kind="command", room=None, summary="Arrest the Chef?")
        page = html(app, game)
        assert ">Duties (2)</button>" in page and ">Duties</button>" not in page, location


def test_the_system_menu_rows_drop_the_pda_when_it_is_put_away(app):
    screens = (
        (None, [["Duties", "Hands", "PDA"]], [["Duties", "Hands"]]),
        ({"x": 0, "y": 0}, [["Character Sheet", "Duties"], ["Hands", "PDA"]], [["Character Sheet", "Duties"], ["Hands"]]),
        (location_from_key(BOTANY_KEY), [["Character Sheet", "Duties", "Exit Room"], ["Hands", "PDA"]],
         [["Character Sheet", "Duties"], ["Hands", "Exit Room"]]),
    )
    for location, with_pda, without_pda in screens:
        for pda, expected in (("left", with_pda), ("carried", without_pda)):
            game = playing("Staff Assistant", pda=pda)
            if location:
                game.player_data["location"] = location
            page = html(app, game)
            assert system_menu_rows(page) == expected
            assert "slot" not in page.split('class="stack system-menu"', 1)[1]


def test_the_pda_menu_and_inbox_screens(app):
    game = playing("Captain")
    send(game.player_data, "Bridge", "Report in.")
    game.perform("game.pda", {})
    page = html(app, game)
    for text in ("<h2>PDA</h2>", "Ada, Captain", ">Messages (1 new)</button>", ">Broadcast</button>",
                 ">Stocks</button>", ">Files</button>", ">Close</button>",
                 "To scan something related to your job, use the PDA on the object."):
        assert text in page, text
    game.perform("panel.messages", {})
    page = html(app, game)
    assert '<p class="note pda-new"><span class="note-time">T+0m, Bridge (new)</span><br>Report in.</p>' in page

    game = playing("Staff Assistant")
    game.perform("game.pda", {})
    assert ">Messages</button>" in html(app, game)
    game.perform("panel.messages", {})
    assert "No messages yet." in html(app, game)


def test_the_job_app_screens(app):
    game = playing("Engineer")
    game.open_panel("power_readout")
    assert "<h2>Power Readout</h2>" in html(app, game) and "No hazards reported." in html(app, game)
    set_hazard(game.player_data, ENGINEERING_KEY, "fire")
    assert "<b>! Fire in the Engineering Bay</b>" in html(app, game)

    game = playing("Security Guard")
    game.open_panel("scan_crew")
    assert "There is nobody here to scan." in html(app, game)
    chef = posted(game, "Chef")
    chef["location"] = dict(game.player_data["location"])
    assert f">{escape(chef['name'])} (Chef)</button>" in html(app, game)

    game = playing("Captain")
    game.open_panel("broadcast")
    page = html(app, game)
    assert ">Security to the Bridge.</button>" in page and 'name="text" type="text" maxlength="200"' in page

    game = playing("Miner")
    game.player_data["mining"]["identified"] = ["gold_ore"]
    game.open_panel("ore_log")
    page = html(app, game)
    assert "1 of 5 identified this shift." in page and page.count('<p class="note muted">???</p>') == 4
    assert "<b>Gold Ore</b><br>Exports for 60 credits. Found on Kessar IV, Pyros, Verdis." in page

    game = playing("Doctor")
    posted(game, "Chef")["limbs"]["head"] = 20
    game.open_panel("crew_vitals", read_only=True)
    assert ">Treat</button>" not in html(app, game)


def test_the_stock_market_screen_on_the_pda_has_no_trade_form(app):
    game = playing("Staff Assistant")
    game.open_panel("stock_market", read_only=True, selected=game.market_engine.companies[0].name)
    page = html(app, game)
    assert "Trade at the computer in your quarters." in page and ">Back to PDA</button>" in page
    assert "data-share-input" not in page
    game.ui["panels"] = [{"type": "stock_market", "selected": game.market_engine.companies[0].name}]
    page = html(app, game)
    assert "data-share-input" in page and ">Back to Computer</button>" in page


def test_the_inventory_offers_a_scan_only_with_the_pda_in_hand(app):
    for pda, shown in (("left", True), (False, False)):
        game = playing("Chef", pda=pda)
        add_to_inventory(game.player_data, get_item_definition("tomato"))
        game.open_panel("inventory")
        game.perform("panel.select", {"index": 0})
        assert (">Scan with PDA</button>" in html(app, game)) is shown


def test_the_file_screens_at_the_computer_and_on_the_pda(app):
    game = computer(playing("Chef", pda=False))
    game.player_data["files"] = {"home/list.txt": "eggs & <flour>"}
    page = html(app, game)
    for text in ("<h2>Files</h2>", ">Chef.md</button>", ">Kitchen.md</button>", ">list.txt</button>",
                 'data-action="panel.new"', 'data-action="panel.delete" data-args=\'{"path": "home/list.txt"}\''):
        assert text in page, text

    game.perform("panel.open", {"path": "home/list.txt"})
    page = html(app, game)
    text_box = '<div class="text-block file-text" data-scroll-key="file-text:home/list.txt">eggs &amp; &lt;flour&gt;</div>'
    assert page.index(">Edit</button>") < page.index(">Close</button>") < page.index(text_box) < page.index(
        ">Delete</button>")
    assert page.count(">Edit</button>") == 1
    game.perform("panel.edit", {})
    assert 'spellcheck="false">eggs &amp; &lt;flour&gt;</textarea>' in html(app, game)
    game.ui["panels"] = game.ui["panels"][:2]

    game.perform("panel.open", {"path": "guide/Kitchen.md"})
    page = html(app, game)
    assert 'data-scroll-key="file-text:guide/Kitchen.md"><h1>Kitchen</h1>\n<p>' in page
    for button in (">Edit</button>", ">Delete</button>", "Restore Original"):
        assert button not in page, button

    game.ui["panels"] = [{"type": "files", "read_only": True}]
    page = html(app, game)
    assert "Your PDA only reads files." in page and 'data-action="panel.delete"' not in page
    assert 'data-action="panel.new"' not in page
    game.perform("panel.open", {"path": "home/list.txt"})
    page = html(app, game)
    assert ">Edit</button>" not in page and ">Delete</button>" not in page
    game.player_data["files"] = {}
    game.ui["panels"] = [{"type": "files", "read_only": True}]
    assert "You haven't written any files yet." in html(app, game)


def test_the_computer_opens_the_files(app):
    game = playing("Chef", pda=False)
    game.open_panel("computer")
    assert ">Files</button>" in html(app, game)


# --- Guide files from the wiki ----------------------------------------------------------

def test_a_wiki_page_becomes_markdown_text(app):
    with app.test_request_context():
        stores = file_text("Station Stores")
        botanist = file_text("Botanist")
    assert stores.startswith("# Station Stores\n\nThe departments run on what the others make.")
    assert "| Store | Filled by | Used by | Starts with | Holds |\n| --- | --- | --- | --- | --- |\n| Ore |" in stores
    assert "\n\n## When the crew hold the jobs\n\n" in stores
    assert "- The Miner sends up 2 ore every 60 seconds.\n- The Botanist sends" in stores
    assert "- **Miner**: sell ore at the [Cargo](Cargo.md) Bay's export counter.\n" in stores
    assert "Player Guide" not in stores and "<" not in stores and stores.endswith(".\n")

    assert botanist.startswith("# Botanist\n\n**Department**\n\nCivilian\n\n")
    assert "**Stations**\n\n- Botany Lab: Botany Station\n\n" in botanist
    assert "**Crop Request**: the Bartender asks for a piece of produce you carry or have growing" in botanist


def test_markdown_renders_as_headings_paragraphs_lists_emphasis_and_tables():
    text = ("# Title\n\nOne line\nand the next.\n\n## Part\n### Bit\n#### Not a heading\n\n"
            "- **Bold** item\n- *Italic* item\n\n| A | B |\n| --- | --- |\n| 1 | **2** |\n\n| No | Header |\n")
    assert render_markdown(text) == "\n".join((
        "<h1>Title</h1>",
        "<p>One line and the next.</p>",
        "<h2>Part</h2>",
        "<h3>Bit</h3>",
        "<p>#### Not a heading</p>",
        "<ul><li><b>Bold</b> item</li><li><i>Italic</i> item</li></ul>",
        '<table class="wiki-table"><thead><tr><th>A</th><th>B</th></tr></thead>'
        "<tbody><tr><td>1</td><td><b>2</b></td></tr></tbody></table>",
        '<table class="wiki-table"><tbody><tr><td>No</td><td>Header</td></tr></tbody></table>',
    ))


def test_markdown_shows_any_html_in_a_file_as_text():
    assert render_markdown("<script>alert(1)</script> & **<b>**") == (
        "<p>&lt;script&gt;alert(1)&lt;/script&gt; &amp; <b>&lt;b&gt;</b></p>")


def test_a_guide_file_keeps_the_wiki_pages_links_to_other_pages(app):
    with app.test_request_context():
        assert "See [Health](Health.md)." in file_text("Items and Hands")
        assert "guide index" in file_text("Getting Started") and "[guide index]" not in file_text("Getting Started")


def test_a_link_opens_only_a_file_in_the_guide_folder():
    assert render_markdown("See [Health](Health.md), [Cargo](Cargo.md) and [<b>](x.md).", ["Health.md"]) == (
        '<p>See <button type="button" class="link-button" data-action="panel.follow" '
        "data-args='{&#34;name&#34;: &#34;Health.md&#34;}'>Health</button>, Cargo and &lt;b&gt;.</p>")


def reading_items_and_hands_on_the_pda():
    game = playing("Chef")
    game.perform("game.pda", {})
    game.perform("panel.files", {})
    game.perform("panel.open", {"path": "guide/Items and Hands.md"})
    return game


def test_following_a_link_opens_that_guide_file_on_top_and_back_returns(app):
    game = reading_items_and_hands_on_the_pda()
    page = html(app, game)
    assert 'data-action="panel.follow"' in page and 'data-scroll-key="file-text:guide/Items and Hands.md"' in page
    assert 'data-action="panel.back"' not in page and 'data-action="panel.close_reading"' in page
    game.perform("panel.back", {})
    assert game.top_panel()["path"] == "guide/Items and Hands.md"
    for name in ("Cargo.md", "../home/home.md", "Nothing.md"):
        game.perform("panel.follow", {"name": name})
        assert game.top_panel()["path"] == "guide/Items and Hands.md", name
    game.perform("panel.follow", {"name": "Health.md"})
    assert game.top_panel() == {"type": "file", "path": "guide/Health.md", "read_only": True, "from_link": True}
    page = html(app, game)
    assert 'data-scroll-key="file-text:guide/Health.md"' in page and "file-text:guide/Items and Hands.md" not in page
    assert page.index(">Back</button>") < page.index(">Close</button>") < page.index('class="text-block')
    game.perform("panel.back", {})
    assert game.top_panel()["path"] == "guide/Items and Hands.md"


def test_close_leaves_every_linked_file_for_the_files_list():
    game = reading_items_and_hands_on_the_pda()
    game.perform("panel.follow", {"name": "Health.md"})
    game.perform("panel.follow", {"name": "Hazards.md"})
    assert [panel["type"] for panel in game.ui["panels"]][-4:] == ["files", "file", "file", "file"]
    game.perform("panel.close_reading", {})
    assert game.top_panel()["type"] == "files"


def test_a_guide_page_and_the_sample_home_file_render_with_no_markdown_left(app):
    with app.test_request_context():
        pages = (file_text("Station Stores"), file_text("Botanist"), STARTING_FILES["home/home.md"])
    for page in pages:
        html_text = re.sub(r"<[^>]+>", "", render_markdown(page))
        assert "**" not in html_text and "| " not in html_text and "\n#" not in "\n" + html_text, page[:20]
