import re
from pathlib import Path

from flask import render_template_string
from markupsafe import escape

from helpers import board_shuttle, buttons, give, give_duty, html, in_room, menu_widgets, new_game
from space_online.game.character_methods.character_creation import JOBS
from space_online.game.helper_methods.combat import start_fight
from space_online.game.helper_methods.hazards import set_hazard
from space_online.game.helper_methods.rounds import ANTAGONIST
from space_online.game.main import SPECIAL_ROOM_CLASSES
from space_online.game.maps.donut import (
    BAR_KEY,
    BOTANY_KEY,
    CHEMISTRY_KEY,
    KITCHEN_KEY,
    MINING_KEY,
    QUARTERS_KEY,
)
from space_online.game.objects.items import get_item_definition


def as_json(app, value):
    """value as a button's data-args holds it."""
    with app.test_request_context():
        return render_template_string("{{ value|tojson }}", value=value)


def test_the_stock_market_shows_news_and_a_price_on_every_company(app):
    game = new_game()
    game.market_engine.news = [{"company": "TechCorp", "direction": "down", "text": "TechCorp slips", "real": False}]
    game.player_data["stock_holdings"] = {"TechCorp": 4}
    game.open_panel("stock_market")
    page = html(app, game)
    assert '<p class="news-item trend-down">TechCorp slips</p>' in page
    assert '<span class="company-owned">x4</span>' in page
    assert page.count('class="company-price"') == len(game.market_engine.companies)
    assert 'data-share-input' in page


def test_the_stock_market_with_no_news_and_nothing_listed(app):
    game = new_game()
    game.market_engine.news = []
    game.open_panel("stock_market", ownership="owned")
    page = html(app, game)
    assert "No news this cycle." in page and "No companies match these filters." in page
    assert 'data-share-input' not in page


def test_the_stove_uses_the_mixers_page_with_its_own_words(app):
    game = in_room(KITCHEN_KEY, "Civilian", "Chef", "service_station")
    game.player_data["service_window"]["stock"]["kitchen"] = {"Beer": 2}
    game.perform("room.show_mixer", {})
    page = html(app, game)
    for text in ("<h2>Chef&#39;s Stove</h2>", "<legend>Pan</legend>", "Clear Pan", "Cook Dish",
                 "Add ingredients to the pan and cook a dish", ">Beer (2)</button>", ">Egg</button>"):
        assert text in page, text


def test_the_food_menu_and_the_chefs_recipe_book(app):
    game = in_room(KITCHEN_KEY, "Civilian", "Chef", "service_station")
    game.perform("room.show_menu", {})
    page = html(app, game)
    assert "<h2>Food Menu</h2>" in page and "Order Selected Dish" in page and "Bread Roll - free" in page
    game.ui["panels"] = []
    game.perform("room.show_recipes", {})
    page = html(app, game)
    assert "<h2>Chef&#39;s Recipe Book</h2>" in page and "<b>Price:</b> 18 credits" in page
    assert "Ingredients List" not in page


def test_the_bartenders_recipe_book_keeps_its_ingredients_list(app):
    game = in_room(BAR_KEY, "Civilian", "Bartender", "service_station")
    game.perform("room.show_recipes", {})
    assert "Ingredients List" in html(app, game)


def test_the_service_window_from_both_sides(app):
    game = in_room(KITCHEN_KEY, "Civilian", "Chef", "service_station")
    window = game.player_data["service_window"]
    window["requests"]["bar"] = {"Celery": 2}
    window["stock"]["kitchen"] = {"Wine": 1}
    game.perform("room.show_window", {})
    page = html(app, game)
    for text in ("<legend>Your Ingredients</legend>", "Put on the Window", "<legend>The Bartender Is Asking For</legend>",
                 '<div class="list-item">Celery x 2</div>', '<div class="list-item">Wine x 1</div>',
                 "<legend>On the Window for the Bar</legend>", "Nothing yet."):
        assert text in page, text
    game.perform("panel.mode", {"name": "ask"})
    page = html(app, game)
    assert "<legend>The Bartender&#39;s Ingredients</legend>" in page and "Ask the Bartender" in page


