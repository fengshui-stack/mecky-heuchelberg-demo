# Mecky – digitaler Gastgeber der Heuchelberger Warte

Mecky ist ein modellgeführter Chatbot: GPT-5 Mini führt das Gespräch, strikt typisierte Tools liefern Betriebsfakten und ein separater GPT-5-Mini-Validator prüft jede Antwort vor der Ausgabe.

- **Kundentest:** https://mecky-kundentest.ben-fenger.chatgpt.site/
- **API/Demo:** https://mecky-heuchelberg-demo.onrender.com/
- **Quellcode:** https://github.com/fengshui-stack/mecky-heuchelberg-demo

## Lokal starten

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m mecky.bootstrap
.venv/bin/uvicorn mecky.api:app --host 127.0.0.1 --port 8000
```

Benötigte Produktionsvariablen sind `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-5-mini`, `OPENAI_API_KEY` und `ADMIN_SECRET`. Ohne OpenAI-Schlüssel liefert die Entwicklungsinstanz ausschließlich einen ehrlichen Notfalltext und führt keine vermeintliche Ersatz-Chatlogik aus.

## Architektur

`mecky/engine.py` sendet die aktuelle Nachricht und die letzten zehn Originalnachrichten an GPT-5 Mini. Das Modell kann 17 Read-only-Werkzeuge in `mecky/tools.py` aufrufen. Deren strukturierte Ergebnisse bilden den Evidence Cache des Turns. `mecky/validator.py` prüft die formulierte Antwort in einem getrennten Modellaufruf. Bei ungedeckten Fakten folgen höchstens zwei Korrekturversuche, danach ein thematischer Notfalltext.

Es gibt im Live-Pfad keinen Intent-Router, kein Planning-Modul, keine Keywordlisten und keine Antworttemplates. Crawler, FTS5, PDF-Kartenparser, Team-Regeln und Admin-Overrides bleiben die Wissensquellen. Details stehen in [docs/architecture.md](docs/architecture.md).

## API

- `POST /chat`: vollständige validierte Antwort
- `POST /chat/stream`: validierte Metadaten, danach Text-Deltas per SSE
- `GET /model`: Modell und hinterlegte Preise
- `GET /health`: Dienst, Wissensindex, Provider und Architektur
- `/admin/knowledge`, `/admin/traces`, `/admin/analytics`: geschützte Pflege und Diagnose

Jede Antwort enthält echte Provider-Nutzung für Agent, Tool-Runden und Validator. `session_usage` summiert Tokens, Modellaufrufe und geschätzte Kosten. Die schmale Entwickler-HUD oberhalb des WhatsApp-Interfaces zeigt diese Werte live.

## Tests

```bash
.venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python scripts/live_contract_check.py
PYTHONPATH=. .venv/bin/python scripts/live_engine_check.py
```

Die Tests prüfen strikte Tool-Schemas, Tool-Auswahl, Evidence Cache, Validator-Retry, Notfalltext, zehn Originalnachrichten, SSE-Reihenfolge, redigierte Traces, Analytics und die getrennte Telemetrie-HUD. Das Ausgangsprotokoll des alten Live-Builds liegt in [docs/live-chat-100-messages-2026-09-16.json](docs/live-chat-100-messages-2026-09-16.json).

## Deployment

`render.yaml` definiert den Webdienst in Frankfurt und hält `OPENAI_API_KEY` sowie `ADMIN_SECRET` als nicht synchronisierte Secrets. `data/seed.db` wird beim Start in den flüchtigen Laufzeitspeicher kopiert. Für dauerhaft gespeicherte Chats, Feedbacks und Admin-Overrides ist später ein persistenter Datenspeicher nötig.
