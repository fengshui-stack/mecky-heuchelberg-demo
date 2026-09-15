import json
import shutil

from fastapi.testclient import TestClient

from mecky import engine, store
from mecky.api import app
from mecky.engine import chat, resolve_date
from mecky.menu import current_document, parse_items, source_metadata
from mecky.understanding import normalize, route_message


def test_normalization_and_compositional_routing():
    assert normalize("Hamma morgen auf?!") == "haben wir morgen auf"
    assert route_message("hamma morgen auf").intents == ("OPENING_HOURS",)
    assert route_message("was gibts zum fuddern").intents == ("MENU",)
    assert route_message("was gibts bei euch zu saufen?").intents == ("DRINKS",)
    assert route_message("bierchen?").intents == ("DRINKS",)
    assert route_message("Habt ihr morgen offen und darf mein Hund mit?").intents == ("OPENING_HOURS", "DOGS")
    assert route_message("wie gehts?").mode == "SMALLTALK"
    assert route_message("I am hungry").entities["locale"] == "en"
    assert route_message("Kann ich ein Firmenevent buchen?").intents == ("CORPORATE_EVENT",)
    assert route_message("Brauche ich für den Biergarten eine Reservierung?").intents == ("GARDEN",)
    assert route_message("habt ihr Gutscheine?").intents == ("VOUCHER",)
    assert route_message("Wie komme ich mit der S-Bahn?").intents == ("PUBLIC_TRANSPORT",)
    assert route_message("Darf ich direkt hochfahren?").intents == ("PARKING",)
    assert route_message("Gibt es eine geheime Weinprobe für 5 Euro?").intents == ("CURRENT_EVENT",)
    from datetime import datetime
    from zoneinfo import ZoneInfo
    reference = datetime(2026,9,16,tzinfo=ZoneInfo("Europe/Berlin"))
    assert resolve_date("Öffnet ihr am 24. Dezember?",reference).isoformat()=="2026-12-24"
    assert resolve_date("Ist am 6. Januar geöffnet?",reference).isoformat()=="2027-01-06"


