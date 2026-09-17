"""OpenAI Responses API transport for the model-led agent and its validator."""
import json
import math
import os

import httpx

from .config import load_config
from .validator import schema as validator_schema


ANSWER_SCHEMA={
    "type":"object","additionalProperties":False,
    "properties":{
        "message":{"type":"string","minLength":1,"maxLength":1000},
        "response_type":{"type":"string","enum":["factual","smalltalk","clarification","casual","abuse","fallback"]},
        "contact_needed":{"type":"boolean"}
    },
    "required":["message","response_type","contact_needed"]
}


def configured_provider():
    return "openai" if os.getenv("LLM_PROVIDER",load_config().llm.provider).lower()=="openai" and os.getenv("OPENAI_API_KEY") else "mock"


def nonnegative_number(value):
    if isinstance(value,bool) or value is None or value=="":return None
    try:
        number=float(value);return number if math.isfinite(number) and number>=0 else None
    except (TypeError,ValueError):return None


def model_configuration():
    cfg=load_config();provider=configured_provider();model=cfg.llm.model if provider=="openai" else None
    return {"provider":provider,"model":model,"validator_model":cfg.validator.llm_judge_model if provider=="openai" else None,
            "scope":"agent_and_evidence_validator","currency":"USD","api":"responses" if provider=="openai" else None,
            "input_usd_per_m":nonnegative_number(os.getenv("LLM_INPUT_USD_PER_M") or ("0.25" if model=="gpt-5-mini" else "")),
            "output_usd_per_m":nonnegative_number(os.getenv("LLM_OUTPUT_USD_PER_M") or ("2" if model=="gpt-5-mini" else ""))}


def no_model_usage():
    return {"provider":"rules","model":None,"model_called":False,"model_calls":0,"tokens_input":0,"tokens_output":0,
            "tokens_total":0,"tokens_complete":True,"cost_usd":0.0,"currency":"USD","cost_status":"not_used"}


def measured_usage(data,model):
    raw=data.get("usage") or {};tin=raw.get("input_tokens");tout=raw.get("output_tokens")
    complete=type(tin) is int and type(tout) is int
    config=model_configuration();ip=config["input_usd_per_m"];op=config["output_usd_per_m"]
    cost=(tin*ip+tout*op)/1_000_000 if complete and ip is not None and op is not None else None
    return {"provider":"openai","model":data.get("model") or model,"model_called":True,"model_calls":1,
            "tokens_input":tin,"tokens_output":tout,"tokens_total":tin+tout if complete else None,
            "tokens_complete":complete,"cost_usd":cost,"currency":"USD","cost_status":"estimated" if cost is not None else "unavailable"}


def _text(data):
    if isinstance(data.get("output_text"),str):return data["output_text"]
    for item in data.get("output",[]):
        if item.get("type")=="message":
            for content in item.get("content",[]):
                if content.get("type") in ("output_text","text") and content.get("text"):return content["text"]
    return None


def _post(request:dict,model:str)->dict:
    usage={**no_model_usage(),"provider":"openai","model":model,"model_called":True,"model_calls":1,
           "tokens_input":None,"tokens_output":None,"tokens_total":None,"tokens_complete":False,"cost_usd":None,"cost_status":"unavailable"}
    if configured_provider()!="openai":return {"data":None,"usage":no_model_usage(),"error":"MODEL_NOT_CONFIGURED"}
    try:
        response=httpx.post("https://api.openai.com/v1/responses",json=request,
                            headers={"Authorization":"Bearer "+os.environ["OPENAI_API_KEY"],"Content-Type":"application/json"},
                            timeout=load_config().llm.timeout_seconds)
        response.raise_for_status();data=response.json()
        return {"data":data,"usage":measured_usage(data,model),"error":None}
    except (httpx.HTTPError,ValueError,KeyError,TypeError) as exc:
        return {"data":None,"usage":usage,"error":type(exc).__name__}


def agent_request(input_items:list,system_prompt:str,tools:list,feedback:str|None=None)->dict:
    cfg=load_config();instructions=system_prompt+("\n\nKORREKTURHINWEIS DES FAKTENPRÜFERS:\n"+feedback if feedback else "")
    request={"model":cfg.llm.model,"instructions":instructions,"input":input_items,"tools":tools[:cfg.tools.max_tools_per_request],
             "parallel_tool_calls":cfg.tools.parallel_tool_calls,
             "max_output_tokens":cfg.llm.max_tokens,"store":False,"reasoning":{"effort":"minimal"},
             "text":{"format":{"type":"json_schema","name":"mecky_answer","strict":True,"schema":ANSWER_SCHEMA}}}
    result=_post(request,cfg.llm.model);data=result["data"] or {};calls=[]
    for item in data.get("output",[]):
        if item.get("type")=="function_call":
            try:arguments=json.loads(item.get("arguments") or "{}")
            except json.JSONDecodeError:arguments={"__invalid_json__":True}
            calls.append({"call_id":item.get("call_id"),"name":item.get("name"),"arguments":arguments,"raw":item})
    payload=None;text=_text(data)
    if text:
        try:payload=json.loads(text)
        except json.JSONDecodeError:payload=None
    return {"payload":payload,"tool_calls":calls,"output_items":data.get("output",[]),"usage":result["usage"],"error":result["error"]}


def validator_request(answer:str,evidence:dict,validator_prompt:str)->dict:
    cfg=load_config();model=cfg.validator.llm_judge_model
    request={"model":model,"instructions":"Prüfe nur Faktenbindung. Antworte ausschließlich im JSON-Schema.",
             "input":[{"role":"user","content":[{"type":"input_text","text":validator_prompt}]}],
             "max_output_tokens":250,"store":False,"reasoning":{"effort":"minimal"},
             "text":{"format":{"type":"json_schema","name":"mecky_verdict","strict":True,"schema":validator_schema()}}}
    result=_post(request,model);text=_text(result["data"] or {});payload=None
    if text:
        try:payload=json.loads(text)
        except json.JSONDecodeError:payload=None
    return {"payload":payload,"usage":result["usage"],"error":result["error"]}


def transcribe_audio(content:bytes,filename:str,media_type:str)->dict:
    """Transcribe a short guest recording without exposing the API key to the browser."""
    model=os.getenv("VOICE_TRANSCRIPTION_MODEL","gpt-4o-mini-transcribe")
    if configured_provider()!="openai":return {"text":None,"usage":None,"error":"MODEL_NOT_CONFIGURED"}
    try:
        response=httpx.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization":"Bearer "+os.environ["OPENAI_API_KEY"]},
            files={"file":(filename,content,media_type)},
            data={"model":model,"language":"de","response_format":"json",
                  "prompt":"Heuchelberger Warte, Mecky, Gastronomie, Reservierung, Speisekarte"},
            timeout=45,
        )
        response.raise_for_status();data=response.json();raw=data.get("usage") or {}
        tin=raw.get("input_tokens");tout=raw.get("output_tokens")
        complete=type(tin) is int and type(tout) is int
        cost=(tin*1.25+tout*5.0)/1_000_000 if complete else None
        return {"text":data.get("text"),"model":data.get("model") or model,
                "usage":{"tokens_input":tin,"tokens_output":tout,"tokens_total":tin+tout if complete else None,
                         "tokens_complete":complete,"cost_usd":cost,"currency":"USD",
                         "cost_status":"estimated" if cost is not None else "unavailable"},"error":None}
    except (httpx.HTTPError,ValueError,KeyError,TypeError) as exc:
        return {"text":None,"model":model,"usage":None,"error":type(exc).__name__}
