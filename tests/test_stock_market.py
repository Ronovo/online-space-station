import pytest

from helpers import new_game
from space_online.game.helper_methods import stock_market
from space_online.game.helper_methods.stock_market import (
    CYCLE_INTERVAL_SECONDS,
    MAX_TRADE_LOG_CYCLES,
    Company,
    StockMarketEngine,
    generate_market_tip,
    record_trade,
)


def market(prices, credits=1000, holdings=None):
    """A game whose market has one company per (name, previous, current) price."""
    game = new_game()
    companies = []
    for name, previous, current in prices:
        company = Company(name, previous)
        company.current_value = current
        company.price_history = [previous, current]
        companies.append(company)
    game.market_engine.companies = companies
    game.player_data.update(credits=credits, stock_holdings=dict(holdings or {}))
    game.open_panel("stock_market")
    return game


def panel(game):
    return game.view()["panel"]["ctx"]


def last_message(game):
    return game._messages[-1][1:3]


PRICES = [("Cheap", 10.0, 12.0), ("Pricey", 2000.0, 1500.0), ("Middling", 100.0, 100.0)]


def test_prices_never_fall_below_one_credit_and_keep_fifty_cycles_of_history(monkeypatch):
    company = Company("Sinking", 1.05)
    monkeypatch.setattr(stock_market.random, "uniform", lambda low, high: low)
    for _ in range(60):
        company.update_value()
    assert company.current_value == 1.0
    assert len(company.price_history) == 50


def test_trades_in_one_cycle_merge_by_company():
    player = new_game().player_data
    record_trade(player, 1, "bought", "Cheap", 2, 10.0, 20.0)
    record_trade(player, 1, "bought", "Cheap", 2, 20.0, 40.0)
    record_trade(player, 1, "sold", "Cheap", 1, 25.0, 25.0)
    assert player["stock_market"]["trade_log"] == [{"cycle": 1, "trades": {
        "bought": {"Cheap": {"amount": 4, "price": 15.0, "total": 60.0}},
        "sold": {"Cheap": {"amount": 1, "price": 25.0, "total": 25.0}}}}]


def test_the_trade_log_keeps_only_recent_cycles():
    player = new_game().player_data
    for cycle in range(MAX_TRADE_LOG_CYCLES + 5):
        record_trade(player, cycle, "bought", "Cheap", 1, 1.0, 1.0)
    log = player["stock_market"]["trade_log"]
    assert (len(log), log[0]["cycle"]) == (MAX_TRADE_LOG_CYCLES, 5)


def test_market_tips(monkeypatch):
    assert generate_market_tip([]) is None
    monkeypatch.setattr(stock_market.random, "choice", lambda options: options[0])
    assert generate_market_tip([{"name": "Cheap"}]) == "Overheard that Cheap stock is expected to rise soon!"
    monkeypatch.setattr(stock_market.random, "choice", lambda options: options[-1])
    assert generate_market_tip([{"name": "Cheap"}]) == "Overheard that Cheap stock might be dropping in value soon!"


def test_the_market_catches_up_every_missed_cycle():
    engine = StockMarketEngine([Company("Cheap", 10.0)])
    engine.tick_if_due(CYCLE_INTERVAL_SECONDS - 1)
    assert engine.cycle_number == 1
    engine.tick_if_due(3 * CYCLE_INTERVAL_SECONDS)
    assert (engine.cycle_number, len(engine.companies[0].price_history)) == (4, 4)


@pytest.mark.parametrize("group, value, listed", [
    ("filter", "All", ["Cheap", "Middling", "Pricey"]),
    ("filter", "Affordable", ["Cheap", "Middling"]),
    ("filter", "Expensive", ["Pricey"]),
    ("ownership", "owned", ["Middling"]),
    ("ownership", "not_owned", ["Cheap", "Pricey"]),
    ("trend", "rising", ["Cheap"]),
    ("trend", "falling", ["Pricey"]),
    ("sort", "price_desc", ["Pricey", "Middling", "Cheap"]),
])
def test_filters_and_sorting(group, value, listed):
    game = market(PRICES, holdings={"Middling": 2})
    game.perform("panel.set_filter", {"group": group, "value": value})
    assert panel(game)["companies"] == listed


