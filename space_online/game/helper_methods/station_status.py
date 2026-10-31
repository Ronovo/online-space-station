"""Captain's Station Status: aggregate live station data for the briefing panel."""

from space_online.game.helper_methods.health_bands import health_band, overall_health
from space_online.game.helper_methods.door_control import SPECIAL_ROOM_DOORS
from space_online.game.helper_methods.game_clock import format_elapsed, get_elapsed_seconds
from space_online.game.helper_methods.npc_movement import has_post
from space_online.game.helper_methods.oxygen_helper import DAMAGE_THRESHOLD_LEVEL, WARNING_THRESHOLDS
from space_online.game.helper_methods.power_constants import BATTERY_BAND_COLORS, battery_band
from space_online.game.helper_methods.ui_panels import register_panel
from space_online.game.maps import donut
from space_online.game.objects.botany_items import GROWTH_STAGES, refresh_all_planters_growth

OXYGEN_STRESS_THRESHOLD = WARNING_THRESHOLDS[0]

SYSTEM_DISPLAY = (
    ("life_support", "Life Support"),
    ("hallway_lighting", "Hallway Lighting"),
    ("security_systems", "Security Systems"),
    ("communication_array", "Comm Array"),
)

OVERALL_COLORS = {
    "NOMINAL": "#00FF00",
    "CAUTION": "#FFFF00",
    "CRITICAL": "#FF0000",
}


def crew_health_status(member):
    """(Healthy / Injured / Critical, colour) for a crew member's overall health."""
    return health_band(overall_health(member))


def _is_on_duty(member):
    """Posted NPCs use on_duty; others count as on duty unless jailed."""
    if member.get("in_jail"):
        return False
    if has_post(member):
        return bool(member.get("on_duty", True))
    return True


