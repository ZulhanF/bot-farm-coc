"""Names of templates, ROIs and points shared by calibration, vision and actions."""
from __future__ import annotations

from coc_bot.config import BB_MAX_SLOTS, Settings

# Screen markers / buttons
HOME_ATTACK = "home_attack"          # Attack button on the home village
BTN_FIND_MATCH = "btn_find_match"    # "Find a Match" in the attack menu
BTN_ATTACK = "btn_attack"            # "Serang!" button in confirmation screen
BTN_SURRENDER = "btn_surrender"      # "Menyerah" button during active battle
BTN_NEXT = "btn_next"                # Next button while previewing an enemy base
BTN_END_BATTLE = "btn_end_battle"    # End Battle / Surrender button
BTN_RETURN_HOME = "btn_return_home"  # Return Home on the battle result screen
SEARCHING = "searching"              # clouds while searching for opponent

# Popups, in priority order
POPUP_RELOAD = "popup_reload"
POPUP_TRY_AGAIN = "popup_try_again"
POPUP_OKAY = "popup_okay"
POPUP_CLOSE = "popup_close"
POPUP_TEMPLATES = (POPUP_RELOAD, POPUP_TRY_AGAIN, POPUP_OKAY, POPUP_CLOSE)

# Builder Base (desa malam)
BB_BOAT = "bb_boat"                    # boat on the home village that sails to the Builder Base
BB_ATTACK = "bb_attack"                # Attack button on the Builder Base (also its screen marker)
BB_BTN_FIND_NOW = "bb_btn_find_now"    # "Find Now" in the Builder Base attack panel
BB_SEARCHING = "bb_searching"          # searching for an opponent
BB_PREP = "bb_prep"                    # preparation banner ("battle starts in ..."), both stages
BB_BTN_SURRENDER = "bb_btn_surrender"  # Surrender during a Builder Base battle
BB_BTN_END_BATTLE = "bb_btn_end_battle"  # "Akhiri Serangan": replaces Surrender after a star; also on stage-2 prep
BB_BTN_RETURN_HOME = "bb_btn_return_home"  # Return Home on the Builder Base result screen
BB_ELIXIR_CART = "bb_elixir_cart"      # the Elixir Cart next to the boat
BB_BTN_COLLECT = "bb_btn_collect"      # Collect in the Elixir Cart window
BB_TEMPLATES = (
    BB_BOAT, BB_ATTACK, BB_BTN_FIND_NOW, BB_SEARCHING, BB_PREP, BB_BTN_SURRENDER,
    BB_BTN_END_BATTLE, BB_BTN_RETURN_HOME, BB_ELIXIR_CART, BB_BTN_COLLECT,
)

REQUIRED_TEMPLATES = (
    HOME_ATTACK, BTN_FIND_MATCH, BTN_ATTACK, BTN_NEXT, BTN_END_BATTLE, BTN_RETURN_HOME, POPUP_OKAY,
)
OPTIONAL_TEMPLATES = (
    SEARCHING, POPUP_RELOAD, POPUP_TRY_AGAIN, POPUP_CLOSE, BTN_SURRENDER,
)

# Loot ROIs on the enemy base preview
ROI_GOLD = "gold"
ROI_ELIXIR = "elixir"
ROI_DE = "de"
# Own resource bars (the coloured fill, without the icon) -> storage-full check without any capacity
ROI_HOME_GOLD_BAR = "home_gold_bar"
ROI_HOME_ELIXIR_BAR = "home_elixir_bar"
ROI_HOME_DE_BAR = "home_de_bar"
HOME_BAR_ROIS = (ROI_HOME_GOLD_BAR, ROI_HOME_ELIXIR_BAR, ROI_HOME_DE_BAR)

REQUIRED_ROIS = (ROI_GOLD, ROI_ELIXIR)
OPTIONAL_ROIS = (ROI_DE,) + HOME_BAR_ROIS
MAX_GOLD = 5_000_000
MAX_ELIXIR = 5_000_000
MAX_DE = 100_000
ROI_LIMITS = {ROI_GOLD: MAX_GOLD, ROI_ELIXIR: MAX_ELIXIR, ROI_DE: MAX_DE}
ROI_BB_DAMAGE = "bb_damage"            # destruction % during a Builder Base battle (0-200)
ROI_BB_RESULT_GOLD = "bb_result_gold"  # Builder Gold won, on the result screen
BB_ROIS = (ROI_BB_DAMAGE, ROI_BB_RESULT_GOLD)
MAX_BB_DAMAGE = 200
MAX_BB_GOLD = 10_000_000

