"""What sits on the service window between the Bar and the Kitchen.

player_data["service_window"] holds:
    stock     {side: {ingredient: count}} waiting on the window for that side's station
    requests  {side: {ingredient: count}} that side's crew member is asking the other side for
"""

from space_online.game.helper_methods.mixing import Supply, take_from_stock

WINDOW_SIDES = ("bar", "kitchen")


def other_side(side):
    return WINDOW_SIDES[1 - WINDOW_SIDES.index(side)]


def new_service_window():
    return {"stock": {side: {} for side in WINDOW_SIDES}, "requests": {side: {} for side in WINDOW_SIDES}}


def window_supply(side):
    """The ingredients waiting on the window for side's mixing station."""
    def stock(game):
        return game.player_data["service_window"]["stock"][side]

    return Supply(
        key="Window",
        heading="From the Service Window",
        counts=stock,
        take=lambda game, name: take_from_stock(stock(game), name),
    )
