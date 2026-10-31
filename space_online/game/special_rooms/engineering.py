from space_online.game.objects.items import add_to_inventory, get_item_definition
from space_online.game.helper_methods.power_constants import (
    BALANCED_SYSTEM_LEVELS,
    BATTERY_BAND_COLORS,
    LOW_POWER_SYSTEM_LEVELS,
    SYSTEM_POWER_RATES,
    battery_band,
)
from space_online.game.helper_methods.oxygen_helper import (
    LIFE_SUPPORT_DAMAGE_BEGIN_TITLE,
    LIFE_SUPPORT_DAMAGE_BEGIN_MESSAGE,
    OXYGEN_DEPLETION_ANNOUNCEMENT_TEXT,
    OXYGEN_DEPLETION_GRACE_SECONDS,
    OXYGEN_DEPLETION_MODAL_BODY,
    OXYGEN_DEPLETION_FOLLOWUP_TITLE,
    OXYGEN_DEPLETION_FOLLOWUP_MESSAGE,
    life_support_entering_damage_range,
)
from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.ui_panels import (
    current_feedback,
    panel_action,
    register_panel,
    set_feedback,
)
from space_online.game.special_rooms.shared import (
    SpecialRoomBase,
    button,
    npc_contact_widgets,
    room_action,
    text_line,
)
from space_online.game.helper_methods.door_control import can_control_door
from space_online.game.maps.donut import ENGINEERING_KEY

FABRICATABLE_ITEM_IDS = {
    "Tool": ["wrench", "screwdriver", "wirecutters", "basic_tools"],
    "Book": ["welcome_guide", "station_map"],
}

SYSTEM_CONTROLS = (
    {"name": "Life Support", "key": "life_support", "power_draw": "High", "battery": True},
    {"name": "Hallway Lighting", "key": "hallway_lighting", "power_draw": "Medium", "battery": True},
    {"name": "Security Systems", "key": "security_systems", "power_draw": "Medium", "battery": False},
    {"name": "Communication Array", "key": "communication_array", "power_draw": "Low", "battery": False},
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
    CONTACT_JOBS = ("Engineer",)

    def room_options(self):
        widgets = [button("Access Fabricator", "room.access_fabricator")]
        widgets += npc_contact_widgets(
            self.game,
            "Engineer",
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
            button("Back to Station Menu", "room.set_mode", mode="menu"),
        ]

    @room_action
    def talk_to_engineer(self):
        self.game.alert("Engineer", "The engineer barely glances up from the console. 'Kinda busy here.'")

    @room_action
    def access_fabricator(self):
        self.game.open_panel("fabricator", category=next(iter(FABRICATABLE_ITEM_IDS)))

    @room_action(station="engineering_station")
    def access_engineering_panel(self):
        if not has_engineering_access(self.player_data):  # pragma: no cover - opening the station needs the same clearance
            self.game.alert(
                "Unauthorized Access",
                "You do not have authorization to access the Engineering Panel. "
                "Engineering, HoP or Captain clearance required.",
                kind="warning",
            )
            return
        self.game.open_panel("engineering_panel")


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
        "item_names": [item["name"] for item in items],
        "selected": selected if selected is not None and selected < len(items) else None,
        "feedback": current_feedback(state),
    }


@panel_action("fabricator", "category")
def fabricator_category(game, state, args):
    if args["name"] in FABRICATABLE_ITEM_IDS:
        state["category"] = args["name"]
        state.pop("selected", None)


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
            "draw": _power_draw(control["key"], value),
        })
    return {
        "battery_level": battery_level,
        "battery_color": BATTERY_BAND_COLORS[band],
        "battery_status": {"normal": "Normal operation", "low": "Low power mode"}.get(band, "Critical power level"),
        "battery_icon": "⚠️" if critical else "🔋",
        "battery_icon_color": "#FF0000" if critical else "#00FF00",
        "solar": bool(power["solar_charging"]),
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


def _update_system_level(game, system_key, value):
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
            game.report(LIFE_SUPPORT_DAMAGE_BEGIN_TITLE, LIFE_SUPPORT_DAMAGE_BEGIN_MESSAGE, kind="warning")


@panel_action("engineering_panel")
def set_level(game, state, args):
    if not has_engineering_access(game.player_data):
        return
    system_key = args["system"]
    value = int(args["value"])
    if system_key in SYSTEM_POWER_RATES and 0 <= value <= 10:
        _update_system_level(game, system_key, value)


@panel_action("engineering_panel")
def set_power_mode(game, state, args):
    mode = args["mode"]
    if not has_engineering_access(game.player_data) or mode not in POWER_MODE_LEVELS:
        return
    game.player_data["station_power"]["power_mode"] = mode
    for system_key, value in POWER_MODE_LEVELS[mode].items():
        _update_system_level(game, system_key, value)


def announce_oxygen_depletion(game):
    """Announce oxygen depletion to all crew when life support is set to 0"""
    if game.ui.get("announcement_active"):
        return

    game.player_data.setdefault("announcements", []).append({
        "text": OXYGEN_DEPLETION_ANNOUNCEMENT_TEXT,
        "type": "emergency",
    })
    game.player_data["damage_timers"]["oxygen_depletion"] = {
        "active": True,
        "damage_starts_at_seconds": get_elapsed_seconds(game.player_data) + OXYGEN_DEPLETION_GRACE_SECONDS,
    }
    game.ui["announcement_active"] = True
    game.open_panel("oxygen_announcement")


@register_panel("oxygen_announcement", "STATION-WIDE EMERGENCY ANNOUNCEMENT")
def oxygen_announcement_panel(game, state):
    return {"body": OXYGEN_DEPLETION_MODAL_BODY}


@panel_action("oxygen_announcement")
def acknowledge(game, state, args):
    game.ui["announcement_active"] = False
    game.close_panel("oxygen_announcement")
    game.report(OXYGEN_DEPLETION_FOLLOWUP_TITLE, OXYGEN_DEPLETION_FOLLOWUP_MESSAGE, kind="warning")
