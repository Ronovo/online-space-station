import copy
import random

from space_online.game.maps import donut
from space_online.game.objects.items import PDA_ID, build_default_locker_inventory, get_item_definition
from space_online.game.helper_methods.power_constants import default_station_power
from space_online.game.helper_methods.artifacts import new_research
from space_online.game.helper_methods.atmos import new_atmos
from space_online.game.helper_methods.engine import new_engine
from space_online.game.helper_methods.stores import new_cargo, new_stores
from space_online.game.helper_methods.stock_market import (
    create_default_companies,
    default_stock_market_state,
    generate_news,
    serialize_companies,
)
from space_online.game.helper_methods.antagonists import new_threats
from space_online.game.helper_methods.rounds import PEACEFUL, new_round
from space_online.game.helper_methods.window_stock import new_service_window
from space_online.game.objects.mining_items import new_mining
from space_online.game.helper_methods.hazards import new_hazards
from space_online.game.helper_methods.health_bands import new_body
from space_online.game.helper_methods.needs import new_needs
from space_online.game.helper_methods.pda import new_pda
from space_online.game.helper_methods.npc_movement import (
    JOB_POSTS,
    POSTS,
    pick_random_hallway_location,
    player_holds_post,
)
from space_online.game.helper_methods.game_clock import default_game_clock
from space_online.game.objects.botany_items import new_botany

NPC_NAMES = [
    "Alex Chen", "Morgan Yu", "Sarah Connor", "John Shepard", "Ellen Ripley",
    "Isaac Clarke", "Samantha Carter", "Jean-Luc Picard", "Nyota Uhura", "Malcolm Reynolds",
    "River Tam", "Kaidan Alenko", "Liara T'Soni", "James Holden", "Naomi Nagata",
    "Amos Burton", "Alex Kamal", "Camina Drummer", "Julie Mao", "Joe Miller",
    "Kara Thrace", "William Adama", "Laura Roslin", "Gaius Baltar", "Sharon Valerii",
    "David Bowman", "Frank Poole", "Chris Hadfield", "Valentina Tereshkova", "Yuri Gagarin",
    "Sally Ride", "Neil Armstrong", "Mae Jemison", "Buzz Aldrin", "Alan Shepard",
    "Jim Lovell", "John Glenn", "Peggy Whitson", "Scott Kelly", "Christina Koch",
    "Anne McClain", "Jessica Meir", "Sunita Williams", "Mark Kelly", "Michael Collins",
    "Helen Sharman", "Tim Peake", "Andreas Mogensen", "Thomas Pesquet", "Samantha Cristoforetti"
]

JOBS = {
    "Staff Assistant": {
        "department": "Civilian",
        "subdepartment": "Assistant",
        "credits": 1000,
        "description": "Staff Assistants are the backbone of daily station operations. They handle various tasks as needed across the station.",
    },
    "Engineer": {
        "department": "Engineering",
        "subdepartment": "Engineer",
        "credits": 2500,
        "description": "Engineers are responsible for keeping the station's critical systems operational. They excel at repairing equipment and solving technical problems. They have access to the Engineering Station.",
    },
    "Security Guard": {
        "department": "Security",
        "subdepartment": "Security",
        "credits": 5000,
        "description": "Security Guards maintain order and protect the station from threats. They carry a stun baton and handcuffs from the armory, and have access to the Security Station.",
    },
    "Doctor": {
        "department": "Medical",
        "subdepartment": "Doctor",
        "credits": 7500,
        "description": "Doctors provide medical care to the station's crew. They can diagnose and treat a variety of conditions. They have access to the MedBay Station.",
    },
    "Captain": {
        "department": "Administration",
        "subdepartment": "Captain",
        "credits": 10000,
        "description": "The Captain is the highest authority on the station. They make critical decisions, coordinate all departments, and are the only one who can call the crew shuttle. They have access to all station areas.",
    },
    "Bartender": {
        "department": "Civilian",
        "subdepartment": "Bar",
        "credits": 1500,
        "description": "Bartenders run the station's social hub, mixing drinks and providing a place for crew members to relax. They have deep knowledge of beverages and excellent social skills. They have access to the Bar Station.",
    },
    "Head of Personnel": {
        "department": "Administration",
        "subdepartment": "HoP",
        "credits": 9000,
        "description": "The Head of Personnel (HoP) is the second-in-command of the station. They manage crew assignments, access permissions, and administrative matters. They have access to the HoP Station, MedBay, Engineering, the Bar, the Kitchen, the Botany Lab, Atmospherics, the Chemistry Lab, the Research Lab, the Mining Bay and the Cargo Bay.",
    },
    "Chef": {
        "department": "Civilian",
        "subdepartment": "Kitchen",
        "credits": 2000,
        "description": "Chefs feed the station. They cook dishes from the pantry, serve the crew's food orders, and trade ingredients with the Bartender through the service window. They have access to the Chef Station.",
    },
    "Scientist": {
        "department": "Science",
        "subdepartment": "Science",
        "credits": 4500,
        "description": "Scientists work the station's science labs, posted to one of them each shift. They mix compounds at the chemical dispenser in the Chemistry Lab, work out what alien artifacts do on the test rigs of the Research Lab, run the teleporter once they have cracked its calibration, and fill, heat and burn gases in Atmospherics. They have access to every science station.",
    },
    "Miner": {
        "department": "Supply",
        "subdepartment": "Mining",
        "credits": 3000,
        "description": "Miners bring ore aboard, from rocks the magnet pulls in or from shuttle trips down to the planet below, where the ore is better and the wildlife is not friendly. They have access to the Miner Station.",
    },
    "Quartermaster": {
        "department": "Supply",
        "subdepartment": "Cargo",
        "credits": 3500,
        "description": "Quartermasters keep the station supplied. They order supplies up from Central Command, sell them over the counter, and buy the station's ore, produce and artifacts for export. They have access to the Cargo Station.",
    },
    "Botanist": {
        "department": "Civilian",
        "subdepartment": "Botany",
        "credits": 2500,
        "description": "Botanists cultivate and maintain the station's plant life. They grow food and medicinal herbs in the Botany Lab. They have access to the Botany Station.",
    },
}

