"""Builder Base (desa malam) actions on top of the shared Game primitives."""
from __future__ import annotations

import logging

from coc_bot import names as N
from coc_bot.config import Point
from coc_bot.game.actions import Game
from coc_bot.vision.cards import ability_ready
from coc_bot.vision.screens import Screen, detect_builder_screen
from coc_bot.vision.stage import is_stage2_map

log = logging.getLogger(__name__)

DROP_SPREAD_PX = 12   # one deploy point, but not the same pixel every tap
BOAT_SWIPES = 2       # drags towards the bottom-left shore when the boat is off screen
SHORE_SWIPE = (600, 400, 900, 150)   # finger up-right = map moves up-right = bottom-left comes into view
BOAT_THRESHOLD = 0.80  # the boat bubble sits on sand, sea or the event panel: looser than buttons
CART_THRESHOLD = 0.72  # the cart looks different empty / full (bottles, bubble); nothing else scores > 0.4
CART_SCALES = (1.0, 1.4)  # zoom when arriving by boat / the closer default zoom after a battle
DOCK_SWIPE = (800, 200, 450, 500)  # finger down-left = map moves down-left = the dock (top-right) comes into view
CARD_SELECT_S = 0.4   # a map tap right after selecting a card is ignored by the game
DROP_CHECK_S = 0.8    # wait before checking whether the first drop started the battle


