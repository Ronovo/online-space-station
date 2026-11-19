"""The work the NPC crew get on with by themselves, on the master clock.

Each kind of work belongs to a post, a job in a room. post_worker() says who is doing a post's work right now: its
holder while they are at the post and fit to work. When the holder is jailed, too badly hurt, or the post is empty,
the Captain covers it, and failing that the Head of Personnel covers the rooms a HoP has access to. Nobody covers a
post the player holds: that work is the player's to do.

Besides keeping the crew on their feet and the power on, that work is what fills the station stores (see stores)
and puts dishes and drinks on the menus.

player_data["crew_work"] holds {room key: game seconds at which the work of the post there is next due}.
"""

import random
from collections import Counter

from space_online.game.helper_methods import gas_mix
from space_online.game.helper_methods.artifacts import ARTIFACT_KINDS, artifact_of
from space_online.game.helper_methods.engine import (
    HOT_LIMIT,
    SAFE_SETTINGS,
    fit_lines,
    send_back_empty,
    send_fresh_canister,
    wrecked,
)
from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.hazards import HAZARDS, clear_hazard, hazard_rooms, room_hazard
from space_online.game.helper_methods.health_bands import heal_fully, is_incapacitated, overall_health
from space_online.game.helper_methods.npc_movement import (
    can_work,
    on_duty_npc_for_job,
    player_holds_post,
    post_holder,
)
from space_online.game.helper_methods.mixing import add_to_stock
from space_online.game.helper_methods.station_air import (
    RESERVOIR_LOW,
    UPKEEP_MOLES,
    contaminated,
    reservoir_share,
    reservoir_tainted,
    vent_station,
)
from space_online.game.helper_methods.stores import KITCHEN_PRODUCE, add_to_stores, take_from_stores
from space_online.game.maps.donut import (
    ATMOSPHERICS_KEY,
    BAR_KEY,
    BOTANY_KEY,
    CHEMISTRY_KEY,
    ENGINEERING_KEY,
    KITCHEN_KEY,
    MEDBAY_KEY,
    MINING_KEY,
    RESEARCH_KEY,
    ROOMS,
)
from space_online.game.objects.botany_items import (
    BOTANY_ITEMS,
    BOTANY_SEED_IDS,
    GROWTH_STAGES,
    empty_planter,
    planted_from_seed,
    refresh_planter_growth,
    water_npc_planters,
)
from space_online.game.objects.chemicals import STORE_REMEDY_IDS
from space_online.game.objects.dishes import DISHES, PANTRY_INGREDIENTS
from space_online.game.objects.drinks import BASIC_RECIPES
from space_online.game.objects.gases import AIR, ROOM_TEMP
from space_online.game.helper_methods.power_constants import system_name
from space_online.game.special_rooms.engineering import POWER_MODE_LEVELS, repair_system, set_system_level

# The jobs that stand in for a post nobody can work, in the order they are tried, with the door access that lets
# them: None is any room.
COVER_JOBS = (("Captain", None), ("Head of Personnel", "HoP"))

DOCTOR_WORK_SECONDS = 60
ENGINEER_WORK_SECONDS = 90
MINER_WORK_SECONDS = 60
BOTANIST_WORK_SECONDS = 90
CHEMISTRY_WORK_SECONDS = 120
CHEF_WORK_SECONDS = 120
BARTENDER_WORK_SECONDS = 120
RESEARCH_WORK_SECONDS = 150
ATMOSPHERICS_WORK_SECONDS = 60
ORE_PER_TURN = 2
# The chance each turn away that the Botanist pages the player about one thirsty planter.
BOTANIST_ASK_CHANCE = 0.5
# The most of any one dish or drink an NPC keeps ready on the menu.
MAX_READY = 3
TAMPERED_LIGHTS_PAGE = "Someone tampered with the hallway lighting. Check the Incident Log."


def _worker_named(worker, job):
    """How a log line names whoever did job's work: by name for one of its own, and as cover for anyone else."""
    if worker["job"] == job:
        return worker["name"]
    return f"With no {job} on duty, {worker['job']} {worker['name']}"


