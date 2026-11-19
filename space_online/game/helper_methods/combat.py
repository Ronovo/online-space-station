"""Turn-based fights, used for planet monsters and for the station's antagonists.

player_data["fight"] holds the fight in progress, or None:
    kind      which FIGHT_ENDINGS entry settles it
    enemy     {"name", "hp", "max_hp", "attack": (low, high), "extra": (damage type, amount) or None, "humanoid"};
              its name is written as it reads mid-sentence, e.g. "the Sand Crawler"
    braced    True after a Block, so the next Attack is a counter-attack
    stunned   turns the enemy still loses
    recharge  turns until a stun baton can stun again
    log       what the last turn did
    last_turn_at  game seconds at which the enemy last had its turn, or the fight began
plus whatever the code that started it passed along for its ending to use.
"""

import random

from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.health_bands import LIMBS, change_limb, limb_label, overall_health
from space_online.game.objects.items import HAND_SIDES, carried_or_held, held_items

UNARMED_ATTACK = 3
# A held item with no attack of its own still hits a little.
IMPROVISED_ATTACK = 2
MAX_BLOCK = 80
# Blocking adds BRACE_BLOCK to the held items' block for that hit, up to MAX_BRACED_BLOCK.
BRACE_BLOCK = 40
MAX_BRACED_BLOCK = 90
COUNTER_MULTIPLIER = 1.5
STUN_RECHARGE_TURNS = 4
# Below this overall health the fight is lost.
DEFEAT_HEALTH = 30
# Aboard the shuttle in flight the enemy takes its turn this often, whether or not the player acts.
TRANSIT_ENEMY_TURN_SECONDS = 10

# kind -> (won(game, fight, how), lost(game, fight)); how is "beaten" or "cuffed".
FIGHT_ENDINGS = {}


def capitalized(text):
    """text with its first letter upper case, for a name that starts a sentence."""
    return text[:1].upper() + text[1:]


def register_fight(kind, won, lost):
    FIGHT_ENDINGS[kind] = (won, lost)


def attack_power(player_data):
    """Damage an Attack does: that of the stronger held item, or bare fists."""
    held = held_items(player_data)
    if not held:
        return UNARMED_ATTACK
    return max(item.get("attributes", {}).get("attack", IMPROVISED_ATTACK) for item in held)


def block_percent(player_data):
    """Percentage of every hit the held items stop."""
    return min(MAX_BLOCK, sum(item.get("attributes", {}).get("block", 0) for item in held_items(player_data)))


def _stun_turns(player_data):
    """Turns a held stun weapon makes an enemy lose, or 0 with none in hand."""
    return max((item.get("attributes", {}).get("stun", 0) for item in held_items(player_data)), default=0)


def _has_handcuffs(player_data):
    return carried_or_held(player_data, ("handcuffs",)) is not None


def start_fight(game, kind, enemy, intro, **details):
    """Put the player in a fight they can't walk away from."""
    game.player_data["fight"] = {
        "kind": kind,
        "enemy": {**enemy, "max_hp": enemy["hp"]},
        "braced": False,
        "stunned": 0,
        "recharge": 0,
        "log": [intro],
        "last_turn_at": get_elapsed_seconds(game.player_data),
        **details,
    }
    game.ui["panels"] = []


def fight_view(game):
    """The fight screen: the enemy, what just happened, and this turn's choices."""
    player_data = game.player_data
    fight = player_data["fight"]
    enemy = fight["enemy"]
    actions = [("Attack", "attack"), ("Block", "block")]
    if _stun_turns(player_data):
        actions.append(("Stun", "stun"))
    if enemy["humanoid"] and _has_handcuffs(player_data):
        actions.append(("Cuff", "cuff"))
    return {
        "type": "fight",
        "title": f"Fight: {capitalized(enemy['name'])}",
        "heading": capitalized(enemy["name"]),
        "style": {"bg": "black", "fg": "white"},
        "hp": enemy["hp"],
        "max_hp": enemy["max_hp"],
        "stunned": fight["stunned"],
        "log": fight["log"],
        "attack": attack_power(player_data),
        "block": block_percent(player_data),
        "health": int(overall_health(player_data)),
        "defeat_health": DEFEAT_HEALTH,
        "actions": [{"label": label, "action": f"fight.{name}"} for label, name in actions],
    }


