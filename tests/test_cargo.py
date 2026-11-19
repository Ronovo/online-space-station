import pytest

from helpers import (
    carried,
    crew,
    duty,
    duty_id,
    fix_random,
    give,
    give_duty,
    html,
    in_room,
    job_event,
    labels,
    last_message,
    new_game,
    notes,
    panel,
    pda_messages,
    reopen,
)
from space_online.game.helper_methods import gas_mix
from space_online.game.helper_methods.antagonists import incident_log_panel
from space_online.game.helper_methods.artifacts import EXPORT_VALUE, mark_analysed, new_artifact
from space_online.game.helper_methods.atmos import CANISTER_FILL, CANISTER_SLOTS
from space_online.game.helper_methods.hazards import set_hazard
from space_online.game.helper_methods.npc_movement import post_holder
from space_online.game.helper_methods.stores import STARTING_ORE
from space_online.game.maps.donut import CARGO_KEY, ENGINEERING_KEY, MEDBAY_KEY
from space_online.game.objects.botany_items import BOTANY_ITEMS, BOTANY_SEED_IDS
from space_online.game.objects.gases import CANISTER, DANGEROUS_GASES
from space_online.game.objects.items import add_to_inventory, get_item_definition
from space_online.game.objects.mining_items import ORE_VALUES
from space_online.game.special_rooms import cargo as cargo_room
from space_online.game.special_rooms.cargo import (
    CANISTER_PRICES,
    CARGO_DELIVERY_SECONDS,
    COUNTER_PRICES,
    DANGEROUS_ORDERS_ALLOWED,
    MUTANT_EXPORT_VALUE,
    NOTHING_TO_EXPORT,
    ORDER_ALERT_CHANCE,
    ORDER_PRICES,
    PRODUCE_EXPORT_VALUE,
    REQUEST_DECISION_SECONDS_RANGE,
    REQUEST_PRICES,
    STOCKPILING,
    export_value,
    tick_cargo,
)


def in_cargo():
    return in_room(CARGO_KEY)


def at_station():
    return in_room(CARGO_KEY, "Supply", "Quartermaster", "cargo_station")


def at(game, seconds):
    game.player_data["game_clock"]["elapsed_seconds"] = seconds
    tick_cargo(game)
    return game


def test_the_cargo_bay_is_off_the_northeast_hallway_next_to_the_mining_bay():
    game = new_game("Supply", "Quartermaster")
    game.player_data["location"] = {"x": 5, "y": 1}
    screen = game.view()["screen"]
    assert (screen["name"], screen["grid"][0][1]) == (
        "Cargo Bay Entrance", {"label": "Cargo Bay", "action": "game.enter_room", "args": {"room_key": CARGO_KEY}})
    game.perform("game.enter_room", {"room_key": CARGO_KEY})
    assert labels(game) == ["Enter Cargo Station", "Lock/Unlock Door", "Room Options"]
    assert game.player_data["cargo"] == {"orders": [], "arrived": [], "requests": [], "pickups": [], "canisters": [],
                                         "gas_orders": 0}


def test_visitors_buy_supplies_and_sell_exports_while_the_quartermaster_is_in():
    game = in_cargo()
    assert labels(game) == ["Buy Supplies", "Order Console", "Export Counter", NOTHING_TO_EXPORT]
    game.perform("room.buy_supplies", {})
    ctx = panel(game)["ctx"]
    assert (panel(game)["type"], ctx["goods"][0]) == ("supply_counter",
                                                      {"id": "snack", "name": "Snack", "price": COUNTER_PRICES["snack"]})
    game.perform("panel.buy", {"item_id": "medkit"})
    assert (carried(game), game.player_data["credits"]) == ({"medkit": 1}, 1000 - COUNTER_PRICES["medkit"])