def post_worker(game, job, room_key):
    """The NPC doing the work of job's post in room_key right now, or None when nobody is."""
    if player_holds_post(game.player_data, job, room_key):
        return None
    crew = game.station_crew
    holder = post_holder(crew, job, room_key)
    if job != "Engineer" and room_hazard(game.player_data, room_key):
        return None
    if holder is not None and can_work(holder):
        return holder if holder["on_duty"] else None
    for cover_job, access in COVER_JOBS:
        cover = on_duty_npc_for_job(crew, cover_job)
        if cover is not None and cover_job != job and (access is None or access in ROOMS[room_key].access):
            return cover
    return None


def _treat_the_worst_hurt(game, worker):
    """The doctor puts the crew member in the worst shape back on their feet."""
    patients = [npc for npc in game.station_crew if npc is not worker and is_incapacitated(npc)]
    if not patients or not take_from_stores(game.player_data, "remedies"):
        return
    patient = min(patients, key=overall_health)
    heal_fully(patient)
    message = (f"{_worker_named(worker, 'Doctor')} treats {patient['name']} ({patient['job']}), "
               "who is fit for work again.")
    game.announce("MedBay", message)
    game.add_note(message)


def _keep_the_power_on(game, worker):
    """The engineer deals with one thing a turn: a room hazard, then a faulted system, then a solar array that is
    down, then life support that a dead battery shut off and that has power again, then the Combustion Engine's cut
    coolant line, then an engine overheating, which they shut down, then an engine that isn't running, which they
    light at the safe setting once it has a fuel and an oxidizer canister with gas in them connected, then hallway
    lighting an antagonist dimmed, which they restore and report to Security, then a nearly empty canister in the
    engine's bay, which they send back down the tube to Atmospherics."""
    power = game.player_data["station_power"]
    engine = game.player_data["engine"]
    burning = hazard_rooms(game.player_data)
    if burning:
        room_key, kind = burning[0]
        clear_hazard(game.player_data, room_key)
        message = (f"{_worker_named(worker, 'Engineer')} deals with the {HAZARDS[kind]['name']} "
                   f"in the {ROOMS[room_key].name}.")
    elif power["faults"]:
        system_key = power["faults"][0]
        repair_system(game, system_key)
        message = f"{_worker_named(worker, 'Engineer')} repairs the {system_name(system_key)}."
    elif not power["solar_charging"]:
        power["solar_charging"] = True
        message = f"{_worker_named(worker, 'Engineer')} restarts the solar array."
    elif power["system_levels"]["life_support"] == 0 and power["battery_level"] > 0:
        set_system_level(game, "life_support", POWER_MODE_LEVELS[power["power_mode"]]["life_support"])
        message = f"{_worker_named(worker, 'Engineer')} brings life support back up."
    elif engine["coolant_fault"]:
        engine["coolant_fault"] = False
        message = f"{_worker_named(worker, 'Engineer')} repairs the engine's coolant line."
    elif engine["running"] and engine["hot"] > HOT_LIMIT:
        engine["running"] = False
        message = f"{_worker_named(worker, 'Engineer')} shuts down the overheating combustion engine."
    elif not engine["running"] and not wrecked(engine) and fit_lines(engine):
        engine.update(settings=dict(SAFE_SETTINGS), running=True)
        message = f"{_worker_named(worker, 'Engineer')} lights the combustion engine."
    elif power["dimmed_from"] is not None:
        set_system_level(game, "hallway_lighting", power["dimmed_from"])
        power["dimmed_from"] = None
        message = (f"{_worker_named(worker, 'Engineer')} restores the hallway lighting and reports to Security that "
                   "someone tampered with it.")
        if game.player_data["job"] == "Security Guard":
            game.page("Engineering", TAMPERED_LIGHTS_PAGE)
    elif returned := send_back_empty(engine, game.player_data["atmos"]["canisters"]):
        message = (f"{_worker_named(worker, 'Engineer')} sends the empty {returned['label']} back down the tube to "
                   "Atmospherics.")
    else:
        return
    game.announce("Engineering", message)
    game.add_note(message)


