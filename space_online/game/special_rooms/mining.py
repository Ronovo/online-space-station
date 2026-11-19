"""The Mining Bay: the Miner Station's locker room, the magnet, and shuttle trips to the planet below.

player_data["mining"]["expedition"] holds a shuttle trip in progress:
    planet   index into PLANETS
    haul     {ore id: count} dug up so far, kept only if the miner makes it back
    vein     the ore id of the vein the last action struck, or None
    log      what the last action did, shown on the surface screen

Ore from a vein reads as unidentified on the surface until the Miner scans a vein of its kind with their PDA.
The station sorts the haul when the shuttle docks.
"""

import random

from space_online.game.helper_methods.combat import DEFEAT_HEALTH, capitalized, register_fight, start_fight
from space_online.game.helper_methods.errands import counted
from space_online.game.helper_methods.game_clock import get_elapsed_seconds, pass_time
from space_online.game.helper_methods.artifacts import new_artifact
from space_online.game.helper_methods.health_bands import overall_health
from space_online.game.helper_methods.ui_panels import register_panel
from space_online.game.maps.donut import MINING_KEY
from space_online.game.objects.items import PDA_ID, add_to_inventory, carried_or_held, get_item_definition, holding
from space_online.game.objects.mining_items import (
    MAGNET_ORES,
    MINER_STAND_PRICES,
    MINING_GEAR_IDS,
    ORE_VALUES,
    PLANETS,
    SURFACE_ORES,
    planet_index,
    rocks_waiting,
)
from space_online.game.special_rooms.shared import (
    SpecialRoomBase,
    available_npc,
    button,
    issue_gear,
    npc_contact_widgets,
    register_stand,
    room_action,
    text_line,
)

MONSTER_CHANCE = 0.35
ORE_CHANCE = 0.45
ARTIFACT_CHANCE = 0.06
# Game seconds a search of the surface takes.
SEARCH_SECONDS_RANGE = (20, 30)
# Ore the shuttle's hold takes on one trip. Artifacts don't count.
HOLD_CAPACITY = 10

register_stand("ore_counter", "Ore Counter", "The miner sells common ore from the day's haul.",
               MINER_STAND_PRICES, "the Miner")


def _ore_name(ore_id):
    return get_item_definition(ore_id)["name"]


def _ore_summary(ores, identified=None):
    """'2 Iron Ore, 1 Quartz' for {ore id: count}. Given the kinds identified, the rest count as unidentified ore."""
    named = {ore_id: count for ore_id, count in ores.items() if identified is None or ore_id in identified}
    parts = [f"{count} {_ore_name(ore_id)}" for ore_id, count in named.items()]
    unidentified = sum(ores.values()) - sum(named.values())
    return ", ".join(parts + ([f"{unidentified} unidentified ore"] if unidentified else []))


def _haul_summary(expedition, identified=None):
    """'2 Gold Ore, 1 Alien Artifact' for what a trip has in the shuttle's hold."""
    artifacts = [f"{expedition['artifacts']} Alien Artifact"] if expedition["artifacts"] else []
    return ", ".join([*filter(None, [_ore_summary(expedition["haul"], identified)]), *artifacts])


def _planets_with(ore_id):
    return ", ".join(planet["name"] for planet in PLANETS if ore_id in planet["ores"])


def _add_ore(player_data, ores):
    for ore_id, count in ores.items():
        add_to_inventory(player_data, {**get_item_definition(ore_id), "quantity": count})


