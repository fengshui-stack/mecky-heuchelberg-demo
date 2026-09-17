import hmac
import json
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

load_dotenv()

from .engine import chat
from .store import connect, now, stable_id

app=FastAPI(title="Mecky Demo",version="0.2.0")
origins=[x.strip() for x in os.getenv("MECKY_ALLOWED_ORIGINS","https://mecky-kundentest.ben-fenger.chatgpt.site").split(",") if x.strip()]
if origins:
    app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=["GET","POST","PATCH","DELETE"],allow_headers=["content-type","x-admin-secret"])

class ChatInput(BaseModel):
    session_id: str | None = Field(default=None,max_length=100)
    message: str = Field(min_length=1,max_length=2000)
    user_id: str | None = Field(default=None,max_length=100)
    memory_consent: bool = False
    client_context: dict | None = None

class KnowledgeInput(BaseModel):
    category: str = Field(min_length=2,max_length=80)
    subject: str = Field(min_length=2,max_length=120)
    value: str = Field(min_length=2,max_length=2000)
    valid_from: str | None = None
    valid_until: str | None = None

class KnowledgePatch(BaseModel):
    category: str | None = None
    subject: str | None = None
    value: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    active: bool | None = None

class FeedbackInput(BaseModel):
    interaction_id: int
    rating: int = Field(ge=-1,le=1)
    comment: str | None = Field(default=None,max_length=500)

def require_admin(secret):
    expected=os.getenv("ADMIN_SECRET","")
    if not expected:
        path=Path(os.getenv("ADMIN_SECRET_FILE","/etc/secrets/mecky_admin_secret"))
        if path.is_file():
            expected=path.read_text(encoding="utf-8").strip()
    if not expected:
        raise HTTPException(503,"Admin secret is not configured")
    if not secret or not hmac.compare_digest(secret,expected):
        raise HTTPException(401,"Unauthorized")

@app.get("/health")
def health():
    from .provider import configured_provider
    db=connect()
    docs=db.execute("SELECT count(*) FROM documents").fetchone()[0]
    chunks=db.execute("SELECT count(*) FROM document_chunks").fetchone()[0]
    db.close()
    from .provider import model_configuration
    return {"api":"ok","database":"ok","knowledge_index":"ready" if chunks else "empty","documents":docs,
            "provider":configured_provider(),"model":model_configuration()["model"],"architecture":"model-led-tools-validator"}

@app.post("/chat")
def chat_route(body:ChatInput):
    if not body.message.strip():
        raise HTTPException(422,"Message must not be blank")
    sid=body.session_id or secrets.token_urlsafe(18)
    if not sid.replace("-","").replace("_","").isalnum():
        raise HTTPException(422,"Invalid session ID")
    return chat(sid,body.message.strip(),user_id=body.user_id,memory_consent=body.memory_consent,client_context=body.client_context)

@app.post("/chat/stream")
def chat_stream(body:ChatInput):
    if not body.message.strip(): raise HTTPException(422,"Message must not be blank")
    sid=body.session_id or secrets.token_urlsafe(18)
    if not sid.replace("-","").replace("_","").isalnum(): raise HTTPException(422,"Invalid session ID")
    from .streaming import events
    result=chat(sid,body.message.strip(),user_id=body.user_id,memory_consent=body.memory_consent,client_context=body.client_context)
    return StreamingResponse(events(result),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.get("/model")
def model_info():
    from .provider import model_configuration
    return model_configuration()

@app.post("/transcribe")
async def transcribe_route(request:Request):
    media_type=request.headers.get("content-type","").split(";",1)[0].lower()
    extensions={"audio/webm":"webm","audio/ogg":"ogg","audio/mp4":"m4a","audio/mpeg":"mp3","audio/wav":"wav","audio/x-wav":"wav"}
    if media_type not in extensions: raise HTTPException(415,"Unsupported audio format")
    declared=request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared)>8_000_000: raise HTTPException(413,"Audio file is too large")
    audio=await request.body()
    if not 100<=len(audio)<=8_000_000: raise HTTPException(422,"Audio recording is empty or too large")
    from .provider import transcribe_audio
    result=transcribe_audio(audio,"mecky-voice."+extensions[media_type],media_type)
    if result.get("error"): raise HTTPException(502,"Transcription is temporarily unavailable")
    transcript=(result.get("text") or "").strip()
    if not transcript: raise HTTPException(422,"No speech was recognized")
    return {"text":transcript[:2000],"model":result.get("model"),"usage":result.get("usage")}

