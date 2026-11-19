"""The PDA every crew member carries, and the files on their computer.

player_data["pda"] holds:
    messages  [{"at": game seconds, "subject", "text", "unread"}], oldest first, up to MAX_MESSAGES
    warned    the keys of the needs at the player's job they have already been messaged about

player_data["files"] maps a path to its text, for the files the player wrote ("home/<name>"). Guide files
("guide/<wiki page>.md") aren't stored: their text is the wiki page, which the template fetches, and they can't be
edited.

The PDA opens while it is held in a hand, and reads the files. The Quarters computer creates, edits and deletes the
player's own files.
"""

import re

from space_online.game.helper_methods.antagonists import loose_threats
from space_online.game.helper_methods.combat import capitalized
from space_online.game.helper_methods.engine import DAMAGE_WARNINGS, engine_output
from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.hazards import HAZARDS, hazard_rooms
from space_online.game.helper_methods.health_bands import is_incapacitated
from space_online.game.helper_methods.jail import has_fine, is_jailed, members_in_room, warrant_reason_text
from space_online.game.helper_methods.npc_movement import player_holds_post
from space_online.game.helper_methods.power_constants import BATTERY_CRITICAL, system_name, system_online
from space_online.game.helper_methods.station_air import RESERVOIR_LOW, contaminated, readings, reservoir_share
from space_online.game.helper_methods.station_status import collect_station_status
from space_online.game.helper_methods.ui_panels import current_feedback, panel_action, register_panel, set_feedback
from space_online.game.helper_methods.window_stock import other_side
from space_online.game.maps.donut import ATMOSPHERICS_KEY, CHEMISTRY_KEY, ROOMS
from space_online.game.objects.items import PDA_ID, holding
from space_online.game.special_rooms.service_window import SIDES

MAX_MESSAGES = 50
LOW_ORE = 2
LOW_REMEDIES = 1
MAX_BROADCAST_CHARS = 200
BROADCAST_PRESETS = (
    "All hands, return to your posts.",
    "Security to the Bridge.",
    "Medical emergency. Doctor to MedBay.",
    "All crew, make your way to Departures.",
)

GUIDE_FOLDER = "guide/"
HOME_FOLDER = "home/"
MAX_OWN_FILES = 20
MAX_FILE_CHARS = 4000
FILE_NAME = re.compile(r"[A-Za-z0-9 _.-]{1,40}")
# The wiki pages in every guide folder, after the job's own page and the pages its work leans on.
STATION_GUIDES = ("PDA", "Getting Started", "The Station", "Duties and Job Events", "Health", "Hazards",
                  "Items and Hands")
JOB_GUIDES = {
    "Engineer": ("Engineering", "Power", "Life Support"),
    "Security Guard": ("Security and Jail", "Antagonists", "Combat and Weapons"),
    "Doctor": ("Medical",),
    "Bartender": ("Bar",),
    "Chef": ("Kitchen", "Station Stores"),
    "Botanist": ("Botany", "Station Stores"),
    "Scientist": ("Chemistry", "Research", "Atmospherics", "Station Stores"),
    "Miner": ("Mining", "Station Stores"),
    "Quartermaster": ("Cargo", "Station Stores"),
    "Head of Personnel": ("Bridge and Personnel", "Crew"),
    "Captain": ("Bridge and Personnel", "Station Status", "Antagonists"),
}

# job -> (menu label, panel, the state it opens with) for the jobs whose PDA has an app of its own.
JOB_APPS = {
    "Engineer": ("Power Readout", "power_readout", {}),
    "Doctor": ("Crew Vitals", "crew_vitals", {"read_only": True}),
    "Security Guard": ("Scan Crew", "scan_crew", {}),
    "Head of Personnel": ("Access Control", "hop_console", {}),
    "Captain": ("Broadcast", "broadcast", {}),
    "Miner": ("Ore Log", "ore_log", {}),
}


def new_pda():
    return {"messages": [], "warned": []}


def send(player_data, subject, text):
    """Put a message on the player's PDA. It waits there until they read it."""
    messages = player_data["pda"]["messages"]
    messages.append({"at": get_elapsed_seconds(player_data), "subject": subject, "text": text, "unread": True})
    del messages[:-MAX_MESSAGES]


def unread_count(player_data):
    return sum(message["unread"] for message in player_data["pda"]["messages"])


def pda_button(player_data):
    """The label of the screen's PDA button, or None while the PDA isn't in a hand."""
    if not holding(player_data, PDA_ID):
        return None
    unread = unread_count(player_data)
    return f"PDA ({unread})" if unread else "PDA"


# --- Needs at the player's job -------------------------------------------------
# Each returns {key: (subject, text)} for what the job is needed for right now.

