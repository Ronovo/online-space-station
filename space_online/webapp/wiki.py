"""Player Guide: wiki pages at /wiki/<Page_Name>, listed by section on the /wiki/ index."""

from flask import Blueprint, abort, render_template, url_for

from space_online.game.character_methods.character_creation import JOBS
from space_online.game.helper_methods import alcohol_helper, jail, oxygen_helper, power_constants, random_events
from space_online.game.helper_methods.door_control import SPECIAL_ROOM_DOORS, can_control_door
from space_online.game.helper_methods.npc_movement import NPC_CALL_SUCCESS_CHANCE
from space_online.game.helper_methods.stock_market import CYCLE_INTERVAL_SECONDS, DEFAULT_COMPANY_NAMES
from space_online.game.main import SPECIAL_ROOM_CLASSES
from space_online.game.objects import botany_items
from space_online.game.objects.drinks import MAX_GLASS_POURS
from space_online.game.objects.food import PRODUCE
from space_online.game.objects.items import ALOE_BURN_RELIEF, DEFAULT_LOCKER_ITEM_IDS, get_item_definition
from space_online.game.special_rooms.engineering import FABRICATABLE_ITEM_IDS, POWER_MODES, system_name
from space_online.game.special_rooms.med_bay import COST_MULTIPLIERS

WIKI_SECTIONS = (
    ("Basics", ("Getting Started", "The Station", "Items and Hands", "Health", "Crew")),
    ("Systems", ("Power", "Life Support", "Medical", "Security and Jail", "Stock Market", "Bar", "Botany",
                 "Engineering", "Bridge and Personnel", "Errands and Job Events", "Station Status")),
    ("Jobs", ("Staff Assistant", "Engineer", "Security Guard", "Doctor", "Bartender", "Botanist",
              "Head of Personnel", "Captain")),
)

wiki = Blueprint("wiki", __name__, url_prefix="/wiki")


def page_slug(title):
    """'Staff Assistant' -> 'Staff_Assistant', the page's name in its URL."""
    return title.replace(" ", "_")


PAGES = {page_slug(title): title for _, titles in WIKI_SECTIONS for title in titles}


def page_url(title):
    return url_for("wiki.page", name=page_slug(title))


def job_stations(job):
    """'Room: Station' for every station the job can work, in map order."""
    subdepartment = JOBS[job]["subdepartment"]
    stations = []
    for room_class in SPECIAL_ROOM_CLASSES.values():
        door_key = getattr(room_class, "DOOR_KEY", None)
        if door_key is None or not can_control_door({"subdepartment": subdepartment}, door_key):
            continue
        for entry in room_class.STATION_ENTRIES:
            allowed = entry.get("subdepartments")
            if allowed is None or subdepartment in allowed:
                stations.append(f"{room_class.ROOM_TITLE}: {entry['label'].removeprefix('Enter ')}")
    return stations


def _item_name(item_id):
    return get_item_definition(item_id)["name"]


def _stage_minutes():
    """(plant name, minutes per growth stage) for every seed."""
    plants = []
    for seed_id in botany_items.BOTANY_SEED_IDS:
        attributes = botany_items.BOTANY_ITEMS[seed_id]["attributes"]
        seconds = botany_items.growth_duration_seconds(attributes["growth_class"])
        plants.append((attributes["plant_name"], seconds // 60))
    return plants


def _facts():
    """Numbers the pages quote, read from the game so the guide follows it when they change."""
    return {
        "rooms": [door["room_name"] for door in SPECIAL_ROOM_DOORS.values()],
        "locker_items": [_item_name(item_id) for item_id in DEFAULT_LOCKER_ITEM_IDS],
        "call_chance": NPC_CALL_SUCCESS_CHANCE,
        "company_count": len(DEFAULT_COMPANY_NAMES),
        "stage_minutes": _stage_minutes(),
        "food_produce": [item["name"] for item in PRODUCE.values()],
        "fabricator": {category: [_item_name(item_id) for item_id in item_ids]
                       for category, item_ids in FABRICATABLE_ITEM_IDS.items()},
        "power_modes": [label for label, _ in POWER_MODES],
        "faultable": [system_name(key) for key in power_constants.FAULTABLE_SYSTEMS],
        "power": power_constants,
        "oxygen": oxygen_helper,
        "alcohol": alcohol_helper,
        "cost_multipliers": COST_MULTIPLIERS,
        "aloe_relief": ALOE_BURN_RELIEF,
        "jail": jail,
        "market_minutes": CYCLE_INTERVAL_SECONDS // 60,
        "max_pours": MAX_GLASS_POURS,
        "botany": botany_items,
        "events": random_events,
        "item_name": _item_name,
    }


@wiki.app_context_processor
def wiki_helpers():
    return {"wiki_url": page_url}


@wiki.route("/")
def index():
    return render_template("wiki/index.html", sections=WIKI_SECTIONS)


@wiki.route("/<name>")
def page(name):
    title = PAGES.get(name)
    if title is None:
        abort(404)
    is_job = title in JOBS
    return render_template(
        f"wiki/pages/{name.lower()}.html",
        title=title,
        sections=WIKI_SECTIONS,
        facts=_facts(),
        job=JOBS[title] if is_job else None,
        stations=job_stations(title) if is_job else None,
    )
