import time
from types import SimpleNamespace

from flask import render_template
from ronovo_portfolio_auth.security_questions import QUESTIONS

from space_online.game.character_methods import character_creation
from space_online.game.character_methods.character_creation import JOBS
from space_online.game.helper_methods import gas_mix, random_events
from space_online.game.helper_methods.antagonists import THREAT_TYPES
from space_online.game.helper_methods.combat import start_fight
from space_online.game.helper_methods.crew_work import CREW_WORK
from space_online.game.helper_methods.errands import add_duty
from space_online.game.helper_methods.rounds import (
    ANTAGONIST,
    PEACEFUL,
    SHUTTLE_ARRIVAL_SECONDS,
    SHUTTLE_LOCKOUT_SECONDS,
    call_shuttle,
    tick_round,
)
from space_online.game.main import SpaceStationGame
from space_online.game.helper_methods.station_air import AIR_MOLES
from space_online.game.maps.donut import ATMOSPHERICS_KEY, DEPARTURES_KEY, location_from_key
from space_online.game.objects.gases import GAS_TANK, ROOM_TEMP
from space_online.game.objects.items import add_to_inventory, get_item_definition

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


def start_round(client, name="Ada", job="Staff Assistant", mode=PEACEFUL):
    return post(client, "/round/start", name=name, job=job, mode=mode)


def new_game(department="Civilian", job="Staff Assistant", mode=PEACEFUL, extras=False, pda=False, post=None):
    """A game in its first moment. department is the job's own, so a test reads as who is playing.

    The shift's randomly picked extra crew are left out unless extras is set, so a test knows who is aboard. The
    PDA everyone starts with is left out unless pda is "carried" or the hand to hold it in, so a test knows what
    is in the inventory. post is the room key of the post a job with several is given, picked at random without it.
    """
    assert JOBS[job]["department"] == department
    usual_extras, usual_post = character_creation.EXTRA_CREW_RANGE, character_creation._player_post
    if not extras:
        character_creation.EXTRA_CREW_RANGE = (0, 0)
    if post:
        character_creation._player_post = lambda job: post
    try:
        game = SpaceStationGame(character_creation.new_shift("Ada", job, mode=mode))
    finally:
        character_creation.EXTRA_CREW_RANGE, character_creation._player_post = usual_extras, usual_post
    if pda != "carried":
        held = game.player_data["inventory"].pop()
        if pda:
            game.player_data["hands"][pda] = held
    return game


def in_room(room_key, department="Civilian", job="Staff Assistant", room_mode=None, **game_options):
    """A new_game with the player standing in room_key, its menu switched to room_mode when one is given."""
    game = new_game(department, job, **game_options)
    game.player_data["location"] = location_from_key(room_key)
    if room_mode:
        game.ui["room_mode"] = room_mode
    return game


def threat(kind="Wizard", crew_name=None, target=None, **changes):
    """A hidden threat of kind that has not acted yet, hosted by crew_name when one is given."""
    details = THREAT_TYPES[kind]
    return {
        "type": kind, "crew_name": crew_name, "name": f"{crew_name} the {kind}" if crew_name else f"the {kind}",
        "starts_at": 0, "next_act_at": 0, "acts": 0, "reveal_after": 2, "revealed": False, "hp": details["hp"],
        "attack": details["attack"], "extra": details["extra"], "humanoid": details["humanoid"], "location": None,
        "objective": {"kind": details["objective"], "target": target, "progress": 0}, "fate": None, "hurt": [],
        **changes,
    }


def station(*threats, department="Civilian", job="Staff Assistant"):
    """An Antagonist round with only these threats aboard."""
    game = new_game(department, job, ANTAGONIST)
    game.player_data["threats"] = list(threats)
    return game


def in_atmospherics(department="Science", job="Scientist", **game_options):
    """A new game in Atmospherics. A Scientist is posted there."""
    return in_room(ATMOSPHERICS_KEY, department, job, post=ATMOSPHERICS_KEY if job == "Scientist" else None,
                   **game_options)


def at_atmospherics_station(panel=None):
    """A Scientist at the Atmospherics Station, with room.show_<panel> pressed when panel is given."""
    game = in_atmospherics(room_mode="atmospherics_station")
    if panel:
        game.perform(f"room.show_{panel}", {})
    return game


