"""Atmospherics, the north door of the Science Hall: the Canister Rack with its heater/freezer, the Gas Dispenser,
the Combustion Chamber, the life support Reservoir, the Air Monitor and the tank rack. The state and the rules are in
helper_methods/atmos.py and helper_methods/station_air.py."""

import copy

from space_online.game.helper_methods import gas_mix
from space_online.game.helper_methods.atmos import (
    CHAMBER,
    HEATER_RANGE,
    PORTS,
    burst_chamber_if_over,
    burst_if_over,
    connect,
    dispense_into,
    light_chamber,
    move_canister,
    port_canister,
    poured,
)
from space_online.game.helper_methods.station_air import (
    TANK_FULL,
    VENT_SHARE,
    pump_rate,
    readings,
    reservoir_share,
    vent_station,
)
from space_online.game.helper_methods.ui_panels import (
    choice_handler,
    current_feedback,
    panel_action,
    register_panel,
    set_feedback,
)
from space_online.game.maps.donut import ATMOSPHERICS_KEY
from space_online.game.objects.gases import CANISTER, GAS_TANK, GASES, RESERVOIR, ROOM_TEMP, STATION_AIR
from space_online.game.objects.items import (
    GAS_ANALYZER_ID,
    GAS_TANK_ID,
    TRANSFER_VALVE_ID,
    add_to_inventory,
    format_inventory_label,
    get_item_definition,
    tank_readout,
)
from space_online.game.special_rooms.shared import (
    SpecialRoomBase,
    available_npc,
    button,
    issue_gear,
    npc_contact_widgets,
    room_action,
    text_line,
)

TANK_RACK_IDS = (GAS_TANK_ID, GAS_ANALYZER_ID)
# The slider tops: a whole canister's worth of gas at room temperature, and a Gas Tank's.
DISPENSE_MAX = round(gas_mix.moles_at(CANISTER["rated"], CANISTER["volume"], ROOM_TEMP))
TANK_FILL_MAX = round(TANK_FULL)


class Atmospherics(SpecialRoomBase):
    ROOM_TITLE = "Atmospherics"
    ROOM_HEADING = "Atmospherics"
    ROOM_DESCRIPTION = (
        "Pipes run across the ceiling of the atmospherics lab. A rack of gas canisters stands against one wall beside "
        "the gas dispenser, and a heavy combustion chamber with a thick viewing port fills the far end."
    )
    DOOR_KEY = ATMOSPHERICS_KEY
    STATION_ENTRIES = ({"label": "Enter Atmospherics Station", "mode": "atmospherics_station"},)
    CONTACT_POSTS = {"Scientist": DOOR_KEY}

    def room_options(self):
        widgets = npc_contact_widgets(
            self.game,
            "Scientist",
            self.DOOR_KEY,
            talk_label="Talk to Scientist",
            talk_action="talk_to_scientist",
            absent_flavor="The scientist is away from the lab.",
        )
        return widgets + self.back_to_station_menu()

    def mode_buttons(self, mode):
        if mode != "atmospherics_station" or not self.station_allowed(mode):
            return None
        return [
            text_line("Atmospherics Station Controls", style="title"),
            button("Canister Rack", "room.show_canister_rack"),
            button("Gas Dispenser", "room.show_gas_dispenser"),
            button("Combustion Chamber", "room.show_combustion_chamber"),
            button("Reservoir", "room.show_reservoir"),
            button("Air Monitor", "room.show_air_monitor"),
            button("Tank Rack", "room.take_tanks"),
            button("Test Range", "room.show_test_range"),
            button("Back to Station Menu", "room.set_mode", mode="menu"),
        ]

    @room_action
    def talk_to_scientist(self):
        if available_npc(self.game, "Scientist", self.DOOR_KEY):
            self.game.alert("Scientist", "The scientist taps a pressure gauge. 'Mind the plasma canister. And the "
                                         "chamber. And the vents.'")

    @room_action(station="atmospherics_station")
    def show_canister_rack(self):
        self.game.open_panel("canister_rack")

    @room_action(station="atmospherics_station")
    def show_gas_dispenser(self):
        self.game.open_panel("gas_dispenser")

    @room_action(station="atmospherics_station")
    def show_combustion_chamber(self):
        self.game.open_panel("combustion_chamber")

    @room_action(station="atmospherics_station")
    def show_reservoir(self):
        self.game.open_panel("reservoir")

    @room_action(station="atmospherics_station")
    def show_air_monitor(self):
        self.game.open_panel("air_monitor")

    @room_action(station="atmospherics_station")
    def take_tanks(self):
        """Hand out a Gas Tank and a Gas Analyzer, and the shift's one free Tank Transfer Valve."""
        issue_gear(self.game, TANK_RACK_IDS, "Tank Rack", "the tank rack", "a Gas Tank and a Gas Analyzer")
        atmos = _atmos(self.game)
        if atmos["valve_taken"]:
            return
        atmos["valve_taken"] = True
        add_to_inventory(self.game.player_data, get_item_definition(TRANSFER_VALVE_ID))
        self.game.add_note("Took the shift's Tank Transfer Valve from the tank rack.")
        self.game.alert("Tank Rack", "You take the shift's one Tank Transfer Valve from the rack. The fabricator in "
                                     "Engineering makes more.")

    @room_action(station="atmospherics_station")
    def show_test_range(self):
        self.game.open_panel("bomb_range")