# Jobs a crew member can ask the Head of Personnel for: everything outside Administration.
REQUESTABLE_JOBS = [job for job, info in JOBS.items() if info.get("department") != "Administration"]


DEPARTMENT_ORDER = [
    "Civilian",
    "Medical",
    "Science",
    "Engineering",
    "Supply",
    "Security",
    "Administration",
]


def group_jobs_by_department():
    """Group jobs by department, sorted by DEPARTMENT_ORDER with credits ascending within each."""
    by_dept = {}
    for job_name, job_info in JOBS.items():
        by_dept.setdefault(job_info["department"], []).append((job_name, job_info["credits"]))
    order = [dept for dept in DEPARTMENT_ORDER if dept in by_dept] + sorted(set(by_dept) - set(DEPARTMENT_ORDER))
    return [(dept, [job_name for job_name, _ in sorted(by_dept[dept], key=lambda x: x[1])]) for dept in order]


MAX_NAME_LENGTH = 40
# How many extra crew a shift gets on top of one holder per post, and the jobs there is only ever one of.
EXTRA_CREW_RANGE = (2, 3)
UNIQUE_JOBS = ("Captain", "Head of Personnel")
# The files a new career or round starts with on the player's computer.
STARTING_FILES = {"home/home.md": """# Home

This file is yours. Edit it at the computer in your quarters, and read it on your PDA. Any file whose name ends in \
.md is shown formatted, like this one.

## Formatting

- A line starting with one, two or three # signs and a space is a heading.
- A line starting with a hyphen and a space is a list item, like this one.
- Two stars on each side make text **bold**, and one star makes it *italic*.
- A blank line starts a new paragraph.
- [PDA](PDA.md) links to another guide file. Edit this file to see how it's written.

## A table

| Shift | Job | Notes |
| --- | --- | --- |
| 1 | Staff Assistant | Learned my way around. |
"""}


def _clean_record():
    """The unhurt, awake body and clean legal record every crew member, player included, starts with."""
    return {
        **new_body(),
        "warrant": False,
        "warrant_reason": "",
        "warrant_by_player": False,
        "fine_amount": 0,
        "fine_reason": "",
        "in_jail": False,
        "jail_release_at_seconds": None,
        "asleep": False,
        "damage_timers": {},
    }


def _crew_record(name, job, *, post_key=None, roams=False):
    """An NPC in job: on duty at their post in the room post_key, or out in the hallways with no post. roams marks
    one of the shift's extra crew, who share a job with a post holder but spend the shift on the move."""
    job_info = JOBS[job]
    record = {
        "name": name,
        "job": job,
        "department": job_info["department"],
        "subdepartment": job_info["subdepartment"],
        "credits": job_info["credits"],
        "inventory": [],
        "location": donut.location_from_key(post_key) if post_key else pick_random_hallway_location(),
        "post_key": post_key,
        "room_visit_remaining": 0,
        "stroll_remaining": 0,
        "npc_goal": None,
        "npc_goal_room_key": None,
        **_clean_record(),
    }
    if post_key:
        record["on_duty"] = True
    if roams:
        record["roams"] = True
    return record


