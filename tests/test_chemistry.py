import pytest

from helpers import (
    add_ingredients,
    buttons,
    carried,
    ctx,
    duty,
    give,
    in_room,
    index_of,
    item_action,
    job_event,
    labels,
    last_message,
    new_game,
    notes,
    open_station,
    panel,
)
from space_online.game.helper_methods import random_events
from space_online.game.helper_methods.npc_movement import post_holder
from space_online.game.maps.donut import CHEMISTRY_KEY, MEDBAY_KEY, RESEARCH_KEY, location_from_key
from space_online.game.objects.chemicals import COMPOUNDS, DISPENSER_CHEMICALS, PROCESSOR_RESULTS, reagent_of
from space_online.game.objects.items import add_to_inventory, get_item_definition


def in_chemistry(department="Science", job="Scientist", post=CHEMISTRY_KEY):
    return in_room(CHEMISTRY_KEY, department, job, post=post)


def give_drink(game, name, alcoholic):
    add_to_inventory(game.player_data, {"id": f"drink_{name.lower()}", "name": name, "category": "Drink",
                                        "attributes": {"alcoholic": alcoholic}, "actions": ["drink"]})
    return game


def dispenser(game=None):
    return open_station(game or in_chemistry(), "chemistry_station", "access_dispenser")


def test_chemistry_is_the_east_door_of_the_science_hall():
    game = new_game("Science", "Scientist", post=CHEMISTRY_KEY)
    game.player_data["location"] = {"x": 3, "y": 5}
    game.perform("game.move", {"direction": "east"})
    screen = game.view()["screen"]
    assert (game.player_data["location"], screen["name"]) == ({"x": 3, "y": 6}, "Science Hall")
    assert screen["grid"][1][2] == {"label": "Chemistry Lab", "action": "game.enter_room",
                                    "args": {"room_key": CHEMISTRY_KEY}}
    labels = [cell["label"] for row in screen["grid"] for cell in row if cell]
    assert labels == ["Atmospherics", "Go West", "Chemistry Lab", "Research Lab"]
    game.perform("game.move", {"direction": "east"})
    assert game.player_data["location"] == {"x": 3, "y": 6}


def test_the_scientist_works_the_chemistry_station():
    game = in_chemistry()
    assert buttons(game) == [("Enter Chemistry Station", "room.open_station"),
                             ("Lock/Unlock Door", "room.toggle_door"), ("Room Options", "room.set_mode")]
    game.perform("room.open_station", {"mode": "chemistry_station"})
    assert labels(game) == ["Chemistry Station Controls", "Chemical Dispenser", "Processor", "Formula Book",
                            "Send Remedies to MedBay", "Back to Station Menu"]
    game.perform("room.show_formulas", {})
    assert (panel(game)["type"], ctx(game)["header"]) == ("formulas", "SCIENTIST'S FORMULA BOOK")
    assert [recipe["name"] for recipe in ctx(game)["sections"][0]["recipes"]] == sorted(COMPOUNDS)
    assert ctx(game)["sections"][0]["recipes"][0]["price"] is None


def test_visitors_only_get_to_talk_to_the_scientist():
    game = in_chemistry("Civilian", "Staff Assistant")
    assert buttons(game) == [("Talk to Scientist", "room.talk_to_scientist")]
    game.perform("room.talk_to_scientist", {})
    assert last_message(game) == ("Scientist", "The scientist doesn't look up from a bubbling flask. 'Don't touch "
                                               "anything.'")
    game.ui["room_mode"] = "chemistry_station"
    assert buttons(game) == [("Talk to Scientist", "room.talk_to_scientist")]
    for action in ("access_dispenser", "access_processor", "show_formulas"):
        game.perform(f"room.{action}", {})
    assert game.ui["panels"] == []


def test_mixing_a_compound_from_the_dispenser():
    game = dispenser()
    context = ctx(game)
    assert (context["labels"].title, context["categories"]) == (
        "Chemical Dispenser", ["All", "Elements", "Solvents", "Inventory"])
    assert context["ingredients"] == DISPENSER_CHEMICALS
    add_ingredients(game, "Nitrogen", "Phosphorus", "Potassium")
    game.perform("panel.mix", {})
    assert ctx(game)["result"] == {
        "text": f"Success! You've made Miracle Grow.\n{COMPOUNDS['Miracle Grow']['desc']}\n"
                "It has been added to your inventory.", "color": "lightgreen"}
    assert carried(game) == {"miracle_grow": 1}
    assert notes(game)[-1] == "Mixed Miracle Grow at the chemical dispenser."