def _miner_needs(game):
    if game.player_data["stores"]["ore"] > LOW_ORE:
        return {}
    return {"ore": ("Engineering", "The fabricator is almost out of ore. Send some up from the Mining Bay.")}


def _botanist_needs(game):
    return {f"produce:{name}": ("Kitchen", f"The kitchen is out of {name.lower()}. Send some from the Botany Lab.")
            for name, count in game.player_data["stores"]["produce"].items() if count == 0}


def _air_needs(game):
    atmos = game.player_data["atmos"]
    needs = {}
    if any(row["past"] and row["low"] for row in readings(atmos["air"])):
        needs["air:low"] = ("Atmospherics", "The station air is low on Oxygen.")
    if contaminated(atmos["air"]):
        needs["air:contaminated"] = ("Atmospherics", "The station air is contaminated.")
    if reservoir_share(atmos["reservoir"]) < RESERVOIR_LOW:
        needs["reservoir"] = ("Atmospherics", "The life support reservoir is nearly empty.")
    return needs


def _scientist_needs(game):
    """The Scientist who holds the Chemistry post keeps MedBay in remedies, and the one who holds the Atmospherics
    post looks after the station's air."""
    player_data = game.player_data
    needs = _air_needs(game) if player_holds_post(player_data, "Scientist", ATMOSPHERICS_KEY) else {}
    if player_holds_post(player_data, "Scientist", CHEMISTRY_KEY) and player_data["stores"]["remedies"] <= LOW_REMEDIES:
        needs["remedies"] = ("MedBay", "MedBay is almost out of remedies. Send some from Chemistry.")
    return needs


def _doctor_needs(game):
    return {f"critical:{npc['name']}": ("Crew Vitals", f"{npc['name']} is in critical condition.")
            for npc in game.station_crew if is_incapacitated(npc)}


def _engineer_needs(game):
    player_data = game.player_data
    power = player_data["station_power"]
    needs = {f"fault:{key}": ("Power", f"A fault has shut down the {system_name(key)}.") for key in power["faults"]}
    needs.update({f"hazard:{key}": ("Hazard", f"{HAZARDS[kind]['name'].capitalize()} in the {ROOMS[key].name}.")
                  for key, kind in hazard_rooms(player_data)})
    if power["battery_level"] <= BATTERY_CRITICAL:
        needs["battery"] = ("Power", "The station battery is critically low.")
    if not power["solar_charging"]:
        needs["solar"] = ("Power", "The solar panels are offline. Restart them from the Engineering Panel.")
    if power["dimmed_from"] is not None:
        needs["dimmed"] = ("Power", "Someone has dimmed the hallway lighting.")
    needs.update({f"engine:{level}": ("Combustion Engine", f"The combustion chamber is at {level}% damage.")
                  for level in DAMAGE_WARNINGS if player_data["engine"]["damage"] >= level})
    needs.update(_air_needs(game))
    return needs


def _quartermaster_needs(game):
    if not game.player_data["cargo"]["arrived"]:
        return {}
    return {"docked": ("Cargo Bay", "A supply pod has docked. Collect it at the Cargo Bay.")}


def _security_needs(game):
    needs = {f"warrant:{npc['name']}": ("Warrant", f"{npc['name']} is wanted: {warrant_reason_text(npc)}.")
             for npc in game.station_crew if npc["warrant"] and not is_jailed(npc)}
    needs.update({f"threat:{threat['name']}": ("Alert", f"{capitalized(threat['name'])} is loose on the station.")
                  for threat in loose_threats(game.player_data) if threat["revealed"]})
    return needs


def _hop_needs(game):
    """A crew member's request to change jobs, waiting at Access Control."""
    request = game.player_data.get("access_request")
    if not request or request.get("requester_name") in (None, game.player_data["name"]):
        return {}
    who, job = request["requester_name"], request["requested_job"]
    return {f"access:{who}:{job}": ("Access Request", f"{who} has asked to become {job}. Review it at Access Control "
                                                      "on the Bridge.")}


def _window_needs(game):
    """What the crew member across the service window has asked the player's side for."""
    player_data = game.player_data
    side = next((side for side, details in SIDES.items() if details.job == player_data["job"]), None)
    if side is None:
        return {}
    asking = other_side(side)
    return {f"window:{ingredient}": ("Service Window", f"The {SIDES[asking].job} asks for {amount} {ingredient} at "
                                                       "the service window.")
            for ingredient, amount in player_data["service_window"]["requests"][asking].items()}


JOB_NEEDS = {
    "Miner": _miner_needs,
    "Botanist": _botanist_needs,
    "Scientist": _scientist_needs,
    "Doctor": _doctor_needs,
    "Engineer": _engineer_needs,
    "Quartermaster": _quartermaster_needs,
    "Security Guard": _security_needs,
    "Head of Personnel": _hop_needs,
    "Bartender": _window_needs,
    "Chef": _window_needs,
}