def _end(game, won, how=None):
    fight = game.player_data["fight"]
    game.player_data["fight"] = None
    on_won, on_lost = FIGHT_ENDINGS[fight["kind"]]
    if won:
        on_won(game, fight, how)
    else:
        on_lost(game, fight)


def _spend_single_use(player_data):
    """Empty the hands of items that only work once. Returns a log line for each."""
    hands = player_data["hands"]
    lines = []
    for side, _ in HAND_SIDES:
        item = hands[side]
        if item and item.get("attributes", {}).get("single_use"):
            hands[side] = None
            lines.append(f"The {item['name']} is used up.")
    return lines


def _enemy_turn(game, blocked_percent):
    """The enemy hits a limb for what gets past the block, unless it is stunned. Too much and the fight is lost."""
    player_data = game.player_data
    fight = player_data["fight"]
    enemy = fight["enemy"]
    fight["last_turn_at"] = get_elapsed_seconds(player_data)
    fight["recharge"] = max(0, fight["recharge"] - 1)
    if fight["stunned"]:
        fight["stunned"] -= 1
        fight["log"].append(f"{capitalized(enemy['name'])} is stunned and can't strike.")
        return

    kept = 1 - blocked_percent / 100
    damage = round(random.randint(*enemy["attack"]) * kept)
    limb = random.choice(LIMBS)
    _, after = change_limb(player_data, limb, -damage)
    line = f"{capitalized(enemy['name'])} hits your {limb_label(limb).lower()} for {damage}. It is at {after}%."
    if enemy["extra"]:
        dtype, amount = enemy["extra"]
        amount = round(amount * kept)
        player_data["damage"][dtype] = min(100, player_data["damage"][dtype] + amount)
        line += f" You take {amount}% {dtype} damage."
    fight["log"].append(line)
    if overall_health(player_data) < DEFEAT_HEALTH:
        _end(game, won=False)


def attack(game):
    player_data = game.player_data
    fight = player_data["fight"]
    enemy = fight["enemy"]
    damage = attack_power(player_data)
    if fight["braced"]:
        damage = round(damage * COUNTER_MULTIPLIER)
        fight["braced"] = False
    enemy["hp"] -= damage
    fight["log"] = [f"You hit {enemy['name']} for {damage}."] + _spend_single_use(player_data)
    if enemy["hp"] > 0:
        _enemy_turn(game, block_percent(player_data))
    else:
        _end(game, won=True, how="beaten")


def block(game):
    fight = game.player_data["fight"]
    fight["braced"] = True
    fight["log"] = ["You brace behind your guard, ready to strike back."]
    _enemy_turn(game, min(MAX_BRACED_BLOCK, block_percent(game.player_data) + BRACE_BLOCK))


def stun(game):
    """Make the enemy lose its next turns with a held stun weapon, which then has to recharge."""
    player_data = game.player_data
    fight = player_data["fight"]
    turns = _stun_turns(player_data)
    if not turns:
        return
    if fight["recharge"]:
        game.alert("Stun", f"The baton is still recharging. It will be ready in {fight['recharge']} turns.")
        return
    fight["stunned"] = turns
    fight["recharge"] = STUN_RECHARGE_TURNS
    fight["log"] = [f"You jab {fight['enemy']['name']} with the baton. It locks up."]
    _enemy_turn(game, block_percent(player_data))


def cuff(game):
    """Handcuff a stunned humanoid enemy, which ends the fight on the spot."""
    player_data = game.player_data
    fight = player_data["fight"]
    enemy = fight["enemy"]
    if not enemy["humanoid"] or not _has_handcuffs(player_data):
        return
    if not fight["stunned"]:
        game.alert("Handcuffs", f"{capitalized(enemy['name'])} won't hold still. Stun them first.")
        return
    _end(game, won=True, how="cuffed")


def tick_fight(game):
    """Give the enemy its turn in a fight aboard the shuttle in flight, where waiting it out would hold the
    shuttle up for ever."""
    player_data = game.player_data
    fight = player_data["fight"]
    if not fight or player_data["round"]["shuttle"]["state"] != "transit":
        return
    if get_elapsed_seconds(player_data) - fight["last_turn_at"] >= TRANSIT_ENEMY_TURN_SECONDS:
        fight["log"] = ["You hesitate."]
        _enemy_turn(game, block_percent(player_data))


FIGHT_ACTIONS = {"attack": attack, "block": block, "stun": stun, "cuff": cuff}