def _atmos(game):
    return game.player_data["atmos"]


def _canister(game, index):
    """The canister in slot `index`, or None for an empty slot or no slot."""
    canisters = _atmos(game)["canisters"]
    return canisters[index] if index is not None and 0 <= index < len(canisters) else None


def _gauge(canister):
    return gas_mix.readout(canister["mix"], CANISTER["volume"])


def _canister_rows(game):
    return [{"index": index, "label": canister["label"]}
            for index, canister in enumerate(_atmos(game)["canisters"]) if canister]


def _whole_moles(mix):
    return int(gas_mix.total_moles(mix))


def _amount(state, key, top):
    """The amount a slider is set to, kept within 0 and top."""
    return max(0, min(top, state.get(key, 0)))


def _set_slider(state, key, args):
    state[key] = max(0, int(args["value"]))


def _over_rating(into, source, amount, spec):
    """Whether moving `amount` mol of the gas in `source` into `into` would take it past spec's rated pressure."""
    portion = gas_mix.take(copy.deepcopy(source), amount)
    return gas_mix.pressure(poured(into, portion), spec["volume"]) > spec["rated"]


def _tank(game, state):
    """The carried Gas Tank picked on the panel, or None."""
    inventory = game.player_data["inventory"]
    index = state.get("tank")
    if index is None or not 0 <= index < len(inventory) or inventory[index].get("id") != GAS_TANK_ID:
        return None
    return inventory[index]


@register_panel("canister_rack", "Canister Rack")
def canister_rack_panel(game, state):
    canister = _canister(game, state.get("selected"))
    tank = _tank(game, state)
    moles = _whole_moles(canister["mix"]) if canister else 0
    return {
        "slots": [{"index": index, "label": slot["label"] if slot else f"Slot {index + 1}: empty", "empty": not slot}
                  for index, slot in enumerate(_atmos(game)["canisters"])],
        "selected": state.get("selected") if canister else None,
        "canister": canister and {
            "label": canister["label"],
            "gauge": _gauge(canister),
            "port": canister["port"],
            "thermo": canister["thermo"],
        },
        "targets": [row for row in _canister_rows(game) if row["index"] != state.get("selected")],
        "target": state.get("target"),
        "amount": _amount(state, "amount", moles),
        "max_amount": moles,
        "tanks": [{"index": index, "label": f"{format_inventory_label(item)}: {tank_readout(item)}"}
                  for index, item in enumerate(game.player_data["inventory"]) if item.get("id") == GAS_TANK_ID],
        "tank": state.get("tank") if tank else None,
        "tank_amount": _amount(state, "tank_amount", TANK_FILL_MAX),
        "tank_max": TANK_FILL_MAX,
        "ports": list(PORTS.items()),
        "heater_range": HEATER_RANGE,
        "feedback": current_feedback(state),
    }


def _selected_canister(game, state):
    canister = _canister(game, state.get("selected"))
    if canister is None:
        set_feedback(state, "Pick a canister on the rack first.", "orange")
    return canister


@panel_action("canister_rack")
def select_canister(game, state, args):
    if _canister(game, int(args["index"])) is not None:
        state["selected"] = int(args["index"])
        state.pop("target", None)


@panel_action("canister_rack")
def set_target(game, state, args):
    state["target"] = int(args["index"])


@panel_action("canister_rack")
def set_amount(game, state, args):
    _set_slider(state, "amount", args)


@panel_action("canister_rack")
def transfer(game, state, args):
    canister = _selected_canister(game, state)
    target = _canister(game, state.get("target"))
    if canister is None:
        return
    if target is None or target is canister:
        set_feedback(state, "Pick a canister to transfer into.", "orange")
        return
    moved = gas_mix.take(canister["mix"], state.get("amount", 0))
    gas_mix.merge(target["mix"], moved)
    set_feedback(state, f"Moved {gas_mix.total_moles(moved):.0f} mol from {canister['label']} to {target['label']}.")
    burst_if_over(game, target, CANISTER, target["label"])


