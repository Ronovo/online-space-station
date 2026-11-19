"""The Research Lab: the artifact bench in the Artifact Section and the teleporter in the Teleporter Room, two
stations behind one door.

player_data["research"] (see artifacts.new_research) holds the bench, the artifacts waiting to be worked out, and
tele, the teleporter's calibration for this shift, which nobody is told.

The teleporter's console doesn't take station coordinates. On each axis the number to enter for a place is
    console = m * station + c
with a multiplier m and an offset c picked afresh every shift. Sending a test beacon reports the station
coordinates it came out at, so two sends per axis are enough to work both numbers out.
"""

import random

from space_online.game.helper_methods.artifacts import (
    ARTIFACT_KINDS,
    DEVICES,
    MAX_STRENGTH,
    OVERLOAD_DAMAGE,
    artifact_of,
    is_unknown_artifact,
    mark_analysed,
    run_test,
)
from space_online.game.helper_methods.errands import duty_by_id, finish_duty, open_duties
from space_online.game.helper_methods.health_bands import LIMBS, change_limb
from space_online.game.helper_methods.ui_panels import panel_action, register_panel
from space_online.game.maps import donut
from space_online.game.objects.items import (
    add_to_inventory,
    format_inventory_label,
    remove_one_from_inventory,
    stack_into,
)
from space_online.game.special_rooms.shared import (
    SpecialRoomBase,
    available_npc,
    button,
    npc_contact_widgets,
    room_action,
    text_line,
)

MAX_BENCH = 3
FINDERS_FEE = 120
ANALYSIS_REWARD = 300
MAX_TELE_LOG = 6


def station_coordinates(tele, console_x, console_y):
    """Where console numbers come out on the station: (x, y), which need not be whole numbers or on the station."""
    return tuple((value - tele[axis]["c"]) / tele[axis]["m"] for axis, value in (("x", console_x), ("y", console_y)))


def _tile_key(point):
    """The map key of a point the teleporter came out at, or None when there is no floor there."""
    x, y = point
    if x != int(x) or y != int(y):
        return None
    key = donut.tile_key(int(x), int(y))
    return key if key in donut.SHIP_MAP else None


class Research(SpecialRoomBase):
    ROOM_TITLE = "Research Lab"
    ROOM_HEADING = "Station Research Lab"
    ROOM_DESCRIPTION = (
        "The research lab hums behind thick glass. A row of test rigs faces a scarred steel bench, and a "
        "teleporter pad sits in a ring of scorch marks at the back."
    )
    DOOR_KEY = donut.RESEARCH_KEY
    STATION_ENTRIES = (
        {"label": "Enter the Artifact Section", "mode": "artifact_section"},
        {"label": "Enter the Teleporter Room", "mode": "teleporter_room"},
    )
    CONTACT_POSTS = {"Scientist": DOOR_KEY}

    def room_options(self):
        widgets = []
        if any(is_unknown_artifact(item) for item in self.player_data["inventory"]):
            widgets.append(button("Leave an Artifact on the Bench", "room.leave_artifact"))
        widgets += npc_contact_widgets(
            self.game,
            "Scientist",
            self.DOOR_KEY,
            talk_label="Talk to Scientist",
            talk_action="talk_to_scientist",
            absent_flavor="The scientist is away from the lab.",
        )
        return widgets + self.back_to_station_menu()

    def mode_buttons(self, mode):
        if not self.station_allowed(mode):
            return None
        if mode == "artifact_section":
            title = "Artifact Section"
            station = button(f"Artifact Bench ({len(self.player_data['research']['bench'])})", "room.show_bench")
        else:
            title, station = "Teleporter Room", button("Teleporter", "room.show_teleporter")
        return [
            text_line(title, style="title"),
            station,
            button("Back to Station Menu", "room.set_mode", mode="menu"),
        ]

    @room_action
    def talk_to_scientist(self):
        if available_npc(self.game, "Scientist", self.DOOR_KEY):
            self.game.alert("Scientist", "The scientist waves you back from the bench. 'Don't touch that one. "
                                         "Or that one.'")

    @room_action
    def leave_artifact(self):
        """Put the first unidentified artifact the player carries on the bench. Central Command pays a finder's fee
        to anyone who isn't a Scientist, whose pay comes from working it out."""
        player_data = self.player_data
        bench = player_data["research"]["bench"]
        index = next((i for i, item in enumerate(player_data["inventory"]) if is_unknown_artifact(item)), None)
        if index is None:
            return
        if len(bench) >= MAX_BENCH:
            self.game.alert("Research Lab", "The bench is full. The artifacts on it have to be worked out first.")
            return
        bench.append(player_data["inventory"].pop(index))
        if player_data["job"] == "Scientist":
            self.game.alert("Research Lab", "You set the artifact down on the bench.")
            return
        player_data["credits"] += FINDERS_FEE
        self.add_note(f"Left an artifact at the Research Lab for a {FINDERS_FEE}-credit finder's fee.")
        self.game.alert("Research Lab", f"You set the artifact down on the bench. Central Command pays you a "
                                        f"finder's fee of {FINDERS_FEE} credits.")

    @room_action(station="artifact_section")
    def show_bench(self):
        self.game.open_panel("artifact_bench")

    @room_action(station="teleporter_room")
    def show_teleporter(self):
        self.game.open_panel("teleporter")


