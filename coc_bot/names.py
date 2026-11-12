"""Names of templates, ROIs and points shared by calibration, vision and actions."""
from __future__ import annotations

from coc_bot.config import Settings

# Screen markers / buttons
HOME_ATTACK = "home_attack"          # Attack button on the home village
BTN_FIND_MATCH = "btn_find_match"    # "Find a Match" in the attack menu
BTN_ATTACK = "btn_attack"            # "Serang!" button in confirmation screen
BTN_SURRENDER = "btn_surrender"      # "Menyerah" button during active battle
BTN_NEXT = "btn_next"                # Next button while previewing an enemy base
BTN_END_BATTLE = "btn_end_battle"    # End Battle / Surrender button
BTN_RETURN_HOME = "btn_return_home"  # Return Home on the battle result screen
ARMY_CLOSE = "army_close"            # X that closes the army window
SEARCHING = "searching"              # clouds while searching for opponent

# Popups, in priority order
POPUP_RELOAD = "popup_reload"
POPUP_TRY_AGAIN = "popup_try_again"
POPUP_OKAY = "popup_okay"
POPUP_CLOSE = "popup_close"
POPUP_TEMPLATES = (POPUP_RELOAD, POPUP_TRY_AGAIN, POPUP_OKAY, POPUP_CLOSE)

REQUIRED_TEMPLATES = (
    HOME_ATTACK, BTN_FIND_MATCH, BTN_ATTACK, BTN_NEXT, BTN_END_BATTLE, BTN_RETURN_HOME, POPUP_OKAY,
)
OPTIONAL_TEMPLATES = (
    SEARCHING, POPUP_RELOAD, POPUP_TRY_AGAIN, POPUP_CLOSE, BTN_SURRENDER, ARMY_CLOSE,
)

# Loot ROIs on the enemy base preview
ROI_GOLD = "gold"
ROI_ELIXIR = "elixir"
ROI_DE = "de"
# Own resource counters on the home village (top right) -> storage-full check
ROI_HOME_GOLD = "home_gold"
ROI_HOME_ELIXIR = "home_elixir"
ROI_HOME_DE = "home_de"
HOME_ROIS = (ROI_HOME_GOLD, ROI_HOME_ELIXIR, ROI_HOME_DE)
# Own resource bars (the coloured fill, without the icon) -> storage-full check without any capacity
ROI_HOME_GOLD_BAR = "home_gold_bar"
ROI_HOME_ELIXIR_BAR = "home_elixir_bar"
ROI_HOME_DE_BAR = "home_de_bar"
HOME_BAR_ROIS = (ROI_HOME_GOLD_BAR, ROI_HOME_ELIXIR_BAR, ROI_HOME_DE_BAR)

REQUIRED_ROIS = (ROI_GOLD, ROI_ELIXIR)
OPTIONAL_ROIS = (ROI_DE,) + HOME_BAR_ROIS + HOME_ROIS
MAX_GOLD = 5_000_000
MAX_ELIXIR = 5_000_000
MAX_DE = 100_000
MAX_STORAGE = 100_000_000
MAX_STORAGE_DE = 1_000_000
ROI_LIMITS = {
    ROI_GOLD: MAX_GOLD, ROI_ELIXIR: MAX_ELIXIR, ROI_DE: MAX_DE,
    ROI_HOME_GOLD: MAX_STORAGE, ROI_HOME_ELIXIR: MAX_STORAGE, ROI_HOME_DE: MAX_STORAGE_DE,
}

# Points: map diamond corners (fully zoomed out) and troop card slots
MAP_CORNERS = ("map_top", "map_right", "map_bottom", "map_left")
MAP_CLOCK_POINTS = ("map_11", "map_9", "map_1", "map_3")
MAP_CENTER = "map_center"           # middle of the enemy base; spells aim from the deploy line towards it


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
    if pattern in ("v_top", "clock", "lines"):
        return MAP_CLOCK_POINTS + slot_points
    return MAP_CORNERS + slot_points


# resource -> (bar ROI, counter ROI, StorageConfig cap field)
STORAGE_RESOURCES = (
    ("gold", ROI_HOME_GOLD_BAR, ROI_HOME_GOLD, "gold_cap"),
    ("elixir", ROI_HOME_ELIXIR_BAR, ROI_HOME_ELIXIR, "elixir_cap"),
    ("de", ROI_HOME_DE_BAR, ROI_HOME_DE, "de_cap"),
)


def storage_checks(settings: Settings) -> list[tuple[str, str]]:
    """(resource, "bar" | "cap") for every resource whose fullness the bot can check.

    A calibrated bar ROI wins (no capacity needed); otherwise a cap > 0 uses the OCR'd counter.
    """
    rois = settings.calibration.rois
    checks = []
    for resource, bar_roi, _counter_roi, cap_field in STORAGE_RESOURCES:
        if bar_roi in rois:
            checks.append((resource, "bar"))
        elif getattr(settings.storage, cap_field) > 0:
            checks.append((resource, "cap"))
    return checks


def used_slots(settings: Settings) -> tuple[int, ...]:
    """Every card slot the army uses: troops, heroes, siege and spells."""
    d = settings.deploy
    slots = set(d.troop_slots) | set(d.hero_slots) | set(settings.spells.slots)
    if d.siege_slot > 0:
        slots.add(d.siege_slot)
    return tuple(sorted(slots))


def valid_names(kind: str, troop_slots: tuple[int, ...]) -> tuple[str, ...]:
    if kind == "template":
        return REQUIRED_TEMPLATES + OPTIONAL_TEMPLATES
    if kind == "roi":
        return REQUIRED_ROIS + OPTIONAL_ROIS
    if kind == "point":
        return MAP_CLOCK_POINTS + MAP_CORNERS + (MAP_CENTER,) + tuple(troop_slot(n) for n in troop_slots)
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
    required_rois = required_rois + tuple(
        counter_roi for _res, bar_roi, counter_roi, cap_field in STORAGE_RESOURCES
        if getattr(settings.storage, cap_field) > 0 and bar_roi not in cal.rois
    )
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
