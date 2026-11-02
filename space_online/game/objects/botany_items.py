"""Botany seed/liquid/tool item definitions and growth-class timers."""

BOTANY_SEED_IDS = (
    "tomato_seeds",
    "potato_seeds",
    "wheat_seeds",
    "carrot_seeds",
    "apple_seeds",
    "aloe_seeds",
)

# item_id -> (price in credits, most the vending machine holds)
BOTANY_VEND_CATALOG = {
    "tomato_seeds": (15, 10),
    "potato_seeds": (10, 10),
    "wheat_seeds": (10, 10),
    "carrot_seeds": (10, 10),
    "apple_seeds": (25, 5),
    "aloe_seeds": (20, 5),
    "watering_can": (40, 3),
    "miracle_grow": (50, 5),
    "plentiful_harvest": (75, 5),
    "the_ooze_mutagen": (100, 3),
    "trowel": (30, 3),
    "chainsaw": (150, 2),
}

# The vending machine gets back one of each item this often, up to its maximum.
VEND_RESTOCK_SECONDS = 5 * 60

# produce item_id -> price at the Botanist NPC's produce stand
BOTANIST_STAND_PRICES = {
    "potato": 15,
    "wheat": 15,
    "carrot": 15,
    "tomato": 20,
    "apple": 30,
    "aloe": 40,
}

GROWTH_STAGES = 5  # 1..5, mature at 5

GROWTH_CLASS_SECONDS = {
    "crop": 3 * 60,
    "fruiting": 5 * 60,
    "tree": 8 * 60,
}

GROWTH_STAGE_LABELS = {
    1: "Seedling",
    2: "Sprouting",
    3: "Growing",
    4: "Ripening",
    5: "Mature",
}

# Floor so Miracle Grow's speed bonus can never shrink a stage to ~0 seconds.
MIN_STAGE_SECONDS = 30

# Miracle Grow shortens each stage's duration by this fraction. Non-stacking:
# applying it again just keeps the bonus at this value.
MIRACLE_GROW_SPEED_BONUS = 0.1

# Plentiful Harvest multiplies produce quantity on the next harvest.
PLENTIFUL_HARVEST_YIELD_MULTIPLIER = 3