def test_the_dispenser_the_formula_book_and_the_processor(app):
    game = give(in_room(CHEMISTRY_KEY, "Science", "Scientist", "chemistry_station"), "potato")
    game.perform("room.access_dispenser", {})
    page = html(app, game)
    assert "<h2>Chemical Dispenser</h2>" in page and "<legend>Beaker</legend>" in page and "Mix Compound" in page
    game.ui["panels"] = []
    game.perform("room.show_formulas", {})
    page = html(app, game)
    assert "<h2>Scientist&#39;s Formula Book</h2>" in page and "<b>Price:</b>" not in page
    game.ui["panels"] = []
    game.perform("room.access_processor", {})
    page = html(app, game)
    assert "Becomes Starch" in page and "Nothing you are carrying can be processed." not in page
    game.perform("panel.process", {"index": 0})
    game.perform("panel.process", {"index": 0})
    assert "The processor grinds the Potato down into Starch." in html(app, game)
    game.player_data["inventory"] = []
    assert "Nothing you are carrying can be processed." in html(app, game)


def test_the_ore_counter_and_the_produce_stand_share_a_page(app):
    game = in_room(MINING_KEY, "Civilian", "Staff Assistant", "menu")
    game.perform("room.buy_ore", {})
    page = html(app, game)
    assert "<h2>Ore Counter</h2>" in page and "Iron Ore - 20 credits" in page
    game = in_room(BOTANY_KEY, "Civilian", "Staff Assistant", "menu")
    game.perform("room.talk_to_botanist", {})
    page = html(app, game)
    assert "<h2>Produce Stand</h2>" in page and "The botanist sells fresh produce from the lab." in page


def test_the_locker_room_and_a_fight_on_the_planet(app):
    game = in_room(MINING_KEY, "Supply", "Miner", "locker_room")
    assert ">Magnet: OFF</button>" in html(app, game)
    give(game, "pickaxe")
    game.perform("room.board_shuttle", {})
    page = html(app, game)
    assert '<h1 class="screen-title">Surface of Kessar IV</h1>' in page and ">Search for Rocks</button>" in page
    start_fight(game, "monster", {"name": "the Sand Crawler", "hp": 30, "attack": (6, 12), "extra": None,
                                  "humanoid": False}, "A Sand Crawler bursts out of the rocks!", monster="Sand Crawler")
    game.player_data["fight"]["enemy"]["hp"] = 12
    page = html(app, game)
    assert '<h1 class="screen-title">The Sand Crawler</h1>' in page and "<b>12/30 HP</b>" in page
    assert "A Sand Crawler bursts out of the rocks!" in page and "Your attack: 3. You block 0% of each hit." in page
    assert "Your health: 100%. The fight is lost if it falls below 30%." in page
    assert ">Attack</button>" in page and ">Block</button>" in page and ">Hands</button>" in page
    assert ">Stun</button>" not in page and ">Search for Rocks</button>" not in page


def test_the_status_bar_and_a_stunned_antagonist(app):
    game = new_game("Security", "Security Guard", mode=ANTAGONIST)
    game.player_data["threats"] = [{
        "type": "Wizard", "crew_name": None, "name": "the Wizard", "starts_at": 0, "next_act_at": 9999, "acts": 4,
        "reveal_after": 2, "revealed": True, "hp": 45, "attack": (8, 15), "extra": ("burn", 6), "humanoid": True,
        "location": {"x": 1, "y": 0}, "fate": None,
    }]
    game.player_data["round"]["shuttle"].update(state="called", until=120, called_at=0, travel=120)
    page = html(app, game)
    for text in ('class="status-bar alert-red"', "ALERT: RED", "Shift T+0m", "Shuttle docks in 2m 0s",
                 "The Wizard was last seen in the Departures Entrance."):
        assert text in page, text
    for item_id, side in (("stun_baton", "left"), ("handcuffs", "right")):
        game.player_data["hands"][side] = get_item_definition(item_id)
    start_fight(game, "threat", {"name": "the Wizard", "hp": 45, "attack": (8, 15), "extra": ("burn", 6),
                                 "humanoid": True}, "The Wizard is here!", threat=0)
    game.perform("fight.stun", {})
    page = html(app, game)
    assert ">Stun</button>" in page and ">Cuff</button>" in page and "Stunned for 1 more" in page


def test_the_station_log_and_the_players_health_show_beside_every_screen(app):
    game = new_game()
    page = html(app, game)
    assert 'data-health="100"' in page and "Nothing to report yet." in page
    game.alert("Power", "Battery low", "warning")
    game.open_panel("character_sheet")
    page = html(app, game)
    assert "log-warning log-new" in page and "Battery low" in page and "Nothing to report yet." not in page


