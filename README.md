# Mecky – digitaler Gastgeber der Heuchelberger Warte

Mecky ist eine kanalunabhängige Chat-Engine mit einer responsiven Web-Demo. Sie beantwortet belegte Betriebsfragen zuerst, verlinkt anschließend die passende offizielle Seite und sagt offen, wenn ein Termin, Preis oder eine Regel nicht bestätigt ist. Die Demo läuft ohne LLM-Kosten; OpenAI und OpenRouter sind optional.

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

`LLM_PROVIDER=mock` ist der kostenlose Standard. Die belegten Betriebsantworten werden deterministisch formuliert. Optional sind `LLM_PROVIDER=openai` mit `OPENAI_API_KEY` oder `LLM_PROVIDER=openrouter` mit `OPENROUTER_API_KEY` und `LLM_MODEL`. In V1 nutzt Mecky ein Modell nur für Smalltalk; operative Antworten bleiben aus Sicherheitsgründen auch bei konfiguriertem Modell quellengebunden. Der Prompt liegt versioniert in `prompts/mecky_system_v1.md`; Website-Text ist ausdrücklich untrusted source content. Die Datenbank enthält eine separate `llm_usage`-Tabelle für Provider, Modell, Tokenzahlen und geschätzte Kosten. Für eine Kostenschätzung können `LLM_INPUT_USD_PER_M` und `LLM_OUTPUT_USD_PER_M` gesetzt werden; ohne Tarife wird 0 gespeichert. Der sichere Mock-Modus führt keine Modellanfragen aus.

## Evaluation

`eval/questions.jsonl` enthält 130 realistische Einzelanfragen samt Kategorie, erwarteter Quelle, nicht zu behauptenden Aussagen und Confidence-Erwartung. `scripts/evaluate.py` schreibt `eval/report.json` mit Linkprüfung, Statusverteilung, verbotenen Behauptungen und Latenz. Das ist ein automatischer Smoke-Test; er ersetzt keine menschliche Faktenprüfung. `tests/test_mecky.py` deckt fünf mehrstufige Gespräche, Datumsauflösung, operative Halluzinationsfallen, manuelle Regeln, Feedback und den gesamten Admin-Override-Zyklus ab. `scripts/http_qa.py` prüft zusätzlich 20 Fragen und fünf Gesprächsfolgen gegen einen gestarteten Server.

## Deployment

`render.yaml` definiert eine kostenlose Python-Web-Demo in Frankfurt. Für einen direkten Render-Service gelten dieselben Befehle: Build `pip install -r requirements.txt`, Start `python -m mecky.bootstrap && uvicorn mecky.api:app --host 0.0.0.0 --port $PORT`; `MECKY_DB=/tmp/mecky.db`, `LLM_PROVIDER=mock`, `PYTHON_VERSION=3.12.8`. `ADMIN_SECRET` muss als Secret gesetzt werden. `/health` prüft API, Datenbank, Index und Provider. Nach einem neuen Crawl kann `scripts/create_seed.py` eine neue anonymisierte Startdatenbank erstellen, die per Git-Deploy veröffentlicht wird.

**Grenze des kostenlosen Render-Plans:** Das Dateisystem ist flüchtig. Die versionierte Wissensbasis wird beim Start aus `data/seed.db` wiederhergestellt, aber Chats, Feedback und Chef-Overrides auf der laufenden Instanz gehen bei Sleep, Neustart oder Redeploy verloren. Für dauerhaftes Online-Admin-Wissen ist ein externer persistenter Datenspeicher oder ein kostenpflichtiger Render-Datenträger erforderlich. Lokal bleibt SQLite persistent. Die Demo ist deshalb ein öffentlich testbarer V1-Prototyp und noch kein dauerhaftes Produktionssystem.

## Datenschutz und Sicherheit

Die Demo generiert zufällige Session-IDs, speichert keine IP-Adresse und benutzt kein User-Tracking. Gesprächsnachrichten können trotzdem personenbezogene Angaben enthalten; für eine produktive DSGVO-Nutzung sind Löschfristen, Einwilligung und ein persistenter Speicher zu ergänzen. Secrets liegen nur in Umgebungsvariablen, `.env` und Datenbankdateien mit Chats werden nicht committed. Die Admin-API prüft Secrets mit konstantem Vergleich, Eingaben werden validiert und Quellentexte bleiben Daten statt Anweisungen.

Der vorherige Chatbot-Prototyp liegt unverändert im Ordner `legacy/`. Seine Inhalte wurden geprüft; für Mecky ist besonders die RAG-Datei im Projektstamm als Team-Wissen relevant.
