"""The original smile score, with explicit customer arming and stable timing."""
from collections import deque
import time


class SmileGate:
    def __init__(self, threshold=.75, frames=5, cooldown=15, hold=.6):
        self.threshold, self.cooldown, self.hold = threshold, cooldown, hold
        self.scores = deque(maxlen=frames)
        self.armed = False
        self.since = None
        self.last_trigger = float('-inf')
        self.score = 0.
        self.neutral_seen = False

    def arm(self):
        self.armed = True
        self.scores.clear()
        self.since = None
        self.neutral_seen = False

    def disarm(self):
        self.armed = False
        self.since = None
        self.scores.clear()

    def update(self, score, now=None, eligible=True):
        now = time.monotonic() if now is None else now
        if score is None:
            self.scores.clear()
            self.score = 0
            self.since = None
            self.neutral_seen = False
            return False
        self.scores.append(max(0., min(1., float(score))))
        self.score = sum(self.scores) / len(self.scores)
        if self.score < .4:
            self.neutral_seen = True
        # A held smile can be the first expression after arming. One-shot arming
        # and the cooldown prevent repeated requests without a hidden neutral gate.
        ready = (self.armed and eligible and len(self.scores) == self.scores.maxlen
                 and now - self.last_trigger >= self.cooldown and self.score >= self.threshold)
        if not ready:
            self.since = None
            return False
        if self.since is None:
            self.since = now
        if now - self.since < self.hold:
            return False
        self.armed = False
        self.last_trigger = now
        self.since = None
        return True


def smile_score(blendshapes):
    scores = {c.category_name: c.score for c in blendshapes}
    return (scores.get('mouthSmileLeft', 0) + scores.get('mouthSmileRight', 0)) / 2