@app.post("/feedback")
def feedback(body:FeedbackInput):
    db=connect()
    if not db.execute("SELECT 1 FROM interactions WHERE id=?",(body.interaction_id,)).fetchone():
        db.close();raise HTTPException(404,"Interaction not found")
    db.execute("INSERT INTO feedback(interaction_id,rating,comment,created_at) VALUES(?,?,?,?)",(body.interaction_id,body.rating,body.comment,now()))
    row=db.execute("SELECT session_id FROM interactions WHERE id=?",(body.interaction_id,)).fetchone()
    session_row=db.execute("SELECT context FROM sessions WHERE id=?",(row["session_id"],)).fetchone()
    if session_row:
        state=json.loads(session_row["context"])
        state["feedback_history"]=(state.get("feedback_history",[])+[{"interaction_id":body.interaction_id,"rating":body.rating}])[-10:]
        db.execute("UPDATE sessions SET context=?,updated_at=? WHERE id=?",(json.dumps(state,ensure_ascii=False),now(),row["session_id"]))
    db.commit();db.close()
    return {"ok":True}

@app.get("/admin/knowledge")
def knowledge_list(x_admin_secret:str|None=Header(default=None)):
    require_admin(x_admin_secret)
    db=connect();rows=[dict(x) for x in db.execute("SELECT * FROM admin_knowledge ORDER BY updated_at DESC")];db.close()
    return {"items":rows}

@app.post("/admin/knowledge")
def knowledge_create(body:KnowledgeInput,x_admin_secret:str|None=Header(default=None)):
    require_admin(x_admin_secret)
    if body.valid_from and body.valid_until and body.valid_from>body.valid_until:
        raise HTTPException(422,"valid_from must precede valid_until")
    db=connect();kid=stable_id(body.category,body.subject,now(),secrets.token_hex(8))
    db.execute("INSERT INTO admin_knowledge VALUES(?,?,?,?,?,?,?,?,?)",(kid,body.category,body.subject,body.value,body.valid_from,body.valid_until,1,now(),now()))
    db.commit();db.close()
    return {"id":kid,"active":True}

@app.patch("/admin/knowledge/{kid}")
def knowledge_patch(kid:str,body:KnowledgePatch,x_admin_secret:str|None=Header(default=None)):
    require_admin(x_admin_secret)
    data=body.model_dump(exclude_unset=True)
    if not data: raise HTTPException(422,"No fields")
    if "active" in data: data["active"]=int(data["active"])
    data["updated_at"]=now()
    db=connect()
    if not db.execute("SELECT 1 FROM admin_knowledge WHERE id=?",(kid,)).fetchone():
        db.close();raise HTTPException(404,"Not found")
    db.execute("UPDATE admin_knowledge SET "+",".join(f"{k}=?" for k in data)+" WHERE id=?",(*data.values(),kid))
    db.commit();db.close()
    return {"id":kid,"updated":True}

@app.delete("/admin/knowledge/{kid}")
def knowledge_delete(kid:str,x_admin_secret:str|None=Header(default=None)):
    require_admin(x_admin_secret)
    db=connect();cur=db.execute("UPDATE admin_knowledge SET active=0,updated_at=? WHERE id=?",(now(),kid));db.commit();db.close()
    if not cur.rowcount: raise HTTPException(404,"Not found")
    return {"id":kid,"active":False}

@app.get("/admin/gaps")
def gaps(x_admin_secret:str|None=Header(default=None)):
    require_admin(x_admin_secret)
    db=connect();rows=[dict(x) for x in db.execute("SELECT * FROM knowledge_gaps ORDER BY occurrences DESC LIMIT 50")];db.close()
    return {"items":rows}

