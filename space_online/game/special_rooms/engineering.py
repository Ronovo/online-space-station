from space_online.game.objects.items import add_to_inventory, carried_or_held, get_item_definition
from space_online.game.helper_methods.power_constants import (
    BALANCED_SYSTEM_LEVELS,
    BATTERY_BAND_COLORS,
    LOW_POWER_SYSTEM_LEVELS,
    SYSTEM_NAMES,
    SYSTEM_POWER_RATES,
    battery_band,
    system_name,
)
from space_online.game.helper_methods.oxygen_helper import (
    LIFE_SUPPORT_DAMAGE_BEGIN_TITLE,
    LIFE_SUPPORT_DAMAGE_BEGIN_MESSAGE,
    OXYGEN_DEPLETION_ANNOUNCEMENT_TEXT,
    OXYGEN_DEPLETION_MODAL_BODY,
    OXYGEN_DEPLETION_FOLLOWUP_TITLE,
    OXYGEN_DEPLETION_FOLLOWUP_MESSAGE,
    life_support_entering_damage_range,
)
from space_online.game.helper_methods import gas_mix
from space_online.game.helper_methods.atmos import connect, move_canister, port_canister
from space_online.game.helper_methods.engine import (
    BURN_CHAMBER,
    HOT_LIMIT,
    LINES,
    SETTING_RANGES,
    engine_output,
    hint,
    wrecked,
)
from space_online.game.helper_methods.errands import record_duty_done
from space_online.game.helper_methods.stores import take_from_stores
from space_online.game.helper_methods.ui_panels import (
    current_feedback,
    panel_action,
    register_panel,
    set_feedback,
)
from space_online.game.special_rooms.shared import (
    SpecialRoomBase,
    available_npc,
    button,
    npc_contact_widgets,
    room_action,
    text_line,
)
from space_online.game.helper_methods.door_control import can_control_door
from space_online.game.maps.donut import ENGINEERING_KEY
from space_online.game.objects.gases import CANISTER
from space_online.game.objects.weapons import FABRICATOR_WEAPON_IDS

FABRICATABLE_ITEM_IDS = {
    "Tool": ["wrench", "screwdriver", "wirecutters", "repair_tool", "fire_extinguisher", "basic_tools", "gas_analyzer",
             "transfer_valve"],
    "Book": ["welcome_guide", "station_map"],
    "Weapon": FABRICATOR_WEAPON_IDS,
}
# Ore from the station stores that fabricating an item uses up. Anything not listed is free.
FABRICATION_ORE = {"wrench": 1, "screwdriver": 1, "wirecutters": 1, "repair_tool": 2, "fire_extinguisher": 1,
                   "basic_tools": 3, "gas_analyzer": 2, "transfer_valve": 3,
                   "crowbar": 2, "combat_knife": 3, "fire_axe": 4}

SYSTEM_CONTROLS = tuple(
    {"name": SYSTEM_NAMES[key], "key": key, "power_draw": power_draw, "battery": battery}
    for key, power_draw, battery in (
        ("life_support", "High", True),
        ("hallway_lighting", "Medium", True),
        ("security_systems", "Medium", False),
        ("communication_array", "Low", False),
    )
)

POWER_MODES = (
    ("Balanced (Standard Operation)", "balanced"),
    ("High Performance (Increased Draw)", "high"),
    ("Power Saving (Limited Functionality)", "low"),
    ("Emergency Only (Critical Systems)", "emergency"),
)

POWER_MODE_LEVELS = {
    "balanced": BALANCED_SYSTEM_LEVELS,
    "high": {"life_support": 10, "hallway_lighting": 10, "security_systems": 10, "communication_array": 10},
    "low": LOW_POWER_SYSTEM_LEVELS,
    "emergency": {"life_support": 10, "hallway_lighting": 1, "security_systems": 3, "communication_array": 1},
}

# Either of these, carried or held, repairs a faulted system.
REPAIR_TOOL_IDS = ("basic_tools", "repair_tool")