def test_the_counters_are_shut_while_the_quartermaster_is_away_and_the_station_is_for_cargo_staff():
    game = give(in_cargo(), "iron_ore")
    quartermaster = crew(game, "Quartermaster")
    quartermaster.update(on_duty=False, location={"x": 2, "y": 5})
    assert labels(game)[0] == "The quartermaster is away from the bay."
    game.ui["room_mode"] = "cargo_station"
    assert labels(game)[0] == "The quartermaster is away from the bay."
    for action in ("buy_supplies", "sell_exports", "show_orders", "collect_deliveries"):
        game.perform(f"room.{action}", {})
    game.perform("room.sell_export", {"name": "Iron Ore"})
    assert (game.ui["panels"], carried(game), game._messages) == ([], {"iron_ore": 1}, [])


def test_the_export_counter_buys_ore_produce_mutants_and_analysed_artifacts():
    game = give(at_station(), "iron_ore", "iron_ore", "gold_ore", "tomato", "golden_apple", "medkit")
    artifact, unknown = new_artifact(), new_artifact()
    mark_analysed(artifact)
    for item in (artifact, unknown):
        add_to_inventory(game.player_data, item)
    assert [export_value(item) for item in (artifact, unknown, get_item_definition("medkit"))] == [EXPORT_VALUE, 0, 0]
    game.perform("room.sell_exports", {})
    total = (2 * ORE_VALUES["iron_ore"] + ORE_VALUES["gold_ore"] + PRODUCE_EXPORT_VALUE + MUTANT_EXPORT_VALUE
             + EXPORT_VALUE)
    assert last_message(game) == ("Export Counter", f"You sell 2 Iron Ore, 1 Gold Ore, 1 Tomato, 1 Golden Apple, "
                                                    f"1 {artifact['name']} for {total} credits.")
    assert game.player_data["credits"] == 3500 + total
    assert [item["id"] for item in game.player_data["inventory"]] == ["medkit", "alien_artifact"]
    assert game.player_data["stores"]["ore"] == STARTING_ORE + 3
    game.perform("room.sell_exports", {})
    assert last_message(game) == ("Export Counter", "You have nothing the export counter takes. It buys ore, produce "
                                                    "and analysed artifacts.")


def test_every_botany_harvest_sells_at_the_export_counter_plain_aloe_too():
    harvests = [BOTANY_ITEMS[seed]["attributes"]["produces"] for seed in BOTANY_SEED_IDS]
    assert [export_value(get_item_definition(item_id)) for item_id in harvests] == (
        [PRODUCE_EXPORT_VALUE] * len(harvests))
    game = give(at_station(), "aloe")
    game.perform("room.sell_export", {"name": "Aloe"})
    assert last_message(game) == ("Export Counter", f"You sell 1 Aloe for {PRODUCE_EXPORT_VALUE} credits.")
    assert (carried(game), game.player_data["credits"]) == ({}, 3500 + PRODUCE_EXPORT_VALUE)


def test_ordering_supplies_costs_credits_and_they_dock_later():
    game = at_station()
    assert labels(game) == ["Cargo Station", "Orders on the way: 0", "Order Supplies", "Collect Deliveries (0)",
                            "Back to Station Menu", "Export Counter", NOTHING_TO_EXPORT]
    game.perform("room.collect_deliveries", {})
    assert last_message(game) == ("Cargo Bay", "Nothing has docked yet.")
    game.perform("room.show_orders", {})
    assert panel(game)["ctx"]["goods"][3] == {"id": "medkit", "name": "Medkit", "price": ORDER_PRICES["medkit"]}
    game.perform("panel.order", {"item_id": "medkit"})
    game.perform("panel.order", {"item_id": "snack"})
    game.perform("panel.order", {"item_id": "energy_sword"})
    ctx = panel(game)["ctx"]
    assert ctx["orders"] == [{"name": "Medkit", "left": "1m 30s"}, {"name": "Snack", "left": "1m 30s"}]
    assert ctx["feedback"]["text"] == "Ordered a Snack. Its supply pod docks in 1m 30s."
    assert game.player_data["credits"] == 3500 - ORDER_PRICES["medkit"] - ORDER_PRICES["snack"]
    assert notes(game)[-1] == "Ordered a Snack from Central Command for 5 credits."

    at(game, CARGO_DELIVERY_SECONDS - 1)
    assert game.player_data["cargo"]["arrived"] == [] and len(game._messages) == 1
    at(game, CARGO_DELIVERY_SECONDS)
    assert last_message(game) == ("Cargo Bay", "A supply pod has docked at the Cargo Bay with Medkit, Snack.")
    game.ui["panels"] = []
    assert labels(game)[1:4] == ["Orders on the way: 0", "Order Supplies", "Collect Deliveries (2)"]
    game.perform("room.collect_deliveries", {})
    assert (carried(game), game.player_data["cargo"]["orders"], game.player_data["cargo"]["arrived"]) == (
        {"medkit": 1, "snack": 1}, [], [])
    assert last_message(game) == ("Cargo Bay", "You take Medkit, Snack off the conveyor.")


