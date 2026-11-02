import copy
import random

from space_online.game.maps import donut
from space_online.game.objects.items import build_default_locker_inventory
from space_online.game.helper_methods.power_constants import default_station_power
from space_online.game.helper_methods.stock_market import (
    create_default_companies,
    default_stock_market_state,
    serialize_companies,
)
from space_online.game.helper_methods.health_bands import new_body
from space_online.game.helper_methods.npc_movement import JOB_POST_KEY, location_for_post, pick_random_hallway_location
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
        "description": "Staff Assistants are the backbone of daily station operations. They handle various tasks as needed across the station. Starting with 1000 credits.",
    },
    "Engineer": {
        "department": "Engineering",
        "subdepartment": "Engineer",
        "credits": 2500,
        "description": "Engineers are responsible for keeping the station's critical systems operational. They excel at repairing equipment and solving technical problems. Starting with 2500 credits and access to the Engineering Station.",
    },
    "Security Guard": {
        "department": "Security",
        "subdepartment": "Security",
        "credits": 5000,
        "description": "Security Guards maintain order and protect the station from threats. They have access to security systems and equipment. Starting with 5000 credits and access to the Security Station.",
    },
    "Doctor": {
        "department": "Medical",
        "subdepartment": "Doctor",
        "credits": 7500,
        "description": "Doctors provide medical care to the station's crew. They can diagnose and treat a variety of conditions. Starting with 7500 credits and access to the MedBay Station.",
    },
    "Captain": {
        "department": "Administration",
        "subdepartment": "Captain",
        "credits": 10000,
        "description": "The Captain is the highest authority on the station. They make critical decisions and coordinate all departments. Starting with 10000 credits and access to all station areas.",
    },
    "Bartender": {
        "department": "Civilian",
        "subdepartment": "Bar",
        "credits": 3500,
        "description": "Bartenders run the station's social hub, mixing drinks and providing a place for crew members to relax. They have deep knowledge of beverages and excellent social skills. Starting with 3500 credits and access to the Bar Station.",
    },
    "Head of Personnel": {
        "department": "Administration",
        "subdepartment": "HoP",
        "credits": 9000,
        "description": "The Head of Personnel (HoP) is the second-in-command of the station. They manage crew assignments, access permissions, and administrative matters. Starting with 9000 credits and access to the HoP Station, MedBay, Engineering, the Bar and the Botany Lab.",
    },
    "Botanist": {
        "department": "Civilian",
        "subdepartment": "Botany",
        "credits": 3000,
        "description": "Botanists cultivate and maintain the station's plant life. They grow food and medicinal herbs in the Botany Lab. Starting with 3000 credits and access to the Botany Station.",
    },
}

# Jobs a crew member can ask the Head of Personnel for: everything outside Administration.
REQUESTABLE_JOBS = [job for job, info in JOBS.items() if info.get("department") != "Administration"]


DEPARTMENT_ORDER = [
    "Civilian",
    "Medical",
    "Engineering",
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


SELECT_DEPARTMENT = "Select A Department"
SELECT_JOB = "Select A Job"


def get_jobs_for_department(department):
    """Return sorted job names for a department, or empty list if not found."""
    for dept, jobs in group_jobs_by_department():
        if dept == department:
            return jobs
    return []


MAX_NAME_LENGTH = 40


def _clean_record():
    """The unhurt body and clean legal record every crew member, player included, starts with."""
    return {
        **new_body(),
        "warrant": False,
        "warrant_reason": "",
        "fine_amount": 0,
        "fine_reason": "",
        "in_jail": False,
        "jail_release_at_seconds": None,
    }


def _crew_record(name, job, credits, location, *, posted):
    """Base NPC dict shared by department heads and staff assistants."""
    job_info = JOBS[job]
    record = {
        "name": name,
        "job": job,
        "department": job_info["department"],
        "subdepartment": job_info["subdepartment"],
        "credits": credits,
        "inventory": [],
        "location": location,
        "room_visit_remaining": 0,
        "npc_goal": None,
        "npc_goal_room_key": None,
        **_clean_record(),
    }
    if posted:
        record["on_duty"] = True
    return record


def _generate_station_crew(player_name, job):
    """Build the NPC crew around the player's chosen job."""
    station_crew = []
    available_names = NPC_NAMES.copy()
    if player_name in available_names:
        available_names.remove(player_name)

    def _pick_npc_name():
        npc_name = random.choice(available_names)
        available_names.remove(npc_name)
        return npc_name

    def _make_staff_assistant(npc_name):
        # Staff Assistants have no fixed post, so they start out
        # wandering the hallway ring rather than parked in quarters.
        return _crew_record(
            npc_name,
            "Staff Assistant",
            JOBS["Staff Assistant"]["credits"],
            pick_random_hallway_location(),
            posted=False,
        )

    if job == "Head of Personnel":
        # HoP always has an NPC Captain; remaining vacant head slots + 2 are Staff Assistants
        station_crew.append(
            _crew_record(_pick_npc_name(), "Captain", JOBS["Captain"]["credits"], location_for_post("Captain"),
                         posted=True)
        )
        vacant_roles = [j for j in JOB_POST_KEY if j not in (job, "Captain")]
        for _ in range(len(vacant_roles) + 2):
            station_crew.append(_make_staff_assistant(_pick_npc_name()))
        return station_crew

    for npc_job in JOB_POST_KEY:
        if npc_job == job:
            continue
        station_crew.append(
            _crew_record(_pick_npc_name(), npc_job, JOBS[npc_job]["credits"], location_for_post(npc_job), posted=True)
        )

    for _ in range(2):
        station_crew.append(_make_staff_assistant(_pick_npc_name()))
    return station_crew


def create_character(player_name, department, job):
    """Validate the creation form and return a brand-new player_data save.

    Raises ValueError with a player-facing message when the input is invalid.
    """
    player_name = (player_name or "").strip()
    if not player_name:
        raise ValueError("Please enter a character name.")
    if len(player_name) > MAX_NAME_LENGTH:
        raise ValueError(f"Character names can be at most {MAX_NAME_LENGTH} characters.")
    if not department or department == SELECT_DEPARTMENT:
        raise ValueError("Please select a department.")
    if job not in JOBS or job not in get_jobs_for_department(department):
        raise ValueError("Please select a job.")

    job_info = JOBS[job]
    station_crew = _generate_station_crew(player_name, job)

    stock_market = default_stock_market_state()
    stock_market["companies"] = serialize_companies(create_default_companies())

    # Solar ON when an NPC Engineer is present; OFF if the player is the Engineer
    station_power = default_station_power()
    station_power["solar_charging"] = job != "Engineer" and any(
        npc.get("job") == "Engineer" for npc in station_crew
    )

    player_data = {
        "name": player_name,
        "job": job,
        "department": job_info["department"],
        "subdepartment": job_info["subdepartment"],
        "inventory": [],
        "locker_inventory": build_default_locker_inventory(),
        "hands": {"left": None, "right": None},
        "credits": job_info["credits"],
        "location": dict(donut.QUARTERS_LOCATION),
        "stock_holdings": {},
        "bar_mixed_stock": {},
        "station_crew": station_crew,
        "stock_market": stock_market,
        **_clean_record(),
        "alcohol_percent": 0,
        "damage_timers": {},
        "station_power": station_power,
        "ship_map": copy.deepcopy(donut.SHIP_MAP),
        "botany": new_botany(),
        "game_clock": default_game_clock(),
        "notes": [],
    }
    return player_data
