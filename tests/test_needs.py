import time
from types import SimpleNamespace

from helpers import html, new_game
from space_online.game.helper_methods import needs
from space_online.game.helper_methods.needs import (
    NEED_PER_MINUTE,
    NEED_WARNING,
    STARVING_DAMAGE,
    STARVING_HURT_SECONDS,
    new_needs,
    satisfy,
    tick_needs,
)
from space_online.game.maps.donut import KITCHEN_KEY, location_from_key
from space_online.game.special_rooms.kitchen import BASIC_FEEDS, DISH_FEEDS


def test_a_shift_starts_fed_and_watered():
    assert new_game().player_data["needs"] == new_needs() == {"hunger": 0, "thirst": 0}


def test_hunger_and_thirst_climb_with_the_clock_and_say_so_as_they_get_serious():
    game = new_game()
    tick_needs(game, 60)
    assert game.player_data["needs"] == {"hunger": NEED_PER_MINUTE["hunger"], "thirst": NEED_PER_MINUTE["thirst"]}
    assert game._messages == []
    game.player_data["needs"] = {"hunger": NEED_WARNING - 1, "thirst": 99}
    tick_needs(game, 60)
    assert game._messages == [
        ("Hunger", "You are getting hungry. The Kitchen serves food.", "warning"),
        ("Thirst", "You are parched. Drink something before it wears you down.", "error"),
    ]
    assert game.player_data["needs"]["thirst"] == 100
    tick_needs(game, 60)
    assert len(game._messages) == 2


def test_a_need_left_at_its_worst_wears_the_limbs_down_until_it_is_met(monkeypatch):
    monkeypatch.setattr(needs, "random", SimpleNamespace(choice=lambda limbs: limbs[0]))
    game = new_game()
    game.player_data["needs"]["hunger"] = 100
    tick_needs(game, STARVING_HURT_SECONDS - 1)
    assert game.player_data["limbs"]["head"] == 100
    tick_needs(game, 1 + STARVING_HURT_SECONDS)
    assert game.player_data["limbs"]["head"] == 100 - 2 * STARVING_DAMAGE
    assert satisfy(game.player_data, "hunger", 30) == 70
    tick_needs(game, 1)
    assert game.player_data["damage_timers"]["needs_acc"] == 0.0
    assert satisfy(game.player_data, "hunger", 500) == 0


def test_the_master_clock_runs_the_needs():
    game = new_game()
    game.player_data["game_clock"]["last_real_time"] = time.time() - 60
    game.tick()
    assert round(game.player_data["needs"]["thirst"]) == NEED_PER_MINUTE["thirst"]


def test_a_cooked_dish_feeds_more_than_a_basic():
    game = new_game()
    game.player_data.update(location=location_from_key(KITCHEN_KEY), kitchen_stock={"Omelette": 1})
    game.perform("room.show_menu", {})
    for name in ("Omelette", "Bread Roll"):
        game.perform("panel.select", {"name": name})
        game.perform("panel.order", {})
    feeds = {item["name"]: item["attributes"]["feeds"] for item in game.player_data["inventory"]}
    assert feeds == {"Omelette": DISH_FEEDS, "Bread Roll": BASIC_FEEDS}


def test_the_character_sheet_shows_hunger_and_thirst(app):
    game = new_game()
    game.player_data["needs"] = {"hunger": 72.4, "thirst": 5}
    game.perform("game.character_sheet", {})
    assert game.view()["panel"]["ctx"]["needs"] == [{"name": "Hunger", "value": 72.4, "color": "red"},
                                                    {"name": "Thirst", "value": 5, "color": "green"}]
    page = html(app, game)
    assert "Hunger: 72%" in page and "Thirst: 5%" in page


def test_the_character_sheet_closes_from_its_header_and_shows_both_health_lines(app):
    game = new_game()
    game.perform("game.character_sheet", {})
    page = html(app, game)
    header = page.split('class="panel-header"', 1)[1].split("</div>", 1)[0]
    assert 'data-action="game.close_panel"' in header
    assert page.count('data-action="game.close_panel"') == 1
    assert "Non-Limb Health: " in page and '">Limb Health: ' in page


def test_items_on_the_floor_show_under_the_screen_with_a_pick_up_button_each(app):
    game = new_game()
    game.player_data["floor"]["-1,0"] = [{"id": "snack", "name": "Snack", "quantity": 2}]
    page = html(app, game)
    assert "On the Floor Here" in page and "Pick Up Snack x 2" in page
    game.perform("game.character_sheet", {})
    assert "On the Floor Here" not in html(app, game)
