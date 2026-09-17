import json

from mecky import engine, store


def usage(tokens_in=100, tokens_out=20):
    return {"provider":"openai","model":"gpt-5-mini","model_called":True,"model_calls":1,
            "tokens_input":tokens_in,"tokens_output":tokens_out,"tokens_total":tokens_in+tokens_out,
            "tokens_complete":True,"cost_usd":(tokens_in*.25+tokens_out*2)/1_000_000,
            "currency":"USD","cost_status":"estimated"}


def tool_result(name, arguments, call_id="call-1"):
    raw={"type":"function_call","call_id":call_id,"name":name,"arguments":json.dumps(arguments)}
    return {"payload":None,"tool_calls":[{"call_id":call_id,"name":name,"arguments":arguments,"raw":raw}],
            "output_items":[raw],"usage":usage(),"error":None}


def answer_result(message, response_type="factual", contact=False):
    return {"payload":{"message":message,"response_type":response_type,"contact_needed":contact},
            "tool_calls":[],"output_items":[],"usage":usage(),"error":None}


def pass_result():
    return {"payload":{"verdict":"pass","reason":"fully grounded","ungrounded_claims":[]},
            "usage":usage(40,8),"error":None}


def test_model_selects_tool_and_validator_checks_evidence(seeded_db, monkeypatch):
    monkeypatch.setattr(engine,"configured_provider",lambda:"openai")
    queue=[tool_result("get_dog_policy",{}),answer_result("Ja, Hunde dürfen mit und bleiben an der Leine.")]
    monkeypatch.setattr(engine,"agent_request",lambda *_args,**_kwargs:queue.pop(0))
    seen={}
    def validate(answer,evidence,prompt):
        seen.update({"answer":answer,"evidence":evidence,"prompt":prompt});return pass_result()
    monkeypatch.setattr(engine,"validator_request",validate)
    result=engine.chat("dog-flow","Darf mein Hund mit?")
    assert result["message"].startswith("Ja")
    assert result["intents"]==["get_dog_policy"]
    assert seen["evidence"]["get_dog_policy"]["data"]=={"allowed":True,"leash_required":True}
    assert result["validator_result"]=="pass" and result["retry_count"]==0
    assert result["usage"]["model_calls"]==3 and result["usage"]["tokens_total"]==288
    db=store.connect()
    assert [x[0] for x in db.execute("SELECT stage FROM decision_events ORDER BY id")]==["agent","tools","validator","rendering"]
    assert "Darf mein Hund" not in json.dumps([dict(x) for x in db.execute("SELECT * FROM decision_events")])
    db.close()


def test_validator_retries_with_claims_and_then_passes(seeded_db,monkeypatch):
    monkeypatch.setattr(engine,"configured_provider",lambda:"openai")
    answers=iter([answer_result("Wir öffnen um 6 Uhr."),answer_result("Welche Uhrzeit möchtest du wissen?","clarification")])
    monkeypatch.setattr(engine,"agent_request",lambda *_args,**_kwargs:next(answers))
    verdicts=iter([
        {"payload":{"verdict":"fail","reason":"unsupported","ungrounded_claims":["6 Uhr"]},"usage":usage(30,7),"error":None},
        pass_result(),
    ])
    monkeypatch.setattr(engine,"validator_request",lambda *_args,**_kwargs:next(verdicts))
    result=engine.chat("retry-flow","Wann öffnet ihr?")
    assert result["message"]=="Welche Uhrzeit möchtest du wissen?"
    assert result["validator_result"]=="retry_pass" and result["retry_count"]==1
    db=store.connect();detail=json.loads(db.execute("SELECT detail FROM decision_events WHERE stage='validator'").fetchone()[0]);db.close()
    assert [x["verdict"] for x in detail["attempts"]]==["fail","pass"]
    assert detail["attempts"][0]["claims"]==["6 Uhr"]


def test_repeated_validator_failure_uses_topic_fallback(seeded_db,monkeypatch):
    monkeypatch.setattr(engine,"configured_provider",lambda:"openai")
    calls=[tool_result("get_opening_hours",{"date":"2026-09-20"}),answer_result("Offen bis 99 Uhr.")]
    calls.extend([answer_result("Offen bis 88 Uhr."),answer_result("Offen bis 77 Uhr.")])
    monkeypatch.setattr(engine,"agent_request",lambda *_args,**_kwargs:calls.pop(0))
    monkeypatch.setattr(engine,"validator_request",lambda *_args,**_kwargs:{"payload":{"verdict":"fail","reason":"unsupported","ungrounded_claims":["Uhrzeit"]},"usage":usage(),"error":None})
    result=engine.chat("fallback-flow","Habt ihr Sonntag offen?")
    assert result["fallback_used"] is True and result["validator_result"]=="fallback"
    assert "Öffnungszeit" in result["message"] and "99" not in result["message"]
    assert result["retry_count"]==2


