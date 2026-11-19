import random

from space_online.game.character_methods.character_creation import JOBS, REQUESTABLE_JOBS, UNIQUE_JOBS
from space_online.game.helper_methods.errands import duty_by_id, leave_duties_behind, record_duty_done, with_article
from space_online.game.helper_methods.jail import set_warrant
from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.npc_movement import (
    JOB_POSTS,
    can_work,
    crew_named,
    open_post,
    post_holder,
    reassign_npc_post,
)
from space_online.game.helper_methods.ui_panels import (
    choice_handler,
    current_feedback,
    panel_action,
    register_panel,
    set_feedback,
)
from space_online.game.special_rooms.shared import (
    SpecialRoomBase,
    available_npc,
    button,
    member_named,
    npc_contact_widgets,
    room_action,
    text_line,
)
from space_online.game.helper_methods.antagonists import alert_level
from space_online.game.helper_methods.rounds import (
    call_shuttle,
    captain_caller,
    recall_shuttle,
    shuttle_call_blocked,
    shuttle_recall_blocked,
)
from space_online.game.maps.donut import BRIDGE_KEY, DEPARTURES_KEY, LOCKABLE_ROOM_KEYS, ROOMS, SECURITY_KEY
from space_online.game.special_rooms.engineering import apply_power_mode, set_system_level

# Giving away one of the UNIQUE_JOBS moves its holder to this job.
RELIEVED_JOB = "Staff Assistant"
# Taking one of these jobs away from someone asks first.
CONFIRMED_DEMOTIONS = ("Head of Personnel", "Doctor", "Engineer", "Security Guard")

# Department doors a sector lockdown can close. Departures stays open so the crew can always reach the shuttle.
LOCKDOWN_DOOR_KEYS = tuple(key for key in LOCKABLE_ROOM_KEYS
                           if key not in (BRIDGE_KEY, SECURITY_KEY, DEPARTURES_KEY))


# A Head of Personnel answers the player's own access request this many game seconds after it is put in.
ACCESS_DECISION_SECONDS_RANGE = (30, 60)
ACCESS_APPROVAL_CHANCE = 0.5
ACCESS_PENDING = "Decision pending: the Head of Personnel will answer on your PDA"


