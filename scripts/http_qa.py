import json
import os
import uuid
import httpx

ROOT=os.getenv("MECKY_TEST_URL","http://127.0.0.1:8765")
QUESTIONS=[
"Habt ihr am 20.09.2026 offen?","Bis wann hat die Küche am 19.09.2026 geöffnet?","Kann ich Sonntag mit 8 Leuten kommen?",
"Wo kann ich reservieren?","Kann ich für 20 Personen online buchen?","Zeig mir die Speisekarte.","Wo ist die Getränkekarte?",
"Wo kann ich parken?","Darf ich direkt hochfahren?","Wie komme ich mit der S-Bahn?","Kann mein Vater mit dem Shuttle hoch?",
"Sind Hunde willkommen?","Kann ich mit Kreditkarte zahlen?","Ist der Garten bei Regen offen?","Kann ich Kindergeburtstag feiern?",
"Gibt es Sonntag Ponyreiten um 10?","Wir wollen heiraten.","Wie teuer ist eine Hochzeit?","Was ist morgen für ein Event?",
"Gibt es eine geheime Weinprobe für 5 Euro?"]
CONVERSATIONS=[
 ["Wir wollen am 20.09.2026 kommen.","Wir sind 8.","Kann ich reservieren?"],
 ["Wir sind 20 Leute.","Und Sonntag?","Kann ich reservieren?"],
 ["Kann ich draußen sitzen?","Auch mit Hund?"],
 ["Habt ihr am 20.09.2026 offen?","Und am 21.09.2026?"],
 ["Wir wollen heiraten.","Was kostet das?"]]

with httpx.Client(timeout=10) as client:
    for page in ("/","/admin","/assets/style.css","/assets/chat.js","/assets/admin.js"):
        r=client.get(ROOT+page);r.raise_for_status()
    print("health",client.get(ROOT+"/health").json())
    for i,q in enumerate(QUESTIONS):
        r=client.post(ROOT+"/chat",json={"session_id":f"http-qa-{i}","message":q});r.raise_for_status();x=r.json()
        print(json.dumps({"question":q,"intent":x["intent"],"status":x["status"],"answer":x["message"],"links":[y["url"] for y in x["links"]]},ensure_ascii=False))
    for i,turns in enumerate(CONVERSATIONS):
        last=None
        for turn in turns:
            r=client.post(ROOT+"/chat",json={"session_id":f"http-multi-{i}","message":turn});r.raise_for_status();last=r.json()
        print("multi",i,last["message"])
    secret=os.getenv("MECKY_TEST_ADMIN_SECRET")
    if secret:
        day="2026-09-20"
        headers={"x-admin-secret":secret}
        r=client.post(ROOT+"/admin/knowledge",headers=headers,json={"category":"opening_hours","subject":day,"value":"Für den Test schließen wir um 17 Uhr.","valid_from":day,"valid_until":day});r.raise_for_status()
        kid=r.json()["id"]
        try:
            x=client.post(ROOT+"/chat",json={"message":"Habt ihr am 20.09.2026 geöffnet?"}).json()
            assert "17 Uhr" in x["message"]
            print("admin override",x["message"])
        finally:
            client.delete(ROOT+"/admin/knowledge/"+kid,headers=headers).raise_for_status()
        x=client.post(ROOT+"/chat",json={"message":"Habt ihr am 20.09.2026 geöffnet?"}).json()
        assert "11 bis 23" in x["message"]
        print("override deactivated",x["message"])
