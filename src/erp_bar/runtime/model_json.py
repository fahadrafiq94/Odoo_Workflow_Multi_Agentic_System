"""One shared, strict boundary between model text and executable proposals."""
import json
import re


def _without_leading_thinking(text):
    text = text.strip()
    while text.lower().startswith("<think>"):
        end = text.lower().find("</think>")
        if end < 0:
            raise ValueError("The model returned an unfinished thinking block, not a JSON response.")
        text = text[end + len("</think>"):].strip()
    return text


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys are not allowed in a proposal.")
        result[key] = value
    return result


def parse_model_object(response):
    """Allow presentation wrappers, but never select one of multiple proposals."""
    text = _without_leading_thinking(response)
    fence = re.match(r"^```(?:json)?\s*\n", text, re.I)
    if fence:
        text = text[fence.end():].lstrip()
    decoder = json.JSONDecoder(object_pairs_hook=_unique_keys)
    data, end = decoder.raw_decode(text)
    if not isinstance(data, dict):
        raise ValueError("Return one JSON object, not a list or scalar.")
    tail = text[end:].strip()
    if fence:
        if not tail.startswith("```"):
            raise ValueError("The JSON code fence was not closed.")
        tail = tail[3:].strip()
    tail = _without_leading_thinking(tail)
    if tail:
        raise ValueError(
            f"Return exactly one JSON object. Extra text or another object follows it at character {end}. "
            "Do not append an explanation or repeat the JSON."
        )
    return data
