"""Extract only the explicit, top-level public reason from a partial JSON reply."""
import json
import os
import re

from erp_bar.runtime.events import clean_text


def reason_prefix(content):
    text = content.lstrip()
    # Never search for JSON inside a model's private reasoning blocks.
    while text.lower().startswith("<think>"):
        end = text.lower().find("</think>")
        if end < 0:
            return ""
        text = text[end + 8:].lstrip()
    if text.startswith("```"):
        if "\n" not in text:
            return ""
        text = text.split("\n", 1)[1].lstrip()
    if not text.startswith("{"):
        return ""
    decoder = json.JSONDecoder()
    pos = 1
    try:
        while True:
            while pos < len(text) and text[pos].isspace():
                pos += 1
            key, pos = decoder.raw_decode(text, pos)
            if not isinstance(key, str):
                return ""
            while pos < len(text) and text[pos].isspace():
                pos += 1
            if text[pos] != ":":
                return ""
            pos += 1
            while pos < len(text) and text[pos].isspace():
                pos += 1
            if key == "reason":
                if text[pos] != '"':
                    return ""
                start = pos
                pos += 1
                # Decode only complete JSON escape sequences; an unfinished escape waits.
                while pos < len(text):
                    if text[pos] == '"':
                        value = json.loads(text[start:pos + 1])
                        return safe_prefix(value)
                    if text[pos] == "\\":
                        width = 6 if text[pos + 1:pos + 2] == "u" else 2
                        if pos + width > len(text):
                            break
                        pos += width
                    else:
                        pos += 1
                return safe_prefix(json.loads(text[start:pos] + '"'))
            _, pos = decoder.raw_decode(text, pos)
            while pos < len(text) and text[pos].isspace():
                pos += 1
            if text[pos] != ",":
                return ""
            pos += 1
    except (ValueError, IndexError):
        return ""


def safe_prefix(value):
    # Withhold suffixes that might become a secret or a markup block next chunk.
    for key, secret in os.environ.items():
        if any(word in key.upper() for word in ("PASSWORD", "SECRET", "TOKEN", "API_KEY")) and len(secret) >= 4:
            value = value.replace(secret, "[redacted]")
            for size in range(min(len(value), len(secret) - 1), 0, -1):
                if value.endswith(secret[:size]):
                    value = value[:-size]
                    break
    value = re.sub(r"<[^>]*$", "", value)
    value = clean_text(value)
    # A surrogate pair may be split across JSON chunks.
    return value.encode("utf-8", "replace").decode("utf-8")
