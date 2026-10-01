"""One Ollama call: observable generation, then a separately validated JSON reply."""
import os

from langchain_ollama import ChatOllama
from erp_bar.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from erp_bar.runtime.events import observed_model, emit_model_stream
from erp_bar.runtime.model_stream import GenerationStream, text_content


def get_llm() -> ChatOllama:
    mode = os.getenv("OLLAMA_REASONING", "true").lower().strip()
    if mode not in {"true", "false", "auto"}:
        raise ValueError("OLLAMA_REASONING must be true, false, or auto.")
    return ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0,
        format="json",
        reasoning={"true": True, "false": False, "auto": None}[mode],
    )


@observed_model
def invoke_llm(system_prompt: str, user_prompt: str) -> str:
    # Native JSON generation keeps extra prose out of the executable response.
    # Each agent keeps its original schema/prompt. Python still validates all actions.
    llm = get_llm()
    display = GenerationStream(emit_model_stream)
    parts = []
    try:
        for chunk in llm.stream([("system", system_prompt), ("human", user_prompt)]):
            thinking = (getattr(chunk, "additional_kwargs", {}) or {}).get("reasoning_content", "")
            if isinstance(thinking, str):
                display.feed("thinking", thinking)
            content = text_content(chunk.content)
            if content:
                parts.append(content)
                display.feed("output", content)
    except Exception:
        display.finish(interrupted=True)
        raise
    display.finish()
    # Thinking is displayed but NEVER concatenated into the JSON for execution.
    return "".join(parts).strip()
