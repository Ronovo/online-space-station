import re

import pytest
from markupsafe import escape

from helpers import create_character, register
from space_online.game.character_methods.character_creation import JOBS
from space_online.game.objects.botany_items import BOTANY_VEND_CATALOG
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
    for name in ("Head of Personnel", "head_of_personnel", "Nowhere"):
        assert client.get(f"/wiki/{name}").status_code == 404


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
                                                 "Botany Lab: Botany Station"]
    assert "Bridge: Captain's Station" in job_stations("Captain")
    assert len(job_stations("Captain")) == 7


def test_the_botany_page_lists_the_vending_machine_from_the_game(client):
    html = text(client.get("/wiki/Botany"))
    price, stock = BOTANY_VEND_CATALOG["chainsaw"]
    assert f"<tr><td>Chainsaw</td><td>{price}</td><td>{stock}</td></tr>" in html


def test_the_login_and_home_pages_link_to_the_guide(client):
    assert 'href="/wiki/"' in text(client.get("/login"))
    register(client)
    assert 'href="/wiki/"' in text(client.get("/"))
    create_character(client)
    assert 'href="/wiki/"' in text(client.get("/"))
