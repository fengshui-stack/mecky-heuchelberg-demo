"""Model-led Mecky agent: model chooses tools, tools provide facts, validator checks facts."""
import json
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .config import load_config
from .provider import agent_request,configured_provider,no_model_usage,validator_request
from .store import connect,now,stable_id
from .tools import TOOL_MODELS,ToolOutput,execute,tool_definitions
from .usage import record_usage,session_usage
from .validator import parse as parse_verdict,prompt as validator_prompt

TZ=ZoneInfo("Europe/Berlin")


def _persona_prompt()->str:
    persona=json.loads(Path(__file__).with_name("persona.yaml").read_text(encoding="utf-8"))
    today=datetime.now(TZ).date().isoformat()
    return persona["system_prompt"]+f"\n\nHEUTIGES DATUM IN EUROPE/BERLIN: {today}. Relative Datumsangaben für Toolargumente rechnest du in ISO-Daten um."


def _sum_usage(rows:list[dict])->dict:
    if not rows:return no_model_usage()
    calls=sum(row.get("model_calls",1 if row.get("model_called") else 0) for row in rows)
    unknown_tokens=any(not row.get("tokens_complete") for row in rows)
    costs=[row.get("cost_usd") for row in rows]
    return {"provider":"openai","model":rows[-1].get("model"),"model_called":calls>0,"model_calls":calls,
            "tokens_input":sum(row.get("tokens_input") or 0 for row in rows),
            "tokens_output":sum(row.get("tokens_output") or 0 for row in rows),
            "tokens_total":None if unknown_tokens else sum(row.get("tokens_total") or 0 for row in rows),
            "tokens_complete":not unknown_tokens,"cost_usd":sum(costs) if all(x is not None for x in costs) else None,
            "currency":"USD","cost_status":"estimated" if all(x is not None for x in costs) else "incomplete"}


def _history(db,sid:str,limit=10)->list[dict]:
    rows=db.execute("SELECT role,content FROM conversation_messages WHERE session_id=? ORDER BY id DESC LIMIT ?",(sid,limit)).fetchall()
    return [{"role":row["role"],"content":row["content"]} for row in rows][::-1]


def _state(db,sid:str)->dict:
    row=db.execute("SELECT context FROM sessions WHERE id=?",(sid,)).fetchone()
    if not row:return {"turn_count":0,"recent_response_hashes":[]}
    try:return json.loads(row["context"])
    except (json.JSONDecodeError,TypeError):return {"turn_count":0,"recent_response_hashes":[]}


def _save(db,sid,state,user_message,assistant_message):
    db.execute("INSERT OR REPLACE INTO sessions VALUES(?,?,?)",(sid,json.dumps(state,ensure_ascii=False),now()))
    for role,content in (("user",user_message),("assistant",assistant_message)):
        db.execute("INSERT INTO conversation_messages(session_id,role,content,created_at) VALUES(?,?,?,?)",(sid,role,content,now()))


def _tool_payload(output:ToolOutput)->dict:
    return {"tool":output.name,"status":output.status,"data":output.data,"sources":output.sources,"error":output.error}


def _merge_evidence(cache:dict,output:ToolOutput):
    value=_tool_payload(output);existing=cache.get(output.name)
    if existing is None:cache[output.name]=value
    elif isinstance(existing,list):existing.append(value)
    else:cache[output.name]=[existing,value]


def _safe_tool_call(db,call:dict)->ToolOutput:
    name=call.get("name")
    if name not in TOOL_MODELS:return ToolOutput(name or "unknown",{},"PARTIAL",error="UNKNOWN_TOOL")
    try:return execute(db,name,call.get("arguments") or {})
    except (ValidationError,ValueError,TypeError,KeyError) as exc:
        return ToolOutput(name,{},"PARTIAL",error="INVALID_ARGUMENTS_"+type(exc).__name__)


def _fallback(tool_names:list[str])->str:
    names=set(tool_names)
    if names & {"get_menu","get_drinks","get_vegetarian_options","get_allergen_info"}:
        return "Die passende Karte kann ich gerade nicht sicher auslesen. Soll ich sie dir direkt verlinken?"
    if "get_opening_hours" in names:
        return "Die Öffnungszeit für deinen Tag habe ich gerade nicht sicher. Welchen Tag meinst du genau?"
    if names & {"get_reservation_policy","get_group_policy"}:
        return "Die Buchung kann ich gerade nicht sicher prüfen. Soll ich dir die Reservierung öffnen?"
    if names:
        return "Das hab ich gerade nicht sicher in meinen Infos. Soll ich dir zeigen, wo du das direkt nachfragen kannst?"
    return "Das weiß ich leider nicht. Bei Fragen zur Warte helf ich dir aber gern."


def _dedupe(items:list[dict])->list[dict]:
    result=[];seen=set()
    for item in items:
        key=item.get("url") or json.dumps(item,sort_keys=True,ensure_ascii=False)
        if key not in seen:seen.add(key);result.append(item)
    return result


