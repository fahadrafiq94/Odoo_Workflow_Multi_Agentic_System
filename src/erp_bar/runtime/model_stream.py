"""Stream the user's local model output without changing its executable reply."""
import os
import time


class Redactor:
    def __init__(self):
        self.secrets = sorted({value for key, value in os.environ.items()
                               if any(word in key.upper() for word in ("PASSWORD", "SECRET", "TOKEN", "API_KEY"))
                               and len(value) >= 4}, key=len, reverse=True)
        self.pending = ""

    def feed(self, text, final=False):
        value = self.pending + text
        for secret in self.secrets:
            value = value.replace(secret, "[redacted]")
        hold = 0
        for secret in self.secrets:
            for size in range(min(len(secret) - 1, len(value)), hold, -1):
                if value.endswith(secret[:size]):
                    hold = size
                    break
        self.pending = value[-hold:] if hold else ""
        value = value[:-hold] if hold else value
        if final:
            value += "[redacted]" if self.pending else ""
            self.pending = ""
        return value


class GenerationStream:
    """Small deltas while running, one authoritative full snapshot on completion."""
    def __init__(self, publish):
        self.publish = publish
        self.redactors = {phase: Redactor() for phase in ("thinking", "output")}
        self.full = {"thinking": "", "output": ""}
        self.pending = {"thinking": "", "output": ""}
        self.last = {"thinking": 0.0, "output": 0.0}

    def feed(self, phase, text):
        if not text:
            return
        safe = self.redactors[phase].feed(text)
        self.pending[phase] += safe
        # First tokens appear immediately; subsequent chunks are batched for the UI.
        if self.pending[phase] and (not self.full[phase] or time.monotonic() - self.last[phase] >= .08
                                   or len(self.pending[phase]) >= 128):
            self.flush(phase)

    def flush(self, phase):
        delta = self.pending[phase]
        if delta:
            self.full[phase] += delta
            self.pending[phase] = ""
            self.last[phase] = time.monotonic()
            self.publish("model_stream", phase=phase, delta=delta)

    def finish(self, interrupted=False):
        for phase in self.full:
            self.pending[phase] += self.redactors[phase].feed("", final=True)
            self.flush(phase)
        self.publish("model_stream_end", **self.full, interrupted=interrupted)


def text_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block if isinstance(block, str) else block.get("text", "")
                       for block in content if isinstance(block, str)
                       or isinstance(block, dict) and block.get("type") == "text")
    return ""