def test_unknown_filters_and_companies_are_ignored():
    game = market(PRICES)
    game.perform("panel.set_filter", {"group": "filter", "value": "Free"})
    game.perform("panel.set_filter", {"group": "colour", "value": "All"})
    game.perform("panel.select", {"name": "Nobody Inc"})
    ctx = panel(game)
    assert (ctx["filters"]["filter"], ctx["selected"]) == ("All", "Cheap")


def test_the_selected_company_details():
    game = market(PRICES, credits=1000, holdings={"Pricey": 3})
    game.perform("panel.select", {"name": "Pricey"})
    detail = panel(game)["detail"]
    assert {key: detail[key] for key in ("name", "price", "change", "change_pct", "change_color", "owned",
                                         "total_value", "max_buy", "max_sell")} == {
        "name": "Pricey", "price": 1500.0, "change": -500.0, "change_pct": -25.0, "change_color": "red", "owned": 3,
        "total_value": 4500.0, "max_buy": 0, "max_sell": 3}
    assert detail["chart"]["color"] == "red"
    assert [tick["label"] for tick in detail["chart"]["y_ticks"]] == ["1500", "1625", "1750", "1875", "2000"]


def test_a_flat_price_chart_still_has_a_scale():
    game = market([("Middling", 100.0, 100.0)])
    chart = panel(game)["detail"]["chart"]
    assert [tick["label"] for tick in chart["y_ticks"]] == ["99.00", "99.50", "100.00", "100.50", "101.00"]
    assert (chart["color"], chart["x_ticks"][-1]["label"]) == ("green", "1")


def test_an_empty_listing_has_no_selection():
    game = market(PRICES, holdings={})
    game.perform("panel.set_filter", {"group": "ownership", "value": "owned"})
    ctx = panel(game)
    assert (ctx["companies"], ctx["selected"], ctx["detail"]) == ([], None, None)
    game.perform("panel.buy", {"shares": "1"})
    assert game.player_data["credits"] == 1000


@pytest.mark.parametrize("elapsed, text, color", [
    (0, "Next Update: 05:00", "yellow"),
    (CYCLE_INTERVAL_SECONDS - 10, "Next Update: 00:10", "orange"),
    (CYCLE_INTERVAL_SECONDS - 3, "Next Update: 00:03", "red"),
    (CYCLE_INTERVAL_SECONDS - 0.5, "Updating Market...", "green"),
])
def test_the_update_countdown(elapsed, text, color):
    game = market(PRICES)
    game.player_data["game_clock"]["elapsed_seconds"] = elapsed
    assert panel(game)["timer"] == {"text": text, "color": color}


def test_buying_and_selling_shares():
    game = market(PRICES, credits=1000)
    game.perform("panel.select", {"name": "Cheap"})
    game.perform("panel.buy", {"shares": " 5 "})
    assert last_message(game) == ("Transaction Complete", "Bought 5 shares of Cheap for 60.00 credits.")
    assert (game.player_data["credits"], game.player_data["stock_holdings"]) == (940.0, {"Cheap": 5})
    game.perform("panel.sell", {"shares": "5"})
    assert (game.player_data["credits"], game.player_data["stock_holdings"]) == (1000.0, {})
    assert [note["text"] for note in game.player_data["notes"]] == [
        "Bought 5 shares of Cheap at 12.00 cr/share (Total: 60.00 cr)",
        "Sold 5 shares of Cheap at 12.00 cr/share (Total: 60.00 cr)"]
    game.perform("panel.history", {})
    entries = panel(game)["entries"]
    assert entries[0]["trades"]["bought"]["Cheap"]["amount"] == 5


@pytest.mark.parametrize("shares", ["many", "0", "-2", ""])
def test_a_trade_needs_a_positive_number_of_shares(shares):
    game = market(PRICES)
    game.perform("panel.buy", {"shares": shares})
    assert last_message(game) == ("Input Error", "Please enter a valid number of shares.")


def test_you_cannot_buy_beyond_your_credits_or_sell_what_you_do_not_own():
    game = market(PRICES, credits=50)
    game.perform("panel.buy", {"shares": "5"})
    assert last_message(game) == ("Transaction Failed", "Not enough credits for this purchase.")
    game.perform("panel.sell", {"shares": "1"})
    assert last_message(game) == ("Transaction Failed", "You don't own that many shares.")
    assert game.player_data["credits"] == 50


def test_the_trade_history_without_a_log():
    game = market(PRICES)
    game.player_data["stock_market"]["trade_log"] = None
    game.perform("panel.history", {})
    assert panel(game) == {"entries": None}
