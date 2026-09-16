"""Strict, read-only knowledge tools. Outputs are data, never guest-facing prose."""
from dataclasses import dataclass, field
from datetime import date
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .menu import current_document, indexed_items, examples, source_metadata

BOOKING = "https://www.sevenrooms.com/explore/heuchelbergerwarte/reservations/create/search/"
GROUP_FORM = "https://8lnr26nliuj.typeform.com/to/sXrNgblN?typeform-source=heuchelberg.com"
CONTACT = "https://heuchelberg.com/kontakt/"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MenuArgs(StrictModel):
    category: Literal["all", "starter", "main", "dessert", "children"] = "all"
    vegetarian_only: bool = False
    search: str | None = None


class DrinksArgs(StrictModel):
    category: Literal["all", "beer", "wine", "coffee", "soft", "cocktail"] = "all"
    search: str | None = None


class DateArgs(StrictModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class DateRangeArgs(StrictModel):
    date_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    search: str | None = Field(default=None, min_length=2, max_length=80)


class EmptyArgs(StrictModel):
    pass


class AllergenArgs(StrictModel):
    dish: str = Field(min_length=2, max_length=100)


class VenueInfoArgs(StrictModel):
    topic: Literal["overview", "garden", "children", "kitchen_hours", "public_transport", "shuttle", "jobs", "brunch", "overnight", "smoking", "wedding", "private_events", "corporate_events"]
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


TOOL_MODELS = {
    "get_menu": MenuArgs, "get_drinks": DrinksArgs, "get_opening_hours": DateArgs,
    "get_dog_policy": EmptyArgs, "get_events": DateRangeArgs, "get_parking_info": EmptyArgs,
    "get_reservation_policy": EmptyArgs, "get_contact_info": EmptyArgs,
    "get_allergen_info": AllergenArgs, "get_vegetarian_options": EmptyArgs,
    "get_directions": EmptyArgs, "get_payment_methods": EmptyArgs,
    "get_accessibility_info": EmptyArgs, "get_group_policy": EmptyArgs,
    "get_voucher_info": EmptyArgs, "get_weather_dependent_opening": EmptyArgs,
    "get_venue_info": VenueInfoArgs,
}

DESCRIPTIONS = {
    "get_menu": "Use for hunger, food, menu or dish questions. Read current official dishes, descriptions, prices and dietary labels.",
    "get_drinks": "Use for thirst or drink questions. Read current official drinks and prices.",
    "get_opening_hours": "Read official opening hours for one date.",
    "get_dog_policy": "Read the approved rule for dogs.",
    "get_events": "Read confirmed official events in a date range.",
    "get_parking_info": "Read approved parking and hill-access facts.",
    "get_reservation_policy": "Read booking limits and the official booking action.",
    "get_contact_info": "Read approved contact details.",
    "get_allergen_info": "Read explicit allergen labels for one dish; never infer safety.",
    "get_vegetarian_options": "Read dishes explicitly labelled vegetarian or vegan.",
    "get_directions": "Read the official address and directions source.",
    "get_payment_methods": "Read approved payment methods.",
    "get_accessibility_info": "Read approved accessibility information.",
    "get_group_policy": "Read the group threshold and enquiry action.",
    "get_voucher_info": "Read approved voucher information.",
    "get_weather_dependent_opening": "Read weather-dependent garden and kitchen rules.",
    "get_venue_info": "Read one approved specialist topic such as garden, children or celebrations.",
}


def tool_definitions() -> list[dict]:
    definitions = []
    for name, model in TOOL_MODELS.items():
        schema = model.model_json_schema()
        schema["additionalProperties"] = False
        # OpenAI strict function tools require every property to be listed as
        # required. Optional arguments remain nullable through Pydantic's anyOf.
        schema["required"] = list(schema.get("properties", {}))
        definitions.append({"type": "function", "name": name, "description": DESCRIPTIONS[name],
                            "parameters": schema, "strict": True})
    return definitions


@dataclass
class ToolOutput:
    name: str
    data: dict
    status: str = "KNOWN"
    sources: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    error: str | None = None
    handoff: bool = False


def _source(row, title: str):
    if not row or "source_url" not in row.keys() or not row["source_url"]:
        return []
    return [{"title": title, "url": row["source_url"], "source_type": "structured_fact",
             "crawl_timestamp": row["retrieved_at"] if "retrieved_at" in row.keys() else None,
             "content_date": None, "valid_from": row["valid_from"] if "valid_from" in row.keys() else None,
             "valid_until": row["valid_until"] if "valid_until" in row.keys() else None,
             "priority": row["priority"] if "priority" in row.keys() else None}]


def _source_action(sources: list[dict], label: str = "Offizielle Informationen") -> list[dict]:
    """Expose a factual source as a contextual link, without inventing navigation."""
    return ([{"type": "VIEW_SOURCE", "label": label, "url": sources[0]["url"]}]
            if sources and sources[0].get("url") else [])


def _manual(db, section: str):
    return db.execute("SELECT * FROM manual_knowledge WHERE section=? LIMIT 1", (section,)).fetchone()


def _fact(db, category: str, subject: str):
    return db.execute("SELECT * FROM structured_facts WHERE category=? AND subject=? ORDER BY priority,retrieved_at DESC LIMIT 1", (category, subject)).fetchone()


def _hours(db, day: date, category="opening_hours"):
    admin=db.execute("SELECT * FROM admin_knowledge WHERE active=1 AND category=? AND (valid_from IS NULL OR valid_from<=?) AND (valid_until IS NULL OR valid_until>=?) ORDER BY updated_at DESC LIMIT 1",(category,day.isoformat(),day.isoformat())).fetchone()
    if admin:return admin
    months={1:"JANUAR",2:"FEBRUAR",3:"MÄRZ",4:"APRIL",5:"MAI",6:"JUNI",7:"JULI",8:"AUGUST",9:"SEPTEMBER",10:"OKTOBER",11:"NOVEMBER",12:"DEZEMBER"}
    exact = _fact(db, "special_openings", day.isoformat())
    if exact and category == "opening_hours": return exact
    subjects=(months[day.month]+":"+day.strftime("%A"), months[day.month])
    return db.execute("SELECT * FROM structured_facts WHERE category=? AND subject IN (?,?) AND valid_from<=? AND valid_until>=? ORDER BY CASE WHEN subject=? THEN 0 ELSE 1 END LIMIT 1",
                      (category,*subjects,day.isoformat(),day.isoformat(),subjects[0])).fetchone()


def _items(db, category: str, search=None, vegetarian=False):
    doc=current_document(db,category)
    if not doc: return None,[]
    items=indexed_items(db,doc)
    if search: items=[x for x in items if search.casefold() in x["item_name"].casefold()]
    if vegetarian: items=[x for x in items if set(json.loads(x["dietary_labels"])) & {"vegetarisch","vegan"}]
    elif not search:
        _,preferred=examples(db,category)
        if preferred: items=preferred+ [x for x in items if x["id"] not in {y["id"] for y in preferred}]
    return doc,items[:20]


def execute(db, name: str, arguments: dict) -> ToolOutput:
    if name not in TOOL_MODELS: raise ValueError("Unknown tool")
    args=TOOL_MODELS[name].model_validate(arguments)
    if name in ("get_menu","get_drinks","get_vegetarian_options","get_allergen_info"):
        category="drinks" if name=="get_drinks" else "menu"
        search=getattr(args,"search",None) or (args.dish if name=="get_allergen_info" else None)
        doc,items=_items(db,category,search,name=="get_vegetarian_options" or getattr(args,"vegetarian_only",False))
        data_items=[{"name":x["item_name"],"description":x["description"],"price":x["price"],
                     "dietary_labels":json.loads(x["dietary_labels"]),"allergen_labels":json.loads(x["allergen_labels"]),
                     "page":x["page"],"confidence":x["confidence"]} for x in items]
        if search=="schnitzel" and doc and "bergschnitzel" in doc["content"].casefold() and not any("bergschnitzel" in x["name"].casefold() for x in data_items):
            data_items.insert(0,{"name":"Bergschnitzel","description":None,"price":None,"dietary_labels":[],"allergen_labels":[],"page":None,"confidence":0.6})
        if search=="schnitzel":
            order=("bergschnitzel","kinderschnitzel")
            data_items.sort(key=lambda item: next((i for i,x in enumerate(order) if x in item["name"].casefold()),len(order)))
        source=source_metadata(doc) if doc else None
        fallback=db.execute("SELECT url FROM source_links WHERE upper(label) LIKE ? ORDER BY updated_at DESC LIMIT 1",("%GETRÄNKEKARTE%" if category=="drinks" else "%SPEISEKARTE%",)).fetchone()
        url=doc["url"] if doc else fallback["url"] if fallback else None
        action={"type":"VIEW_DRINKS" if category=="drinks" else "VIEW_MENU","label":"Getränkekarte" if category=="drinks" else "Speisekarte","url":url} if url else None
        status="KNOWN" if doc and items else "PARTIAL"
        error=None if items else "NO_MATCHING_ITEMS" if doc else "NO_CURRENT_CARD"
        if name=="get_allergen_info":
            return ToolOutput(name,{"dish":args.dish,"matches":data_items,"safety_confirmed":False,"staff_confirmation_required":True},
                              status,[source] if source else [],([action] if action else [])+[{"type":"CONTACT","label":"Kontakt","url":CONTACT}],error,True)
        return ToolOutput(name,{"category":category,"document_url":url,"items":data_items},status,[source] if source else [],[action] if action else [],error)
    if name=="get_opening_hours":
        day=DateArgs.model_validate(arguments).date
        row=_hours(db,date.fromisoformat(day))
        sources=_source(row,"Öffnungszeiten")
        return ToolOutput(name,{"date":day,"hours":row["value"] if row else None},"KNOWN" if row else "PARTIAL",sources,
                          _source_action(sources,"Öffnungszeiten"),error=None if row else "NO_DATE_FACT")
    if name=="get_events":
        rows=db.execute("SELECT subject,value,source_url,retrieved_at,valid_from,valid_until,priority FROM structured_facts WHERE category='events' AND subject!='official_page' AND (? IS NULL OR valid_until IS NULL OR valid_until>=?) AND (? IS NULL OR valid_from IS NULL OR valid_from<=?) ORDER BY valid_from LIMIT 20",
                        (args.date_from,args.date_from,args.date_to,args.date_to)).fetchall()
        if args.search:
            needle=args.search.casefold()
            rows=[row for row in rows if needle in (row["subject"]+" "+row["value"]).casefold()]
        events=[{"name":x["subject"],"details":x["value"],"valid_from":x["valid_from"],"valid_until":x["valid_until"]} for x in rows]
        page=_fact(db,"events","official_page")
        return ToolOutput(name,{"events":events,"date_from":args.date_from,"date_to":args.date_to,"search":args.search},"KNOWN" if events else "PARTIAL",_source(page,"Events"),
                          [{"type":"VIEW_EVENT","label":"Events","url":"https://heuchelberg.com/events/"}],None if events else "NO_CONFIRMED_EVENT")
    if name=="get_contact_info":
        fields={r["subject"]:r["value"] for r in db.execute("SELECT * FROM structured_facts WHERE category='contact'")}
        return ToolOutput(name,fields,"KNOWN" if fields else "PARTIAL",actions=[{"type":"CONTACT","label":"Kontakt","url":CONTACT}],handoff=True)
    if name=="get_reservation_policy":
        row=_fact(db,"reservation","reservation")
        return ToolOutput(name,{"online_guest_min":1,"online_guest_max":14,"advance_days":28,"live_availability_connected":False,
                                "policy_source_value":row["value"] if row else None},"KNOWN" if row else "PARTIAL",_source(row,"Reservierung"),
                          [{"type":"RESERVE","label":"Tisch reservieren","url":BOOKING}])
    if name=="get_group_policy":
        row=_manual(db,"Gruppen ab ca 15 Personen und Sonderthemen")
        return ToolOutput(name,{"group_from_guests":15,"individual_arrangement_required":True},"KNOWN" if row else "PARTIAL",
                          [{"title":row["section"],"url":row["source_url"],"source_type":"team_rule"}] if row and row["source_url"] else [],
                          [{"type":"GROUP_REQUEST","label":"Gruppenanfrage","url":GROUP_FORM}],handoff=True)
    if name=="get_dog_policy":
        row=_manual(db,"Hausregeln Hunde")
        return ToolOutput(name,{"allowed":True if row else None,"leash_required":True if row else None},"KNOWN" if row else "PARTIAL")
    if name=="get_payment_methods":
        row=_manual(db,"Zahlungsarten")
        return ToolOutput(name,{"cash":True,"ec_card":True,"visa":True,"mastercard":True,"other_credit_cards":False} if row else {},"KNOWN" if row else "PARTIAL")
    if name=="get_parking_info":
        row=_fact(db,"parking","parking_rule") or _manual(db,"Hauptparkplatz Talstation Details")
        return ToolOutput(name,{"drive_to_venue":False,"main_parking":"foot_of_hill","walk_minutes":10,"shuttle_available":True},"KNOWN" if row else "PARTIAL",_source(row,"Parken"),
                          [{"type":"GET_DIRECTIONS","label":"Anfahrt","url":"https://heuchelberg.com/"}])
    if name=="get_directions":
        row=_fact(db,"contact","address")
        return ToolOutput(name,{"address":row["value"] if row else None,"park_at_foot_of_hill":True},"KNOWN" if row else "PARTIAL",_source(row,"Anfahrt"),
                          [{"type":"GET_DIRECTIONS","label":"Anfahrt","url":"https://heuchelberg.com/"}])
    if name=="get_accessibility_info":
        row=_manual(db,"Wanderparkplatz Alte Burg")
        sources=([{"title":"Barrierearme Anfahrt","url":row["source_url"],"source_type":"team_rule"}]
                 if row and row["source_url"] else [{"title":"Anfahrt","url":"https://heuchelberg.com/","source_type":"official_site"}])
        return ToolOutput(name,{"shuttle_from_main_parking":True,"flat_route_from":"Wanderparkplatz Alte Burg","wheelchair_suitable_route":True,"distance_km":2},"KNOWN" if row else "PARTIAL",
                          sources,[{"type":"GET_DIRECTIONS","label":"Anfahrt","url":"https://heuchelberg.com/"}])
    if name=="get_voucher_info":
        return ToolOutput(name,{"confirmed":False,"clarification_options":["restaurant","event"]},"PARTIAL",error="VOUCHER_TYPE_REQUIRED")
    if name=="get_weather_dependent_opening":
        row=_manual(db,"Garten und Biergarten Betrieb")
        sources=([{"title":"Garten","url":row["source_url"],"source_type":"team_rule"}]
                 if row and row["source_url"] else [{"title":"Heuchelberger Warte","url":"https://heuchelberg.com/","source_type":"official_site"}])
        return ToolOutput(name,{"garden_open_during_opening_hours":True,"garden_all_weather":True,"garden_self_service":True,"kitchen_may_close_early_in_bad_weather":True},"KNOWN" if row else "PARTIAL",
                          sources,_source_action(sources,"Garten & Wetter"))
    if name=="get_venue_info":
        sections={"overview":"Website allgemein","garden":"Garten und Biergarten Betrieb","children":"Bankette und größere Feiern","public_transport":"Website allgemein",
                  "shuttle":"Shuttle Fahrzeug Fahrzeit Preis","jobs":"Jobs und Karriere","brunch":"Frühstück und Brunch","overnight":"Übernachtung",
                  "smoking":"Rauchen","wedding":"Räumlichkeiten und Charakter","private_events":"Bankette und größere Feiern","corporate_events":"Events und Feiern Positionierung"}
        if args.topic=="kitchen_hours":
            row=_hours(db,date.fromisoformat(args.date),"kitchen_hours") if args.date else None
            sources=_source(row,"Küchenzeiten")
            if not sources:
                sources=[{"title":"Heuchelberger Warte","url":"https://heuchelberg.com/","source_type":"official_site"}]
            return ToolOutput(name,{"topic":args.topic,"date":args.date,"hours":row["value"] if row else None,"weather_can_close_early":True},"KNOWN" if row else "PARTIAL",sources,
                              _source_action(sources,"Küchenzeiten"),error=None if row else "DATE_OR_FACT_REQUIRED")
        row=_manual(db,sections[args.topic])
        page_category={"children":"children","wedding":"weddings","private_events":"private_events","corporate_events":"corporate_events"}.get(args.topic)
        page=db.execute("SELECT * FROM structured_facts WHERE category=? AND subject='official_page' LIMIT 1",(page_category,)).fetchone() if page_category else None
        data={"topic":args.topic,"approved_information":row["value"] if row else None}
        sources=_source(page,args.topic) if page else ([{"title":row["section"],"url":row["source_url"],"source_type":"team_rule"}] if row and row["source_url"] else [])
        if args.topic=="wedding":
            sources=[{"title":"Hochzeiten","url":"https://heuchelberg.com/hochzeit-heuchelberg-bei-heilbronn/","source_type":"official_site"}]
        if args.topic in {"overview","garden","public_transport","shuttle"}:
            sources=[{"title":"Heuchelberger Warte","url":"https://heuchelberg.com/","source_type":"official_site"}]
        actions=_source_action(sources,args.topic.replace("_"," ").title())
        return ToolOutput(name,data,"KNOWN" if row or page else "PARTIAL",sources,actions,error=None if row or page else "NO_APPROVED_FACT")
    raise ValueError("Unimplemented tool")