class Engineering(SpecialRoomBase):
    ROOM_TITLE = "Engineering Bay"
    ROOM_HEADING = "Station Engineering Bay"
    ROOM_DESCRIPTION = (
        "The engineering bay is filled with equipment and tools. Various machines hum with power, "
        "and spare parts are organized on shelves. This is where the station's systems are maintained "
        "and repaired."
    )
    DOOR_KEY = ENGINEERING_KEY
    STATION_ENTRIES = ({"label": "Enter Engineering Station", "mode": "engineering_station"},)
    CONTACT_POSTS = {"Engineer": DOOR_KEY}

    def room_options(self):
        widgets = [button("Access Fabricator", "room.access_fabricator")]
        widgets += npc_contact_widgets(
            self.game,
            "Engineer",
            self.DOOR_KEY,
            talk_label="Talk to Engineer",
            talk_action="talk_to_engineer",
            absent_flavor="The engineer is away from the bay.",
        )
        return widgets + self.back_to_station_menu()

    def mode_buttons(self, mode):
        if mode != "engineering_station" or not self.station_allowed(mode):
            return None
        return [
            text_line("Engineering Station Controls", style="title"),
            button("Engineering Panel", "room.access_engineering_panel"),
            button("Combustion Engine", "room.access_combustion_engine"),
            button("Back to Station Menu", "room.set_mode", mode="menu"),
        ]

    @room_action
    def talk_to_engineer(self):
        if available_npc(self.game, "Engineer", self.DOOR_KEY):
            self.game.alert("Engineer", "The engineer barely glances up from the console. 'Kinda busy here.'")

    @room_action
    def access_fabricator(self):
        self.game.open_panel("fabricator", category=next(iter(FABRICATABLE_ITEM_IDS)))

    @room_action(station="engineering_station")
    def access_engineering_panel(self):
        self.game.open_panel("engineering_panel")

    @room_action(station="engineering_station")
    def access_combustion_engine(self):
        self.game.open_panel("combustion_engine")


def has_engineering_access(player_data):
    """True if the player may use engineering panel controls: the same people who can work its door."""
    return can_control_door(player_data, ENGINEERING_KEY)


def _fabricator_items(category):
    return [get_item_definition(item_id) for item_id in FABRICATABLE_ITEM_IDS.get(category, [])]


@register_panel("fabricator", "Fabricator")
def fabricator_panel(game, state):
    category = state.get("category")
    items = _fabricator_items(category)
    selected = state.get("selected")
    return {
        "categories": [c for c in FABRICATABLE_ITEM_IDS if _fabricator_items(c)],
        "category": category,
        "ore": game.player_data["stores"]["ore"],
        "item_names": [item["name"] + (f" ({FABRICATION_ORE[item['id']]} ore)" if item["id"] in FABRICATION_ORE else "")
                       for item in items],
        "selected": selected if selected is not None and selected < len(items) else None,
        "feedback": current_feedback(state),
    }


@panel_action("fabricator", "category")
def fabricator_category(game, state, args):
    if args["name"] in FABRICATABLE_ITEM_IDS:
        state["category"] = args["name"]
        state.pop("selected", None)
        state.pop("feedback", None)


@panel_action("fabricator", "select")
def fabricator_select(game, state, args):
    state["selected"] = int(args["index"])


def _fabricator_selection(state, prompt, prompt_seconds):
    items = _fabricator_items(state.get("category"))
    selected = state.get("selected")
    if selected is None or not (0 <= selected < len(items)):
        set_feedback(state, prompt, "orange", seconds=prompt_seconds)
        return None
    return items[selected]


@panel_action("fabricator")
def create(game, state, args):
    item_def = _fabricator_selection(state, "Please select a category and an item.", 3)
    if item_def is None:
        return
    cost = FABRICATION_ORE.get(item_def["id"], 0)
    if not take_from_stores(game.player_data, "ore", cost):
        set_feedback(state, f"Not enough ore in the station stores: a {item_def['name']} takes {cost}.", "orange")
        return
    add_to_inventory(game.player_data, get_item_definition(item_def["id"]))
    set_feedback(state, f"'{item_def['name']}' created successfully.", "cyan")
    game.add_note(f"Fabricated a {item_def['name']} ({item_def['id']}) in Engineering.")


