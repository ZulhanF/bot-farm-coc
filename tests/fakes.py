"""Shared test doubles. Later tasks append more fakes to this file."""
from coc_bot.vision.templates import Match


class FakeTemplates:
    def __init__(self, visible=(), positions=None):
        self.visible = set(visible)
        self.positions = positions or {}

    def find(self, image, name, threshold=None):
        if name not in self.visible:
            return None
        x, y = self.positions.get(name, (100, 100))
        return Match(name, x, y, 10, 10, 0.99)

    def names(self):
        return sorted(self.visible)
