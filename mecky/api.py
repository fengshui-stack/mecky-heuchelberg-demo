import hmac
import json
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
    return {"api":"ok","database":"ok","knowledge_index":"ready" if chunks else "empty","documents":docs,"provider":configured_provider()}

@app.post("/chat")
def chat_route(body:ChatInput):
    if not body.message.strip():
        raise HTTPException(422,"Message must not be blank")
    sid=body.session_id or secrets.token_urlsafe(18)
    if not sid.replace("-","").replace("_","").isalnum():
        raise HTTPException(422,"Invalid session ID")
    return chat(sid,body.message.strip())

@app.get("/model")
def model_info():
    from .provider import model_configuration
    return model_configuration()

@app.post("/feedback")
def feedback(body:FeedbackInput):
    db=connect()
    if not db.execute("SELECT 1 FROM interactions WHERE id=?",(body.interaction_id,)).fetchone():
        db.close();raise HTTPException(404,"Interaction not found")
    db.execute("INSERT INTO feedback(interaction_id,rating,comment,created_at) VALUES(?,?,?,?)",(body.interaction_id,body.rating,body.comment,now()))
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
    response_types=[dict(x) for x in db.execute("SELECT json_extract(detail,'$.type') response_type,count(*) count FROM decision_events WHERE stage='response' GROUP BY response_type ORDER BY count DESC")]
    retrieval=db.execute("SELECT count(*) requests,sum(CASE WHEN json_extract(detail,'$.gate')=1 THEN 1 ELSE 0 END) indexed_searches,sum(coalesce(json_extract(detail,'$.indexed_hits'),0)) indexed_hits FROM decision_events WHERE stage='retrieval'").fetchone()
    total=db.execute("SELECT count(*) FROM interactions").fetchone()[0]
    db.close()
    return {"total":total,"intents":intents,"negative_feedback":negative,"model_usage":model_usage,
            "response_types":response_types,"retrieval":{"requests":retrieval[0],"indexed_searches":retrieval[1],"indexed_hits":retrieval[2]}}

@app.get("/admin/traces")
def traces(limit:int=20,x_admin_secret:str|None=Header(default=None)):
    require_admin(x_admin_secret)
    if not 1<=limit<=100: raise HTTPException(422,"limit must be 1 to 100")
    db=connect()
    rows=[{"interaction_id":x["interaction_id"],"stage":x["stage"],"detail":json.loads(x["detail"]),"created_at":x["created_at"]}
          for x in db.execute("SELECT interaction_id,stage,detail,created_at FROM decision_events ORDER BY id DESC LIMIT ?",(limit,))]
    db.close()
    return {"items":rows}

@app.get("/")
def index(): return FileResponse(Path("frontend/index.html"))

@app.get("/admin")
def admin_page(): return FileResponse(Path("frontend/admin.html"))

@app.get("/assets/{filename}")
def asset(filename:str):
    if filename not in ("style.css","chat.js","admin.js"):
        raise HTTPException(404)
    return FileResponse(Path("frontend")/filename)