def test_the_order_console_shows_what_is_on_the_way(app):
    game = at_station()
    game.perform("room.show_orders", {})
    assert "Nothing is on its way." in html(app, game)
    game.perform("panel.order", {"item_id": "pickaxe"})
    page = html(app, game)
    assert "Pickaxe - docks in 1m 30s" in page and "Ordered a Pickaxe." in page


def test_the_quartermaster_gets_supply_requests_from_the_departments(monkeypatch):
    game = new_game("Supply", "Quartermaster")
    event = job_event(monkeypatch, game)
    assert (event["title"], event["desc"]) == (
        "Supply Request", "The Doctor needs a medkit. Deliver it to the MedBay for 160 credits.")
    event["effect"]()
    assert (duty(game)["item"], duty(game)["room"]) == ("medkit", MEDBAY_KEY)


def test_a_supply_request_for_something_with_a_plural_name_asks_for_some(monkeypatch):
    event = job_event(monkeypatch, new_game("Supply", "Quartermaster"),
                      pick=lambda options: next(o for o in options if o[2] == "emergency_rations"))
    assert event["desc"] == "The Chef needs some emergency rations. Deliver it to the Kitchen for 160 credits."


def test_the_export_counter_sells_one_kind_of_thing_at_a_time():
    game = give(in_cargo(), "iron_ore", "iron_ore", "gold_ore", "tomato", "medkit")
    assert labels(game)[-4:] == ["Sell 2 Iron Ore", "Sell 1 Gold Ore", "Sell 1 Tomato", "Sell All"]
    game.perform("room.sell_export", {"name": "Iron Ore"})
    assert carried(game) == {"gold_ore": 1, "tomato": 1, "medkit": 1}
    assert game.player_data["credits"] == 1000 + 2 * ORE_VALUES["iron_ore"]
    assert game.player_data["stores"]["ore"] == STARTING_ORE + 2
    assert last_message(game) == ("Export Counter", f"You sell 2 Iron Ore for {2 * ORE_VALUES['iron_ore']} credits.")
    game.perform("room.sell_export", {"name": "Medkit"})
    assert last_message(game) == ("Export Counter", NOTHING_TO_EXPORT)
    assert carried(game) == {"gold_ore": 1, "tomato": 1, "medkit": 1}


def test_sell_all_sells_even_an_ore_a_duty_asks_for():
    game = give(in_cargo(), "iron_ore", "tomato")
    give_duty(game, kind="deliver", giver="Engineer", room=ENGINEERING_KEY, item="iron_ore", label="iron ore",
              reward=100, summary="Bring iron ore")
    game.perform("room.sell_exports", {})
    assert carried(game) == {}


# --- The crew's Order Console -------------------------------------------------------------

def quartermaster(game):
    return post_holder(game.station_crew, "Quartermaster", CARGO_KEY)


def cargo(game):
    return game.player_data["cargo"]


def rolls(monkeypatch, chance):
    """Every roll at the Cargo Bay comes up chance, and the Quartermaster takes the shortest time to answer."""
    fix_random(monkeypatch, cargo_room, roll=chance, randint=lambda low, high: low)


def request(game, item):
    reopen(game, "order_request")
    game.perform("panel.request", {"item_id": item})
    return panel(game)["ctx"]


