from space_online.game.helper_methods.mixing import (
    MixingStation,
    RecipeBook,
    Supply,
    match_recipe,
    register_mixing_station,
    register_recipe_book,
)
from space_online.game.helper_methods.ui_panels import current_feedback, panel_action, register_panel, set_feedback
from space_online.game.maps.donut import CHEMISTRY_KEY
from space_online.game.objects.chemicals import (
    COMPOUNDS,
    DISPENSER,
    DISPENSER_CHEMICALS,
    MAX_BEAKER_CHEMICALS,
    PROCESSOR_RESULTS,
    get_compound_feedback,
    reagent_of,
)
from space_online.game.objects.items import (
    GAS_TANK_ID,
    add_to_inventory,
    format_inventory_label,
    get_item_definition,
    heals_text,
    item_quantity,
    item_scanner,
    remove_one_from_inventory,
    tank_readout,
)
from space_online.game.special_rooms.shared import (
    SpecialRoomBase,
    available_npc,
    button,
    npc_contact_widgets,
    room_action,
    send_to_stores,
    text_line,
)


@item_scanner("Scientist")
def chemical_reading(item):
    """An item's chemistry: what it is in the beaker, what it processes into, what it is made of and what it does,
    or a Gas Tank's gauge."""
    if item.get("id") == GAS_TANK_ID:
        return tank_readout(item)
    attributes = item.get("attributes") or {}
    facts = []
    reagent = reagent_of(item)
    if reagent:
        facts.append(f"Goes into the beaker as {reagent}.")
    if item.get("id") in PROCESSOR_RESULTS:
        facts.append(f"The processor makes {get_item_definition(PROCESSOR_RESULTS[item['id']])['name']} of it.")
    compound = next((details for details in COMPOUNDS.values() if details["item"] == item.get("id")), None)
    if compound:
        facts.append(f"A compound of {', '.join(compound['ingredients'])}.")
    if heals_text(item):
        facts.append(f"Treats: {heals_text(item)}.")
    if attributes.get("alcohol_content"):
        facts.append(f"Alcohol: {attributes['alcohol_content']}%.")
    return " ".join(facts) or "No chemical properties on record."


def _dispenser_shelf(game):
    return {"All": ("All Chemicals", DISPENSER_CHEMICALS),
            **{name: (name, chemicals) for name, chemicals in DISPENSER.items()}}


def _carried_reagents(game):
    """{chemical: count} of what the inventory's liquids and reagents can add to the beaker."""
    counts = {}
    for item in game.player_data["inventory"]:
        chemical = reagent_of(item)
        if chemical:
            counts[chemical] = counts.get(chemical, 0) + item_quantity(item)
    return counts


def _use_reagent(game, chemical):
    """Pour one inventory item that gives chemical into the beaker."""
    inventory = game.player_data["inventory"]
    index = next(i for i, item in enumerate(inventory) if reagent_of(item) == chemical)
    remove_one_from_inventory(game.player_data, index)


def _mix_compound(game, ingredients):
    compound, recipe = match_recipe(COMPOUNDS, ingredients)
    if not compound:
        return {"text": f"The mixture fizzles into grey sludge. {get_compound_feedback(ingredients)}",
                "color": "red"}
    add_to_inventory(game.player_data, get_item_definition(recipe["item"]))
    game.add_note(f"Mixed {compound} at the chemical dispenser.")
    return {
        "text": f"Success! You've made {compound}.\n{recipe['desc']}\nIt has been added to your inventory.",
        "color": "lightgreen",
    }


DISPENSER_STATION = register_mixing_station(MixingStation(
    panel="dispenser",
    title="Chemical Dispenser",
    name="Dispenser",
    container="beaker",
    container_label="Beaker",
    mix_label="Mix Compound",
    idle_text="Add chemicals to the beaker and mix a compound",
    capacity=MAX_BEAKER_CHEMICALS,
    shelf=_dispenser_shelf,
    mix=_mix_compound,
    supplies=(Supply(key="Inventory", heading="From Your Inventory", counts=_carried_reagents, take=_use_reagent),),
    book="formulas",
))

register_recipe_book(RecipeBook(
    panel="formulas",
    title="Scientist's Formula Book",
    recipes=COMPOUNDS,
    categories=(("all", "All Formulas"),),
    sections=lambda category: [("COMPOUNDS", sorted(COMPOUNDS))],
))


def _processable(game):
    """(inventory index, item, what it becomes) for each carried item the processor can break down."""
    return [(index, item, get_item_definition(PROCESSOR_RESULTS[item["id"]]))
            for index, item in enumerate(game.player_data["inventory"]) if item.get("id") in PROCESSOR_RESULTS]


@register_panel("processor", "Processor")
def processor_panel(game, state):
    return {
        "items": [{"index": index, "label": format_inventory_label(item), "makes": result["name"]}
                  for index, item, result in _processable(game)],
        "feedback": current_feedback(state),
    }


@panel_action("processor")
def process(game, state, args):
    index = int(args["index"])
    match = next((entry for entry in _processable(game) if entry[0] == index), None)
    if match is None:
        return
    _, item, result = match
    remove_one_from_inventory(game.player_data, index)
    add_to_inventory(game.player_data, result)
    game.add_note(f"Processed {item['name']} into {result['name']}.")
    set_feedback(state, f"The processor grinds the {item['name']} down into {result['name']}.")


class Chemistry(SpecialRoomBase):
    ROOM_TITLE = "Chemistry"
    ROOM_HEADING = "Chemistry Lab"
    ROOM_DESCRIPTION = (
        "The chemistry lab is spotless and brightly lit. A chemical dispenser takes up one wall, a "
        "processor sits on the bench beside it, and racks of glassware line the shelves."
    )
    DOOR_KEY = CHEMISTRY_KEY
    STATION_ENTRIES = ({"label": "Enter Chemistry Station", "mode": "chemistry_station"},)
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
        if mode != "chemistry_station" or not self.station_allowed(mode):
            return None
        return [
            text_line("Chemistry Station Controls", style="title"),
            button("Chemical Dispenser", "room.access_dispenser"),
            button("Processor", "room.access_processor"),
            button("Formula Book", "room.show_formulas"),
            button("Send Remedies to MedBay", "room.send_remedies"),
            button("Back to Station Menu", "room.set_mode", mode="menu"),
        ]

    @room_action
    def talk_to_scientist(self):
        if available_npc(self.game, "Scientist", self.DOOR_KEY):
            self.game.alert("Scientist", "The scientist doesn't look up from a bubbling flask. 'Don't touch "
                                         "anything.'")

    @room_action(station="chemistry_station")
    def access_dispenser(self):
        self.game.open_panel(DISPENSER_STATION.panel)

    @room_action(station="chemistry_station")
    def access_processor(self):
        self.game.open_panel("processor")

    @room_action(station="chemistry_station")
    def show_formulas(self):
        self.game.open_panel(DISPENSER_STATION.book)

    @room_action(station="chemistry_station")
    def send_remedies(self):
        send_to_stores(self.game, "remedies", "MedBay", "You have no remedies MedBay treats with.")
