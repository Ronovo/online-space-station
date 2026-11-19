import pytest

from helpers import fix_random, give, hold, last_message, new_game
from space_online.game.helper_methods import combat
from space_online.game.helper_methods.combat import (
    COUNTER_MULTIPLIER,
    DEFEAT_HEALTH,
    IMPROVISED_ATTACK,
    MAX_BLOCK,
    STUN_RECHARGE_TURNS,
    TRANSIT_ENEMY_TURN_SECONDS,
    UNARMED_ATTACK,
    attack_power,
    block_percent,
    register_fight,
    start_fight,
    tick_fight,
)
from space_online.game.helper_methods.health_bands import overall_health
from space_online.game.objects.items import get_item_definition

ENDINGS = []
register_fight("drill", lambda game, fight, how: ENDINGS.append(("won", how, fight["enemy"]["name"])),
               lambda game, fight: ENDINGS.append(("lost", fight["enemy"]["name"])))


@pytest.fixture(autouse=True)
def fresh_endings():
    ENDINGS.clear()


def rolls(monkeypatch, randint=lambda low, high: low):
    fix_random(monkeypatch, combat, randint=randint)


def fighting(monkeypatch, hp=30, humanoid=True, extra=None, **hands):
    game = hold(new_game(), **hands)
    rolls(monkeypatch)
    start_fight(game, "drill", {"name": "the dummy", "hp": hp, "attack": (6, 12), "extra": extra,
                                "humanoid": humanoid}, "A dummy squares up to you.")
    return game


def fight(game):
    return game.player_data["fight"]


def screen(game):
    return game.view()["screen"]


def test_what_is_in_your_hands_sets_your_attack_and_block():
    game = new_game()
    assert (attack_power(game.player_data), block_percent(game.player_data)) == (UNARMED_ATTACK, 0)
    hold(game, left="pickaxe", right="blast_shield")
    assert (attack_power(game.player_data), block_percent(game.player_data)) == (15, 50)
    hold(game, left="watering_can", right="chainsaw")
    assert (attack_power(game.player_data), block_percent(game.player_data)) == (25, 0)
    hold(game, left="watering_can")
    assert attack_power(game.player_data) == IMPROVISED_ATTACK
    hold(game, left="blast_shield", right="blast_shield")
    assert block_percent(game.player_data) == MAX_BLOCK


def test_every_weapon_hits_harder_than_bare_hands():
    for item_id in ("crowbar", "combat_knife", "fire_axe", "energy_sword", "stun_baton"):
        game = hold(new_game(), left=item_id)
        assert attack_power(game.player_data) > UNARMED_ATTACK, item_id
    attacks = [get_item_definition(item_id)["attributes"]["attack"]
               for item_id in ("crowbar", "combat_knife", "fire_axe", "energy_sword")]
    assert attacks == sorted(set(attacks))


def test_the_fight_screen_shows_the_enemy_and_this_turns_choices(monkeypatch):
    game = fighting(monkeypatch)
    view = game.view()
    assert view["title"] == "Fight: The dummy"
    shown = screen(game)
    assert (shown["type"], shown["heading"], shown["hp"], shown["max_hp"], shown["stunned"]) == (
        "fight", "The dummy", 30, 30, 0)
    assert shown["log"] == ["A dummy squares up to you."]
    assert (shown["attack"], shown["block"]) == (UNARMED_ATTACK, 0)
    assert (shown["health"], shown["defeat_health"]) == (100, DEFEAT_HEALTH)
    game.player_data["limbs"]["head"] = 40
    assert screen(game)["health"] == int(overall_health(game.player_data)) < 100
    assert shown["actions"] == [{"label": "Attack", "action": "fight.attack"},
                                {"label": "Block", "action": "fight.block"}]


def test_attacking_hurts_the_enemy_and_it_hits_back(monkeypatch):
    game = fighting(monkeypatch, left="pickaxe")
    game.perform("fight.attack", {})
    assert fight(game)["enemy"]["hp"] == 15
    assert game.player_data["limbs"]["head"] == 94
    assert fight(game)["log"] == ["You hit the dummy for 15.", "The dummy hits your head for 6. It is at 94%."]


