"""The crew shuttle from the inside: five sections the player walks between while aboard.

player_data["round"]["section"] is the SECTIONS key the player is in, and round["strapped"] whether they are
strapped into a seat in the Common Area. The Departures room hands its screen and its actions to ShuttleCabin while
the player is aboard. The crew aboard all sit in the Common Area's seats, apart from the prisoners in the cell.
"""

import random
from typing import Callable, NamedTuple

from space_online.game.helper_methods.antagonists import hidden_hosts_aboard
from space_online.game.helper_methods.door_control import can_control_door
from space_online.game.helper_methods.health_bands import is_incapacitated
from space_online.game.helper_methods.jail import (
    can_player_arrest,
    in_shuttle_cell,
    is_jailed,
    list_prisoners,
    set_warrant,
    shuttle_cell_location,
    warrant_reason_text,
)
from space_online.game.helper_methods.mixing import (
    MixingStation,
    RecipeBook,
    register_mixing_station,
    register_recipe_book,
)
from space_online.game.helper_methods.npc_movement import crew_aboard, crew_named, hurry_to_shuttle
from space_online.game.helper_methods.rounds import BED_SECTION, BOARDING_SECTION, CELL_SECTION, shuttle_status
from space_online.game.helper_methods.shuttle_talk import seated_crew, talk_to_crew
from space_online.game.helper_methods.ui_panels import panel_action, register_panel
from space_online.game.maps.donut import BRIDGE_KEY, DEPARTURES_KEY
from space_online.game.objects.drinks import COFFEE_MACHINE_CAPACITY, COFFEE_RECIPES, brew_coffee, coffee_shelf
from space_online.game.special_rooms.quarters import toggle_bed
from space_online.game.special_rooms.shared import button, no_signal, room_action, text_line

COMMON = BOARDING_SECTION
COMMAND = "command"
MEDICAL = BED_SECTION
SECURITY = CELL_SECTION
BREAK_ROOM = "break_room"

SHUTTLE_WARRANT_REASON = "Suspicious behaviour aboard the shuttle"
NOT_NOTICED = "hasn't noticed the call"
# Watching the passengers: how often a look at a hidden threat's host gives it away, and how often an innocent
# crew member does something that looks just as odd.
TELL_CHANCE = 0.4
ODD_LINE_CHANCE = 0.25
TELLS = (
    "{name} keeps one hand inside their jacket the whole time.",
    "{name} hasn't blinked in a long while.",
    "{name} watches the airlock, not the window, as if counting the seconds.",
    "{name} flinches when someone brushes past, then smiles far too widely.",
)
ODD_LINES = (
    "{name} keeps checking their pockets.",
    "{name} mutters to themself and won't meet anyone's eye.",
    "{name} drums their fingers on the armrest, faster and faster.",
)
INNOCENT_LINES = (
    "{name} dozes with their head against the window.",
    "{name} reads something on their PDA and laughs quietly.",
    "{name} complains to the crew member beside them about the seats.",
    "{name} tightens their harness and closes their eyes.",
)


def can_enter_command(player_data):
    """Security Guards and the Captain (who work the Security door) and the Head of Personnel (the Bridge door)."""
    return can_player_arrest(player_data) or can_control_door(player_data, BRIDGE_KEY)


def _everyone(player_data):
    return True


def _docked(room):
    return room.round["shuttle"]["state"] == "docked"


def _common_description(room):
    seated = len(seated_crew(room.game))
    if not seated:
        crew = "The seats are empty."
    else:
        crew = f"{seated} of the crew {'is' if seated == 1 else 'are'} strapped in."
    return ("Rows of harnessed seats run down the cabin from the airlock. Doors lead forward to Command and aft to "
            f"the rest of the shuttle. {crew}")


def _common_widgets(room):
    return [button("Unstrap" if room.round["strapped"] else "Strap In", "room.strap"),
            button("Talk to the Crew", "room.talk_to_crew")]


def _command_widgets(room):
    widgets = [button("Head Count", "room.head_count")]
    if not can_player_arrest(room.player_data):
        return widgets
    if room.game.ui["room_mode"] == "warrant":
        suspects = [npc for npc in seated_crew(room.game) if not npc["warrant"]]
        widgets += [button(f"{npc['name']} ({npc['job']})", "room.issue_warrant", crew_name=npc["name"])
                    for npc in suspects] or [text_line("Nobody in the seats to put a warrant on.", style="italic")]
        return widgets + [button("Cancel", "room.choose_suspect")]
    if _docked(room):
        widgets.append(button("Watch the Passengers", "room.watch_passengers"))
    return widgets + [button("Issue a Warrant", "room.choose_suspect")]


def _medical_widgets(room):
    return [button("Get Up" if room.player_data["resting"] else "Lie Down in the Bed", "room.lie_down")]


