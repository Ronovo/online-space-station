import re

import pytest
from markupsafe import escape

from helpers import new_game, register, start_round
from space_online.game.helper_methods import lighting_helper, oxygen_helper, power_constants, random_events, rounds
from space_online.game.character_methods.character_creation import JOBS
from space_online.game.helper_methods.artifacts import ARTIFACT_KINDS, TELE_MULTIPLIERS
from space_online.game.helper_methods.errands import MAX_OPEN_DUTIES
from space_online.game.helper_methods.pda import LOW_ORE, MAX_FILE_CHARS, MAX_MESSAGES, MAX_OWN_FILES
from space_online.game.helper_methods.stores import MAX_ORE, STARTING_ORE
from space_online.game.objects.botany_items import BOTANY_ITEMS, BOTANY_SEED_IDS, BOTANY_VEND_CATALOG
from space_online.game.objects.items import get_item_definition
from space_online.game.objects.mining_items import SURFACE_ORES
from space_online.game.special_rooms.cargo import COUNTER_PRICES, ORDER_PRICES
from space_online.game.special_rooms import quarters
from space_online.webapp.wiki import PAGES, WIKI_SECTIONS, job_stations, page_slug


def text(response):
    return response.get_data(as_text=True)


def test_the_index_lists_basics_then_systems_then_jobs_without_a_login(client):
    response = client.get("/wiki/")
    assert response.status_code == 200
    html = text(response)
    assert [section for section, _ in WIKI_SECTIONS] == ["Basics", "Systems", "Jobs"]
    positions = [html.index(f"<h2>{section}</h2>") for section, _ in WIKI_SECTIONS]
    assert positions == sorted(positions)
    for _, titles in WIKI_SECTIONS:
        for title in titles:
            assert f'href="/wiki/{page_slug(title)}"' in html


@pytest.mark.parametrize("slug", sorted(PAGES))
def test_every_page_opens_without_a_login_and_its_guide_links_work(client, slug):
    response = client.get(f"/wiki/{slug}")
    assert response.status_code == 200
    html = text(response)
    assert f"<h1>{PAGES[slug]}</h1>" in html
    assert 'aria-current="page"' in html
    for link in set(re.findall(r'href="(/wiki/[^"]*)"', html)):
        assert client.get(link).status_code == 200, link


def test_page_names_use_underscores_and_unknown_pages_are_missing(client):
    assert page_slug("Head of Personnel") == "Head_of_Personnel"
    assert client.get("/wiki/Head_of_Personnel").status_code == 200
    for name in ("Head of Personnel", "Nowhere"):
        assert client.get(f"/wiki/{name}").status_code == 404


@pytest.mark.parametrize("name, page", [("head_of_personnel", "Head_of_Personnel"),
                                        ("getting-started", "Getting_Started"), ("bridge", "Bridge_and_Personnel"),
                                        ("Head-of-Personnel", "Head_of_Personnel")])
def test_the_wrong_case_hyphens_and_the_start_of_one_page_name_redirect_to_the_page(client, name, page):
    response = client.get(f"/wiki/{name}")
    assert (response.status_code, response.headers["Location"]) == (302, f"/wiki/{page}")


def test_a_name_that_starts_two_pages_is_missing(client):
    assert client.get("/wiki/station_st").status_code == 404


def test_every_job_has_a_page():
    jobs = dict(WIKI_SECTIONS)["Jobs"]
    assert set(jobs) == set(JOBS)


def test_a_job_page_shows_the_job_from_the_game(client):
    html = text(client.get("/wiki/Doctor"))
    assert f"<dd>{JOBS['Doctor']['credits']}</dd>" in html
    assert str(escape(JOBS["Doctor"]["description"])) in html
    assert "<li>MedBay: MedBay Station</li>" in html