@panel_action("fabricator", "examine")
def fabricator_examine(game, state, args):
    item_def = _fabricator_selection(state, "Please select a category and an item to examine.", 4)
    if item_def is not None:
        set_feedback(
            state, f"Examine: {item_def.get('description', 'No description available.')}", "yellow", seconds=None
        )


def _power_draw(key, value):
    if value == 0:
        return {"text": "Power draw: None (System OFF)", "color": "#FF0000"}
    rate = SYSTEM_POWER_RATES.get(key, 0.3) * value / 10.0
    color = "#00FF00" if value <= 3 else "#FFAA00" if value <= 7 else "#FF5500"
    return {"text": f"Power draw: {rate:.2f}% per minute", "color": color}


@register_panel("engineering_panel", "Engineering Panel")
def engineering_panel(game, state):
    power = game.player_data["station_power"]
    battery_level = power["battery_level"]
    band = battery_band(battery_level)
    critical = band in ("outage", "critical")
    levels = power["system_levels"]
    systems = []
    for control in SYSTEM_CONTROLS:
        value = int(levels.get(control["key"], BALANCED_SYSTEM_LEVELS[control["key"]]))
        systems.append({
            **control,
            "value": value,
            "online": value > 0,
            "faulted": control["key"] in power["faults"],
            "draw": _power_draw(control["key"], value),
        })
    return {
        "battery_level": battery_level,
        "battery_color": BATTERY_BAND_COLORS[band],
        "battery_status": {"normal": "Normal operation", "low": "Low power mode"}.get(band, "Critical power level"),
        "battery_icon": "⚠️" if critical else "🔋",
        "battery_icon_color": "#FF0000" if critical else "#00FF00",
        "solar": bool(power["solar_charging"]),
        "engine_output": engine_output(game.player_data["engine"]),
        "systems": systems,
        "power_modes": POWER_MODES,
        "power_mode": power["power_mode"],
    }


@panel_action("engineering_panel")
def toggle_solar(game, state, args):
    if not has_engineering_access(game.player_data):
        return
    power = game.player_data["station_power"]
    power["solar_charging"] = not power["solar_charging"]
    game.alert(
        "Solar Control",
        "Solar arrays activated. Batteries now charging from solar power."
        if power["solar_charging"]
        else "Solar arrays deactivated. Battery charging stopped.",
    )


def set_system_level(game, system_key, value):
    """Set a system's power level and apply life-support side effects."""
    levels = game.player_data["station_power"]["system_levels"]
    previous_value = levels.get(system_key, 10)
    levels[system_key] = value

    if system_key == "life_support":
        if value == 0:
            if previous_value > 0:
                announce_oxygen_depletion(game)
            return
        game.player_data.pop("announcements", None)
        game.ui["announcement_active"] = False
        if life_support_entering_damage_range(previous_value, value):
            game.alert(LIFE_SUPPORT_DAMAGE_BEGIN_TITLE, LIFE_SUPPORT_DAMAGE_BEGIN_MESSAGE, kind="warning")


@panel_action("engineering_panel")
def set_level(game, state, args):
    if not has_engineering_access(game.player_data):
        return
    system_key = args["system"]
    value = int(args["value"])
    if system_key not in SYSTEM_POWER_RATES or not 0 <= value <= 10:
        return
    power = game.player_data["station_power"]
    if value > 0 and system_key == "life_support" and power["battery_level"] <= 0:
        game.alert("No Power", "The battery is dead. Life support can't run until it has some charge.", kind="warning")
        return
    if value > 0 and system_key in power["faults"]:
        game.alert("System Fault", f"{system_name(system_key)} is faulted. Repair it before powering it back up.",
                   kind="warning")
        return
    before = power["system_levels"][system_key]
    set_system_level(game, system_key, value)
    if system_key == "hallway_lighting":
        power["dimmed_from"] = None
    if before > 0 and value == 0 and system_key != "life_support":
        game.alert("Engineering Panel", f"{system_name(system_key)} switched off.")
    elif before == 0 and value > 0:
        game.alert("Engineering Panel", f"{system_name(system_key)} back on at level {value}.")