class Mining(SpecialRoomBase):
    ROOM_TITLE = "Mining Bay"
    ROOM_HEADING = "Station Mining Bay"
    ROOM_DESCRIPTION = (
        "The mining bay smells of dust and machine oil. Lockers line one wall, the magnet's housing "
        "fills the far end, and a small shuttle waits on its cradle above the bay doors."
    )
    DOOR_KEY = MINING_KEY
    STATION_ENTRIES = ({"label": "Enter Miner Station", "mode": "locker_room"},)
    CONTACT_POSTS = {"Miner": DOOR_KEY}
    SURFACE_ACTIONS = frozenset({"search", "scan_vein", "return_to_station"})

    @property
    def mining(self):
        return self.player_data["mining"]

    @property
    def expedition(self):
        return self.mining["expedition"]

    def _planet(self):
        """The planet of the trip in progress, else the one the station is over now."""
        if self.expedition:
            return PLANETS[self.expedition["planet"]]
        return PLANETS[planet_index(get_elapsed_seconds(self.player_data))]

    def view(self):
        screen = super().view()
        if self.expedition:
            planet = self._planet()
            screen.update(title=planet["name"], heading=f"Surface of {planet['name']}", description=planet["desc"])
        return screen

    def buttons(self):
        return self.surface_widgets() if self.expedition else super().buttons()

    def hazard(self):
        return None if self.expedition else super().hazard()

    def perform(self, name, args):
        """On the planet only the surface actions work: the shuttle is the one way back."""
        on_surface = bool(self.expedition)
        if on_surface and name == "exit":
            self.game.alert("On the Surface", "The shuttle is the only way back to the station.")
        elif on_surface == (name in self.SURFACE_ACTIONS):
            super().perform(name, args)

    def room_options(self):
        widgets = npc_contact_widgets(
            self.game,
            "Miner",
            self.DOOR_KEY,
            talk_label="Buy Ore",
            talk_action="buy_ore",
            absent_flavor="The miner is away from the bay.",
        )
        return widgets + self.back_to_station_menu()

    def mode_buttons(self, mode):
        if mode != "locker_room" or not self.station_allowed(mode):
            return None
        planet = self._planet()
        waiting = rocks_waiting(self.mining, get_elapsed_seconds(self.player_data))
        magnet = "ON" if self.mining["magnet_since"] is not None else "OFF"
        return [
            text_line("Locker Room", style="title"),
            text_line(f"The station is passing over {planet['name']}.", style="italic"),
            button("Take Mining Gear", "room.take_gear"),
            button(f"Magnet: {magnet}", "room.toggle_magnet"),
            button(f"Mine Rocks ({waiting} waiting)", "room.mine_rocks"),
            button(f"Board the Shuttle to {planet['name']}", "room.board_shuttle"),
            text_line("Ore sells at the Cargo Bay's export counter.", style="italic"),
            button("Back to Station Menu", "room.set_mode", mode="menu"),
        ]

    def surface_widgets(self):
        expedition = self.expedition
        widgets = [text_line(line) for line in expedition["log"]]
        haul = _haul_summary(expedition, self.mining["identified"]) or "nothing yet"
        return widgets + [
            text_line(f"In the shuttle's hold: {haul}.", style="italic"),
            *([button("Scan the Vein", "room.scan_vein")] if self._vein_to_scan() else []),
            button("Search for Rocks", "room.search"),
            button("Return to the Station", "room.return_to_station"),
        ]

    # --- Room options --------------------------------------------------------

    @room_action
    def buy_ore(self):
        if available_npc(self.game, "Miner", self.DOOR_KEY):
            self.game.open_panel("ore_counter")

    # --- Locker room ---------------------------------------------------------

    def _has_pickaxe(self):
        if carried_or_held(self.player_data, ("pickaxe",)):
            return True
        self.game.alert("No Pickaxe", "You need a pickaxe. Take your mining gear from the lockers.")
        return False

    @room_action(station="locker_room")
    def take_gear(self):
        issue_gear(self.game, MINING_GEAR_IDS, "Lockers", "the mining lockers", "your mining gear")

    @room_action(station="locker_room")
    def toggle_magnet(self):
        elapsed_seconds = get_elapsed_seconds(self.player_data)
        if self.mining["magnet_since"] is None:
            self.mining["magnet_since"] = elapsed_seconds
            self.game.alert("Magnet", "The magnet hums to life and starts pulling rocks toward the bay.")
        else:
            self.mining["rocks"] = rocks_waiting(self.mining, elapsed_seconds)
            self.mining["magnet_since"] = None
            self.game.alert("Magnet", "The magnet winds down.")

    @room_action(station="locker_room")
    def mine_rocks(self):
        elapsed_seconds = get_elapsed_seconds(self.player_data)
        waiting = rocks_waiting(self.mining, elapsed_seconds)
        if not waiting:
            self.game.alert("Magnet", "There are no rocks to mine yet. The magnet brings them in while it is on.")
            return
        if not self._has_pickaxe():
            return
        ores = {}
        for _ in range(waiting):
            ore_id = random.choice(MAGNET_ORES)
            ores[ore_id] = ores.get(ore_id, 0) + 1
        _add_ore(self.player_data, ores)
        self.mining["rocks"] = 0
        if self.mining["magnet_since"] is not None:
            self.mining["magnet_since"] = elapsed_seconds
        self.add_note(f"Mined {counted(waiting, 'rock')} from the magnet: {_ore_summary(ores)}.")
        self.game.alert("Mining", f"You break up {counted(waiting, 'rock')} and get {_ore_summary(ores)}.")

    @room_action(station="locker_room")
    def board_shuttle(self):
        if not self._has_pickaxe():
            return
        if overall_health(self.player_data) < DEFEAT_HEALTH:
            self.game.alert("Shuttle", "You are in no shape for the surface. Get treated in MedBay first.")
            return
        index = planet_index(get_elapsed_seconds(self.player_data))
        planet = PLANETS[index]
        self.mining["expedition"] = {
            "planet": index,
            "haul": {},
            "vein": None,
            "artifacts": 0,
            "log": [f"The shuttle sets down on {planet['name']}."],
        }
        self.add_note(f"Took the shuttle down to {planet['name']}.")

    # --- The surface -----------------------------------------------------------

    @room_action
    def search(self):
        """Look for rocks, which takes a while. Sometimes there is ore, sometimes nothing, and sometimes something
        finds the miner. Nothing is searched for once the hold is full."""
        expedition = self.expedition
        expedition["vein"] = None
        if sum(expedition["haul"].values()) >= HOLD_CAPACITY:
            expedition["log"] = ["The shuttle's hold is full of ore. Take it back to the station."]
            return
        pass_time(self.player_data, random.randint(*SEARCH_SECONDS_RANGE))
        planet = self._planet()
        roll = random.random()
        if roll < MONSTER_CHANCE:
            monster = random.choice(planet["monsters"])
            expedition["log"] = []
            start_fight(self.game, "monster", {**monster, "name": f"the {monster['name']}", "humanoid": False},
                        f"A {monster['name']} bursts out of the rocks and comes straight at you!",
                        monster=monster["name"])
        elif roll < MONSTER_CHANCE + ORE_CHANCE:
            _strike_vein(self.mining, random.choice(planet["ores"]), "You find")
        elif roll < MONSTER_CHANCE + ORE_CHANCE + ARTIFACT_CHANCE:
            expedition["artifacts"] += 1
            expedition["log"] = ["Half buried in the rock is something nobody mined: an alien artifact. "
                                 "The Research Lab will want it."]
        else:
            expedition["log"] = ["You search the rocks and find nothing worth taking."]

    def _vein_to_scan(self):
        """The ore id of a struck vein a Miner holding their PDA has yet to identify, or None."""
        vein = self.expedition["vein"]
        if (vein is None or vein in self.mining["identified"] or self.player_data["job"] != "Miner"
                or not holding(self.player_data, PDA_ID)):
            return None
        return vein

    @room_action
    def scan_vein(self):
        """Identify the vein just struck. Every vein of that ore is known on sight for the rest of the shift."""
        ore_id = self._vein_to_scan()
        if ore_id is None:
            return
        name = _ore_name(ore_id)
        self.mining["identified"].append(ore_id)
        self.expedition["log"] = [f"Your PDA identifies the vein: {name}."]
        self.add_note(f"Identified {name} with the PDA.")
        self.game.alert("PDA Scan: Vein", f"{name}. Exports for {ORE_VALUES[ore_id]} credits. "
                                          f"Found on {_planets_with(ore_id)}.")

    @room_action
    def return_to_station(self):
        expedition = self.expedition
        planet = self._planet()
        _add_ore(self.player_data, expedition["haul"])
        for _ in range(expedition["artifacts"]):
            add_to_inventory(self.player_data, new_artifact())
        self.mining["expedition"] = None
        summary = _haul_summary(expedition)
        if summary:
            self.add_note(f"Came back from {planet['name']} with {summary}.")
            self.game.alert("Back Aboard", f"The shuttle docks. You unload {summary}.")
        else:
            self.game.alert("Back Aboard", "The shuttle docks. You came back empty-handed.")