@panel_action("canister_rack")
def select_tank(game, state, args):
    state["tank"] = int(args["index"])


@panel_action("canister_rack")
def set_tank_amount(game, state, args):
    _set_slider(state, "tank_amount", args)


def _canister_and_tank(game, state):
    canister = _selected_canister(game, state)
    if canister is None:
        return None, None
    tank = _tank(game, state)
    if tank is None:
        set_feedback(state, "Pick a Gas Tank you are carrying. The tank rack hands out empty ones.", "orange")
    return canister, tank


@panel_action("canister_rack")
def fill_tank(game, state, args):
    canister, tank = _canister_and_tank(game, state)
    if tank is None:
        return
    contents = tank["attributes"]["contents"]
    amount = _amount(state, "tank_amount", TANK_FILL_MAX)
    if _over_rating(contents, canister["mix"], amount, GAS_TANK):
        set_feedback(state, f"That would take the tank past its rated {GAS_TANK['rated']} kPa.", "orange")
        return
    gas_mix.merge(contents, gas_mix.take(canister["mix"], amount))
    set_feedback(state, f"The tank reads {tank_readout(tank)}.")


@panel_action("canister_rack")
def empty_tank(game, state, args):
    canister, tank = _canister_and_tank(game, state)
    if tank is None:
        return
    gas_mix.merge(canister["mix"], gas_mix.take(tank["attributes"]["contents"], float("inf")))
    set_feedback(state, f"You empty the tank into {canister['label']}.")
    burst_if_over(game, canister, CANISTER, canister["label"])


@panel_action("canister_rack")
def vent_canister(game, state, args):
    canister = _selected_canister(game, state)
    if canister is None:
        return
    canister["mix"] = gas_mix.empty_mix()
    game.add_note(f"Vented {canister['label']} to space.")
    set_feedback(state, f"{canister['label']} hisses empty into space.")


@panel_action("canister_rack")
def send_to_engineering(game, state, args):
    canister = _selected_canister(game, state)
    if canister is None:
        return
    if canister["port"]:
        set_feedback(state, f"Disconnect {canister['label']} first.", "orange")
        return
    free = move_canister(_atmos(game)["canisters"], state["selected"], game.player_data["engine"]["canisters"])
    if free is None:
        set_feedback(state, "The Combustion Engine's canister bay has no free slot.", "orange")
        return
    state.pop("selected")
    message = f"{canister['label']} goes down the tube into slot {free + 1} of the Combustion Engine's canister bay."
    game.add_note(message)
    set_feedback(state, message)


@panel_action("canister_rack")
def set_port(game, state, args):
    canister = _selected_canister(game, state)
    port = args.get("port") or None
    if canister is None or (port is not None and port not in PORTS):
        return
    connect(_atmos(game), canister, port)
    set_feedback(state, f"{canister['label']} is connected to the {PORTS[port]}." if port
                 else f"{canister['label']} is disconnected.")


@panel_action("canister_rack")
def set_heater_target(game, state, args):
    canister = _selected_canister(game, state)
    if canister is not None:
        canister["thermo"]["target"] = max(HEATER_RANGE[0], min(HEATER_RANGE[1], int(args["value"])))


@panel_action("canister_rack")
def toggle_heater(game, state, args):
    """Switch the heater/freezer on for the selected canister, which takes it off any other, or switch it off."""
    canister = _selected_canister(game, state)
    if canister is None:
        return
    if canister["thermo"]["on"]:
        canister["thermo"]["on"] = False
        set_feedback(state, "The heater/freezer winds down.")
        return
    for other in _atmos(game)["canisters"]:
        if other:
            other["thermo"]["on"] = False
    canister["thermo"]["on"] = True
    set_feedback(state, f"The heater/freezer works {canister['label']} toward {canister['thermo']['target']} K.")


@register_panel("gas_dispenser", "Gas Dispenser")
def gas_dispenser_panel(game, state):
    gas = state.get("gas", next(iter(GASES)))
    canister = _canister(game, state.get("canister"))
    stock = _atmos(game)["stock"]
    top = min(DISPENSE_MAX, stock[gas]) if gas in stock else DISPENSE_MAX
    amount = _amount(state, "amount", top)
    return {
        "gases": [{"name": name, "label": f"{name} ({stock[name]:.0f} mol left)" if name in stock else name}
                  for name in GASES],
        "gas": gas,
        "canisters": _canister_rows(game),
        "canister": state.get("canister") if canister else None,
        "amount": amount,
        "max_amount": top,
        "before": _gauge(canister) if canister else None,
        "after": gas_mix.readout(poured(canister["mix"], gas_mix.mix_of({gas: 1}, amount, ROOM_TEMP)),
                                 CANISTER["volume"]) if canister else None,
        "feedback": current_feedback(state),
    }