@panel_action("engineering_panel")
def set_power_mode(game, state, args):
    mode = args["mode"]
    if has_engineering_access(game.player_data) and mode in POWER_MODE_LEVELS:
        apply_power_mode(game, mode)


def apply_power_mode(game, mode):
    """Switch to a power mode, setting every system that isn't faulted to the mode's level. Returns a line such as
    "Life Support 0 to 7" for each level that changed. The lighting follows the mode from here on, so an
    antagonist's dim is no longer the Engineer's to undo."""
    power = game.player_data["station_power"]
    power.update(power_mode=mode, dimmed_from=None)
    changed = []
    for system_key, value in POWER_MODE_LEVELS[mode].items():
        dead = system_key == "life_support" and power["battery_level"] <= 0
        before = power["system_levels"][system_key]
        if system_key not in power["faults"] and not dead and before != value:
            set_system_level(game, system_key, value)
            changed.append(f"{system_name(system_key)} {before} to {value}")
    return changed


@panel_action("engineering_panel")
def repair(game, state, args):
    power = game.player_data["station_power"]
    system_key = args["system"]
    if has_engineering_access(game.player_data) and system_key in power["faults"]:
        repair_with_tools(game, system_name(system_key), lambda: repair_system(game, system_key), "It is back online.")


def repair_with_tools(game, name, fix, result):
    """Repair `name` by calling fix(), given Basic Tools or a Repair Tool carried or held. `result` is the sentence
    the log adds after saying so."""
    tool = carried_or_held(game.player_data, REPAIR_TOOL_IDS)
    if tool is None:
        game.alert("Repair", f"You need Basic Tools or a Repair Tool to repair the {name}.")
        return
    fix()
    record_duty_done(game.player_data)
    game.add_note(f"Repaired the {name} with the {tool['name']}.")
    game.alert("Repair", f"You repair the {name} with the {tool['name']}. {result}")


def repair_system(game, system_key):
    """Clear a system's fault and bring it back up to the level it had."""
    power = game.player_data["station_power"]
    power["faults"].remove(system_key)
    set_system_level(game, system_key, power["fault_levels"].pop(system_key))


def announce_oxygen_depletion(game):
    """Announce oxygen depletion to all crew when life support is set to 0"""
    if game.ui.get("announcement_active"):
        return

    game.player_data.setdefault("announcements", []).append({
        "text": OXYGEN_DEPLETION_ANNOUNCEMENT_TEXT,
        "type": "emergency",
    })
    game.ui["announcement_active"] = True
    game.open_panel("oxygen_announcement")


@register_panel("oxygen_announcement", "STATION-WIDE EMERGENCY ANNOUNCEMENT")
def oxygen_announcement_panel(game, state):
    return {"body": OXYGEN_DEPLETION_MODAL_BODY}


@panel_action("oxygen_announcement")
def acknowledge(game, state, args):
    game.ui["announcement_active"] = False
    game.close_panel("oxygen_announcement")
    game.alert(OXYGEN_DEPLETION_FOLLOWUP_TITLE, OXYGEN_DEPLETION_FOLLOWUP_MESSAGE, kind="warning")


ENGINE_SETTINGS = (("mixer", "Mixer ratio (% fuel)"), ("injection", "Injection rate"), ("coolant", "Coolant flow"))


