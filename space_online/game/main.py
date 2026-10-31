"""Game session engine for the web client.

A SpaceStationGame wraps one character's saved player_data plus its UI state
for the duration of a single request: advance the master clock, run one
client action, then describe the screen to render.
"""

import logging
import time
import uuid

from space_online.game.maps import donut
from space_online.game.helper_methods.stock_market import StockMarketEngine, round_credits
from space_online.game.helper_methods.npc_movement import (
    roll_departures,
    step_wanderers,
)
from space_online.game.helper_methods.player_movement import PlayerMovementMixin
from space_online.game.helper_methods.jail import (
    arrest_member,
    can_player_arrest,
    fined_in_room,
    has_fine,
    is_jailed,
    offer_player_arrest_choice,
    resolve_fine_with_guard,
    security_hallway_location,
    security_room_location,
    tick_jail_releases,
    wanted_in_room,
    warrant_reason_text,
)
from space_online.game.helper_methods.game_clock import (
    seconds_since_last_tick,
    advance,
    get_elapsed_seconds,
)
from space_online.game.helper_methods.power_constants import (
    BATTERY_CRITICAL,
    LOW_POWER_SYSTEM_LEVELS,
    HIGH_MODE_SOLAR_DRAIN,
    calculate_discharge,
    calculate_solar_charge,
)
from space_online.game.helper_methods.lighting_helper import (
    clamp_lighting_for_battery,
    clamped_station_power,
    lighting_style,
)
from space_online.game.helper_methods.oxygen_helper import (
    OXYGEN_WARNING_MESSAGES,
    OXYGEN_DEATH_TITLE,
    OXYGEN_DEATH_MESSAGE,
    OXYGEN_DEATH_NOTE,
    apply_oxygen_tick,
    apply_oxygen_death_state,
)
from space_online.game.helper_methods.alcohol_helper import apply_alcohol_tick
from space_online.game.helper_methods.ui_panels import (
    CHOICE_HANDLERS,
    PANEL_ACTIONS,
    PANELS,
    coalesce_reports,
    default_ui_state,
)
from space_online.game.character_methods import character_sheet  # noqa: F401  (registers the character sheet panels)
from space_online.game.special_rooms import MedBay, Bridge, Security, Engineering, Bar, Botany, Quarters
from space_online.game.special_rooms.shared import add_note as shared_add_note

SPECIAL_ROOM_CLASSES = {
    "Bridge": Bridge,
    "MedBay": MedBay,
    "Security": Security,
    "Engineering": Engineering,
    "Bar": Bar,
    "Botany": Botany,
    "Quarters": Quarters,
}

SPECIAL_ROOM_TILES = donut.SPECIAL_ROOM_TILES
SPECIAL_ROOM_HALLWAY = donut.SPECIAL_ROOM_HALLWAY

# Real-time NPC wander cadence. NPC steps run at most this often inside tick(),
# not scaled by elapsed time, so NPC pacing doesn't depend on player clicks or
# on how long the player was away.
NPC_MOVE_INTERVAL_SECONDS = 3.0

# Master clock interval (real seconds). The browser polls at this rate;
# requests arriving faster than this skip the tick and catch up on the next
# one, since power/oxygen/alcohol formulas are linear in elapsed time.
MASTER_TICK_INTERVAL_SECONDS = 1.0

GAME_ACTIONS = frozenset({
    "move",
    "enter_room",
    "character_sheet",
    "hands",
    "close_panel",
    "choose",
    "save_and_exit",
})

DEFAULT_TITLE = "Space Station Explorer"

logger = logging.getLogger(__name__)