def test_job_stations_follow_door_access():
    assert job_stations("Staff Assistant") == []
    assert job_stations("Head of Personnel") == ["Bridge: HoP's Station", "MedBay: MedBay Station",
                                                 "Engineering Bay: Engineering Station", "Bar: Bartender Station",
                                                 "Kitchen: Chef Station", "Botany Lab: Botany Station",
                                                 "Chemistry: Chemistry Station", "Mining Bay: Miner Station",
                                                 "Cargo Bay: Cargo Station", "Research Lab: the Artifact Section",
                                                 "Research Lab: the Teleporter Room",
                                                 "Atmospherics: Atmospherics Station"]
    assert "Bridge: Captain's Station" in job_stations("Captain")
    assert len(job_stations("Captain")) == 14
    assert job_stations("Scientist") == ["Chemistry: Chemistry Station", "Research Lab: the Artifact Section",
                                         "Research Lab: the Teleporter Room", "Atmospherics: Atmospherics Station"]
    assert job_stations("Chef") == ["Kitchen: Chef Station"]


def test_the_kitchen_chemistry_and_mining_pages_quote_the_game(client):
    assert "<tr><td>Omelette</td><td>Egg, Cheese, Butter</td><td>18</td></tr>" in text(client.get("/wiki/Kitchen"))
    assert "<tr><td>Potato</td><td>Starch</td></tr>" in text(client.get("/wiki/Chemistry"))
    assert "<td>Sand Crawler, Dune Stalker</td>" in text(client.get("/wiki/Mining"))


def test_the_research_page_sets_out_the_teleporter_formulas(client):
    html = text(client.get("/wiki/Research"))
    for line in ("console = m &times; station + c", "m = (a2 - a1) &divide; (r2 - r1)", "c = a1 - m &times; r1",
                 "X = 2 &times; 6 + 3 = 15 and Y = 4 &times; 6 - 1 = 23",
                 f"<b>m</b> is a multiplier: {', '.join(map(str, TELE_MULTIPLIERS))}."):
        assert line in html, line
    assert f"<td>{ARTIFACT_KINDS['healer']['shows']}</td>" in html


def test_the_cargo_hazards_stores_botany_antagonists_and_duties_pages_quote_the_game(client):
    cargo = text(client.get("/wiki/Cargo"))
    assert f"<tr><td>Medkit</td><td>{ORDER_PRICES['medkit']}</td><td>{COUNTER_PRICES['medkit']}</td></tr>" in cargo
    assert "<tr><td>Gold Ore</td><td>60</td></tr>" in cargo
    assert "<tr><td>Hull breach</td><td>Wrench</td><td>oxygen</td></tr>" in text(client.get("/wiki/Hazards"))
    assert f"<td>{STARTING_ORE}</td><td>{MAX_ORE}</td>" in text(client.get("/wiki/Station_Stores"))
    assert "<td>Golden Apple</td>" in text(client.get("/wiki/Botany"))
    antagonists = text(client.get("/wiki/Antagonists"))
    assert "Out to steal 400 credits: needs 400 credits stolen." in antagonists
    assert "<td>Cripple the station&#39;s systems</td>" in antagonists
    assert f"You can have {MAX_OPEN_DUTIES} at once" in text(client.get("/wiki/Duties_and_Job_Events"))


def test_the_pda_page_quotes_the_game(client):
    html = text(client.get("/wiki/PDA"))
    for line in (f"It keeps the last {MAX_MESSAGES}.", f"<td>The ore store is down to {LOW_ORE} or less</td>",
                 f"<b>home/</b> holds files you write yourself: up to {MAX_OWN_FILES} of them",
                 f"{MAX_FILE_CHARS} characters.",
                 f"The {len(SURFACE_ORES)} ores found in veins"):
        assert line in html, line
    assert f"There are {len(SURFACE_ORES)} ores to identify" in text(client.get("/wiki/Mining"))


def test_the_pda_page_says_a_chef_scan_shows_what_it_mends_only_for_mutant_produce(client):
    html = " ".join(text(client.get("/wiki/PDA")).split())
    assert "how much hunger it feeds and, for mutant produce, what it mends" in html
    assert "how much hunger it feeds and what it mends" not in html