def _strike_vein(mining, ore_id, found):
    """Dig ore out of a vein. found starts the log line, which names the ore only once it has been identified."""
    expedition = mining["expedition"]
    expedition["haul"][ore_id] = expedition["haul"].get(ore_id, 0) + 1
    expedition["vein"] = ore_id
    what = _ore_name(ore_id) if ore_id in mining["identified"] else "ore you don't recognise"
    expedition["log"] = [f"{found} a vein of {what} and dig some out."]


def _monster_beaten(game, fight, how):
    """A beaten monster turns up a piece of the planet's ore."""
    mining = game.player_data["mining"]
    _strike_vein(mining, random.choice(PLANETS[mining["expedition"]["planet"]]["ores"]),
                 f"{capitalized(fight['enemy']['name'])} goes down. Under it you find")


def _rescued(game, fight):
    """The rescue drone flies a beaten miner home, without the trip's ore."""
    mining = game.player_data["mining"]
    planet = PLANETS[mining["expedition"]["planet"]]
    monster = fight["monster"]
    mining["expedition"] = None
    game.add_note(f"Was beaten by a {monster} on {planet['name']} and lost the trip's ore.")
    game.alert(
        "Rescued",
        f"The {monster} is too much for you. The shuttle's rescue drone drags you aboard and "
        "flies you back to the Mining Bay. The ore you dug up is left behind. Get treated in MedBay.",
        kind="warning",
    )


register_fight("monster", _monster_beaten, _rescued)


@register_panel("ore_log", "Ore Log")
def ore_log_panel(game, state):
    """The Miner's collection: every ore found in veins, named once its vein has been scanned."""
    identified = game.player_data["mining"]["identified"]
    return {
        "ores": [{"name": _ore_name(ore_id), "value": ORE_VALUES[ore_id], "planets": _planets_with(ore_id)}
                 if ore_id in identified else None for ore_id in SURFACE_ORES],
        "found": len(identified),
        "total": len(SURFACE_ORES),
    }
