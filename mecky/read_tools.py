"""Narrow, grounded read operations for the conversation decision layer."""
from dataclasses import dataclass, field
import json
import re

from .menu import current_document, examples, matching_items, source_metadata, is_fresh
from .understanding import normalize


@dataclass
class ToolResult:
    trace_id: str
    status: str
    message: str
    links: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    error: str | None = None
    handoff: bool = False
    referenced_item: str | None = None


def get_catalogue(db, category: str, question: str, state: dict, trace_id: str, locale="de") -> ToolResult:
    """Answer only from the selected current official PDF; uncertain prices stay uncertain."""
    if category not in ("menu", "drinks"):
        return ToolResult(trace_id, "UNKNOWN", "", error="UNSUPPORTED_CATEGORY")
    doc = current_document(db, category)
    intent = "MENU" if category == "menu" else "DRINKS"
    from .engine import source_link  # Reuse the official homepage-link fallback.
    link = source_link(db, intent)
    links = [link] if link else []
    sources = [source_metadata(doc)] if doc else []
    q = normalize(question)
    if doc and not is_fresh(doc):
        text = (("My copy of the menu may be out of date; please check the official card here." if category == "menu" else
                 "My copy of the drinks card may be out of date; please check the official card here.") if locale == "en" else
                ("Meine gespeicherte Speisekarte ist möglicherweise nicht mehr aktuell. Schau bitte in die offizielle Karte." if category == "menu" else
                 "Meine gespeicherte Getränkekarte ist möglicherweise nicht mehr aktuell. Schau bitte in die offizielle Karte."))
        return ToolResult(trace_id, "PARTIAL", text, links, sources, error="STALE_CARD")
    allergy = bool(re.search(r"\b(\w*allergie|allergy|allergen|nut allergy|severe allergy|anaphylax|unverträglich|zöliakie|celiac)\b", q))
    if allergy:
        text = ("For an allergy, please check the menu with our team before ordering; I can't confirm a dish is safe from ingredients alone."
                if locale == "en" else "Bei einer Allergie prüf das Gericht bitte vor der Bestellung direkt mit dem Team; aus Zutaten allein kann ich keine Sicherheit ableiten.")
        from .engine import CONTACT
        links.append({"url": CONTACT, "title": "Contact" if locale == "en" else "Kontakt"})
        return ToolResult(trace_id, "PARTIAL", text, links, sources, handoff=True)

    dietary = re.search(r"\b(vegan\w*|vegetarisch\w*|glutenfrei|vegetarian|gluten free)\b", q)
    if dietary and doc:
        tag = ("vegan" if dietary.group(0).startswith("vegan") else
               "vegetarisch" if dietary.group(0).startswith("vegetar") else "glutenfrei")
        from .menu import indexed_items
        listed = [x for x in indexed_items(db,doc) if tag in json.loads(x["dietary_labels"])]
        if listed:
            names = ", ".join(x["item_name"].title() for x in listed[:3])
            text = (f"The card explicitly labels {names} as {tag}." if locale=="en" else
                    f"Als {tag} bezeichnet die Karte zum Beispiel {names}.")
            return ToolResult(trace_id,"KNOWN",text,links,sources)
        text = ("The card doesn't clearly label a suitable dish; please check the menu. For an allergy, confirm with our team." if locale=="en" else
                "Die Karte kennzeichnet dafür kein Gericht eindeutig. Schau bitte in die Karte; bei einer Allergie frag vor der Bestellung das Team.")
        return ToolResult(trace_id,"PARTIAL",text,links,sources,error="DIETARY_UNVERIFIED")

    if category=="menu" and doc and re.search(r"\b(kinder|kids|children)\b",q):
        from .menu import indexed_items
        available = indexed_items(db,doc)
        preferred = ("KINDERSCHNITZEL", "BERG-NUGGETS", "MECKIS KNUSPERTELLER")
        children = [next((x for x in available if normalize(x["item_name"])==normalize(name)),None) for name in preferred]
        children = [x for x in children if x] or [x for x in available if re.search(r"kind|nuggets",normalize(x["item_name"]))]
        if children:
            names = ", ".join(x["item_name"].title() for x in children[:3])
            text = (f"For children, the menu lists {names}, for example." if locale=="en" else
                    f"Für Kinder stehen zum Beispiel {names} auf der Karte.")
            return ToolResult(trace_id,"KNOWN",text,links,sources)
        return ToolResult(trace_id,"PARTIAL","I can't read the children's dishes clearly; here's the menu." if locale=="en" else
                          "Die Kindergerichte kann ich gerade nicht klar auslesen; hier ist die Karte.",links,sources,error="CHILDREN_MENU_UNREADABLE")

    item = re.search(r"\b(\w*schnitzel|burger|spritz|bier|wein|kaffee|waffel|kuchen|beer|wine|coffee)\b", q)
    term = item.group(0) if item else (state.get("last_referenced_item") if re.search(r"\b(kostet das|wie viel|wie teuer|how much|price)\b", q) else None)
    if term in ("beer", "wine", "coffee"):
        term = {"beer": "bier", "wine": "wein", "coffee": "kaffee"}[term]
    asking_price = bool(re.search(r"\b(preis|kostet|kosten|teuer|price|how much)\b", q)) or bool(state.get("pending_catalogue_price"))
    if term and doc:
        _, matches = matching_items(db, category, term)
        names = [x["item_name"].title() for x in matches[:3]]
        if term == "schnitzel" and "bergschnitzel" in normalize(doc["content"]) and not any("bergschnitzel" in normalize(name) for name in names):
            names.insert(0, "Bergschnitzel")
        if names:
            if asking_price:
                priced = [x for x in matches if x["price"] and normalize(x["item_name"]) == normalize(term)]
                if len(priced) == 1:
                    text = (f"{priced[0]['item_name'].title()} is listed at {priced[0]['price']}." if locale == "en"
                            else f"{priced[0]['item_name'].title()} steht mit {priced[0]['price']} auf der Karte.")
                    return ToolResult(trace_id, "KNOWN", text, links, sources, referenced_item=term)
                if len(names)>1:
                    text = (f"Do you mean {names[0]} or {names[1]}?" if locale == "en" else
                            f"Meinst du {names[0]} oder {names[1]}?")
                else:
                    text = (f"I can't reliably match a price to {names[0]} in this PDF." if locale == "en" else
                            f"Den Preis für {names[0]} kann ich aus dem PDF gerade nicht eindeutig zuordnen.")
                return ToolResult(trace_id, "PARTIAL", text, links, sources,
                                  error="PRICE_ITEM_AMBIGUOUS" if len(names)>1 else "PRICE_UNREADABLE", referenced_item=term)
            text = (f"Yes, the current card lists {', '.join(names[:3])}." if locale == "en"
                    else f"Ja, auf der Karte stehen {', '.join(names[:3])}.")
            return ToolResult(trace_id, "KNOWN", text, links, sources, referenced_item=term)
        # Full text may contain a product whose OCR layout defeated item parsing.
        if re.search(r"\b" + re.escape(term) + r"\b", normalize(doc["content"])):
            text = (f"{term.title()} appears on the current card; I can't read its details reliably from this PDF."
                    if locale == "en" else f"{term.title()} finde ich auf der Karte; die Details sind im PDF nicht eindeutig lesbar.")
            return ToolResult(trace_id, "PARTIAL", text, links, sources, referenced_item=term)
        text = (f"I can't find {term} on the current card. Want to see the full menu?"
                if locale == "en" else f"{term.title()} finde ich auf der aktuellen Karte nicht. Soll ich dir die ganze Karte zeigen?")
        return ToolResult(trace_id, "PARTIAL", text, links, sources, referenced_item=term)

    if doc:
        _, chosen = examples(db, category)
        if chosen:
            names = ", ".join(x["item_name"].title() for x in chosen)
            text = ((f"The current menu includes {names}, for example. Here's the full card." if category == "menu" else
                     f"The drinks card includes {names}, for example. Here's the full card.") if locale == "en" else
                    (f"Auf der Karte stehen zum Beispiel {names}. Hier ist die ganze Speisekarte." if category == "menu" else
                     f"Bei den Getränken gibt's zum Beispiel {names}. Hier ist die ganze Getränkekarte."))
            return ToolResult(trace_id, "KNOWN", text, links, sources)
    if link:
        text = (("I don't have readable dish details yet; here's the official menu." if category == "menu" else
                 "I don't have readable drink details yet; here's the official drinks card.") if locale == "en" else
                ("Die Gerichte kann ich gerade nicht sicher auslesen; hier ist die offizielle Speisekarte." if category == "menu" else
                 "Die Getränke kann ich gerade nicht sicher auslesen; hier ist die offizielle Getränkekarte."))
        return ToolResult(trace_id, "PARTIAL", text, links, sources, error="NO_READABLE_ITEMS")
    text = (("Are you after a particular dish?" if category == "menu" else "Are you looking for a particular drink?") if locale == "en" else
            ("Suchst du ein bestimmtes Gericht?" if category == "menu" else "Suchst du ein bestimmtes Getränk?"))
    return ToolResult(trace_id, "PARTIAL", text, error="NO_CURRENT_CARD")


