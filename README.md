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

`mecky/crawler.py` erfasst HTML und PDF mit URL, Titel, Canonical, Zeitstempel, Hash, Kategorie und Priorität. `mecky/store.py` nutzt SQLite und FTS5 für Dokumente, Textchunks, strukturierte Fakten, Quelllinks, Sessions, Admin-Wissen, Feedback und Wissenslücken. `mecky/engine.py` löst relative Daten in `Europe/Berlin` auf, berücksichtigt Gesprächskontext und wählt vor Textsuche gültige Fakten und Admin-Overrides. Die API in `mecky/api.py` bleibt unabhängig von der Weboberfläche. Ein späterer WhatsApp-Adapter kann dieselbe Chat-Funktion oder `/chat` verwenden.

Quellenrang: aktive Chef-Overrides → manuell gepflegte Team-Regeln aus `heuchelberger-warte-rag.md` → aktuelle offizielle Website → aktuelle offizielle PDFs. Allgemeines Modellwissen ist keine Quelle für Betriebsfakten. Manche Richtwerte in der RAG-Datei widersprechen der Live-Seite oder haben keinen aktuellen Zeitraum; sie sind beim Import mit Konflikthinweisen versehen und werden nicht als feste aktuelle Slots ausgegeben. Beispielsweise nennt die Website derzeit 28 Tage Reservierungsvorlauf, während die ältere RAG-Notiz „in der Regel 3 Wochen“ erwähnt.

Die Zeitlogik speichert Monats- und Wochentagsregeln getrennt von datierten Ausnahmen. Ein Chef-Override mit Zeitraum hat Vorrang. Fehlt für den angefragten Tag eine eindeutige Angabe, antwortet Mecky mit Unsicherheit und Kontakt- oder Eventlink. Freie Tische, Preise und künftige Veranstaltungen werden nicht aus allgemeinem Wissen geschätzt.

## Chat und Team-Wissen

`POST /chat` erwartet `{"session_id":"optional","message":"Habt ihr Sonntag geöffnet?"}` und liefert Antwort, Links, Status `KNOWN`, `PARTIAL` oder `UNKNOWN`, Intent, Confidence und Interaction-ID. Eine anonyme Session speichert unter anderem Personenzahl, Datum und Thema, damit „Und Sonntag?“ oder „Wir sind 8“ im Gespräch verstanden werden. `user_memory` ist für späteres, einwilligungsbasiertes Langzeitwissen separat angelegt; die Web-Demo nutzt es noch nicht.

Team-Wissen lässt sich über `POST /admin/knowledge`, `GET /admin/knowledge`, `PATCH /admin/knowledge/{id}` und `DELETE /admin/knowledge/{id}` pflegen. Das Löschen deaktiviert einen Eintrag. Jede Anfrage benötigt `X-Admin-Secret`. Die Admin-Seite bietet ein Formular, bestehende Overrides, Wissenslücken, häufige Intents und negatives Feedback. Gäste können keinen Betriebsfakt verändern. `GET /admin/gaps` und `GET /admin/analytics` zeigen aggregierte Qualitätsdaten; `POST /feedback` nimmt 👍/👎 entgegen. Nutzerrückmeldungen werden nie automatisch als Betriebswahrheit übernommen.

## Modell und Kosten