def _bench_artifact(game, state):
    bench = game.player_data["research"]["bench"]
    selected = state.get("selected")
    return bench[selected] if selected is not None and 0 <= selected < len(bench) else None


@register_panel("artifact_bench", "Artifact Bench")
def artifact_bench_panel(game, state):
    bench = game.player_data["research"]["bench"]
    artifact = _bench_artifact(game, state)
    return {
        "artifacts": [{"index": index,
                       "label": f"Artifact {index + 1}" + (" (active)" if artifact_of(item)["activated"] else "")}
                      for index, item in enumerate(bench)],
        "selected": state.get("selected") if artifact else None,
        "devices": list(DEVICES.items()),
        "device": state.get("device", next(iter(DEVICES))),
        "strength": state.get("strength", 1),
        "max_strength": MAX_STRENGTH,
        "kinds": [(kind, details["name"]) for kind, details in ARTIFACT_KINDS.items()],
        "result": state.get("result", "Pick an artifact, a device and a strength, and run a test."),
        "filed": state.get("filed", {}),
    }


@panel_action("artifact_bench")
def select_artifact(game, state, args):
    state["selected"] = int(args["index"])
    state.pop("result", None)


@panel_action("artifact_bench")
def set_device(game, state, args):
    if args["name"] in DEVICES:
        state["device"] = args["name"]


@panel_action("artifact_bench")
def set_strength(game, state, args):
    state["strength"] = max(1, min(MAX_STRENGTH, int(args["value"])))


@panel_action("artifact_bench")
def test(game, state, args):
    artifact = _bench_artifact(game, state)
    if artifact is None:
        state["result"] = "Pick an artifact from the bench first."
        return
    device = state.get("device", next(iter(DEVICES)))
    strength = state.get("strength", 1)
    outcome, seen = run_test(artifact, device, strength)
    state["result"] = f"{DEVICES[device]} at {strength}: {seen}"
    if outcome == "overload":
        limb = random.choice(LIMBS)
        change_limb(game.player_data, limb, -OVERLOAD_DAMAGE)
        game.alert("Artifact Bench", "The artifact's pulse throws you against the wall.", kind="warning")


@panel_action("artifact_bench")
def file_analysis(game, state, args):
    """File what the artifact is and what sets it off. A correct form pays and hands the artifact over to use."""
    artifact = _bench_artifact(game, state)
    if artifact is None:
        state["result"] = "Pick an artifact from the bench first."
        return
    details = artifact_of(artifact)
    wrong = [label for label, guess, answer in (("what it is", args.get("kind"), details["kind"]),
                                                ("what sets it off", args.get("device"), details["device"]))
             if guess != answer]
    if wrong:
        state["result"] = f"Central Command sends the form back. Wrong: {' and '.join(wrong)}."
        state["filed"] = {"kind": args.get("kind"), "device": args.get("device")}
        return
    player_data = game.player_data
    player_data["research"]["bench"].remove(artifact)
    mark_analysed(artifact)
    add_to_inventory(player_data, artifact)
    state.pop("selected", None)
    state["result"] = f"Analysis accepted: a {artifact['name']}. It is yours to use or to sell at the Cargo Bay."
    note = f"Analysed a {artifact['name']} for {ANALYSIS_REWARD} credits."
    message = f"Central Command accepts your analysis of the {artifact['name']} and pays you {ANALYSIS_REWARD} credits."
    own_duty = details.get("duty")
    duty = duty_by_id(player_data, own_duty) if own_duty else next(iter(open_duties(player_data, ("analyse",))), None)
    if duty is not None:
        finish_duty(game, duty, note, message, ANALYSIS_REWARD)
        return
    reward = ANALYSIS_REWARD
    if own_duty:
        reward = ANALYSIS_REWARD // 2
        note = f"Analysed a {artifact['name']} late, for {reward} credits."
        message = (f"Central Command accepts your late analysis of the {artifact['name']} and pays you {reward} "
                   "credits, half the usual, as its duty was missed.")
    player_data["credits"] += reward
    game.add_note(note)
    game.alert("Artifact Bench", message)