def get_opening_hours(db, date, trace_id: str, locale="de") -> ToolResult:
    from .engine import current_admin, hours_fact, friendly_opening
    if not date:
        return ToolResult(trace_id, "PARTIAL", "Which day would you like to visit?" if locale == "en" else "Für welchen Tag möchtest du kommen?", error="DATE_REQUIRED")
    admin = current_admin(db, "opening_hours", date)
    fact = admin or hours_fact(db, "opening_hours", date)
    if not fact:
        text = (f"I can't confirm the opening hours for {date.strftime('%d.%m.%Y')}. Is this a regular visit or an event?" if locale == "en" else
                f"Für den {date.strftime('%d.%m.%Y')} kann ich die Öffnung gerade nicht bestätigen. Geht's um einen normalen Besuch oder eine Feier?")
        return ToolResult(trace_id, "PARTIAL", text, error="NO_DATE_FACT")
    value = fact["value"]
    if locale == "en":
        hours = re.search(r"(\d{1,2}(?::\d{2})?) bis (\d{1,2}(?::\d{2})?) Uhr", value)
        if hours and not re.search(r"geschlossen|nur|ausnahm|außer", value, re.I):
            text = f"On {date.strftime('%d.%m.%Y')}, we're open from {hours[1]} to {hours[2]}."
        elif re.search(r"geschlossen|nur.*veranstaltung", value, re.I):
            text = f"We're closed to regular visitors on {date.strftime('%d.%m.%Y')}."
        else:
            text = f"The published opening note for {date.strftime('%d.%m.%Y')} is: {value}."
    else:
        text = friendly_opening(value, date)
    source_url = fact["source_url"] if "source_url" in fact.keys() else None
    sources = [{"title": "Öffnungszeiten", "url": source_url, "source_type": "structured_fact",
                "crawl_timestamp": fact["retrieved_at"] if "retrieved_at" in fact.keys() else None,
                "content_date": date.isoformat(), "valid_from": fact["valid_from"] if "valid_from" in fact.keys() else None,
                "valid_until": fact["valid_until"] if "valid_until" in fact.keys() else None,
                "priority": fact["priority"] if "priority" in fact.keys() else None}] if source_url else []
    return ToolResult(trace_id, "KNOWN", text,
                      [{"url": source_url, "title": "Opening hours" if locale == "en" else "Öffnungszeiten"}] if source_url else [], sources)


