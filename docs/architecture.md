# Mecky: modellgeführte Architektur

```text
Originalnachricht + letzte 10 Originalnachrichten
                    │
                    ▼
        GPT-5 Mini mit 17 strict Tools
          │                    │
   freie Unterhaltung     Tool-Aufrufe
                               │
                               ▼
                 strukturierte Wissensdaten
                               │
                               ▼
                  Evidence Cache dieses Turns
                               │
                    ┌──────────┘
                    ▼
              formulierte Antwort
                    │
                    ▼
       separater GPT-5-Mini-Validator
          │ pass              │ fail
          ▼                   ▼
       Rendering       Feedback + Retry (max. 2)
                              │
                              ▼
                 thematischer Notfalltext
```

`mecky/engine.py` enthält nur den Agenten-Loop. Es gibt davor keinen Router, keine Intent-Klassifikation, keine Keywordliste und kein Planungsmodul. GPT-5 Mini erhält den kurzen Charakter-Prompt aus `mecky/persona.yaml`, das aktuelle Datum, die letzten zehn Originalnachrichten und die Function-Tool-Schemas. Es entscheidet selbst, ob es normal antwortet oder Wissen benötigt.

## Fakten und Validierung

Die 17 Tools in `mecky/tools.py` verwenden Pydantic-Argumente, OpenAI `strict: true` und `additionalProperties: false`. Sie lesen ausschließlich SQLite-, Website-, PDF-, Admin- und Teamdaten und geben strukturierte Objekte zurück. Jedes Ergebnis wird in den turnlokalen Evidence Cache geschrieben.

Nach jeder formulierten Antwort prüft ein eigener GPT-5-Mini-Aufruf ausschließlich die Faktenbindung. Sein Vertrag ist `pass|fail`, eine kurze Begründung und eine Liste ungedeckter Aussagen. Bei `fail` bekommt das Hauptmodell diese Liste und darf neu formulieren oder weitere Tools aufrufen. Nach zwei Retries erscheint ein thematischer Notfalltext, der sich an den tatsächlich aufgerufenen Tools orientiert.

## Zustand und Ausgabe

SQLite speichert die Originalnachrichten, Turn-Zahl und letzte Antwort-Hashes. Der API-Vertrag enthält `response_type`, `show_feedback`, `contact`, `actions`, `sources`, `validator_result`, `retry_count`, `usage` und `session_usage`. Feedback wird nur für faktische Antworten angeboten. Kontakt und Links stammen aus Tool-Aktionen.

SSE sendet zuerst validierte Metadaten und danach Text-Deltas. Tool-Aufrufe und ungeprüfte Entwürfe werden nie gestreamt. Die Entwickler-HUD über der Kundensicht zeigt Modell, kumulierte Tokens, Kosten, Modellaufrufe, Latenz und Validatorstatus; sie ist gestalterisch vom WhatsApp-Interface getrennt.

## Beobachtbarkeit

Je Turn entstehen redigierte `decision_events` für `agent`, `tools`, `validator` und `rendering`. Sie enthalten keine Gastnachricht. `/admin/traces/{interaction_id}` zeigt den Pfad. `/admin/analytics` aggregiert Tool-Nutzung, Validatorresultate, Antworttypen, Latenzen, Tokens und Kosten.
