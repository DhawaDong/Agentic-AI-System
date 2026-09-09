"""
Thin wrapper around the Groq chat completions API.
Every agent in the pipeline calls `call_agent(...)` — this is the single
choke point where we talk to Groq, so retries/logging/JSON-parsing live here
instead of being duplicated in every agent.
"""
import json
import logging
import time

from groq import Groq

from core import config

logger = logging.getLogger("agent.llm")

_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set")
        _client = Groq(api_key=config.GROQ_API_KEY)
    return _client


def call_agent(system_prompt: str, user_prompt: str, model: str = None,
                temperature: float = 0.3, max_tokens: int = 2000,
                json_mode: bool = False, retries: int = 3) -> str:
    """
    Calls a Groq chat model playing the role described by `system_prompt`.
    Returns the raw text response (or a JSON string if json_mode=True).
    """
    model = model or config.SMART_MODEL
    client = _get_client()

    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("Groq call failed (attempt %s/%s): %s", attempt, retries, e)
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Groq call failed after {retries} attempts: {last_err}")


def call_agent_json(system_prompt: str, user_prompt: str, model: str = None,
                     temperature: float = 0.2, max_tokens: int = 2000) -> dict:
    """
    Calls the agent and parses the reply as JSON. Falls back to extracting
    the first {...} block if the model wraps JSON in prose despite instructions.
    """
    text = call_agent(system_prompt, user_prompt, model=model,
                       temperature=temperature, max_tokens=max_tokens, json_mode=True)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        logger.error("Could not parse JSON from model output: %s", text[:500])
        return {}
