# Mecky – digitaler Gastgeber der Heuchelberger Warte

Mecky ist eine kanalunabhängige Chat-Engine mit einer responsiven Web-Demo. Sie beantwortet belegte Betriebsfragen zuerst, verlinkt anschließend die passende offizielle Seite und sagt offen, wenn ein Termin, Preis oder eine Regel nicht bestätigt ist. Die Demo läuft ohne LLM-Kosten; OpenAI und OpenRouter sind optional.

**Messenger-Kundentest:** https://mecky-kundentest.ben-fenger.chatgpt.site/

**Öffentliche Demo:** https://mecky-heuchelberg-demo.onrender.com/ · **Quellcode:** https://github.com/fengshui-stack/mecky-heuchelberg-demo

## Schnellstart

Python 3.12 oder neuer wird benötigt.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# ADMIN_SECRET in .env durch einen langen zufälligen Wert ersetzen
.venv/bin/python -m mecky.bootstrap
.venv/bin/uvicorn mecky.api:app --host 127.0.0.1 --port 8000
```

Chat: `http://127.0.0.1:8000/`, Team-Ansicht: `/admin`, Health: `/health`. Die Team-Ansicht verlangt das in `ADMIN_SECRET` gesetzte Secret. Die mitgelieferte `data/seed.db` enthält ausschließlich offizielle Inhalte und die manuell gepflegten Regeln; sie enthält keine Chats, Admin-Overrides oder Nutzerdaten.

Aktualisierung und Tests:

```bash
.venv/bin/python -m mecky refresh
.venv/bin/python -m mecky import-rag
.venv/bin/python -m mecky stats
.venv/bin/python -m mecky prune
.venv/bin/python -m pytest -q
.venv/bin/python scripts/build_eval.py
.venv/bin/python -m scripts.evaluate
```

`crawl` und `refresh` prüfen robots.txt, den Sitemap-Index sowie Navigation und offizielle PDF-Links. Sie bleiben auf `heuchelberg.com`, begrenzen Seiten und Dateigröße und verarbeiten nur Dokumente mit geändertem Content-Hash erneut. `reindex` erstellt strukturierte Fakten nach Änderungen an der Extraktion erneut. Die interne Sitemap steht in `docs/site-map.md`.

## Architektur

`mecky/crawler.py` erfasst HTML und PDF mit URL, Titel, Canonical, Zeitstempel, Hash, Kategorie und Priorität; bei neuen PDFs bleiben die Seitengrenzen erhalten. `mecky/store.py` nutzt SQLite und FTS5 für Dokumente, Textchunks, strukturierte Fakten, strukturierte Kartenprodukte, Sessions, Admin-Wissen, Feedback und Wissenslücken. `mecky/understanding.py` normalisiert Umgangssprache nur für die Erkennung, erkennt mehrere Anliegen und liefert eine interne Routing-Entscheidung. `mecky/read_tools.py` liest aktuelle Karten, Öffnungszeiten und Hausregeln gezielt; `mecky/engine.py` koordiniert diese Werkzeuge mit dem Gesprächszustand. Die API in `mecky/api.py` bleibt unabhängig von der Weboberfläche. Ein späterer WhatsApp-Adapter kann dieselbe Chat-Funktion oder `/chat` verwenden. Die Diagnose des früheren Verhaltens und die verbleibenden Grenzen stehen in `docs/agent-audit.md`.

Quellenrang: aktive Chef-Overrides → manuell gepflegte Team-Regeln aus `heuchelberger-warte-rag.md` → aktuelle offizielle Website → aktuelle offizielle PDFs. Allgemeines Modellwissen ist keine Quelle für Betriebsfakten. Manche Richtwerte in der RAG-Datei widersprechen der Live-Seite oder haben keinen aktuellen Zeitraum; sie sind beim Import mit Konflikthinweisen versehen und werden nicht als feste aktuelle Slots ausgegeben. Beispielsweise nennt die Website derzeit 28 Tage Reservierungsvorlauf, während die ältere RAG-Notiz „in der Regel 3 Wochen“ erwähnt.

Die Zeitlogik speichert Monats- und Wochentagsregeln getrennt von datierten Ausnahmen. Ein Chef-Override mit Zeitraum hat Vorrang. Fehlt für den angefragten Tag eine eindeutige Angabe, fragt Mecky nach dem Zweck des Besuchs, statt ungefragt auf die Kontaktseite zu verweisen. Freie Tische, Preise und künftige Veranstaltungen werden nicht aus allgemeinem Wissen geschätzt.

## Chat und Team-Wissen