@pytest.mark.parametrize("beaker, feedback", [
    (["Carbon"], "A compound needs at least two chemicals."),
    (["Carbon", "Sulfur"], "Check the formula book for what reacts."),
])
def test_a_mixture_that_makes_nothing_says_why(beaker, feedback):
    game = dispenser()
    add_ingredients(game, *beaker)
    game.perform("panel.mix", {})
    assert ctx(game)["result"] == {"text": f"The mixture fizzles into grey sludge. {feedback}", "color": "red"}
    assert game.player_data["inventory"] == []


def test_what_carried_items_go_into_the_beaker_as():
    assert reagent_of(get_item_definition("aloe_extract")) == "Aloe Extract"
    assert reagent_of({"name": "Vodka", "category": "Drink", "attributes": {"alcoholic": True}}) == "Ethanol"
    assert reagent_of({"name": "Orange Juice", "category": "Drink", "attributes": {"alcoholic": False}}) == "Fruit Acid"
    assert reagent_of({"name": "Cola", "category": "Drink", "attributes": {"alcoholic": False}}) is None
    assert reagent_of(get_item_definition("potato")) is None
    assert reagent_of({"name": "Rock", "category": "Ore"}) is None


def test_carried_liquids_and_reagents_can_be_added_and_are_used_up():
    game = give(give_drink(give_drink(in_chemistry(), "Vodka", True), "Cola", False), "aloe_extract", "starch", "wrench")
    dispenser(game)
    assert ctx(game)["counts"] == {"Ethanol": 1, "Aloe Extract": 1, "Starch": 1}
    game.perform("panel.category", {"name": "Inventory"})
    assert ctx(game)["ingredients"] == ["Aloe Extract", "Ethanol", "Starch"]
    add_ingredients(game, "Aloe Extract", "Starch", "Ethanol", "Ethanol")
    assert last_message(game) == ("Dispenser", "There is no more Ethanol to add.")
    game.perform("panel.mix", {})
    assert carried(game) == {"drink_cola": 1, "wrench": 1, "healing_gel": 1}


def test_the_processor_turns_solids_into_reagents():
    game = open_station(give(in_chemistry(), "potato", "potato", "aloe", "wrench"), "chemistry_station",
                        "access_processor")
    assert ctx(game)["items"] == [{"index": 0, "label": "Potato x 2", "makes": "Starch"},
                                  {"index": 1, "label": "Aloe", "makes": "Aloe Extract"}]
    game.perform("panel.process", {"index": 0})
    assert carried(game) == {"potato": 1, "aloe": 1, "wrench": 1, "starch": 1}
    assert ctx(game)["feedback"]["text"] == "The processor grinds the Potato down into Starch."
    assert notes(game)[-1] == "Processed Potato into Starch."
    game.perform("panel.process", {"index": 2})
    assert carried(game)["wrench"] == 1


def test_everything_the_processor_and_the_formulas_make_is_a_real_item():
    for item_id in list(PROCESSOR_RESULTS) + list(PROCESSOR_RESULTS.values()):
        assert get_item_definition(item_id) is not None, item_id
    for compound in COMPOUNDS.values():
        assert get_item_definition(compound["item"]) is not None


def test_compounds_treat_what_they_are_for():
    game = give(new_game(), "burn_salve", "healing_gel", "sober_up")
    game.player_data["damage"]["burn"] = 40
    game.player_data["limbs"]["head"] = 50
    game.player_data["alcohol_percent"] = 12.5
    item_action(game, index_of(game, "burn_salve"), "use")
    assert last_message(game) == ("Burn Salve", "You use the burn salve:\n\nBurn: 40% → 10%")
    item_action(game, index_of(game, "healing_gel"), "use")
    assert last_message(game) == ("Healing Gel", "You use the healing gel:\n\nHead: 50% → 65%")
    item_action(game, index_of(game, "sober_up"), "use")
    assert last_message(game) == ("Sober-Up", "You use the sober-up:\n\nAlcohol: 12.5% → 0.0%")
    assert game.player_data["inventory"] == []
    assert notes(game)[-1] == "Used a sober-up."


def test_a_compound_with_nothing_to_treat_is_kept():
    game = give(new_game(), "sober_up", "antitoxin")
    item_action(game, index_of(game, "sober_up"), "use")
    assert last_message(game) == ("Sober-Up", "You have nothing for the sober-up to treat. It is not needed.")
    item_action(game, index_of(game, "antitoxin"), "use")
    assert last_message(game) == ("Antitoxin", "You have nothing for the antitoxin to treat. It is not needed.")
    assert carried(game) == {"sober_up": 1, "antitoxin": 1}


