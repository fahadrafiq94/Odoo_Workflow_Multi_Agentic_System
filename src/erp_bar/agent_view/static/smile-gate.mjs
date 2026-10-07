// Scores are expression estimates, not a probability of a customer's intent.
export class SmileGate {
  constructor() {
    this.samples = []; this.since = null; this.neutralSince = null;
    this.needsNeutral = false; this.lastTrigger = -Infinity; this.score = null;
  }
  pause() {
    this.samples = []; this.since = this.neutralSince = null;
    this.needsNeutral = true;
  }
  update(value, now, eligible) {
    if (!eligible) { this.pause(); this.score = value; return false; }
    if (value == null || !Number.isFinite(value)) {
      this.samples = []; this.score = null; this.since = null;
    } else {
      this.samples.push(Math.max(0, Math.min(1, value)));
      if (this.samples.length > 5) this.samples.shift();
      this.score = this.samples.reduce((a, b) => a + b, 0) / this.samples.length;
    }
    if (this.needsNeutral) {
      if (this.score == null || this.score < .4) {
        this.neutralSince ??= now;
        if (now - this.neutralSince >= 1200) this.needsNeutral = false;
      } else this.neutralSince = null;
      return false;
    }
    if (now - this.lastTrigger < 15000 || this.score == null || this.score < .75) {
      this.since = null; return false;
    }
    this.since ??= now;
    if (now - this.since < 600) return false;
    this.lastTrigger = now; this.pause(); return true;
  }
}
