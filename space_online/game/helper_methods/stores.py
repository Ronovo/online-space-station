"""The station stores: what the departments make for each other.

player_data["stores"] holds:
    ore       how much ore the Mining Bay has sent up, of any kind. The fabricator builds out of it
    produce   {name: count} of what Botany has sent to the Kitchen. The stove cooks with it
    remedies  how many remedies Chemistry has sent to MedBay. Every treatment there uses one

The NPC holding a post keeps its store topped up on the clock (see crew_work). A player who holds the post has to
do it themself, or the department downstream runs dry.
"""

from space_online.game.maps.donut import ENGINEERING_KEY, KITCHEN_KEY, MEDBAY_KEY
from space_online.game.objects.chemicals import STORE_REMEDY_IDS
from space_online.game.objects.food import KITCHEN_PRODUCE_IDS, PRODUCE
from space_online.game.objects.mining_items import ORE_VALUES

STARTING_ORE = 6
STARTING_PRODUCE = 3
STARTING_REMEDIES = 4
MAX_ORE = 30
MAX_PRODUCE = 8
MAX_REMEDIES = 10

# The room each store belongs to: something for a store that is delivered there goes into it.
STORE_ROOMS = {"ore": ENGINEERING_KEY, "produce": KITCHEN_KEY, "remedies": MEDBAY_KEY}
KITCHEN_PRODUCE = {item_id: PRODUCE[item_id]["name"] for item_id in KITCHEN_PRODUCE_IDS}


def new_stores():
    return {
        "ore": STARTING_ORE,
        "produce": {name: STARTING_PRODUCE for name in KITCHEN_PRODUCE.values()},
        "remedies": STARTING_REMEDIES,
    }


def new_cargo():
    """A fresh Cargo Bay block for player_data.

    orders     [{"item", "arrives_at": game seconds}] for what has been ordered and is on its way. item is an item id,
               or a gas for a canister of it, which also carries its "number". An order the crew requested names its
               "request" by id
    arrived    [item id] for what the Quartermaster ordered that has docked and waits in the bay to be collected
    requests   [{"id", "item", "requester", "price", "decide_at": game seconds, "status"}] for what the crew asked the
               Quartermaster for at the Order Console. status is "waiting", "ordered" or "denied", with its "reason".
               A request leaves the list when its order docks
    pickups    [item id] for what the crew requested that has docked and waits in the bay to be collected
    canisters  the canisters that have docked and wait for a free slot on the Atmospherics Canister Rack
    gas_orders how many canisters of dangerous gas have been ordered this shift
    """
    return {"orders": [], "arrived": [], "requests": [], "pickups": [], "canisters": [], "gas_orders": 0}


def store_of(item_id):
    """Which store an item goes into: "ore", "produce" or "remedies", or None for anything else."""
    if item_id in ORE_VALUES:
        return "ore"
    if item_id in KITCHEN_PRODUCE:
        return "produce"
    if item_id in STORE_REMEDY_IDS:
        return "remedies"
    return None


def add_to_stores(player_data, item_id, count=1):
    """Put count of an item into the store it belongs in, up to what that store holds."""
    stores = player_data["stores"]
    store = store_of(item_id)
    if store == "produce":
        name = KITCHEN_PRODUCE[item_id]
        stores["produce"][name] = min(MAX_PRODUCE, stores["produce"][name] + count)
    else:
        stores[store] = min(MAX_ORE if store == "ore" else MAX_REMEDIES, stores[store] + count)


def send_from_inventory(player_data, store, keep=()):
    """Move everything in the inventory that belongs in store into it, except one of each item id in keep for each
    time it is listed there. Returns ({item name: count} sent, {item name: count} held back)."""
    sent, held, staying = {}, {}, []
    to_hold = list(keep)
    for item in player_data["inventory"]:
        if store_of(item.get("id")) != store:
            staying.append(item)
            continue
        count = item.get("quantity", 1)
        back = min(count, to_hold.count(item["id"]))
        for _ in range(back):
            to_hold.remove(item["id"])
        if back:
            held[item["name"]] = held.get(item["name"], 0) + back
            staying.append(item if back == count else {**item, "quantity": back})
        if count > back:
            add_to_stores(player_data, item["id"], count - back)
            sent[item["name"]] = sent.get(item["name"], 0) + count - back
    player_data["inventory"][:] = staying
    return sent, held


def take_from_stores(player_data, store, count=1):
    """Use up count of the ore or remedies. Returns False, taking nothing, when there isn't that much."""
    stores = player_data["stores"]
    if stores[store] < count:
        return False
    stores[store] -= count
    return True
