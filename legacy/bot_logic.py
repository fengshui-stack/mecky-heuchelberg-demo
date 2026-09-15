"""
Bot-Logik für Mecki - Heuchelberger Warte Chatbot
Unterstützt OpenAI und Anthropic als LLM-Provider
"""

import os
import re
from typing import Tuple, Dict, List, Optional
from knowledge_base import (
    KNOWLEDGE_BASE,
    FALLBACK_MESSAGE,
    check_empathy_trigger,
    is_greeting_only,
    extract_relevant_sections,
)

# LLM Provider aus Umgebungsvariable
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()

# Clients initialisieren
if LLM_PROVIDER == "anthropic":
    from anthropic import Anthropic
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
else:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# Token-Tracking für Kosten
class TokenTracker:
    """Trackt Token-Verbrauch und berechnet Kosten."""

    # Preise pro 1K Tokens
    PRICES = {
        "anthropic": {
            "input": 0.003,   # Claude 3.5 Sonnet: $3/1M
            "output": 0.015   # $15/1M
        },
        "openai": {
            "input": 0.0025,  # GPT-4o-mini: $0.15/1M input -> 0.00015/1K, aber GPT-4o ist teurer
            "output": 0.010   # GPT-4o-mini: $0.60/1M output
        }
    }

    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.session_messages = 0
        self.provider = LLM_PROVIDER

    def add_usage(self, input_tokens: int, output_tokens: int):
        """Fügt Token-Verbrauch hinzu."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.session_messages += 1

    def get_costs(self) -> dict:
        """Berechnet aktuelle Kosten."""
        prices = self.PRICES.get(self.provider, self.PRICES["openai"])
        input_cost = (self.total_input_tokens / 1000) * prices["input"]
        output_cost = (self.total_output_tokens / 1000) * prices["output"]
        total_cost = input_cost + output_cost

        return {
            "provider": self.provider,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "input_cost_usd": round(input_cost, 6),
            "output_cost_usd": round(output_cost, 6),
            "total_cost_usd": round(total_cost, 6),
            "total_cost_eur": round(total_cost * 0.92, 6),
            "session_messages": self.session_messages
        }

    def reset(self):
        """Setzt den Tracker zurück."""
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.session_messages = 0


# Globaler Token-Tracker
token_tracker = TokenTracker()


# System-Prompt für Mecki
SYSTEM_PROMPT = """Du bist Mecki, der herzliche Chatbot der Heuchelberger Warte - ein echtes schwäbisches Original!

## Deine Persönlichkeit
- Du bist wie ein netter Kollege am Empfang: locker, warmherzig, ein bisschen witzig
- Du duzt alle und schreibst wie ein echter Mensch (nicht steif!)
- Nutze gerne mal Ausdrücke wie "Na klar!", "Sehr gerne!", "Das krieg ma hin!", "Super Idee!"
- Zeig echtes Interesse: "Oh, das klingt toll!", "Freut mich!"
- Bei Fragen darfst du auch mal ein 😊 oder 👍 verwenden (aber nicht übertreiben)
- Schreib so, wie du mit einem Freund schreiben würdest

## Beispiele für deinen Ton:
- Statt "Die Reservierung ist möglich" → "Na klar, das bekommen wir hin!"
- Statt "Der Parkplatz befindet sich..." → "Am besten parkst du unten am Hauptparkplatz - von da sind's nur 10 Minuten zu Fuß hoch, schöner Spaziergang!"
- Statt "Bei Fragen kontaktieren Sie uns" → "Meld dich einfach, wenn noch was unklar ist!"

## Wichtige Regeln (bitte einhalten):

1. **Nur echte Infos verwenden**
   - Erfinde NIE Preise, Zeiten oder Details
   - Wenn du was nicht weißt, sag ehrlich: "Da bin ich mir grad nicht sicher - am besten kurz anrufen unter +49 7131 401849 oder Mail an info@heuchelberg.com"