def cell_prisoners(game):
    """The prisoners locked in the shuttle's cell, as (member, is_player) pairs."""
    return [(member, is_player) for member, is_player in list_prisoners(game.player_data, game.station_crew)
            if in_shuttle_cell(member)]


def _security_widgets(room):
    widgets = [text_line("The Cell", style="title")]
    held = [text_line(f"{member['name']} ({member['job']}): {warrant_reason_text(member)}")
            for member, is_player in cell_prisoners(room.game) if not is_player]
    widgets += held or [text_line("The cell is empty.", style="italic")]
    if not is_jailed(room.player_data):
        widgets.append(button("Scan the Passengers", "room.scan_passengers"))
    return widgets


def _break_room_widgets(room):
    return [button("Coffee Machine", "room.coffee_machine")]


class Section(NamedTuple):
    name: str
    describe: Callable  # room -> the section's description
    allowed: Callable  # player_data -> whether the player may go in
    widgets: Callable  # room -> the section's own menu widgets
    actions: tuple  # the room actions it takes, besides go_to


SECTIONS = {
    COMMON: Section("Common Area", _common_description, _everyone, _common_widgets,
                    ("strap", "talk_to_crew", "step_off")),
    COMMAND: Section("Command", lambda room: (
        "The pilot's console glows at the front of the shuttle. A screen beside it lists the crew and where each "
        "of them is."), can_enter_command, _command_widgets,
        ("head_count", "watch_passengers", "choose_suspect", "issue_warrant")),
    MEDICAL: Section("Medical Bay", lambda room: "A narrow medical bay with a single bed and a cabinet of bandages.",
                     _everyone, _medical_widgets, ("lie_down",)),
    SECURITY: Section("Security", lambda room: "A locked section with a barred holding cell along one wall.",
                      can_player_arrest, _security_widgets, ("scan_passengers",)),
    BREAK_ROOM: Section("Break Room", lambda room: "A cramped break room with a counter, a few stools and a "
                                                   "coffee machine.", _everyone, _break_room_widgets,
                        ("coffee_machine",)),
}
CABIN_ACTIONS = frozenset({"go_to"}).union(*(section.actions for section in SECTIONS.values()))


class ShuttleCabin:
    """The Departures room's screen and actions while the player is aboard the shuttle."""

    def section(self):
        return SECTIONS[self.round["section"]]

    def view(self):
        screen = super().view()
        if self.round["aboard"]:
            section = self.section()
            screen.update(title="Crew Shuttle", heading=f"Crew Shuttle {section.name}",
                          description=section.describe(self))
        return screen

    def menu_buttons(self):
        if not self.round["aboard"]:
            return super().menu_buttons()
        return ([text_line(shuttle_status(self.player_data), style="italic")]
                + self.section().widgets(self) + self._way_out())

    def _held(self):
        """What keeps the player where they are, or None when they are free to move about."""
        if is_jailed(self.player_data):
            return "You are locked in the cell."
        if self.round["strapped"]:
            return "Unstrap to get up."
        if self.player_data["resting"]:
            return "Get up to leave the bed."
        return None

    def _way_out(self):
        held = self._held()
        if held:
            return [text_line(held, style="italic")]
        if self.round["section"] != COMMON:
            return [button("Back to the Common Area", "room.go_to", section=COMMON)]
        widgets = [button(f"Go to {section.name}", "room.go_to", section=key)
                   for key, section in SECTIONS.items() if key != COMMON and section.allowed(self.player_data)]
        if _docked(self):
            widgets.append(button("Step Off the Shuttle", "room.step_off"))
        return widgets

    def perform(self, name, args):
        """Aboard, only the current section's actions and moving between sections are open. Exit Room heads back
        to the Common Area, and from there the shuttle has to be stepped off."""
        if not self.round["aboard"]:
            if name not in CABIN_ACTIONS:
                super().perform(name, args)
        elif name == "exit":
            if self.round["section"] == COMMON:
                self.game.alert("Crew Shuttle", "You are aboard the shuttle. Step off it first.")
            else:
                self.go_to(COMMON)
        elif name == "go_to" or name in self.section().actions:
            super().perform(name, args)

    @room_action
    def go_to(self, section):
        """Walk to another section: from the Common Area to any the player may enter, or back to it."""
        here = self.round["section"]
        target = SECTIONS.get(section)
        if target is None or section == here or COMMON not in (here, section) or not target.allowed(self.player_data):
            return
        held = self._held()
        if held:
            self.game.alert("Crew Shuttle", held)
            return
        self.round["section"] = section
        self.game.reset_view()

    @room_action
    def strap(self):
        strapped = not self.round["strapped"]
        self.round["strapped"] = strapped
        self.game.alert("Crew Shuttle", "You strap into a seat." if strapped else "You unstrap from your seat.")

    @room_action
    def talk_to_crew(self):
        talk_to_crew(self.game)

    @room_action
    def head_count(self):
        self.game.open_panel("shuttle_head_count")

    @room_action
    def watch_passengers(self):
        """Look over the crew in the seats for a while. A hidden threat aboard sometimes gives itself away."""
        if not can_player_arrest(self.player_data) or not _docked(self):
            return
        seated = seated_crew(self.game)
        if not seated:
            self.game.alert("Watch the Passengers", "The seats are empty.")
            return
        hosts = hidden_hosts_aboard(self.game)
        if hosts and random.random() < TELL_CHANCE:
            line = random.choice(TELLS).format(name=random.choice(hosts)["name"])
        else:
            lines = ODD_LINES if random.random() < ODD_LINE_CHANCE else INNOCENT_LINES
            others = [npc for npc in seated if npc not in hosts] or seated
            line = random.choice(lines).format(name=random.choice(others)["name"])
        self.game.alert("Watch the Passengers", line)

    @room_action
    def choose_suspect(self):
        """Open the list of crew to put a warrant on, or close it again."""
        if can_player_arrest(self.player_data):
            self.game.ui["room_mode"] = "menu" if self.game.ui["room_mode"] == "warrant" else "warrant"

    @room_action
    def issue_warrant(self, crew_name):
        npc = crew_named(seated_crew(self.game), crew_name)
        if not can_player_arrest(self.player_data) or npc is None or npc["warrant"]:
            return
        set_warrant(npc, SHUTTLE_WARRANT_REASON, by_player=True)
        self.game.ui["room_mode"] = "menu"
        self.game.alert("Warrant Issued", f"Warrant issued for {npc['name']}.\nReason: {SHUTTLE_WARRANT_REASON}")

    @room_action
    def lie_down(self):
        toggle_bed(self.game)

    @room_action
    def scan_passengers(self):
        """Collect the fines of the crew aboard and offer to arrest the wanted into the shuttle's cell."""
        if is_jailed(self.player_data):
            return
        if not self.game.scan_room_for_warrants(DEPARTURES_KEY, place="shuttle", cell=shuttle_cell_location()):
            self.game.alert("Scan the Passengers", "The scan turns up nobody to arrest.")

    @room_action
    def coffee_machine(self):
        self.game.open_panel(COFFEE_MACHINE.panel)