@register_panel("combustion_engine", "Combustion Engine")
def combustion_engine_panel(game, state):
    engine = game.player_data["engine"]
    return {
        "gauge": gas_mix.readout(engine["chamber"], BURN_CHAMBER["volume"]),
        "rated": BURN_CHAMBER["rated"],
        "running": engine["running"],
        "hot": engine["hot"],
        "cold": engine["cold"],
        "hot_limit": HOT_LIMIT,
        "output": engine_output(engine),
        "damage": engine["damage"],
        "hint": hint(engine),
        "slots": [canister and {"index": index, "label": canister["label"], "port": canister["port"],
                                "gauge": gas_mix.readout(canister["mix"], CANISTER["volume"])}
                  for index, canister in enumerate(engine["canisters"])],
        "lines": [(line, name) for line, (name, _, _) in LINES.items()],
        "settings": [{"key": key, "label": label, "value": engine["settings"][key], "max": SETTING_RANGES[key]}
                     for key, label in ENGINE_SETTINGS],
        "coolant_fault": engine["coolant_fault"],
        "repairable": engine["damage"] > 0 and not engine["running"],
        "feedback": current_feedback(state),
    }


def _engine_panel_action(handler):
    """A Combustion Engine panel action, for players with Engineering access, given the engine."""
    @panel_action("combustion_engine", handler.__name__)
    def action(game, state, args):
        if has_engineering_access(game.player_data):
            handler(game, state, args, game.player_data["engine"])
    return action


def _bay_canister(engine, args):
    index = int(args["index"])
    return engine["canisters"][index] if 0 <= index < len(engine["canisters"]) else None


@_engine_panel_action
def set_setting(game, state, args, engine):
    key = args["setting"]
    if key in SETTING_RANGES:
        engine["settings"][key] = max(0, min(SETTING_RANGES[key], int(args["value"])))


@_engine_panel_action
def ignite(game, state, args, engine):
    if engine["running"]:
        set_feedback(state, "The engine is already running.")
    elif wrecked(engine):
        set_feedback(state, "The chamber is wrecked. Repair it first.", "orange")
    elif port_canister(engine, "fuel") is None:
        set_feedback(state, "Connect a canister as Fuel first.", "orange")
    else:
        engine["running"] = True
        game.add_note("Lit the combustion engine.")
        set_feedback(state, "The igniter sparks, and the chamber catches.", "lightgreen")


@_engine_panel_action
def shut_down(game, state, args, engine):
    if not engine["running"]:
        set_feedback(state, "The engine isn't running.")
        return
    engine["running"] = False
    game.add_note("Shut the combustion engine down.")
    set_feedback(state, "The injectors close and the burn dies away.")


@_engine_panel_action
def emergency_vent(game, state, args, engine):
    engine.update(chamber=gas_mix.empty_mix(), running=False)
    game.add_note("Vented the combustion chamber to space.")
    set_feedback(state, "The chamber vents to space. Whatever was burning goes out.")


@_engine_panel_action
def set_port(game, state, args, engine):
    canister = _bay_canister(engine, args)
    port = args.get("port") or None
    if canister is None or (port is not None and port not in LINES):
        return
    if engine["running"] and (canister["port"] or (port and port_canister(engine, port))):
        set_feedback(state, "Shut the engine down before changing a line it is drawing from.", "orange")
        return
    connect(engine, canister, port)
    set_feedback(state, f"{canister['label']} is connected as {LINES[port][0]}." if port
                 else f"{canister['label']} is disconnected.")


@_engine_panel_action
def send_to_atmospherics(game, state, args, engine):
    canister = _bay_canister(engine, args)
    if canister is None:
        return
    if canister["port"]:
        set_feedback(state, f"Disconnect {canister['label']} first.", "orange")
        return
    free = move_canister(engine["canisters"], int(args["index"]), game.player_data["atmos"]["canisters"])
    if free is None:
        set_feedback(state, "The Canister Rack in Atmospherics has no free slot.", "orange")
        return
    message = f"{canister['label']} goes down the tube into slot {free + 1} of the Atmospherics Canister Rack."
    game.add_note(message)
    set_feedback(state, message)


@_engine_panel_action
def repair_coolant_line(game, state, args, engine):
    if engine["coolant_fault"]:
        repair_with_tools(game, "coolant line", lambda: engine.update(coolant_fault=False), "Coolant flows again.")


@_engine_panel_action
def repair_chamber(game, state, args, engine):
    if engine["damage"] > 0 and not engine["running"]:
        repair_with_tools(game, "combustion chamber", lambda: engine.update(damage=0.0), "It is ready to light.")
