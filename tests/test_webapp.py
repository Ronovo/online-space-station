import json

import pytest

from helpers import CSRF, QUESTION, act, create_character, post, register, set_csrf
from space_online import webapp
from space_online.webapp import db


def test_home_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_register_logs_in_and_goes_to_character_creation(client):
    response = register(client)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/character/new")


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
    assert response.headers["Location"].endswith("/character/new")
    create_character(client)
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


def test_character_creation_rejects_job_outside_department(client):
    register(client)
    response = create_character(client, department="Civilian", job="Captain")
    assert response.status_code == 200
    assert b"Please select a job." in response.data


def test_create_character_and_play(client):
    register(client)
    response = create_character(client)
    assert response.headers["Location"].endswith("/play")
    response = client.get("/play")
    assert response.status_code == 200
    assert client.get("/character/new").headers["Location"].endswith("/play")


def test_act_tick_returns_screen_and_skips_unchanged_html(client):
    register(client)
    create_character(client)

    first = act(client, action="tick").get_json()
    assert {"hash", "title", "alerts", "choice", "html"} <= first.keys()

    second = act(client, action="tick", hash=first["hash"]).get_json()
    assert ("html" in second) == (second["hash"] != first["hash"])


def test_act_args_that_are_not_an_object_are_ignored(client):
    register(client)
    create_character(client)
    response = act(client, action="game.move", args=["north"])
    assert response.status_code == 200
    assert "redirect" not in response.get_json()


def test_act_without_character_redirects_to_creation(client):
    register(client)
    assert act(client, action="tick").get_json()["redirect"].endswith("/character/new")


def test_delete_character_needs_confirmation(client):
    register(client)
    create_character(client)
    response = post(client, "/character/delete")
    assert response.headers["Location"].endswith("/")
    assert client.get("/play").status_code == 200

    response = post(client, "/character/delete", confirm="yes")
    assert response.headers["Location"].endswith("/character/new")
    assert client.get("/play").headers["Location"].endswith("/character/new")


def test_progress_persists_across_logins(client):
    register(client)
    create_character(client, name="Persistent Pat")
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


def test_the_character_form_lists_the_departments(client):
    register(client)
    response = client.get("/character/new")
    assert response.status_code == 200
    assert b"Select A Department" in response.data


def test_a_second_character_made_at_the_same_moment_is_refused(client, monkeypatch):
    register(client)
    create_character(client)
    with monkeypatch.context() as race:
        race.setattr(db, "character_summary", lambda user_id: None)
        response = create_character(client, name="Twin")
    assert response.headers["Location"].endswith("/")
    page = client.get("/").data
    assert b"Ada" in page and b"Twin" not in page


def test_an_act_body_that_is_not_an_object_is_a_tick(client):
    register(client)
    create_character(client)
    set_csrf(client)
    response = client.post("/api/act", data=json.dumps(["game.move"]), content_type="application/json",
                           headers={"X-CSRF-Token": CSRF})
    assert response.status_code == 200
    assert "hash" in response.get_json()


def test_save_and_exit_sends_the_page_home(client):
    register(client)
    create_character(client)
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
    create_character(client)

    def crash(player_data, ui_state):
        player_data["credits"] = 0
        raise RuntimeError("game crashed")

    with app.app_context():
        user_id = db.get_user_by_name("pilot")["id"]
        with pytest.raises(RuntimeError):
            db.update_character(user_id, crash)
        assert db.update_character(user_id, lambda player_data, ui_state: (
            player_data["credits"], player_data, ui_state)) == 1000

