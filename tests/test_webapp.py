import json

import pytest

from helpers import CSRF, QUESTION, act, post, register, set_csrf, start_round
from space_online import webapp
from space_online.game.character_methods.character_creation import JOBS, group_jobs_by_department
from space_online.game.helper_methods.rounds import MODE_DESCRIPTIONS
from space_online.webapp import db


def test_home_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_register_logs_in_and_goes_to_the_lobby(client):
    response = register(client)
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    page = client.get("/").data
    assert b"Start Career" in page and b"Start Round" in page and b"Delete Career" not in page


def test_register_rejects_invalid_username(client):
    response = register(client, username="x")
    assert response.status_code == 200
    assert b"Usernames are 3-32 characters" in response.data


def test_register_rejects_mismatched_passwords(client):
    response = post(client, "/register", username="pilot", password="hunter22", confirm_password="other22")
    assert b"Passwords do not match." in response.data


def test_register_rejects_taken_username(client, app):
    register(client)
    response = register(app.test_client(), username="PILOT")
    assert b"That username is already taken." in response.data


def test_login_with_wrong_password_fails(client):
    register(client)
    post(client, "/logout")
    response = post(client, "/login", username="pilot", password="wrong-password")
    assert b"Incorrect username or password." in response.data


def test_login_and_logout(client):
    register(client)
    post(client, "/logout")
    response = post(client, "/login", username="pilot", password="hunter22")
    assert response.headers["Location"].endswith("/")
    response = post(client, "/logout")
    assert response.headers["Location"].endswith("/login")
    assert client.get("/").status_code == 302


def test_post_without_csrf_token_is_rejected(client):
    response = client.post("/register", data={"username": "pilot", "password": "hunter22",
                                             "confirm_password": "hunter22"})
    assert response.status_code == 400


@pytest.mark.parametrize("fields, message", [
    ({"job": "Janitor"}, b"Please select a job."),
    ({"name": "  "}, b"Please enter a character name."),
    ({"mode": "sandbox"}, b"Choose a kind of round."),
    ({"mode": "career"}, b"Start a career first."),
])
def test_a_round_that_cannot_start_says_why_in_the_lobby(client, fields, message):
    register(client)
    response = start_round(client, **fields)
    assert response.headers["Location"] == "/"
    assert message in client.get("/").data
    assert client.get("/play").headers["Location"] == "/"


def test_start_a_single_round_and_play(client):
    register(client)
    response = start_round(client)
    assert response.headers["Location"].endswith("/play")
    response = client.get("/play")
    assert response.status_code == 200 and b"ALERT: GREEN" in response.data
    lobby = client.get("/").data
    assert b"Round in Progress" in lobby and b"Abandon Round" in lobby and b"Start Round" not in lobby


def test_act_tick_returns_screen_and_skips_unchanged_html(client):
    register(client)
    start_round(client)

    first = act(client, action="tick").get_json()
    assert {"hash", "title", "choice", "html"} <= first.keys()

    stale = act(client, action="tick", hash="stale").get_json()
    assert "html" in stale

    current = act(client, action="tick", hash=stale["hash"]).get_json()
    assert current["hash"] == stale["hash"] and "html" not in current


def test_act_args_that_are_not_an_object_are_ignored(client, app):
    register(client)
    start_round(client)
    with app.app_context():
        before = db.load_save(1)[0]["shift"]["location"]
    response = act(client, action="game.move", args=["north"])
    assert "redirect" not in response.get_json()
    with app.app_context():
        assert db.load_save(1)[0]["shift"]["location"] == before


def test_act_with_no_round_in_progress_goes_back_to_the_lobby(client):
    register(client)
    assert act(client, action="tick").get_json() == {"redirect": "/"}
    start_round(client)
    post(client, "/round/abandon")
    assert act(client, action="tick").get_json() == {"redirect": "/"}


def test_delete_character_needs_confirmation(client):
    register(client)
    start_round(client)
    response = post(client, "/character/delete")
    assert response.headers["Location"].endswith("/")
    assert client.get("/play").status_code == 200

    response = post(client, "/character/delete", confirm="yes")
    assert response.headers["Location"] == "/"
    assert client.get("/play").headers["Location"] == "/"


