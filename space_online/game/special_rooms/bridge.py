import random

from space_online.game.character_methods.character_creation import JOBS, REQUESTABLE_JOBS
from space_online.game.helper_methods.npc_movement import reassign_npc_post
from space_online.game.helper_methods.ui_panels import (
    choice_handler,
    current_feedback,
    panel_action,
    register_panel,
    set_feedback,
)
from space_online.game.special_rooms.shared import (
    PLAYER_CREW_INDEX,
    SpecialRoomBase,
    available_npc,
    button,
    member_for_crew_index,
    npc_contact_widgets,
    room_action,
    text_line,
)
from space_online.game.maps.donut import BRIDGE_KEY


def pending_access_request(player_data):
    """The access request waiting for the HoP, or None."""
    request = player_data.get("access_request")
    return request if request and request.get("requested_job") else None


def _approved_suffix(solar_activated):
    return " Solar arrays are now active." if solar_activated else ""


class Bridge(SpecialRoomBase):
    ROOM_TITLE = "Bridge"
    ROOM_HEADING = "Station Bridge"
    ROOM_DESCRIPTION = (
        "The bridge is the command center of the station. Multiple workstations with monitors "
        "displaying various station systems are arranged around the room. This is where the Captain "
        "and Department Heads coordinate station operations."
    )
    DOOR_KEY = BRIDGE_KEY
    STATION_ENTRIES = (
        {"label": "Enter Captain's Station", "mode": "captain_station", "subdepartments": {"Captain"}},
        {"label": "Enter HoP's Station", "mode": "hop_station", "subdepartments": {"Captain", "HoP"}},
    )
    CONTACT_JOBS = ("Captain", "Head of Personnel")

    def room_options(self):
        return [button("Talk to Ship Leadership", "room.talk_to_leadership")] + self.back_to_station_menu()

    def mode_buttons(self, mode):
        if mode == "leadership":
            return self._leadership_buttons()
        if mode == "hop_talk" and available_npc(self.game, "Head of Personnel"):
            return [
                text_line("Head of Personnel", style="title"),
                button("Access Control", "room.show_access_control"),
                button("Talk to HoP", "room.resolve_hop_access_request"),
                button("Return to Bridge", "room.set_mode", mode="options"),
            ]
        if mode == "captain_station" and self.station_allowed(mode):
            return [
                text_line("Captain's Station", style="title"),
                button("Station Status", "room.show_station_status"),
                button("Security Alerts", "room.security_alerts"),
                button("Crew Manifest", "room.show_crew_manifest"),
                button("Back to Bridge Menu", "room.set_mode", mode="menu"),
            ]
        if mode == "hop_station" and self.station_allowed(mode):
            return [
                text_line("Head of Personnel Station", style="title"),
                button("Crew Manifest", "room.show_crew_manifest"),
                button("Job Assignments", "room.show_job_assignments"),
                button("Access Control", "room.show_hop_access_control_console"),
                button("Back to Bridge Menu", "room.set_mode", mode="menu"),
            ]
        return None

    def _leadership_present(self):
        """Return which leadership jobs exist on the station (player + NPCs)."""
        jobs = {member.get("job") for member in [self.player_data] + self.station_crew}
        return {"captain": "Captain" in jobs, "hop": "Head of Personnel" in jobs}

    def _leadership_buttons(self):
        present = self._leadership_present()
        widgets = [text_line("Ship Leadership", style="title")]
        if present["captain"]:
            widgets += npc_contact_widgets(
                self.game,
                "Captain",
                talk_label="Talk to Captain",
                talk_action="talk_to_captain",
                absent_flavor="The Captain is away from the bridge.",
            )
        if present["hop"]:
            widgets += npc_contact_widgets(
                self.game,
                "Head of Personnel",
                talk_label="Talk to HoP",
                talk_action="show_hop_talk_menu",
                absent_flavor="The Head of Personnel is away from the bridge.",
            )
        widgets.append(button("Return to Bridge", "room.set_mode", mode="options"))
        return widgets

    @room_action
    def talk_to_leadership(self):
        """Show Captain/HoP talk options when leadership is present on the station."""
        present = self._leadership_present()
        if not present["captain"] and not present["hop"]:
            self.game.alert("Bridge", "Captain and Department Heads are not in.")
            return
        self.game.ui["room_mode"] = "leadership"

    @room_action
    def talk_to_captain(self):
        """Captain is always too busy for casual conversation."""
        if available_npc(self.game, "Captain"):
            self.game.alert("Captain", "The Captain is too busy for your chats.")

    @room_action
    def show_hop_talk_menu(self):
        if available_npc(self.game, "Head of Personnel"):
            self.game.ui["room_mode"] = "hop_talk"

    @room_action
    def show_access_control(self):
        if available_npc(self.game, "Head of Personnel"):
            self.game.open_panel("access_request")

    @room_action
    def resolve_hop_access_request(self):
        """Talk to HoP: resolve a pending access request with a 50/50 approve/deny."""
        if available_npc(self.game, "Head of Personnel") is None:
            return
        request = pending_access_request(self.player_data)
        if request is None:
            self.game.alert(
                "Head of Personnel",
                "The HoP is busy. Use the Access Control terminal to put in a request.",
            )
            return

        job = request["requested_job"]
        requester = request.get("requester_name")
        for_crew = requester and requester != self.player_data.get("name")
        whose = f"{requester}'s" if for_crew else "your"
        if random.random() < 0.5:
            ok, solar_activated, error = apply_access_request_job(self.game, job)
            if error:
                self.game.alert("Head of Personnel", error)
            elif ok:
                now = f"{requester} is now {job}." if for_crew else f"You are now {job}."
                self.game.alert("Head of Personnel",
                                f"The HoP approved {whose} request. {now}{_approved_suffix(solar_activated)}")
        else:
            self.player_data.pop("access_request", None)
            self.game.alert("Head of Personnel", f"The HoP denied {whose} request for {job}.")

    @room_action(station="captain_station")
    def show_station_status(self):
        self.game.open_panel("station_status")

    @room_action(station="captain_station")
    def security_alerts(self):
        wanted = [member.get("name", "Unknown") for member in [self.player_data] + self.game.station_crew
                  if member.get("warrant") and not member.get("in_jail")]
        self.game.alert("Security Alerts",
                        f"Wanted crew at large: {', '.join(wanted)}." if wanted else "No security alerts reported.")

    @room_action
    def show_crew_manifest(self):
        if self.station_allowed("captain_station") or self.station_allowed("hop_station"):
            self.game.open_panel("crew_manifest")

    @room_action(station="hop_station")
    def show_job_assignments(self):
        self.game.open_panel("job_assignment")

    @room_action(station="hop_station")
    def show_hop_access_control_console(self):
        self.game.open_panel("hop_console")


