from space_online.game.helper_methods.jail import (
    MAX_FINE,
    add_jail_time,
    clear_warrant,
    has_fine,
    is_held,
    is_jailed,
    set_warrant,
    jail_seconds_remaining,
    list_prisoners,
    release_member,
    resolve_fine_with_guard,
    warrant_reason_text,
)
from space_online.game.helper_methods.game_clock import format_elapsed, get_elapsed_seconds
from space_online.game.helper_methods.ui_panels import panel_action, register_panel
from space_online.game.special_rooms.shared import (
    SpecialRoomBase,
    available_npc,
    button,
    issue_gear,
    member_named,
    npc_contact_widgets,
    room_action,
)
from space_online.game.maps.donut import SECURITY_KEY
from space_online.game.objects.weapons import ARMORY_ITEM_IDS

MAX_REASON_LENGTH = 200


class Security(SpecialRoomBase):
    ROOM_TITLE = "Security"
    ROOM_HEADING = "Station Security Office"
    ROOM_DESCRIPTION = (
        "The security office is filled with monitoring equipment. Screens showing various parts of "
        "the station line the walls. A few security officers monitor the feeds, while weapon lockers "
        "are secured along one wall."
    )
    DOOR_KEY = SECURITY_KEY
    STATION_ENTRIES = ({"label": "Enter Security Station", "mode": "security_station"},)
    CONTACT_POSTS = {"Security Guard": DOOR_KEY}

    def room_options(self):
        widgets = npc_contact_widgets(
            self.game,
            "Security Guard",
            self.DOOR_KEY,
            talk_label="Talk to Security Guard",
            talk_action="talk_to_guard",
            absent_flavor="The security guard has stepped away from the office.",
        )
        return widgets + self.back_to_station_menu()

    def mode_buttons(self, mode):
        if mode != "security_station" or not self.station_allowed(mode):
            return None
        return [
            button("View Crew Manifest", "room.view_crew_manifest"),
            button("Issue Warrant/Fine", "room.show_issue_warrant"),
            button("View Jail", "room.view_jail"),
            button("Incident Log", "room.show_incident_log"),
            button("Armory", "room.open_armory"),
            button("Back to Station Menu", "room.set_mode", mode="menu"),
        ]

    @room_action
    def talk_to_guard(self):
        if available_npc(self.game, "Security Guard", self.DOOR_KEY) is None:
            return
        if has_fine(self.player_data) and not is_jailed(self.player_data):
            resolve_fine_with_guard(
                self.player_data,
                game=self.game,
                is_player=True,
                guard_name="The security guard",
                elapsed_seconds=get_elapsed_seconds(self.player_data),
            )
            return

        self.game.alert(
            "Security Guard",
            "The security agent waves you away without looking up from the cameras.",
        )

    @room_action(station="security_station")
    def view_crew_manifest(self):
        self.game.open_panel("crew_manifest")

    @room_action(station="security_station")
    def show_issue_warrant(self):
        self.game.open_panel("issue_warrant")

    @room_action(station="security_station")
    def view_jail(self):
        self.game.open_panel("jail")

    @room_action(station="security_station")
    def show_incident_log(self):
        self.game.open_panel("incident_log")

    @room_action(station="security_station")
    def open_armory(self):
        issue_gear(self.game, ARMORY_ITEM_IDS, "Armory", "the Security armory", "everything the armory issues")


def _warrant_row(member, is_player=False):
    name = member.get("name", "Unknown")
    job = member.get("job", "Unknown")
    wanted = " [WANTED]" if member.get("warrant", False) else ""
    fined = f" [FINE: {member['fine_amount']:.0f}]" if has_fine(member) else ""
    you = " (YOU)" if is_player else ""
    return f"{name} ({job}){you}{wanted}{fined}"


@register_panel("issue_warrant", "Issue Warrant/Fine")
def issue_warrant_panel(game, state):
    rows = [{"name": game.player_data["name"], "label": _warrant_row(game.player_data, is_player=True)}]
    rows += [{"name": npc["name"], "label": _warrant_row(npc)} for npc in game.station_crew]
    return {"rows": rows, "selected": state.get("selected")}


@panel_action("issue_warrant", "select")
def warrant_select(game, state, args):
    if member_named(game, args["name"]) is not None:
        state["selected"] = args["name"]


def _selected_member(game, state):
    member = member_named(game, state.get("selected"))
    if member is None:
        game.alert("No Selection", "Select a crew member first.", kind="warning")
    return member


@panel_action("issue_warrant")
def issue_warrant(game, state, args):
    member = _selected_member(game, state)
    if member is None:
        return
    if member.get("warrant", False):
        game.alert("Warrant", f"{member.get('name', 'That crew member')} already has an active warrant.")
        return
    game.open_panel("charge", crew_name=state["selected"], kind="warrant")