def test_progress_persists_across_logins(client):
    register(client)
    start_round(client, name="Persistent Pat")
    post(client, "/logout")
    post(client, "/login", username="pilot", password="hunter22")
    assert b"Persistent Pat" in client.get("/").data


def test_a_secret_key_is_made_once_and_kept(tmp_path, monkeypatch):
    monkeypatch.delenv("SPACE_ONLINE_SECRET_KEY", raising=False)
    folder = str(tmp_path / "instance")
    key = webapp._load_secret_key(folder)
    assert len(key) == 64
    assert webapp._load_secret_key(folder) == key
    monkeypatch.setenv("SPACE_ONLINE_SECRET_KEY", "from the shell")
    assert webapp._load_secret_key(folder) == "from the shell"


def test_the_app_runs_on_its_own_settings(tmp_path, monkeypatch):
    real_flask = webapp.Flask
    monkeypatch.setattr(webapp, "Flask", lambda name, instance_path: real_flask(name, instance_path=str(tmp_path)))
    monkeypatch.delenv("SPACE_ONLINE_SECRET_KEY", raising=False)
    monkeypatch.setenv("SECURE_COOKIES", "1")
    app = webapp.create_app()
    assert app.config["DATABASE"] == str(tmp_path / "space_online.sqlite3")
    assert app.config["SECRET_KEY"] == (tmp_path / "secret_key").read_text(encoding="utf-8")
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_five_wrong_passwords_lock_the_username(client):
    register(client)
    post(client, "/logout")
    for _ in range(5):
        post(client, "/login", username="pilot", password="wrong-password")
    response = post(client, "/login", username="pilot", password="hunter22")
    assert b"Too many wrong passwords. Wait a minute and try again." in response.data


def test_register_shows_its_form_and_explains_a_short_password(client):
    assert client.get("/register").status_code == 200
    response = post(client, "/register", username="pilot", password="abc", confirm_password="abc",
                    question=QUESTION, answer="rex")
    assert b"Passwords must be 6-128 characters." in response.data


def test_the_reset_form_starts_by_asking_for_the_username(client):
    register(client)
    for response in (client.get("/reset-password"), post(client, "/reset-password", username="  ")):
        assert response.status_code == 200
        assert QUESTION.encode() not in response.data


def test_a_reset_needs_a_usable_new_password(client, app):
    register(client)
    response = post(app.test_client(), "/reset-password", username="pilot", answer="rex", password="abc",
                    confirm_password="abc")
    assert b"Passwords must be 6-128 characters." in response.data


def test_the_single_round_form_lists_every_job_by_department(client):
    register(client)
    page = client.get("/").data.decode()
    assert '<option value="Captain">Captain - starts with 10000 cr</option>' in page
    for department, jobs in group_jobs_by_department():
        group = page.split(f'<optgroup label="{department}">')[1].split("</optgroup>")[0]
        assert " ".join(group.split()) == " ".join(
            f'<option value="{job}">{job} - starts with {JOBS[job]["credits"]} cr</option>' for job in jobs)


def test_the_lobby_offers_a_chooser_and_keeps_each_form_in_its_own_panel(client):
    register(client)
    page = client.get("/").data.decode()
    assert 'data-lobby-choose="career"' in page and 'data-lobby-choose="single"' in page
    career, single = page.split('data-lobby-panel="single"')
    assert 'data-lobby-panel="career"' in career and 'class="lobby-block hidden"' in career
    assert "/career/new" in career and "Start Career" in career and "round-mode" not in career
    assert "Start Round" in single and "Start Career" not in single and "/career/new" not in single
    assert single.count("data-lobby-back") == 1 and career.count("data-lobby-back") == 1


def test_the_mode_is_a_drop_down_with_descriptions(client):
    register(client)
    page = client.get("/").data.decode()
    assert '<select name="mode" id="round-mode">' in page and 'type="radio"' not in page
    for mode, description in MODE_DESCRIPTIONS.items():
        assert f'<option value="{mode}" data-description="{description}">{mode.title()}</option>' in page
    assert '<p class="muted" id="round-mode-description"></p>' in page