def chat(sid,message,*,user_id=None,memory_consent=False,client_context=None):
    del user_id,memory_consent,client_context
    started=time.monotonic();db=connect();state=_state(db,sid);history=_history(db,sid,10)
    base_input=[{"role":turn["role"],"content":turn["content"]} for turn in history]
    base_input.append({"role":"user","content":message})
    evidence={};outputs=[];actions=[];sources=[];usage_rows=[];tool_names=[];tool_errors=[]
    payload=None;validator_result="fallback";retry_count=0;feedback=None;validator_attempts=[]
    model_ready=configured_provider()=="openai";working_input=list(base_input)
    cfg=load_config()

    if model_ready:
        for generation_index in range(cfg.validator.max_retries+1):
            retry_count=generation_index
            for _round in range(cfg.tools.max_tool_rounds):
                result=agent_request(working_input,_persona_prompt(),tool_definitions(),feedback)
                usage_rows.append(result["usage"])
                if result["error"]:tool_errors.append(result["error"])
                if result["tool_calls"]:
                    working_input.extend(result["output_items"])
                    for call in result["tool_calls"]:
                        output=_safe_tool_call(db,call);outputs.append(output);tool_names.append(output.name)
                        _merge_evidence(evidence,output);actions.extend(output.actions);sources.extend(output.sources)
                        working_input.append({"type":"function_call_output","call_id":call.get("call_id"),
                                              "output":json.dumps(_tool_payload(output),ensure_ascii=False)})
                    continue
                payload=result["payload"]
                break
            if not payload:
                feedback="Deine Antwort war leer oder nicht schema-konform. Formuliere eine kurze Antwort im geforderten Schema."
                working_input=list(base_input)
                continue
            judged=validator_request(payload["message"],evidence,validator_prompt(payload["message"],evidence))
            usage_rows.append(judged["usage"]);verdict=parse_verdict(judged["payload"])
            validator_attempts.append({"attempt":generation_index+1,"verdict":verdict.verdict if verdict else "uncertain",
                                       "claims":verdict.ungrounded_claims if verdict else [],"error":judged["error"]})
            if verdict is None and cfg.validator.pass_on_uncertainty:
                validator_result="retry_pass" if generation_index else "pass";break
            if verdict and verdict.verdict=="pass":
                validator_result="retry_pass" if generation_index else "pass";break
            claims=verdict.ungrounded_claims if verdict else []
            feedback="Deine vorherige Antwort enthielt nicht gedeckte Fakten: "+("; ".join(claims) if claims else "Faktenprüfung fehlgeschlagen")+". Formuliere neu ohne diese Aussagen oder rufe zuerst das passende Tool auf."
            payload=None
        else:payload=None

    fallback_used=payload is None
    if fallback_used:
        answer=_fallback(tool_names);response_type="fallback";contact_needed=False;validator_result="fallback"
    else:
        answer=payload["message"].strip();response_type=payload["response_type"];contact_needed=payload["contact_needed"]
    actions=_dedupe(actions);sources=_dedupe(sources)
    if not contact_needed:actions=[action for action in actions if action.get("type")!="CONTACT"]
    links=[{"url":action["url"],"title":action.get("label",action.get("type","Mehr erfahren"))} for action in actions if action.get("url")]
    show_feedback=response_type=="factual" and bool(evidence)
    statuses=[output.status for output in outputs]
    status="KNOWN" if statuses and all(x=="KNOWN" for x in statuses) else "PARTIAL" if statuses else "UNKNOWN" if fallback_used else "KNOWN"
    usage=_sum_usage(usage_rows)
    state={"turn_count":state.get("turn_count",0)+1,
           "recent_response_hashes":(state.get("recent_response_hashes",[])+[stable_id(answer)])[-5:]}
    _save(db,sid,state,message,answer)
    latency=int((time.monotonic()-started)*1000)
    cur=db.execute("INSERT INTO interactions(session_id,intent,confidence,sources,answer,latency_ms,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
                   (sid,tool_names[0] if tool_names else response_type.upper(),.98 if status=="KNOWN" else .65 if status=="PARTIAL" else 0,
                    json.dumps([x.get("url") for x in sources if x.get("url")]),answer,latency,status,now()))
    iid=cur.lastrowid
    traces={
        "agent":{"llm_called":usage["model_called"],"llm_model":usage["model"],"tokens_in":usage["tokens_input"],"tokens_out":usage["tokens_output"],"tool_rounds":len(outputs)},
        "tools":{"tools_called":tool_names,"errors":tool_errors,"evidence_keys":list(evidence)},
        "validator":{"validator_result":validator_result,"retry_count":retry_count,"attempts":validator_attempts},
        "rendering":{"response_type":response_type,"show_feedback":show_feedback,"contact":contact_needed,"latency_ms":latency},
    }
    for stage,detail in traces.items():db.execute("INSERT INTO decision_events(interaction_id,session_id,stage,detail,created_at) VALUES(?,?,?,?,?)",(iid,sid,stage,json.dumps(detail,ensure_ascii=False),now()))
    record_usage(db,sid,iid,usage);totals=session_usage(db,sid);db.commit();db.close()
    return {"session_id":sid,"message":answer,"links":links,"confidence":.98 if status=="KNOWN" else .65 if status=="PARTIAL" else 0,
            "intent":tool_names[0] if tool_names else response_type.upper(),"intents":tool_names,"status":status,"response_type":response_type,
            "actions":actions,"show_feedback":show_feedback,"sources":sources if response_type=="factual" else [],
            "handoff":any(output.handoff for output in outputs),"contact":next((x for x in actions if x.get("type")=="CONTACT"),None),
            "interaction_id":iid,"usage":usage,"session_usage":totals,"latency_ms":latency,
            "validator_result":validator_result,"retry_count":retry_count,"fallback_used":fallback_used}