def _log(state, line):
    state["log"] = ([line] + state.get("log", []))[:MAX_TELE_LOG]


def _console_numbers(state, args):
    """The whole numbers typed into the console's X and Y, or None (with a line in the log) when they aren't."""
    try:
        return int(str(args.get("x", "")).strip()), int(str(args.get("y", "")).strip())
    except ValueError:
        _log(state, "The console wants a whole number for X and for Y.")
        return None


def _target(game, state, args):
    """(console numbers, map key of the tile they come out on) for a teleporter action, or None when the numbers
    are no good or there is no floor there."""
    numbers = _console_numbers(state, args)
    if numbers is None:
        return None
    key = _tile_key(station_coordinates(game.player_data["research"]["tele"], *numbers))
    if key is None:
        _log(state, f"X {numbers[0]}, Y {numbers[1]}: the pad stays dark. There is no floor at those coordinates.")
        return None
    return numbers, key


@register_panel("teleporter", "Teleporter")
def teleporter_panel(game, state):
    return {
        "x": state.get("x", ""),
        "y": state.get("y", ""),
        "log": state.get("log", []),
        "rooms": [{"name": room.name, **donut.location_from_key(key)} for key, room in donut.ROOMS.items()],
        "pad_items": [{"index": index, "label": format_inventory_label(item)}
                      for index, item in enumerate(game.player_data["inventory"])],
    }


def _remember(state, args):
    state["x"], state["y"] = str(args.get("x", ""))[:8], str(args.get("y", ""))[:8]


@panel_action("teleporter")
def scan(game, state, args):
    _remember(state, args)
    target = _target(game, state, args)
    if target is not None:
        (x, y), key = target
        _log(state, f"X {x}, Y {y}: the scanner reads solid floor.")


@panel_action("teleporter")
def beacon(game, state, args):
    """Send the test beacon, which reports the station coordinates it came out at and is pulled straight back."""
    _remember(state, args)
    numbers = _console_numbers(state, args)
    if numbers is None:
        return
    north, east = station_coordinates(game.player_data["research"]["tele"], *numbers)
    _log(state, f"X {numbers[0]}, Y {numbers[1]}: the beacon reports {north:g} North, {east:g} East.")


@panel_action("teleporter")
def send_me(game, state, args):
    _remember(state, args)
    target = _target(game, state, args)
    if target is None:
        return
    _, key = target
    name = game.ship_map[key]["name"]
    game.player_data["location"] = donut.location_from_key(key)
    game.reset_view()
    game.add_note(f"Teleported to the {name}.")
    game.alert("Teleporter", f"The lab folds away, and you are standing in the {name}.")


@panel_action("teleporter")
def send_item(game, state, args):
    _remember(state, args)
    target = _target(game, state, args)
    if target is None:
        return
    (x, y), key = target
    sent = remove_one_from_inventory(game.player_data, int(args["item"]))
    if sent is None:
        _log(state, "Put something on the pad first.")
        return
    stack_into(game.player_data["floor"].setdefault(key, []), sent)
    game.add_note(f"Teleported a {sent['name']} to the {game.ship_map[key]['name']}.")
    _log(state, f"X {x}, Y {y}: the {sent['name']} vanishes from the pad.")


@panel_action("teleporter")
def receive(game, state, args):
    """Bring back everything lying on the floor at the target."""
    _remember(state, args)
    target = _target(game, state, args)
    if target is None:
        return
    (x, y), key = target
    found = game.player_data["floor"].pop(key, [])
    if not found:
        _log(state, f"X {x}, Y {y}: nothing comes back. There is nothing lying there.")
        return
    for item in found:
        add_to_inventory(game.player_data, item)
    _log(state, f"X {x}, Y {y}: {', '.join(format_inventory_label(item) for item in found)} appears on the pad.")
