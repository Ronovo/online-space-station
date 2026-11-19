import datetime

from space_online.game.character_methods.character_creation import group_jobs_by_department
from space_online.game.helper_methods.door_control import (
    can_control_door,
    toggle_door_lock,
)
from space_online.game.helper_methods.atmos import tank_index
from space_online.game.helper_methods.lighting_helper import lighting_style
from space_online.game.helper_methods.hazards import HAZARD_ROOM_KEYS, HAZARDS, fix_hazard, room_hazard
from space_online.game.helper_methods.health_bands import is_incapacitated
from space_online.game.helper_methods.npc_movement import (
    call_npc,
    crew_named,
    on_duty_npc_for_job,
    player_holds_post,
    post_holder,
)
from space_online.game.helper_methods.power_constants import system_online
from space_online.game.helper_methods.jail import (
    is_jailed,
    jailed_away_text,
    offer_player_arrest_choice,
    player_jail_text,
)
from space_online.game.helper_methods.errands import (
    ROOM_ERRAND_KINDS,
    duty_by_id,
    finish_duty,
    open_duties,
)
from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.stores import STORE_ROOMS, add_to_stores, send_from_inventory, store_of
from space_online.game.helper_methods.ui_panels import panel_action, register_panel
from space_online.game.maps.donut import SECURITY_KEY
from space_online.game.objects.botany_items import water_npc_planters
from space_online.game.objects.items import (
    add_to_inventory,
    carried_or_held,
    get_item_definition,
    inventory_index,
    remove_one_from_inventory,
)

def lighting_chrome(player_data, place="room"):
    """The style dict for a room or hallway at the station's current lighting."""
    return lighting_style(player_data["station_power"]["system_levels"]["hallway_lighting"], place=place)


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
    """Room menu widget: a line of text. style is None, 'title', 'italic' or 'status' (an italic status line)."""
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


def member_named(game, name):
    """The player or the crew member called name, or None."""
    if name == game.player_data["name"]:
        return game.player_data
    return crew_named(game.station_crew, name)


def no_signal(game):
    """Say so and return True when the Communication Array is down, so nobody can be called."""
    if system_online(game.player_data, "communication_array"):
        return False
    game.alert("No Signal", "The Communication Array is down. Nobody can be called.", kind="warning")
    return True


def incapacitated_text(member):
    return f"{member['name']} is too badly hurt to work and needs a doctor."


def available_npc(game, job_name, room_key):
    """The NPC posted as job_name in room_key if they are at their post and able to work (never a post the player
    holds), or None. A hazard in the room clears them out of it."""
    if player_holds_post(game.player_data, job_name, room_key) or room_hazard(game.player_data, room_key):
        return None
    return on_duty_npc_for_job(game.station_crew, job_name, room_key)


def unavailable_text(game, npc, job_name, room_key):
    """Why npc, posted as job_name in room_key, can't work there: jailed, too hurt, or cleared out by a hazard. None
    when nothing but being away from the post keeps them."""
    if is_jailed(npc):
        return jailed_away_text(npc, get_elapsed_seconds(game.player_data))
    if is_incapacitated(npc):
        return incapacitated_text(npc)
    hazard = room_hazard(game.player_data, room_key)
    if hazard:
        return f"The {job_name} has cleared out until the {HAZARDS[hazard]['name']} is dealt with."
    return None


def npc_contact_widgets(game, job_name, room_key, *, talk_label=None, talk_action=None, absent_flavor=None):
    """Widgets for an NPC-dependent action, gated on the NPC posted as job_name in room_key being present.

    - If the player themself holds that post, or nobody holds it at all, nothing is shown.
    - If an on-duty NPC holds it, show the normal action button, or nothing with no talk_label.
    - If that NPC is jailed, show their release countdown.
    - If that NPC is too badly hurt to work, say so.
    - If a hazard has cleared the room, say so.
    - If that NPC is off duty, show a status line plus a "Call {name}" button.
    """
    if player_holds_post(game.player_data, job_name, room_key):
        return []

    if available_npc(game, job_name, room_key) is not None:
        return [button(talk_label, f"room.{talk_action}")] if talk_label else []

    away_npc = post_holder(game.station_crew, job_name, room_key)
    if away_npc is None:
        return []

    reason = unavailable_text(game, away_npc, job_name, room_key)
    if reason:
        return [text_line(reason, color="orange", style="status")]

    return [
        text_line(absent_flavor or f"The {job_name} is away from their post.", color="lightgray", style="status"),
        button(f"Call {away_npc.get('name', job_name)}", "room.call_npc", job=job_name),
    ]