def test_the_botany_page_lists_the_vending_machine_from_the_game(client):
    html = text(client.get("/wiki/Botany"))
    price, stock = BOTANY_VEND_CATALOG["chainsaw"]
    assert f"<tr><td>Chainsaw</td><td>{price}</td><td>{stock}</td></tr>" in html


def test_the_login_and_home_pages_link_to_the_guide(client):
    assert 'href="/wiki/"' in text(client.get("/login"))
    register(client)
    assert 'href="/wiki/"' in text(client.get("/"))
    start_round(client)
    assert 'href="/wiki/"' in text(client.get("/"))


def test_the_hazards_page_lists_every_hallway_accident(client):
    page = text(client.get("/wiki/Hazards"))
    accidents = [event["title"] for event in random_events._static_events(new_game()) if event["type"] == "bad"]
    assert accidents and all(f"<td>{title}</td>" in page for title in accidents)
    assert "<td>Chemical Spill</td><td>Left leg 5-10%, burn 5-15%, poison 10-20%</td>" in page


def test_the_life_support_page_works_its_damage_rate_out_from_the_game(client, monkeypatch):
    page = text(client.get("/wiki/Life_Support"))
    assert "16% a minute just past a limit" in page and "32% a minute the further past it" in page
    monkeypatch.setattr(oxygen_helper, "BASE_DAMAGE_PER_TICK", 8)
    page = text(client.get("/wiki/Life_Support"))
    assert "32% a minute just past a limit" in page and "64% a minute the further past it" in page


def test_the_power_page_says_when_the_lights_dim(client, monkeypatch):
    monkeypatch.setattr(lighting_helper, "DIM_LIGHTING_BATTERY", 21)
    monkeypatch.setattr(lighting_helper, "EMERGENCY_LIGHTING_BATTERY", 7)
    page = text(client.get("/wiki/Power"))
    assert "At 21% battery or less" in page and "at 7% or less they drop to red" in page


def test_the_shuttle_page_quotes_the_game(client, monkeypatch):
    monkeypatch.setattr(rounds, "LAUNCH_WARNING_SECONDS", 20)
    monkeypatch.setattr(rounds, "LAUNCH_THROW_DAMAGE_RANGE", (11, 22))
    monkeypatch.setattr(rounds, "FLIGHT_EVENT_RANGE_SECONDS", (5, 45))
    monkeypatch.setattr(quarters, "SHUTTLE_BED_HEAL_PER_MINUTE", 35)
    monkeypatch.setattr(random_events, "TURBULENCE_DAMAGE_RANGE", (6, 16))
    monkeypatch.setattr(random_events, "FLIGHT_REMEDY_REWARD_RANGE", (40, 90))
    page = " ".join(text(client.get("/wiki/Rounds_and_the_Shuttle")).split())
    for line in ("the shuttle warns 20 seconds before it leaves", "hurts a limb by 11-22%",
                 "it mends every limb by 35% a minute", "one thing happens 5 to 45 seconds into the flight",
                 "hurts a limb by 6-16% if you aren't strapped in", "they pay you 40-90 credits",
                 "<tr><td>Security</td><td>Security Guards and the Captain</td>"):
        assert line in page, line
    assert "The bed in the crew shuttle's Medical Bay mends them faster." in " ".join(
        text(client.get("/wiki/Health")).split())


def test_the_power_page_quotes_the_game_s_power_alerts(client, monkeypatch):
    page = " ".join(text(client.get("/wiki/Power")).split())
    for alert in (power_constants.LOW_POWER_ALERT, power_constants.POWER_OUTAGE_ALERT):
        assert str(escape(alert)) in page, alert
    monkeypatch.setattr(power_constants, "LOW_POWER_ALERT", "Battery low. Light the engine.")
    assert "Battery low. Light the engine." in text(client.get("/wiki/Power"))


def test_the_cargo_page_sells_every_botany_product_aloe_included(client):
    grown = [get_item_definition(BOTANY_ITEMS[seed_id]["attributes"]["produces"])["name"]
             for seed_id in BOTANY_SEED_IDS]
    assert "Aloe" in grown
    assert f": {', '.join(grown)}</td>" in text(client.get("/wiki/Cargo"))