def test_smalltalk_and_casual_skip_retrieval_and_feedback(seeded_db, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("indexed retrieval should not run")
    monkeypatch.setattr(engine, "retrieve", forbidden)
    for n, text in enumerate(("wie gehts?", "Danke", "ich hob geschisse")):
        answer = chat(f"casual-{n}", text)
        assert answer["response_type"] == "conversation"
        assert answer["show_feedback"] is False
        assert answer["actions"] == []
    db = store.connect()
    gates = [json.loads(x[0]) for x in db.execute("SELECT detail FROM decision_events WHERE stage='retrieval'")]
    assert all(not gate["gate"] for gate in gates)
    db.close()


def test_real_menu_drinks_item_followup_and_contract(tmp_path, monkeypatch):
    target = tmp_path / "live-seed-copy.db"
    shutil.copyfile("data/seed.db", target)
    monkeypatch.setattr(store, "DB_PATH", target)
    hunger = chat("food-flow", "ich hab hunger")
    assert "Käsespätzle" in hunger["message"]
    assert "Berg-Currybowl" in hunger["message"]
    assert hunger["show_feedback"] is True
    assert hunger["response_type"] == "factual"
    assert any(action["type"] == "VIEW_MENU" for action in hunger["actions"])
    assert hunger["sources"][0]["source_type"] == "pdf"
    first = chat("schnitzel-flow", "Habt ihr Schnitzel?")
    second = chat("schnitzel-flow", "Wie teuer?")
    third = chat("schnitzel-flow", "Kinderschnitzel")
    assert "Bergschnitzel" in first["message"]
    assert second["response_type"] == "clarification" and second["show_feedback"] is False
    assert "Kinderschnitzel" in second["message"]
    assert "13,40 €" in third["message"]
    drinks = chat("drinks-flow", "was gibts bei euch zu saufen?")
    assert drinks["intents"] == ["DRINKS"]
    assert "Palmbräu" in drinks["message"]
    vegan = chat("vegan-flow", "was habt ihr vegan?")
    assert "Karotten-Ingwer-Suppe" in vegan["message"]
    assert "Ziegenfrischkäse" not in vegan["message"]
    allergy = chat("allergy-flow", "Ich habe eine schwere Nussallergie")
    assert allergy["handoff"] is True
    assert any(action["type"] == "CONTACT" for action in allergy["actions"])
    assert "garantiert" not in allergy["message"].lower()
    english = chat("english-flow", "I am hungry")
    assert english["message"].startswith("The current menu")
    en_hours = chat("english-hours", "Is it open tomorrow?")
    assert en_hours["message"].startswith("On ")
    combined = chat("combined-flow", "Habt ihr morgen offen und darf mein Hund mit?")
    assert combined["intents"] == ["OPENING_HOURS", "DOGS"]
    assert "Leine" in combined["message"]
    assert "Uhr" in combined["message"]
    food_drink = chat("food-drink-flow", "Was gibt's zu essen und zu trinken?")
    assert food_drink["intents"] == ["MENU", "DRINKS"]
    assert any(action["type"] == "VIEW_MENU" for action in food_drink["actions"])
    assert any(action["type"] == "VIEW_DRINKS" for action in food_drink["actions"])
    dog_parking = chat("dog-parking-flow", "Darf mein Hund mit und wo parke ich?")
    assert dog_parking["intents"] == ["DOGS", "PARKING"]
    assert "Leine" in dog_parking["message"] and "unten" in dog_parking["message"]


def test_menu_extraction_is_structured_and_newer_year_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "freshness.db")
    db = store.connect()
    for year, price in ((2025, "6,50"), (2026, "7,50")):
        url = f"https://heuchelberg.com/wp-content/uploads/{year}/menu-{year}.pdf"
        text = f"KAROTTEN-INGWER-SUPPE\nVegane Suppe mit Kokos\n{price}\n"
        doc = {"id": store.stable_id(url), "url": url, "canonical_url": url, "title": "Menü", "content": text,
               "content_type": "pdf", "crawled_at": store.now(), "last_modified": None,
               "content_hash": store.stable_id(text), "category": "menu", "source_priority": 4}
        store.upsert_document(db, doc)
    selected = current_document(db, "menu")
    assert "/2026/" in selected["url"]
    items = parse_items(selected["content"], "menu", selected["url"], selected["id"])
    assert items[0]["item_name"] == "KAROTTEN-INGWER-SUPPE"
    assert items[0]["price"] == "7,50 €"
    assert json.loads(items[0]["dietary_labels"]) == ["vegan"]
    assert items[0]["source_url"] == selected["url"]
    assert source_metadata(selected)["crawl_timestamp"]
    db.close()


def test_repetition_progress_and_booking_boundary(seeded_db):
    answers = [chat("repeat-flow", "was kann man essen") for _ in range(3)]
    assert len({answer["message"] for answer in answers}) == 3
    assert all(not any(action["type"] == "CONTACT" for action in answer["actions"]) for answer in answers)
    booking = chat("booking-flow", "Habt ihr am 20.09.2026 um 19 Uhr noch einen Tisch für 4 Personen frei?")
    assert booking["status"] == "PARTIAL"
    assert "Freie Tische kann ich noch nicht selbst prüfen" in booking["message"]
    assert any(action["type"] == "RESERVE" for action in booking["actions"])
    assert "reserviert" not in booking["message"].lower()
    cancellation = chat("cancel-flow", "Wie storniere ich meinen Tisch?")
    assert cancellation["handoff"] is True
    assert any(action["type"] == "CONTACT" for action in cancellation["actions"])
    assert "noch nicht selbst" in cancellation["message"]


def test_expired_session_does_not_reuse_stale_turn(seeded_db):
    first=chat("expired-flow","was kann man essen")
    db=store.connect()
    db.execute("UPDATE sessions SET updated_at='2020-01-01T00:00:00+00:00' WHERE id='expired-flow'")
    db.commit();db.close()
    after_expiry=chat("expired-flow","was kann man essen")
    assert after_expiry["message"]==first["message"]


def test_admin_traces_and_analytics_expose_decisions_not_guest_text(seeded_db):
    chat("trace-flow", "wie gehts?")
    client = TestClient(app)
    headers = {"x-admin-secret": "test-secret"}
    traces = client.get("/admin/traces", headers=headers).json()["items"]
    assert {item["stage"] for item in traces} == {"route", "retrieval", "response"}
    assert "wie gehts" not in json.dumps(traces).lower()
    analytics = client.get("/admin/analytics", headers=headers).json()
    assert analytics["retrieval"]["requests"] == 1
    assert analytics["retrieval"]["indexed_searches"] == 0