def answered(game):
    """Move the clock to when the Quartermaster answers the first request still waiting."""
    due = next(request["decide_at"] for request in cargo(game)["requests"] if request["status"] == "waiting")
    return at(game, due)


def requested_rows(game):
    reopen(game, "order_request")
    return panel(game)["ctx"]["requests"]


def test_the_order_console_opens_from_the_cargo_bay_for_everyone_but_the_quartermaster():
    game = in_cargo()
    quartermaster(game).update(on_duty=False, location={"x": 2, "y": 5})
    assert "Order Console" in labels(game)
    game.perform("room.show_order_request", {})
    ctx = panel(game)["ctx"]
    assert (panel(game)["type"], ctx["requests"], ctx["absent"], ctx["held"]) == ("order_request", [], None, [])
    assert ctx["goods"][3] == {"id": "medkit", "name": "Medkit", "price": COUNTER_PRICES["medkit"]}
    assert ctx["goods"][-3:] == [{"id": gas, "name": f"Canister of {gas}", "price": 2 * CANISTER_PRICES[gas]}
                                 for gas in DANGEROUS_GASES]

    game = at_station()
    game.ui["room_mode"] = "options"
    assert "Order Console" not in labels(game)
    game.perform("room.show_order_request", {})
    assert game.ui["panels"] == []


def test_a_request_is_recorded_at_the_counter_price_and_not_charged_yet(monkeypatch):
    rolls(monkeypatch, 0.0)
    game = in_cargo()
    ctx = request(game, "medkit")
    assert ctx["feedback"]["text"] == (f"Requested a Medkit for {COUNTER_PRICES['medkit']} credits. The Quartermaster "
                                       "answers on your PDA.")
    assert ctx["requests"] == [{"name": "Medkit", "status": "Waiting on the Quartermaster"}]
    (recorded,) = cargo(game)["requests"]
    assert {key: value for key, value in recorded.items() if key != "id"} == {
        "item": "medkit", "requester": "Ada", "price": COUNTER_PRICES["medkit"],
        "decide_at": REQUEST_DECISION_SECONDS_RANGE[0], "status": "waiting"}
    assert (game.player_data["credits"], cargo(game)["orders"]) == (1000, [])
    request(game, "energy_sword")
    assert len(cargo(game)["requests"]) == 1


def test_the_quartermaster_answers_after_a_while_and_orders_what_the_requester_can_pay_for(monkeypatch):
    rolls(monkeypatch, 0.0)
    game = in_cargo()
    request(game, "basic_tools")
    at(game, REQUEST_DECISION_SECONDS_RANGE[0] - 1)
    assert (cargo(game)["requests"][0]["status"], game._messages) == ("waiting", [])
    answered(game)
    price = COUNTER_PRICES["basic_tools"]
    message = (f"The Quartermaster approved your request for a Basic Tools and charged you {price} credits. It docks "
               "at the Cargo Bay in 1m 30s.")
    assert last_message(game) == ("Quartermaster", message)
    assert game.player_data["pda"]["messages"][-1]["text"] == message
    assert game.player_data["credits"] == 1000 - price
    assert cargo(game)["orders"] == [{"item": "basic_tools", "arrives_at": REQUEST_DECISION_SECONDS_RANGE[0]
                                      + CARGO_DELIVERY_SECONDS, "request": cargo(game)["requests"][0]["id"]}]
    at(game, REQUEST_DECISION_SECONDS_RANGE[0] + 30)
    assert requested_rows(game) == [{"name": "Basic Tools", "status": "On its way, docks in 1m 0s"}]


def test_the_quartermaster_denies_a_request_the_requester_cannot_pay_for(monkeypatch):
    rolls(monkeypatch, 0.0)
    game = in_cargo()
    request(game, "pickaxe")
    game.player_data["credits"] = COUNTER_PRICES["pickaxe"] - 1
    answered(game)
    reason = f"you can't pay the {COUNTER_PRICES['pickaxe']} credits it costs"
    assert last_message(game) == ("Quartermaster", f"The Quartermaster denied your request for a Pickaxe: {reason}.")
    assert (game.player_data["credits"], cargo(game)["orders"]) == (COUNTER_PRICES["pickaxe"] - 1, [])
    assert requested_rows(game) == [{"name": "Pickaxe", "status": f"Denied: {reason}"}]