def crew(game, job):
    return next(npc for npc in game.station_crew if npc["job"] == job)


def nobody_covers(game):
    """Take the Captain and the Head of Personnel off duty, so neither covers a post nobody can work."""
    crew(game, "Captain")["on_duty"] = False
    crew(game, "Head of Personnel")["on_duty"] = False


def only_working(game, *jobs):
    """Put every other post's work off, so a test watches these jobs' NPC work on its own."""
    game.player_data["crew_work"] = {room_key: 10 ** 9 for job, room_key in CREW_WORK if job not in jobs}
    return game


def hurt_badly(npc):
    npc["limbs"] = {limb: 10 for limb in npc["limbs"]}
    return npc


def seated(game, *jobs):
    """Put the crew with these jobs in Departures, where they are aboard when the shuttle leaves. Returns them."""
    found = [crew(game, job) for job in jobs]
    for npc in found:
        npc["location"] = location_from_key(DEPARTURES_KEY)
    return found


def stowaway(game):
    """Start a fight with a weak monster."""
    start_fight(game, "monster", {"name": "the stowaway", "hp": 5, "attack": (1, 1), "extra": None,
                                  "humanoid": False}, "It attacks!")


def board_shuttle(game, called_at=SHUTTLE_LOCKOUT_SECONDS):
    """Call the crew shuttle at called_at, let it dock, and board it from Departures. The shuttle leaves at
    game.player_data["round"]["shuttle"]["until"]."""
    game.player_data["game_clock"]["elapsed_seconds"] = called_at
    call_shuttle(game, "the shift is over")
    game.player_data["game_clock"]["elapsed_seconds"] += SHUTTLE_ARRIVAL_SECONDS
    tick_round(game)
    game.player_data["location"] = location_from_key(DEPARTURES_KEY)
    game.perform("room.board", {})
    return game


def give_duty(game, **fields):
    """Put a duty on the board as the game would. Returns its id."""
    return add_duty(game.player_data, **fields)["id"]


def duty(game):
    """The one duty on the board, without the id and deadline the board gave it."""
    (only,) = game.player_data["duties"]
    return {key: value for key, value in only.items() if key not in ("id", "expires_at")}


def duty_id(game):
    return game.player_data["duties"][0]["id"]


def reports(game):
    return [title for title, *_ in game._messages]


def drain(game):
    """The log lines written so far, as dicts, starting the list over."""
    lines = [{"title": title, "message": message, "kind": kind} for title, message, kind in game._messages]
    game._messages = []
    return lines


def last_message(game):
    """The newest log line as (title, message)."""
    return game._messages[-1][:2]


def messages(game):
    """Every log line so far as (title, message)."""
    return [(title, message) for title, message, _ in game._messages]


def pda_messages(game):
    """The PDA inbox as (subject, text)."""
    return [(message["subject"], message["text"]) for message in game.player_data["pda"]["messages"]]


def notes(game):
    return [note["text"] for note in game.player_data["notes"]]


def carried(game):
    """The inventory as {item id: quantity}."""
    return {item["id"]: item["quantity"] for item in game.player_data["inventory"]}


def menu_widgets(game):
    """The room menu's buttons and lines."""
    return game.view()["screen"]["buttons"]


def buttons(game):
    """The room menu as (label, action), with None as the action of a line of text."""
    return [(w.get("label") or w.get("text"), w.get("action")) for w in menu_widgets(game)]


def labels(game):
    return [label for label, _ in buttons(game)]


def panel(game):
    """The top panel, or None."""
    return game.view()["panel"]


def ctx(game):
    return panel(game)["ctx"]


def feedback(game):
    return ctx(game)["feedback"]["text"]


def html(app, game):
    """The game screen as the page renders it."""
    with app.test_request_context():
        return render_template("game/screen.html", view=game.view())


def give(game, *item_ids):
    """Add these items to the inventory."""
    for item_id in item_ids:
        add_to_inventory(game.player_data, get_item_definition(item_id))
    return game


def hold(game, left=None, right=None):
    """Put these items in the hands, leaving a hand given no item empty."""
    game.player_data["hands"] = {"left": left and get_item_definition(left),
                                 "right": right and get_item_definition(right)}
    return game


