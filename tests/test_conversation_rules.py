import pytest

from mecky.engine import chat, detect_intent
from mecky.store import connect, now, stable_id


@pytest.mark.parametrize("message,intent", [
    ("ich hab hunger", "MENU"),
    ("was kann man essen", "MENU"),
    ("gibts was zu futtern", "MENU"),
    ("was habt ihr leckeres", "MENU"),
    ("ich hab durst", "DRINKS"),
    ("habt ihr bier", "DRINKS"),
    ("was gibt's zu trinken", "DRINKS"),
    ("will morgen kommen", "OPENING_HOURS"),
    ("habt ihr morgen auf", "OPENING_HOURS"),
    ("ich will morgen zu einer Hochzeit kommen", "WEDDING"),
])
def test_colloquial_intent_is_inferred(message, intent):
    assert detect_intent(message) == intent


def test_vague_need_gets_a_short_followup_without_contact(seeded_db):
    hunger = chat("hungry", "ich hab hunger")
    thirst = chat("thirsty", "ich hab durst")
    for result, intent in ((hunger, "MENU"), (thirst, "DRINKS")):
        assert result["intent"] == intent
        assert result["message"].count("?") == 1
        assert len(result["message"].split()) < 22
        assert all("/kontakt/" not in item["url"] for item in result["links"])
        assert "verlässliche" not in result["message"]


def test_menu_link_is_contextual_and_reformulation_moves_conversation_forward(seeded_db):
    db = connect()
    menu_url = "https://heuchelberg.com/speisekarte-test.pdf"
    db.execute("INSERT INTO source_links VALUES(?,?,?,?,?)", (stable_id(menu_url), stable_id("https://heuchelberg.com/"), "SPEISEKARTE", menu_url, now()))
    db.commit(); db.close()
    first = chat("menu-followup", "was kann man essen")
    second = chat("menu-followup", "welche speisen habt ihr?")
    assert first["intent"] == second["intent"] == "MENU"
    assert "offizielle Speisekarte" in first["message"]
    assert first["links"] == [{"url": menu_url, "title": "Speisekarte"}]
    assert second["message"] != first["message"]
    assert second["message"].endswith("?")
    assert second["links"] == []


def test_specific_missing_time_asks_about_visit_and_does_not_route_to_contact(seeded_db):
    answer = chat("missing-hours", "Habt ihr am 01.07.2027 offen?")
    assert answer["intent"] == "OPENING_HOURS"
    assert "01.07.2027" in answer["message"]
    assert "normalen Besuch oder eine Feier" in answer["message"]
    assert answer["message"].count("?") == 1
    assert all("/kontakt/" not in item["url"] for item in answer["links"])


def test_contact_link_only_when_context_requires_it(seeded_db):
    for n, question in enumerate(("Darf mein Hund mitkommen?", "Kann ich mit Visa zahlen?", "Ich hab Hunger")):
        result = chat(f"no-contact-{n}", question)
        assert all("/kontakt/" not in item["url"] for item in result["links"])
    contact = chat("contact", "Wie kann ich euch kontaktieren?")
    assert contact["intent"] == "CONTACT"
    assert any("/kontakt/" in item["url"] for item in contact["links"])