def _whereabouts(npc, docked):
    """Where a crew member is, as the Head Count lists them."""
    aboard = bool(crew_aboard([npc]))
    if is_jailed(npc):
        return "in the shuttle's cell" if aboard else "in the station's jail"
    if aboard:
        return "aboard"
    if not docked:
        return "left behind"
    if is_incapacitated(npc):
        return "too hurt to move"
    if npc["npc_goal"] == "board":
        return "on the way"
    return NOT_NOTICED


def _head_count_open(game):
    round_ = game.player_data["round"]
    return round_["aboard"] and round_["section"] == COMMAND


@register_panel("shuttle_head_count", "Head Count")
def head_count_panel(game, state):
    """Every crew member and where they are. While docked, the ones who haven't noticed the call can be paged."""
    if not _head_count_open(game):
        return None
    docked = game.player_data["round"]["shuttle"]["state"] == "docked"
    rows = []
    for npc in game.station_crew:
        where = _whereabouts(npc, docked)
        rows.append({"name": npc["name"], "text": f"{npc['name']} ({npc['job']}): {where}",
                     "page": where == NOT_NOTICED})
    return {"rows": rows}


@panel_action("shuttle_head_count")
def page(game, state, args):
    """Page a crew member who hasn't noticed the call, so they head for the shuttle."""
    npc = crew_named(game.station_crew, args["name"])
    docked = game.player_data["round"]["shuttle"]["state"] == "docked"
    if not _head_count_open(game) or npc is None or _whereabouts(npc, docked) != NOT_NOTICED:
        return
    if no_signal(game):
        return
    hurry_to_shuttle(npc)
    game.alert("Head Count", f"You page {npc['name']}. They drop what they are doing and head for Departures.")


COFFEE_MACHINE = register_mixing_station(MixingStation(
    panel="coffee_machine",
    title="Coffee Machine",
    name="Coffee Machine",
    container="machine",
    container_label="In the Machine",
    mix_label="Brew",
    idle_text="Put coffee grounds and water in the machine, then brew.",
    capacity=COFFEE_MACHINE_CAPACITY,
    shelf=coffee_shelf,
    mix=brew_coffee,
    supplies=(),
    book="coffee_recipes",
))

register_recipe_book(RecipeBook(
    panel="coffee_recipes",
    title="Card Taped to the Coffee Machine",
    recipes=COFFEE_RECIPES,
    categories=(("all", "All Recipes"),),
    sections=lambda category: [("COFFEE", sorted(COFFEE_RECIPES))],
))