def test_beating_the_enemy_ends_the_fight(monkeypatch):
    game = fighting(monkeypatch, left="energy_sword", right="pickaxe")
    game.perform("fight.attack", {})
    assert (fight(game), ENDINGS) == (None, [("won", "beaten", "the dummy")])
    assert game.player_data["limbs"]["head"] == 100
    assert screen(game)["type"] == "quarters"


def test_blocking_stops_most_of_a_hit_and_sets_up_a_counter_attack(monkeypatch):
    game = fighting(monkeypatch, left="pickaxe", right="blast_shield")
    rolls(monkeypatch, randint=lambda low, high: high)
    game.perform("fight.block", {})
    assert game.player_data["limbs"]["head"] == 99
    assert fight(game)["log"] == ["You brace behind your guard, ready to strike back.",
                                  "The dummy hits your head for 1. It is at 99%."]
    game.perform("fight.attack", {})
    assert fight(game)["enemy"]["hp"] == 30 - round(15 * COUNTER_MULTIPLIER)
    assert game.player_data["limbs"]["head"] == 93
    game.perform("fight.attack", {})
    assert fight(game) is None


def test_a_single_use_weapon_is_gone_after_one_attack(monkeypatch):
    game = fighting(monkeypatch, hp=100, left="acid_flask", right="pickaxe")
    game.perform("fight.attack", {})
    assert fight(game)["log"][:2] == ["You hit the dummy for 30.", "The Acid Flask is used up."]
    assert game.player_data["hands"]["left"] is None
    assert game.player_data["hands"]["right"]["id"] == "pickaxe"


def test_some_enemies_burn_or_poison(monkeypatch):
    game = fighting(monkeypatch, extra=("burn", 6), right="blast_shield")
    game.perform("fight.attack", {})
    assert game.player_data["damage"]["burn"] == 3
    assert fight(game)["log"][-1] == "The dummy hits your head for 3. It is at 97%. You take 3% burn damage."


def test_taking_too_much_loses_the_fight(monkeypatch):
    game = fighting(monkeypatch)
    game.player_data["limbs"] = {limb: DEFEAT_HEALTH for limb in game.player_data["limbs"]}
    game.perform("fight.block", {})
    assert (fight(game), ENDINGS) == (None, [("lost", "the dummy")])


def in_transit(game):
    game.player_data["round"]["shuttle"]["state"] = "transit"
    return game


def wait(game, seconds):
    game.player_data["game_clock"]["elapsed_seconds"] += seconds
    tick_fight(game)


def test_aboard_the_shuttle_in_flight_the_enemy_does_not_wait_for_the_player(monkeypatch):
    game = in_transit(fighting(monkeypatch))
    wait(game, TRANSIT_ENEMY_TURN_SECONDS - 1)
    assert game.player_data["limbs"]["head"] == 100
    wait(game, 1)
    assert fight(game)["log"] == ["You hesitate.", "The dummy hits your head for 6. It is at 94%."]
    wait(game, TRANSIT_ENEMY_TURN_SECONDS - 1)
    assert game.player_data["limbs"]["head"] == 94
    game.perform("fight.attack", {})
    wait(game, TRANSIT_ENEMY_TURN_SECONDS - 1)
    assert game.player_data["limbs"]["head"] == 88
    wait(game, 1)
    assert game.player_data["limbs"]["head"] == 82


def test_a_fight_left_alone_in_flight_is_lost(monkeypatch):
    game = in_transit(fighting(monkeypatch))
    game.player_data["limbs"] = {limb: DEFEAT_HEALTH for limb in game.player_data["limbs"]}
    wait(game, TRANSIT_ENEMY_TURN_SECONDS)
    assert (fight(game), ENDINGS) == (None, [("lost", "the dummy")])
    wait(game, TRANSIT_ENEMY_TURN_SECONDS)
    assert ENDINGS == [("lost", "the dummy")]


def test_on_the_station_the_enemy_waits_for_the_player(monkeypatch):
    game = fighting(monkeypatch)
    wait(game, 10 ** 6)
    assert (game.player_data["limbs"]["head"], fight(game)["log"]) == (100, ["A dummy squares up to you."])