class RoomBase:
    """A room whose @room_action methods the client can call."""

    ROOM_TITLE = ""

    def __init__(self, game):
        self.game = game
        self.player_data = game.player_data
        self.station_crew = game.station_crew

    def perform(self, name, args):
        method = getattr(self, name, None)
        if not callable(method) or not getattr(method, "room_action", False):
            return
        if method.station_mode and not self.station_allowed(method.station_mode):
            return
        method(**args)


class SpecialRoomBase(RoomBase):
    """Shared shell for door-keyed special rooms (not Quarters)."""

    ROOM_HEADING = ""
    ROOM_DESCRIPTION = ""
    DOOR_KEY = None
    # Station menu entries: {"label", "mode", "subdepartments"?}
    STATION_ENTRIES = ()
    # The posts whose NPCs this room's contact sections can call back: {job: room key of the post}.
    CONTACT_POSTS = {}

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

    def hazard(self):
        """The kind of hazard in this room, or None."""
        return room_hazard(self.player_data, self.DOOR_KEY) if self.can_have_hazard() else None

    def view(self):
        style = lighting_chrome(self.player_data)
        hazard = self.hazard()
        return {
            "type": "room",
            "title": self.ROOM_TITLE,
            "heading": self.ROOM_HEADING,
            "description": self.ROOM_DESCRIPTION,
            "light": style["light"],
            "hazard": (HAZARDS[hazard]["here"] if hazard else "") if self.can_have_hazard() else None,
            "style": style,
            "buttons": self.buttons(),
        }

    def can_have_hazard(self):
        return self.DOOR_KEY in HAZARD_ROOM_KEYS

    def buttons(self):
        hazard = self.hazard()
        fix = [button(HAZARDS[hazard]["fix"], "room.fix_hazard")] if hazard else []
        return fix + self.menu_buttons()

    def menu_buttons(self):
        mode = self.game.ui.get("room_mode", "menu")
        if mode == "options":
            return self.options()
        if mode != "menu":
            widgets = self.mode_buttons(mode)
            if widgets is not None:
                return widgets
        return self.station_menu()

    def options(self):
        """Room options, led by a button for each duty that is done here."""
        return self.duty_widgets() + self.room_options()

    def room_duties(self):
        """The deliver and help duties for this room whose giver is here to take them."""
        return [duty for duty in open_duties(self.player_data, ROOM_ERRAND_KINDS, self.DOOR_KEY)
                if available_npc(self.game, duty["giver"], self.DOOR_KEY) is not None]

    def duty_widgets(self):
        """A button for each duty done here."""
        return [
            button(f"Deliver {get_item_definition(duty['item'])['name']}" if duty["kind"] == "deliver"
                   else f"Help the {duty['giver']} {duty['label']}", "room.complete_duty", duty_id=duty["id"])
            for duty in self.room_duties()
        ]

    def station_menu(self):
        """Authorized station menu, or the regular room options."""
        if not self.can_control():
            return self.options()
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
    def fix_hazard(self):
        fix_hazard(self.game, self.DOOR_KEY)

    @room_action
    def call_npc(self, job):
        room_key = self.CONTACT_POSTS.get(job)
        if room_key is None or player_holds_post(self.player_data, job, room_key):
            return
        away_npc = post_holder(self.station_crew, job, room_key)
        if away_npc is None:
            return

        if is_jailed(away_npc):
            self.game.alert("In Jail", jailed_away_text(away_npc, get_elapsed_seconds(self.player_data)))
            return
        if is_incapacitated(away_npc):
            self.game.alert("Hurt", incapacitated_text(away_npc))
            return
        if no_signal(self.game):
            return

        success, message = call_npc(away_npc)
        self.game.alert("Call Successful" if success else "No Answer", message)
        if success:
            offer_player_arrest_choice(self.game, away_npc, place="call")

    @room_action
    def complete_duty(self, duty_id):
        """Finish a deliver or help duty for the giver in this room."""
        duty = duty_by_id(self.player_data, duty_id)
        if duty not in self.room_duties():
            return
        giver, label, reward = duty["giver"], duty["label"], duty["reward"]
        if duty["kind"] == "help":
            if giver == "Botanist":
                water_npc_planters(self.player_data, get_elapsed_seconds(self.player_data))
            finish_duty(self.game, duty, f"Helped the {giver} {label} for {reward} credits.",
                        f"You {label}. The {giver} pays you {reward} credits.", reward)
            return
        index = (tank_index(self.player_data, duty["gas"]) if duty.get("gas")
                 else inventory_index(self.player_data, duty["item"]))
        if index is None:
            self.game.alert("Nothing to Deliver", f"You don't have {label} to deliver.")
            return
        remove_one_from_inventory(self.player_data, index)
        if STORE_ROOMS.get(store_of(duty["item"])) == self.DOOR_KEY:
            add_to_stores(self.player_data, duty["item"])
        finish_duty(self.game, duty, f"Delivered {label} to the {giver} for {reward} credits.",
                    f"The {giver} takes {label} and pays you {reward} credits.", reward)

    @room_action
    def exit(self):
        """Leave the room unless the player is jailed. A locked door only stops people coming in."""
        if is_jailed(self.player_data) and self.DOOR_KEY == SECURITY_KEY:
            self.game.alert("In Jail", player_jail_text(self.player_data))
            return
        self.game.leave_room()


