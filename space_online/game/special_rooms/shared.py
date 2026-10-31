import datetime

from space_online.game.helper_methods.door_control import (
    can_control_door,
    toggle_door_lock,
)
from space_online.game.helper_methods.lighting_helper import (
    clamped_station_power,
    lighting_style,
)
from space_online.game.helper_methods.npc_movement import any_npc_for_job, call_npc, on_duty_npc_for_job
from space_online.game.helper_methods.jail import (
    is_jailed,
    jailed_away_text,
    offer_player_arrest_choice,
    player_jail_text,
)
from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.ui_panels import register_panel
from space_online.game.maps.donut import SECURITY_KEY

PLAYER_CREW_INDEX = -1


def room_lighting_chrome(player_data):
    """Clamp lighting for battery and return style dict for a special room shell."""
    station_power = clamped_station_power(player_data)
    level = station_power["system_levels"].get("hallway_lighting", 5)
    return lighting_style(level, place="room")


MAX_NOTES = 200


def add_note(player_data, text):
    """Append a timestamped note, dropping the oldest once there are MAX_NOTES."""
    notes = player_data["notes"]
    notes.append({"timestamp": datetime.datetime.now().isoformat(), "text": text})
    del notes[:-MAX_NOTES]


def button(label, action, **args):
    """Room menu widget: a button that posts action with args."""
    return {"kind": "button", "label": label, "action": action, "args": args}


def text_line(text, *, color=None, style=None):
    """Room menu widget: a line of text. style is None, 'title', or 'italic'."""
    return {"kind": "text", "text": text, "color": color, "style": style}


def room_action(fn=None, *, station=None):
    """Allow a room method to be called from the client.

    station: a station-menu mode the player must be authorized for.
    """
    def wrap(method):
        method.room_action = True
        method.station_mode = station
        return method
    return wrap(fn) if fn is not None else wrap


def member_for_crew_index(crew_index, player_data, station_crew):
    if crew_index == PLAYER_CREW_INDEX:
        return player_data
    return station_crew[crew_index]


def is_players_own_job(player_data, job_name):
    """Whether the player holds job_name, so nobody can talk to or call themselves."""
    return player_data.get("job") == job_name


def available_npc(game, job_name):
    """On-duty, non-jailed NPC holding job_name (never the player's own job), or None."""
    if is_players_own_job(game.player_data, job_name):
        return None
    npc = on_duty_npc_for_job(game.station_crew, job_name)
    if npc is None or is_jailed(npc):
        return None
    return npc


def npc_contact_widgets(game, job_name, *, talk_label, talk_action, absent_flavor=None):
    """Widgets for an NPC-dependent action, gated on that NPC being present.

    - If the player themself holds job_name, nothing is shown.
    - If an on-duty NPC holds job_name, show the normal action button.
    - If that NPC is jailed, show their release countdown.
    - If that NPC is off duty, show a status line plus a "Call {name}" button.
    - If nobody holds job_name at all, show nothing.
    """
    if is_players_own_job(game.player_data, job_name):
        return []

    if available_npc(game, job_name) is not None:
        return [button(talk_label, f"room.{talk_action}")]

    away_npc = any_npc_for_job(game.station_crew, job_name)
    if away_npc is None:
        return []

    if is_jailed(away_npc):
        return [text_line(jailed_away_text(away_npc, get_elapsed_seconds(game.player_data)), color="orange", style="italic")]

    return [
        text_line(absent_flavor or f"The {job_name} is away from their post.", color="lightgray", style="italic"),
        button(f"Call {away_npc.get('name', job_name)}", "room.call_npc", job=job_name),
    ]