BOTANY_ITEMS = {
    "tomato_seeds": {
        "id": "tomato_seeds",
        "name": "Tomato Seeds",
        "description": "Grows into juicy red tomatoes.",
        "category": "Botany",
        "attributes": {
            "produces": "tomato",
            "plant_name": "Tomato",
            "growth_class": "fruiting",
            "vend_kinds": ["seed"],
        },
        "actions": ["examine", "equip", "drop"],
    },
    "potato_seeds": {
        "id": "potato_seeds",
        "name": "Potato Seeds",
        "description": "Produces starchy potatoes.",
        "category": "Botany",
        "attributes": {
            "produces": "potato",
            "plant_name": "Potato",
            "growth_class": "crop",
            "vend_kinds": ["seed"],
        },
        "actions": ["examine", "equip", "drop"],
    },
    "wheat_seeds": {
        "id": "wheat_seeds",
        "name": "Wheat Seeds",
        "description": "Grows into tall wheat stalks.",
        "category": "Botany",
        "attributes": {
            "produces": "wheat",
            "plant_name": "Wheat",
            "growth_class": "crop",
            "vend_kinds": ["seed"],
        },
        "actions": ["examine", "equip", "drop"],
    },
    "carrot_seeds": {
        "id": "carrot_seeds",
        "name": "Carrot Seeds",
        "description": "Produces orange root vegetables.",
        "category": "Botany",
        "attributes": {
            "produces": "carrot",
            "plant_name": "Carrot",
            "growth_class": "crop",
            "vend_kinds": ["seed"],
        },
        "actions": ["examine", "equip", "drop"],
    },
    "apple_seeds": {
        "id": "apple_seeds",
        "name": "Apple Seeds",
        "description": "Grows into small apple trees.",
        "category": "Botany",
        "attributes": {
            "produces": "apple",
            "plant_name": "Apple",
            "growth_class": "tree",
            "vend_kinds": ["seed"],
        },
        "actions": ["examine", "equip", "drop"],
    },
    "aloe_seeds": {
        "id": "aloe_seeds",
        "name": "Aloe Seeds",
        "description": "Grows into aloe plants whose gel soothes burns.",
        "category": "Botany",
        "attributes": {
            "produces": "aloe",
            "plant_name": "Aloe",
            "growth_class": "crop",
            "vend_kinds": ["seed"],
        },
        "actions": ["examine", "equip", "drop"],
    },
    "watering_can": {
        "id": "watering_can",
        "name": "Watering Can",
        "description": "A sturdy can for watering hydroponic planters.",
        "category": "Botany",
        "attributes": {
            "vend_kinds": ["liquid", "tool"],
        },
        "actions": ["examine", "equip", "drop"],
    },
    "miracle_grow": {
        "id": "miracle_grow",
        "name": "Miracle Grow",
        "description": "A potent liquid fertilizer for healthier plants.",
        "category": "Botany",
        "attributes": {
            "vend_kinds": ["liquid"],
        },
        "actions": ["examine", "equip", "drop"],
    },
    "plentiful_harvest": {
        "id": "plentiful_harvest",
        "name": "Plentiful Harvest",
        "description": "A growth serum that promises larger yields.",
        "category": "Botany",
        "attributes": {
            "vend_kinds": ["liquid"],
        },
        "actions": ["examine", "equip", "drop"],
    },
    "the_ooze_mutagen": {
        "id": "the_ooze_mutagen",
        "name": '"The Ooze" Mutagen',
        "description": "An unstable green mutagen. Handle with care.",
        "category": "Botany",
        "attributes": {
            "vend_kinds": ["liquid"],
        },
        "actions": ["examine", "equip", "drop"],
    },
    "trowel": {
        "id": "trowel",
        "name": "Trowel",
        "description": "A small hand tool for digging and transplanting.",
        "category": "Botany",
        "attributes": {
            "vend_kinds": ["tool"],
        },
        "actions": ["examine", "equip", "drop"],
    },
    "chainsaw": {
        "id": "chainsaw",
        "name": "Chainsaw",
        "description": "A powered saw for clearing stubborn plant growth.",
        "category": "Botany",
        "attributes": {
            "vend_kinds": ["tool"],
        },
        "actions": ["examine", "equip", "drop"],
    },
}


PLANTERS_PER_ROW = 4
PLANTER_ROWS = 4


def empty_planter():
    return {
        "occupied": False,
        "plant": None,
        "seed_id": None,
        "produces": None,
        "growth_class": None,
        "planted_at_seconds": None,
        "growth_stage": 0,
        "dead": False,
        "watered": False,
        "miracle_grow": 0.0,
        "yield_multiplier": 1,
        "ooze_applied": False,
        "announced": None,
    }


def new_botany():
    return {
        "planters": [empty_planter() for _ in range(PLANTERS_PER_ROW * PLANTER_ROWS)],
        "vending_stock": {item_id: most for item_id, (_, most) in BOTANY_VEND_CATALOG.items()},
        "vending_restocked_at_seconds": 0.0,
    }


