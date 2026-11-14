"""Builder Base (desa malam) actions on top of the shared Game primitives."""
from __future__ import annotations

import logging

from coc_bot import names as N
from coc_bot.config import Point
from coc_bot.game.actions import Game
from coc_bot.vision.screens import Screen, detect_builder_screen

log = logging.getLogger(__name__)

DROP_SPREAD_PX = 12   # one deploy point, but not the same pixel every tap


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
        for _ in range(taps):
            self.tap(self._spread(target))
        return True

    def _tap_card(self, slot: int) -> None:
        card = self._point(N.bb_slot(slot))
        if card is not None:
            self.tap(card)

    # --- village / search -----------------------------------------------------
    def go_to_builder_base(self) -> bool:
        if not self.tap_template(N.BB_BOAT):
            return False
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
    def drop_one_troop(self) -> bool:
        target = self._point(N.BB_DEPLOY_STAGE1)
        if target is None:
            return False
        return self._drop(self.settings.builder.troop_slot, target, taps=1)

    def deploy_stage(self, stage: int) -> None:
        b = self.settings.builder
        target = self._point(N.BB_DEPLOY_STAGE1 if stage == 1 else N.BB_DEPLOY_STAGE2)
        if target is None:
            log.warning("Deploy point for stage %d is not calibrated", stage)
            return
        self._drop(b.hero_slot, target, taps=1)
        self.sleep(1.0)
        if b.tank_slot > 0:
            self._drop(b.tank_slot, target, b.taps_per_slot)
            self.sleep(b.witch_delay_s)
        for slot in b.main_slots + (b.stage2_slots if stage == 2 else ()):
            self._drop(slot, target, b.taps_per_slot)

    def hero_ability(self) -> None:
        """Tap the hero card: fires the ability when charged, does nothing otherwise."""
        self._tap_card(self.settings.builder.hero_slot)

    def troop_abilities(self) -> None:
        """Tap the deployed Night Witch cards once (Bat Swarm)."""
        for slot in self.settings.builder.main_slots:
            self._tap_card(slot)

    # --- battle ---------------------------------------------------------------
    def surrender(self) -> bool:
        """Surrender / End Battle (also ends the battle on the stage-2 screen) and confirm."""
        tapped = (self.tap_template(N.BB_BTN_SURRENDER)
                  or self.tap_template(N.BB_BTN_END_BATTLE, fresh=False))
        if tapped and self.wait_for(N.POPUP_OKAY, timeout_s=3.0):
            self.tap_template(N.POPUP_OKAY, fresh=False)
        return tapped

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
    def collect_cart(self) -> bool:
        if not self.tap_template(N.BB_ELIXIR_CART, fresh=False):
            return False
        if not self.wait_for(N.BB_BTN_COLLECT, timeout_s=3.0):
            self.go_back()
            return False
        self.tap_template(N.BB_BTN_COLLECT, fresh=False)
        self.sleep(1.0)
        if not self.tap_template(N.POPUP_CLOSE):   # close the cart window
            self.go_back()
        return True