def test_the_duties_panel_lists_what_is_waiting_or_says_nothing_is(app):
    game = new_game()
    game.perform("game.duties", {})
    assert "Nothing is waiting on you right now." in html(app, game)
    give_duty(game, kind="help", room="-1,3", summary="Help at the bar")
    page = html(app, game)
    assert "Help at the bar" in page and "6m 0s left" in page and "0 done, 0 missed" in page
    assert ">Approve</button>" not in page
    request = give_duty(game, kind="command", room=None, summary="Lock down the Bar?")
    page = html(app, game)
    assert page.count(f'data-args=\'{{"duty_id": "{request}"}}\'') == 2
    assert ">Approve</button>" in page and ">Deny</button>" in page


def test_every_list_in_a_panel_keeps_its_scroll_position():
    panels = Path(__file__).resolve().parent.parent / "space_online" / "webapp" / "templates" / "panels"
    unkeyed = [f"{template.name}: {tag}" for template in sorted(panels.glob("*.html"))
               for tag in re.findall(r'<[^>]*class="listbox[^>]*>', template.read_text(encoding="utf-8"))
               if "data-scroll-key=" not in tag]
    assert unkeyed == []


def test_a_room_menu_holds_only_what_it_shows_for_every_job_in_every_room(app):
    rooms = [room.DOOR_KEY for name, room in SPECIAL_ROOM_CLASSES.items() if name != "Quarters"]
    for job, details in JOBS.items():
        for room_key in rooms:
            for room_mode in ("menu", "options"):
                game = in_room(room_key, details["department"], job, room_mode)
                where = (job, room_key, room_mode)
                assert {widget["kind"] for widget in menu_widgets(game)} <= {"button", "text"}, where
                page = html(app, game)
                assert "slot" not in page[page.index('class="stack room-menu"'):page.index("system-menu")], where


def test_a_staff_assistant_in_botany_sees_just_its_two_buttons():
    assert buttons(in_room(BOTANY_KEY)) == [("View Plants", "room.view_plants"),
                                            ("Talk to Botanist", "room.talk_to_botanist")]


def test_the_lighting_and_hazard_lines_show_only_when_they_have_something_to_say(app):
    def between_description_and_menu(game):
        page = html(app, game)
        return page[page.index('<p class="screen-desc">'):page.index('<div class="stack room-menu">')].count("<p")

    game = in_room(BOTANY_KEY)
    assert between_description_and_menu(game) == 1
    game.player_data["station_power"]["system_levels"]["hallway_lighting"] = 4
    assert between_description_and_menu(game) == 2
    set_hazard(game.player_data, BOTANY_KEY, "fire")
    assert between_description_and_menu(game) == 3


def test_the_status_bar_shows_the_shuttle_only_once_it_is_called(app):
    game = new_game()
    assert "status-shuttle" not in html(app, game)
    game.player_data["round"]["shuttle"].update(state="called", until=600)
    assert '<span class="status-shuttle">' in html(app, game)


def test_a_panel_shows_its_feedback_line_only_with_a_message(app):
    def feedback_line(fb):
        with app.test_request_context():
            return render_template_string('{% import "game/_ui.html" as ui %}{{ ui.feedback(fb) }}', fb=fb).strip()

    assert feedback_line(None) == feedback_line({"text": "", "color": "white"}) == ""
    assert feedback_line({"text": "Done.", "color": "white"}) == '<p class="feedback" style="color: white">Done.</p>'


LIST_PANELS = ("notes", "pda_messages", "duties", "incident_log", "ore_log", "crew_manifest", "coffee_recipes",
               "ingredients", "trade_history")


def test_every_list_panel_has_its_one_close_button_above_the_list(app):
    for panel in LIST_PANELS:
        game = new_game()
        game.open_panel(panel)
        page = html(app, game)
        assert page.count('data-action="game.close_panel"') == 1, panel
        assert page.index('data-action="game.close_panel"') < page.index('class="text-block"'), panel


# Panels whose way out is one of the choices on a short prompt or menu, and the alert that must be acknowledged.
WAY_OUT_IN_THE_CHOICES = ("charge.html", "computer.html", "equip_hand.html", "file_edit.html", "item_actions.html",
                          "oxygen_announcement.html", "pda.html", "put_back_tools.html")


