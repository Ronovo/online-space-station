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
from space_online.game.helper_methods.npc_movement import step_crew
from space_online.game.helper_methods.player_movement import PlayerMovementMixin
from space_online.game.helper_methods.jail import (
    arrest_member,
    can_hack_doors,
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
    warrants_enforced,
)
from space_online.game.helper_methods.game_clock import (
    seconds_since_last_tick,
    advance,
    get_elapsed_seconds,
    pass_time,
)
from space_online.game.helper_methods.antagonists import alert_level, sightings, step_threats, tick_threats
from space_online.game.helper_methods.career import pay_salary
from space_online.game.helper_methods.door_control import can_control_door
from space_online.game.helper_methods.needs import tick_needs
from space_online.game.helper_methods.pda import pda_button, send, tick_pda_needs
from space_online.game.objects.items import add_to_inventory, format_inventory_label
from space_online.game.helper_methods.crew_work import tick_crew_work
from space_online.game.helper_methods.errands import duties_button, tick_duty_expiry
from space_online.game.helper_methods.random_events import tick_flight_event, tick_job_events
from space_online.game.helper_methods.hazards import HAZARD_ROOM_KEYS, HAZARDS, room_hazard, tick_hazards
from space_online.game.helper_methods.health_bands import health_band, overall_health
from space_online.game.helper_methods.combat import FIGHT_ACTIONS, fight_view, tick_fight
from space_online.game.helper_methods.rounds import kill_player, round_over, shuttle_status, tick_round
from space_online.game.helper_methods.power_constants import (
    BATTERY_CRITICAL,
    LOW_POWER_ALERT,
    POWER_OUTAGE_ALERT,
    calculate_discharge,
    calculate_solar_charge,
    system_online,
)
from space_online.game.helper_methods.lighting_helper import clamp_lighting_for_battery
from space_online.game.helper_methods.oxygen_helper import (
    OXYGEN_WARNING_MESSAGES,
    OXYGEN_DEATH_TITLE,
    OXYGEN_DEATH_MESSAGE,
    OXYGEN_DEATH_NOTE,
    apply_oxygen_tick,
    apply_oxygen_death_state,
)
from space_online.game.helper_methods.alcohol_helper import apply_alcohol_tick
from space_online.game.helper_methods.atmos import tick_atmos
from space_online.game.helper_methods.engine import engine_output, tick_engine
from space_online.game.helper_methods.bombs import floor_label, tick_bombs
from space_online.game.helper_methods.station_air import time_factor
from space_online.game.helper_methods.ui_panels import (
    CHOICE_HANDLERS,
    PANEL_ACTIONS,
    PANELS,
    default_ui_state,
)
from space_online.game.character_methods import character_sheet  # noqa: F401  (registers the character sheet panels)
from space_online.game.special_rooms.atmospherics import Atmospherics
from space_online.game.special_rooms.bar import Bar
from space_online.game.special_rooms.botany import Botany
from space_online.game.special_rooms.bridge import Bridge
from space_online.game.special_rooms.cargo import Cargo
from space_online.game.special_rooms.chemistry import Chemistry
from space_online.game.special_rooms.departures import Departures
from space_online.game.special_rooms.engineering import Engineering
from space_online.game.special_rooms.kitchen import Kitchen
from space_online.game.special_rooms.med_bay import MedBay
from space_online.game.special_rooms.mining import Mining
from space_online.game.special_rooms.quarters import Quarters
from space_online.game.special_rooms.research import Research
from space_online.game.special_rooms.security import Security
from space_online.game.special_rooms.botany import announce_planter_changes
from space_online.game.special_rooms.bridge import tick_access_request
from space_online.game.special_rooms.cargo import tick_cargo
from space_online.game.special_rooms.engineering import set_system_level
from space_online.game.special_rooms.quarters import tick_rest
from space_online.game.special_rooms.service_window import tick_service_window
from space_online.game.special_rooms.shared import add_note as shared_add_note, lighting_chrome

SPECIAL_ROOM_CLASSES = {
    "Bridge": Bridge,
    "MedBay": MedBay,
    "Security": Security,
    "Engineering": Engineering,
    "Bar": Bar,
    "Kitchen": Kitchen,
    "Botany": Botany,
    "Chemistry": Chemistry,
    "Mining": Mining,
    "Cargo": Cargo,
    "Research": Research,
    "Atmospherics": Atmospherics,
    "Departures": Departures,
    "Quarters": Quarters,
}

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
    "duties",
    "pda",
    "hands",
    "close_panel",
    "choose",
    "pick_up",
    "save_and_exit",
})
# The only game actions open during a fight: changing what is in your hands.
FIGHT_GAME_ACTIONS = frozenset({"hands", "close_panel"})

