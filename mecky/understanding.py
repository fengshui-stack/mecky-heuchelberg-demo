"""Local, inspectable conversation routing. Original guest text is never rewritten."""
from dataclasses import dataclass, asdict
import re
import unicodedata


@dataclass(frozen=True)
class Route:
    mode: str
    intents: tuple[str, ...]
    entities: dict
    needs_retrieval: bool
    needs_action: bool
    needs_clarification: bool
    confidence: float

    def trace(self):
        return asdict(self)


def normalize(message: str) -> str:
    """Normalize only for understanding, including common dialect and STT spellings."""
    value = unicodedata.normalize("NFKC", message).casefold()
    value = value.replace("’", "'").replace("`", "'")
    value = re.sub(r"[^\wäöüß' ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    substitutions = (
        (r"\bhamma\b|\bham mer\b", "haben wir"),
        (r"\bgibts\b|\bgibt's\b", "gibt es"),
        (r"\bfuddern\b|\bfuttern\b|\bfressen\b", "essen"),
        (r"\bsaufen\b", "trinken"),
        (r"\bbierchen\b", "bier"),
        (r"\bwieviel\b", "wie viel"),
        (r"\bkost des\b", "kostet das"),
        (r"\bwoi\b", "wein"),
        (r"\bauf ham\b", "offen haben"),
        (r"\bwie gehts\b|\bwie geht's\b", "wie geht es"),
    )
    for pattern, replacement in substitutions:
        value = re.sub(pattern, replacement, value)
    return value


PATTERNS = (
    ("DOGS", r"\b(hund|hunde|dog|dogs|haustier)\b"),
    ("PAYMENT", r"\b(bezahlen|zahlung|karte zahlen|kreditkarte|visa|mastercard|ec karte|pay|payment|credit card|cash)\b"),
    ("KITCHEN_HOURS", r"\b(küche|kitchen)\b.*\b(offen|open|bis|schließt|schliesst|zeit|hours)\b|\b(bis|wann|zeit|hours)\b.*\b(küche|kitchen)\b"),
    ("OPENING_HOURS", r"\b(öffnungszeit|geöffnet|offen|auf|öffnet|öffnen|open|opening hours|hours)\b|\b(heute|morgen|übermorgen|freitag|samstag|sonntag|today|tomorrow|friday|saturday|sunday)\b.*\b(kommen|komme|besuchen|vorbeikommen|come|visit)\b"),
    ("MENU", r"\b(hunger|hungrig|essen|speisen|speisekarte|menü|menu|food|hungry|futter|leckeres|\w*schnitzel|burger|vegetarisch|vegan\w*|glutenfrei|\w*allergie|allergy|allergen|zöliakie|celiac|waffel|kuchen)\b"),
    ("DRINKS", r"\b(durst|durstig|trinken|getränke|getränkekarte|bier|wein|spritz|kaffee|drinks|drink|thirsty|beer|wine|coffee)\b"),
    ("CHILDREN", r"\b(kinder|kind|pony|spielplatz|children|kids|playground)\b"),
    ("RESERVATION", r"\b(reservierung|reservieren|reservier|buchen|tisch|plätze|platz frei|booking|book|reserve|reservation|table|availability)\b"),
    ("WEDDING", r"\b(hochzeit|heiraten|trauung|wedding)\b"),
    ("CORPORATE_EVENT", r"\b(firma|firmenfeier|firmenevent|betrieb|tagung|kollegen|corporate|company)\b"),
    ("PRIVATE_EVENT", r"\b(geburtstag|feier|taufe|konfirmation|birthday|party|private event)\b"),
    ("CURRENT_EVENT", r"\b(events?|veranstaltung|programm|was ist los|weinprobe)\b"),
    ("PARKING", r"\b(park\w*|auto|car|e ladeplatz|charging point|hochfahren)\b"),
    ("PUBLIC_TRANSPORT", r"\b(s bahn|bahn|bus|train|public transport)\b"),
    ("DIRECTIONS", r"\b(anfahrt|adresse|weg|hochfahren|directions|address|how to get)\b"),
    ("ACCESSIBILITY", r"\b(rollstuhl|barrierefrei|gehbehindert|wheelchair|accessible|accessibility)\b"),
    ("CONTACT", r"\b(kontakt|kontaktieren|telefon|anrufen|email|e mail|contact|call|phone|human|mensch|mitarbeiter|beschwerde|whatsapp)\b"),
    ("VOUCHER", r"\b(gutscheine?|geschenkkarte|voucher|gift cards?)\b"),
    ("WEATHER_RELATED", r"\b(regen|rain|schlechtes wetter|bad weather)\b"),
    ("GARDEN", r"\b(biergarten|garten|terrasse|garden|outdoors)\b"),
)


def language(message: str) -> str:
    q = normalize(message)
    english = re.findall(r"\b(?:i|am|do|does|can|could|you|your|we|is|are|the|please|tomorrow|today|menu|food|drink|dog|book|table|open|hours|thanks|hello|hi|hungry|thirsty|allow|have|want|what|where)\b", q)
    german = re.findall(r"\b(?:ich|ihr|habt|haben|wir|bei|euch|morgen|heute|essen|trinken|offen|danke|hallo|hund|tisch|und|ist|kann|darf|wie|für|zum)\b", q)
    return "en" if len(english) > len(german) and english else "de"


