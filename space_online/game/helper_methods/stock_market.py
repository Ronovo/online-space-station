"""Stock market simulation, master-timer cycles, and the quarters trading terminal."""

import random

from space_online.game.helper_methods.errands import counted
from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.ui_panels import panel_action, register_panel

DEFAULT_COMPANY_NAMES = [
    "TechCorp",
    "GlobalBank",
    "HealthCare Plus",
    "EnergyCo",
    "FoodChain",
    "AutoMakers",
    "RetailGiant",
    "PharmaTech",
    "RealEstate Co",
    "MediaGroup",
    "Aerospace Inc",
    "TechStart",
    "GreenEnergy",
    "DigitalBank",
    "SmartHome",
]

CYCLE_INTERVAL_SECONDS = 300  # a new cycle every 5 minutes of master game time

NEWS_PER_CYCLE = 3
NEWS_REAL_CHANCE = 0.6
# How far a headline that turns out to be real moves its company, as a fraction of the price.
NEWS_MOVE_RANGE = (0.03, 0.12)
NEWS_HEADLINES = {
    "up": (
        "{name} beats its earnings forecast",
        "Analysts upgrade {name} to a strong buy",
        "{name} lands a major station supply contract",
        "Rumours of a buyout offer for {name}",
    ),
    "down": (
        "{name} recalls its flagship product",
        "Regulators open an inquiry into {name}",
        "{name} misses its quarterly targets",
        "A senior executive resigns from {name}",
    ),
}


class Company:
    def __init__(self, name, starting_value):
        self.name = name
        self.current_value = starting_value
        self.previous_value = starting_value
        self.price_history = [starting_value]

    @classmethod
    def from_save(cls, data):
        """A live company from its saved dict."""
        company = cls(data["name"], data["current_value"])
        company.previous_value = data["previous_value"]
        company.price_history = data["price_history"]
        return company

    def update_value(self, direction=None):
        """Move the price for a new cycle: at random, or up or down when real news pushes it."""
        self.previous_value = self.current_value

        if direction is None:
            change = random.uniform(-0.10, 0.10)
        else:
            change = random.uniform(*NEWS_MOVE_RANGE) * (1 if direction == "up" else -1)

        self.current_value = max(1.0, self.current_value * (1 + change))
        self.price_history.append(self.current_value)
        if len(self.price_history) > 50:
            self.price_history.pop(0)


def create_default_companies(history_cycles=5):
    """Create the default company list with optional price history."""
    companies = [Company(name, random.uniform(10, 1000)) for name in DEFAULT_COMPANY_NAMES]
    for _ in range(history_cycles):
        for company in companies:
            company.update_value()
    return companies


def serialize_companies(companies):
    """Serialize live company objects for player_data storage."""
    return [
        {
            "name": company.name,
            "current_value": company.current_value,
            "previous_value": company.previous_value,
            "price_history": company.price_history,
        }
        for company in companies
    ]


def get_seconds_until_next_cycle(elapsed_seconds, interval=CYCLE_INTERVAL_SECONDS):
    """Calculate seconds remaining until the next market cycle, per the master timer."""
    return int(max(0, interval - (elapsed_seconds % interval)))


def default_stock_market_state():
    """Return a fresh stock_market block for player_data."""
    return {
        "cycle_number": 1,
        "companies": [],
        "news": [],
        "trade_log": [],
    }


def generate_news(companies):
    """This cycle's headlines: each names a company and a direction, and only some of them are real.

    A real headline pushes its company that way at the next cycle; the rest are noise.
    """
    news = []
    for company in random.sample(companies, min(NEWS_PER_CYCLE, len(companies))):
        direction = random.choice(("up", "down"))
        news.append({
            "company": company.name,
            "direction": direction,
            "text": random.choice(NEWS_HEADLINES[direction]).format(name=company.name),
            "real": random.random() < NEWS_REAL_CHANCE,
        })
    return news


def round_credits(value):
    """Credits are kept to the cent, rounded."""
    return round(value, 2)


# The trade log keeps this many of the most recent cycles that had trades.
MAX_TRADE_LOG_CYCLES = 50


def record_trade(player_data, cycle, side, company_name, shares, price, total):
    """Append or merge a buy/sell entry in the current cycle trade log."""
    trade_log = player_data["stock_market"]["trade_log"]
    current_cycle_entry = next((entry for entry in trade_log if entry["cycle"] == cycle), None)
    if not current_cycle_entry:
        current_cycle_entry = {
            "cycle": cycle,
            "trades": {"bought": {}, "sold": {}},
        }
        trade_log.append(current_cycle_entry)
        del trade_log[:-MAX_TRADE_LOG_CYCLES]

    side_trades = current_cycle_entry["trades"][side]
    if company_name in side_trades:
        existing = side_trades[company_name]
        existing["amount"] += shares
        existing["total"] += total
        existing["price"] = existing["total"] / existing["amount"]
    else:
        side_trades[company_name] = {
            "amount": shares,
            "price": price,
            "total": total,
        }