@panel_action("issue_warrant")
def issue_fine(game, state, args):
    if _selected_member(game, state) is not None:
        game.open_panel("charge", crew_name=state["selected"], kind="fine")


@panel_action("issue_warrant", "clear_warrant")
def warrant_clear(game, state, args):
    member = _selected_member(game, state)
    if member is None:
        return
    if not member.get("warrant", False):
        game.alert("Warrant", f"{member.get('name', 'That crew member')} does not have a warrant.")
        return
    clear_warrant(member)
    game.alert("Warrant Cleared", f"Warrant cleared for {member.get('name', 'Unknown')}.")


@register_panel("charge", "Issue Warrant")
def charge_panel(game, state):
    """The reason form for a warrant, or the reason and amount form for a fine."""
    member = member_named(game, state["crew_name"])
    if member is None:
        return None
    fine = state["kind"] == "fine"
    return {"title": "Issue Fine" if fine else "Issue Warrant", "fine": fine,
            "name": member.get("name", "Unknown"), "max_length": MAX_REASON_LENGTH}


@panel_action("charge")
def confirm(game, state, args):
    member = member_named(game, state["crew_name"])
    if member is None:
        return
    reason =str(args.get("reason", "")).strip()[:MAX_REASON_LENGTH]
    if not reason:
        game.alert("Reason Required", f"Enter a reason for the {state['kind']}.", kind="warning")
        return
    if state["kind"] == "warrant":
        if member is game.player_data:
            game.alert("Warrant Refused", "You can't issue a warrant for yourself.", kind="warning")
            return
        set_warrant(member, reason, by_player=True)
        game.close_panel("charge")
        game.alert("Warrant Issued", f"Warrant issued for {member.get('name', 'Unknown')}.\nReason: {reason}")
        return
    typed = str(args.get("amount", "")).strip()
    amount = int(typed) if typed.isdecimal() else 0
    if not 1 <= amount <= MAX_FINE:
        game.alert("Invalid Amount", f"Enter a whole number of credits from 1 to {MAX_FINE}.", kind="warning")
        return

    existing = member["fine_amount"]
    member["fine_amount"] = min(MAX_FINE, existing + amount)
    if existing > 0 and (member.get("fine_reason") or "").strip():
        member["fine_reason"] = f"{member.get('fine_reason').strip()}; {reason}"
    else:
        member["fine_reason"] = reason

    game.close_panel("charge")
    game.alert(
        "Fine Issued",
        f"Fine issued for {member.get('name', 'Unknown')}.\n"
        f"Amount: {amount:.0f} credits\nReason: {reason}\n"
        f"Total owed: {member['fine_amount']:.0f} credits",
    )


@register_panel("jail", "Jail")
def jail_panel(game, state):
    elapsed_seconds = get_elapsed_seconds(game.player_data)
    rows = []
    for member, is_player in list_prisoners(game.player_data, game.station_crew):
        sentence = ("held for Central Command" if is_held(member)
                    else f"{format_elapsed(jail_seconds_remaining(member, elapsed_seconds))} remaining")
        you = " (YOU)" if is_player else ""
        rows.append({
            "name": member["name"],
            "label": (
                f"{member.get('name', 'Unknown')} ({member.get('job', 'Unknown')}){you} - "
                f"{sentence} | Charge: {warrant_reason_text(member)}"
            ),
        })
    return {"rows": rows, "selected": state.get("selected")}


@panel_action("jail", "select")
def jail_select(game, state, args):
    state["selected"] = args["name"]


def _selected_prisoner(game, state):
    member = member_named(game, state.get("selected"))
    if member is None or not is_jailed(member):
        game.alert("No Selection", "Select a prisoner first.", kind="warning")
        return None
    if is_held(member):
        game.alert("Held", f"{member['name']} is held for Central Command. Their sentence is out of your hands.",
                   kind="warning")
        return None
    return member


@panel_action("jail")
def pardon(game, state, args):
    if is_jailed(game.player_data):
        game.alert("Pardon", "Prisoners can't sign pardons.", kind="warning")
        return
    member = _selected_prisoner(game, state)
    if member is None:
        return
    name = member["name"]
    release_member(member, game=game, show_message=False)
    game.alert("Pardon", f"{name} has been pardoned and released from jail.")


@panel_action("jail")
def add_time(game, state, args):
    member = _selected_prisoner(game, state)
    if member is None:
        return
    add_jail_time(member, get_elapsed_seconds(game.player_data))
    game.alert("Add Time", f"Added 1 minute to {member.get('name', 'the prisoner')}'s sentence.")