def _grant_job(member, job):
    job_info = JOBS[job]
    member["job"] = job
    member["department"] = job_info["department"]
    member["subdepartment"] = job_info["subdepartment"]


def _activate_solar_for_engineer(game, job):
    """Assigning an Engineer turns the solar array on. Returns True if it changed."""
    if job != "Engineer":
        return False
    power = game.player_data["station_power"]
    if power.get("solar_charging"):
        return False
    power["solar_charging"] = True
    return True


def apply_access_request_job(game, job, confirmed=False):
    """Apply a pending access request to the player or requesting NPC, under the Job Assignments rules for
    the Captain.

    Returns (ok, solar_activated, error_message). Not ok with no message means the player was asked to
    confirm giving up the captaincy first.
    """
    player_data = game.player_data
    if job not in REQUESTABLE_JOBS:
        player_data.pop("access_request", None)
        return False, False, "Your access request was invalid and has been cleared."

    requester_name = player_data.get("access_request", {}).get("requester_name")

    # NPC-submitted request (HoP job event): update that crew member.
    if requester_name and requester_name != player_data.get("name"):
        npc = next((n for n in game.station_crew if n.get("name") == requester_name), None)
        player_data.pop("access_request", None)
        if npc is None:
            return False, False, "The requester is no longer on the station. Request cleared."
        if npc.get("job") == "Captain" and not _player_is_captain(player_data):
            return False, False, "Only the Captain can reassign the current Captain. Request cleared."
        _grant_job(npc, job)
        reassign_npc_post(npc, job)
        return True, _activate_solar_for_engineer(game, job), None

    if not confirmed and player_data.get("job") == "Captain" and not _npc_captain_exists(game):
        game.ask(
            "Confirm Reassignment",
            "You are about to give up captain access with no captain. Continue?",
            [("Yes", "confirm_access_request", {"job": job}), ("No", None, None)],
        )
        return False, False, None

    _grant_job(player_data, job)
    player_data.pop("access_request", None)
    return True, _activate_solar_for_engineer(game, job), None