@panel_action("gas_dispenser")
def pick_gas(game, state, args):
    if args["name"] in GASES:
        state["gas"] = args["name"]


@panel_action("gas_dispenser")
def pick_canister(game, state, args):
    state["canister"] = int(args["index"])


@panel_action("gas_dispenser", "set_amount")
def set_dispense_amount(game, state, args):
    _set_slider(state, "amount", args)


@panel_action("gas_dispenser")
def dispense(game, state, args):
    """Fill the picked canister with the picked gas at room temperature. The dangerous gases come out of the
    shift's stock and stop when it is gone, and nothing goes past the canister's rated pressure."""
    gas = state.get("gas", next(iter(GASES)))
    canister = _canister(game, state.get("canister"))
    amount = state.get("amount", 0)
    stock = _atmos(game)["stock"]
    if canister is None:
        set_feedback(state, "Pick a canister to fill.", "orange")
        return
    if amount <= 0:
        set_feedback(state, "Set an amount to dispense.", "orange")
        return
    if gas in stock and amount > stock[gas]:
        set_feedback(state, f"Only {stock[gas]:.0f} mol of {gas} is left this shift.", "orange")
        return
    gas_in = gas_mix.mix_of({gas: 1}, amount, ROOM_TEMP)
    if gas_mix.pressure(poured(canister["mix"], gas_in), CANISTER["volume"]) > CANISTER["rated"]:
        set_feedback(state, f"That would take {canister['label']} past its rated {CANISTER['rated']} kPa.", "orange")
        return
    dispense_into(_atmos(game), canister, gas, amount)
    game.add_note(f"Dispensed {amount} mol of {gas} into {canister['label']}.")
    set_feedback(state, f"Dispensed {amount} mol of {gas} into {canister['label']}.")


@register_panel("combustion_chamber", "Combustion Chamber")
def combustion_chamber_panel(game, state):
    chamber = _atmos(game)["chamber"]
    inlet = port_canister(_atmos(game), "chamber")
    moles = _whole_moles(inlet["mix"]) if inlet else 0
    return {
        "gauge": gas_mix.readout(chamber["mix"], CHAMBER["volume"]),
        "rated": CHAMBER["rated"],
        "lit": chamber["lit"],
        "inlet": inlet and {"label": inlet["label"], "gauge": _gauge(inlet)},
        "amount": _amount(state, "amount", moles),
        "max_amount": moles,
        "canisters": _canister_rows(game),
        "target": state.get("target") if _canister(game, state.get("target")) else None,
        "feedback": current_feedback(state),
    }


@panel_action("combustion_chamber", "set_amount")
def set_inject_amount(game, state, args):
    _set_slider(state, "amount", args)


@panel_action("combustion_chamber")
def inject(game, state, args):
    inlet = port_canister(_atmos(game), "chamber")
    if inlet is None:
        set_feedback(state, f"Connect a canister to the {PORTS['chamber']} at the Canister Rack first.", "orange")
        return
    moved = gas_mix.take(inlet["mix"], state.get("amount", 0))
    gas_mix.merge(_atmos(game)["chamber"]["mix"], moved)
    set_feedback(state, f"Injected {gas_mix.total_moles(moved):.0f} mol from {inlet['label']}.")
    burst_chamber_if_over(game)


@panel_action("combustion_chamber")
def ignite(game, state, args):
    chamber = _atmos(game)["chamber"]
    if chamber["lit"]:
        set_feedback(state, "It is already burning.")
    elif gas_mix.can_burn(chamber["mix"], spark=True):
        light_chamber(chamber)
        game.add_note("Lit a burn in the combustion chamber.")
        set_feedback(state, "The igniter sparks, and the chamber fills with flame.", "lightgreen")
    else:
        set_feedback(state, "The igniter sparks. Nothing in the chamber burns: it needs a fuel and an oxidizer.",
                     "orange")


@panel_action("combustion_chamber")
def pick_target(game, state, args):
    state["target"] = int(args["index"])


