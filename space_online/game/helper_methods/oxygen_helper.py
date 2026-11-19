"""Breathing damage: what the air each crew member breathes does to them. The limits are in station_air."""

from space_online.game.helper_methods.game_clock import format_elapsed
from space_online.game.helper_methods.station_air import AIR_LASTS_SECONDS, KEEPS_UP_LEVEL, breath_effects, breath_of
from space_online.game.maps import donut

OXYGEN_TICK_SECONDS = 15
BASE_DAMAGE_PER_TICK = 4
DOCTOR_REQUIRED_FLOOR = 25
WARNING_THRESHOLDS = (30, 60, 90)
DEATH_THRESHOLD = 100
POST_DEATH_OXYGEN = 50
POST_DEATH_LIMB_HEALTH = 20
RECOVERY_SECONDS_PER_PERCENT = 30
RICH_RECOVERY_FACTOR = 2

OXYGEN_WARNING_MESSAGES = {
    30: "You're feeling light-headed and having difficulty breathing. Oxygen levels are dropping.",
    60: "Your vision is beginning to blur and you're experiencing severe difficulty breathing. Oxygen deprivation is worsening.",
    90: "You're on the verge of losing consciousness. Severe oxygen deprivation detected. Immediate action required.",
}

OXYGEN_DEATH_TITLE = "CRITICAL: Oxygen Depleted"
OXYGEN_DEATH_MESSAGE = (
    "You have succumbed to oxygen deprivation. Emergency medical protocols have been "
    "activated, and you have been revived at minimal health levels."
)
OXYGEN_DEATH_NOTE = (
    "CRITICAL EVENT: Nearly died from oxygen deprivation. Emergency medical systems intervened."
)

LIFE_SUPPORT_DAMAGE_BEGIN_TITLE = "Life Support Warning"
LIFE_SUPPORT_DAMAGE_BEGIN_MESSAGE = (
    "The life support pumps can't keep up with the crew's breathing at this level. The air will thin out.")

OXYGEN_DEPLETION_ANNOUNCEMENT_TEXT = (
    "CRITICAL ALERT: Life support systems offline! Oxygen levels dropping to critical levels. "
    "All crew are advised to evacuate or obtain emergency oxygen supplies immediately."
)
OXYGEN_DEPLETION_MODAL_BODY = (
    "LIFE SUPPORT SYSTEMS OFFLINE!\n\n"
    "Oxygen levels dropping to critical levels.\n\n"
    "All crew are advised to evacuate or obtain emergency oxygen supplies immediately."
)
OXYGEN_DEPLETION_FOLLOWUP_TITLE = "CRITICAL SYSTEM ALERT"
OXYGEN_DEPLETION_FOLLOWUP_MESSAGE = (
    "STATION ALERT: Life support systems have been deactivated!\n\n"
    f"The air will last about {format_elapsed(AIR_LASTS_SECONDS)} before it starts to harm the crew unless life "
    "support is turned on."
)


def damage_for_tick(timers, key, severity, elapsed_seconds):
    """Whole points of damage for the elapsed interval, scaled from 1x at the edge of a limit (severity 0) to 2x at
    its worst (severity 1). The fraction left over carries into the next tick in timers[key], so short ticks still
    add up."""
    damage = timers.get(key, 0.0) + BASE_DAMAGE_PER_TICK * (1 + severity) * max(
        elapsed_seconds / float(OXYGEN_TICK_SECONDS), 0)
    whole = int(damage)
    timers[key] = damage - whole
    return whole


def recovery_for_tick(timers, elapsed_seconds):
    """Whole % of oxygen damage that wears off over the elapsed interval, carrying the fraction over."""
    recovery_acc = timers.get("oxygen_recovery_acc", 0.0) + elapsed_seconds / float(RECOVERY_SECONDS_PER_PERCENT)
    recovery_amount = int(recovery_acc)
    timers["oxygen_recovery_acc"] = recovery_acc - recovery_amount
    return recovery_amount


def recovery_floor_for(current_oxygen_damage):
    """Passive recovery floor: doctor required at/above 25%, else recover to 0."""
    return DOCTOR_REQUIRED_FLOOR if current_oxygen_damage >= DOCTOR_REQUIRED_FLOOR else 0


def life_support_entering_damage_range(previous, new):
    """True when life support drops from a level whose pumps keep up with the crew to one whose pumps don't."""
    return new < KEEPS_UP_LEVEL <= previous


def apply_oxygen_tick(player_data, station_crew, elapsed_seconds):
    """Apply what each crew member's breath does to them for one master clock tick: oxygen damage past the Oxygen,
    Carbon Dioxide or pressure limit, poison damage past the Plasma limit, and otherwise oxygen recovery, faster in
    Oxygen-rich air.

    Returns player-facing events for UI: ``{"crossed_warnings": [...], "died": bool}``.
    """
    events = {"crossed_warnings": [], "died": False}
    for member in [player_data, *station_crew]:
        effects = breath_effects(breath_of(player_data, member))
        timers = member["damage_timers"]
        damage = member["damage"]
        if effects["poison"] is not None:
            damage["poison"] = min(DEATH_THRESHOLD, damage["poison"] + damage_for_tick(
                timers, "poison_damage_acc", effects["poison"], elapsed_seconds))

        current_oxygen_damage = int(damage["oxygen"])
        if effects["oxygen"] is not None:
            new_oxygen_damage = min(DEATH_THRESHOLD, current_oxygen_damage + damage_for_tick(
                timers, "oxygen_damage_acc", effects["oxygen"], elapsed_seconds))
            damage["oxygen"] = new_oxygen_damage
            if member is player_data:
                events["crossed_warnings"] = [threshold for threshold in WARNING_THRESHOLDS
                                              if current_oxygen_damage < threshold <= new_oxygen_damage]
                events["died"] = new_oxygen_damage >= DEATH_THRESHOLD
            continue

        rate = RICH_RECOVERY_FACTOR if effects["rich"] else 1
        recovery_amount = recovery_for_tick(timers, elapsed_seconds * rate)
        floor = recovery_floor_for(current_oxygen_damage)
        if current_oxygen_damage > floor and recovery_amount:
            damage["oxygen"] = max(floor, current_oxygen_damage - recovery_amount)

    return events


def apply_oxygen_death_state(player_data):
    """Apply soft-death state: oxygen/limbs reset and teleport to quarters. No UI."""
    player_data["damage"]["oxygen"] = POST_DEATH_OXYGEN
    for limb in player_data["limbs"]:
        player_data["limbs"][limb] = POST_DEATH_LIMB_HEALTH
    player_data["location"] = dict(donut.QUARTERS_LOCATION)