def restock_vending(botany, elapsed_seconds):
    """Add the restocks due since the last one to the vending stock. Returns the stock."""
    stock = botany["vending_stock"]
    due = int((elapsed_seconds - botany["vending_restocked_at_seconds"]) // VEND_RESTOCK_SECONDS)
    if due > 0:
        for item_id, (_, most) in BOTANY_VEND_CATALOG.items():
            stock[item_id] = min(most, stock[item_id] + due)
        botany["vending_restocked_at_seconds"] += due * VEND_RESTOCK_SECONDS
    return stock


def growth_duration_seconds(growth_class):
    """Return seconds per stage advance for a growth class (defaults to crop)."""
    return GROWTH_CLASS_SECONDS.get(growth_class, GROWTH_CLASS_SECONDS["crop"])


def effective_stage_seconds(growth_class, miracle_grow=0.0):
    """Seconds per stage advance after Miracle Grow's speed bonus (floored)."""
    base = growth_duration_seconds(growth_class)
    boosted = base * (1 - float(miracle_grow or 0.0))
    return max(MIN_STAGE_SECONDS, boosted)


def apply_miracle_grow(planter, elapsed_seconds):
    """Give a planter Miracle Grow from now on.

    Stages are timed from planted_at_seconds, so it moves to where the faster
    stages would have put the plant's current progress.
    """
    growth_class = planter["growth_class"]
    old_stage_seconds = effective_stage_seconds(growth_class, planter["miracle_grow"])
    new_stage_seconds = effective_stage_seconds(growth_class, MIRACLE_GROW_SPEED_BONUS)
    grown = max(0.0, float(elapsed_seconds) - float(planter["planted_at_seconds"]))
    planter["planted_at_seconds"] = elapsed_seconds - grown * new_stage_seconds / old_stage_seconds
    planter["miracle_grow"] = MIRACLE_GROW_SPEED_BONUS


def _stage_timing(planted_at_seconds, growth_class, elapsed_seconds, miracle_grow):
    """(seconds since planting, seconds per stage)."""
    return (max(0.0, float(elapsed_seconds) - float(planted_at_seconds)),
            effective_stage_seconds(growth_class, miracle_grow))


def compute_growth_stage(planted_at_seconds, growth_class, elapsed_seconds, miracle_grow=0.0):
    """Return growth stage 1..GROWTH_STAGES from planted time vs master clock.

    GROWTH_CLASS_SECONDS is time spent on each stage before advancing; miracle_grow shortens each stage.
    """
    if planted_at_seconds is None:
        return 1
    elapsed, stage_len = _stage_timing(planted_at_seconds, growth_class, elapsed_seconds, miracle_grow)
    return min(GROWTH_STAGES, 1 + int(elapsed / stage_len))


def growth_stage_label(stage):
    """Display label for a growth stage."""
    return GROWTH_STAGE_LABELS.get(stage, "Growing")


def growth_seconds_to_next_stage(planted_at_seconds, growth_class, elapsed_seconds, miracle_grow=0.0):
    """Seconds until the next stage advance, or 0 if mature / missing data."""
    if planted_at_seconds is None:
        return 0
    stage = compute_growth_stage(planted_at_seconds, growth_class, elapsed_seconds, miracle_grow)
    if stage >= GROWTH_STAGES:
        return 0
    elapsed, stage_len = _stage_timing(planted_at_seconds, growth_class, elapsed_seconds, miracle_grow)
    next_at = stage * stage_len
    return max(0, int(next_at - elapsed))


def refresh_planter_growth(planter, elapsed_seconds):
    """Update an occupied planter's cached growth_stage from the game clock.

    Applies Miracle Grow's speed bonus and the watering-can survival rule: each
    watering carries the plant through one stage. If a stage is due while the
    planter hasn't been watered since its last advance, the plant dies and
    growth freezes there. The result is the same however long ago the planter
    was last looked at.

    Returns the current stage (0 if empty).
    """
    if not planter["occupied"]:
        return 0
    if planter.get("dead"):
        return int(planter.get("growth_stage") or 1)

    planted_at_seconds = planter.get("planted_at_seconds")
    if planted_at_seconds is None:
        return int(planter.get("growth_stage") or 1)

    miracle_grow = float(planter.get("miracle_grow") or 0.0)
    raw_stage = compute_growth_stage(
        planted_at_seconds, planter.get("growth_class"), elapsed_seconds, miracle_grow
    )
    previous_stage = int(planter.get("growth_stage") or 1)

    if raw_stage > previous_stage:
        if not planter.get("watered"):
            planter["dead"] = True
            planter["growth_stage"] = previous_stage
            return previous_stage
        reached = previous_stage + 1
        planter["growth_stage"] = reached
        if reached < GROWTH_STAGES:
            planter["watered"] = False
            if raw_stage > reached:
                planter["dead"] = True
        return reached

    planter["growth_stage"] = raw_stage
    return raw_stage


def refresh_all_planters_growth(player_data, elapsed_seconds):
    """Refresh growth_stage on all botany planters. Returns the planters list."""
    planters = player_data["botany"]["planters"]
    for planter in planters:
        refresh_planter_growth(planter, elapsed_seconds)
    return planters