def get_dog_policy(db, trace_id: str, locale="de") -> ToolResult:
    row = db.execute("SELECT value,source_url,updated_at FROM manual_knowledge WHERE section='Hausregeln Hunde' LIMIT 1").fetchone()
    if not row:
        return ToolResult(trace_id, "PARTIAL", "I can't confirm the dog policy yet. Is this about a regular visit?" if locale == "en" else
                          "Die Hunderegel kann ich gerade nicht bestätigen. Geht's um einen normalen Besuch?", error="NO_POLICY_SOURCE")
    text = "Dogs are welcome; please keep them on a leash." if locale == "en" else "Hunde dürfen mit, bitte nehmt sie an die Leine."
    source = {"title": "Hausregeln Hunde", "url": row["source_url"], "source_type": "team_rule",
              "crawl_timestamp": row["updated_at"], "content_date": None, "valid_from": None, "valid_until": None, "priority": 2}
    return ToolResult(trace_id, "KNOWN", text, sources=[source])


def get_payment_policy(db, trace_id: str, locale="de") -> ToolResult:
    row = db.execute("SELECT value,source_url,updated_at FROM manual_knowledge WHERE section='Zahlungsarten' LIMIT 1").fetchone()
    if not row:
        return ToolResult(trace_id, "PARTIAL", "I can't confirm payment methods yet. Are you asking about cash or cards?" if locale == "en" else
                          "Die Zahlungsarten kann ich gerade nicht bestätigen. Geht's dir um Barzahlung oder Karte?", error="NO_PAYMENT_SOURCE")
    text = ("You can pay cash or by EC card; Visa and Mastercard are also accepted." if locale == "en" else
            "Ihr könnt bar, mit EC-Karte, Visa oder Mastercard zahlen.")
    source = {"title": "Zahlungsarten", "url": row["source_url"], "source_type": "team_rule",
              "crawl_timestamp": row["updated_at"], "content_date": None, "valid_from": None, "valid_until": None, "priority": 2}
    return ToolResult(trace_id, "KNOWN", text, sources=[source])