class BuilderGame(Game):
    def screen(self) -> Screen:
        return detect_builder_screen(self.capture(), self.templates)

    # --- helpers ------------------------------------------------------------
    def _point(self, name: str) -> Point | None:
        return self.settings.calibration.points.get(name)

    def _spread(self, pt: Point) -> Point:
        s = DROP_SPREAD_PX
        return (pt[0] + self.rng.randint(-s, s), pt[1] + self.rng.randint(-s, s))

    def _drop(self, slot: int, target: Point, taps: int) -> bool:
        card = self._point(N.bb_slot(slot))
        if card is None:
            log.warning("Card bb_slot_%d is not calibrated, skipped", slot)
            return False
        self.tap(card)
        self.sleep(CARD_SELECT_S)
        for _ in range(taps):
            self.tap(self._spread(target))
        return True

    def _tap_card(self, slot: int) -> None:
        card = self._point(N.bb_slot(slot))
        if card is not None:
            self.tap(card)

    # --- village / search -----------------------------------------------------
    def go_to_builder_base(self) -> bool:
        # the boat moves with the camera: search the whole screen, drag the map towards it if needed
        match = self.templates.find(self.capture(), N.BB_BOAT, BOAT_THRESHOLD, anywhere=True)
        for _ in range(BOAT_SWIPES):
            if match is not None:
                break
            log.info("Boat not on screen, dragging the map towards the shore")
            self.adb.swipe(*SHORE_SWIPE, 600)
            self.sleep(1.0)
            match = self.templates.find(self.capture(), N.BB_BOAT, BOAT_THRESHOLD, anywhere=True)
        if match is None:
            return False
        self.tap(match.center)
        self.sleep(6.0)   # sailing + loading
        return True

    def open_attack(self) -> bool:
        if not self.tap_template(N.BB_ATTACK, fresh=False):
            return False
        if not self.wait_for(N.BB_BTN_FIND_NOW, timeout_s=4.0):
            log.warning("Find Now did not appear after tapping Attack")
            return False
        return self.tap_template(N.BB_BTN_FIND_NOW, fresh=False)

    # --- deploy ---------------------------------------------------------------
    def _deploy_points(self, stage: int) -> list[Point]:
        return [p for name in N.bb_deploy_points(stage) if (p := self._point(name)) is not None]

    def _open_battle(self, slot: int, stage: int) -> Point | None:
        """Drop the first card at the first deploy point that starts the battle.

        Corners are tried first but the defender may have a building there: a drop on a blocked
        spot does nothing and the "battle starts in" banner stays, so the next point is tried.
        """
        card = self._point(N.bb_slot(slot))
        points = self._deploy_points(stage)
        if card is None or not points:
            log.warning("Card bb_slot_%d or the stage-%d deploy point is not calibrated", slot, stage)
            return None
        self.tap(card)
        self.sleep(CARD_SELECT_S)
        for point in points:
            self.tap(self._spread(point))
            self.sleep(DROP_CHECK_S)
            if self.templates.find(self.capture(), N.BB_PREP) is None:
                log.info("Stage %d: deploying at %s", stage, point)
                return point
            log.info("Deploy point %s is blocked, trying the next one", point)
        log.warning("No stage-%d deploy point worked", stage)
        return None

    def drop_one_troop(self) -> bool:
        return self._open_battle(self.settings.builder.troop_slot, stage=1) is not None

    def deploy_stage(self, stage: int) -> None:
        b = self.settings.builder
        target = self._open_battle(b.hero_slot, stage)
        if target is None:
            return
        self.sleep(1.0)
        if b.tank_slot > 0:
            self._drop(b.tank_slot, target, b.taps_per_slot)
            self.sleep(b.witch_delay_s)
        for slot in b.main_slots + (b.stage2_slots if stage == 2 else ()):
            self._drop(slot, target, b.taps_per_slot)

    def hero_ability(self) -> bool:
        """Fire the hero ability if its card shows it charged (pale card = still charging)."""
        card = self._point(N.bb_slot(self.settings.builder.hero_slot))
        if card is None or not ability_ready(self.capture(), card):
            return False
        self.tap(card)
        return True

    def troop_abilities(self) -> None:
        """Tap the deployed Night Witch cards once (Bat Swarm)."""
        b = self.settings.builder
        for i, slot in enumerate(b.main_slots):
            if i:
                self.sleep(b.bat_swarm_gap_s)
            self._tap_card(slot)

    # --- battle ---------------------------------------------------------------
    def surrender(self) -> bool:
        """Surrender / End Battle (also ends the battle on the stage-2 screen) and confirm."""
        tapped = (self.tap_template(N.BB_BTN_SURRENDER)
                  or self.tap_template(N.BB_BTN_END_BATTLE, fresh=False))
        if tapped and self.wait_for(N.POPUP_OKAY, timeout_s=3.0):
            self.tap_template(N.POPUP_OKAY, fresh=False)
        return tapped

    def battle_stage(self) -> int:
        """Stage of the battle on screen, from the battlefield colour (green = 1, dark blue = 2)."""
        return 2 if is_stage2_map(self._image(fresh=False)) else 1

    def read_damage(self) -> int | None:
        roi = self.settings.calibration.rois.get(N.ROI_BB_DAMAGE)
        if roi is None:
            return None
        return self.ocr.read_number(self._image(fresh=True), roi, N.MAX_BB_DAMAGE)

    def read_result_gold(self) -> int | None:
        roi = self.settings.calibration.rois.get(N.ROI_BB_RESULT_GOLD)
        if roi is None:
            return None
        return self.ocr.read_number(self._image(fresh=False), roi, N.MAX_BB_GOLD)

    def return_home(self) -> bool:
        return self.tap_template(N.BB_BTN_RETURN_HOME, fresh=False)

    # --- Elixir Cart ------------------------------------------------------------
    def _find_cart(self, fresh: bool):
        return self.templates.find(self._image(fresh), N.BB_ELIXIR_CART, CART_THRESHOLD,
                                   anywhere=True, scales=CART_SCALES)

    def collect_cart(self) -> bool:
        # the cart moves with the camera, changes with its fill level and its size follows the zoom
        cart = self._find_cart(fresh=False)
        for _ in range(BOAT_SWIPES):
            if cart is not None:
                break
            log.info("Elixir Cart not on screen, dragging the map towards the dock")
            self.adb.swipe(*DOCK_SWIPE, 600)
            self.sleep(1.0)
            cart = self._find_cart(fresh=True)
        if cart is None:
            return False
        self.tap(cart.center)
        if not self.wait_for(N.BB_BTN_COLLECT, timeout_s=3.0):
            self.go_back()
            return False
        self.tap_template(N.BB_BTN_COLLECT, fresh=False)
        self.sleep(1.0)
        if not self.tap_template(N.POPUP_CLOSE):   # close the cart window
            self.go_back()
        return True
