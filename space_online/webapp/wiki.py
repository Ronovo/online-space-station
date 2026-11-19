"""Player Guide: wiki pages at /wiki/<Page_Name>, listed by section on the /wiki/ index.

The same pages, turned into markdown text, are the guide files on the player's computer and PDA.
"""

import functools
import itertools
import json
import re
from html.parser import HTMLParser

from flask import Blueprint, abort, redirect, render_template, url_for
from markupsafe import Markup, escape

from space_online.game.character_methods.character_creation import EXTRA_CREW_RANGE, JOBS
from space_online.game.helper_methods import (
    alcohol_helper,
    antagonists,
    artifacts,
    atmos,
    bombs,
    career,
    combat,
    crew_work,
    engine,
    errands,
    gas_mix,
    game_clock,
    hazards,
    jail,
    lighting_helper,
    needs,
    npc_movement,
    oxygen_helper,
    pda,
    power_constants,
    random_events,
    rounds,
    station_air,
    stock_market,
    stores,
)
from space_online.game.helper_methods.door_control import can_control_door
from space_online.game.helper_methods.health_bands import limb_label
from space_online.game.maps.donut import LOCKABLE_ROOM_KEYS, ROOMS
from space_online.game.helper_methods.stock_market import CYCLE_INTERVAL_SECONDS, DEFAULT_COMPANY_NAMES
from space_online.game.main import LOG_NEW_SECONDS, SPECIAL_ROOM_CLASSES
from space_online.game.objects import botany_items, chemicals, dishes, food, gases, mining_items, weapons
from space_online.game.special_rooms import atmospherics, bridge, cargo, kitchen, mining, quarters, research
from space_online.game.special_rooms.service_window import MAX_WINDOW_PASS
from space_online.game.objects.drinks import MAX_GLASS_POURS
from space_online.game.objects.food import PRODUCE
from space_online.game.objects.items import ALOE_BURN_RELIEF, DEFAULT_LOCKER_ITEM_IDS, get_item_definition
from space_online.game.special_rooms.engineering import (
    FABRICATABLE_ITEM_IDS,
    FABRICATION_ORE,
    POWER_MODE_LEVELS,
    POWER_MODES,
)
from space_online.game.special_rooms.med_bay import COST_MULTIPLIERS