@choice_handler("confirm_access_request")
def confirm_access_request(game, job):
    request = pending_access_request(game.player_data)
    if request != {"requested_job": job, "requester_name": game.player_data.get("name")}:
        return
    _, solar_activated, _ = apply_access_request_job(game, job, confirmed=True)
    game.close_panel("hop_console")
    game.alert("Access Control", f"You are now {job}.{_approved_suffix(solar_activated)}")


@register_panel("access_request", "Access Control")
def access_request_panel(game, state):
    job = state.get("job")
    player_name = game.player_data.get("name", "Unknown")
    if job:
        result = {"text": f"{player_name} → {job}", "color": "lightgreen" if state.get("submitted") else "white"}
    else:
        result = {"text": "Select a job to request.", "color": "cyan"}
    return {
        "jobs": REQUESTABLE_JOBS,
        "selected": job,
        "result": result,
        "feedback": current_feedback(state),
    }


@panel_action("access_request", "select")
def access_request_select(game, state, args):
    if args["job"] in REQUESTABLE_JOBS:
        state["job"] = args["job"]
        state["submitted"] = False


@panel_action("access_request")
def submit(game, state, args):
    job = state.get("job")
    if not job:
        set_feedback(state, "Select a job first.", "orange")
        return
    if job not in REQUESTABLE_JOBS:
        set_feedback(state, "That job cannot be requested here.", "red")
        return
    game.player_data["access_request"] = {
        "requested_job": job,
        "requester_name": game.player_data.get("name", "Unknown"),
    }
    state["submitted"] = True
    set_feedback(state, f"Request for {job} submitted for HoP approval.", "cyan")


@register_panel("hop_console", "Access Control")
def hop_console_panel(game, state):
    request = pending_access_request(game.player_data)
    return {
        "request": (
            f"{request.get('requester_name', 'Unknown')} → {request['requested_job']}" if request else None
        ),
        "feedback": current_feedback(state),
    }


@panel_action("hop_console")
def approve(game, state, args):
    req = pending_access_request(game.player_data)
    if req is None:
        set_feedback(state, "No pending request to approve.", "orange", seconds=None)
        return
    job = req["requested_job"]
    ok, solar_activated, error = apply_access_request_job(game, job)
    if error:
        set_feedback(state, error, "red", seconds=None)
        return
    if not ok:
        return
    game.close_panel("hop_console")
    game.alert("Access Control",
               f"Approved. {req.get('requester_name', 'Crew')} is now {job}.{_approved_suffix(solar_activated)}")


@panel_action("hop_console")
def deny(game, state, args):
    req = pending_access_request(game.player_data)
    if req is None:
        set_feedback(state, "No pending request to deny.", "orange", seconds=None)
        return
    game.player_data.pop("access_request", None)
    game.close_panel("hop_console")
    game.alert("Access Control", f"Denied request for {req['requested_job']}.")


def _player_is_captain(player_data):
    return player_data.get("subdepartment") == "Captain"


def _assignable_rows(game):
    """(crew_index, label) rows; Captain NPCs (and the player) only for a Captain."""
    player_is_captain = _player_is_captain(game.player_data)
    rows = []
    if player_is_captain:
        rows.append((
            PLAYER_CREW_INDEX,
            f"{game.player_data.get('name', 'Unknown')} ({game.player_data.get('job', 'Unknown')}) (YOU)",
        ))
    for crew_index, npc in enumerate(game.station_crew):
        if not player_is_captain and npc.get("job") == "Captain":
            continue
        rows.append((crew_index, f"{npc.get('name', 'Unknown')} ({npc.get('job', 'Unknown')})"))
    return rows