DEFAULT_TITLE = "Space Station Explorer"
MAX_LOG_LINES = 200
LOG_NEW_SECONDS = 8

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
        """Add a line to the station log, which the screen shows beside the game."""
        self._messages.append((title, message, kind))
        log = self.player_data["log"]
        log.append({"at": get_elapsed_seconds(self.player_data), "title": title, "text": message, "kind": kind})
        del log[:-MAX_LOG_LINES]

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

    def announce(self, title, message, kind="info"):
        """Log a station-wide announcement, which only gets through while the Communication Array is up."""
        if system_online(self.player_data, "communication_array"):
            self.alert(title, message, kind)

    def page(self, subject, text):
        """Send a message to the player's PDA."""
        send(self.player_data, subject, text)

    def add_note(self, text):
        shared_add_note(self.player_data, text)

    def floor_here(self):
        """The items lying where the player is standing, as a list to add to or take from."""
        return self.player_data["floor"].setdefault(self.location_key(), [])

    def log_view(self):
        """The station log, newest first. A line reads as new for LOG_NEW_SECONDS after it is written."""
        elapsed = get_elapsed_seconds(self.player_data)
        return [{"time": f"{int(entry['at'] // 60)}m", "title": entry["title"], "text": entry["text"],
                 "kind": entry["kind"], "new": elapsed - entry["at"] < LOG_NEW_SECONDS}
                for entry in reversed(self.player_data["log"])]

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
        if round_over(self.player_data) or seconds_since_last_tick(self.player_data) < MASTER_TICK_INTERVAL_SECONDS:
            return

        _, real_seconds = advance(self.player_data)
        # While the player breathes Nitrous Oxide they lose time: the whole station runs on ahead of them.
        factor = time_factor(self)
        pass_time(self.player_data, real_seconds * (factor - 1))
        delta_seconds = real_seconds * factor

        for step in (
            lambda: tick_engine(self, delta_seconds),
            lambda: self._tick_power(delta_seconds),
            lambda: self.check_life_support_status(delta_seconds),
            lambda: apply_alcohol_tick(self.player_data, delta_seconds),
            lambda: tick_rest(self, delta_seconds),
            lambda: tick_hazards(self, delta_seconds),
            lambda: tick_atmos(self, delta_seconds),
            lambda: tick_bombs(self),
            lambda: tick_needs(self, delta_seconds),
            lambda: tick_jail_releases(self),
            lambda: tick_access_request(self),
            lambda: self.market_engine.tick_if_due(get_elapsed_seconds(self.player_data)),
            lambda: announce_planter_changes(self),
            lambda: pay_salary(self),
            lambda: tick_cargo(self),
            lambda: tick_crew_work(self),
            lambda: tick_service_window(self),
            lambda: tick_job_events(self),
            lambda: tick_flight_event(self),
            lambda: tick_duty_expiry(self),
            lambda: tick_pda_needs(self),
            lambda: tick_threats(self),
            lambda: tick_fight(self),
            lambda: tick_round(self),
            lambda: self._tick_npc_move(factor),
        ):
            try:
                step()
            except Exception:
                logger.exception("Master clock subsystem failed")

    def _tick_npc_move(self, steps):
        """Advance NPCs `steps` steps at most once every NPC_MOVE_INTERVAL_SECONDS of real time."""
        clock = self.player_data["game_clock"]
        now = time.time()
        if now - clock.get("last_npc_move_real", 0.0) >= NPC_MOVE_INTERVAL_SECONDS - 0.05:
            clock["last_npc_move_real"] = now
            for _ in range(steps):
                step_crew(self)
                step_threats(self)

    def _tick_power(self, delta_seconds):
        """Charge the battery from the solar array and the Combustion Engine and drain it by what the systems draw,
        for the elapsed delta."""
        power = self.player_data["station_power"]
        net_change = (calculate_solar_charge(delta_seconds, power["solar_charging"])
                      + engine_output(self.player_data["engine"]) * delta_seconds / 60
                      - calculate_discharge(power["system_levels"], delta_seconds))

        old_level = power["battery_level"]
        new_level = max(0, min(100, old_level + net_change))
        power["battery_level"] = new_level
        clamp_lighting_for_battery(power)

        if 0 < new_level <= BATTERY_CRITICAL < old_level:
            self.alert("Low Power Warning", LOW_POWER_ALERT, kind="warning")
        elif new_level <= 0 < old_level:
            self.trigger_power_outage()

    def check_life_support_status(self, delta_seconds):
        """Apply what the air they breathe does to the player and the NPCs."""
        events = apply_oxygen_tick(self.player_data, self.station_crew, delta_seconds)
        for threshold in events["crossed_warnings"]:
            self.alert("Oxygen Warning", OXYGEN_WARNING_MESSAGES[threshold], kind="warning")
            self.add_note(f"Suffered {threshold}% oxygen damage due to life support failure.")
        if events["died"] and not kill_player(self, "died when the oxygen ran out"):
            self.alert(OXYGEN_DEATH_TITLE, OXYGEN_DEATH_MESSAGE, kind="error")
            apply_oxygen_death_state(self.player_data)
            self.add_note(OXYGEN_DEATH_NOTE)
            self.reset_view()

    def trigger_power_outage(self):
        """The battery is flat, and life support goes down with it."""
        self.alert("Power Outage", POWER_OUTAGE_ALERT, kind="error")
        self.add_note("CRITICAL: Station suffered complete power failure. Life support shut down.")
        set_system_level(self, "life_support", 0)

    # --- Navigation -------------------------------------------------------------

    def location_key(self):
        return donut.location_key(self.player_data["location"])

    def current_room_name(self):
        return donut.SPECIAL_ROOM_TILES.get(self.location_key())

    def current_room(self):
        room_name = self.current_room_name()
        return SPECIAL_ROOM_CLASSES[room_name](self) if room_name else None

    def _normalize_location(self):
        """Keep the player somewhere they can be: a prisoner in the jail, unless they ride in the shuttle's cell."""
        if (is_jailed(self.player_data) and not self.player_data["round"]["aboard"]
                and self.location_key() != donut.SECURITY_KEY):
            self.player_data["location"] = security_room_location()
            self.reset_view()
        if self.location_key() not in self.ship_map:
            self.alert("Error", "Invalid location!", kind="error")
            self.player_data["location"] = dict(donut.QUARTERS_LOCATION)
            self.reset_view()
        # Being arrested or revived moves the player off the planet, which ends the shuttle trip.
        if self.location_key() != donut.MINING_KEY:
            self.player_data["mining"]["expedition"] = None

    def _hallway_buttons(self, x, y):
        """(row, col, label, action, args) for the hallway nav grid at (x, y)."""
        cells = [(row, col, f"Go {direction.title()}", "game.move", {"direction": direction})
                 for direction, (row, col) in donut.DIRECTION_GRID.items()
                 if direction in donut.hallway_neighbors(x, y)]
        for room_key, room in donut.ROOMS.items():
            if room.hallway == (x, y):
                cells.append((*room.button, room.name, "game.enter_room", {"room_key": room_key}))
        return cells

    def hallway_view(self):
        location = self.ship_map[self.location_key()]
        style = lighting_chrome(self.player_data, place="hallway")
        x =self.player_data["location"]["x"]
        y = self.player_data["location"]["y"]

        grid = [[None] * 3 for _ in range(3)]
        for row, col, label, action, args in self._hallway_buttons(x, y):
            grid[row][col] = {"label": label, "action": action, "args": args}

        return {
            "type": "hallway",
            "title": DEFAULT_TITLE,
            "name": location["name"],
            "description": location["desc"],
            "light": style["light"],
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

        name = donut.ROOMS[room_key].name
        if (self.ship_map[room_key].get("locked") and system_online(self.player_data, "security_systems")
                and not can_control_door(self.player_data, room_key)):
            if can_hack_doors(self.player_data):
                self.ask("Locked", f"The {name} door is locked. Force it with your screwdriver and wirecutters?",
                         [("Force the Lock", "hack_door", {"room_key": room_key}), ("Leave It", None, None)])
            else:
                self.alert("Locked", f"The {name} door is locked.")
            return

        self.player_data["location"] = donut.location_from_key(room_key)
        self.reset_view()
        hazard = room_hazard(self.player_data, room_key) if room_key in HAZARD_ROOM_KEYS else None
        if hazard:
            self.alert("Hazard", HAZARDS[hazard]["here"] + " Staying here will hurt you.", kind="warning")

        if can_player_arrest(self.player_data) and not is_jailed(self.player_data):
            self.scan_room_for_warrants(room_key)

    def leave_room(self):
        """Step out of the current room onto the hallway tile in front of its door."""
        hallway_x, hallway_y = donut.SPECIAL_ROOM_HALLWAY[self.location_key()]
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
            resolve_fine_with_guard(
                npc,
                game=self,
                is_player=False,
                guard_name=self.player_data.get("name", "Security"),
                elapsed_seconds=elapsed_seconds,
            )
            return True

        if (npc_is_guard and self.player_data["warrant"] and not is_jailed(self.player_data)
                and warrants_enforced(self.player_data)):
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

    def scan_room_for_warrants(self, room_key, place="room", cell=None):
        """As Security Guard or Captain, collect fines and offer Arrest/Let Go for wanted people. Whoever is jailed
        goes to cell (see arrest_member). Returns whether anyone was fined or offered for arrest."""
        elapsed_seconds = get_elapsed_seconds(self.player_data)

        fined = fined_in_room(room_key, self.station_crew)
        for npc in fined:
            resolve_fine_with_guard(
                npc,
                game=self,
                is_player=False,
                guard_name=self.player_data.get("name", "Security"),
                elapsed_seconds=elapsed_seconds,
                cell=cell,
            )

        offered = [offer_player_arrest_choice(self, npc, place=place)
                   for npc in list(wanted_in_room(room_key, self.station_crew))]
        return bool(fined) or any(offered)

    # --- Actions -------------------------------------------------------------------

    def perform(self, action, args):
        """Run one client action such as 'game.move', 'room.socialize', or 'panel.buy'."""
        scope, _, name = str(action).partition(".")
        args = args if isinstance(args, dict) else {}

        if round_over(self.player_data) or (self.ui["choices"] and action != "game.choose"):
            return

        # A fight leaves only its own actions and changing what is held.
        fighting = bool(self.player_data["fight"])
        try:
            if scope == "fight":
                if fighting and name in FIGHT_ACTIONS and not self.ui["panels"]:
                    FIGHT_ACTIONS[name](self)
            elif scope == "game" and name in GAME_ACTIONS:
                if not fighting or name in FIGHT_GAME_ACTIONS:
                    getattr(self, f"_action_{name}")(args)
            elif scope == "room":
                room = self.current_room()
                if room is not None and not self.ui["panels"] and not fighting:
                    room.perform(name, args)
            elif scope == "panel":
                top = self.top_panel()
                handler = PANEL_ACTIONS.get((top["type"], name)) if top else None
                if handler is not None:
                    handler(self, top, args)
        except (KeyError, TypeError, ValueError, IndexError):
            logger.exception("Action %r failed", action)
            self.alert("Error", "That action could not be completed.", kind="error")

    def _action_move(self, args):
        self.move(args["direction"])

    def _action_enter_room(self, args):
        if not self.ui["panels"]:
            self.enter_room(args["room_key"])

    def _action_character_sheet(self, args):
        self.open_panel("character_sheet")

    def _action_duties(self, args):
        self.open_panel("duties")

    def _action_pda(self, args):
        if pda_button(self.player_data):
            self.open_panel("pda")

    def _action_hands(self, args):
        self.open_panel("hands")

    def _action_pick_up(self, args):
        """Pick up one of the stacks lying where the player is standing."""
        items = self.floor_here()
        index = int(args["index"])
        if self.ui["panels"] or not 0 <= index < len(items):
            return
        item = items.pop(index)
        add_to_inventory(self.player_data, item)
        self.add_note(f"Picked up the {item['name']}.")
        self.alert("Pick Up", f"You pick up the {format_inventory_label(item)}.")

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
                "template": definition["template"],
                "title": context.get("title", definition["title"]),
                "ctx": context,
            }
        return None

    def _status(self):
        """The bar above every screen: the alert level, the shift clock, the player's health, the shuttle, and any
        threat sightings.

        The clock is in whole minutes so the screen isn't redrawn every second for it.
        """
        level, color = alert_level(self.player_data)
        health = overall_health(self.player_data)
        return {
            "alert": level,
            "alert_color": color,
            "health": int(health),
            "health_color": health_band(health)[1],
            "clock": f"{int(get_elapsed_seconds(self.player_data) // 60)}m",
            "shuttle": shuttle_status(self.player_data),
            "sightings": sightings(self.player_data),
        }

    def view(self):
        """Everything the client needs to draw the current screen."""
        self._normalize_location()
        room = self.current_room()
        if self.player_data["fight"]:
            screen = fight_view(self)
        else:
            screen = room.view() if room is not None else self.hallway_view()
        panel = self._panel_view()
        choice = self.ui["choices"][0] if self.ui["choices"] else None
        return {
            "title": panel["title"] if panel else screen["title"],
            "status": self._status(),
            "screen": screen,
            "panel": panel,
            "choice": {
                "id": choice["id"],
                "title": choice["title"],
                "message": choice["message"],
                "buttons": [button["label"] for button in choice["buttons"]],
            } if choice else None,
            "floor": [{"index": index, "label": floor_label(self.player_data, item)}
                      for index, item in enumerate(self.player_data["floor"].get(self.location_key(), []))],
            "log": self.log_view(),
            "pda": pda_button(self.player_data),
            "duties": duties_button(self.player_data),
            "redirect": self.redirect,
        }