# Points: map diamond corners (fully zoomed out) and troop card slots
MAP_CORNERS = ("map_top", "map_right", "map_bottom", "map_left")
MAP_CLOCK_POINTS = ("map_11", "map_9", "map_1", "map_3")
MAP_CENTER = "map_center"           # middle of the enemy base; spells aim from the deploy line towards it
BB_DEPLOY_STAGE1 = "bb_deploy_stage1"  # the single deploy point on stage 1
BB_DEPLOY_STAGE2 = "bb_deploy_stage2"  # the single deploy point on stage 2


def bb_slot(n: int) -> str:
    return f"bb_slot_{n}"


def troop_slot(n: int) -> str:
    return f"troop_slot_{n}"


def required_points(
    troop_slots: tuple[int, ...],
    pattern: str = "all",
    hero_slots: tuple[int, ...] = (),
    siege_slot: int = 0,
) -> tuple[str, ...]:
    all_slots = set(troop_slots) | set(hero_slots)
    if siege_slot > 0:
        all_slots.add(siege_slot)
    slot_points = tuple(troop_slot(n) for n in sorted(all_slots))
    if uses_clock_points(pattern):
        return MAP_CLOCK_POINTS + slot_points
    return MAP_CORNERS + slot_points


# resource -> bar ROI (the coloured fill of the home resource bar)
STORAGE_BARS = (
    ("gold", ROI_HOME_GOLD_BAR),
    ("elixir", ROI_HOME_ELIXIR_BAR),
    ("de", ROI_HOME_DE_BAR),
)


def storage_checks(settings: Settings) -> list[str]:
    """Resources whose storage-full check is on: those with a calibrated bar ROI."""
    rois = settings.calibration.rois
    return [resource for resource, bar_roi in STORAGE_BARS if bar_roi in rois]


def uses_clock_points(pattern: str) -> bool:
    """v_top / clock / lines deploy along map_11-map_9 and map_1-map_3, the rest along the corners."""
    return pattern in ("v_top", "clock", "lines")


def used_slots(settings: Settings) -> tuple[int, ...]:
    """Every card slot the army uses: troops, heroes, siege and spells."""
    d = settings.deploy
    slots = set(d.troop_slots) | set(d.hero_slots) | set(settings.spells.slots)
    if d.siege_slot > 0:
        slots.add(d.siege_slot)
    return tuple(sorted(slots))


def loot_filter_on(settings: Settings) -> bool:
    loot = settings.loot
    return loot.min_gold > 0 or loot.min_elixir > 0 or loot.min_de > 0


def relevant_names(settings: Settings) -> list[tuple[str, str]]:
    """(kind, name) of every calibration item that does something with the current settings."""
    items = [("template", n) for n in REQUIRED_TEMPLATES + OPTIONAL_TEMPLATES]
    if loot_filter_on(settings):
        items += [("roi", n) for n in REQUIRED_ROIS]
        if settings.loot.min_de > 0:
            items.append(("roi", ROI_DE))
    items += [("roi", n) for n in HOME_BAR_ROIS]
    corners = MAP_CLOCK_POINTS if uses_clock_points(settings.deploy.pattern) else MAP_CORNERS
    items += [("point", n) for n in corners]
    if settings.spells.slots:
        items.append(("point", MAP_CENTER))
    items += [("point", troop_slot(n)) for n in used_slots(settings)]
    return items


def valid_names(kind: str, troop_slots: tuple[int, ...]) -> tuple[str, ...]:
    if kind == "template":
        return REQUIRED_TEMPLATES + OPTIONAL_TEMPLATES + BB_TEMPLATES
    if kind == "roi":
        return REQUIRED_ROIS + OPTIONAL_ROIS + BB_ROIS
    if kind == "point":
        return (MAP_CLOCK_POINTS + MAP_CORNERS + (MAP_CENTER,)
                + (BB_DEPLOY_STAGE1, BB_DEPLOY_STAGE2)
                + tuple(bb_slot(n) for n in range(1, BB_MAX_SLOTS + 1))
                + tuple(troop_slot(n) for n in troop_slots))
    raise ValueError(f"Unknown kind: {kind}")