def _generate_station_crew(player_name, job, post_key):
    """Build the NPC crew around the player's chosen job and post: a holder for every post the player doesn't hold,
    two Staff Assistants, and EXTRA_CREW_RANGE more crew in jobs picked at random who roam the station.

    A Head of Personnel gets a Captain and a pool of Staff Assistants to hand the other jobs out to instead.
    """
    available_names = [name for name in NPC_NAMES if name != player_name]
    random.shuffle(available_names)
    extras = random.randint(*EXTRA_CREW_RANGE)

    if job == "Head of Personnel":
        vacant = [npc_job for npc_job, _ in POSTS if npc_job not in (job, "Captain")]
        captain = _crew_record(available_names.pop(), "Captain", post_key=JOB_POSTS["Captain"][0])
        return [captain] + [_crew_record(available_names.pop(), "Staff Assistant")
                            for _ in range(len(vacant) + 2 + extras)]

    player = {"job": job, "post_key": post_key}
    crew = [_crew_record(available_names.pop(), npc_job, post_key=room_key) for npc_job, room_key in POSTS
            if not player_holds_post(player, npc_job, room_key)]
    crew += [_crew_record(available_names.pop(), "Staff Assistant") for _ in range(2)]
    extra_jobs = [npc_job for npc_job in JOB_POSTS if npc_job not in (job, *UNIQUE_JOBS)]
    crew += [_crew_record(available_names.pop(), random.choice(extra_jobs), roams=True) for _ in range(extras)]
    return crew


def clean_name(player_name):
    """A character name with its outer spaces gone. Raises ValueError with a player-facing message if it won't do."""
    player_name = (player_name or "").strip()
    if not player_name:
        raise ValueError("Please enter a character name.")
    if len(player_name) > MAX_NAME_LENGTH:
        raise ValueError(f"Character names can be at most {MAX_NAME_LENGTH} characters.")
    return player_name


def _player_post(job):
    """The room the player is posted to for the shift: one of job's posts picked at random when it has more than
    one, else None."""
    rooms = JOB_POSTS.get(job, ())
    return random.choice(rooms) if len(rooms) > 1 else None


def new_shift(player_name, job, mode=PEACEFUL, credits=None):
    """Return the player_data for a fresh round: a new station, crew and locker for player_name in job.

    credits is what the player arrives with, the job's starting credits unless a career brings its own.
    Raises ValueError with a player-facing message when the name or job is invalid.
    """
    player_name = clean_name(player_name)
    if job not in JOBS:
        raise ValueError("Please select a job.")

    job_info = JOBS[job]
    post_key = _player_post(job)
    station_crew = _generate_station_crew(player_name, job, post_key)

    companies = create_default_companies()
    stock_market = default_stock_market_state()
    stock_market["companies"] = serialize_companies(companies)
    stock_market["news"] = generate_news(companies)

    station_power = default_station_power()
    npc_engineer = job != "Engineer" and any(npc.get("job") == "Engineer" for npc in station_crew)
    station_power["solar_charging"] = npc_engineer

    player_data = {
        "name": player_name,
        "job": job,
        "department": job_info["department"],
        "subdepartment": job_info["subdepartment"],
        "post_key": post_key,
        "inventory": [get_item_definition(PDA_ID)],
        "locker_inventory": build_default_locker_inventory(),
        "hands": {"left": None, "right": None},
        "credits": job_info["credits"] if credits is None else credits,
        "location": dict(donut.QUARTERS_LOCATION),
        "stock_holdings": {},
        "bar_mixed_stock": {},
        "kitchen_stock": {},
        "service_window": new_service_window(),
        "mining": new_mining(),
        "station_crew": station_crew,
        "stock_market": stock_market,
        **_clean_record(),
        "alcohol_percent": 0,
        "resting": False,
        "needs": new_needs(),
        "floor": {},
        "station_power": station_power,
        "ship_map": copy.deepcopy(donut.SHIP_MAP),
        "botany": new_botany(),
        "game_clock": default_game_clock(),
        "notes": [],
        "log": [{"at": 0, "title": "Your Post", "kind": "info",
                 "text": f"You are posted to the {donut.ROOMS[post_key].name} this shift."}] if post_key else [],
        "crew_work": {},
        "stores": new_stores(),
        "hazards": new_hazards(),
        "cargo": new_cargo(),
        "research": new_research(),
        "atmos": new_atmos(),
        "engine": new_engine(running=npc_engineer),
        "round": new_round(mode, job),
        "duties": [],
        "pda": new_pda(),
        "files": dict(STARTING_FILES),
        "threats": new_threats(mode, station_crew),
        "incidents": [],
        "fight": None,
    }
    return player_data