def collect_station_status(player_data, station_crew):
    """Aggregate captain-facing station metrics into a single status dict."""
    power = player_data["station_power"]
    system_levels = power["system_levels"]
    battery_level = float(power.get("battery_level", 0) or 0)
    life_support = int(system_levels.get("life_support", 0) or 0)
    band = battery_band(battery_level)

    if life_support <= 0:
        oxygen_threat = "emergency"
    elif life_support <= DAMAGE_THRESHOLD_LEVEL:
        oxygen_threat = "damaging"
    else:
        oxygen_threat = "safe"

    systems = []
    for key, label in SYSTEM_DISPLAY:
        level = int(system_levels.get(key, 0) or 0)
        online = level > 0
        systems.append(
            {
                "name": label,
                "level": level,
                "status": "Online" if online else "Offline",
                "status_color": "#00FF00" if online else "#FF0000",
            }
        )

    all_crew = [player_data] + list(station_crew)
    healthy = injured = critical = oxygen_stress = on_duty = away = 0
    for member in all_crew:
        status = crew_health_status(member)[0]
        if status == "Healthy":
            healthy += 1
        elif status == "Injured":
            injured += 1
        else:
            critical += 1
        if member["damage"]["oxygen"] >= OXYGEN_STRESS_THRESHOLD:
            oxygen_stress += 1
        if _is_on_duty(member):
            on_duty += 1
        else:
            away += 1

    wanted_details = []
    jailed_details = []
    fine_details = []
    for member in all_crew:
        name = member.get("name", "Unknown")
        if member.get("warrant"):
            reason = member.get("warrant_reason") or "unknown"
            wanted_details.append({"name": name, "reason": reason, "kind": "wanted"})
        if member.get("in_jail"):
            reason = member.get("warrant_reason") or member.get("fine_reason") or "detained"
            jailed_details.append({"name": name, "reason": reason, "kind": "jailed"})
        fine_amount = member.get("fine_amount") or 0
        if fine_amount:
            reason = member.get("fine_reason") or "unpaid fine"
            fine_details.append(
                {
                    "name": name,
                    "reason": f"{reason} ({fine_amount:.0f} cr)",
                    "kind": "fine",
                }
            )

    security_details = wanted_details + jailed_details + fine_details
    security_online = int(system_levels.get("security_systems", 0) or 0) > 0

    ship_map = player_data.get("ship_map") or donut.SHIP_MAP
    locked_rooms = []
    for door_key, door_info in SPECIAL_ROOM_DOORS.items():
        tile = ship_map.get(door_key) or {}
        if tile.get("locked"):
            locked_rooms.append(door_info["room_name"])

    elapsed_seconds = get_elapsed_seconds(player_data)
    planters = refresh_all_planters_growth(player_data, elapsed_seconds)
    botany_total = len(planters)
    botany_occupied = sum(1 for p in planters if p["occupied"])
    botany_mature = sum(1 for p in planters if p["occupied"] and p["growth_stage"] >= GROWTH_STAGES)

    market = player_data["stock_market"]
    cycle_number = market["cycle_number"]

    announcements = player_data.get("announcements") or []
    emergency_announcements = [a for a in announcements if a.get("type") == "emergency"]

    alerts = []
    if oxygen_threat == "emergency":
        alerts.append({"text": "Life Support offline: oxygen emergency active", "severity": "critical"})
    elif oxygen_threat == "damaging":
        alerts.append({"text": f"Life Support degraded (Lv {life_support}): oxygen damage active", "severity": "caution"})

    if band in ("outage", "critical"):
        alerts.append({"text": f"Battery critical ({battery_level:.0f}%)", "severity": "critical"})
    elif band == "low":
        alerts.append({"text": f"Battery low ({battery_level:.0f}%)", "severity": "caution"})

    if critical > 0:
        alerts.append(
            {
                "text": f"{critical} crew in critical condition",
                "severity": "critical",
            }
        )
    elif injured > 0:
        alerts.append(
            {
                "text": f"{injured} crew injured",
                "severity": "caution",
            }
        )

    if oxygen_stress > 0:
        alerts.append(
            {
                "text": f"Oxygen stress affecting {oxygen_stress} crew",
                "severity": "caution" if oxygen_threat != "emergency" else "critical",
            }
        )

    for ann in emergency_announcements:
        text = ann.get("text") or "Emergency announcement active"
        if not any(a["text"] == text for a in alerts):
            alerts.append({"text": text, "severity": "critical"})

    if wanted_details:
        alerts.append(
            {
                "text": f"{len(wanted_details)} wanted crew on station",
                "severity": "caution",
            }
        )
    if jailed_details:
        alerts.append(
            {
                "text": f"{len(jailed_details)} crew currently jailed",
                "severity": "caution",
            }
        )
    if locked_rooms:
        alerts.append(
            {
                "text": f"Locked rooms: {', '.join(locked_rooms)}",
                "severity": "caution",
            }
        )

    access_request = player_data.get("access_request")
    if access_request and access_request.get("requested_job"):
        requester = access_request.get("requester_name") or "Unknown"
        job = access_request.get("requested_job")
        alerts.append(
            {
                "text": f"Pending access request: {requester} → {job}",
                "severity": "caution",
            }
        )

    overall = "NOMINAL"
    if (
        band in ("outage", "critical")
        or oxygen_threat == "emergency"
        or critical > 0
        or emergency_announcements
    ):
        overall = "CRITICAL"
    elif (
        band == "low"
        or oxygen_threat == "damaging"
        or injured > 0
        or fine_details
        or locked_rooms
        or wanted_details
        or jailed_details
        or access_request
    ):
        overall = "CAUTION"

    return {
        "elapsed_seconds": elapsed_seconds,
        "elapsed_display": format_elapsed(elapsed_seconds),
        "cycle_number": cycle_number,
        "overall": overall,
        "overall_color": OVERALL_COLORS[overall],
        "alerts": alerts,
        "power": {
            "battery_level": battery_level,
            "battery_band": band.title(),
            "battery_color": BATTERY_BAND_COLORS[band],
            "solar_charging": bool(power.get("solar_charging")),
            "power_mode": power.get("power_mode") or "balanced",
            "systems": systems,
            "oxygen_threat": oxygen_threat,
        },
        "crew": {
            "complement": len(all_crew),
            "on_duty": on_duty,
            "away": away,
            "healthy": healthy,
            "injured": injured,
            "critical": critical,
            "oxygen_stress": oxygen_stress,
            "access_request": access_request,
        },
        "security": {
            "wanted_count": len(wanted_details),
            "jailed_count": len(jailed_details),
            "fines_count": len(fine_details),
            "details": security_details,
            "security_systems_online": security_online,
        },
        "facilities": {
            "locked_rooms": locked_rooms,
            "botany_occupied": botany_occupied,
            "botany_total": botany_total,
            "botany_mature": botany_mature,
        },
    }


@register_panel("station_status", "Station Status")
def station_status_panel(game, state):
    status = collect_station_status(game.player_data, game.station_crew)
    return status
