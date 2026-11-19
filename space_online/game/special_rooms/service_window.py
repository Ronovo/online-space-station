"""The service window panel: each side passes its own ingredients through for the other side's station to use."""

from typing import NamedTuple

from space_online.game.helper_methods.npc_movement import can_work, post_holder
from space_online.game.helper_methods.ui_panels import current_feedback, panel_action, register_panel, set_feedback
from space_online.game.helper_methods.window_stock import other_side

MAX_WINDOW_PASS = 10
WINDOW_MODES = (("pass", "Pass Through"), ("ask", "Ask For"))

SIDES = {}


class Side(NamedTuple):
    job: str
    place: str
    gives: list  # the ingredients this side can pass through
    wants: tuple  # what this side's crew member asks the other side for


def register_window_side(side, **details):
    SIDES[side] = Side(**details)


def window_partner(game, side):
    """The crew member who works the other side of the window from side, wherever they are, or None when nobody
    holds that post or they can't work."""
    npc = post_holder(game.station_crew, SIDES[other_side(side)].job)
    return npc if npc is not None and can_work(npc) else None


def _giving_side(state):
    """The side whose ingredients the panel lists: the player's to pass, the other one's to ask for."""
    side = state["side"]
    return SIDES[side if state.get("mode", "pass") == "pass" else other_side(side)]


@register_panel("service_window", "Service Window")
def service_window_panel(game, state):
    side = state["side"]
    there = other_side(side)
    window = game.player_data["service_window"]
    giving = _giving_side(state)
    selected = state.get("selected")
    return {
        "here": SIDES[side],
        "there": SIDES[there],
        "modes": WINDOW_MODES,
        "mode": state.get("mode", "pass"),
        "ingredients": giving.gives,
        "selected": selected if selected in giving.gives else None,
        "waiting": sorted(window["stock"][side].items()),
        "sent": sorted(window["stock"][there].items()),
        "requests": sorted(window["requests"][there].items()),
        "max": MAX_WINDOW_PASS,
        "feedback": current_feedback(state),
    }


@panel_action("service_window", "mode")
def window_mode(game, state, args):
    if args["name"] in dict(WINDOW_MODES):
        state["mode"] = args["name"]
        state.pop("selected", None)


@panel_action("service_window", "select")
def window_select(game, state, args):
    if args["name"] in _giving_side(state).gives:
        state["selected"] = args["name"]


def _pass_through(game, side, name, amount):
    """Put amount of name on the window. The other side's crew member takes what they asked for first."""
    there = other_side(side)
    window = game.player_data["service_window"]
    requests = window["requests"][there]
    taken = min(amount, requests.get(name, 0))
    if taken:
        requests[name] -= taken
        if requests[name] <= 0:
            del requests[name]
    left = amount - taken
    if left:
        stock = window["stock"][there]
        stock[name] = stock.get(name, 0) + left

    job = SIDES[there].job
    game.add_note(f"Passed {amount} {name} through the service window to the {SIDES[there].place}.")
    if taken:
        return f"You pass {amount} {name} through the window. The {job} takes {taken}."
    return f"You put {amount} {name} on the window for the {SIDES[there].place}."


def _hand_over(game, side, name, amount):
    """The other side's crew member puts amount of name on the window for side. Returns the line saying so."""
    job = SIDES[other_side(side)].job
    stock = game.player_data["service_window"]["stock"][side]
    stock[name] = stock.get(name, 0) + amount
    game.add_note(f"The {job} passed {amount} {name} through the service window.")
    return f"The {job} passes {amount} {name} through the window."


def _ask_for(game, side, name, amount):
    """Have the other side's crew member pass amount of name through. While they can't work, the request waits for
    them."""
    if window_partner(game, side) is not None:
        return _hand_over(game, side, name, amount)
    job = SIDES[other_side(side)].job
    asked = game.player_data["service_window"]["requests"][side]
    asked[name] = asked.get(name, 0) + amount
    game.add_note(f"Asked the {job} for {amount} {name} at the service window.")
    return f"The {job} can't pass you {name} right now. It will come through the window when they can."


def tick_service_window(game):
    """Each side's crew member passes through what the other side asked for once they can work. What is asked of
    the player's own job waits for the player."""
    for side, asked in game.player_data["service_window"]["requests"].items():
        if asked and SIDES[other_side(side)].job != game.player_data["job"] and window_partner(game, side):
            for name, amount in asked.items():
                game.alert("Service Window", _hand_over(game, side, name, amount))
            asked.clear()


@panel_action("service_window")
def confirm(game, state, args):
    name = state.get("selected")
    if name not in _giving_side(state).gives:
        game.alert("Service Window", "Select an ingredient first.")
        return
    try:
        amount = int(str(args.get("amount", "")).strip())
    except ValueError:
        amount = 0
    if not 1 <= amount <= MAX_WINDOW_PASS:
        game.alert("Service Window", f"Enter an amount from 1 to {MAX_WINDOW_PASS}.")
        return

    act = _pass_through if state.get("mode", "pass") == "pass" else _ask_for
    set_feedback(state, act(game, state["side"], name, amount))
