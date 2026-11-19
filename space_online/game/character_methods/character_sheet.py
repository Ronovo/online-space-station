import datetime

from space_online.game.helper_methods import gas_mix
from space_online.game.helper_methods.station_air import tank_on
from space_online.game.helper_methods.health_bands import DAMAGE_TYPES, LIMBS, average_limb_health, damage_band, health_band, limb_label
from space_online.game.helper_methods.ui_panels import panel_action, register_panel
from space_online.game.objects.gases import GAS_TANK
from space_online.game.objects.items import inventory_item_count


@register_panel("character_sheet", "Character Sheet")
def character_sheet_panel(game, state):
    player_data = game.player_data
    alcohol_value = player_data["alcohol_percent"]

    damage_rows = []
    for key in DAMAGE_TYPES:
        value = player_data["damage"][key]
        status, color = damage_band(value)
        damage_rows.append({"name": key.title(), "value": value, "color": color,
                            "effect": None if status == "Clear" else status})

    limbs = [
        {
            "name": limb_label(limb),
            "health": player_data["limbs"][limb],
            "color": health_band(player_data["limbs"][limb])[1],
        }
        for limb in LIMBS
    ]

    needs = [{"name": need.title(), "value": value, "color": damage_band(value)[1]}
             for need, value in player_data["needs"].items()]

    tank = tank_on(player_data)
    limb_health = average_limb_health(player_data)
    damage_health = 100 - (sum(player_data["damage"].values()) / len(player_data["damage"]))

    return {
        "name": player_data["name"],
        "job": player_data["job"],
        "department": player_data.get("department", "Unknown"),
        "credits": player_data["credits"],
        "alcohol": alcohol_value,
        "alcohol_color": damage_band(alcohol_value)[1],
        "inventory_count": inventory_item_count(player_data),
        "holdings_count": len(player_data.get("stock_holdings", {})),
        "notes_count": len(player_data.get("notes", [])),
        "needs": needs,
        "damage": damage_rows,
        "limbs": limbs,
        "damage_health": damage_health,
        "damage_health_color": health_band(damage_health)[1],
        "limb_health": limb_health,
        "limb_health_color": health_band(limb_health)[1],
        "tank_kpa": gas_mix.pressure(tank["attributes"]["contents"], GAS_TANK["volume"]) if tank else None,
    }


@panel_action("character_sheet", "inventory")
def open_inventory(game, state, args):
    game.open_panel("inventory")


@panel_action("character_sheet", "holdings")
def open_holdings(game, state, args):
    game.open_panel("holdings")


@panel_action("character_sheet", "notes")
def open_notes(game, state, args):
    game.open_panel("notes")


@register_panel("holdings", "Stock Holdings")
def holdings_panel(game, state):
    return {"holdings": list(game.player_data["stock_holdings"].items())}


@register_panel("notes", "Character Notes")
def notes_panel(game, state):
    notes = []
    for note in reversed(game.player_data["notes"]):
        formatted_time = datetime.datetime.fromisoformat(note["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
        notes.append({"time": formatted_time, "text": note["text"]})
    return {"notes": notes}
