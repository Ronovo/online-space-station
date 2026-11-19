"""The body: its limbs and damage types, the health and damage bands, and the arithmetic of hurting and healing.
The character sheet, MedBay, station status and random events all use it."""

LIMBS = ("head", "chest", "left_arm", "right_arm", "left_leg", "right_leg")
DAMAGE_TYPES = ("burn", "poison", "oxygen")


def new_body():
    """A crew member's unhurt limbs and damage."""
    return {"limbs": {limb: 100 for limb in LIMBS}, "damage": {dtype: 0 for dtype in DAMAGE_TYPES}}


def limb_label(limb):
    return limb.replace("_", " ").title()


def health_band(value):
    """(status, colour) for a health percentage, where 100 is unhurt. Only 100 is Healthy."""
    if value >= 100:
        return "Healthy", "green"
    if value > 75:
        return "Minor injuries", "green"
    if value > 40:
        return "Injured", "yellow"
    return "Critical", "red"


def damage_band(value):
    """(status, colour) for a damage percentage, where 0 is unhurt."""
    if value < 10:
        return "Clear", "green"
    if value < 30:
        return "Mild", "yellow"
    if value < 60:
        return "Moderate", "orange"
    return "Severe", "red"


def average_limb_health(member):
    return sum(member["limbs"].values()) / len(member["limbs"])


def overall_health(member):
    """Average limb health, scaled down by the average damage taken: 100 is unhurt."""
    damage = member["damage"]
    return average_limb_health(member) * (1 - sum(damage.values()) / (len(damage) * 100))


def is_incapacitated(member):
    """Whether a crew member is too badly hurt to work or move: their overall health is in the Critical band."""
    return health_band(overall_health(member))[0] == "Critical"


def heal_fully(member):
    """Restore every limb and clear every damage type."""
    for limb in member["limbs"]:
        member["limbs"][limb] = 100
    for damage_type in member["damage"]:
        member["damage"][damage_type] = 0


def change_limb(member, limb, amount):
    """Add amount (negative hurts) to a limb, kept within 0-100. Returns (before, after)."""
    before = member["limbs"][limb]
    member["limbs"][limb] = max(0, min(100, before + amount))
    return before, member["limbs"][limb]


def reduce_damage(member, dtype, amount):
    """Take amount off a damage type, down to 0. Returns (before, after)."""
    before = member["damage"][dtype]
    member["damage"][dtype] = max(0, before - amount)
    return before, member["damage"][dtype]
