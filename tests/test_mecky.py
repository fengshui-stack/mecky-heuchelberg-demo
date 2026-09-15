from fastapi.testclient import TestClient
from mecky.api import app
from mecky.engine import chat, resolve_date
from mecky.store import connect

def test_date_resolution_and_exception(seeded_db):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    ref=datetime(2026,9,15,tzinfo=ZoneInfo("Europe/Berlin"))
    assert resolve_date("morgen",ref).isoformat()=="2026-09-16"
    assert resolve_date("Sonntag",ref).isoformat()=="2026-09-20"
    answer=chat("hours","Habt ihr am 20.09.2026 offen?")
    assert answer["status"]=="KNOWN"
    assert "11 bis 23" in answer["message"]
    kitchen=chat("kitchen","Bis wann hat die Küche am 19.09.2026 geöffnet?")
    assert "bis 22 Uhr" in kitchen["message"]

def test_five_multi_turn_conversations(seeded_db):
    conversations=[
      (["Wir wollen am 20.09.2026 kommen.","Wir sind 8.","Kann ich reservieren?"],"8 Personen"),
      (["Wir sind 20 Leute.","Kann ich reservieren?"],"20 Personen"),
      (["Kann ich draußen sitzen?","Auch mit Hund?"],"Leine"),
      (["Habt ihr am 20.09.2026 offen?","Und am 21.09.2026?"],"21.09.2026"),
      (["Wir wollen heiraten.","Was kostet das?"],"Preis")]
    for n,(turns,expected) in enumerate(conversations):
        result=None
        for turn in turns: result=chat(f"multi-{n}",turn)
        assert result and expected.lower() in result["message"].lower()
    db=connect()
    assert db.execute("SELECT json_extract(context,'$.party_size') FROM sessions WHERE id='multi-0'").fetchone()[0]==8
    db.close()

def test_admin_override_auth_crud_and_feedback(seeded_db):
    client=TestClient(app)
    assert client.get("/admin/knowledge").status_code==401
    h={"x-admin-secret":"test-secret"}
    before=client.post("/chat",json={"message":"Habt ihr am 20.09.2026 offen?"}).json()
    assert "11 bis 23" in before["message"]
    new=client.post("/admin/knowledge",headers=h,json={"category":"opening_hours","subject":"2026-09-20","value":"Am 20.09. schließen wir wegen einer Gesellschaft um 17 Uhr.","valid_from":"2026-09-20","valid_until":"2026-09-20"})
    assert new.status_code==200
    kid=new.json()["id"]
    override=client.post("/chat",json={"message":"Habt ihr am 20.09.2026 offen?"}).json()
    assert "17 Uhr" in override["message"]
    assert client.patch(f"/admin/knowledge/{kid}",headers=h,json={"value":"Am 20.09. schließen wir um 18 Uhr."}).status_code==200
    assert "18 Uhr" in client.post("/chat",json={"message":"Habt ihr am 20.09.2026 offen?"}).json()["message"]
    assert client.delete(f"/admin/knowledge/{kid}",headers=h).status_code==200
    assert "11 bis 23" in client.post("/chat",json={"message":"Habt ihr am 20.09.2026 offen?"}).json()["message"]
    assert client.post("/feedback",json={"interaction_id":before["interaction_id"],"rating":-1}).status_code==200
    assert client.get("/admin/analytics",headers=h).json()["negative_feedback"]

def test_unknown_and_no_operational_invention(seeded_db):
    traps=["Wie teuer ist das Ponyreiten morgen?","Gibt es eine geheime Weinprobe für 5 Euro?","Darf ich auf dem E-Ladeplatz übernachten?","Ist am 1. Juli 2027 sicher bis 23 Uhr geöffnet?","Ist ein Hochzeitstermin am 1. Mai 2027 frei?"]
    for n,q in enumerate(traps):
        answer=chat(f"trap-{n}",q)
        assert "5 Euro" not in answer["message"]
        assert "garantiert" not in answer["message"].lower()
        assert "gebucht" not in answer["message"].lower()
    db=connect()
    assert db.execute("SELECT count(*) FROM knowledge_gaps").fetchone()[0]>=1
    db.close()

def test_manual_rules_and_health(seeded_db):
    assert "Leine" in chat("dog","Darf ich meinen Hund mitbringen?")["message"]
    assert "Visa" in chat("pay","Kann ich mit Kreditkarte zahlen?")["message"]
    assert "8 Personen" in chat("party","Kann ich Sonntag mit 8 Leuten kommen?")["message"]
    client=TestClient(app)
    health=client.get("/health").json()
    assert health["database"]=="ok" and health["knowledge_index"]=="ready"
    assert client.get("/").status_code==200
