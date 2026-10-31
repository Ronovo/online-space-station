import base64
import time
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from helpers import create_character, post, register

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY = base64.b64encode(KEY.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)).decode()


def issue(sub, aud="space-online", expires_in=300):
    now = int(time.time())
    return jwt.encode({"iss": "portfolio", "aud": aud, "sub": sub, "name": f"player{sub}", "iat": now,
                       "exp": now + expires_in}, KEY, algorithm="RS256")


@pytest.fixture
def portfolio(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_SSO_URL", "http://portfolio.test")
    monkeypatch.setenv("PORTFOLIO_SSO_PUBLIC_KEY", PUBLIC_KEY)


def portfolio_login(client, sub, token=None):
    query = parse_qs(urlsplit(client.get("/sso/login").location).query)
    assert query["app"] == ["space-online"]
    return client.post("/sso/callback", data={"state": query["state"][0], "token": token or issue(sub)})


def username(client):
    with client.session_transaction() as session:
        return session.get("username")


def test_portfolio_login_is_off_without_config(client, monkeypatch):
    monkeypatch.delenv("PORTFOLIO_SSO_URL", raising=False)
    assert b"portfolio-button" not in client.get("/login").data
    assert client.get("/sso/login").status_code == 404


def test_first_login_asks_before_making_an_account(portfolio, app):
    phone = app.test_client()
    page = phone.get("/login").data
    assert b"Log In with Portfolio Account" in page and b'data-portfolio-url="http://portfolio.test"' in page
    res = portfolio_login(phone, "1")
    assert res.status_code == 302 and res.location.endswith("/link-account")
    assert username(phone) is None
    assert b"This is the first time player1 has logged in here." in phone.get("/link-account").data


def test_a_new_account_is_shared_by_every_device(portfolio, app):
    phone = app.test_client()
    portfolio_login(phone, "1")
    res = post(phone, "/link-account", action="new")
    assert res.status_code == 302 and res.location.endswith("/character/new")
    res = post(phone, "/character/new", name="Ava", department="Engineering", job="Engineer")
    assert res.status_code == 302 and res.location.endswith("/play")

    laptop = app.test_client()
    res = portfolio_login(laptop, "1")
    assert res.status_code == 302 and res.location.endswith("/")
    assert username(laptop) == "player1"
    assert b"Ava" in laptop.get("/").data


def test_an_existing_account_can_be_linked_once(portfolio, app):
    laptop = app.test_client()
    register(laptop, "pilot")
    create_character(laptop)

    phone = app.test_client()
    portfolio_login(phone, "3")
    res = post(phone, "/link-account", action="link", username="pilot", password="wrong!")
    assert res.status_code == 200 and b"Incorrect username or password" in res.data
    res = post(phone, "/link-account", action="link", username="pilot", password="hunter22")
    assert res.status_code == 302 and res.location.endswith("/")
    assert username(phone) == "pilot"

    tablet = app.test_client()
    portfolio_login(tablet, "3")
    assert username(tablet) == "pilot"

    other = app.test_client()
    portfolio_login(other, "4")
    res = post(other, "/link-account", action="link", username="pilot", password="hunter22")
    assert b"That account is already linked to another portfolio account." in res.data
    assert username(other) is None


def test_a_taken_name_gets_a_number(portfolio, app):
    register(app.test_client(), "player2")
    client = app.test_client()
    portfolio_login(client, "2")
    post(client, "/link-account", action="new")
    assert username(client) == "player22"


def test_cancel_and_no_waiting_login(portfolio, app):
    client = app.test_client()
    res = client.get("/link-account")
    assert res.status_code == 302 and res.location.endswith("/login")
    portfolio_login(client, "5")
    res = post(client, "/link-account", action="cancel")
    assert res.status_code == 302 and res.location.endswith("/login")
    assert client.get("/link-account").location.endswith("/login")


def test_portfolio_accounts_have_no_usable_password(portfolio, app):
    client = app.test_client()
    portfolio_login(client, "6")
    post(client, "/link-account", action="new")
    post(client, "/logout")
    res = post(client, "/login", username="player6", password="")
    assert res.status_code == 200 and b"Incorrect username or password" in res.data


def test_a_linked_account_returns_to_the_page_it_came_from(portfolio, app):
    client = app.test_client()
    portfolio_login(client, "7")
    post(client, "/link-account", action="new")
    post(client, "/logout")

    query = parse_qs(urlsplit(client.get("/sso/login?next=/play").location).query)
    res = client.post("/sso/callback", data={"state": query["state"][0], "token": issue("7")})
    assert res.status_code == 302 and res.location == "/play"
    assert username(client) == "player7"


def test_a_first_login_ignores_next(portfolio, client):
    query = parse_qs(urlsplit(client.get("/sso/login?next=/play").location).query)
    res = client.post("/sso/callback", data={"state": query["state"][0], "token": issue("8")})
    assert res.status_code == 302 and res.location.endswith("/link-account")


def refused(client, res):
    assert res.status_code == 302 and res.location.endswith("/login")
    assert username(client) is None
    return client.get("/login").data


@pytest.mark.parametrize("token", [issue("1", aud="casino"), issue("1", expires_in=-10)])
def test_bad_tokens_are_refused(portfolio, client, token):
    assert b"That portfolio login didn&#39;t check out. Try again." in refused(client, portfolio_login(client, "1", token))


def test_callback_needs_the_state_from_this_browser(portfolio, client):
    client.get("/sso/login")
    res = client.post("/sso/callback", data={"state": "wrong", "token": issue("1")})
    assert b"Your portfolio login expired. Try again." in refused(client, res)


def test_callback_without_a_login_in_progress_is_expired(portfolio, client):
    res = client.post("/sso/callback", data={"state": "any", "token": issue("1")})
    assert b"Your portfolio login expired. Try again." in refused(client, res)