def get_parking(db, trace_id: str, locale="de") -> ToolResult:
    row=db.execute("SELECT * FROM structured_facts WHERE subject='parking_rule' ORDER BY retrieved_at DESC LIMIT 1").fetchone()
    if not row:
        return ToolResult(trace_id,"PARTIAL","Where would you be arriving from?" if locale=="en" else "Von wo reist du an?",error="NO_PARKING_SOURCE")
    text=("Please park at the bottom of the hill rather than driving up to the Warte. It's about a 10-minute walk uphill." if locale=="en" else
          "Bitte parkt unten am Berg, nicht direkt an der Warte. Von dort sind es etwa zehn Minuten zu Fuß bergauf.")
    url=row["source_url"]
    source={"title":"Parken","url":url,"source_type":"structured_fact","crawl_timestamp":row["retrieved_at"],
            "content_date":None,"valid_from":row["valid_from"],"valid_until":row["valid_until"],"priority":row["priority"]}
    return ToolResult(trace_id,"KNOWN",text,[{"url":url,"title":"Parking" if locale=="en" else "Parken"}],[source])


def get_directions(db, trace_id: str, locale="de") -> ToolResult:
    row=db.execute("SELECT * FROM structured_facts WHERE subject='address' ORDER BY retrieved_at DESC LIMIT 1").fetchone()
    if not row:
        return ToolResult(trace_id,"PARTIAL","Are you coming by car or public transport?" if locale=="en" else "Kommst du mit dem Auto oder mit öffentlichen Verkehrsmitteln?",error="NO_ADDRESS_SOURCE")
    text=("We're at Auf dem Heuchelberg 1, 74211 Leingarten-Heilbronn." if locale=="en" else
          "Ihr findet uns auf dem Heuchelberg 1, 74211 Leingarten-Heilbronn.")
    url=row["source_url"]
    source={"title":"Adresse","url":url,"source_type":"structured_fact","crawl_timestamp":row["retrieved_at"],
            "content_date":None,"valid_from":row["valid_from"],"valid_until":row["valid_until"],"priority":row["priority"]}
    return ToolResult(trace_id,"KNOWN",text,[{"url":url,"title":"Directions" if locale=="en" else "Anfahrt"}],[source])


def get_reservation_information(db, party_size: int | None, trace_id: str, locale="de") -> ToolResult:
    row=db.execute("SELECT * FROM structured_facts WHERE subject='reservation' ORDER BY retrieved_at DESC LIMIT 1").fetchone()
    from .engine import BOOKING, GROUP_FORM
    if party_size and party_size>14:
        text=(f"For {party_size} guests, please use the group enquiry." if locale=="en" else
              f"Für {party_size} Personen nutzt bitte die Gruppenanfrage.")
        link={"url":GROUP_FORM,"title":"Group enquiry" if locale=="en" else "Gruppenanfrage"}
    else:
        text=("You can book a table online; current slots are shown in the booking system." if locale=="en" else
              "Einen Tisch könnt ihr online reservieren; freie Zeiten stehen im Buchungssystem.")
        link={"url":BOOKING,"title":"Book a table" if locale=="en" else "Tisch reservieren"}
    source={"title":"Reservierung","url":row["source_url"],"source_type":"structured_fact",
            "crawl_timestamp":row["retrieved_at"],"content_date":None,"valid_from":row["valid_from"],
            "valid_until":row["valid_until"],"priority":row["priority"]} if row else None
    return ToolResult(trace_id,"KNOWN" if row else "PARTIAL",text,[link],[source] if source else [],
                      error=None if row else "NO_RESERVATION_SOURCE")