`POST /chat` erwartet `{"session_id":"optional","message":"Habt ihr Sonntag geöffnet?"}` und liefert Antwort, Status, erkannte Anliegen, passende Aktionen und Quellen sowie `response_type`, `show_feedback` und `handoff`. Das bisherige einzelne `intent` und `links` bleiben für ältere Clients enthalten. Eine anonyme Session speichert Datum, Personenzahl, zuletzt besprochenes Kartenprodukt, offene Rückfragen, letzte Aktionen und Antwort-Hashes. Sie nutzt die letzten Nachrichten in voller Form und hält ältere relevante Angaben kompakt. So kann „Wie teuer?“ nach einer Schnitzelfrage das Gericht wieder aufnehmen. `user_memory` ist für späteres, einwilligungsbasiertes Langzeitwissen separat angelegt; die Web-Demo nutzt es noch nicht.

Team-Wissen lässt sich über `POST /admin/knowledge`, `GET /admin/knowledge`, `PATCH /admin/knowledge/{id}` und `DELETE /admin/knowledge/{id}` pflegen. Das Löschen deaktiviert einen Eintrag. Jede Anfrage benötigt `X-Admin-Secret`. Die Admin-Seite bietet ein Formular, bestehende Overrides, Wissenslücken, häufige Intents und negatives Feedback. Gäste können keinen Betriebsfakt verändern. `GET /admin/gaps` und `GET /admin/analytics` zeigen aggregierte Qualitätsdaten; `POST /feedback` nimmt 👍/👎 entgegen. Nutzerrückmeldungen werden nie automatisch als Betriebswahrheit übernommen.

## Modell und Kosten