def pending_access_request(player_data):
    """The access request waiting for the HoP, or None. Its decide_at is when the NPC Head of Personnel answers the
    player's own request, and None for a crew member's request waiting on the player as Head of Personnel."""
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
    CONTACT_POSTS = {"Captain": DOOR_KEY, "Head of Personnel": DOOR_KEY}

    def room_options(self):
        return [button("Talk to Ship Leadership", "room.talk_to_leadership")] + self.back_to_station_menu()

    def mode_buttons(self, mode):
        if mode == "leadership":
            return self._leadership_buttons()
        if mode == "hop_talk" and available_npc(self.game, "Head of Personnel", self.DOOR_KEY):
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
                button("Incident Log", "room.show_incident_log"),
                button("Crew Manifest", "room.show_crew_manifest"),
                self._shuttle_button(),
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

    def _shuttle_button(self):
        """Recall while the shuttle is on its way here and can still be sent back, otherwise call it. A shuttle
        that can't be recalled leaves the reason where the button was."""
        if self.player_data["round"]["shuttle"]["state"] != "called":
            return button("Call Crew Shuttle", "room.call_shuttle")
        blocked = shuttle_recall_blocked(self.player_data)
        return text_line(blocked) if blocked else button("Recall Crew Shuttle", "room.recall_shuttle")

    @room_action(station="captain_station")
    def call_shuttle(self):
        blocked = shuttle_call_blocked(self.player_data)
        if blocked:
            self.game.alert("Crew Shuttle", blocked)
            return
        self.game.ask(
            "Call Crew Shuttle",
            "Call the crew shuttle and end the shift? It can be recalled once a shift, and only until it is "
            "halfway here.",
            [("Call It", "call_shuttle", None), ("Not Yet", None, None)],
        )

    @room_action(station="captain_station")
    def recall_shuttle(self):
        blocked = shuttle_recall_blocked(self.player_data)
        if blocked:
            self.game.alert("Crew Shuttle", blocked)
            return
        self.game.ask(
            "Recall Crew Shuttle",
            "Send the crew shuttle back? It can only be recalled once a shift.",
            [("Recall It", "recall_shuttle", None), ("Not Yet", None, None)],
        )

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
                self.DOOR_KEY,
                talk_label="Talk to Captain",
                talk_action="talk_to_captain",
                absent_flavor="The Captain is away from the bridge.",
            )
        if present["hop"]:
            widgets += npc_contact_widgets(
                self.game,
                "Head of Personnel",
                self.DOOR_KEY,
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
        if available_npc(self.game, "Captain", self.DOOR_KEY):
            self.game.alert("Captain", "The Captain is too busy for your chats.")

    @room_action
    def show_hop_talk_menu(self):
        if available_npc(self.game, "Head of Personnel", self.DOOR_KEY):
            self.game.ui["room_mode"] = "hop_talk"

    @room_action
    def show_access_control(self):
        if available_npc(self.game, "Head of Personnel", self.DOOR_KEY):
            self.game.open_panel("access_request")

    @room_action
    def resolve_hop_access_request(self):
        """Talk to HoP: they answer access requests on the PDA, not in person."""
        if available_npc(self.game, "Head of Personnel", self.DOOR_KEY) is None:
            return
        if pending_access_request(self.player_data) is None:
            self.game.alert(
                "Head of Personnel",
                "The HoP is busy. Use the Access Control terminal to put in a request.",
            )
            return
        self.game.alert("Head of Personnel", "The HoP will answer your request on your PDA.")

    @room_action(station="captain_station")
    def show_station_status(self):
        self.game.open_panel("station_status")

    @room_action(station="captain_station")
    def show_incident_log(self):
        self.game.open_panel("incident_log")

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


def _lock_down(game, door_key):
    door = game.ship_map[door_key]
    name = ROOMS[door_key].name
    if door["locked"]:
        return f"The {name} door is already locked."
    door["locked"] = True
    return f"The {name} door is now locked."


def _warrant_for(game, suspect):
    npc = crew_named(game.station_crew, suspect)
    if npc is None or npc.get("warrant") or npc.get("in_jail"):
        return f"{suspect} is no longer a suspect."
    set_warrant(npc, "Suspected smuggling")
    return f"A warrant has been issued for {suspect}."


def _command_duty(game, args):
    """The Command Request duty args names, or None."""
    duty = duty_by_id(game.player_data, args.get("duty_id"))
    return duty if duty is not None and duty["kind"] == "command" else None


@panel_action("duties", "approve_request")
def approve_request(game, state, args):
    duty = _command_duty(game, args)
    if duty is not None:
        approve_command_request(game, duty)


@panel_action("duties", "deny_request")
def deny_request(game, state, args):
    duty = _command_duty(game, args)
    if duty is not None:
        deny_command_request(game, duty)


def approve_command_request(game, duty):
    """Do what a Command Request asked for, which takes it off the board as a duty done."""
    game.player_data["duties"].remove(duty)
    request, text = duty["request"], duty["text"]
    if request == "life_support":
        set_system_level(game, "life_support", 10)
        result = "Life support is now at full power."
    elif request == "power_saving":
        changed = apply_power_mode(game, "low")
        result = "The station is now in Power Saving mode."
        if changed:
            result += f" {', '.join(changed)}."
    elif request == "lockdown":
        result = _lock_down(game, duty["door"])
    else:
        result = _warrant_for(game, duty["suspect"])
    record_duty_done(game.player_data)
    game.add_note(f"Approved: {text} {result}")
    game.alert("Command Request", f"Approved. {result}")


def deny_command_request(game, duty):
    """Turn a Command Request down, which takes it off the board as a duty done."""
    game.player_data["duties"].remove(duty)
    text = duty["text"]
    record_duty_done(game.player_data)
    game.add_note(f"Denied: {text}")
    game.alert("Command Request", f"Denied. {text}")


def _grant_job(game, member, job):
    """Give member job. A player who changes job takes an open post of it when it has more than one, and no
    post_key for a one-room job."""
    job_info = JOBS[job]
    if member is game.player_data and job != member["job"]:
        member["post_key"] = open_post(member, game.station_crew, job) if len(JOB_POSTS.get(job, ())) > 1 else None
    member["job"] = job
    member["department"] = job_info["department"]
    member["subdepartment"] = job_info["subdepartment"]
    if member is game.player_data:
        leave_duties_behind(game)


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

    if requester_name and requester_name != player_data.get("name"):
        npc = crew_named(game.station_crew, requester_name)
        player_data.pop("access_request", None)
        if npc is None:
            return False, False, "The requester is no longer on the station. Request cleared."
        if npc.get("job") == "Captain" and not _player_is_captain(player_data):
            return False, False, "Only the Captain can reassign the current Captain. Request cleared."
        _grant_job(game, npc, job)
        reassign_npc_post(game, npc, job)
        return True, _activate_solar_for_engineer(game, job), None

    if not confirmed and player_data.get("job") == "Captain" and not _npc_captain_exists(game):
        game.ask(
            "Confirm Reassignment",
            "You are about to give up captain access with no captain. Continue?",
            [("Yes", "confirm_access_request", {"job": job}), ("No", None, None)],
        )
        return False, False, None

    _grant_job(game, player_data, job)
    player_data.pop("access_request", None)
    return True, _activate_solar_for_engineer(game, job), None


def tick_access_request(game):
    """The NPC Head of Personnel answers the player's own access request once it is due and they can work: approved
    or denied at even odds, on the PDA and in the log."""
    player_data = game.player_data
    request = pending_access_request(player_data)
    if request is None or request["decide_at"] is None or get_elapsed_seconds(player_data) < request["decide_at"]:
        return
    hop = post_holder(game.station_crew, "Head of Personnel")
    if hop is None or not can_work(hop):
        return
    job = request["requested_job"]
    request["decide_at"] = None
    if random.random() < ACCESS_APPROVAL_CHANCE:
        ok, solar_activated, _ = apply_access_request_job(game, job)
        if ok:
            _answer_access_request(game, f"The HoP approved your request. You are now {job}."
                                         f"{_approved_suffix(solar_activated)}")
    else:
        player_data.pop("access_request", None)
        _answer_access_request(game, f"The HoP denied your request for {job}.")


def _answer_access_request(game, message):
    game.alert("Head of Personnel", message)
    game.page("Head of Personnel", message)


@choice_handler("confirm_access_request")
def confirm_access_request(game, job):
    request = pending_access_request(game.player_data)
    if request is None or (request["requested_job"], request["requester_name"]) != (job, game.player_data["name"]):
        return
    _, solar_activated, _ = apply_access_request_job(game, job, confirmed=True)
    game.close_panel("hop_console")
    game.alert("Access Control", f"You are now {job}.{_approved_suffix(solar_activated)}")


@choice_handler("call_shuttle")
def call_shuttle_confirmed(game):
    """The Captain's own call: urgent when the station is already at Red alert."""
    call_shuttle(game, "the Captain has ended the shift", urgent=alert_level(game.player_data)[0] == "Red",
                 caller=captain_caller(game.player_data["name"]))


@choice_handler("recall_shuttle")
def recall_shuttle_confirmed(game):
    if not recall_shuttle(game):
        game.alert("Crew Shuttle", shuttle_recall_blocked(game.player_data))


@register_panel("access_request", "Access Control")
def access_request_panel(game, state):
    job = state.get("job")
    player_name = game.player_data.get("name", "Unknown")
    request = pending_access_request(game.player_data)
    if request is not None and request["decide_at"] is not None:
        result = {"text": ACCESS_PENDING, "color": "cyan"}
    elif job:
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
    game.player_data["access_request"] = {
        "requested_job": job,
        "requester_name": game.player_data.get("name", "Unknown"),
        "decide_at": get_elapsed_seconds(game.player_data) + random.randint(*ACCESS_DECISION_SECONDS_RANGE),
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
    record_duty_done(game.player_data)
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
    record_duty_done(game.player_data)
    game.close_panel("hop_console")
    game.alert("Access Control", f"Denied request for {req['requested_job']}.")


def _player_is_captain(player_data):
    return player_data.get("subdepartment") == "Captain"


def _assignable_rows(game):
    """(name, label) rows; Captain NPCs (and the player) only for a Captain."""
    player = game.player_data
    player_is_captain = _player_is_captain(player)
    rows = []
    if player_is_captain:
        rows.append((player["name"], f"{player['name']} ({player['job']}) (YOU)"))
    for npc in game.station_crew:
        if not player_is_captain and npc["job"] == "Captain":
            continue
        rows.append((npc["name"], f"{npc['name']} ({npc['job']})"))
    return rows


def _assignable_jobs(player_data):
    return [job for job in JOBS if job != "Captain" or _player_is_captain(player_data)]


@register_panel("job_assignment", "Job Assignment")
def job_assignment_panel(game, state):
    rows = _assignable_rows(game)
    crew_name = state.get("crew_name")
    if crew_name not in {name for name, _ in rows}:
        crew_name = None
    job = state.get("job")

    if crew_name is not None:
        if job:
            result = {"text": f"{crew_name} → {job}", "color": state.get("result_color", "white")}
        else:
            result = {"text": f"{crew_name} - select a job.", "color": "cyan"}
    elif job:
        result = {"text": f"Select an NPC for {job}.", "color": "cyan"}
    else:
        result = {"text": "Select an NPC and a job to confirm.", "color": "cyan"}

    return {
        "rows": [{"name": name, "label": label} for name, label in rows],
        "jobs": _assignable_jobs(game.player_data),
        "crew_name": crew_name,
        "job": job,
        "result": result,
        "feedback": current_feedback(state),
    }


@panel_action("job_assignment")
def select_member(game, state, args):
    state["crew_name"] = args["name"]
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
    crew_name = state.get("crew_name")
    job = state.get("job")
    if crew_name is None or not job:
        set_feedback(state, "Select both an NPC and a job first.", "orange")
        return
    if crew_name not in {name for name, _ in _assignable_rows(game)}:
        set_feedback(state, "Invalid NPC selection.", "red")
        return
    if job not in JOBS:
        set_feedback(state, "Invalid job selection.", "red")
        return

    if job == "Captain" and not _player_is_captain(game.player_data):
        set_feedback(state, "Only the Captain can assign the Captain role.", "orange")
        return

    member = member_named(game, crew_name)
    question = _assignment_question(game, member, job)
    if question:
        game.ask("Confirm Reassignment", question,
                 [("Yes", "assign_role", {"crew_name": crew_name, "job": job}), ("No", None, None)])
        return

    assign_role(game, crew_name, job)


def _holders(game, job, besides):
    """Everyone aboard, the player included, who holds job, other than besides."""
    return [member for member in (game.player_data, *game.station_crew)
            if member["job"] == job and member is not besides]


def _job_title(job):
    """'the Captain', 'an Engineer': job as it reads after "is now"."""
    return f"the {job}" if job in UNIQUE_JOBS else with_article(job)


def _assignment_question(game, member, job):
    """What to confirm before giving member job, or None when it can go ahead."""
    name, old_job = member["name"], member["job"]
    if job == old_job:
        return None
    lines = []
    if member is game.player_data and old_job == "Captain":
        lines.append("You are about to give up the Captain's post.")
    elif old_job in CONFIRMED_DEMOTIONS:
        lines.append(f"{name} will no longer be the {old_job}.")
    if job in UNIQUE_JOBS:
        lines += [f"{holder['name']} is the {job} and will become {_job_title(RELIEVED_JOB)}."
                  for holder in _holders(game, job, member)]
    return " ".join(lines + ["Continue?"]) if lines else None


def _move_to_job(game, member, job):
    _grant_job(game, member, job)
    if member is not game.player_data:
        reassign_npc_post(game, member, job)


@choice_handler("assign_role")
def assign_role(game, crew_name, job):
    """Give crew_name job. A Captain or Head of Personnel already in post becomes a Staff Assistant."""
    member = member_named(game, crew_name)
    if member is None:
        return
    relieved = _holders(game, job, member) if job in UNIQUE_JOBS else []
    _move_to_job(game, member, job)
    for holder in relieved:
        _move_to_job(game, holder, RELIEVED_JOB)
    solar_activated = _activate_solar_for_engineer(game, job)
    game.alert("Job Assignment", " ".join([f"{member['name']} is now {_job_title(job)}."]
                                          + [f"{holder['name']} is now {_job_title(RELIEVED_JOB)}."
                                             for holder in relieved]))

    if member is game.player_data or any(holder is game.player_data for holder in relieved):
        game.close_panel("job_assignment")
        return

    state = game.top_panel()
    state["result_color"] = "lightgreen"
    feedback = f"Assigned {member['name']} as {job}."
    if member.get("in_jail"):
        feedback += " They take up the post when released."
    if solar_activated:
        feedback += " Solar arrays are now active."
    set_feedback(state, feedback, "cyan")
