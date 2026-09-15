import hashlib
from pathlib import Path
import pytest

from mecky import store
from mecky.crawler import extract_facts
from mecky.manual import import_rag

HOME="""Heuchelberger Warte
Auf dem Heuchelberg 1
74211 Leingarten-Heilbronn
Telefon: 0 71 31 – 40 18 49
E-Mail: info@heuchelberg.com
Bitte fahrt nicht direkt nach oben! Es droht ein Bußgeld von 55€ vom Ordnungsamt Leingarten.
Der Hauptparkplatz direkt am Fuß der Heuchelberger Warte: ca. 10 min. bergauf.
Von Alte Burg ist der Weg geeignet für Rollstuhlfahrer.
Mit der S-Bahn Linie S4 ist Leingarten erreichbar.
Unsere Öffnungszeiten
ÖFFNUNGSZEITEN
SEPTEMBER
SONNTAGS
Sonntags 11 bis 23 Uhr geöffnet
SAMSTAGS
Samstags 12 bis 23 Uhr geöffnet
MITTWOCH - FREITAG
Mittwoch, Donnertag & Freitag 12 bis 22 Uhr geöffnet
Montag & Dienstag
Mo & Di nur für Veranstaltungen & Events auf Vorbestellung geöffnet
KÜCHENÖFFNUNGSZEIT
Unsere Küche hat an allen Öffnungstagen durchgehend bis 21 Uhr - ab 25 Grad bis 21:30 / Fr & Sa bis 22 Uhr geöffnet
Bei kaltem oder schlechtem Wetter behalten wir uns vor die Küche vorzeitig zu schließen
OKTOBER
Reserviere online einen Tisch für 1-14 Gäste in unserem Wirtshaus. Reservierungen im Bedienbereich sind 28 Tage im Voraus möglich.
Unser Garten hat zu unseren Öffnungszeiten bei jedem Wetter geöffnet. Man kann sich einfach ein Plätzle suchen und sich selbst bedienen.
Heuchelberg Hupfer: Einzelfahrt bergauf 1 Euro, Talfahrt kostenlos.
Berg-Brunch auf Vorbestellung.
"""

@pytest.fixture
def seeded_db(tmp_path,monkeypatch):
    monkeypatch.setattr(store,"DB_PATH",tmp_path/"mecky.db")
    monkeypatch.setenv("ADMIN_SECRET","test-secret")
    monkeypatch.setenv("LLM_PROVIDER","mock")
    db=store.connect()
    doc={"id":store.stable_id("https://heuchelberg.com/"),"url":"https://heuchelberg.com/","canonical_url":"https://heuchelberg.com/","title":"Heuchelberger Warte","content":HOME,"content_type":"html","crawled_at":store.now(),"last_modified":None,"content_hash":hashlib.sha256(HOME.encode()).hexdigest(),"category":"other","source_priority":3}
    store.upsert_document(db,doc)
    extract_facts(db,doc)
    wedding_url="https://heuchelberg.com/hochzeit-heuchelberg-bei-heilbronn/"
    wedding_content="Hochzeiten und Feiern auf dem Heuchelberg. Wir beraten euch zu eurem Fest und den Räumen."
    wedding={"id":store.stable_id(wedding_url),"url":wedding_url,"canonical_url":wedding_url,"title":"Hochzeit Heuchelberg","content":wedding_content,"content_type":"html","crawled_at":store.now(),"last_modified":None,"content_hash":hashlib.sha256(wedding_content.encode()).hexdigest(),"category":"weddings","source_priority":3}
    store.upsert_document(db,wedding)
    store.save_fact(db,"reservation","reservation","Reserviere online einen Tisch für 1-14 Gäste. Reservierungen 28 Tage im Voraus möglich.",doc["url"],doc["id"])
    db.commit();db.close()
    import_rag()
    yield
