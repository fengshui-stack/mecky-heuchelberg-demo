import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from mecky import provider
from mecky.api import app
from mecky.tools import TOOL_MODELS, execute, tool_definitions
from mecky.validator import schema


def test_all_tools_have_openai_strict_schemas():
    definitions=tool_definitions()
    assert len(definitions)==17 and set(TOOL_MODELS)=={x["name"] for x in definitions}
    for item in definitions:
        assert item["strict"] is True and item["parameters"]["additionalProperties"] is False
        assert set(item["parameters"]["required"])==set(item["parameters"].get("properties",{}))
    assert schema()["required"]==["verdict","reason","ungrounded_claims"]


def test_tools_return_structured_data_not_guest_copy(seeded_db):
    from mecky.store import connect
    db=connect()
    dog=execute(db,"get_dog_policy",{})
    booking=execute(db,"get_reservation_policy",{})
    db.close()
    assert dog.data=={"allowed":True,"leash_required":True}
    assert booking.data["online_guest_max"]==14
    assert booking.actions[0]["type"]=="RESERVE"


def test_responses_api_contract_and_live_usage(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER","openai");monkeypatch.setenv("OPENAI_API_KEY","test")
    payload={"model":"gpt-5-mini","output":[{"type":"message","content":[{"type":"output_text","text":json.dumps({"message":"Servus!","response_type":"smalltalk","contact_needed":False})}]}],"usage":{"input_tokens":1000,"output_tokens":250}}
    captured={}
    def fake_post(*_args,**kwargs):
        captured.update(kwargs["json"]);return httpx.Response(200,json=payload,request=httpx.Request("POST","https://api.openai.com/v1/responses"))
    monkeypatch.setattr(httpx,"post",fake_post)
    result=provider.agent_request([{"role":"user","content":"Hi"}],"persona",tool_definitions(),None)
    assert captured["model"]=="gpt-5-mini" and captured["store"] is False
    assert "temperature" not in captured and captured["text"]["format"]["strict"] is True
    assert result["payload"]["message"]=="Servus!"
    assert result["usage"]["tokens_total"]==1250
    assert result["usage"]["cost_usd"]==pytest.approx(.00075)


def test_stream_contract_emits_metadata_before_text(seeded_db,monkeypatch):
    response={"session_id":"stream","message":"Servus!","usage":{},"session_usage":{},"validator_result":"pass"}
    monkeypatch.setattr("mecky.api.chat",lambda *_args,**_kwargs:response)
    client=TestClient(app);result=client.post("/chat/stream",json={"session_id":"stream","message":"Hi"})
    assert result.status_code==200
    assert result.text.index("event: meta")<result.text.index("event: delta")<result.text.index("event: done")
    meta=json.loads(result.text.split("event: meta\ndata: ",1)[1].split("\n\n",1)[0])
    assert "message" not in meta and meta["validator_result"]=="pass"


def test_legacy_conversation_layers_are_gone():
    root=Path(__file__).parents[1]
    removed=("perception","understanding","planning","knowledge","generation","grounding","guardrails","dialogue","read_tools")
    assert all(not (root/"mecky"/(name+".py")).exists() for name in removed)
    runtime="\n".join(path.read_text(encoding="utf-8") for path in (root/"mecky").glob("*.py"))
    assert "Dazu habe ich keine verlässliche Information" not in runtime
    assert "Da möchte ich dir nichts Falsches erzählen" not in runtime


def test_customer_site_is_whatsapp_only_with_separate_telemetry_hud():
    root=Path(__file__).parents[1]/"customer-site"/"dist"
    html=(root/"index.html").read_text(encoding="utf-8")
    css=(root/"style.css").read_text(encoding="utf-8")
    js=(root/"app.js").read_text(encoding="utf-8")
    assert html.index('class="telemetry-hud"')<html.index('class="chat"')
    assert "Eine Frage" not in html and "SCHÖN, DASS DU DA BIST" not in html
    assert all(item in html for item in ("hud-calls","hud-latency","hud-validator","top-tokens","mobile-cost"))
    assert "ui-monospace" in css and "data.validator_result" in js
