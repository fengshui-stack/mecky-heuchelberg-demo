"""Contracts for the independent GPT-5 Mini evidence validator."""
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ValidatorVerdict(BaseModel):
    model_config=ConfigDict(extra="forbid")
    verdict: Literal["pass","fail"]
    reason: str=Field(max_length=500)
    ungrounded_claims: list[str]=Field(max_length=10)


def schema()->dict:
    result=ValidatorVerdict.model_json_schema()
    result["additionalProperties"]=False
    result["required"]=list(result["properties"])
    return result


def prompt(answer: str,evidence: dict)->str:
    return """Du bist der Faktenprüfer für Mecky, den Chatbot der Heuchelberger Warte.

Prüfe ausschließlich, ob jede faktische Aussage über die Heuchelberger Warte durch den Evidence Cache gedeckt ist.
Ein Faktenfehler ist eine nicht gedeckte Zahl, Uhrzeit, Datum, Menge, ein Gericht, Getränk, Event, eine Regel, Adresse, ein Name oder eine Kontaktinfo.
Kleine sprachliche Umformulierungen sind erlaubt. Ignoriere Smalltalk, Humor, Emotionen, Rückfragen und ehrliche Unsicherheit.
Bei Unsicherheit entscheide pass. Prüfe nicht Ton oder Stil.

WICHTIGE ENTSCHEIDUNGSREGELN:
- Eine Frage ist keine Tatsachenbehauptung. Rückfragen immer ignorieren.
- Gesprächssätze wie „ich hör zu“, „alles gut?“ oder „womit kann ich helfen?“ sind keine Fakten über den Betrieb.
- Ist der Evidence Cache leer, entscheide pass, solange die Antwort keine konkrete betriebliche Tatsache über die Heuchelberger Warte behauptet.
- Wenn ein Tool ein ISO-Datum und dazu eine Öffnungszeiten-Regel liefert, ist die Anwendung dieser Regel auf genau dieses Datum gedeckt.
- Wenn die Antwort dieselben Daten wie der Cache nur natürlicher formuliert, entscheide pass.
- Erfinde niemals selbst einen möglichen Fehler. Fail nur bei einer konkreten, widersprüchlichen oder fehlenden betrieblichen Behauptung.

ANTWORT:
"""+answer+"\n\nEVIDENCE CACHE:\n"+json.dumps(evidence,ensure_ascii=False)


def parse(payload)->ValidatorVerdict|None:
    try:return ValidatorVerdict.model_validate(payload)
    except ValidationError:return None