@pytest.mark.parametrize("trouble, absent", [
    (lambda npc, game: npc.update(in_jail=True, jail_release_at_seconds=600),
     lambda npc: f"{npc['name']} is in jail and will be released in 9m 0s."),
    (lambda npc, game: npc["limbs"].update(dict.fromkeys(npc["limbs"], 10)),
     lambda npc: f"{npc['name']} is too badly hurt to work and needs a doctor."),
    (lambda npc, game: set_hazard(game.player_data, CARGO_KEY, "fire"),
     lambda npc: "The Quartermaster has cleared out until the fire is dealt with."),
    (lambda npc, game: npc.update(on_duty=False, location={"x": 2, "y": 5}),
     lambda npc: "The quartermaster is away from the bay."),
    (lambda npc, game: npc.update(job="Chef"), lambda npc: "Nobody holds the Quartermaster's post."),
])
def test_a_request_waits_while_the_quartermaster_cannot_answer_and_the_console_says_why(monkeypatch, trouble,
                                                                                        absent):
    rolls(monkeypatch, 0.0)
    game = in_cargo()
    npc = quartermaster(game)
    request(game, "snack")
    trouble(npc, game)
    at(game, 60)
    assert (cargo(game)["requests"][0]["status"], game.player_data["credits"]) == ("waiting", 1000)
    reopen(game, "order_request")
    assert panel(game)["ctx"]["absent"] == absent(npc)


def test_a_request_is_answered_once_the_quartermaster_is_out_of_jail(monkeypatch):
    rolls(monkeypatch, 0.0)
    game = in_cargo()
    request(game, "snack")
    quartermaster(game).update(in_jail=True)
    answered(game)
    assert cargo(game)["requests"][0]["status"] == "waiting"
    quartermaster(game).update(in_jail=False)
    at(game, 100)
    assert cargo(game)["requests"][0]["status"] == "ordered"


def test_an_approved_request_docks_for_the_requester_to_collect_at_the_cargo_bay(monkeypatch, app):
    rolls(monkeypatch, 0.0)
    game = in_cargo()
    assert not any(label.startswith("Collect Your Order") for label in labels(game))
    game.perform("room.collect_order", {})
    assert last_message(game) == ("Cargo Bay", "Nothing has docked yet.")
    request(game, "medkit")
    answered(game)
    at(game, REQUEST_DECISION_SECONDS_RANGE[0] + CARGO_DELIVERY_SECONDS)
    assert last_message(game) == ("Cargo Bay", "A supply pod has docked at the Cargo Bay with Medkit.")
    assert (cargo(game)["pickups"], cargo(game)["arrived"], cargo(game)["requests"]) == (["medkit"], [], [])
    assert requested_rows(game) == [{"name": "Medkit", "status": "Ready to collect at the Cargo Bay"}]
    assert "Medkit - Ready to collect at the Cargo Bay" in html(app, game)
    game.ui["panels"] = []
    assert "Collect Your Order (1)" in labels(game)
    game.perform("room.collect_order", {})
    assert (carried(game), cargo(game)["pickups"]) == ({"medkit": 1}, [])
    assert last_message(game) == ("Cargo Bay", "You take Medkit off the conveyor.")


def test_the_order_console_screen(monkeypatch, app):
    rolls(monkeypatch, 0.0)
    game = in_cargo()
    quartermaster(game).update(in_jail=True, jail_release_at_seconds=600)
    game.open_panel("order_request")
    page = html(app, game)
    assert "You have no requests open." in page and f"Medkit - {COUNTER_PRICES['medkit']} credits" in page
    game.perform("panel.request", {"item_id": "Plasma"})
    page = html(app, game)
    assert "Canister of Plasma - Waiting on the Quartermaster" in page
    assert "is in jail and will be released in" in page


# --- A player Quartermaster answers the crew's Supply Requests -------------------------------