def test_a_scientist_posted_to_chemistry_gets_a_compound_request(monkeypatch):
    game = new_game("Science", "Scientist", post=CHEMISTRY_KEY)
    event = job_event(monkeypatch, game)
    assert (event["title"], event["desc"]) == (
        "Compound Request", "The Doctor needs a burn salve. Deliver it to the MedBay for 160 credits.")
    event["effect"]()
    assert duty(game) == {
        "kind": "deliver", "giver": "Doctor", "room": MEDBAY_KEY, "item": "burn_salve", "label": "a burn salve",
        "reward": 160, "summary": "Bring a burn salve to the Doctor in the MedBay (160 cr)"}
    assert notes(game)[-1] == "The Doctor requested a burn salve for 160 credits."


def test_no_compound_requests_with_nobody_to_ask(monkeypatch):
    game = new_game("Science", "Scientist", post=CHEMISTRY_KEY)
    game.player_data["station_crew"] = [npc for npc in game.station_crew if npc["job"] == "Staff Assistant"]
    assert job_event(monkeypatch, game) is None


def test_a_reagent_that_left_your_pockets_stops_the_mix():
    game = dispenser(give(in_chemistry(), "aloe_extract", "aloe_extract"))
    add_ingredients(game, "Aloe Extract", "Aloe Extract")
    game.player_data["inventory"][0]["quantity"] = 1
    game.perform("panel.mix", {})
    assert ctx(game)["result"] == {"text": "There isn't enough Aloe Extract left for that.", "color": "orange"}
    assert (carried(game), ctx(game)["glass"]) == ({"aloe_extract": 1}, ["Aloe Extract", "Aloe Extract"])


def test_the_scientist_only_talks_when_they_are_in():
    game = in_chemistry("Civilian", "Staff Assistant")
    scientist = post_holder(game.station_crew, "Scientist", CHEMISTRY_KEY)
    scientist["on_duty"] = False
    game.perform("room.talk_to_scientist", {})
    assert game._messages == []
    scientist["on_duty"] = True
    game.perform("room.talk_to_scientist", {})
    assert last_message(game)[0] == "Scientist"


def test_a_scientist_posted_to_research_works_chemistry_beside_its_own_scientist():
    game = in_chemistry(post=RESEARCH_KEY)
    game.perform("room.open_station", {"mode": "chemistry_station"})
    assert buttons(game)[0] == ("Chemistry Station Controls", None)
    game.ui["room_mode"] = "options"
    assert buttons(game) == [("Talk to Scientist", "room.talk_to_scientist"),
                             ("Back to Station Menu", "room.set_mode")]
    game.perform("room.talk_to_scientist", {})
    assert last_message(game)[0] == "Scientist"


def test_a_scientist_posted_to_chemistry_has_nobody_there_to_talk_to():
    game = in_chemistry()
    game.ui["room_mode"] = "options"
    assert buttons(game) == [("Back to Station Menu", "room.set_mode")]
    game.perform("room.talk_to_scientist", {})
    assert game._messages == []


def test_a_scientist_who_holds_every_lab_gets_the_events_of_one_of_them(monkeypatch):
    game = new_game("Medical", "Doctor")
    game.player_data["job"] = "Scientist"
    assert job_event(monkeypatch, game)["title"] == "Compound Request"


def test_a_lab_with_no_events_of_its_own_brings_its_scientist_none(monkeypatch):
    monkeypatch.delitem(random_events.LAB_EVENT_BUILDERS, RESEARCH_KEY)
    assert job_event(monkeypatch, new_game("Science", "Scientist", post=RESEARCH_KEY)) is None


def test_the_scientist_in_chemistry_asks_a_miner_for_iron_ore_and_takes_it_there(monkeypatch):
    game = new_game("Supply", "Miner")
    game.player_data["station_crew"] = [post_holder(game.station_crew, "Scientist", RESEARCH_KEY),
                                        post_holder(game.station_crew, "Scientist", CHEMISTRY_KEY)]
    event = job_event(monkeypatch, game)
    assert event["desc"] == "The Scientist needs an iron ore. Deliver it to the Chemistry Lab for 160 credits."
    event["effect"]()
    give(game, "iron_ore")
    game.player_data["location"] = location_from_key(RESEARCH_KEY)
    assert ("Deliver Iron Ore", "room.complete_duty") not in buttons(game)
    game.player_data["location"] = location_from_key(CHEMISTRY_KEY)
    assert buttons(game)[0] == ("Deliver Iron Ore", "room.complete_duty")
    game.perform("room.complete_duty", {"duty_id": game.player_data["duties"][0]["id"]})
    assert (game.player_data["duties"], last_message(game)[0]) == ([], "Duty Done")
