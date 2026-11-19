from space_online.game.helper_methods.rounds import BOARDING_SECTION, shuttle_status
from space_online.game.maps.donut import DEPARTURES_KEY
from space_online.game.special_rooms.shared import SpecialRoomBase, button, room_action, text_line
from space_online.game.special_rooms.shuttle import ShuttleCabin


class Departures(ShuttleCabin, SpecialRoomBase):
    """The lounge the crew shuttle docks at. Once the player is aboard, ShuttleCabin takes over the screen."""

    ROOM_TITLE = "Departures"
    ROOM_HEADING = "Departures Lounge"
    ROOM_DESCRIPTION = (
        "Rows of worn seats face a wide airlock. This is where the crew shuttle docks at the end of a "
        "shift to take everyone back to Central Command."
    )
    DOOR_KEY = DEPARTURES_KEY

    @property
    def round(self):
        return self.player_data["round"]

    def room_options(self):
        status = shuttle_status(self.player_data) or "No shuttle has been called. The Captain calls it from the Bridge."
        docked = self.round["shuttle"]["state"] == "docked"
        return [text_line(status, style="italic")] + ([button("Board the Shuttle", "room.board")] if docked else [])

    @room_action
    def board(self):
        if self.round["shuttle"]["state"] == "docked":
            self.round.update(aboard=True, section=BOARDING_SECTION, strapped=False)
            self.add_note("Boarded the crew shuttle.")

    @room_action
    def step_off(self):
        if self.round["shuttle"]["state"] == "docked" and not self.round["strapped"]:
            self.round["aboard"] = False