class SpecialRoomBase:
    """Shared shell for door-keyed special rooms (not Quarters)."""

    ROOM_TITLE = ""
    ROOM_HEADING = ""
    ROOM_DESCRIPTION = ""
    DOOR_KEY = None
    # Station menu entries: {"label", "mode", "subdepartments"?}
    STATION_ENTRIES = ()
    # Jobs whose NPCs this room's contact sections can call back.
    CONTACT_JOBS = ()

    def __init__(self, game):
        self.game = game
        self.player_data = game.player_data
        self.station_crew = game.station_crew

    def add_note(self, text):
        self.game.add_note(text)

    def can_control(self):
        return can_control_door(self.player_data, self.DOOR_KEY)

    def available_stations(self):
        return [
            entry for entry in self.STATION_ENTRIES
            if entry.get("subdepartments") is None
            or self.player_data["subdepartment"] in entry["subdepartments"]
        ]

    def station_allowed(self, mode):
        return self.can_control() and any(e["mode"] == mode for e in self.available_stations())

    def view(self):
        style = room_lighting_chrome(self.player_data)
        return {
            "type": "room",
            "title": self.ROOM_TITLE,
            "heading": self.ROOM_HEADING,
            "description": self.ROOM_DESCRIPTION + style["power_desc"],
            "style": style,
            "buttons": self.buttons(),
        }

    def buttons(self):
        mode = self.game.ui.get("room_mode", "menu")
        if mode == "options":
            return self.room_options()
        if mode != "menu":
            widgets = self.mode_buttons(mode)
            if widgets is not None:
                return widgets
        return self.station_menu()

    def room_options(self):  # pragma: no cover - every room overrides this
        return []

    def mode_buttons(self, mode):  # pragma: no cover - every room overrides this
        """Widgets for a room-specific menu mode, or None if mode is unknown."""
        return None

    def station_menu(self):
        """Authorized station menu, or the regular room options."""
        if not self.can_control():
            return self.room_options()
        widgets = [
            button(entry["label"], "room.open_station", mode=entry["mode"])
            for entry in self.available_stations()
        ]
        widgets.append(button("Lock/Unlock Door", "room.toggle_door"))
        widgets.append(button("Room Options", "room.set_mode", mode="options"))
        return widgets

    def back_to_station_menu(self):
        """'Back to Station Menu' when the player can control the room door."""
        if self.can_control():
            return [button("Back to Station Menu", "room.set_mode", mode="menu")]
        return []

    def perform(self, name, args):
        method = getattr(self, name, None)
        if not callable(method) or not getattr(method, "room_action", False):
            return
        if method.station_mode and not self.station_allowed(method.station_mode):
            return
        method(**args)

    @room_action
    def set_mode(self, mode):
        if mode in ("menu", "options"):
            self.game.ui["room_mode"] = mode

    @room_action
    def open_station(self, mode):
        if self.station_allowed(mode):
            self.game.ui["room_mode"] = mode

    @room_action
    def toggle_door(self):
        toggle_door_lock(self.game, self.DOOR_KEY)

    @room_action
    def call_npc(self, job):
        if job not in self.CONTACT_JOBS or is_players_own_job(self.player_data, job):
            return
        away_npc = any_npc_for_job(self.station_crew, job)
        if away_npc is None:
            return

        elapsed_seconds = get_elapsed_seconds(self.player_data)
        if is_jailed(away_npc):
            self.game.alert("In Jail", jailed_away_text(away_npc, elapsed_seconds))
            return

        success, message = call_npc(away_npc, elapsed_seconds)
        self.game.alert("Call Successful" if success else "No Answer", message)
        if success:
            # Security Guard / Captain players scan anyone they call back for warrants.
            offer_player_arrest_choice(self.game, away_npc, place="call")

    @room_action
    def exit(self):
        """Leave the room unless the player is jailed. A locked door only stops people coming in."""
        if is_jailed(self.player_data) and self.DOOR_KEY == SECURITY_KEY:
            self.game.alert("In Jail", player_jail_text(self.player_data))
            return
        self.game.leave_room()


MANIFEST_DEPARTMENTS = {
    "COMMAND": ["Captain", "Head of Personnel"],
    "SECURITY": ["Security Guard"],
    "MEDICAL": ["Doctor"],
    "ENGINEERING": ["Engineer"],
    "BOTANY": ["Botanist"],
    "SERVICE": ["Bartender"],
    "CIVILIAN": ["Staff Assistant"],
}


@register_panel("crew_manifest", "Crew Manifest")
def crew_manifest_panel(game, state):
    player_data = game.player_data
    all_crew = [player_data] + game.station_crew
    departments = []
    for dept_name, jobs_in_dept in MANIFEST_DEPARTMENTS.items():
        members = []
        for crew_member in all_crew:
            job = crew_member.get("job")
            if job not in jobs_in_dept:
                continue
            is_player = crew_member is player_data
            tags = (
                (" (YOU)" if is_player else "")
                + (" [WANTED]" if crew_member.get("warrant", False) else "")
                + (" [JAILED]" if crew_member.get("in_jail", False) else "")
            )
            members.append({"text": f"- {job}: {crew_member.get('name')}{tags}", "is_player": is_player})
        departments.append({"name": dept_name, "members": members})
    return {"departments": departments}
