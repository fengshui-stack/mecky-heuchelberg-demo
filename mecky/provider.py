import json
import os
from pathlib import Path
import httpx
from .store import connect, now

PROMPT = Path("prompts/mecky_system_v1.md").read_text(encoding="utf-8")

def configured_provider():
    name = os.getenv("LLM_PROVIDER","mock").lower()
    if name == "openai" and os.getenv("OPENAI_API_KEY"):
        return "openai"
    if name == "openrouter" and os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    return "mock"

def generate(question, context, sources, status):
    provider = configured_provider()
    if provider == "mock" or status == "UNKNOWN":
        return None
    if provider == "openai":
        endpoint = "https://api.openai.com/v1/chat/completions"
        key = os.environ["OPENAI_API_KEY"]
        model = os.getenv("LLM_MODEL") or "gpt-4.1-mini"
    else:
        endpoint = "https://openrouter.ai/api/v1/chat/completions"
        key = os.environ["OPENROUTER_API_KEY"]
        model = os.getenv("LLM_MODEL") or "openrouter/free"
    facts = [{"url":x["url"],"title":x["title"],"content":x["snippet"][:1000]} for x in sources[:3]]
    payload = {"model":model,"temperature":0.2,"max_tokens":180,"messages":[
        {"role":"system","content":PROMPT},
        {"role":"user","content":json.dumps({"question":question,"session_context":context,"source_status":status,"untrusted_official_source_data":facts},ensure_ascii=False)}]}
    try:
        r=httpx.post(endpoint,json=payload,headers={"Authorization":"Bearer "+key},timeout=8)
        r.raise_for_status()
        data=r.json()
        message=data["choices"][0]["message"]["content"].strip()
        usage=data.get("usage",{})
        tokens_in=usage.get("prompt_tokens",0)
        tokens_out=usage.get("completion_tokens",0)
        estimated=(tokens_in*float(os.getenv("LLM_INPUT_USD_PER_M","0"))+tokens_out*float(os.getenv("LLM_OUTPUT_USD_PER_M","0")))/1_000_000
        db=connect()
        db.execute("INSERT INTO llm_usage(provider,model,tokens_input,tokens_output,estimated_cost,created_at) VALUES(?,?,?,?,?,?)",(provider,model,tokens_in,tokens_out,estimated,now()))
        db.commit();db.close()
        return message if 0 < len(message) < 1200 else None
    except Exception:
        return None