def supply_request(game):
    return give_duty(game, kind="deliver", giver="Doctor", room=MEDBAY_KEY, item="medkit", label="a medkit",
                     reward=120, summary="Deliver a medkit to the MedBay")


def test_a_player_quartermaster_approves_a_supply_request_and_delivers_it_as_before(app):
    game = at_station()
    duty_id = supply_request(game)
    give_duty(game, kind="deliver", giver="Engineer", room=ENGINEERING_KEY, item="iron_ore", label="iron ore",
              reward=100, summary="Bring iron ore")
    game.perform("room.show_orders", {})
    assert panel(game)["ctx"]["requests"] == [{"id": duty_id, "text": "The Doctor needs a medkit (120 cr)",
                                               "price": ORDER_PRICES["medkit"], "approved": False}]
    page = html(app, game)
    assert "Approve (40 cr)</button>" in page and ">Deny</button>" in page
    game.perform("panel.approve", {"duty_id": duty_id})
    assert game.player_data["credits"] == 3500 - ORDER_PRICES["medkit"]
    assert [order["item"] for order in cargo(game)["orders"]] == ["medkit"]
    assert panel(game)["ctx"]["requests"][0]["approved"] is True
    assert '<span class="italic">Approved</span>' in html(app, game)
    game.perform("panel.approve", {"duty_id": duty_id})
    game.perform("panel.deny", {"duty_id": duty_id})
    assert (len(cargo(game)["orders"]), len(game.player_data["duties"])) == (1, 2)

    at(game, CARGO_DELIVERY_SECONDS)
    assert cargo(game)["arrived"] == ["medkit"]


def test_approving_takes_the_quartermasters_credits_for_the_order():
    game = at_station()
    game.player_data["credits"] = 10
    supply_request(game)
    game.perform("room.show_orders", {})
    game.perform("panel.approve", {"duty_id": duty_id(game)})
    assert panel(game)["ctx"]["feedback"]["text"] == "You don't have the 40 credits a Medkit costs."
    assert (cargo(game)["orders"], game.player_data["duties"][0].get("approved")) == ([], None)


def test_a_player_quartermaster_denies_a_supply_request_which_counts_as_done():
    game = at_station()
    supply_request(game)
    game.perform("room.show_orders", {})
    game.perform("panel.deny", {"duty_id": "nonsense"})
    game.perform("panel.deny", {"duty_id": duty_id(game)})
    assert (game.player_data["duties"], cargo(game)["orders"]) == ([], [])
    assert game.player_data["round"]["duties_done"] == 1
    assert last_message(game) == ("Duty Done", "You deny the Doctor's request for a medkit.")
    assert game.player_data["credits"] == 3500


# --- Dangerous gas ------------------------------------------------------------------------

def rack(game):
    return game.player_data["atmos"]["canisters"]


def test_an_ordered_canister_comes_down_the_tube_into_an_empty_atmospherics_slot(monkeypatch):
    rolls(monkeypatch, 0.0)
    game = in_cargo()
    rack(game)[5] = None
    request(game, "Hydrogen")
    answered(game)
    assert game.player_data["credits"] == 1000 - REQUEST_PRICES["Hydrogen"]
    at(game, REQUEST_DECISION_SECONDS_RANGE[0] + CARGO_DELIVERY_SECONDS)
    canister = rack(game)[5]
    assert canister["label"] == f"Canister {CANISTER_SLOTS + 1}"
    assert gas_mix.fractions(canister["mix"]) == {"Hydrogen": 1.0}
    assert gas_mix.pressure(canister["mix"], CANISTER["volume"]) == pytest.approx(CANISTER_FILL)
    assert (cargo(game)["canisters"], cargo(game)["pickups"], cargo(game)["requests"]) == ([], [], [])
    assert last_message(game) == ("Atmospherics", f"Canister {CANISTER_SLOTS + 1} comes down the tube from the Cargo "
                                                  "Bay into slot 6 of the Canister Rack.")