@panel_action("combustion_chamber")
def pump_out(game, state, args):
    """Pump all of the chamber's gas into the picked canister, hot as it is."""
    target = _canister(game, state.get("target"))
    if target is None:
        set_feedback(state, "Pick a canister to pump into.", "orange")
        return
    chamber = _atmos(game)["chamber"]
    gas_mix.merge(target["mix"], gas_mix.take(chamber["mix"], float("inf")))
    set_feedback(state, f"The chamber's gas is pumped into {target['label']}, which reads {_gauge(target)}.")
    burst_if_over(game, target, CANISTER, target["label"])


@panel_action("combustion_chamber")
def vent_chamber(game, state, args):
    chamber = _atmos(game)["chamber"]
    chamber.update(mix=gas_mix.empty_mix(), lit=False, peak=None)
    game.add_note("Vented the combustion chamber to space.")
    set_feedback(state, "The chamber vents to space. Whatever was burning goes out.")


@register_panel("reservoir", "Reservoir")
def reservoir_panel(game, state):
    reservoir = _atmos(game)["reservoir"]
    port = port_canister(_atmos(game), "reservoir")
    return {
        "gauge": gas_mix.readout(reservoir, RESERVOIR["volume"]),
        "fill": 100 * reservoir_share(reservoir),
        "rated": RESERVOIR["rated"],
        "port": port and {"label": port["label"], "gauge": _gauge(port)},
        "amount": _amount(state, "amount", DISPENSE_MAX),
        "max_amount": DISPENSE_MAX,
        "feedback": current_feedback(state),
    }


@panel_action("reservoir", "set_amount")
def set_reservoir_amount(game, state, args):
    _set_slider(state, "amount", args)


def _reservoir_port(game, state):
    canister = port_canister(_atmos(game), "reservoir")
    if canister is None:
        set_feedback(state, f"Connect a canister to the {PORTS['reservoir']} at the Canister Rack first.", "orange")
    return canister


@panel_action("reservoir")
def pump_in(game, state, args):
    """Pump gas from the canister on the Reservoir Port into the reservoir, up to the reservoir's rating."""
    canister = _reservoir_port(game, state)
    if canister is None:
        return
    reservoir = _atmos(game)["reservoir"]
    amount = state.get("amount", 0)
    if _over_rating(reservoir, canister["mix"], amount, RESERVOIR):
        set_feedback(state, f"That would take the reservoir past its rated {RESERVOIR['rated']} kPa.", "orange")
        return
    moved = gas_mix.take(canister["mix"], amount)
    gas_mix.merge(reservoir, moved)
    message = f"Pumped {gas_mix.total_moles(moved):.0f} mol from {canister['label']} into the life support reservoir."
    game.add_note(message)
    set_feedback(state, message)


@panel_action("reservoir")
def draw_off(game, state, args):
    """Draw reservoir gas off into the canister on the Reservoir Port, which can rupture it."""
    canister = _reservoir_port(game, state)
    if canister is None:
        return
    moved = gas_mix.take(_atmos(game)["reservoir"], state.get("amount", 0))
    gas_mix.merge(canister["mix"], moved)
    message = f"Drew {gas_mix.total_moles(moved):.0f} mol off the life support reservoir into {canister['label']}."
    game.add_note(message)
    set_feedback(state, message)
    burst_if_over(game, canister, CANISTER, canister["label"])


def _limit_status(row):
    """(word, colour) for how the air stands against one limit."""
    if not row["past"]:
        return "OK", "#00FF00"
    if row["effect"] == "rich":
        return "Rich", "#FFFF00"
    return ("Low" if row["low"] else "Dangerous"), "#FF0000"


@register_panel("air_monitor", "Air Monitor")
def air_monitor_panel(game, state):
    player_data = game.player_data
    return {
        "gauge": gas_mix.readout(_atmos(game)["air"], STATION_AIR["volume"]),
        "limits": [{"name": row["name"], "kpa": row["kpa"], "status": _limit_status(row)}
                   for row in readings(_atmos(game)["air"])],
        "level": player_data["station_power"]["system_levels"]["life_support"],
        "pump_rate": pump_rate(player_data),
        "vent_share": VENT_SHARE,
    }


@panel_action("air_monitor")
def vent(game, state, args):
    game.ask("Vent the Station",
             f"Dump {VENT_SHARE:.0%} of the station's air to space? Everyone aboard breathes thin air until the pump "
             "refills it from the reservoir, and at low life support that can kill.",
             [("Vent It", "vent_station", {}), ("Leave It", None, None)])


@choice_handler("vent_station")
def confirm_vent(game):
    vent_station(game.player_data)
    message = "You vent the station's air to space. The pump starts refilling it from the reservoir."
    game.add_note("Vented the station's air to space.")
    game.alert("Air Monitor", message, kind="warning")
