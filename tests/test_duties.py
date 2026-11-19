from helpers import at, duty_id, give_duty, new_game
from space_online.game.helper_methods.errands import (
    DUTY_EXPIRY_SECONDS,
    MAX_OPEN_DUTIES,
    duties_full,
    duty_by_id,
    open_duties,
    tick_duty_expiry,
)
from space_online.game.maps.donut import BAR_KEY, MEDBAY_KEY


def test_a_duty_gets_an_id_and_a_deadline_when_it_goes_on_the_board():
    game = at(new_game(), 100)
    first = give_duty(game, kind="help", room=BAR_KEY, summary="Help at the bar")
    second = give_duty(game, kind="treat", room=MEDBAY_KEY, summary="Treat Sam")
    duties = game.player_data["duties"]
    assert first != second and [duty["expires_at"] for duty in duties] == [100 + DUTY_EXPIRY_SECONDS] * 2
    assert duty_by_id(game.player_data, second) is duties[1]
    assert duty_by_id(game.player_data, "none") is None
    assert open_duties(game.player_data, ("help", "deliver")) == [duties[0]]
    assert open_duties(game.player_data, room=MEDBAY_KEY) == [duties[1]]
    assert open_duties(game.player_data, ("help",), MEDBAY_KEY) == []


def test_the_board_holds_only_so_many_duties():
    game = new_game()
    for _ in range(MAX_OPEN_DUTIES - 1):
        give_duty(game, kind="help", room=BAR_KEY, summary="Busy")
    assert not duties_full(game.player_data)
    give_duty(game, kind="help", room=BAR_KEY, summary="Busy")
    assert duties_full(game.player_data)


def test_a_duty_left_too_long_is_missed():
    game = new_game()
    give_duty(game, kind="help", room=BAR_KEY, summary="Help at the bar")
    at(game, 50)
    give_duty(game, kind="treat", room=MEDBAY_KEY, summary="Treat Sam")
    tick_duty_expiry(at(game, DUTY_EXPIRY_SECONDS - 1))
    assert len(game.player_data["duties"]) == 2 and game._messages == []
    tick_duty_expiry(at(game, DUTY_EXPIRY_SECONDS))
    assert [duty["summary"] for duty in game.player_data["duties"]] == ["Treat Sam"]
    assert game._messages == [("Duty Missed", "You ran out of time: Help at the bar.", "warning")]
    assert game.player_data["notes"][-1]["text"] == "You ran out of time: Help at the bar."
    assert game.player_data["round"]["duties_missed"] == 1


def test_the_duties_panel_opens_from_anywhere_and_lists_what_is_waiting():
    game = at(new_game("Civilian", "Bartender"), 60)
    give_duty(game, kind="help", room=BAR_KEY, summary="Help at the bar")
    game.player_data["round"].update(duties_done=2, duties_missed=1)
    game.perform("game.duties", {})
    panel = game.view()["panel"]
    assert (panel["type"], panel["title"]) == ("duties", "Duties")
    assert panel["ctx"] == {"job": "Bartender", "duties": [{"id": duty_id(game), "summary": "Help at the bar",
                                                           "left": "6m 0s", "answer": False}],
                            "done": 2, "missed": 1}
