"""Names of templates, ROIs and points shared by calibration, vision and actions."""
from __future__ import annotations

from coc_bot.config import Settings

# Screen markers / buttons
HOME_ATTACK = "home_attack"          # Attack button on the home village
BTN_FIND_MATCH = "btn_find_match"    # "Find a Match" in the attack menu
BTN_NEXT = "btn_next"                # Next button while previewing an enemy base
BTN_END_BATTLE = "btn_end_battle"    # End Battle / Surrender button
BTN_RETURN_HOME = "btn_return_home"  # Return Home on the battle result screen
BTN_ARMY = "btn_army"                # Army / train button on the home village
ARMY_CLOSE = "army_close"            # X that closes the army window
ARMY_FULL = "army_full"              # indicator that the army is complete
TAB_QUICK_TRAIN = "tab_quick_train"  # Quick Train tab in the army window
BTN_TRAIN_SAVED = "btn_train_saved"  # Train button of saved army #1
SEARCHING = "searching"              # clouds while searching for opponent

# Popups, in priority order
POPUP_RELOAD = "popup_reload"
POPUP_TRY_AGAIN = "popup_try_again"
POPUP_OKAY = "popup_okay"
POPUP_CLOSE = "popup_close"
POPUP_TEMPLATES = (POPUP_RELOAD, POPUP_TRY_AGAIN, POPUP_OKAY, POPUP_CLOSE)

REQUIRED_TEMPLATES = (
    HOME_ATTACK, BTN_FIND_MATCH, BTN_NEXT, BTN_END_BATTLE, BTN_RETURN_HOME,
    BTN_ARMY, ARMY_CLOSE, ARMY_FULL, TAB_QUICK_TRAIN, BTN_TRAIN_SAVED, POPUP_OKAY,
)
OPTIONAL_TEMPLATES = (SEARCHING, POPUP_RELOAD, POPUP_TRY_AGAIN, POPUP_CLOSE)

# Loot ROIs on the enemy base preview
ROI_GOLD = "gold"
ROI_ELIXIR = "elixir"
ROI_DE = "de"
REQUIRED_ROIS = (ROI_GOLD, ROI_ELIXIR)
OPTIONAL_ROIS = (ROI_DE,)
MAX_GOLD = 5_000_000
MAX_ELIXIR = 5_000_000
MAX_DE = 100_000

# Points: map diamond corners (fully zoomed out) and troop card slots
MAP_CORNERS = ("map_top", "map_right", "map_bottom", "map_left")


def troop_slot(n: int) -> str:
    return f"troop_slot_{n}"


def required_points(troop_slots: tuple[int, ...]) -> tuple[str, ...]:
    return MAP_CORNERS + tuple(troop_slot(n) for n in troop_slots)


def valid_names(kind: str, troop_slots: tuple[int, ...]) -> tuple[str, ...]:
    if kind == "template":
        return REQUIRED_TEMPLATES + OPTIONAL_TEMPLATES
    if kind == "roi":
        return REQUIRED_ROIS + OPTIONAL_ROIS
    if kind == "point":
        return required_points(troop_slots)
    raise ValueError(f"Unknown kind: {kind}")


def missing_calibration(settings: Settings, template_names: set[str]) -> list[str]:
    cal = settings.calibration
    missing = [
        f"template:{n}" for n in REQUIRED_TEMPLATES
        if n not in template_names or n not in cal.templates
    ]
    missing += [f"roi:{n}" for n in REQUIRED_ROIS if n not in cal.rois]
    missing += [
        f"point:{n}" for n in required_points(settings.deploy.troop_slots) if n not in cal.points
    ]
    return missing