def send_to_stores(game, store, where, nothing):
    """Send everything the player carries that belongs in store up to it, keeping back one of each item an open
    deliver duty asks for, and say what went and what was kept."""
    wanted = [duty["item"] for duty in open_duties(game.player_data, ("deliver",))]
    sent, kept = send_from_inventory(game.player_data, store, keep=wanted)
    kept_line = f" Kept back: {_listed(kept)}." if kept else ""
    if not sent:
        game.alert("Station Stores", nothing + kept_line)
        return
    game.add_note(f"Sent {_listed(sent)} to {where}.{kept_line}")
    game.alert("Station Stores", f"You send {_listed(sent)} to {where}.{kept_line}")


def _listed(counts):
    return ", ".join(f"{count} {name}" for name, count in counts.items())


def send_produce_to_kitchen(game):
    send_to_stores(game, "produce", "the Kitchen", "You have no produce the kitchen cooks with.")


def issue_gear(game, item_ids, title, source, kit):
    """Hand the player whichever of item_ids they aren't already carrying or holding."""
    missing = [item_id for item_id in item_ids if not carried_or_held(game.player_data, (item_id,))]
    if not missing:
        game.alert(title, f"You already have {kit}.")
        return
    for item_id in missing:
        add_to_inventory(game.player_data, get_item_definition(item_id))
    names = " and ".join(get_item_definition(item_id)["name"] for item_id in missing)
    game.add_note(f"Took the {names} from {source}.")
    game.alert(title, f"You take the {names} from {source}. Equip them from Hands to use them.")


def sell_item(game, item_id, price, seller):
    """Charge price and put item_id in the inventory. Returns False when the player can't afford it."""
    item = get_item_definition(item_id)
    if game.player_data["credits"] < price:
        game.alert("Insufficient Credits", f"You don't have enough credits to buy {item['name']}.")
        return False
    game.player_data["credits"] -= price
    add_to_inventory(game.player_data, item)
    game.add_note(f"Bought {item['name']} from {seller} for {price} credits.")
    return True


def register_stand(panel_type, title, intro, prices, seller):
    """A stand where a crew member sells items for the credits in prices ({item id: price})."""
    @register_panel(panel_type, title, template="stand")
    def stand_panel(game, state):
        return {
            "title": title,
            "intro": intro,
            "credits": game.player_data["credits"],
            "goods": [{"id": item_id, "name": get_item_definition(item_id)["name"], "price": price}
                      for item_id, price in prices.items()],
        }

    @panel_action(panel_type, "buy")
    def buy(game, state, args):
        item_id = args["item_id"]
        if item_id in prices:
            sell_item(game, item_id, prices[item_id], seller)


@register_panel("crew_manifest", "Crew Manifest")
def crew_manifest_panel(game, state):
    player_data = game.player_data
    all_crew = [player_data] + game.station_crew
    departments = []
    for dept_name, jobs_in_dept in group_jobs_by_department():
        members = []
        for crew_member in sorted((member for member in all_crew if member["job"] in jobs_in_dept),
                                  key=lambda member: jobs_in_dept.index(member["job"])):
            job = crew_member["job"]
            is_player = crew_member is player_data
            tags = (
                (" (YOU)" if is_player else "")
                + (" [WANTED]" if crew_member.get("warrant", False) else "")
                + (" [JAILED]" if crew_member.get("in_jail", False) else "")
            )
            members.append({"text": f"- {job}: {crew_member.get('name')}{tags}", "is_player": is_player})
        departments.append({"name": dept_name.upper(), "members": members})
    return {"departments": departments}