def tick_pda_needs(game):
    """Message the player once about each need at their job, and again if it comes back after being met."""
    player_data = game.player_data
    pda = player_data["pda"]
    job_needs = JOB_NEEDS.get(player_data["job"])
    needs = job_needs(game) if job_needs else {}
    for key, (subject, text) in needs.items():
        if key not in pda["warned"]:
            send(player_data, subject, text)
    pda["warned"] = sorted(needs)


# --- The PDA menu ----------------------------------------------------------------

@register_panel("pda", "PDA")
def pda_panel(game, state):
    player_data = game.player_data
    if not holding(player_data, PDA_ID):
        return None
    app = JOB_APPS.get(player_data["job"])
    return {"name": player_data["name"], "job": player_data["job"], "unread": unread_count(player_data),
            "app": app[0] if app else None, "orders": not player_holds_post(player_data, "Quartermaster")}


@panel_action("pda", "messages")
def open_messages(game, state, args):
    """Open the inbox. Everything in it counts as read from here on; what was unread is marked new this once."""
    new = unread_count(game.player_data)
    for message in game.player_data["pda"]["messages"]:
        message["unread"] = False
    game.open_panel("pda_messages", new=new)


@panel_action("pda", "stocks")
def open_stocks(game, state, args):
    game.open_panel("stock_market", read_only=True)


@panel_action("pda", "orders")
def open_orders(game, state, args):
    game.open_panel("order_request")


@panel_action("pda", "files")
def open_files(game, state, args):
    game.open_panel("files", read_only=True)


@panel_action("pda", "app")
def open_app(game, state, args):
    app = JOB_APPS.get(game.player_data["job"])
    if app:
        game.open_panel(app[1], **app[2])


@register_panel("pda_messages", "PDA Messages")
def pda_messages_panel(game, state):
    messages = list(reversed(game.player_data["pda"]["messages"]))
    return {"messages": [{"time": f"T+{int(message['at'] // 60)}m", "subject": message["subject"],
                          "text": message["text"], "new": index < state["new"]}
                         for index, message in enumerate(messages)]}


# --- Job apps --------------------------------------------------------------------

@register_panel("power_readout", "Power Readout")
def power_readout_panel(game, state):
    player_data = game.player_data
    return {"power": collect_station_status(player_data, game.station_crew)["power"],
            "engine_output": engine_output(player_data["engine"]),
            "hazards": [f"{HAZARDS[kind]['name'].capitalize()} in the {ROOMS[key].name}"
                        for key, kind in hazard_rooms(player_data)]}


def _crew_here(game):
    return members_in_room(game.station_crew, game.location_key())


def _crew_reading(player_data, member):
    """What a Security Guard's PDA reads off a crew member: their record, and how they stand with the incidents."""
    record = []
    if member["warrant"]:
        record.append(f"Wanted: {warrant_reason_text(member)}.")
    if has_fine(member):
        record.append(f"Owes a fine of {member['fine_amount']:.0f} credits.")
    incidents = [incident for incident in player_data["incidents"] if incident["away"] is not None]
    away = sum(member["name"] in incident["away"] for incident in incidents)
    return " ".join([
        f"{member['job']}.",
        *(record or ["No warrant or fine on record."]),
        f"Away from their post for {away} of this shift's {len(incidents)} incidents." if incidents
        else "No incidents on record this shift.",
    ])


@register_panel("scan_crew", "Scan Crew")
def scan_crew_panel(game, state):
    return {"crew": [{"name": member["name"], "job": member["job"]} for member in _crew_here(game)]}


@panel_action("scan_crew", "scan")
def scan_member(game, state, args):
    member = next((member for member in _crew_here(game) if member["name"] == args["name"]), None)
    if member is not None:
        game.alert(f"PDA Scan: {member['name']}", _crew_reading(game.player_data, member))


@register_panel("broadcast", "Broadcast")
def broadcast_panel(game, state):
    return {"presets": BROADCAST_PRESETS, "max": MAX_BROADCAST_CHARS, "feedback": current_feedback(state)}


@panel_action("broadcast", "send")
def send_broadcast(game, state, args):
    """Announce the Captain's words to the station. Nobody acts on them; they are only heard."""
    text = " ".join(str(args.get("text", "")).split())[:MAX_BROADCAST_CHARS]
    if not text:
        set_feedback(state, "Type a message or pick one.", "orange")
    elif not system_online(game.player_data, "communication_array"):
        set_feedback(state, "The Communication Array is down. Nothing goes out.", "red")
    else:
        game.announce("Captain's Broadcast", text)
        game.add_note(f"Broadcast to the station: {text}")
        set_feedback(state, "Broadcast sent.")


# --- Files -----------------------------------------------------------------------