def test_smalltalk_is_model_led_and_has_no_links(seeded_db,monkeypatch):
    monkeypatch.setattr(engine,"configured_provider",lambda:"openai")
    monkeypatch.setattr(engine,"agent_request",lambda *_args,**_kwargs:answer_result("Mir geht’s gut, danke 😄","smalltalk"))
    monkeypatch.setattr(engine,"validator_request",lambda *_args,**_kwargs:pass_result())
    result=engine.chat("smalltalk","Wie geht’s dir?")
    assert result["message"]=="Mir geht’s gut, danke 😄"
    assert result["actions"]==[] and result["show_feedback"] is False


def test_only_last_ten_original_messages_are_sent(seeded_db,monkeypatch):
    db=store.connect()
    db.execute("INSERT INTO sessions VALUES(?,?,?)",("history",json.dumps({"turn_count":6}),store.now()))
    for number in range(12):
        db.execute("INSERT INTO conversation_messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
                   ("history","user" if number%2==0 else "assistant",f"original-{number}",store.now()))
    db.commit();db.close()
    captured={}
    monkeypatch.setattr(engine,"configured_provider",lambda:"openai")
    def agent(input_items,*_args,**_kwargs):captured["items"]=input_items;return answer_result("Servus!","smalltalk")
    monkeypatch.setattr(engine,"agent_request",agent);monkeypatch.setattr(engine,"validator_request",lambda *_a,**_k:pass_result())
    engine.chat("history","neu")
    assert [x["content"] for x in captured["items"]]==[f"original-{n}" for n in range(2,12)]+["neu"]


def test_exact_repeat_is_regenerated_before_validation(seeded_db,monkeypatch):
    repeated="Servus — was kann ich für dich tun?"
    db=store.connect()
    db.execute("INSERT INTO sessions VALUES(?,?,?)",("repeat",json.dumps({"turn_count":1,"recent_response_hashes":[store.stable_id(repeated)]}),store.now()))
    db.execute("INSERT INTO conversation_messages(session_id,role,content,created_at) VALUES(?,?,?,?)",("repeat","user","Hi",store.now()))
    db.execute("INSERT INTO conversation_messages(session_id,role,content,created_at) VALUES(?,?,?,?)",("repeat","assistant",repeated,store.now()))
    db.commit();db.close()
    monkeypatch.setattr(engine,"configured_provider",lambda:"openai")
    queue=[answer_result(repeated,"smalltalk"),answer_result("Hi nochmal — was liegt an?","smalltalk")]
    monkeypatch.setattr(engine,"agent_request",lambda *_args,**_kwargs:queue.pop(0))
    judged=[]
    def validate(*_args,**_kwargs):judged.append(True);return pass_result()
    monkeypatch.setattr(engine,"validator_request",validate)
    result=engine.chat("repeat","Hi")
    assert result["message"]=="Hi nochmal — was liegt an?" and result["retry_count"]==1
    assert len(judged)==1
    db=store.connect();detail=json.loads(db.execute("SELECT detail FROM decision_events WHERE stage='validator'").fetchone()[0]);db.close()
    assert [x["verdict"] for x in detail["attempts"]]==["repeat","pass"]


def test_price_output_is_regenerated_without_money(seeded_db,monkeypatch):
    monkeypatch.setattr(engine,"configured_provider",lambda:"openai")
    queue=[answer_result("Das kostet 12,50 €."),answer_result("Die aktuellen Preise findest du in unserer Speisekarte.")]
    monkeypatch.setattr(engine,"agent_request",lambda *_args,**_kwargs:queue.pop(0))
    monkeypatch.setattr(engine,"validator_request",lambda *_args,**_kwargs:pass_result())
    result=engine.chat("no-price","Was kostet das Schnitzel?")
    assert result["message"]=="Die aktuellen Preise findest du in unserer Speisekarte."
    assert "€" not in result["message"] and result["retry_count"]==1
    db=store.connect();detail=json.loads(db.execute("SELECT detail FROM decision_events WHERE stage='validator'").fetchone()[0]);db.close()
    assert [x["verdict"] for x in detail["attempts"]]==["price_policy","pass"]
