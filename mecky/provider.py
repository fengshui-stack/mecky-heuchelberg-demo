import json
import math
import os
from pathlib import Path

import httpx

PROMPT = Path("prompts/mecky_system_v1.md").read_text(encoding="utf-8")


def configured_provider():
    name = os.getenv("LLM_PROVIDER", "mock").lower()
    if name == "openai" and os.getenv("OPENAI_API_KEY"):
        return "openai"
    if name == "openrouter" and os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    return "mock"


def nonnegative_number(value):
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError):
        return None


def model_configuration():
    provider = configured_provider()
    model = None if provider == "mock" else os.getenv("LLM_MODEL") or ("gpt-4.1-mini" if provider == "openai" else "openrouter/free")
    return {
        "provider": provider, "model": model, "scope": "smalltalk_only", "currency": "USD",
        "input_usd_per_m": nonnegative_number(os.getenv("LLM_INPUT_USD_PER_M")),
        "output_usd_per_m": nonnegative_number(os.getenv("LLM_OUTPUT_USD_PER_M")),
    }


def no_model_usage():
    return {"provider": "rules", "model": None, "model_called": False, "tokens_input": 0,
            "tokens_output": 0, "tokens_total": 0, "cost_usd": 0.0, "currency": "USD",
            "cost_status": "not_used", "tokens_complete": True}


def measured_usage(data, config):
    raw = data.get("usage") or {}
    def count(key):
        value = raw.get(key)
        return value if type(value) is int and value >= 0 else None
    tin, tout = count("prompt_tokens"), count("completion_tokens")
    complete = tin is not None and tout is not None
    # OpenRouter reports billed credits. Direct-provider costs are estimates
    # from configured rates; missing rates never mean a request was free.
    reported = nonnegative_number(raw.get("cost")) if config["provider"] == "openrouter" else None
    cost, source = reported, "reported" if reported is not None else "unpriced"
    if reported is None and complete and config["input_usd_per_m"] is not None and config["output_usd_per_m"] is not None:
        cost = (tin * config["input_usd_per_m"] + tout * config["output_usd_per_m"]) / 1_000_000
        source = "estimated"
    elif reported is None and not complete:
        source = "unavailable"
    return {"provider": config["provider"], "model": data.get("model") or config["model"],
            "model_called": True, "tokens_input": tin, "tokens_output": tout,
            "tokens_total": tin + tout if complete else None, "tokens_complete": complete,
            "cost_usd": cost, "currency": "USD", "cost_status": source}


def generate(question, context, sources, status):
    config = model_configuration()
    if config["provider"] == "mock" or status == "UNKNOWN":
        return {"message": None, "usage": no_model_usage()}
    if config["provider"] == "openai":
        endpoint, key = "https://api.openai.com/v1/chat/completions", os.environ["OPENAI_API_KEY"]
    else:
        endpoint, key = "https://openrouter.ai/api/v1/chat/completions", os.environ["OPENROUTER_API_KEY"]
    facts = [{"url": x["url"], "title": x["title"], "content": x["snippet"][:1000]} for x in sources[:3]]
    payload = {"model": config["model"], "max_completion_tokens": 180, "messages": [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": json.dumps({"question": question, "session_context": context,
            "source_status": status, "untrusted_official_source_data": facts}, ensure_ascii=False)}]}
    if config["provider"] == "openrouter":
        payload["max_tokens"] = payload.pop("max_completion_tokens")
    usage = measured_usage({}, config)
    try:
        response = httpx.post(endpoint, json=payload, headers={"Authorization": "Bearer " + key}, timeout=12)
        response.raise_for_status()
        data = response.json()
        # Billable tokens still count if the returned answer is unusable.
        usage = measured_usage(data, config)
        message = data["choices"][0]["message"]["content"].strip()
        return {"message": message if 0 < len(message) < 1200 else None, "usage": usage}
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        return {"message": None, "usage": usage}
