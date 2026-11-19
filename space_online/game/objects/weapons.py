"""Melee weapons and the Security kit. A weapon's "attack" is what it adds to an Attack while it is held."""


def _weapon(item_id, name, description, **attributes):
    return {
        "id": item_id,
        "name": name,
        "description": description,
        "category": "Weapon",
        "attributes": attributes,
        "actions": ["examine", "equip", "drop"],
    }


WEAPON_ITEMS = {
    "crowbar": _weapon("crowbar", "Crowbar", "A steel pry bar. Opens crates, doors and arguments.", attack=10),
    "combat_knife": _weapon("combat_knife", "Combat Knife", "A short, sharp fighting knife.", attack=14),
    "fire_axe": _weapon("fire_axe", "Fire Axe", "A heavy axe from an emergency cabinet.", attack=22),
    "energy_sword": _weapon("energy_sword", "Energy Sword", "A humming blade of light from the Security armory.",
                            attack=30),
    "stun_baton": _weapon("stun_baton", "Stun Baton",
                          "A Security baton. It hits lightly, but a jab stuns whoever it touches.",
                          attack=6, stun=2),
    "handcuffs": {
        "id": "handcuffs",
        "name": "Handcuffs",
        "plural": True,
        "description": "Security handcuffs. They go on someone who has been stunned.",
        "category": "Security",
        "attributes": {},
        "actions": ["examine", "drop"],
    },
}

FABRICATOR_WEAPON_IDS = ["crowbar", "combat_knife", "fire_axe"]
ARMORY_ITEM_IDS = ("stun_baton", "handcuffs", "energy_sword")
