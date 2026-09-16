import json

from fastapi.testclient import TestClient

from mecky.api import app
from mecky.store import connect, now


def test_health_model_and_blank_input(seeded_db):
    client=TestClient(app)
    health=client.get("/health").json()
    assert health["api"]=="ok" and health["architecture"]=="model-led-tools-validator"
    assert client.get("/model").json()["provider"]=="mock"
    assert client.post("/chat",json={"message":"   "}).status_code==422


def test_admin_auth_crud_feedback_and_new_analytics(seeded_db):
    client=TestClient(app);headers={"x-admin-secret":"test-secret"}
    assert client.get("/admin/knowledge").status_code==401
    created=client.post("/admin/knowledge",headers=headers,json={"category":"opening_hours","subject":"2026-12-24","value":"geschlossen"})
    assert created.status_code==200
    kid=created.json()["id"]
    assert client.patch(f"/admin/knowledge/{kid}",headers=headers,json={"value":"bis 16 Uhr"}).status_code==200
    assert client.delete(f"/admin/knowledge/{kid}",headers=headers).status_code==200
    db=connect()
    cur=db.execute("INSERT INTO interactions(session_id,intent,confidence,sources,answer,latency_ms,status,created_at) VALUES(?,?,?,?,?,?,?,?)",("admin-test","smalltalk",1,"[]","Hi",10,"KNOWN",now()))
    iid=cur.lastrowid
    for stage,detail in {
        "agent":{"llm_called":True,"tool_rounds":1},"tools":{"tools_called":["get_dog_policy"]},
        "validator":{"validator_result":"pass"},"rendering":{"response_type":"factual"}
    }.items():db.execute("INSERT INTO decision_events(interaction_id,session_id,stage,detail,created_at) VALUES(?,?,?,?,?)",(iid,"admin-test",stage,json.dumps(detail),now()))
    db.commit();db.close()
    analytics=client.get("/admin/analytics",headers=headers).json()
    assert analytics["generation"]["llm_turns"]==1
    assert analytics["validator_failures"]==[{"result":"pass","count":1}]
    assert analytics["tool_use"]==[{"tool":"get_dog_policy","count":1}]
    assert client.post("/feedback",json={"interaction_id":iid,"rating":1}).status_code==200