def index_of(game, item_id):
    return next(i for i, item in enumerate(game.player_data["inventory"]) if item.get("id") == item_id)


def select_item(game, index):
    """Close every panel, open the inventory and select the item at index."""
    game.ui["panels"] = []
    game.open_panel("inventory")
    game.perform("panel.select", {"index": index})


def item_action(game, index, action):
    """Pick action from the actions menu of the inventory item at index."""
    select_item(game, index)
    game.perform("panel.actions", {})
    game.perform("panel.item_action", {"name": action})


def go(game, section):
    game.perform("room.go_to", {"section": section})
    return game


def serve(game):
    """Serve the order on the duty board."""
    game.perform("room.serve_order", {"duty_id": duty_id(game)})


def open_station(game, room_mode, action):
    """Close every panel, switch the room's menu to room_mode and press its room.<action> button."""
    game.ui["panels"] = []
    game.ui["room_mode"] = room_mode
    game.perform(f"room.{action}", {})
    return game


def reopen(game, panel_type, **state):
    """Close every panel and open panel_type on its own."""
    game.ui["panels"] = []
    game.open_panel(panel_type, **state)
    return game


def choose(game, label):
    """Press the button labelled label on the choice the game is asking."""
    choice = game.view()["choice"]
    game.perform("game.choose", {"id": choice["id"], "index": choice["buttons"].index(label)})


def add_ingredients(game, *names):
    """Select and add each of these on the open mixing panel."""
    for name in names:
        game.perform("panel.select_ingredient", {"name": name})
        game.perform("panel.add_ingredient", {})


def at(game, seconds, tick=None):
    """Set the clock to seconds into the round, then run tick(game) when one is given."""
    game.player_data["game_clock"]["elapsed_seconds"] = seconds
    if tick:
        tick(game)
    return game


def tick_after(game, seconds=60):
    """Run game.tick() as if seconds of real time had passed since the last one."""
    game.player_data["game_clock"]["last_real_time"] = time.time() - seconds
    game.tick()
    return game


def fix_random(monkeypatch, *modules, roll=0.0, pick=lambda options: list(options)[0],
               randint=lambda low, high: high):
    """Fix every random draw in these modules: random() returns roll, choice() and randint() go through pick and
    randint, shuffle() keeps the order and sample() takes the first ones."""
    fake = SimpleNamespace(random=lambda: roll, choice=pick, randint=randint, shuffle=lambda items: None,
                           sample=lambda items, count: list(items)[:count])
    for module in modules:
        monkeypatch.setattr(module, "random", fake)


def job_event(monkeypatch, game, roll=0.0, **fixed):
    """The job event the game would offer now, with random_events fixed as fix_random does."""
    fix_random(monkeypatch, random_events, roll=roll, **fixed)
    return random_events.build_job_event(game)


def fill_air(game, fractions):
    """Replace the station's air with `fractions` ({gas: share}) at standard pressure."""
    game.player_data["atmos"]["air"] = gas_mix.mix_of(fractions, AIR_MOLES, ROOM_TEMP)
    return game


def stale_air(game):
    """Leave the station's air with no Oxygen in it, so everyone breathing it takes oxygen damage at the worst rate."""
    return fill_air(game, {"Nitrogen": 1})


def atmos(game):
    return game.player_data["atmos"]


def canister(game, index):
    return atmos(game)["canisters"][index]


def pure(gas, moles, temp=ROOM_TEMP):
    return gas_mix.mix_of({gas: 1}, moles, temp)


def tank_mix(gas, fill=1.0, temp=ROOM_TEMP):
    """A Gas Tank's worth of one gas at fill times the tank's rating."""
    return pure(gas, gas_mix.moles_at(fill * GAS_TANK["rated"], GAS_TANK["volume"], temp), temp)


def tank_item(mix, valve_open=False):
    """A Gas Tank holding mix."""
    tank = get_item_definition("gas_tank")
    tank["attributes"].update(contents=mix, valve_open=valve_open)
    return tank


def give_tank(game, mix=None):
    """Add a Gas Tank to the inventory, empty unless mix is given. Returns its inventory index."""
    add_to_inventory(game.player_data, get_item_definition("gas_tank") if mix is None else tank_item(mix))
    return len(game.player_data["inventory"]) - 1
