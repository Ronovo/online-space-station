"""Server-side UI state for the web client: the panel stack and choices.

The browser only renders what these structures describe. Panels are
overlays on the screen (only the top of the stack is visible) and choices are
modal button prompts the player must answer.
"""

import time

PANELS = {}
PANEL_ACTIONS = {}
CHOICE_HANDLERS = {}

def default_ui_state():
    return {"room_mode": "menu", "panels": [], "choices": []}


def register_panel(panel_type, title, template=None):
    """Register context_fn(game, state) -> dict, or None to auto-close the panel.

    template names the panel's template when several panel types share one.
    """
    def decorator(context_fn):
        PANELS[panel_type] = {"title": title, "context": context_fn, "template": template or panel_type}
        return context_fn
    return decorator


def panel_action(panel_type, name=None):
    """Register fn(game, state, args) as an action of the top panel."""
    def decorator(fn):
        PANEL_ACTIONS[(panel_type, name or fn.__name__)] = fn
        return fn
    return decorator


def choice_handler(name):
    """Register fn(game, **args) run when the matching choice button is picked."""
    def decorator(fn):
        CHOICE_HANDLERS[name] = fn
        return fn
    return decorator


def set_feedback(state, text, color="cyan", seconds=3):
    """Show a panel feedback line; seconds=None keeps it until replaced."""
    state["feedback"] = {
        "text": text,
        "color": color,
        "until": time.time() + seconds if seconds else None,
    }


def current_feedback(state):
    feedback = state.get("feedback")
    if not feedback:
        return None
    until = feedback.get("until")
    if until is not None and time.time() >= until:
        state.pop("feedback", None)
        return None
    return feedback