def _send_up_ore(game, worker):
    add_to_stores(game.player_data, "iron_ore", ORE_PER_TURN)


def _send_produce(game, worker):
    """The botanist sends the kitchen one of whatever it is shortest of."""
    produce = game.player_data["stores"]["produce"]
    add_to_stores(game.player_data, min(KITCHEN_PRODUCE, key=lambda item_id: produce[KITCHEN_PRODUCE[item_id]]))


def _seed_for(item_id):
    return next(BOTANY_ITEMS[seed] for seed in BOTANY_SEED_IDS if BOTANY_ITEMS[seed]["attributes"]["produces"] == item_id)


def _tend_the_planters(game, worker):
    """The botanist keeps the planters they planted going. Turns come at least twice a stage, so a plant tended on
    every turn never misses a watering. Each turn clears dead plants, harvests mature ones into the kitchen's
    produce, plants one empty planter with the seed for the produce the kitchen is shortest of (counting what is
    already growing, crops before the slower fruit and trees), and waters every plant."""
    elapsed = get_elapsed_seconds(game.player_data)
    produce = game.player_data["stores"]["produce"]
    planters = game.player_data["botany"]["planters"]
    for index, planter in enumerate(planters):
        if planter["tended_by"] != "npc":
            continue
        refresh_planter_growth(planter, elapsed)
        if planter["dead"]:
            planters[index] = empty_planter()
        elif planter["growth_stage"] >= GROWTH_STAGES:
            add_to_stores(game.player_data, planter["produces"], planter["yield_multiplier"])
            planters[index] = empty_planter()

    growing = Counter(planter["produces"] for planter in planters if planter["tended_by"] == "npc")
    empty = next((planter for planter in planters if not planter["occupied"]), None)
    if empty is not None:
        seeds = {item_id: _seed_for(item_id) for item_id in KITCHEN_PRODUCE}
        wanted = min(seeds, key=lambda item_id: (produce[KITCHEN_PRODUCE[item_id]] + growing[item_id],
                                                 seeds[item_id]["attributes"]["growth_class"] != "crop"))
        empty.update(planted_from_seed(seeds[wanted], elapsed), tended_by="npc")
    water_npc_planters(game.player_data, elapsed)


def _ask_for_water(game):
    """The botanist is away: maybe page the player once about each thirsty planter they left."""
    elapsed = get_elapsed_seconds(game.player_data)
    for index, planter in enumerate(game.player_data["botany"]["planters"]):
        stage = refresh_planter_growth(planter, elapsed)
        thirsty = (planter["tended_by"] == "npc" and planter["occupied"] and not planter["dead"]
                   and stage < GROWTH_STAGES and not planter["watered"])
        if thirsty and planter["asked_at_stage"] != stage and random.random() < BOTANIST_ASK_CHANCE:
            planter["asked_at_stage"] = stage
            game.page("Botany", f"Could someone water planter {index + 1}? I'm away from the lab.")


def _send_a_remedy(game, worker):
    add_to_stores(game.player_data, STORE_REMEDY_IDS[0])


def _cook_a_dish(game, worker):
    """The chef cooks one dish the pantry and the produce in the stores can make, and uses that produce up."""
    produce = game.player_data["stores"]["produce"]
    stock = game.player_data["kitchen_stock"]

    def can_cook(dish):
        needs = Counter(DISHES[dish]["ingredients"])
        return stock.get(dish, 0) < MAX_READY and all(
            produce[name] >= count if name in produce else name in PANTRY_INGREDIENTS for name, count in needs.items())

    dishes = [dish for dish in DISHES if can_cook(dish)]
    if not dishes:
        return
    dish = random.choice(dishes)
    for name in DISHES[dish]["ingredients"]:
        if name in produce:
            produce[name] -= 1
    add_to_stock(stock, dish)


def _work_out_an_artifact(game, worker):
    """The scientist works out the oldest artifact on the bench and sends it off to Central Command."""
    bench = game.player_data["research"]["bench"]
    if not bench:
        return
    kind = ARTIFACT_KINDS[artifact_of(bench.pop(0))["kind"]]["name"]
    game.announce("Research Lab", f"{_worker_named(worker, 'Scientist')} has worked out an artifact from the bench: "
                                  f"a {kind}.")