`LLM_PROVIDER=mock` ist der kostenlose Standard. Für einen lokalen GPT-5-Mini-Test setzt man `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-5-mini` und `OPENAI_API_KEY` in der ignorierten `.env`. Bei belegten Fragen erzeugt das Modell nur einen kurzen, persönlichen Einstieg; die quellengebundene Faktenantwort wird unverändert angehängt. Smalltalk kann das Modell vollständig formulieren. Fachfremde Anfragen gehen nicht zum Modell. Der Laufzeit-Prompt setzt sich aus `prompts/identity.md`, `conversation.md`, `grounding.md`, `safety.md`, `reservations.md` und `style.md` zusammen; Website-Text ist ausdrücklich untrusted source content. Die Datenbank enthält eine separate `llm_usage`-Tabelle für Provider, Modell, Tokenzahlen und geschätzte Kosten. Für GPT-5 Mini sind derzeit $0.25 pro Million Eingabe-Tokens und $2.00 pro Million Ausgabe-Tokens als Standardschätzung hinterlegt; `LLM_INPUT_USD_PER_M` und `LLM_OUTPUT_USD_PER_M` können diese Werte überschreiben. `/model` liefert das konfigurierte Modell und die Preise. Jede `/chat`-Antwort enthält `usage` für die einzelne Antwort und `session_usage` für das Gespräch. Die Anzeige nutzt ausschließlich gemeldete Tokens; bei Netzwerkfehlern oder fehlenden Nutzungsdaten zeigt sie „unbekannt“. Auch verworfene Modellantworten zählen zum Verbrauch. Die Preisangaben stammen von der [offiziellen GPT-5-Mini-Modellseite](https://developers.openai.com/api/docs/models/gpt-5-mini).

## Messenger-Kundentest

Die lokale Web-Demo bietet ein WhatsApp-artiges Testgespräch mit Quellenlinks, Feedback, neuem Chat und Tokenzähler im oberen Rand. Die Anzeige nutzt die echten `/chat`-Nutzungsdaten, keine aus Zeichenlängen erfundenen Tokens. Im regelbasierten Modus sind Modell-Tokens und Modellkosten null. API-Schlüssel bleiben im Backend; Gäste können keine kostenpflichtigen Modelle aktivieren.

Mecky zeigt sofort eine animierte Tippanzeige und sendet die Antwort erst nach mindestens 1,1 Sekunden. Diese UI-Pause erzeugt keine Tokens. Politik, Programmieraufträge und andere erkannte fachfremde Themen werden freundlich abgegrenzt, bevor Quellen oder ein Modell aufgerufen werden. Der vorherige Besuchskontext bleibt erhalten.

Die Engine erkennt auch umgangssprachliche Anliegen wie „ich hab Hunger“, „gibt’s was zu futtern“, „ich hab Durst“ und „will morgen kommen“. Bei einem allgemeinen Wunsch fragt Mecky gezielt nach; bei einer konkreten Frage nutzt er die passende Speise- oder Getränkekarte. Reformulierungen im selben Gespräch führen zu einer Anschlussfrage statt zur identischen Antwort. Der Kontaktlink erscheint nur bei ausdrücklichem Kontaktwunsch oder wenn eine individuelle Abstimmung mit dem Team nötig ist.

Die Sites-Quellen liegen lokal in `customer-site/` mit eigener Versionsverwaltung. `MECKY_ALLOWED_ORIGINS` erlaubt die veröffentlichte Sites-Origin; für lokale Entwicklung laufen die statische Seite auf Port 8787 und die API auf Port 8788. Die lokale Origin muss dann zusätzlich erlaubt werden.

## Evaluation

`eval/questions.jsonl` enthält 130 realistische Einzelanfragen samt Kategorie, erwarteter Quelle, nicht zu behauptenden Aussagen und Confidence-Erwartung. `scripts/evaluate.py` schreibt `eval/report.json` mit Linkprüfung, Statusverteilung, verbotenen Behauptungen und Latenz. Das ist ein automatischer Smoke-Test; er ersetzt keine menschliche Faktenprüfung. `tests/test_mecky.py` deckt fünf mehrstufige Gespräche, Datumsauflösung, operative Halluzinationsfallen, manuelle Regeln, Feedback und den gesamten Admin-Override-Zyklus ab. `scripts/http_qa.py` prüft zusätzlich 20 Fragen und fünf Gesprächsfolgen gegen einen gestarteten Server.

Am 15.09.2026 bestanden sechs Pytest-Tests, der 130-Fragen-Smoke-Test und die HTTP-Prüfung der öffentlichen Render-Demo einschließlich Admin-Override und Deaktivierung. Der erste Live-Index enthielt 83 offizielle Dokumente und 53 Abschnitte aus der Team-RAG-Datei. Browser-Sichtprüfung erfolgte in Desktop- und Mobilgröße.

Die Erweiterung ergänzt Regressionstests für Preisberechnung, Anbieter-Kosten, Session-Trennung, fehlende Preise/Nutzungsdaten, Timeouts, verworfene Modellantworten, Themenabgrenzung, Gesprächsrouting, Kartenextraktion, mehrteilige Fragen, Feedback-Steuerung und Reservierungsgrenzen. Aktuell bestehen 36 Tests. Die WebMCP-Aktionen zum Senden und Lesen des Verbrauchs wurden mit gültigen und ungültigen Eingaben gegen den lokalen Chatbot geprüft.

## Deployment

`render.yaml` definiert eine kostenlose Python-Web-Demo in Frankfurt. Für einen direkten Render-Service gelten dieselben Befehle: Build `pip install -r requirements.txt`, Start `python -m mecky.serve`; `MECKY_DB=/tmp/mecky.db`, `LLM_PROVIDER=mock`, `PYTHON_VERSION=3.12.8`. `ADMIN_SECRET` wird als Umgebungs-Secret oder als Render Secret File `/etc/secrets/mecky_admin_secret` gesetzt. Das lokal generierte Demo-Secret liegt nur in der ignorierten Datei `.env.admin`; es wird nie committed. `/health` prüft API, Datenbank, Index und Provider. Nach einem neuen Crawl kann `scripts/create_seed.py` eine neue anonymisierte Startdatenbank erstellen, die per Git-Deploy veröffentlicht wird.

**Grenze des kostenlosen Render-Plans:** Das Dateisystem ist flüchtig. Die versionierte Wissensbasis wird beim Start aus `data/seed.db` wiederhergestellt, aber Chats, Feedback und Chef-Overrides auf der laufenden Instanz gehen bei Sleep, Neustart oder Redeploy verloren. Für dauerhaftes Online-Admin-Wissen ist ein externer persistenter Datenspeicher oder ein kostenpflichtiger Render-Datenträger erforderlich. Lokal bleibt SQLite persistent. Die Demo ist deshalb ein öffentlich testbarer V1-Prototyp und noch kein dauerhaftes Produktionssystem.

## Datenschutz und Sicherheit

Die Demo generiert zufällige Session-IDs, speichert keine IP-Adresse und benutzt kein User-Tracking. Gesprächskontext wird nach 24 Stunden nicht mehr verwendet; `python -m mecky prune` löscht alte Chats und Sessions nach 7 Tagen sowie Feedback und Interaktionen nach 30 Tagen. Beispiele in Wissenslücken schwärzen E-Mail-Adressen und Telefonnummern. Gesprächsnachrichten können trotzdem personenbezogene Angaben enthalten; für eine produktive DSGVO-Nutzung sind Einwilligung, automatische Löschjobs und ein persistenter Speicher zu ergänzen. Secrets liegen nur in Umgebungsvariablen, `.env` und Datenbankdateien mit Chats werden nicht committed. Die Admin-API prüft Secrets mit konstantem Vergleich, Eingaben werden validiert und Quellentexte bleiben Daten statt Anweisungen.

Der vorherige Chatbot-Prototyp liegt unverändert im Ordner `legacy/`. Seine Inhalte wurden geprüft; für Mecky ist besonders die RAG-Datei im Projektstamm als Team-Wissen relevant.
