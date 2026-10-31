from space_online.game.helper_methods.jail import (
    add_jail_time,
    has_fine,
    is_jailed,
    jail_seconds_remaining,
    list_prisoners,
    release_member,
    resolve_fine_with_guard,
    warrant_reason_text,
)
from space_online.game.helper_methods.game_clock import format_elapsed, get_elapsed_seconds
from space_online.game.helper_methods.ui_panels import panel_action, register_panel
from space_online.game.special_rooms.shared import (
    PLAYER_CREW_INDEX,
    SpecialRoomBase,
    available_npc,
    button,
    member_for_crew_index,
    npc_contact_widgets,
    room_action,
)
from space_online.game.maps.donut import SECURITY_KEY

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
    CONTACT_JOBS = ("Security Guard",)

    def room_options(self):
        widgets = npc_contact_widgets(
            self.game,
            "Security Guard",
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
            button("Back to Station Menu", "room.set_mode", mode="menu"),
        ]

    @room_action
    def talk_to_guard(self):
        if available_npc(self.game, "Security Guard") is None:
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


def _member(game, crew_index):
    """Crew member for a client-supplied index (player or NPC), or None."""
    if crew_index is None:
        return None
    if crew_index != PLAYER_CREW_INDEX and not (0 <= crew_index < len(game.station_crew)):
        return None
    return member_for_crew_index(crew_index, game.player_data, game.station_crew)


def _warrant_row(member, is_player=False):
    name = member.get("name", "Unknown")
    job = member.get("job", "Unknown")
    wanted = " [WANTED]" if member.get("warrant", False) else ""
    fined = f" [FINE: {member['fine_amount']:.0f}]" if has_fine(member) else ""
    you = " (YOU)" if is_player else ""
    return f"{name} ({job}){you}{wanted}{fined}"


@register_panel("issue_warrant", "Issue Warrant/Fine")
def issue_warrant_panel(game, state):
    rows = [{"index": PLAYER_CREW_INDEX, "label": _warrant_row(game.player_data, is_player=True)}]
    rows += [{"index": i, "label": _warrant_row(npc)} for i, npc in enumerate(game.station_crew)]
    return {"rows": rows, "selected": state.get("selected")}


@panel_action("issue_warrant", "select")
def warrant_select(game, state, args):
    crew_index = int(args["index"])
    if _member(game, crew_index) is not None:
        state["selected"] = crew_index


def _selected_member(game, state):
    member = _member(game, state.get("selected"))
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
    game.open_panel("charge", crew_index=state["selected"], kind="warrant")


@panel_action("issue_warrant")
def issue_fine(game, state, args):
    if _selected_member(game, state) is not None:
        game.open_panel("charge", crew_index=state["selected"], kind="fine")


@panel_action("issue_warrant")
def clear_warrant(game, state, args):
    member = _selected_member(game, state)
    if member is None:
        return
    if not member.get("warrant", False):
        game.alert("Warrant", f"{member.get('name', 'That crew member')} does not have a warrant.")
        return
    member["warrant"] = False
    member["warrant_reason"] = ""
    game.alert("Warrant Cleared", f"Warrant cleared for {member.get('name', 'Unknown')}.")


@register_panel("charge", "Issue Warrant")
def charge_panel(game, state):
    """The reason form for a warrant, or the reason and amount form for a fine."""
    member = _member(game, state["crew_index"])
    if member is None:
        return None
    fine = state["kind"] == "fine"
    return {"title": "Issue Fine" if fine else "Issue Warrant", "fine": fine,
            "name": member.get("name", "Unknown"), "max_length": MAX_REASON_LENGTH}


@panel_action("charge")
def confirm(game, state, args):
    member = _member(game, state["crew_index"])
    if member is None:
        return
    reason = str(args.get("reason", "")).strip()[:MAX_REASON_LENGTH]
    if not reason:
        game.alert("Reason Required", f"Enter a reason for the {state['kind']}.", kind="warning")
        return
    if state["kind"] == "warrant":
        member["warrant"] = True
        member["warrant_reason"] = reason
        game.close_panel("charge")
        game.alert("Warrant Issued", f"Warrant issued for {member.get('name', 'Unknown')}.\nReason: {reason}")
        return
    try:
        amount = float(str(args.get("amount", "")).strip())
    except ValueError:
        game.alert("Invalid Amount", "Enter a valid credit amount.", kind="warning")
        return
    if not amount > 0 or amount == float("inf"):
        game.alert("Invalid Amount", "Fine amount must be greater than zero.", kind="warning")
        return

    existing = member["fine_amount"]
    member["fine_amount"] = existing + amount
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
        remaining = format_elapsed(jail_seconds_remaining(member, elapsed_seconds))
        you = " (YOU)" if is_player else ""
        rows.append({
            "index": PLAYER_CREW_INDEX if is_player else game.station_crew.index(member),
            "label": (
                f"{member.get('name', 'Unknown')} ({member.get('job', 'Unknown')}){you} - "
                f"{remaining} remaining | Charge: {warrant_reason_text(member)}"
            ),
        })
    return {"rows": rows, "selected": state.get("selected")}


@panel_action("jail", "select")
def jail_select(game, state, args):
    state["selected"] = int(args["index"])


def _selected_prisoner(game, state):
    member = _member(game, state.get("selected"))
    if member is None or not is_jailed(member):
        game.alert("No Selection", "Select a prisoner first.", kind="warning")
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
    is_player = state["selected"] == PLAYER_CREW_INDEX
    name = member.get("name", "Unknown")
    release_member(member, is_player=is_player, game=game, show_message=False)
    game.alert("Pardon", f"{name} has been pardoned and released from jail.")
    if is_player:  # pragma: no cover - a jailed player can't pardon, so never pardons themself
        game.reset_view()


@panel_action("jail")
def add_time(game, state, args):
    member = _selected_prisoner(game, state)
    if member is None:
        return
    if not add_jail_time(member, get_elapsed_seconds(game.player_data)):  # pragma: no cover - only prisoners get this far, and a sentence can always grow
        game.alert("Add Time", "Could not add time to that sentence.")
        return
    game.alert("Add Time", f"Added 1 minute to {member.get('name', 'the prisoner')}'s sentence.")