def generate_market_tip(news):
    """Return one of the cycle's headlines as an overheard tip, or None when there is no news."""
    if not news:
        return None
    return f"Overheard in the hall: {random.choice(news)['text']}."


class StockMarketEngine:
    """Owns live market state and master-timer-driven tick logic."""

    def __init__(self, companies, news=None):
        self.companies = companies
        self.cycle_number = 1
        self.news = news if news is not None else []

    def tick_if_due(self, elapsed_seconds):
        """Advance the market to match the master timer.

        Cycles are scheduled purely off ``elapsed_seconds``: cycle N ends at
        ``N * CYCLE_INTERVAL_SECONDS``.
        """
        target_cycle = int(elapsed_seconds // CYCLE_INTERVAL_SECONDS) + 1
        while self.cycle_number < target_cycle:
            pushed = {item["company"]: item["direction"] for item in self.news if item["real"]}
            for company in self.companies:
                company.update_value(pushed.get(company.name))
            self.news = generate_news(self.companies)
            self.cycle_number += 1

    def sync_to_player_data(self, player_data):
        """Write current market state into player_data."""
        player_data["stock_market"].update({
            "cycle_number": self.cycle_number,
            "companies": serialize_companies(self.companies),
            "news": self.news,
        })

    @classmethod
    def from_player_data(cls, player_data):
        """Build an engine from the market state saved on player_data."""
        market_data = player_data["stock_market"]
        engine = cls([Company.from_save(data) for data in market_data["companies"]], market_data["news"])
        engine.cycle_number = market_data["cycle_number"]
        return engine


FILTER_GROUPS = (
    ("filter", "Filter Stocks:", (("All", "Show All"), ("Affordable", "Affordable"), ("Expensive", "Expensive"))),
    ("sort", "Sort By Price:", (("price_asc", "Low to High"), ("price_desc", "High to Low"))),
    ("ownership", "Ownership:", (("all", "All Stocks"), ("owned", "Owned"), ("not_owned", "Not Owned"))),
    ("trend", "Trend:", (("all", "All"), ("rising", "Rising"), ("falling", "Falling"))),
)
FILTER_VALUES = {group: {value for value, _ in options} for group, _, options in FILTER_GROUPS}
SHARE_OPTIONS = (1, 5, 10, 25, 50, 100)

CHART_WIDTH = 560
CHART_HEIGHT = 300
CHART_MARGINS = (60, 16, 30, 44)  # left, right, top, bottom


def _market_filters(state):
    return {group: state.get(group, options[0][0]) for group, _, options in FILTER_GROUPS}


def _filtered_companies(companies, player_credits, holdings, filters):
    """Companies passing the affordability/ownership/trend filters, price-sorted."""
    listed = []
    for company in companies:
        can_afford = player_credits // company.current_value >= 1
        passes_affordability = (
            filters["filter"] == "All"
            or (filters["filter"] == "Affordable" and can_afford)
            or (filters["filter"] == "Expensive" and not can_afford)
        )

        is_owned = holdings.get(company.name, 0) > 0
        passes_ownership = (
            filters["ownership"] == "all"
            or (filters["ownership"] == "owned" and is_owned)
            or (filters["ownership"] == "not_owned" and not is_owned)
        )

        price_change = company.current_value - company.previous_value
        passes_trend = (
            filters["trend"] == "all"
            or (filters["trend"] == "rising" and price_change > 0)
            or (filters["trend"] == "falling" and price_change < 0)
        )

        if passes_affordability and passes_ownership and passes_trend:
            listed.append(company)

    listed.sort(key=lambda c: c.current_value, reverse=filters["sort"] == "price_desc")
    return listed


def _listed_and_selected(game, state):
    """Return (listed companies, selected company); selection falls back to the first row."""
    listed = _filtered_companies(game.market_engine.companies, game.player_data["credits"],
                                 game.player_data["stock_holdings"], _market_filters(state))
    selected = next((c for c in listed if c.name == state.get("selected")), None)
    if selected is None and listed:
        selected = listed[0]
    return listed, selected


def _price_chart(company):
    """Polyline points and axis ticks for an inline SVG price-history chart."""
    prices = company.price_history
    left, right, top, bottom = CHART_MARGINS
    plot_w = CHART_WIDTH - left - right
    plot_h = CHART_HEIGHT - top - bottom
    low, high = min(prices), max(prices)
    if high == low:
        low, high = low - 1, high + 1
    span_x = max(1, len(prices) - 1)
    label_format = "{:.2f}" if high - low < 10 else "{:.0f}"

    def px(i):
        return left + plot_w * i / span_x

    def py(value):
        return top + plot_h * (1 - (value - low) / (high - low))

    return {
        "width": CHART_WIDTH,
        "height": CHART_HEIGHT,
        "left": left,
        "top": top,
        "right": CHART_WIDTH - right,
        "bottom": CHART_HEIGHT - bottom,
        "points": " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(prices)),
        "color": "green" if prices[-1] >= prices[0] else "red",
        "y_ticks": [
            {"y": py(low + (high - low) * k / 4), "label": label_format.format(low + (high - low) * k / 4)}
            for k in range(5)
        ],
        "x_ticks": [{"x": px(i), "label": str(i)} for i in sorted({0, span_x // 2, span_x})],
        "title": f"{company.name} Price History",
    }


def _company_row(company, holdings):
    """One line of the company list: its price, how it moved this cycle, and the shares held."""
    change_pct = (company.current_value - company.previous_value) / company.previous_value * 100
    return {
        "name": company.name,
        "price": company.current_value,
        "change_pct": change_pct,
        "trend": "up" if change_pct > 0 else "down" if change_pct < 0 else "flat",
        "owned": holdings.get(company.name, 0),
    }


@register_panel("stock_market", "Stock Market")
def stock_market_panel(game, state):
    listed, selected = _listed_and_selected(game, state)
    credits = game.player_data["credits"]

    remaining = get_seconds_until_next_cycle(get_elapsed_seconds(game.player_data))
    if remaining <= 0:
        timer = {"text": "Updating Market...", "color": "green"}
    else:
        timer = {
            "text": f"Next Update: {remaining // 60:02d}:{remaining % 60:02d}",
            "color": "yellow" if remaining > 15 else "orange" if remaining > 5 else "red",
        }

    detail = None
    if selected is not None:
        price_change = selected.current_value - selected.previous_value
        owned = game.player_data["stock_holdings"].get(selected.name, 0)
        detail = {
            "name": selected.name,
            "price": selected.current_value,
            "change": price_change,
            "change_pct": (price_change / selected.previous_value) * 100,
            "change_color": "green" if price_change >= 0 else "red",
            "owned": owned,
            "total_value": owned * selected.current_value,
            "max_buy": int(credits / selected.current_value),
            "max_sell": owned,
            "chart": _price_chart(selected),
        }

    holdings = game.player_data["stock_holdings"]
    prices = {company.name: company.current_value for company in game.market_engine.companies}
    return {
        "cycle": game.market_engine.cycle_number,
        "timer": timer,
        "credits": credits,
        "portfolio_value": sum(shares * prices.get(name, 0) for name, shares in holdings.items()),
        "news": [{"text": item["text"], "direction": item["direction"]} for item in game.market_engine.news],
        "filter_groups": FILTER_GROUPS,
        "filters": _market_filters(state),
        "companies": [_company_row(company, holdings) for company in listed],
        "selected": selected.name if selected else None,
        "detail": detail,
        "share_options": SHARE_OPTIONS,
        "read_only": bool(state.get("read_only")),
    }


@panel_action("stock_market")
def set_filter(game, state, args):
    group, value = args["group"], args["value"]
    if value in FILTER_VALUES.get(group, ()):
        state[group] = value


@panel_action("stock_market")
def select(game, state, args):
    name = str(args["name"])
    if any(company.name == name for company in game.market_engine.companies):
        state["selected"] = name


def _requested_shares(game, args):
    try:
        shares = int(str(args.get("shares", "")).strip())
    except ValueError:
        shares = 0
    if shares <= 0:
        game.alert("Input Error", "Please enter a valid number of shares.", kind="error")
        return None
    return shares


def _trade(game, state, args, side):
    """Buy or sell the requested shares of the selected company at today's price. A market opened from the PDA
    is for looking only."""
    if state.get("read_only"):
        return
    _, company = _listed_and_selected(game, state)
    shares = _requested_shares(game, args)
    if company is None or shares is None:
        return

    player_data = game.player_data
    holdings = player_data["stock_holdings"]
    total = shares * company.current_value
    if side == "bought" and total > player_data["credits"]:
        game.alert("Transaction Failed", "Not enough credits for this purchase.", kind="error")
        return
    if side == "sold" and shares > holdings.get(company.name, 0):
        game.alert("Transaction Failed", "You don't own that many shares.", kind="error")
        return

    sign = 1 if side == "bought" else -1
    player_data["credits"] = round_credits(player_data["credits"] - sign * total)
    holdings[company.name] = holdings.get(company.name, 0) + sign * shares
    if holdings[company.name] <= 0:
        del holdings[company.name]
    record_trade(player_data, game.market_engine.cycle_number, side, company.name, shares,
                 company.current_value, total)
    verb = side.title()
    game.add_note(f"{verb} {counted(shares, 'share')} of {company.name} "
                  f"at {company.current_value:.2f} cr/share (Total: {total:.2f} cr)")
    state["selected"] = company.name
    game.alert("Transaction Complete", f"{verb} {counted(shares, 'share')} of {company.name} for {total:.2f} credits.")


@panel_action("stock_market")
def buy(game, state, args):
    _trade(game, state, args, "bought")


@panel_action("stock_market")
def sell(game, state, args):
    _trade(game, state, args, "sold")


@panel_action("stock_market")
def history(game, state, args):
    game.open_panel("trade_history")


@register_panel("trade_history", "Trade History")
def trade_history_panel(game, state):
    trade_log = game.player_data["stock_market"].get("trade_log")
    return {"entries": list(reversed(trade_log)) if trade_log is not None else None}

