from ronovo_portfolio_auth.security_questions import QUESTIONS

from space_online.game.character_methods import character_creation
from space_online.game.main import SpaceStationGame

CSRF = "test-csrf-token"
QUESTION = QUESTIONS[0]


def set_csrf(client):
    # Login, register and logout clear the session, so the token is put back before every post.
    with client.session_transaction() as session:
        session["csrf_token"] = CSRF


def post(client, url, **data):
    set_csrf(client)
    return client.post(url, data={"csrf_token": CSRF, **data})


def act(client, **payload):
    set_csrf(client)
    return client.post("/api/act", json=payload, headers={"X-CSRF-Token": CSRF})


def register(client, username="pilot", password="hunter22"):
    return post(client, "/register", username=username, password=password, confirm_password=password,
                question=QUESTION, answer="rex")


def create_character(client, name="Ada", department="Civilian", job="Staff Assistant"):
    return post(client, "/character/new", name=name, department=department, job=job)


def new_game(department="Civilian", job="Staff Assistant"):
    return SpaceStationGame(character_creation.create_character("Ada", department, job))


def reports(game):
    return [title for _, title, *_ in game._messages]