def guide_titles(job):
    """The wiki pages in a job's guide folder: the job's own page, the pages its work leans on, then the basics."""
    return tuple(dict.fromkeys((job, *JOB_GUIDES.get(job, ()), *STATION_GUIDES)))


def _guide_path(title):
    return f"{GUIDE_FOLDER}{title}.md"


def _file(player_data, path):
    """A file's name, the wiki page it comes from (None for a home file) and the player's text for a home file (None
    for a guide file, which always reads as its wiki page). None when there is no such file."""
    if path.startswith(HOME_FOLDER):
        text = player_data["files"].get(path)
        return None if text is None else {"name": path.removeprefix(HOME_FOLDER), "guide": None, "text": text}
    guide = next((title for title in guide_titles(player_data["job"]) if _guide_path(title) == path), None)
    return None if guide is None else {"name": f"{guide}.md", "guide": guide, "text": None}


def _own_file_path(state, path):
    """path when it is one of the player's home files and state is at the computer, not the PDA's read-only view."""
    return None if state.get("read_only") or not path.startswith(HOME_FOLDER) else path


@register_panel("files", "Files")
def files_panel(game, state):
    player_data = game.player_data
    files = player_data["files"]
    return {
        "read_only": bool(state.get("read_only")),
        "guide": [{"path": _guide_path(title), "name": f"{title}.md"} for title in guide_titles(player_data["job"])],
        "home": [{"path": path, "name": path.removeprefix(HOME_FOLDER)}
                 for path in sorted(files) if path.startswith(HOME_FOLDER)],
        "feedback": current_feedback(state),
    }


@panel_action("files", "open")
def open_file(game, state, args):
    path = str(args["path"])
    if _file(game.player_data, path) is not None:
        game.open_panel("file", path=path, read_only=bool(state.get("read_only")))


@panel_action("files", "delete")
def delete_file(game, state, args):
    path = _own_file_path(state, str(args.get("path", "")))
    if path:
        game.player_data["files"].pop(path, None)


@panel_action("files", "new")
def new_file(game, state, args):
    if state.get("read_only"):
        return
    files = game.player_data["files"]
    name = str(args.get("name", "")).strip()
    path = HOME_FOLDER + name
    if not FILE_NAME.fullmatch(name):
        set_feedback(state, "A file name is 1 to 40 letters, digits, spaces, dots, hyphens or underscores.", "orange")
    elif path in files:
        set_feedback(state, f"You already have a file called {name}.", "orange")
    elif sum(existing.startswith(HOME_FOLDER) for existing in files) >= MAX_OWN_FILES:
        set_feedback(state, f"Your home folder is full. It holds {MAX_OWN_FILES} files.", "orange")
    else:
        files[path] = ""
        game.open_panel("file_edit", path=path)


@register_panel("file", "File")
def file_panel(game, state):
    file = _file(game.player_data, state["path"])
    if file is None:
        return None
    return {**file, "title": file["name"], "read_only": bool(state.get("read_only")),
            "editable": _own_file_path(state, state["path"]) is not None,
            "links": [f"{title}.md" for title in guide_titles(game.player_data["job"])],
            "back": bool(state.get("from_link"))}


@panel_action("file")
def follow(game, state, args):
    """Open the guide file a link in this one points to, on top of it."""
    path = GUIDE_FOLDER + str(args.get("name", ""))
    if _file(game.player_data, path) is not None:
        game.open_panel("file", path=path, read_only=bool(state.get("read_only")), from_link=True)


@panel_action("file")
def back(game, state, args):
    """Return to the file whose link opened this one."""
    if state.get("from_link"):
        game.close_panel("file")


@panel_action("file")
def close_reading(game, state, args):
    """Close this file and every file whose links led to it, back to the Files list."""
    while game.top_panel() and game.top_panel()["type"] == "file":
        game.close_panel()


@panel_action("file")
def edit(game, state, args):
    path = _own_file_path(state, state["path"])
    if path:
        game.open_panel("file_edit", path=path)


@panel_action("file")
def remove(game, state, args):
    delete_file(game, state, {"path": state["path"]})


@register_panel("file_edit", "Edit File")
def file_edit_panel(game, state):
    file = _file(game.player_data, state["path"])
    if file is None or file["guide"] is not None:
        return None
    return {**file, "title": f"Editing {file['name']}", "max": MAX_FILE_CHARS, "feedback": current_feedback(state)}


@panel_action("file_edit")
def save(game, state, args):
    if not _own_file_path(state, state["path"]):
        return
    text = str(args.get("text", "")).replace("\r\n", "\n")
    if len(text) > MAX_FILE_CHARS:
        set_feedback(state, f"A file holds {MAX_FILE_CHARS} characters. This is {len(text)}.", "orange",
                     seconds=None)
        return
    game.player_data["files"][state["path"]] = text
    game.close_panel("file_edit")