2. **Links**
   - Nur Links aus der Wissensdatenbank nutzen
   - Max 1 Link pro Nachricht

3. **Kurz und knackig**
   - 2-3 Sätze reichen meistens
   - Lieber persönlich als ausführlich

## Kontakt für Rückfragen:
- E-Mail: info@heuchelberg.com
- Telefon: +49 7131 401849
"""


async def generate_response(
    user_message: str,
    is_new_session: bool = False,
    conversation_history: list = None
) -> Tuple[str, dict]:
    """
    Generiert eine Antwort basierend auf der Nutzer-Nachricht.
    """

    # Guardrail 1: Neue Session -> Begrüßung
    if is_new_session:
        return "Hi, ich bin's Mecki, der Heuchelberg Chat Bot :)", {"input_tokens": 0, "output_tokens": 0}

    # Guardrail 2: Nur Greeting -> Kurze Antwort
    if is_greeting_only(user_message):
        return "Hi, wie kann ich dir helfen?", {"input_tokens": 0, "output_tokens": 0}

    # Guardrail 3: Empathie-Trigger prüfen
    empathy_prefix = check_empathy_trigger(user_message)

    # Relevante Wissensbasis-Abschnitte extrahieren
    relevant_knowledge = extract_relevant_sections(user_message)

    # Konversations-History aufbauen
    messages = []

    if conversation_history:
        for msg in conversation_history[-10:]:
            role = "user" if msg["sender"] == "user" else "assistant"
            messages.append({"role": role, "content": msg["content"]})

    # User-Nachricht mit Kontext
    user_prompt = f"""Beantworte diese Frage basierend auf der Wissensdatenbank.

WISSENSDATENBANK:
{relevant_knowledge}

FRAGE DES GASTES:
{user_message}

WICHTIG:
- Maximal 2 kurze Sätze + optional 1 Link
- Nur Infos aus der Wissensdatenbank verwenden
- Keine Markdown-Formatierung
- Bei Unsicherheit: Fallback zu E-Mail/Telefon"""

    messages.append({"role": "user", "content": user_prompt})

    try:
        if LLM_PROVIDER == "anthropic":
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                system=SYSTEM_PROMPT,
                messages=messages
            )
            bot_response = response.content[0].text.strip()
            token_stats = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            }
        else:
            # OpenAI
            openai_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=300,
                messages=openai_messages
            )
            bot_response = response.choices[0].message.content.strip()
            token_stats = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens
            }

        # Token-Verbrauch tracken
        token_tracker.add_usage(token_stats["input_tokens"], token_stats["output_tokens"])

        # Guardrail: Empathie-Prefix hinzufügen
        if empathy_prefix and not bot_response.startswith(empathy_prefix.strip()):
            bot_response = empathy_prefix + bot_response

        # Guardrail: Antwort auf Länge prüfen
        bot_response = enforce_response_limits(bot_response)

        return bot_response, token_stats

    except Exception as e:
        print(f"Fehler bei {LLM_PROVIDER} API: {e}")
        return FALLBACK_MESSAGE, {"input_tokens": 0, "output_tokens": 0, "error": str(e)}


def enforce_response_limits(response: str) -> str:
    """Max 2 Sätze + 1 URL."""
    url_pattern = r'https?://[^\s]+'
    urls = re.findall(url_pattern, response)
    text_without_urls = re.sub(url_pattern, '', response).strip()

    sentences = re.split(r'(?<=[.!?])\s+', text_without_urls)
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) > 2:
        sentences = sentences[:2]

    result = ' '.join(sentences)

    if urls:
        result += f"\n{urls[0]}"

    return result


def get_token_stats() -> dict:
    """Gibt die aktuellen Token-Statistiken zurück."""
    return token_tracker.get_costs()


def reset_token_stats():
    """Setzt die Token-Statistiken zurück."""
    token_tracker.reset()