def route_message(message: str, state: dict | None = None) -> Route:
    state = state or {}
    q = normalize(message)
    locale = language(message)
    entities = {"locale": locale}
    item = re.search(r"\b(?:\w*schnitzel|burger|spritz|bier|wein|kaffee|waffel|kuchen)\b", q)
    if item:
        entities["referenced_item"] = item.group(0)
    group = re.search(r"\b(\d{1,3})\s*(?:leute|leuten|personen|gäste|people|guests)\b|\bwir sind\s+(\d{1,3})\b", q)
    if not group and re.search(r"\b(book|booking|reserve|reservation|table)\b", q):
        group = re.search(r"\bfor\s+(\d{1,3})\b", q)
    if group:
        entities["party_size"] = int(group.group(1) or (group.group(2) if group.lastindex and group.lastindex > 1 else None))
    clock = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(?:uhr|o'clock|pm|am)\b", q)
    if clock:
        entities["time"] = clock.group(0)
    elif re.search(r"\b(abend|evening|morgen früh|morning|mittag|noon)\b", q):
        entities["time_of_day"] = re.search(r"\b(abend|evening|morgen früh|morning|mittag|noon)\b", q).group(0)

    from .boundaries import is_off_topic
    if is_off_topic(q):
        return Route("CASUAL_OR_OFF_TOPIC", (), entities, False, False, False, 0.98)
    if re.fullmatch(r"(?:hi|hey|hallo|hello|servus|guten tag|good morning|good evening|danke|thanks|thank you|super|cool|okay|alles klar|tschüss|bye|wie geht es(?: dir)?|how are you)[!?. ]*", q):
        return Route("SMALLTALK", (), entities, False, False, False, 0.99)
    if re.search(r"\b(geschisse|geschissen|müde|muede|tired|joke|witz)\b", q) and not re.search(r"\b(essen|trinken|hungry|food|drink)\b", q):
        return Route("CASUAL_OR_OFF_TOPIC", (), entities, False, False, False, 0.9)

    hits = [(match.start(), name) for name, pattern in PATTERNS if (match := re.search(pattern, q))]
    intents = [name for _, name in sorted(hits)]
    if not intents and re.search(r"\b(heute|morgen|übermorgen|freitag|samstag|sonntag|today|tomorrow)\b", q) and re.search(r"\b(kommen|komme|besuchen|visit|come)\b", q):
        intents = ["OPENING_HOURS"]
    if "WEDDING" in intents or "PRIVATE_EVENT" in intents or "CORPORATE_EVENT" in intents:
        if "OPENING_HOURS" in intents and not re.search(r"\b(offen|geöffnet|open)\b", q):
            intents.remove("OPENING_HOURS")
    if "CHILDREN" in intents and "MENU" in intents and re.search(r"\b(kinder|kids|children)\b", q):
        intents.remove("CHILDREN")
    if "CHILDREN" in intents and not "MENU" in intents and re.search(r"\b(was habt ihr|what do you have)\b.*\b(kinder|kids|children)\b",q):
        intents.remove("CHILDREN")
        intents.append("MENU")
    if "DIRECTIONS" in intents and "PARKING" in intents:
        intents.remove("DIRECTIONS")
    if any(x in intents for x in ("WEDDING","CORPORATE_EVENT","PRIVATE_EVENT")) and "RESERVATION" in intents and not re.search(r"\b(tisch|table)\b",q):
        intents.remove("RESERVATION")
    if "GARDEN" in intents and "RESERVATION" in intents and re.search(r"\b(biergarten|garten|garden)\b",q):
        intents.remove("RESERVATION")
    if "GARDEN" in intents and "OPENING_HOURS" in intents and not re.search(r"\b(heute|morgen|tomorrow|today)\b",q):
        intents.remove("OPENING_HOURS")
    if re.search(r"\b(wie lange kocht|kocht ihr|kitchen closing|kitchen hours)\b",q):
        intents = ["KITCHEN_HOURS"]
    if "OPENING_HOURS" in intents and group and not re.search(r"\b(offen|geöffnet|open|opening hours)\b", q):
        intents.remove("OPENING_HOURS")
        intents.insert(0, "RESTAURANT_VISIT")
    if re.fullmatch(r"(?:wie viel kostet das|was kostet das|wie teuer(?: ist das)?|how much(?: is it)?|und das|and that)[?.! ]*", q):
        reference = state.get("last_user_intent") or state.get("intent")
        if reference:
            intents = [reference]
            entities["reference_from_context"] = True
    if not intents and len(q.split()) <= 4 and state.get("pending_clarification"):
        intents = [state["pending_clarification"]]
        entities["clarification_reply"] = True
    if not intents and re.search(r"\b(?:will|möchte|moechte|i want to)\b", q) and re.search(r"\b(?:kommen|come|visit)\b", q):
        intents = ["OPENING_HOURS"]
    intents = tuple(dict.fromkeys(intents))
    if not intents:
        return Route("AMBIGUOUS_VENUE_INTENT", (), entities, False, False, True, 0.35)
    broad = bool(re.fullmatch(r"(?:ich (?:hab|habe) hunger|ich (?:hab|habe) durst|i am hungry|i am thirsty|was gibt es (?:zu essen|zu trinken)|was gibt es leckeres)[?.! ]*", q))
    needs_action = "RESERVATION" in intents and bool(re.search(r"\b(reservieren|buchen|book|reserve)\b", q))
    return Route("ACTION_REQUEST" if needs_action else "VENUE_INFORMATION", intents, entities,
                 True, needs_action, broad and len(intents) == 1, 0.9 if len(intents) == 1 else 0.82)
