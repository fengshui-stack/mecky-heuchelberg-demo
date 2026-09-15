"""
Wissensdatenbank für Mecki - Heuchelberger Warte Chatbot
Lädt die RAG-Daten aus der heuchelberger-warte-rag.md Datei
"""

import os
import re
from pathlib import Path
from typing import Optional, List

# Pfad zur RAG-Datei
RAG_FILE_PATH = Path(__file__).parent / "heuchelberger-warte-rag.md"


def load_knowledge_base() -> str:
    """Lädt die Wissensdatenbank aus der Markdown-Datei."""
    try:
        with open(RAG_FILE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"WARNUNG: RAG-Datei nicht gefunden: {RAG_FILE_PATH}")
        return ""


# Wissensdatenbank beim Import laden
KNOWLEDGE_BASE = load_knowledge_base()


# Keywords für Kategorisierung
KEYWORDS = {
    "öffnungszeiten": ["öffnungszeiten", "geöffnet", "offen", "wann", "uhrzeit", "zeiten"],
    "reservierung": ["reservieren", "reservierung", "tisch", "buchen", "buchung", "platz", "sevenrooms"],
    "speisekarte": ["speisekarte", "essen", "gericht", "menü", "menu", "karte", "speisen"],
    "preise": ["preis", "kosten", "kostet", "euro", "€", "preise"],
    "kontakt": ["kontakt", "telefon", "email", "mail", "anrufen", "erreichen", "info@"],
    "anfahrt": ["anfahrt", "weg", "adresse", "parken", "parkplatz", "wo", "finden", "navi", "navigation"],
    "shuttle": ["shuttle", "hupfer", "heuchelberghupfer", "transfer", "bus"],
    "veranstaltung": ["veranstaltung", "feier", "feiern", "party", "event", "raum", "räume", "bankett"],
    "hochzeit": ["hochzeit", "heiraten", "trauung", "hochzeitsfeier"],
    "trauerfeier": ["trauerfeier", "beerdigung", "trauer", "beisetzung", "abschied", "kondolenz"],
    "gruppe": ["gruppe", "gruppenanfrage", "firma", "verein", "firmenfeier"],
    "hunde": ["hund", "hunde", "haustier"],
    "glutenfrei": ["glutenfrei", "allergie", "unverträglichkeit", "zöliakie"],
    "zahlung": ["bezahlen", "zahlung", "ec", "karte", "visa", "mastercard", "cash", "bar"],
    "jobs": ["job", "jobs", "karriere", "bewerbung", "ausbildung", "stelle", "arbeiten"],
}

# Empathie-Trigger Patterns
EMPATHY_TRIGGERS = {
    "trauerfeier": {
        "patterns": [r"trauer", r"beerdigung", r"beisetzung", r"abschied", r"kondolenz", r"verstorben"],
        "prefix": "Mein Beileid. "
    },
    "hochzeit": {
        "patterns": [r"hochzeit", r"heirat", r"trau(ung|en)", r"vermähl"],
        "prefix": "Herzlichen Glückwunsch! "
    }
}


def check_empathy_trigger(message: str) -> Optional[str]:
    """
    Prüft ob eine Empathie-Antwort nötig ist.
    Gibt den passenden Prefix zurück oder None.
    """
    message_lower = message.lower()

    for trigger_type, config in EMPATHY_TRIGGERS.items():
        for pattern in config["patterns"]:
            if re.search(pattern, message_lower):
                return config["prefix"]

    return None


def is_greeting_only(message: str) -> bool:
    """Prüft ob die Nachricht nur eine Begrüßung ist."""
    greetings = [
        r"^hallo\.?$",
        r"^hi\.?$",
        r"^hey\.?$",
        r"^guten\s*(tag|morgen|abend)\.?$",
        r"^servus\.?$",
        r"^grüß\s*(gott|dich)\.?$",
        r"^moin\.?$",
    ]

    message_clean = message.strip().lower()

    for pattern in greetings:
        if re.match(pattern, message_clean):
            return True

    return False


def search_knowledge(query: str) -> str:
    """
    Durchsucht die Wissensdatenbank nach relevanten Abschnitten.
    Da die Datenmenge überschaubar ist, wird der gesamte Kontext zurückgegeben.
    """
    return KNOWLEDGE_BASE


def get_matched_keywords(query: str) -> List[str]:
    """Findet welche Keyword-Kategorien in der Anfrage vorkommen."""
    query_lower = query.lower()
    matched = []

    for category, keywords in KEYWORDS.items():
        for keyword in keywords:
            if keyword in query_lower:
                matched.append(category)
                break

    return matched


def extract_relevant_sections(query: str) -> str:
    """
    Extrahiert relevante Abschnitte aus der Wissensdatenbank basierend auf Keywords.
    Fallback: Gesamte Wissensdatenbank.
    """
    query_lower = query.lower()
    sections = KNOWLEDGE_BASE.split("\n## ")
    relevant_sections = []

    # Immer Kontakt-Infos einschließen
    for section in sections:
        if "kontakt" in section.lower()[:50]:
            relevant_sections.append("## " + section if not section.startswith("#") else section)
            break

    # Relevante Abschnitte basierend auf Query finden
    for section in sections:
        section_lower = section.lower()
        # Keywords aus der Sektion extrahieren
        keywords_match = re.search(r"keywords:\s*(.+?)(?:\n|$)", section_lower)

        if keywords_match:
            section_keywords = keywords_match.group(1)
            # Prüfen ob Query-Wörter in den Section-Keywords vorkommen
            query_words = query_lower.split()
            for word in query_words:
                if len(word) > 2 and word in section_keywords:
                    formatted_section = "## " + section if not section.startswith("#") else section
                    if formatted_section not in relevant_sections:
                        relevant_sections.append(formatted_section)
                    break

    if relevant_sections:
        return "\n\n".join(relevant_sections)

    # Fallback: Gesamte Wissensdatenbank
    return KNOWLEDGE_BASE


# Fallback-Nachricht
FALLBACK_MESSAGE = "Ich helfe dir gern weiter. Schreib uns an info@heuchelberg.com oder ruf kurz unter +49 7131 401849 an."