def test_a_stun_baton_makes_the_enemy_lose_its_turns(monkeypatch):
    game = fighting(monkeypatch, hp=200, left="stun_baton")
    assert {"label": "Stun", "action": "fight.stun"} in screen(game)["actions"]
    game.perform("fight.stun", {})
    assert fight(game)["log"] == ["You jab the dummy with the baton. It locks up.",
                                  "The dummy is stunned and can't strike."]
    assert (fight(game)["stunned"], screen(game)["stunned"]) == (1, 1)
    game.perform("fight.attack", {})
    assert fight(game)["log"][-1] == "The dummy is stunned and can't strike."
    game.perform("fight.stun", {})
    assert last_message(game) == ("Stun", "The baton is still recharging. It will be ready in 2 turns.")
    game.perform("fight.attack", {})
    assert game.player_data["limbs"]["head"] == 94
    for _ in range(STUN_RECHARGE_TURNS):
        game.perform("fight.attack", {})
    game.perform("fight.stun", {})
    assert fight(game)["stunned"] == 1


def test_stunning_needs_a_baton_in_hand(monkeypatch):
    game = give(fighting(monkeypatch, left="pickaxe"), "stun_baton")
    assert [action["label"] for action in screen(game)["actions"]] == ["Attack", "Block"]
    game.perform("fight.stun", {})
    assert (fight(game)["stunned"], fight(game)["log"]) == (0, ["A dummy squares up to you."])


def test_handcuffs_arrest_a_stunned_humanoid(monkeypatch):
    game = give(fighting(monkeypatch, hp=200, left="stun_baton"), "handcuffs")
    assert {"label": "Cuff", "action": "fight.cuff"} in screen(game)["actions"]
    game.perform("fight.cuff", {})
    assert last_message(game) == ("Handcuffs", "The dummy won't hold still. Stun them first.")
    game.perform("fight.stun", {})
    game.perform("fight.cuff", {})
    assert (fight(game), ENDINGS) == (None, [("won", "cuffed", "the dummy")])


def test_handcuffs_are_no_use_without_them_or_on_something_that_is_not_humanoid(monkeypatch):
    game = give(fighting(monkeypatch, hp=200, humanoid=False, left="stun_baton"), "handcuffs")
    assert "Cuff" not in [action["label"] for action in screen(game)["actions"]]
    game.perform("fight.stun", {})
    game.perform("fight.cuff", {})
    assert fight(game) is not None
    game = fighting(monkeypatch, hp=200, left="stun_baton")
    game.perform("fight.stun", {})
    game.perform("fight.cuff", {})
    assert (fight(game) is not None, ENDINGS) == (True, [])


def test_a_fight_cannot_be_walked_away_from_but_hands_can_be_changed(monkeypatch):
    game = give(fighting(monkeypatch, hp=200), "pickaxe")
    location = dict(game.player_data["location"])
    for action in ("game.move", "game.character_sheet", "game.save_and_exit", "room.door", "room.bed"):
        game.perform(action, {"direction": "north"})
    assert (game.player_data["location"], game.ui["panels"], game.redirect) == (location, [], None)

    game.perform("game.hands", {})
    assert game.view()["panel"]["type"] == "hands"
    game.perform("fight.attack", {})
    assert fight(game)["enemy"]["hp"] == 200
    game.perform("panel.select", {"index": 0})
    game.perform("panel.equip", {"side": "right"})
    game.perform("game.close_panel", {})
    assert screen(game)["attack"] == 15
    game.perform("fight.attack", {})
    assert fight(game)["enemy"]["hp"] == 185


def test_starting_a_fight_closes_whatever_was_open(monkeypatch):
    game = new_game()
    game.perform("game.character_sheet", {})
    rolls(monkeypatch)
    start_fight(game, "drill", {"name": "the dummy", "hp": 5, "attack": (1, 1), "extra": None, "humanoid": True},
                "It attacks!")
    assert (game.ui["panels"], game.view()["panel"]) == ([], None)


def test_fight_actions_do_nothing_outside_a_fight(monkeypatch):
    game = new_game()
    for action in ("attack", "block", "stun", "cuff"):
        game.perform(f"fight.{action}", {})
    assert (game._messages, fight(game)) == ([], None)
    game = fighting(monkeypatch)
    game.perform("fight.flee", {})
    assert fight(game)["log"] == ["A dummy squares up to you."]