def test_with_no_free_slot_a_canister_waits_at_cargo_until_one_is_cleared(app):
    game = at_station()
    assert None not in rack(game)
    game.perform("room.show_orders", {})
    game.perform("panel.order", {"item_id": "Plasma"})
    game.perform("panel.order", {"item_id": "Nitrous Oxide"})
    assert panel(game)["ctx"]["feedback"]["text"] == ("Ordered a Canister of Nitrous Oxide. Its supply pod docks in "
                                                      "1m 30s.")
    assert game.player_data["credits"] == 3500 - CANISTER_PRICES["Plasma"] - CANISTER_PRICES["Nitrous Oxide"]
    at(game, CARGO_DELIVERY_SECONDS)
    held = [f"Canister {number} waits at the Cargo Bay. Clear a slot on the Atmospherics Canister Rack and it goes "
            "down the tube." for number in (CANISTER_SLOTS + 1, CANISTER_SLOTS + 2)]
    assert (len(cargo(game)["canisters"]), cargo(game)["arrived"]) == (2, [])
    assert panel(game)["ctx"]["held"] == held
    assert held[0] in html(app, game)

    rack(game)[2] = None
    at(game, CARGO_DELIVERY_SECONDS + 1)
    assert gas_mix.fractions(rack(game)[2]["mix"]) == {"Plasma": 1.0}
    assert [canister["label"] for canister in cargo(game)["canisters"]] == [f"Canister {CANISTER_SLOTS + 2}"]


def test_every_dangerous_gas_order_goes_in_the_incident_log_without_counting_as_a_threats_incident(app):
    game = at_station()
    game.player_data["game_clock"]["elapsed_seconds"] = 125
    game.perform("room.show_orders", {})
    game.perform("panel.order", {"item_id": "Plasma"})
    game.perform("panel.order", {"item_id": "medkit"})
    assert game.player_data["incidents"] == [{"at": 125, "where": "Cargo Bay", "away": None,
                                              "what": "Ada ordered a canister of Plasma from Central Command."}]
    assert incident_log_panel(game, {})["incidents"] == [
        {"time": "T+2m", "where": "Cargo Bay", "what": "Ada ordered a canister of Plasma from Central Command.",
         "away": None}]
    reopen(game, "incident_log")
    page = html(app, game)
    assert "Ada ordered a canister of Plasma from Central Command." in page and "Away from their posts" not in page


def order_gas(game, count):
    reopen(game, "cargo_orders")
    for _ in range(count):
        game.perform("panel.order", {"item_id": "Plasma"})


def test_the_first_dangerous_gas_orders_never_raise_a_warrant_and_the_next_ones_can(monkeypatch):
    rolls(monkeypatch, 0.0)
    game = at_station()
    order_gas(game, DANGEROUS_ORDERS_ALLOWED)
    assert game.player_data["warrant"] is False
    order_gas(game, 1)
    assert (game.player_data["warrant"], game.player_data["warrant_reason"]) == (True, STOCKPILING)
    assert len(game.player_data["incidents"]) == DANGEROUS_ORDERS_ALLOWED + 1
    assert game.player_data["pda"]["messages"] == []


def test_an_order_past_the_allowance_is_left_alone_when_the_roll_misses_or_a_warrant_is_already_out(monkeypatch):
    rolls(monkeypatch, ORDER_ALERT_CHANCE)
    game = at_station()
    order_gas(game, DANGEROUS_ORDERS_ALLOWED + 2)
    assert game.player_data["warrant"] is False

    rolls(monkeypatch, 0.0)
    game.player_data.update(warrant=True, warrant_reason="Breaking and entering")
    order_gas(game, 1)
    assert game.player_data["warrant_reason"] == "Breaking and entering"


def test_a_security_guard_who_stockpiles_gas_is_messaged_about_the_warrant(monkeypatch):
    rolls(monkeypatch, 0.0)
    game = in_room(CARGO_KEY, "Security", "Security Guard")
    for _ in range(DANGEROUS_ORDERS_ALLOWED + 1):
        request(game, "Plasma")
        answered(game)
    assert pda_messages(game).count(("Warrant", f"Ada is wanted: {STOCKPILING}.")) == 1
    assert game.player_data["warrant_reason"] == STOCKPILING
