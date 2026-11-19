import pytest

from helpers import ctx, last_message, new_game, notes
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


def test_a_market_tip_repeats_one_of_the_headlines(monkeypatch):
    assert generate_market_tip([]) is None
    monkeypatch.setattr(stock_market.random, "choice", lambda options: options[-1])
    news = [{"text": "Cheap beats its earnings forecast"}, {"text": "Pricey misses its quarterly targets"}]
    assert generate_market_tip(news) == "Overheard in the hall: Pricey misses its quarterly targets."


def test_each_cycle_has_headlines_about_different_companies(monkeypatch):
    companies = [Company(name, 10.0) for name in ("Cheap", "Pricey", "Middling", "Fourth")]
    monkeypatch.setattr(stock_market.random, "sample", lambda population, count: population[:count])
    monkeypatch.setattr(stock_market.random, "choice", lambda options: options[0])
    monkeypatch.setattr(stock_market.random, "random", lambda: stock_market.NEWS_REAL_CHANCE)
    news = stock_market.generate_news(companies)
    assert news == [{"company": name, "direction": "up", "text": f"{name} beats its earnings forecast", "real": False}
                    for name in ("Cheap", "Pricey", "Middling")]
    assert len(stock_market.generate_news(companies[:1])) == 1


def test_real_news_pushes_its_company_and_fake_news_does_not(monkeypatch):
    rising, falling, rumoured = Company("Rising", 100.0), Company("Falling", 100.0), Company("Rumoured", 100.0)
    engine = StockMarketEngine([rising, falling, rumoured], news=[
        {"company": "Rising", "direction": "up", "text": "", "real": True},
        {"company": "Falling", "direction": "down", "text": "", "real": True},
        {"company": "Rumoured", "direction": "up", "text": "", "real": False},
    ])
    monkeypatch.setattr(stock_market.random, "uniform", lambda low, high: low)
    engine.tick_if_due(CYCLE_INTERVAL_SECONDS)
    low = stock_market.NEWS_MOVE_RANGE[0]
    assert (rising.current_value, falling.current_value, rumoured.current_value) == (
        pytest.approx(100 * (1 + low)), pytest.approx(100 * (1 - low)), pytest.approx(90.0))
    assert len(engine.news) == stock_market.NEWS_PER_CYCLE


def test_the_news_is_saved_with_the_market_and_shown_without_saying_what_is_real():
    game = market(PRICES)
    game.market_engine.news = [{"company": "Cheap", "direction": "up", "text": "Cheap soars", "real": True}]
    assert ctx(game)["news"] == [{"text": "Cheap soars", "direction": "up"}]
    saved = new_game()
    assert len(saved.market_engine.news) == stock_market.NEWS_PER_CYCLE
    saved.market_engine.news = game.market_engine.news
    assert saved.to_save_data()["stock_market"]["news"] == game.market_engine.news
    assert StockMarketEngine.from_player_data(saved.player_data).news == game.market_engine.news


def test_the_company_list_shows_price_change_and_shares_held():
    game = market(PRICES, holdings={"Middling": 2, "Gone Bust": 5})
    shown = ctx(game)
    assert shown["companies"] == [
        {"name": "Cheap", "price": 12.0, "change_pct": pytest.approx(20.0), "trend": "up", "owned": 0},
        {"name": "Middling", "price": 100.0, "change_pct": 0.0, "trend": "flat", "owned": 2},
        {"name": "Pricey", "price": 1500.0, "change_pct": -25.0, "trend": "down", "owned": 0},
    ]
    assert shown["portfolio_value"] == 200.0


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
    assert [company["name"] for company in ctx(game)["companies"]] == listed


def test_unknown_filters_and_companies_are_ignored():
    game = market(PRICES)
    game.perform("panel.set_filter", {"group": "filter", "value": "Free"})
    game.perform("panel.set_filter", {"group": "colour", "value": "All"})
    game.perform("panel.select", {"name": "Nobody Inc"})
    shown = ctx(game)
    assert (shown["filters"]["filter"], shown["selected"]) == ("All", "Cheap")


def test_the_selected_company_details():
    game = market(PRICES, credits=1000, holdings={"Pricey": 3})
    game.perform("panel.select", {"name": "Pricey"})
    detail = ctx(game)["detail"]
    assert {key: detail[key] for key in ("name", "price", "change", "change_pct", "change_color", "owned",
                                         "total_value", "max_buy", "max_sell")} == {
        "name": "Pricey", "price": 1500.0, "change": -500.0, "change_pct": -25.0, "change_color": "red", "owned": 3,
        "total_value": 4500.0, "max_buy": 0, "max_sell": 3}
    assert detail["chart"]["color"] == "red"
    assert [tick["label"] for tick in detail["chart"]["y_ticks"]] == ["1500", "1625", "1750", "1875", "2000"]


def test_a_flat_price_chart_still_has_a_scale():
    game = market([("Middling", 100.0, 100.0)])
    chart = ctx(game)["detail"]["chart"]
    assert [tick["label"] for tick in chart["y_ticks"]] == ["99.00", "99.50", "100.00", "100.50", "101.00"]
    assert (chart["color"], chart["x_ticks"][-1]["label"]) == ("green", "1")


def test_an_empty_listing_has_no_selection():
    game = market(PRICES, holdings={})
    game.perform("panel.set_filter", {"group": "ownership", "value": "owned"})
    shown = ctx(game)
    assert (shown["companies"], shown["selected"], shown["detail"]) == ([], None, None)
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
    assert ctx(game)["timer"] == {"text": text, "color": color}


def test_buying_and_selling_shares():
    game = market(PRICES, credits=1000)
    game.perform("panel.select", {"name": "Cheap"})
    game.perform("panel.buy", {"shares": " 5 "})
    assert last_message(game) == ("Transaction Complete", "Bought 5 shares of Cheap for 60.00 credits.")
    assert (game.player_data["credits"], game.player_data["stock_holdings"]) == (940.0, {"Cheap": 5})
    game.perform("panel.sell", {"shares": "5"})
    assert (game.player_data["credits"], game.player_data["stock_holdings"]) == (1000.0, {})
    assert notes(game) == [
        "Bought 5 shares of Cheap at 12.00 cr/share (Total: 60.00 cr)",
        "Sold 5 shares of Cheap at 12.00 cr/share (Total: 60.00 cr)"]
    game.perform("panel.history", {})
    entries = ctx(game)["entries"]
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
    assert ctx(game) == {"entries": None}


def test_a_single_share_reads_as_one():
    game = market(PRICES, credits=1000)
    game.perform("panel.select", {"name": "Cheap"})
    game.perform("panel.buy", {"shares": "1"})
    assert last_message(game) == ("Transaction Complete", "Bought 1 share of Cheap for 12.00 credits.")
    assert notes(game)[-1] == "Bought 1 share of Cheap at 12.00 cr/share (Total: 12.00 cr)"