`LLM_PROVIDER=mock` ist der kostenlose Standard. Die belegten Betriebsantworten werden deterministisch formuliert. Optional sind `LLM_PROVIDER=openai` mit `OPENAI_API_KEY` oder `LLM_PROVIDER=openrouter` mit `OPENROUTER_API_KEY` und `LLM_MODEL`. In V1 nutzt Mecky ein Modell nur für Smalltalk; operative Antworten bleiben aus Sicherheitsgründen auch bei konfiguriertem Modell quellengebunden. Der Prompt liegt versioniert in `prompts/mecky_system_v1.md`; Website-Text ist ausdrücklich untrusted source content. Die Datenbank enthält eine separate `llm_usage`-Tabelle für Provider, Modell, Tokenzahlen und geschätzte Kosten. Für eine Kostenschätzung können `LLM_INPUT_USD_PER_M` und `LLM_OUTPUT_USD_PER_M` gesetzt werden; ohne Tarife bleibt der Preis unbekannt. `/model` liefert das konfigurierte Modell und die Eingabe-/Ausgabepreise pro Million Tokens. Jede `/chat`-Antwort enthält `usage` für die einzelne Antwort und `session_usage` für das Gespräch. Anbieter-gemeldete Kosten haben Vorrang; alternativ werden reale Tokenzahlen mit den konfigurierten USD-Tarifen multipliziert und ausdrücklich als Schätzung markiert. Cache-Rabatte und weitere Sondertarife sind in dieser einfachen Schätzung nicht berücksichtigt. Fehlende Nutzungsdaten, Timeouts und unbekannte Preise bleiben sichtbar unbekannt; auch verworfene Modellantworten zählen zum Verbrauch. Die Tokenmessung folgt der [OpenRouter Usage Accounting-Dokumentation](https://openrouter.ai/docs/cookbook/administration/usage-accounting) und der [OpenAI Chat-Completions-Referenz](https://developers.openai.com/api/reference/resources/chat/subresources/completions). Der sichere Mock-Modus führt keine Modellanfragen aus.

## Messenger-Kundentest

Die zusätzliche Sites-Seite bietet ein WhatsApp-ähnliches Testgespräch mit Quellenlinks, Feedback, neuem Chat und sichtbaren Modellkosten. Am Desktop steht der Tokenzähler neben dem Chat; mobil öffnet „Kosten“ die Verbrauchsansicht. Die Anzeige nutzt die echten `/chat`-Nutzungsdaten, keine aus Zeichenlängen erfundenen Tokens. Im regelbasierten Modus sind Modell-Tokens und Modellkosten null. API-Schlüssel bleiben im Backend; Kunden können keine kostenpflichtigen Modelle aktivieren.

Mecky zeigt zunächst einen Lesehinweis und anschließend „schreibt …“. Vor der Anzeige liegt eine kurze, von der Antwortlänge abhängige Pause zwischen 0,9 und 2,8 Sekunden. Diese UI-Pause erzeugt keine Tokens und ist unabhängig von der gemessenen Backend-Verarbeitung. Politik, Programmieraufträge und andere erkannte fachfremde Themen werden freundlich abgegrenzt, bevor Quellen oder ein Modell aufgerufen werden. Der vorherige Besuchskontext bleibt erhalten.

Die Sites-Quellen liegen lokal in `customer-site/` mit eigener Versionsverwaltung. `MECKY_ALLOWED_ORIGINS` erlaubt die veröffentlichte Sites-Origin; für lokale Entwicklung laufen die statische Seite auf Port 8787 und die API auf Port 8788. Die lokale Origin muss dann zusätzlich erlaubt werden.

## Evaluation

`eval/questions.jsonl` enthält 130 realistische Einzelanfragen samt Kategorie, erwarteter Quelle, nicht zu behauptenden Aussagen und Confidence-Erwartung. `scripts/evaluate.py` schreibt `eval/report.json` mit Linkprüfung, Statusverteilung, verbotenen Behauptungen und Latenz. Das ist ein automatischer Smoke-Test; er ersetzt keine menschliche Faktenprüfung. `tests/test_mecky.py` deckt fünf mehrstufige Gespräche, Datumsauflösung, operative Halluzinationsfallen, manuelle Regeln, Feedback und den gesamten Admin-Override-Zyklus ab. `scripts/http_qa.py` prüft zusätzlich 20 Fragen und fünf Gesprächsfolgen gegen einen gestarteten Server.

Am 15.09.2026 bestanden sechs Pytest-Tests, der 130-Fragen-Smoke-Test und die HTTP-Prüfung der öffentlichen Render-Demo einschließlich Admin-Override und Deaktivierung. Der erste Live-Index enthielt 83 offizielle Dokumente und 53 Abschnitte aus der Team-RAG-Datei. Browser-Sichtprüfung erfolgte in Desktop- und Mobilgröße.

Die Erweiterung ergänzt Regressionstests für Preisberechnung, Anbieter-Kosten, Session-Trennung, fehlende Preise/Nutzungsdaten, Timeouts, verworfene Modellantworten und Themenabgrenzung. Alle 13 Tests bestanden. Die WebMCP-Aktionen zum Senden und Lesen des Verbrauchs wurden mit gültigen und ungültigen Eingaben gegen den lokalen Chatbot geprüft.

## Deployment

`render.yaml` definiert eine kostenlose Python-Web-Demo in Frankfurt. Für einen direkten Render-Service gelten dieselben Befehle: Build `pip install -r requirements.txt`, Start `python -m mecky.serve`; `MECKY_DB=/tmp/mecky.db`, `LLM_PROVIDER=mock`, `PYTHON_VERSION=3.12.8`. `ADMIN_SECRET` wird als Umgebungs-Secret oder als Render Secret File `/etc/secrets/mecky_admin_secret` gesetzt. Das lokal generierte Demo-Secret liegt nur in der ignorierten Datei `.env.admin`; es wird nie committed. `/health` prüft API, Datenbank, Index und Provider. Nach einem neuen Crawl kann `scripts/create_seed.py` eine neue anonymisierte Startdatenbank erstellen, die per Git-Deploy veröffentlicht wird.

**Grenze des kostenlosen Render-Plans:** Das Dateisystem ist flüchtig. Die versionierte Wissensbasis wird beim Start aus `data/seed.db` wiederhergestellt, aber Chats, Feedback und Chef-Overrides auf der laufenden Instanz gehen bei Sleep, Neustart oder Redeploy verloren. Für dauerhaftes Online-Admin-Wissen ist ein externer persistenter Datenspeicher oder ein kostenpflichtiger Render-Datenträger erforderlich. Lokal bleibt SQLite persistent. Die Demo ist deshalb ein öffentlich testbarer V1-Prototyp und noch kein dauerhaftes Produktionssystem.

## Datenschutz und Sicherheit

Die Demo generiert zufällige Session-IDs, speichert keine IP-Adresse und benutzt kein User-Tracking. Gesprächskontext wird nach 24 Stunden nicht mehr verwendet; `python -m mecky prune` löscht alte Chats und Sessions nach 7 Tagen sowie Feedback und Interaktionen nach 30 Tagen. Beispiele in Wissenslücken schwärzen E-Mail-Adressen und Telefonnummern. Gesprächsnachrichten können trotzdem personenbezogene Angaben enthalten; für eine produktive DSGVO-Nutzung sind Einwilligung, automatische Löschjobs und ein persistenter Speicher zu ergänzen. Secrets liegen nur in Umgebungsvariablen, `.env` und Datenbankdateien mit Chats werden nicht committed. Die Admin-API prüft Secrets mit konstantem Vergleich, Eingaben werden validiert und Quellentexte bleiben Daten statt Anweisungen.

Der vorherige Chatbot-Prototyp liegt unverändert im Ordner `legacy/`. Seine Inhalte wurden geprüft; für Mecky ist besonders die RAG-Datei im Projektstamm als Team-Wissen relevant.