def missing_calibration(settings: Settings, template_names: set[str]) -> list[str]:
    cal = settings.calibration
    missing = [
        f"template:{n}" for n in REQUIRED_TEMPLATES
        if n not in template_names or n not in cal.templates
    ]
    if settings.loot.min_gold == 0 and settings.loot.min_elixir == 0:
        required_rois = (ROI_DE,) if settings.loot.min_de > 0 else ()
    else:
        required_rois = REQUIRED_ROIS + ((ROI_DE,) if settings.loot.min_de > 0 else ())
    missing += [f"roi:{n}" for n in required_rois if n not in cal.rois]
    missing += [
        f"point:{n}" for n in required_points(
            settings.deploy.troop_slots,
            settings.deploy.pattern,
            settings.deploy.hero_slots,
            settings.deploy.siege_slot,
        )
        if n not in cal.points
    ]
    spell_points = (MAP_CENTER,) + tuple(troop_slot(n) for n in settings.spells.slots)
    if settings.spells.slots:
        missing += [f"point:{n}" for n in spell_points
                    if n not in cal.points and f"point:{n}" not in missing]
    return missing


# --- Builder Base calibration -----------------------------------------------------------------
_BB_BASE_TEMPLATES = (
    HOME_ATTACK, BB_BOAT, BB_ATTACK, BB_BTN_FIND_NOW, BB_PREP, BB_BTN_SURRENDER, BB_BTN_RETURN_HOME,
    BB_ELIXIR_CART, BB_BTN_COLLECT, POPUP_OKAY,
)
_BB_OPTIONAL = (
    [("template", n) for n in (BB_SEARCHING, BB_BTN_END_BATTLE,
                               POPUP_RELOAD, POPUP_TRY_AGAIN, POPUP_CLOSE)]
    + [("roi", ROI_BB_DAMAGE), ("roi", ROI_BB_RESULT_GOLD)]
)


def builder_slots(settings: Settings) -> tuple[int, ...]:
    """Builder Base card slots the current [builder] settings tap."""
    b = settings.builder
    if b.mode == "elixir":
        return (b.troop_slot,)
    slots = {b.hero_slot, *b.main_slots}
    if b.tank_slot > 0:
        slots.add(b.tank_slot)
    if b.stage2:
        slots |= set(b.stage2_slots)
    return tuple(sorted(slots))


def builder_requirements(settings: Settings) -> list[tuple[str, str]]:
    """(kind, name) of every calibration item the builder mode cannot run without."""
    b = settings.builder
    gold = b.mode == "gold"
    items = [("template", n) for n in _BB_BASE_TEMPLATES]
    if gold:
        items += [("template", BB_BTN_END_BATTLE), ("roi", ROI_BB_DAMAGE)]
    items.append(("point", BB_DEPLOY_STAGE1))
    if gold and b.stage2:
        items.append(("point", BB_DEPLOY_STAGE2))
    items += [("point", bb_slot(n)) for n in builder_slots(settings)]
    return items


def missing_builder_calibration(settings: Settings, template_names: set[str]) -> list[str]:
    cal = settings.calibration
    have = {"template": cal.templates, "roi": cal.rois, "point": cal.points}
    return [
        f"{kind}:{name}" for kind, name in builder_requirements(settings)
        if name not in have[kind] or (kind == "template" and name not in template_names)
    ]


def missing_for_mode(settings: Settings, template_names: set[str], mode: str) -> list[str]:
    if mode == "builder":
        return missing_builder_calibration(settings, template_names)
    return missing_calibration(settings, template_names)


def relevant_for_mode(settings: Settings, mode: str) -> list[tuple[str, str]]:
    if mode != "builder":
        return relevant_names(settings)
    required = builder_requirements(settings)
    return required + [item for item in _BB_OPTIONAL if item not in required]