def _tend_the_air(game, worker):
    """The scientist deals with one thing a turn: a reservoir with something other than air in it, which they flush
    with fresh air, then a contaminant in the station's air, which they vent, then a reservoir running low, which
    they top up, then a Combustion Engine line that is nearly empty, for which they fill a canister on the rack and send
    it down the tube."""
    atmos = game.player_data["atmos"]
    reservoir = atmos["reservoir"]
    who = _worker_named(worker, "Scientist")
    if reservoir_tainted(reservoir):
        gas_mix.take(reservoir, UPKEEP_MOLES)
        gas_mix.merge(reservoir, gas_mix.mix_of(AIR, UPKEEP_MOLES, ROOM_TEMP))
        message = f"{who} flushes the life support reservoir and refills it with fresh air."
    elif contaminated(atmos["air"]):
        vent_station(game.player_data)
        message = f"{who} vents the station's air to clear it."
    elif reservoir_share(reservoir) < RESERVOIR_LOW:
        gas_mix.merge(reservoir, gas_mix.mix_of(AIR, UPKEEP_MOLES, ROOM_TEMP))
        message = f"{who} tops up the life support reservoir with fresh air."
    elif sent := send_fresh_canister(atmos, game.player_data["engine"]):
        canister, gas = sent
        message = f"{who} fills {canister['label']} with {gas} and sends it down the tube to the Combustion Engine."
    else:
        return
    game.announce("Atmospherics", message)
    game.add_note(message)


def _mix_a_drink(game, worker):
    stock = game.player_data["bar_mixed_stock"]
    drinks = [drink for drink in BASIC_RECIPES if stock.get(drink, 0) < MAX_READY]
    if drinks:
        add_to_stock(stock, random.choice(drinks))


def _botanist_turn(game, worker):
    _send_produce(game, worker)
    _tend_the_planters(game, worker)


# (job, room key) of a post -> (seconds between turns at the work, what a turn does)
CREW_WORK = {
    ("Doctor", MEDBAY_KEY): (DOCTOR_WORK_SECONDS, _treat_the_worst_hurt),
    ("Engineer", ENGINEERING_KEY): (ENGINEER_WORK_SECONDS, _keep_the_power_on),
    ("Miner", MINING_KEY): (MINER_WORK_SECONDS, _send_up_ore),
    ("Botanist", BOTANY_KEY): (BOTANIST_WORK_SECONDS, _botanist_turn),
    ("Scientist", CHEMISTRY_KEY): (CHEMISTRY_WORK_SECONDS, _send_a_remedy),
    ("Chef", KITCHEN_KEY): (CHEF_WORK_SECONDS, _cook_a_dish),
    ("Bartender", BAR_KEY): (BARTENDER_WORK_SECONDS, _mix_a_drink),
    ("Scientist", RESEARCH_KEY): (RESEARCH_WORK_SECONDS, _work_out_an_artifact),
    ("Scientist", ATMOSPHERICS_KEY): (ATMOSPHERICS_WORK_SECONDS, _tend_the_air),
}


def next_work_in(game, job, room_key):
    """Seconds until the next turn of work at job's post in room_key, or None while nobody is doing it."""
    if post_worker(game, job, room_key) is None:
        return None
    interval, _ = CREW_WORK[(job, room_key)]
    return max(0, game.player_data["crew_work"].get(room_key, interval) - get_elapsed_seconds(game.player_data))


def tick_crew_work(game):
    """Give every post whose work is due its turn, if anyone is there to do it."""
    elapsed = get_elapsed_seconds(game.player_data)
    due_at = game.player_data["crew_work"]
    for (job, room_key), (interval, work) in CREW_WORK.items():
        if elapsed < due_at.setdefault(room_key, interval):
            continue
        due_at[room_key] = elapsed + interval
        worker = post_worker(game, job, room_key)
        if worker is not None:
            work(game, worker)
        elif job == "Botanist":
            _ask_for_water(game)