class SpaceStationGame(PlayerMovementMixin):
    def __init__(self, player_data, ui_state=None):
        self.player_data = player_data
        self.ui = ui_state or default_ui_state()
        self.event_messages = None
        self.redirect = None
        self._messages = []
        self.market_engine = StockMarketEngine.from_player_data(player_data)

    @property
    def station_crew(self):
        return self.player_data["station_crew"]

    @property
    def ship_map(self):
        return self.player_data["ship_map"]

    def to_save_data(self):
        """Market state synced and credits rounded, ready to persist."""
        self.market_engine.sync_to_player_data(self.player_data)
        self.player_data["credits"] = round_credits(self.player_data["credits"])
        return self.player_data

    # --- Messages ----------------------------------------------------------

    def alert(self, title, message, kind="info"):
        """Show a dialog with the next response."""
        self._messages.append(("alert", title, message, kind))

    def report(self, title, message, kind="info"):
        """Like alert, but reports in the same response merge into one dialog."""
        self._messages.append(("report", title, message, kind))

    def ask(self, title, message, buttons):
        """Queue a modal choice. buttons: (label, choice_handler_name or None, args)."""
        self.ui["choices"].append({
            "id": uuid.uuid4().hex[:12],
            "title": title,
            "message": message,
            "buttons": [
                {"label": label, "handler": handler, "args": args or {}}
                for label, handler, args in buttons
            ],
        })

    def add_note(self, text):
        shared_add_note(self.player_data, text)

    def drain_alerts(self):
        alerts = []
        reports = []
        report_slot = None
        for kind_of, title, message, kind in self._messages:
            if kind_of == "report":
                if report_slot is None:
                    report_slot = len(alerts)
                    alerts.append(None)
                reports.append((title, message, kind))
            else:
                alerts.append({"title": title, "message": message, "kind": kind})
        if report_slot is not None:
            alerts[report_slot] = coalesce_reports(reports)
        self._messages = []
        return alerts

    # --- Panel stack and room menu mode -------------------------------------

    def open_panel(self, panel_type, **state):
        self.ui["panels"].append({"type": panel_type, **state})

    def replace_panel(self, panel_type, **state):
        if self.ui["panels"]:
            self.ui["panels"].pop()
        self.open_panel(panel_type, **state)

    def top_panel(self):
        return self.ui["panels"][-1] if self.ui["panels"] else None

    def close_panel(self, expected_type=None):
        """Pop the top panel (only if it is expected_type, when given)."""
        top = self.top_panel()
        if top is not None and (expected_type is None or top["type"] == expected_type):
            self.ui["panels"].pop()

    def reset_view(self):
        """Clear overlays and room menus, e.g. after moving to another screen."""
        self.ui["panels"] = []
        self.ui["room_mode"] = "menu"
        self.ui["announcement_active"] = False

    # --- Master clock --------------------------------------------------------

    def tick(self):
        """Advance the master clock and every system tied to it, at most once per interval."""
        if seconds_since_last_tick(self.player_data) < MASTER_TICK_INTERVAL_SECONDS:
            return

        elapsed_seconds, delta_seconds = advance(self.player_data)

        for step in (
            lambda: self._tick_power(delta_seconds),
            lambda: self.check_life_support_status(delta_seconds, elapsed_seconds),
            lambda: apply_alcohol_tick(self.player_data, delta_seconds),
            lambda: tick_jail_releases(self),
            lambda: self.market_engine.tick_if_due(get_elapsed_seconds(self.player_data)),
            self._tick_npc_move,
        ):
            try:
                step()
            except Exception:
                logger.exception("Master clock subsystem failed")

    def _tick_npc_move(self):
        """Advance NPCs one step at most once every NPC_MOVE_INTERVAL_SECONDS of real time."""
        clock = self.player_data["game_clock"]
        now = time.time()
        if now - clock.get("last_npc_move_real", 0.0) >= NPC_MOVE_INTERVAL_SECONDS - 0.05:
            clock["last_npc_move_real"] = now
            roll_departures(self.station_crew)
            step_wanderers(self)

    def _tick_power(self, delta_seconds):
        """Discharge/charge the battery for the elapsed real-time delta."""
        power = self.player_data["station_power"]
        system_levels = power["system_levels"]
        total_discharge_rate = calculate_discharge(system_levels, delta_seconds)

        solar_charging = power["solar_charging"]
        charge_rate = calculate_solar_charge(delta_seconds, solar_charging)

        # With solar on, the power mode decides the net change; otherwise charge minus draw.
        power_mode = power["power_mode"]
        net_change = charge_rate - total_discharge_rate
        if solar_charging and power_mode == "high":
            net_change = -(delta_seconds / 60) * HIGH_MODE_SOLAR_DRAIN
        elif solar_charging and power_mode == "balanced":
            net_change = 0
        elif solar_charging and power_mode == "emergency":
            net_change = 1.5 * (charge_rate - calculate_discharge(LOW_POWER_SYSTEM_LEVELS, delta_seconds))

        old_level = power["battery_level"]
        new_level = max(0, min(100, old_level + net_change))
        power["battery_level"] = new_level
        clamp_lighting_for_battery(power)

        if 0 < new_level <= BATTERY_CRITICAL < old_level:
            self.report(
                "Low Power Warning",
                "Warning: Station battery power low. Emergency lighting active. Please activate solar panels.",
                kind="warning",
            )
        elif new_level <= 0 < old_level:
            self.trigger_power_outage()

    def check_life_support_status(self, delta_seconds, elapsed_seconds):
        """Apply oxygen damage to player and NPCs if life support is failing."""
        events = apply_oxygen_tick(self.player_data, self.station_crew, delta_seconds, elapsed_seconds)
        for threshold in events["crossed_warnings"]:
            self.report("Oxygen Warning", OXYGEN_WARNING_MESSAGES[threshold], kind="warning")
            self.add_note(f"Suffered {threshold}% oxygen damage due to life support failure.")
        if events["died"]:
            self.report(OXYGEN_DEATH_TITLE, OXYGEN_DEATH_MESSAGE, kind="error")
            apply_oxygen_death_state(self.player_data)
            self.add_note(OXYGEN_DEATH_NOTE)
            self.reset_view()

    def trigger_power_outage(self):
        self.report(
            "Power Outage",
            "CRITICAL: Station power failure! Emergency systems active. Activate solar arrays immediately!",
            kind="error",
        )
        self.add_note("CRITICAL: Station suffered complete power failure. Emergency systems active.")

    # --- Navigation -------------------------------------------------------------

    def location_key(self):
        return donut.location_key(self.player_data["location"])

    def current_room_name(self):
        return SPECIAL_ROOM_TILES.get(self.location_key())

    def current_room(self):
        room_name = self.current_room_name()
        return SPECIAL_ROOM_CLASSES[room_name](self) if room_name else None

    def _normalize_location(self):
        if is_jailed(self.player_data) and self.location_key() != donut.SECURITY_KEY:
            self.player_data["location"] = security_room_location()
            self.reset_view()
        if self.location_key() not in self.ship_map:
            self.alert("Error", "Invalid location!", kind="error")
            self.player_data["location"] = dict(donut.QUARTERS_LOCATION)
            self.reset_view()

    def _hallway_buttons(self, x, y):
        """(row, col, label, action, args) for the hallway nav grid at (x, y)."""
        cells = [(row, col, f"Go {direction.title()}", "game.move", {"direction": direction})
                 for direction, (row, col) in donut.DIRECTION_GRID.items()
                 if direction in donut.hallway_neighbors(x, y)]
        for room_key, (label, (row, col)) in donut.ROOM_DOOR_BUTTONS.items():
            if SPECIAL_ROOM_HALLWAY[room_key] == (x, y):
                cells.append((row, col, label, "game.enter_room", {"room_key": room_key}))
        return cells

    def hallway_view(self):
        location = self.ship_map[self.location_key()]
        station_power = clamped_station_power(self.player_data)
        style = lighting_style(station_power["system_levels"].get("hallway_lighting", 5), place="hallway")
        x = self.player_data["location"]["x"]
        y = self.player_data["location"]["y"]

        cells = self._hallway_buttons(x, y)
        row_count = max(row for row, *_ in cells) + 1 if cells else 0
        grid = [[None] * 3 for _ in range(row_count)]
        for row, col, label, action, args in cells:
            grid[row][col] = {"label": label, "action": action, "args": args}

        return {
            "type": "hallway",
            "title": DEFAULT_TITLE,
            "name": location["name"],
            "description": location["desc"] + style["power_desc"],
            "coords": f"Location: {x} North, {y} East",
            "style": style,
            "grid": grid,
        }

    def enter_room(self, room_key):
        """Enter the special room whose door is next to the current hallway tile."""
        if self.current_room_name() is not None:
            return
        x = self.player_data["location"]["x"]
        y = self.player_data["location"]["y"]
        allowed = {args.get("room_key") for *_, action, args in self._hallway_buttons(x, y) if action == "game.enter_room"}
        if room_key not in allowed:
            return

        room_details = self.ship_map.get(room_key)
        if room_details.get("locked", False):
            self.alert("Locked", f"The {SPECIAL_ROOM_TILES[room_key]} door is locked.")
            return

        self.player_data["location"] = donut.location_from_key(room_key)
        self.reset_view()

        # Security Guard / Captain players scan the room for warrants on entry.
        if can_player_arrest(self.player_data) and not is_jailed(self.player_data):
            self._scan_room_for_warrants(room_key)

    def leave_room(self):
        """Step out of the current room onto the hallway tile in front of its door."""
        hallway_x, hallway_y = SPECIAL_ROOM_HALLWAY[self.location_key()]
        self.player_data["location"] = {"x": hallway_x, "y": hallway_y}
        self.reset_view()

    def move(self, direction):
        if self.current_room_name() is None and not self.ui["panels"]:
            self.move_direction(direction)

    def save_and_exit(self):
        self.redirect = "home"

    def handle_player_arrest(self, message, show_message=True):
        """Teleport the jailed player into the Security room."""
        if show_message:
            self.alert("Arrested", message)
        self.player_data["location"] = security_room_location()
        self.reset_view()

    def handle_player_release(self):
        """Return the player to the Security hallway after their sentence ends."""
        self.player_data["location"] = security_hallway_location()
        self.alert("Released", "Your sentence is over. You are free to go.")
        self.reset_view()

    # --- Security encounters ---------------------------------------------------

    def _handle_hallway_security_encounter(self, npc):
        """Arrest on hallway pass-by if one party is Security and the other is wanted.

        Also collects unpaid fines when a fined person meets a security guard.
        Returns True if an arrest (or security-specific handling) occurred.
        """
        npc_is_guard = npc.get("job") == "Security Guard"
        player_can_enforce = can_player_arrest(self.player_data)
        elapsed_seconds = get_elapsed_seconds(self.player_data)

        # Unpaid fines: pay or go to jail when meeting security.
        if npc_is_guard and has_fine(self.player_data) and not is_jailed(self.player_data):
            result = resolve_fine_with_guard(
                self.player_data,
                game=self,
                is_player=True,
                guard_name=npc.get("name", "A security guard"),
                elapsed_seconds=elapsed_seconds,
            )
            if result == "jailed":
                return True
            # Paid: still allow warrant handling below if wanted.

        if player_can_enforce and has_fine(npc) and not is_jailed(npc):
            result = resolve_fine_with_guard(
                npc,
                game=self,
                is_player=False,
                guard_name=self.player_data.get("name", "Security"),
                elapsed_seconds=elapsed_seconds,
            )
            if result is not None:  # pragma: no branch - the fine was checked above, so the guard always collects it or jails
                return True

        if npc_is_guard and self.player_data.get("warrant", False) and not is_jailed(self.player_data):
            charge = warrant_reason_text(self.player_data)
            arrest_member(
                self.player_data,
                reason=(
                    f"{npc.get('name', 'A security guard')} stops you in the hall. "
                    f"You are under arrest!\nCharge: {charge}"
                ),
                game=self,
                is_player=True,
                show_message=True,
                elapsed_seconds=elapsed_seconds,
            )
            return True

        if player_can_enforce and npc.get("warrant", False) and not is_jailed(npc):
            offer_player_arrest_choice(self, npc, place="hall")
            return True

        return False

    def _scan_room_for_warrants(self, room_key):
        """As Security Guard or Captain, collect fines and offer Arrest/Let Go for wanted people."""
        elapsed_seconds = get_elapsed_seconds(self.player_data)

        for npc in fined_in_room(room_key, self.station_crew):
            resolve_fine_with_guard(
                npc,
                game=self,
                is_player=False,
                guard_name=self.player_data.get("name", "Security"),
                elapsed_seconds=elapsed_seconds,
            )

        for npc in list(wanted_in_room(room_key, self.station_crew)):
            offer_player_arrest_choice(self, npc, place="room")

    # --- Actions -------------------------------------------------------------------

    def perform(self, action, args):
        """Run one client action such as 'game.move', 'room.socialize', or 'panel.buy'."""
        scope, _, name = str(action).partition(".")
        args = args if isinstance(args, dict) else {}

        if self.ui["choices"] and action != "game.choose":
            return

        try:
            if scope == "game" and name in GAME_ACTIONS:
                getattr(self, f"_action_{name}")(args)
            elif scope == "room":
                room = self.current_room()
                if room is not None and not self.ui["panels"]:
                    room.perform(name, args)
            elif scope == "panel":
                top = self.top_panel()
                handler = PANEL_ACTIONS.get((top["type"], name)) if top else None
                if handler is not None:
                    handler(self, top, args)
        except (KeyError, TypeError, ValueError, IndexError):
            self.alert("Error", "That action could not be completed.", kind="error")

    def _action_move(self, args):
        self.move(args["direction"])

    def _action_enter_room(self, args):
        if not self.ui["panels"]:
            self.enter_room(args["room_key"])

    def _action_character_sheet(self, args):
        self.open_panel("character_sheet")

    def _action_hands(self, args):
        self.open_panel("hands")

    def _action_close_panel(self, args):
        self.close_panel()

    def _action_choose(self, args):
        # The id guards against a stale click answering the next queued choice.
        if not self.ui["choices"] or self.ui["choices"][0]["id"] != args.get("id"):
            return
        picked = self.ui["choices"][0]["buttons"][int(args["index"])]
        self.ui["choices"].pop(0)
        handler = CHOICE_HANDLERS.get(picked["handler"])
        if handler is not None:
            handler(self, **picked["args"])

    def _action_save_and_exit(self, args):
        if not self.ui["panels"]:
            self.save_and_exit()

    # --- View ------------------------------------------------------------------------

    def _panel_view(self):
        """Context for the visible (top) panel; panels whose subject vanished auto-close."""
        while self.ui["panels"]:
            state = self.ui["panels"][-1]
            definition = PANELS.get(state["type"])
            context = definition["context"](self, state) if definition else None
            if context is None:
                self.ui["panels"].pop()
                continue
            return {
                "type": state["type"],
                "title": context.get("title", definition["title"]),
                "ctx": context,
            }
        return None

    def view(self):
        """Everything the client needs to draw the current screen."""
        self._normalize_location()
        room = self.current_room()
        screen = room.view() if room is not None else self.hallway_view()
        panel = self._panel_view()
        choice = self.ui["choices"][0] if self.ui["choices"] else None
        return {
            "title": panel["title"] if panel else screen["title"],
            "screen": screen,
            "panel": panel,
            "choice": {
                "id": choice["id"],
                "title": choice["title"],
                "message": choice["message"],
                "buttons": [button["label"] for button in choice["buttons"]],
            } if choice else None,
            "alerts": self.drain_alerts(),
            "redirect": self.redirect,
        }