@pytest.mark.parametrize("mode", ["peaceful", "antagonist"])
def test_each_drop_down_mode_starts_a_round(client, app, mode):
    register(client)
    assert start_round(client, mode=mode).headers["Location"].endswith("/play")
    with app.app_context():
        assert db.load_save(1)[0]["shift"]["round"]["mode"] == mode


def test_a_round_in_progress_hides_the_chooser_and_leaves_nothing_hidden(client):
    register(client)
    start_round(client)
    page = client.get("/").data.decode()
    assert "lobby-chooser" not in page and " hidden" not in page


def test_a_second_round_cannot_start_while_one_is_in_progress(client):
    register(client)
    start_round(client)
    response = start_round(client, name="Twin")
    assert response.headers["Location"] == "/"
    page = client.get("/").data
    assert b"You already have a round in progress." in page
    assert b"Ada" in page and b"Twin" not in page


def test_an_act_body_that_is_not_an_object_is_a_tick(client):
    register(client)
    start_round(client)
    set_csrf(client)
    response = client.post("/api/act", data=json.dumps(["game.move"]), content_type="application/json",
                           headers={"X-CSRF-Token": CSRF})
    assert response.status_code == 200
    assert "hash" in response.get_json()


def test_save_and_exit_sends_the_page_home(client):
    register(client)
    start_round(client)
    assert act(client, action="game.save_and_exit").get_json() == {"redirect": "/"}


def test_the_coverage_reports_are_served_from_their_folder(client, monkeypatch, tmp_path):
    reports = tmp_path / "coverage"
    (reports / "python").mkdir(parents=True)
    (reports / "index.html").write_text("landing page", encoding="utf-8")
    (reports / "python" / "index.html").write_text("python report", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setattr(webapp, "COVERAGE_DIR", str(reports))

    def get(path):
        with client.get(path) as response:
            return response.status_code, response.data

    assert get("/coverage")[0] == 308
    assert get("/coverage/") == (200, b"landing page")
    assert get("/coverage/python/") == (200, b"python report")
    for path in ("/coverage/js/", "/coverage/../secret.txt", "/coverage/%2e%2e/secret.txt"):
        assert get(path)[0] == 404, path


def test_a_portfolio_account_links_to_one_user_only(app):
    with app.app_context():
        first = db.create_user("first", "hash")
        second = db.create_user("second", "hash")
        assert db.link_portfolio(first, "7")
        assert not db.link_portfolio(second, "7")
        assert db.get_user_by_portfolio("7")["id"] == first


def test_a_failed_update_leaves_the_character_as_it_was(client, app):
    register(client)
    start_round(client)

    def crash(save, ui_state):
        save["shift"]["credits"] = 0
        raise RuntimeError("game crashed")

    with app.app_context():
        user_id = db.get_user_by_name("pilot")["id"]
        with pytest.raises(RuntimeError):
            db.update_character(user_id, crash)
        assert db.update_character(user_id, lambda save, ui_state: (
            save["shift"]["credits"], save, ui_state)) == 1000


def test_a_csrf_token_that_is_not_ascii_is_rejected_like_any_wrong_one(client):
    set_csrf(client)
    response = client.post("/api/act", json={"action": "tick"}, headers={"X-CSRF-Token": "\u00e9"})
    assert response.status_code == 400


def career_panel_and_the_rest(page):
    start = page.index('data-lobby-panel="career"')
    end = page.index('data-lobby-panel="single"')
    return page[start:end], page[:start] + page[end:]


def test_delete_career_is_only_in_the_career_panel_and_only_with_a_career(client):
    register(client)
    start_round(client)
    panel, rest = career_panel_and_the_rest(client.get("/").data.decode())
    assert "danger-zone" not in panel and "danger-zone" not in rest
    post(client, "/round/abandon")
    post(client, "/career/new", name="Ada")
    panel, rest = career_panel_and_the_rest(client.get("/").data.decode())
    assert panel.count('class="danger-zone"') == 1 and "danger-zone" not in rest
