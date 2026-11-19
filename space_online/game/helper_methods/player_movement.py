"""Player hallway movement: directional travel and alcohol impairment checks."""

import random

from space_online.game.helper_methods.alcohol_helper import fall_chance, stumble_chance
from space_online.game.helper_methods.antagonists import check_threat_encounter
from space_online.game.helper_methods.health_bands import LIMBS, change_limb, limb_label
from space_online.game.helper_methods.jail import is_jailed, player_jail_text
from space_online.game.helper_methods.npc_movement import find_hall_passersby
from space_online.game.helper_methods.random_events import maybe_trigger_hallway_event
from space_online.game.maps import donut


class PlayerMovementMixin:
    def _try_alcohol_movement_impairment(self):
        """Roll stumble (then optional fall) before moving. Return True if move is cancelled."""
        alcohol = self.player_data["alcohol_percent"]
        s_chance = stumble_chance(alcohol)
        if s_chance <= 0 or random.random() >= (s_chance / 100.0):
            return False

        f_chance = fall_chance(alcohol)
        if f_chance > 0 and random.random() < (f_chance / 100.0):
            limb = random.choice(LIMBS)
            damage = random.randint(1, 5)
            before, after = change_limb(self.player_data, limb, -damage)
            limb_name = limb_label(limb)
            self.alert("You Fall", f"You stumble and fall hard!\n\nYour {limb_name} took {damage}% blunt damage "
                                   f"and is now at {after}%.")
            self.add_note(f"Fell while intoxicated ({alcohol:.1f}% alcohol). {limb_name} took {damage}% blunt damage "
                          f"(from {before}% to {after}%).")
            return True

        self.alert(
            "You Stumble",
            "You stumble and lose your footing. You stay where you are.",
        )
        self.add_note(
            f"Stumbled while intoxicated ({alcohol:.1f}% alcohol) and failed to move."
        )
        return True

    def move_direction(self, direction):
        if direction not in donut.DIRECTION_STEPS:
            return

        if is_jailed(self.player_data):
            self.alert("In Jail", player_jail_text(self.player_data))
            return

        if self._try_alcohol_movement_impairment():
            return

        step = donut.hallway_neighbors(self.player_data["location"]["x"], self.player_data["location"]["y"]).get(direction)
        if step is None:
            self.alert("Error", "You can't go that way!", kind="error")
            return

        self.player_data["location"] = donut.location_from_tile(step)

        check_threat_encounter(self)
        if self.player_data["fight"]:
            return

        maybe_trigger_hallway_event(self)

        if is_jailed(self.player_data):
            return

        for npc in find_hall_passersby(self.player_data, self.station_crew):
            if self._handle_hallway_security_encounter(npc):
                if is_jailed(self.player_data):
                    return
                continue
            self.alert(
                "Crew Encounter",
                f"{npc.get('name', 'A crew member')} ({npc.get('job', 'Crew')}) passes you in the hall.",
            )