WIKI_SECTIONS = (
    ("Basics", ("Getting Started", "Modes and Careers", "Rounds and the Shuttle", "The Station", "Items and Hands",
                "Health", "Crew")),
    ("Systems", ("Duties and Job Events", "PDA", "Station Stores", "Power", "Life Support", "Hazards", "Medical",
                 "Security and Jail", "Antagonists", "Combat and Weapons", "Stock Market", "Bar", "Kitchen", "Botany",
                 "Chemistry", "Research", "Atmospherics", "Mining", "Cargo", "Engineering", "Bridge and Personnel",
                 "Station Status")),
    ("Jobs", ("Staff Assistant", "Engineer", "Security Guard", "Doctor", "Bartender", "Chef", "Botanist", "Scientist",
              "Miner", "Quartermaster", "Head of Personnel", "Captain")),
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


def _accident_rows():
    """(event, what it does) for each bad hallway event."""
    rows = []
    for title, hurts in random_events.HALLWAY_ACCIDENTS.items():
        limb, low, high = hurts["limb"]
        parts = [f"lose {hurts['credits'][0]}-{hurts['credits'][1]} credits"] if "credits" in hurts else []
        parts.append(f"{limb_label(limb).lower() if limb else 'a limb'} {low}-{high}%")
        parts += [f"{dtype} {hurts[dtype][0]}-{hurts[dtype][1]}%" for dtype in ("burn", "poison") if dtype in hurts]
        rows.append((title, ", ".join(parts).capitalize()))
    return rows


@functools.lru_cache
def _engine_burns():
    """(fuel, oxidizer, output in % a minute) for each pairing, after ten minutes at the safe setting."""
    rows = []
    fuels, oxidizers = ([gas for gas, details in gases.GASES.items() if details["role"] == role]
                        for role in ("fuel", "oxidizer"))
    for fuel, oxidizer in itertools.product(fuels, oxidizers):
        state = engine.new_engine(running=True)
        for canister, gas in zip(state["canisters"], (fuel, oxidizer)):
            canister["mix"] = gas_mix.mix_of({gas: 1}, engine.CANISTER_MOLES, gases.ROOM_TEMP)
        for _ in range(10 * 60):
            engine.step_engine(state, 1)
        rows.append((fuel, oxidizer, engine.engine_output(state)))
    return rows


def _facts():
    """Numbers the pages quote, read from the game so the guide follows it when they change."""
    return {
        "rooms": [ROOMS[key].name for key in LOCKABLE_ROOM_KEYS],
        "locker_items": [_item_name(item_id) for item_id in DEFAULT_LOCKER_ITEM_IDS],
        "call_chance": npc_movement.NPC_CALL_SUCCESS_CHANCE,
        "npcs": npc_movement,
        "extra_crew": EXTRA_CREW_RANGE,
        "work": crew_work,
        "duties": errands,
        "clock": game_clock,
        "log_new_seconds": LOG_NEW_SECONDS,
        "needs": needs,
        "feeds": {"dish": kitchen.DISH_FEEDS, "basic": kitchen.BASIC_FEEDS},
        "rest_per_minute": quarters.REST_HEAL_PER_MINUTE,
        "shuttle_bed_per_minute": quarters.SHUTTLE_BED_HEAL_PER_MINUTE,
        "stores": stores,
        "hazards": hazards,
        "hazard_rows": [(hazard["name"].capitalize(), _item_name(hazard["tool"]),
                         hazard["damage"] or "a limb") for hazard in hazards.HAZARDS.values()],
        "hack_tools": [_item_name(item_id) for item_id in jail.DOOR_HACK_TOOL_IDS],
        "mutants": [(_item_name(plain), food.MUTANT_PRODUCE[mutant]["name"],
                     food.MUTANT_PRODUCE[mutant]["description"]) for plain, mutant in food.MUTANT_OF.items()],
        "cargo": cargo,
        "cargo_orders": [(cargo.goods_name(item), price, cargo.REQUEST_PRICES[item])
                         for item, price in cargo.QUARTERMASTER_PRICES.items()],
        "research": research,
        "artifacts": artifacts,
        "gases": gases,
        "gas_mix": gas_mix,
        "atmos": atmos,
        "bombs": bombs,
        "atmospherics": atmospherics,
        "fabrication_ore": {_item_name(item_id): ore for item_id, ore in FABRICATION_ORE.items()},
        "company_count": len(DEFAULT_COMPANY_NAMES),
        "stage_minutes": _stage_minutes(),
        "food_produce": [item["name"] for item in PRODUCE.values()],
        "export_produce": [_item_name(produce) for produce in
                           (botany_items.BOTANY_ITEMS[seed_id]["attributes"]["produces"]
                            for seed_id in botany_items.BOTANY_SEED_IDS)
                           if cargo.EXPORT_VALUES.get(produce) == cargo.PRODUCE_EXPORT_VALUE],
        "fabricator": {category: [_item_name(item_id) for item_id in item_ids]
                       for category, item_ids in FABRICATABLE_ITEM_IDS.items()},
        "power_modes": [label for label, _ in POWER_MODES],
        "faultable": [power_constants.system_name(key) for key in power_constants.FAULTABLE_SYSTEMS],
        "power": power_constants,
        "mode_draws": [(label, power_constants.calculate_discharge(POWER_MODE_LEVELS[mode], 60))
                       for label, mode in POWER_MODES],
        "engine": engine,
        "engine_burns": _engine_burns(),
        "lighting": lighting_helper,
        "oxygen": oxygen_helper,
        "air": station_air,
        "alcohol": alcohol_helper,
        "cost_multipliers": COST_MULTIPLIERS,
        "aloe_relief": ALOE_BURN_RELIEF,
        "jail": jail,
        "market_minutes": CYCLE_INTERVAL_SECONDS // 60,
        "market": stock_market,
        "max_pours": MAX_GLASS_POURS,
        "dishes": dishes,
        "window_max": MAX_WINDOW_PASS,
        "chemicals": chemicals,
        "processor": sorted({(_item_name(item_id), _item_name(result))
                             for item_id, result in chemicals.PROCESSOR_RESULTS.items()}),
        "mining": mining_items,
        "mining_bay": mining,
        "ore_values": [(_item_name(ore_id), value) for ore_id, value in mining_items.ORE_VALUES.items()],
        "combat": combat,
        "weapons": [(item["name"], item["attributes"]["attack"]) for item in weapons.WEAPON_ITEMS.values()
                    if "attack" in item["attributes"]],
        "armory": [_item_name(item_id) for item_id in weapons.ARMORY_ITEM_IDS],
        "career": career,
        "start_credits": JOBS[career.START_JOB]["credits"],
        "ladder": [(job, career.job_salary(job))
                   for job in (career.START_JOB, *career.REGULAR_JOBS, career.HEAD_JOB, career.TOP_JOB)],
        "rounds": rounds,
        "bridge": bridge,
        "threats": antagonists,
        "botany": botany_items,
        "events": random_events,
        "accidents": _accident_rows(),
        "pda": pda,
        "surface_ores": len(mining_items.SURFACE_ORES),
        "item_name": _item_name,
    }


def _render_page(name, title):
    is_job = title in JOBS
    return render_template(
        f"wiki/pages/{name.lower()}.html",
        title=title,
        sections=WIKI_SECTIONS,
        facts=_facts(),
        job=JOBS[title] if is_job else None,
        salary=career.job_salary(title) if is_job else None,
        stations=job_stations(title) if is_job else None,
    )


class _Markdown(HTMLParser):
    """Turns a rendered wiki page's article into markdown text: headings, paragraphs, lists, bold, tables, and links
    to other pages as links to their guide files."""

    BLOCKS = {"h1": "# {}", "h2": "## {}", "h3": "### {}", "p": "{}", "li": "- {}", "dt": "**{}**", "dd": "{}"}
    INLINE = {"b": "**", "strong": "**", "i": "*", "em": "*"}
    SKIPPED_CLASSES = ("wiki-crumb",)
    PAGE_LINK = re.compile(r"/wiki/([^/?#]+)")

    def __init__(self):
        super().__init__()
        self.lines = []
        self.text = []
        self.cells = None
        self.header_row = False
        self.in_article = False
        self.skipping = None
        self.link = None

    def _flush(self, pattern="{}"):
        text = " ".join("".join(self.text).split())
        self.text = []
        if text:
            self.lines.append(pattern.format(text))

    def handle_starttag(self, tag, attrs):
        if tag == "article":
            self.in_article = True
        elif dict(attrs).get("class") in self.SKIPPED_CLASSES:
            self.skipping = tag
        elif tag in self.BLOCKS:
            self._flush()
        elif tag == "tr":
            self.cells, self.header_row = [], False
        elif tag in self.INLINE:
            self.text.append(self.INLINE[tag])
        elif tag == "a" and self.in_article and not self.skipping:
            page = self.PAGE_LINK.fullmatch(dict(attrs).get("href", ""))
            self.link = page and PAGES.get(page[1])
            if self.link:
                self.text.append("[")

    def handle_endtag(self, tag):
        if tag == self.skipping:
            self.skipping = None
            self.text = []
        elif tag == "article":
            self.in_article = False
        elif tag in self.BLOCKS:
            self._flush(self.BLOCKS[tag])
        elif tag in ("td", "th"):
            self.cells.append(" ".join("".join(self.text).split()))
            self.text = []
            self.header_row = self.header_row or tag == "th"
        elif tag == "tr":
            self.lines.append("| " + " | ".join(self.cells) + " |")
            if self.header_row:
                self.lines.append("|" + " --- |" * len(self.cells))
        elif tag in self.INLINE:
            self.text.append(self.INLINE[tag])
        elif tag == "a" and self.link:
            self.text.append(f"]({self.link}.md)")
            self.link = None

    def handle_data(self, data):
        if self.in_article and not self.skipping:
            self.text.append(data)

    def markdown(self):
        """The lines as one text: list items and table rows stay together, everything else gets a blank line."""
        text = ""
        for previous, line in zip([""] + self.lines, self.lines):
            together = line[0] == previous[:1] and line[0] in "-|"
            text += ("\n" if together else "\n\n") + line
        return text.strip() + "\n"


@functools.lru_cache
def file_text(title):
    """A wiki page as the markdown text of its guide file. The pages only quote the game's code, so the text
    holds for as long as the app runs."""
    parser = _Markdown()
    parser.feed(_render_page(page_slug(title), title))
    return parser.markdown()


HEADING = re.compile(r"(#{1,3}) (.*)")
EMPHASIS = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*")
LINK = re.compile(r"\[([^\]]+)\]\(([^()]+\.md)\)")
TABLE_RULE = re.compile(r":?-{3,}:?")


def _line_kind(line):
    if not line:
        return "blank"
    if HEADING.fullmatch(line):
        return "heading"
    if line.startswith("- "):
        return "list"
    return "table" if line.startswith("|") else "text"


def _link(label, name, links):
    """A link to the guide file name, which opens it when it is one of links, and otherwise just its label."""
    if name not in links:
        return label
    args = escape(json.dumps({"name": name}))
    return (f'<button type="button" class="link-button" data-action="panel.follow" '
            f"data-args='{args}'>{label}</button>")


def _inline(text, links):
    html = EMPHASIS.sub(lambda match: f"<b>{match[1]}</b>" if match[1] is not None else f"<i>{match[2]}</i>",
                        str(escape(text)))
    return LINK.sub(lambda match: _link(match[1], Markup(match[2]).unescape(), links), html)


def _table(lines, links):
    """Table lines as a table, its first row the header when the second is the | --- | rule under it."""
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
    head = len(rows) > 1 and all(TABLE_RULE.fullmatch(cell) for cell in rows[1])
    html = ""
    if head:
        html += "<thead><tr>" + "".join(f"<th>{_inline(cell, links)}</th>" for cell in rows[0]) + "</tr></thead>"
        rows = rows[2:]
    html += "<tbody>" + "".join("<tr>" + "".join(f"<td>{_inline(cell, links)}</td>" for cell in row) + "</tr>"
                                for row in rows) + "</tbody>"
    return f'<table class="wiki-table">{html}</table>'


def render_markdown(text, links=()):
    """Markdown text as HTML: the headings, paragraphs, lists, bold, italic, tables and links that guide files hold.
    A link to one of the file names in links opens that file. The text is escaped first, so any HTML in it shows as
    text."""
    html = []
    for kind, group in itertools.groupby((line.strip() for line in text.splitlines()), _line_kind):
        lines = list(group)
        if kind == "heading":
            for line in lines:
                hashes, title = HEADING.fullmatch(line).groups()
                html.append(f"<h{len(hashes)}>{_inline(title, links)}</h{len(hashes)}>")
        elif kind == "list":
            html.append("<ul>" + "".join(f"<li>{_inline(line[2:], links)}</li>" for line in lines) + "</ul>")
        elif kind == "table":
            html.append(_table(lines, links))
        elif kind == "text":
            html.append(f"<p>{_inline(' '.join(lines), links)}</p>")
    return Markup("\n".join(html))


@wiki.app_context_processor
def wiki_helpers():
    return {"wiki_url": page_url, "wiki_file_text": file_text, "render_markdown": render_markdown}


@wiki.route("/")
def index():
    return render_template("wiki/index.html", sections=WIKI_SECTIONS)


def _title_for(name):
    """The page a URL name means: an exact slug, the same ignoring case and hyphens, or else the one page whose slug
    starts with it. None when there is no such page or more than one."""
    wanted = name.replace("-", "_").lower()
    exact = PAGES.get(name) or next((title for slug, title in PAGES.items() if slug.lower() == wanted), None)
    if exact is not None:
        return exact
    starting = [title for slug, title in PAGES.items() if slug.lower().startswith(wanted)]
    return starting[0] if len(starting) == 1 else None


@wiki.route("/<name>")
def page(name):
    title = _title_for(name)
    if title is None:
        abort(404)
    if name != page_slug(title):
        return redirect(page_url(title))
    return _render_page(name, title)