def _assignable_jobs(player_data):
    return [job for job in JOBS if job != "Captain" or _player_is_captain(player_data)]


@register_panel("job_assignment", "Job Assignment")
def job_assignment_panel(game, state):
    rows = _assignable_rows(game)
    crew_index = state.get("crew_index")
    if crew_index not in {index for index, _ in rows}:
        crew_index = None
    job = state.get("job")

    if crew_index is not None:
        member = member_for_crew_index(crew_index, game.player_data, game.station_crew)
        if job:
            result = {"text": f"{member.get('name', 'Unknown')} → {job}", "color": state.get("result_color", "white")}
        else:
            result = {"text": f"{member.get('name', 'Unknown')} - select a job.", "color": "cyan"}
    elif job:
        result = {"text": f"Select an NPC for {job}.", "color": "cyan"}
    else:
        result = {"text": "Select an NPC and a job to confirm.", "color": "cyan"}

    return {
        "rows": [{"index": index, "label": label} for index, label in rows],
        "jobs": _assignable_jobs(game.player_data),
        "crew_index": crew_index,
        "job": job,
        "result": result,
        "feedback": current_feedback(state),
    }


@panel_action("job_assignment")
def select_member(game, state, args):
    state["crew_index"] = int(args["index"])
    state["result_color"] = "white"


@panel_action("job_assignment")
def select_job(game, state, args):
    if args["job"] in JOBS:
        state["job"] = args["job"]
        state["result_color"] = "white"


def _npc_captain_exists(game):
    return any(npc.get("job") == "Captain" for npc in game.station_crew)


@panel_action("job_assignment")
def assign(game, state, args):
    crew_index = state.get("crew_index")
    job = state.get("job")
    if crew_index is None or not job:
        set_feedback(state, "Select both an NPC and a job first.", "orange")
        return
    if crew_index not in {index for index, _ in _assignable_rows(game)}:
        set_feedback(state, "Invalid NPC selection.", "red")
        return
    if job not in JOBS:
        set_feedback(state, "Invalid job selection.", "red")
        return

    player_is_captain = _player_is_captain(game.player_data)
    if job == "Captain" and not player_is_captain:
        set_feedback(state, "Only the Captain can assign the Captain role.", "orange")
        return

    member = member_for_crew_index(crew_index, game.player_data, game.station_crew)
    if not player_is_captain and crew_index != PLAYER_CREW_INDEX and member.get("job") == "Captain":  # pragma: no cover - a non-Captain is never offered the Captain's row
        set_feedback(state, "Only the Captain can reassign the current Captain.", "orange")
        return

    if (
        crew_index == PLAYER_CREW_INDEX
        and member.get("job") == "Captain"
        and job != "Captain"
        and not _npc_captain_exists(game)
    ):
        game.ask(
            "Confirm Reassignment",
            "You are about to give up captain access with no captain. Continue?",
            [("Yes", "assign_role", {"crew_index": crew_index, "job": job}), ("No", None, None)],
        )
        return

    assign_role(game, crew_index, job)


@choice_handler("assign_role")
def assign_role(game, crew_index, job):
    if crew_index != PLAYER_CREW_INDEX and not (0 <= crew_index < len(game.station_crew)):
        return
    member = member_for_crew_index(crew_index, game.player_data, game.station_crew)
    _grant_job(member, job)

    if crew_index == PLAYER_CREW_INDEX:
        _activate_solar_for_engineer(game, job)
        game.close_panel("job_assignment")
        return

    reassign_npc_post(member, job)
    solar_activated = _activate_solar_for_engineer(game, job)

    state = game.top_panel()
    if state is None or state["type"] != "job_assignment":  # pragma: no cover - an NPC is only assigned from the Job Assignment panel
        return
    state["result_color"] = "lightgreen"
    feedback = f"Assigned {member.get('name', 'Unknown')} as {job}."
    if solar_activated:
        feedback += " Solar arrays are now active."
    set_feedback(state, feedback, "cyan")