def test_every_other_panel_has_its_way_out_in_the_header():
    panels = Path(__file__).resolve().parent.parent / "space_online" / "webapp" / "templates" / "panels"
    misplaced = [template.name for template in sorted(panels.glob("[!_]*.html"))
                 if template.name not in WAY_OUT_IN_THE_CHOICES
                 and ("ui.panel_header(" not in (text := template.read_text(encoding="utf-8")) or "close_btn" in text)]
    assert misplaced == []


def test_only_raw_text_keeps_its_line_breaks_in_a_text_box():
    css = (Path(__file__).resolve().parent.parent / "space_online" / "webapp" / "static" / "style.css").read_text()
    assert "white-space" not in re.search(r"\n\.text-block \{([^}]*)\}", css).group(1)
    assert "pre.text-block { white-space: pre-wrap; }" in css


def test_the_floor_and_navigation_sit_in_the_bottom_block_above_the_menu(app):
    for location in (None, QUARTERS_KEY, BOTANY_KEY):
        game = in_room(location or QUARTERS_KEY)
        if location is None:
            game.player_data["location"] = {"x": 0, "y": 0}
        game.floor_here().append(dict(get_item_definition("snack")))
        page = html(app, game)
        screen = page[page.index('<section class="screen"'):page.index("</section>", page.index("system-menu"))]
        parts = ['class="screen-desc"', 'class="screen-bottom"', 'class="floor"', 'class="stack system-menu"']
        if location is None:
            parts.insert(3, 'class="nav-grid"')
        assert [screen.index(part) for part in parts] == sorted(screen.index(part) for part in parts), location
        assert page.count('class="floor"') == 1, location


def test_the_station_log_fills_its_column_from_an_inner_box(app):
    page = html(app, new_game())
    assert page.index('class="log-body"') < page.index('class="log-lines"') < page.index("</aside>")


def save_and_exit(page):
    """Whether Save and Exit can be pressed in the status bar, and whether any appears below the status bar."""
    bar, rest = page.split('<div class="game-columns">', 1)
    return ('data-action="game.save_and_exit"' in bar, ">Save and Exit</button>" in rest)


def test_save_and_exit_is_only_in_the_status_bar_and_only_in_the_hallway_and_quarters(app):
    hallway = new_game()
    quarters = in_room(QUARTERS_KEY)
    room = in_room(BAR_KEY, "Civilian", "Bartender", "menu")
    pages = [html(app, game) for game in (hallway, quarters, room)]
    assert [save_and_exit(page) for page in pages] == [(True, False), (True, False), (False, False)]
    assert "Save and Exit" not in pages[2]


def test_the_shuttles_sections_its_head_count_and_its_coffee_machine(app):
    game = board_shuttle(new_game("Security", "Security Guard"))
    page = html(app, game)
    for text in ('<h1 class="screen-title">Crew Shuttle Common Area</h1>', ">Strap In</button>", ">Go to Command</button>",
                 ">Go to Security</button>", ">Step Off the Shuttle</button>"):
        assert text in page, text

    prisoner = game.station_crew[0]
    prisoner.update(in_jail=True, location=dict(game.player_data["location"]), warrant_reason="Smuggling")
    game.perform("room.go_to", {"section": "security"})
    page = html(app, game)
    assert '<h3 class="menu-title">The Cell</h3>' in page
    assert f'<p class="menu-text">{escape(prisoner["name"])} ({prisoner["job"]}): Smuggling</p>' in page

    game.perform("room.exit", {})
    game.perform("room.go_to", {"section": "command"})
    for npc in game.station_crew[2:]:
        npc["npc_goal"] = "board"
    game.station_crew[1].update(npc_goal=None, stays_behind=True)
    game.perform("room.head_count", {})
    page = html(app, game)
    assert "<h2>Head Count</h2>" in page
    assert f'<span>{escape(prisoner["name"])} ({prisoner["job"]}): in the shuttle&#39;s cell</span>' in page
    assert page.count('data-action="panel.page"') == 1
    assert f"data-args='{as_json(app, {'name': game.station_crew[1]['name']})}'" in page

    game.ui["panels"] = []
    game.perform("room.exit", {})
    game.perform("room.go_to", {"section": "break_room"})
    game.perform("room.coffee_machine", {})
    page = html(app, game)
    for text in ("<h2>Coffee Machine</h2>", "<legend>In the Machine</legend>", "Clear Machine", ">Brew</button>",
                 ">Coffee Grounds</button>", "Put coffee grounds and water in the machine, then brew."):
        assert text in page, text