@app.get("/admin/analytics")
def analytics(x_admin_secret:str|None=Header(default=None)):
    require_admin(x_admin_secret)
    db=connect()
    intents=[dict(x) for x in db.execute("SELECT intent,count(*) count,avg(confidence) confidence FROM interactions GROUP BY intent ORDER BY count DESC LIMIT 20")]
    negative=[dict(x) for x in db.execute("SELECT f.rating,f.comment,i.intent,i.answer FROM feedback f JOIN interactions i ON i.id=f.interaction_id WHERE f.rating<0 ORDER BY f.id DESC LIMIT 20")]
    model_usage=[dict(x) for x in db.execute("SELECT provider,model,count(*) requests,sum(tokens_input) tokens_input,sum(tokens_output) tokens_output,sum(estimated_cost) estimated_cost FROM llm_usage GROUP BY provider,model")]
    response_types=[dict(x) for x in db.execute("SELECT json_extract(detail,'$.response_type') response_type,count(*) count FROM decision_events WHERE stage='rendering' GROUP BY response_type ORDER BY count DESC")]
    total=db.execute("SELECT count(*) FROM interactions").fetchone()[0]
    generation=dict(db.execute("SELECT count(*) turns,sum(CASE WHEN json_extract(detail,'$.llm_called')=1 THEN 1 ELSE 0 END) llm_turns,sum(coalesce(json_extract(detail,'$.tool_rounds'),0)) tool_rounds FROM decision_events WHERE stage='agent'").fetchone())
    validator=[dict(x) for x in db.execute("SELECT json_extract(detail,'$.validator_result') result,count(*) count FROM decision_events WHERE stage='validator' GROUP BY result ORDER BY count DESC")]
    latency=dict(db.execute("SELECT avg(latency_ms) average_ms,max(latency_ms) max_ms FROM interactions").fetchone())
    tokens_daily=[dict(x) for x in db.execute("SELECT substr(created_at,1,10) day,sum(tokens_input) tokens_input,sum(tokens_output) tokens_output,sum(estimated_cost) estimated_cost FROM llm_usage GROUP BY day ORDER BY day DESC LIMIT 31")]
    tools=[dict(x) for x in db.execute("SELECT value tool,count(*) count FROM decision_events,json_each(decision_events.detail,'$.tools_called') WHERE stage='tools' GROUP BY tool ORDER BY count DESC")]
    db.close()
    return {"total":total,"intents":intents,"negative_feedback":negative,"model_usage":model_usage,
            "response_types":response_types,
            "generation":generation,"validator_failures":validator,"latency":latency,"tokens_per_day":tokens_daily,"tool_use":tools}

@app.get("/admin/traces")
def traces(limit:int=20,x_admin_secret:str|None=Header(default=None)):
    require_admin(x_admin_secret)
    if not 1<=limit<=100: raise HTTPException(422,"limit must be 1 to 100")
    db=connect()
    rows=[{"interaction_id":x["interaction_id"],"stage":x["stage"],"detail":json.loads(x["detail"]),"created_at":x["created_at"]}
          for x in db.execute("SELECT interaction_id,stage,detail,created_at FROM decision_events ORDER BY id DESC LIMIT ?",(limit,))]
    db.close()
    return {"items":rows}

@app.get("/admin/traces/{interaction_id}")
def interaction_trace(interaction_id:int,x_admin_secret:str|None=Header(default=None)):
    require_admin(x_admin_secret)
    db=connect()
    if not db.execute("SELECT 1 FROM interactions WHERE id=?",(interaction_id,)).fetchone():
        db.close();raise HTTPException(404,"Interaction not found")
    stages=[{"stage":x["stage"],"detail":json.loads(x["detail"]),"created_at":x["created_at"]}
            for x in db.execute("SELECT stage,detail,created_at FROM decision_events WHERE interaction_id=? ORDER BY id",(interaction_id,))]
    db.close()
    return {"interaction_id":interaction_id,"stages":stages}

@app.get("/")
def index(): return FileResponse(Path("frontend/index.html"))

@app.get("/admin")
def admin_page(): return FileResponse(Path("frontend/admin.html"))

@app.get("/assets/{filename}")
def asset(filename:str):
    if filename not in ("style.css","chat.js","admin.js"):
        raise HTTPException(404)
    return FileResponse(Path("frontend")/filename)
