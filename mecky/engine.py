import json
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .store import connect, now, stable_id
from .provider import generate, no_model_usage
from .usage import record_usage, session_usage
from .boundaries import is_off_topic, friendly_boundary
from .manual import find_manual
from .understanding import route_message, normalize
from .read_tools import (get_catalogue, get_opening_hours, get_dog_policy, get_payment_policy,
                         get_parking, get_directions, get_reservation_information)

TZ = ZoneInfo("Europe/Berlin")
INTENTS = [
 ("DOGS",r"\bhund\b|hunde|haustier"),
 ("PAYMENT",r"zahlung|bezahlen|kreditkarte|ec-karte|visa|mastercard|\bbar\b"),
 ("SMOKING",r"rauchen|zigarette"),
 ("OVERNIGHT",r"übernacht|hotel|zimmer"),
 ("BRUNCH",r"brunch|frühstück"),
 ("SHUTTLE",r"shuttle|hupfer|transferbus"),
 ("JOBS",r"job|karriere|bewerb|ausbildung"),
 ("KITCHEN_HOURS",r"küche.*(offen|zeit|bis|schließ)|bis.*küche"),
 ("OPENING_HOURS",r"öffnungs|geöffnet|\boffen\b|schließ|wann.*auf|habt ihr.*(heute|morgen|sonntag|samstag)"),
 ("MENU",r"speisekarte|essen|speisen|vegetar|vegan|gluten|gericht|menü|mittagstisch|burger|kuchen"),
 ("DRINKS",r"getränk|trinken|\bbier\b|\bwein\b|kaffee|barista"),
 ("RESERVATION",r"reserv|buchen|tisch|spontan|platz frei|verfügbar"),
 ("WEDDING",r"hochzeit|heirat|trauung"),
 ("CORPORATE_EVENT",r"firma|betrieb|team|weihnachtsfeier|tagung"),
 ("PRIVATE_EVENT",r"geburtstag|private feier|taufe|konfirmation|feiern"),
 ("RESTAURANT_VISIT",r"\b(kommen|komme|besuchen|vorbeikommen|vorbeischauen)\b|\bwir sind \d+\b|\bwir kommen\b"),
 ("PARKING",r"park|auto|hochfahren|zufahrt"),
 ("PUBLIC_TRANSPORT",r"bahn|bus|s-bahn|öffentliche verkehr"),
 ("ACCESSIBILITY",r"rollstuhl|barriere|schlecht laufen|gehbehinder|kinderwagen"),
 ("DIRECTIONS",r"anfahrt|adresse|\bweg\b|wo.*(seid|liegt)|finden"),
 ("CHILDREN",r"kinder|pony|spielplatz"),
 ("GARDEN",r"garten|draußen|terrasse|außen"),
 ("CONTACT",r"kontakt|telefon|mail|erreich"),
 ("CURRENT_EVENT",r"event|veranstaltung|programm|was ist los"),
 ("SMALLTALK",r"^(hi|hey|hallo|guten tag|danke|super|hoffentlich|wie geht|servus)[!?.\s😅]*$")]
CAT = {"KITCHEN_HOURS":"kitchen_hours","OPENING_HOURS":"opening_hours","MENU":"menu","DRINKS":"drinks","RESERVATION":"reservation","RESTAURANT_VISIT":"restaurant","WEDDING":"weddings","CORPORATE_EVENT":"corporate_events","PRIVATE_EVENT":"private_events","PARKING":"parking","PUBLIC_TRANSPORT":"public_transport","ACCESSIBILITY":"accessibility","DIRECTIONS":"directions","CHILDREN":"children","GARDEN":"garden","CONTACT":"contact","CURRENT_EVENT":"events","DOGS":"dogs","PAYMENT":"payment","SMOKING":"services","OVERNIGHT":"services","BRUNCH":"menu","SHUTTLE":"directions","JOBS":"services","VOUCHER":"services","WEATHER_RELATED":"garden"}
CONTACT = "https://heuchelberg.com/kontakt/"
BOOKING = "https://www.sevenrooms.com/explore/heuchelbergerwarte/reservations/create/search/"
GROUP_FORM = "https://8lnr26nliuj.typeform.com/to/sXrNgblN?typeform-source=heuchelberg.com"

def resolve_date(message, reference=None):
    today=(reference or datetime.now(TZ)).date()
    q=message.lower()
    if "übermorgen" in q or "day after tomorrow" in q: return today+timedelta(days=2)
    if "morgen" in q or "tomorrow" in q: return today+timedelta(days=1)
    if "heute" in q or "today" in q: return today
    if "wochenende" in q:
        delta=(5-today.weekday())%7
        if delta==0: delta=7
        return today+timedelta(days=delta)
    if "weihnachten" in q:
        from datetime import date
        year=today.year if today.month<12 or (today.month==12 and today.day<=25) else today.year+1
        return date(year,12,25)
    if "silvester" in q:
        from datetime import date
        return date(today.year if today.month<12 or today.day<=31 else today.year+1,12,31)
    if "neujahr" in q:
        from datetime import date
        year=today.year+1 if today.month>1 or today.day>1 else today.year
        return date(year,1,1)
    m=re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})?",q)
    if m:
        from datetime import date
        year=int(m[3] or today.year)
        try:
            resolved=date(year,int(m[2]),int(m[1]))
            if not m[3] and resolved<today: resolved=date(year+1,int(m[2]),int(m[1]))
            return resolved
        except ValueError: return None
    month_names={"januar":1,"februar":2,"märz":3,"maerz":3,"april":4,"mai":5,"juni":6,"juli":7,"august":8,"september":9,"oktober":10,"november":11,"dezember":12,
                 "january":1,"february":2,"march":3,"may":5,"june":6,"july":7,"october":10,"december":12}
    named=re.search(r"\b(\d{1,2})\.?\s*("+"|".join(month_names)+r")\s*(\d{4})?\b",q)
    if named:
        from datetime import date
        year=int(named[3] or today.year)
        try:
            resolved=date(year,month_names[named[2]],int(named[1]))
            if not named[3] and resolved<today: resolved=date(year+1,month_names[named[2]],int(named[1]))
            return resolved
        except ValueError: return None
    days={"montag":0,"dienstag":1,"mittwoch":2,"donnerstag":3,"freitag":4,"samstag":5,"sonntag":6,
          "monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6}
    for name,weekday in days.items():
        if name in q:
            delta=(weekday-today.weekday())%7
            if delta == 0 or "nächst" in q: delta+=7
            return today+timedelta(days=delta)
    return None

def detect_intent(message, previous=None):
    q=message.lower().strip()
    if is_off_topic(q): return "OFF_TOPIC"
    if re.fullmatch(r"(?:hallo|hi|hey|servus|guten (?:tag|morgen|abend)|danke(?: dir| schön)?|vielen dank|super|okay|alles klar|tschüss|bis bald|wie geht(?: es)?(?: dir)?)(?: mecky)?[!.?\s😊🙂🌿]*",q): return "SMALLTALK"
    # Understand colloquial needs before looking for literal knowledge-base terms.
    if re.search(r"\b(durst|durstig)\b|was (?:gibt.s|gibt es).*zu trinken",q): return "DRINKS"
    if re.search(r"\b(hunger|hungrig|futtern)\b|was habt ihr leckeres|gibt.s was zu essen",q): return "MENU"
    if (resolve_date(q) and re.search(r"\b(kommen|komme|vorbeikommen|vorbeischauen|besuchen|hochkommen)\b",q)
            and not re.search(r"reserv|tisch|hochzeit|feier|firma|betrieb|\d+\s*(leute|personen|gäste)|wir sind \d+",q)):
        return "OPENING_HOURS"
    if ("garten" in q or "draußen" in q) and "regen" in q: return "GARDEN"
    if "kindergeburtstag" in q or "wickel" in q: return "CHILDREN"
    if "biergarten" in q or "bergarten" in q: return "GARDEN"
    if any(x in q for x in ("firma","firmen","firmenfeier","firmenevent","kollegen","betriebsausflug","ausflugs-special")): return "CORPORATE_EVENT"
    if "trauerk" in q or "trauerfeier" in q: return "CONTACT"
    if "reservierungsbüro" in q and any(x in q for x in ("erreich","telefon","mail")): return "CONTACT"
    if "festsaal" in q: return "WEDDING"
    if "allergen" in q: return "MENU"
    if "ohne steigung" in q: return "ACCESSIBILITY"
    if "angebot" in q and "frage" in q: return "CONTACT"
    for intent,pat in INTENTS:
        if re.search(pat,q): return intent
    if len(q.split()) <= 4 and previous and (re.search(r"\b(und|auch|dann|dort)\b",q) or resolve_date(q)):
        return previous
    if previous and re.fullmatch(r"(?:was kostet das|wie teuer(?: ist das)?|wie viel kostet das|geht das|ist das möglich)[?.!]*",q): return previous
    if previous=="MENU" and re.search(r"\b(herzhaft|süß|suess|kuchen|warm|vegetarisch|vegan)\b",q): return "MENU"
    if previous=="DRINKS" and re.search(r"\b(alkoholfrei|kalt|warm|bier|wein)\b",q): return "DRINKS"
    if re.search(r"\b\d+\s*(leute[n]?|personen|gäste)\b|\bwir sind \d+\b",q): return "GROUP"
    return "UNKNOWN"

def repeat_answer(intent, message, context, previous_answer):
    if intent=="MENU":
        return ("Die Speisekarte habe ich dir gerade verlinkt. Suchst du eher etwas Herzhaftes oder Süßes?"
                if "Hier ist unsere Speisekarte" in previous_answer else
                "Du suchst etwas zu essen 😄 Eher was Herzhaftes oder Kaffee und Kuchen?")
    if intent=="DRINKS":
        return ("Die Getränkekarte hatte ich dir eben geschickt. Suchst du ein bestimmtes Getränk?"
                if "Hier ist unsere Getränkekarte" in previous_answer else
                "Du suchst etwas zu trinken. Eher Bier, Wein oder etwas Alkoholfreies?")
    if intent=="OPENING_HOURS":
        return ("Du meinst denselben Tag. Geht's um einen normalen Besuch oder eine Feier?"
                if previous_answer.endswith("?") else
                "Die Öffnungszeit für den Tag steht schon oben. Geht's dir auch darum, wie lange die Küche offen ist?")
    if intent=="RESERVATION":
        return ("Welchen Tag habt ihr für euren Tisch im Blick?" if context.get("party_size") else "Wie viele Gäste seid ihr denn?")
    if intent=="DOGS": return "Dein Hund darf mitkommen, mit Leine 🐕 Möchtest du noch etwas für euren Besuch wissen?"
    return "Geht's dir um einen bestimmten Teil davon?"

def same_need(intent, current, previous):
    if intent not in ("MENU","DRINKS","OPENING_HOURS","RESERVATION","DOGS"): return False
    current_date, previous_date=resolve_date(current),resolve_date(previous)
    if (current_date or previous_date) and current_date!=previous_date: return False
    current_sizes=re.findall(r"\b\d+\s*(?:leute|personen|gäste)\b|\bwir sind \d+\b",current.lower())
    previous_sizes=re.findall(r"\b\d+\s*(?:leute|personen|gäste)\b|\bwir sind \d+\b",previous.lower())
    if (current_sizes or previous_sizes) and current_sizes!=previous_sizes: return False
    if intent=="MENU" and re.search(r"vegetar|vegan|gluten|allerg|\b(preis|kostet|burger|kuchen)\b",current.lower()): return False
    if intent=="DRINKS" and re.search(r"\b(bier|wein|kaffee|preis|kostet)\b",current.lower()): return False
    return True

def staff_needed(intent, message, context):
    q=message.lower()
    if intent=="CONTACT": return True
    if intent=="RESERVATION" and (context.get("party_size",0)>14 or re.search(r"tischwunsch|bestimmte[nr]? tisch|kinderwagen|stornier|absag|ändern|umbuch|cancel|modify",q)): return True
    if intent=="MENU" and re.search(r"allerg|gluten|unverträglich",q): return True
    if intent in ("WEDDING","CORPORATE_EVENT","PRIVATE_EVENT") and re.search(r"preis|kosten|frei|termin|kapazität|angebot|individuell",q): return True
    return False

def missing_detail_question(intent, message):
    questions={
        "MENU":"Geht's dir um die Speisekarte oder darum, ob die Küche gerade noch offen hat?",
        "DRINKS":"Suchst du die Getränkekarte oder hast du etwas Bestimmtes im Kopf?",
        "OPENING_HOURS":"Für welchen Tag planst du deinen Besuch?",
        "KITCHEN_HOURS":"Für welchen Tag möchtest du die Küchenzeiten wissen?",
        "PARKING":"Kommst du mit dem Auto oder suchst du den Fußweg nach oben?",
        "DIRECTIONS":"Kommst du mit dem Auto oder mit öffentlichen Verkehrsmitteln?",
        "CURRENT_EVENT":"Für welchen Tag suchst du eine Veranstaltung?",
        "CHILDREN":"Geht's dir um etwas für Kinder oder um einen bestimmten Termin?",
        "WEDDING":"Für wann und mit ungefähr wie vielen Gästen plant ihr eure Feier?",
        "CORPORATE_EVENT":"Was für eine Firmenfeier habt ihr im Kopf?",
        "PRIVATE_EVENT":"Was für eine Feier plant ihr?",
    }
    return questions.get(intent,"Geht's dir um Essen, Öffnungszeiten oder eine Reservierung?" if intent=="UNKNOWN" else "Was genau möchtest du dazu wissen?")

def source_link(db, intent):
    if intent in ("MENU","DRINKS"):
        from .menu import current_document
        selected=current_document(db,"menu" if intent=="MENU" else "drinks")
        if selected: return {"url":selected["url"],"title":"Speisekarte" if intent=="MENU" else "Getränkekarte"}
        label="SPEISEKARTE" if intent=="MENU" else "GETRÄNKEKARTE"
        row=db.execute("SELECT url,label AS title FROM source_links WHERE document_id=? AND upper(label)=? AND url LIKE '%.pdf' ORDER BY updated_at DESC LIMIT 1",(stable_id("https://heuchelberg.com/"),label)).fetchone()
        if row: return {"url":row["url"],"title":row["title"].title()}
    patterns={
      "MENU":"%.pdf", "DRINKS":"%getraenk%.pdf", "WEDDING":"%/hochzeit-heuchelberg%",
      "CORPORATE_EVENT":"%/firmen-events-%", "PRIVATE_EVENT":"%/feine-feste-%",
      "CHILDREN":"%/kinderaktivitaeten-%", "CURRENT_EVENT":"%/events/%", "CONTACT":"%/kontakt/%"
    }
    if intent == "MENU":
        row=db.execute("SELECT url,title FROM documents WHERE category='menu' AND content_type='pdf' AND (url LIKE '%2026%' OR url LIKE '%26.pdf') ORDER BY CASE WHEN url LIKE '%Wirtshaus%' THEN 0 ELSE 1 END,url LIMIT 1").fetchone()
    elif intent in patterns:
        row=db.execute("SELECT url,title FROM documents WHERE url LIKE ? ORDER BY length(url) LIMIT 1",(patterns[intent],)).fetchone()
    else: row=None
    return {"url":row["url"],"title":row["title"]} if row else None

def retrieve(db, message, intent):
    cat=CAT.get(intent)
    tokens=[t for t in re.findall(r"[\wäöüß]+",message.lower()) if len(t)>3 and t not in ("habt","kann","euch","oder","morgen","heute","sonntag","samstag","bitte")][:5]
    expansion={"OPENING_HOURS":["öffnungszeiten","geöffnet"],"MENU":["speisekarte","speisen"],"DRINKS":["getränkekarte","getränke"],"PARKING":["parkplatz","anfahrt"],"SHUTTLE":["hupfer","shuttle"],"WEDDING":["hochzeit","heiraten"],"CHILDREN":["kinderaktivitäten","ponyreiten"]}
    tokens=list(dict.fromkeys(tokens+expansion.get(intent,[])))[:7]
    rows=[]
    if tokens:
        query=" OR ".join('"'+t.replace('"','')+'"' for t in tokens)
        try:
            rows=db.execute("SELECT d.url,d.title,d.category,c.content AS snippet,bm25(chunks_fts) score FROM chunks_fts JOIN document_chunks c ON c.rowid=chunks_fts.rowid JOIN documents d ON d.id=c.document_id WHERE chunks_fts MATCH ? ORDER BY CASE WHEN d.category=? THEN 0 ELSE 1 END,d.source_priority,score LIMIT 5",(query,cat or "other")).fetchall()
        except Exception: pass
    if not rows and cat:
        rows=db.execute("SELECT d.url,d.title,d.category,c.content AS snippet,0 score FROM documents d JOIN document_chunks c ON c.document_id=d.id WHERE d.category=? ORDER BY CASE WHEN d.content_type='html' THEN 0 ELSE 1 END LIMIT 3",(cat,)).fetchall()
    return [dict(r) for r in rows]

def current_admin(db, category, date=None):
    target=(date.isoformat() if date else datetime.now(TZ).date().isoformat())
    return db.execute("SELECT * FROM admin_knowledge WHERE active=1 AND category=? AND (valid_from IS NULL OR valid_from<=?) AND (valid_until IS NULL OR valid_until>=?) ORDER BY updated_at DESC LIMIT 1",(category,target,target)).fetchone()

def hours_fact(db, category, date):
    months={1:"JANUAR",2:"FEBRUAR",3:"MÄRZ",4:"APRIL",5:"MAI",6:"JUNI",7:"JULI",8:"AUGUST",9:"SEPTEMBER",10:"OKTOBER",11:"NOVEMBER",12:"DEZEMBER"}
    month=months[date.month]
    key=month+":"+date.strftime("%A")
    exact=db.execute("SELECT * FROM structured_facts WHERE category='special_openings' AND subject=? LIMIT 1",(date.isoformat(),)).fetchone()
    if exact and category=="opening_hours": return exact
    return db.execute("SELECT * FROM structured_facts WHERE category=? AND subject IN (?,?) AND valid_from<=? AND valid_until>=? ORDER BY CASE WHEN subject=? THEN 0 ELSE 1 END LIMIT 1",(category,key,month,date.isoformat(),date.isoformat(),key)).fetchone()

def month_requested(message):
    names={"januar":1,"februar":2,"märz":3,"april":4,"mai":5,"juni":6,"juli":7,"august":8,"september":9,"oktober":10,"november":11,"dezember":12}
    return next((number for name,number in names.items() if name in message.lower()),None)

def friendly_opening(value, date):
    days=("Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag")
    label=f"{days[date.weekday()]}, {date.strftime('%d.%m.%Y')}"
    hours=re.search(r"(\d{1,2}(?::\d{2})?) bis (\d{1,2}(?::\d{2})?) Uhr",value)
    if hours and not re.search(r"geschlossen|nur|ausnahm|außer",value,re.I):
        return f"Am {label}, sind wir von {hours[1]} bis {hours[2]} Uhr für euch da."
    return f"Für {label}, gilt bei uns: {value.rstrip('.')}."

def session(db, sid):
    row=db.execute("SELECT context,updated_at FROM sessions WHERE id=?",(sid,)).fetchone()
    if not row: return {}
    try:
        if datetime.fromisoformat(row["updated_at"]) < datetime.fromisoformat(now())-timedelta(hours=24):
            return {}
    except (ValueError,TypeError): return {}
    return json.loads(row["context"])

def redact_example(message):
    message=re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}","[email]",message)
    message=re.sub(r"\+?\d[\d\s()/-]{7,}\d","[phone]",message)
    return message[:180]

def chat(sid, message):
    start=time.monotonic()
    trace_id=stable_id(sid,start)
    db=connect()
    context=session(db,sid)
    last=(db.execute("SELECT i.intent,i.answer,m.content AS question FROM interactions i JOIN conversation_messages m ON m.session_id=i.session_id AND m.role='user' WHERE i.session_id=? ORDER BY i.id DESC,m.id DESC LIMIT 1",(sid,)).fetchone()
          if context else None)
    previous=context.get("intent")
    route=route_message(message,context)
    intent=(route.intents[0] if route.intents else
            "SMALLTALK" if route.mode=="SMALLTALK" else
            "OFF_TOPIC" if route.mode=="CASUAL_OR_OFF_TOPIC" else detect_intent(message,previous))
    all_intents=list(route.intents) if route.intents else ([] if intent in ("SMALLTALK","OFF_TOPIC","UNKNOWN") else [intent])
    locale=route.entities["locale"]
    category=CAT.get(intent,"other")
    date=resolve_date(message) if intent not in ("OFF_TOPIC","SMALLTALK","UNKNOWN") else None
    if date: context["date"]=date.isoformat()
    elif context.get("date") and intent in ("OPENING_HOURS","KITCHEN_HOURS","RESERVATION"):
        from datetime import date as date_type
        date=date_type.fromisoformat(context["date"])
    group=re.search(r"\b(\d{1,3})\s*(?:leute[n]?|personen|gäste)\b|\bwir sind\s+(\d{1,3})\b",message.lower())
    if group and intent!="OFF_TOPIC": context["party_size"]=int(group[1] or group[2])
    elif route.entities.get("party_size"): context["party_size"]=route.entities["party_size"]
    if intent not in ("UNKNOWN","OFF_TOPIC","SMALLTALK"): context["intent"]=intent
    admin=current_admin(db,category,date) if route.needs_retrieval or intent not in ("OFF_TOPIC","SMALLTALK","UNKNOWN") else None
    needs_lookup=intent not in ("OFF_TOPIC","SMALLTALK","UNKNOWN","MENU","DRINKS","DOGS","PAYMENT") and not (intent=="OPENING_HOURS" and date)
    manual=find_manual(db,message,intent) if needs_lookup else None
    sources=retrieve(db,message,intent) if needs_lookup else []
    link=source_link(db,intent) if intent not in ("OFF_TOPIC","SMALLTALK","UNKNOWN") else None
    links=[]
    status="UNKNOWN"
    answer=None
    response_sources=[]
    handoff=False
    used_tool=None
    tool_error=None
    if len(all_intents)>1 and set(all_intents).issubset({"OPENING_HOURS","DOGS","PAYMENT","MENU","DRINKS","PARKING","DIRECTIONS","RESERVATION"}):
        results=[]
        for subintent in all_intents:
            if subintent=="OPENING_HOURS": result=get_opening_hours(db,date,trace_id,locale)
            elif subintent=="DOGS": result=get_dog_policy(db,trace_id,locale)
            elif subintent=="PAYMENT": result=get_payment_policy(db,trace_id,locale)
            elif subintent=="PARKING": result=get_parking(db,trace_id,locale)
            elif subintent=="DIRECTIONS": result=get_directions(db,trace_id,locale)
            elif subintent=="RESERVATION": result=get_reservation_information(db,context.get("party_size"),trace_id,locale)
            else: result=get_catalogue(db,"menu" if subintent=="MENU" else "drinks",message,context,trace_id,locale)
            results.append(result)
        answer=" ".join(re.split(r"(?<=[.!?])\s+",x.message, maxsplit=1)[0] for x in results if x.message)
        links=list({x["url"]:x for result in results for x in result.links}.values())
        response_sources=[x for result in results for x in result.sources]
        handoff=any(result.handoff for result in results)
        status="KNOWN" if all(result.status=="KNOWN" for result in results) else "PARTIAL"
        used_tool="multi_read"
        tool_error=",".join(x.error for x in results if x.error) or None
    if answer:
        pass
    elif intent=="OFF_TOPIC":
        if is_off_topic(normalize(message)):
            answer=friendly_boundary(message) if locale=="de" else "I'll leave that topic aside. I can help with your visit to the Heuchelberger Warte."
        elif re.search(r"geschisse|geschissen",normalize(message)):
            answer="Auch wichtig 😄" if locale=="de" else "Fair enough 😄"
        elif re.search(r"müde|tired",normalize(message)):
            answer="Dann gönn dir erst mal eine Pause." if locale=="de" else "Hope you get a break soon."
        else:
            answer="Haha 😄" if locale=="de" else "Haha 😄"
        status="KNOWN"
    elif intent=="SMALLTALK":
        q=normalize(message)
        if re.search(r"wie geht|how are you",q): answer="Gut soweit 😄 Und dir?" if locale=="de" else "Doing well 😄 And you?"
        elif re.search(r"danke|thanks|thank you",q): answer="Gerne!" if locale=="de" else "You're welcome!"
        elif re.search(r"tschüss|bye",q): answer="Bis bald!" if locale=="de" else "See you!"
        else: answer="Servus 👋" if locale=="de" else "Hi 👋"
        status="KNOWN"
    elif admin and intent!="OPENING_HOURS":
        answer=admin["value"]
        status="KNOWN"
    elif intent=="OPENING_HOURS" and date and "wochenende" not in normalize(message):
        result=get_opening_hours(db,date,trace_id,locale)
        answer,status,links=result.message,result.status,result.links
        response_sources=result.sources
        used_tool="get_opening_hours"
        tool_error=result.error
        if re.search(r"\bspontan\b",normalize(message)) and status=="KNOWN":
            answer+=(" Whether a table is free depends on the booking system." if locale=="en" else
                     " Ob ein Tisch frei ist, siehst du im Buchungssystem.")
            links.append({"url":BOOKING,"title":"Book a table" if locale=="en" else "Tisch reservieren"})
    elif intent in ("MENU","DRINKS"):
        result=get_catalogue(db,"menu" if intent=="MENU" else "drinks",message,context,trace_id,locale)
        answer,status,links=result.message,result.status,result.links
        response_sources=result.sources
        handoff=result.handoff
        used_tool="get_menu" if intent=="MENU" else "get_drinks"
        tool_error=result.error
        if result.referenced_item: context["last_referenced_item"]=result.referenced_item
        context["pending_catalogue_price"]=result.error=="PRICE_ITEM_AMBIGUOUS"
    elif intent=="DOGS":
        result=get_dog_policy(db,trace_id,locale)
        answer,status,links=result.message,result.status,result.links
        response_sources=result.sources
        used_tool="get_dog_policy"
        tool_error=result.error
    elif intent=="PAYMENT":
        result=get_payment_policy(db,trace_id,locale)
        answer,status,links=result.message,result.status,result.links
        response_sources=result.sources
        used_tool="get_payment_policy"
        tool_error=result.error
    elif intent=="SMOKING" and db.execute("SELECT 1 FROM manual_knowledge WHERE section='Rauchen'").fetchone():
        answer="Rauchen ist nur im Biergarten erlaubt."
        status="KNOWN"
    elif intent=="OVERNIGHT" and db.execute("SELECT 1 FROM manual_knowledge WHERE section='Übernachtung'").fetchone():
        answer="Eine Übernachtung direkt bei uns gibt es nicht."
        status="KNOWN"
    elif intent=="BRUNCH":
        home=db.execute("SELECT content FROM documents WHERE url=?",("https://heuchelberg.com/",)).fetchone()
        if home and "Berg-Brunch" in home[0]:
            answer="Einen regulären Frühstücksbetrieb gibt es nicht. Einen Berg-Brunch könnt ihr auf Vorbestellung buchen; die Details stehen auf der offiziellen Seite."
            status="PARTIAL";links=[{"url":"https://heuchelberg.com/event/ber-brunch/","title":"Berg-Brunch"}]
    elif intent=="SHUTTLE":
        home=db.execute("SELECT content FROM documents WHERE url=?",("https://heuchelberg.com/",)).fetchone()
        if home and "Heuchelberg Hupfer" in home[0]:
            answer="Der Heuchelberg-Hupfer fährt vom Hauptparkplatz bis zum Wirtshaus. Laut Website kosten Einzelfahrten bergauf 1 €; die Talfahrt ist kostenlos."
            status="KNOWN";links=[{"url":"https://heuchelberg.com/","title":"Anfahrt und Shuttle"}]
    elif intent=="JOBS":
        answer="Jobs und Ausbildungsmöglichkeiten findest du auf unserer Karriereseite."
        status="PARTIAL";links=[{"url":"https://heuchelberg.com/karriere-heuchelberger-warte-heilbronn/","title":"Karriere"}]
    elif intent=="CHILDREN" and "kindergeburtstag" in message.lower() and db.execute("SELECT 1 FROM manual_knowledge WHERE section='Bankette und größere Feiern'").fetchone():
        answer="Schön, dass ihr an uns denkt! Kindergeburtstage sind bei uns leider nicht möglich."
        status="KNOWN"
    elif intent=="RESERVATION" and re.search(r"bestimmte[nr]? tisch|tischwunsch",message.lower()) and db.execute("SELECT 1 FROM manual_knowledge WHERE section='Tischwünsche und Kinderwagen'").fetchone():
        answer="Einen bestimmten Tisch könnt ihr leider nicht fest reservieren. Das Team vergibt die Plätze passend zur Personenzahl und Verfügbarkeit."
        status="KNOWN";links=[{"url":BOOKING,"title":"Reservieren"}]
    elif intent in ("OPENING_HOURS","KITCHEN_HOURS"):
        fact=hours_fact(db,category,date) if date else None
        opening=hours_fact(db,"opening_hours",date) if category=="kitchen_hours" and date else None
        if category=="opening_hours" and date and "wochenende" in message.lower():
            sunday=date+timedelta(days=1)
            second=hours_fact(db,"opening_hours",sunday)
            if fact and second:
                answer=f"Am Samstag {date.strftime('%d.%m.')} gilt: {fact['value']}; am Sonntag {sunday.strftime('%d.%m.')} gilt: {second['value']}."
                status="KNOWN";links=[{"url":fact["source_url"],"title":"Öffnungszeiten"}]
        elif category=="kitchen_hours" and opening and any(x in opening["value"].lower() for x in ("geschlossen","nur für veranstaltungen","nur vorbestellte")):
            answer=f"Am {date.strftime('%d.%m.%Y')} gibt es für reguläre Gäste keine bestätigte Küchenöffnungszeit; laut Website ist der Betrieb nur für vorbestellte Veranstaltungen offen."
            status="PARTIAL";links=[{"url":opening["source_url"],"title":"Öffnungszeiten"}]
        elif fact:
            if category=="kitchen_hours":
                if date.month==9:
                    if date.weekday() in (4,5): timing="bis 22 Uhr"
                    else: timing="bis 21 Uhr, ab 25 °C bis 21:30 Uhr"
                elif date.month==10:
                    timing="bis 21 Uhr" if date.weekday() in (4,5,6) else "bis 20 Uhr"
                else:
                    timing=fact["value"]
                answer=f"Am {date.strftime('%d.%m.%Y')} hat die Küche laut Website {timing} geöffnet. Bei kaltem oder schlechtem Wetter kann sie früher schließen."
            else:
                answer=friendly_opening(fact["value"],date)
            status="KNOWN";links=[{"url":fact["source_url"],"title":"Öffnungszeiten"}]
        elif not date and month_requested(message):
            requested=month_requested(message)
            current=datetime.now(TZ).date()
            year=current.year if requested>=current.month else current.year+1
            months={1:"JANUAR",2:"FEBRUAR",3:"MÄRZ",4:"APRIL",5:"MAI",6:"JUNI",7:"JULI",8:"AUGUST",9:"SEPTEMBER",10:"OKTOBER",11:"NOVEMBER",12:"DEZEMBER"}
            month=months[requested]
            if category=="kitchen_hours":
                row=db.execute("SELECT * FROM structured_facts WHERE category='kitchen_hours' AND subject=? AND valid_from LIKE ? LIMIT 1",(month,f"{year}-%")).fetchone()
                if row:
                    answer=f"Im {month.title()} gilt laut Website: {row['value'].rstrip('.')}. Bei schlechtem Wetter kann die Küche früher schließen."
                    status="KNOWN";links=[{"url":row["source_url"],"title":"Küchenzeiten"}]
            else:
                rows={x["subject"].split(":")[-1]:x for x in db.execute("SELECT * FROM structured_facts WHERE category='opening_hours' AND subject LIKE ? AND valid_from LIKE ?",(month+":%",f"{year}-%"))}
                if rows:
                    pieces=[]
                    for weekday,label in (("Sunday","sonntags"),("Saturday","samstags"),("Wednesday","mittwochs bis freitags"),("Monday","montags und dienstags")):
                        if weekday in rows: pieces.append(label+" "+rows[weekday]["value"].lower())
                    answer=f"Im {month.title()} nennt die Website: "+"; ".join(pieces)+". Sondertage können abweichen."
                    status="KNOWN";links=[{"url":"https://heuchelberg.com/","title":"Öffnungszeiten"}]
        else:
            if date:
                answer=f"Für den {date.strftime('%d.%m.%Y')} kann ich die {'Küchenzeit' if intent=='KITCHEN_HOURS' else 'Öffnung'} gerade nicht bestätigen. Geht's um einen normalen Besuch oder eine Feier?"
            else:
                answer="Für welchen Tag möchtest du die Öffnungs- oder Küchenzeiten wissen?"
                if intent=="KITCHEN_HOURS" and db.execute("SELECT 1 FROM structured_facts WHERE category='kitchen_hours' LIMIT 1").fetchone():
                    links=[{"url":"https://heuchelberg.com/","title":"Küchenzeiten"}]
            status="PARTIAL"
    elif intent=="RESERVATION":
        party=context.get("party_size")
        if re.search(r"stornier|absag|ändern|umbuch|cancel|modify",normalize(message)):
            answer=("Ändern oder stornieren kann ich eine Buchung noch nicht selbst. Schau in deine Buchungsbestätigung oder melde dich direkt beim Team." if locale=="de" else
                    "I can't change or cancel a booking here yet. Please use your confirmation link or contact the team.")
            links=[{"url":CONTACT,"title":"Kontakt" if locale=="de" else "Contact"}]
            status="PARTIAL";handoff=True;used_tool="reservation_change_unconnected";tool_error="PROVIDER_NOT_CONNECTED"
        elif date and route.entities.get("time") and re.search(r"frei|verfügbar|available|noch.*tisch|noch.*platz",normalize(message)):
            if not party:
                answer="Für wie viele Personen suchst du einen Tisch?" if locale=="de" else "For how many people?"
                status="PARTIAL"
            else:
                from .reservations import gateway
                availability=gateway.get_reservation_availability(date=date.isoformat(),party_size=party,trace_id=trace_id)
                used_tool="get_reservation_availability"
                tool_error=availability.error
                if availability.status=="SUCCESS" and availability.available_slots:
                    slots=", ".join(availability.available_slots[:3])
                    answer=(f"Für {party} Personen zeigt das Buchungssystem am {date.strftime('%d.%m.%Y')} diese freien Zeiten: {slots}." if locale=="de" else
                            f"For {party} guests on {date.strftime('%d.%m.%Y')}, the booking system shows: {slots}.")
                    status="KNOWN"
                else:
                    answer=("Freie Tische kann ich noch nicht selbst prüfen. Die aktuellen Zeiten siehst du direkt im Buchungssystem." if locale=="de" else
                            "I can't check live tables yet. The booking system shows current slots.")
                    status="PARTIAL"
                links=[{"url":BOOKING,"title":"Tisch reservieren" if locale=="de" else "Book a table"}]
        elif re.search(r"kinderwagen.*tisch|tisch.*kinderwagen",message.lower()) and db.execute("SELECT 1 FROM manual_knowledge WHERE section='Tischwünsche und Kinderwagen'").fetchone():
            answer="Ein Kinderwagen direkt am Tisch ist nur begrenzt möglich. Gebt das bitte bei eurer Anfrage an, damit das Team einen passenden Platz prüfen kann."
            links=[{"url":BOOKING,"title":"Reservieren"}]
        elif party and party>14:
            answer=(f"For {party} guests, please use the group enquiry; online table booking is for 1 to 14 guests." if locale=="en" else
                    f"Für {party} Personen klärt ihr die Reservierung am besten direkt mit dem Team; die Online-Tischreservierung ist für 1 bis 14 Gäste vorgesehen.")
            links=[{"url":GROUP_FORM,"title":"Group enquiry" if locale=="en" else "Gruppenanfrage"}]
        elif re.search(r"wie weit|wie lange.*voraus|vorlauf",message.lower()):
            answer="Tischreservierungen im Bedienbereich sind laut aktueller Website 28 Tage im Voraus möglich. Freie Zeiten seht ihr direkt im Buchungssystem."
            links=[{"url":BOOKING,"title":"Tisch reservieren"}]
        else:
            answer=((f"You can book a table online for {party} guests." if party else "You can book a table online for 1 to 14 guests.") +
                    " The booking system shows current slots." if locale=="en" else
                    (f"Für {party} Personen könnt ihr online einen Tisch reservieren." if party else "Einen Tisch könnt ihr online für 1 bis 14 Gäste reservieren.") +
                    " Freie Zeiten seht ihr direkt im Buchungssystem.")
            links=[{"url":BOOKING,"title":"Book a table" if locale=="en" else "Tisch reservieren"}]
        if status=="UNKNOWN":
            status="KNOWN" if db.execute("SELECT 1 FROM structured_facts WHERE subject='reservation'").fetchone() else "PARTIAL"
    elif intent in ("RESTAURANT_VISIT","GROUP"):
        party=context.get("party_size")
        fact=hours_fact(db,"opening_hours",date) if date else None
        if fact:
            answer=friendly_opening(fact["value"],date)
            status="KNOWN";links=[{"url":fact["source_url"],"title":"Öffnungszeiten"}]
            if party:
                answer+=f" Für {party} Personen könnt ihr euren Tisch vorab reservieren; freie Zeiten stehen im Buchungssystem."
                links.append({"url":BOOKING if party<=14 else GROUP_FORM,"title":"Reservieren" if party<=14 else "Gruppenanfrage"})
        elif party:
            answer=f"Für {party} Personen könnt ihr einen Besuch planen. Ob zu eurem Wunschtermin noch Platz ist, zeigt das Buchungssystem."
            status="PARTIAL";links=[{"url":BOOKING if party<=14 else GROUP_FORM,"title":"Reservieren" if party<=14 else "Gruppenanfrage"}]
        else:
            answer="Ihr seid gern eingeladen. Für konkrete Öffnungszeiten oder freie Plätze prüf bitte den gewünschten Tag beziehungsweise das Buchungssystem."
            status="PARTIAL";links=[{"url":"https://heuchelberg.com/","title":"Öffnungszeiten"}]
    elif intent=="PARKING":
        if re.search(r"e ladeplatz|charging point",normalize(message)):
            answer=("I can't confirm a charging point at the venue. The main car park is at the bottom of the hill." if locale=="en" else
                    "Einen E-Ladeplatz kann ich bei uns gerade nicht bestätigen. Der Hauptparkplatz liegt unten am Berg.")
            status="PARTIAL";links=[{"url":"https://heuchelberg.com/","title":"Directions and parking" if locale=="en" else "Anfahrt und Parkplätze"}]
        elif db.execute("SELECT 1 FROM structured_facts WHERE subject='parking_rule'").fetchone():
            answer=("Please park at the bottom of the hill rather than driving up to the Warte. It's about a 10-minute walk uphill, or you can take the Heuchelberg Hupfer." if locale=="en" else
                    "Bitte fahrt nicht direkt bis zur Warte hoch. Der Hauptparkplatz liegt unten am Fuß des Bergs; von dort sind es etwa 10 Minuten zu Fuß bergauf oder ihr nutzt den Heuchelberg-Hupfer.")
            status="KNOWN";links=[{"url":"https://heuchelberg.com/","title":"Directions and parking" if locale=="en" else "Anfahrt und Parkplätze"}]
    elif intent=="WEATHER_RELATED":
        home=db.execute("SELECT content FROM documents WHERE url=?",("https://heuchelberg.com/",)).fetchone()
        if home and "Unser Garten hat zu unseren Öffnungszeiten bei jedem Wetter geöffnet" in home[0]:
            answer=("The garden is open during our opening hours, even in changing weather; it's self-service." if locale=="en" else
                    "Unser Garten ist während der Öffnungszeiten bei jedem Wetter offen; dort ist Selbstbedienung.")
            status="KNOWN";links=[{"url":"https://heuchelberg.com/","title":"Garden" if locale=="en" else "Garten"}]
    elif intent=="VOUCHER":
        answer="Are you after a restaurant voucher or a gift for an event?" if locale=="en" else "Geht's dir um einen Restaurantgutschein oder ein Geschenk für eine Feier?"
        status="PARTIAL"
    elif intent=="PUBLIC_TRANSPORT":
        if any("S-Bahn Linie S4" in x["snippet"] for x in sources) or db.execute("SELECT 1 FROM documents WHERE url=? AND content LIKE '%S-Bahn Linie S4%'",("https://heuchelberg.com/",)).fetchone():
            answer="Mit der S-Bahn S4 kommt ihr nach Leingarten. Von Leingarten Mitte oder Leingarten Bahnhof dauert der Fußweg zur Warte laut Website etwa 45 Minuten."
            status="KNOWN";links=[{"url":"https://heuchelberg.com/","title":"Anfahrt"}]
    elif intent=="ACCESSIBILITY":
        home=db.execute("SELECT content FROM documents WHERE url=?",("https://heuchelberg.com/",)).fetchone()
        if home and "geeignet für Rollstuhlfahrer" in home[0]:
            answer="Wer schlecht zu Fuß ist, kann vom Hauptparkplatz den Heuchelberg-Hupfer nach oben nehmen. Der Weg vom Wanderparkplatz „Alte Burg“ ist laut Website flach und auch für Rollstuhlfahrer geeignet."
            status="PARTIAL";links=[{"url":"https://heuchelberg.com/","title":"Anfahrt"}]
    elif intent=="DIRECTIONS":
        if db.execute("SELECT 1 FROM structured_facts WHERE subject='address'").fetchone():
            answer=("You'll find us at Auf dem Heuchelberg 1, 74211 Leingarten-Heilbronn. Please use a car park at the bottom of the hill." if locale=="en" else
                    "Ihr findet uns auf dem Heuchelberg 1, 74211 Leingarten-Heilbronn. Für die Anfahrt nutzt bitte einen der Parkplätze unten am Berg.")
            status="KNOWN";links=[{"url":"https://heuchelberg.com/","title":"Directions" if locale=="en" else "Anfahrt"}]
    elif intent=="CONTACT":
        handoff=True
        if db.execute("SELECT 1 FROM structured_facts WHERE subject='email'").fetchone():
            if "whatsapp" in normalize(message):
                answer=("Mecky isn't connected to WhatsApp yet. You can reach the team at info@heuchelberg.com or 07131 401849." if locale=="en" else
                        "Mecky ist noch nicht mit WhatsApp verbunden. Das Team erreichst du per E-Mail an info@heuchelberg.com oder unter 07131 401849.")
            else:
                answer=("You can reach the team at info@heuchelberg.com or by phone at 07131 401849." if locale=="en" else
                        "Ihr erreicht unser Team per E-Mail an info@heuchelberg.com oder telefonisch unter 07131 401849.")
            status="KNOWN";links=[{"url":CONTACT,"title":"Contact" if locale=="en" else "Kontakt"}]
        else:
            answer="Here are the contact options:" if locale=="en" else "Hier findest du die Kontaktmöglichkeiten:"
            status="PARTIAL";links=[{"url":CONTACT,"title":"Contact" if locale=="en" else "Kontakt"}]
    elif intent=="GARDEN":
        home=db.execute("SELECT content FROM documents WHERE url=?",("https://heuchelberg.com/",)).fetchone()
        if home and "Unser Garten hat zu unseren Öffnungszeiten bei jedem Wetter geöffnet" in home[0]:
            if "reserv" in message.lower() and "biergarten" in message.lower():
                answer="Im Biergarten findet ihr häufig auch ohne Reservierung ein Plätzchen. Für größere Gruppen fragt bitte vorher an, damit das Team die Möglichkeiten prüfen kann."
            elif re.search(r"bis wann|wie lange|hours|open",normalize(message)) and not date:
                answer="Der Garten ist zu unseren Öffnungszeiten offen. Für welchen Tag möchtest du die genaue Zeit wissen?" if locale=="de" else "The garden is open during our opening hours. Which day are you asking about?"
            else:
                answer="Ja, im Garten könnt ihr zu den Öffnungszeiten draußen sitzen, auch bei wechselhaftem Wetter. Dort ist Selbstbedienung; einen Platz sucht ihr euch selbst."
            status="KNOWN";links=[{"url":"https://heuchelberg.com/","title":"Garten und Öffnungszeiten"}]
    elif intent=="CHILDREN" and "pony" in message.lower() and date:
        fact=db.execute("SELECT * FROM structured_facts WHERE category='events' AND subject=?",("pony:"+date.isoformat(),)).fetchone()
        if fact:
            answer=f"Für den {date.strftime('%d.%m.%Y')} nennt die aktuelle Website Ponyreiten von 13 bis 17 Uhr."
            status="KNOWN";links=[{"url":fact["source_url"],"title":"Ponyreiten"}]
        else:
            answer="Für diesen Tag finde ich gerade keinen bestätigten Ponyreit-Termin. Schau bitte in die aktuellen Hinweise oder frag das Team."
            status="UNKNOWN";links=[{"url":"https://heuchelberg.com/kinderaktivitaeten-ponyreiten-spielplatz-natur-wandern-heuchelberger-warte/","title":"Kinderaktivitäten"}]
    elif intent=="CURRENT_EVENT" and "weinprobe" in normalize(message):
        answer="Eine Weinprobe zu diesem Preis kann ich gerade nicht bestätigen. Für welchen Tag suchst du so etwas?" if locale=="de" else "I can't confirm a wine tasting at that price. Which date are you asking about?"
        status="PARTIAL";links=[{"url":"https://heuchelberg.com/events/","title":"Events"}]
    elif intent=="CURRENT_EVENT" and date:
        answer=f"Für den {date.strftime('%d.%m.%Y')} kann ich gerade keinen konkreten Event bestätigen. Die aktuellen Termine findest du auf der Eventseite."
        status="UNKNOWN";links=[{"url":"https://heuchelberg.com/events/","title":"Events"}]
    elif intent in ("WEDDING","CORPORATE_EVENT","PRIVATE_EVENT","CURRENT_EVENT","CHILDREN"):
        if link or sources:
            names={"WEDDING":"Hochzeiten","CORPORATE_EVENT":"Firmenfeiern","PRIVATE_EVENT":"private Feiern","CURRENT_EVENT":"Veranstaltungen","CHILDREN":"Angebote für Kinder","DRINKS":"Getränke"}
            if intent in ("WEDDING","CORPORATE_EVENT","PRIVATE_EVENT") and any(x in message.lower() for x in ("preis","kosten","kostet","teuer","frei","termin","kapazität","wie viele")):
                if date and context.get("party_size"):
                    answer=(f"Für {context['party_size']} Gäste am {date.strftime('%d.%m.%Y')} muss das Team Preis und Verfügbarkeit individuell prüfen." if locale=="de" else
                            f"For {context['party_size']} guests on {date.strftime('%d.%m.%Y')}, the team needs to check pricing and availability individually.")
                    handoff=True
                elif date:
                    answer="Wie viele Gäste plant ihr?" if locale=="de" else "How many guests are you planning for?"
                elif context.get("party_size"):
                    answer="Welchen Tag habt ihr im Blick?" if locale=="de" else "What date do you have in mind?"
                else:
                    answer=f"Ein konkreter Preis für {names[intent]} hängt von euren Plänen ab. Wie viele Gäste seid ihr?" if locale=="de" else "The price depends on your plans. How many guests are you expecting?"
            elif intent in ("WEDDING","CORPORATE_EVENT","PRIVATE_EVENT"):
                answer=(f"Ja, {names[intent]} können bei uns stattfinden. Für welchen Tag plant ihr?" if locale=="de" else
                        "Yes, we host that kind of celebration. What date do you have in mind?")
            elif intent=="CURRENT_EVENT":
                answer="Hier findest du die aktuellen Veranstaltungen. Suchst du einen bestimmten Tag?"
            else:
                answer="Hier findest du unsere Angebote für Kinder. Geht's dir um Ponyreiten oder den Spielplatz?"
            status="PARTIAL";links=[link] if link else [{"url":sources[0]["url"],"title":sources[0]["title"]}]
            if handoff: links.append({"url":CONTACT,"title":"Kontakt" if locale=="de" else "Contact"})
    elif manual and intent not in ("OPENING_HOURS","KITCHEN_HOURS","RESERVATION"):
        answer=manual["value"][:450]
        status="PARTIAL";links=[{"url":manual["source_url"],"title":"Mehr Informationen"}] if manual["source_url"] and manual["source_url"].startswith("https://") else []
    if not answer:
        if intent=="UNKNOWN" and re.search(r"frei|wunschtermin|verfügbar",normalize(message)):
            answer="Geht's um einen Tisch oder eine Feier?" if locale=="de" else "Is this for a table or an event?"
            status="PARTIAL"
    if not answer:
        answer=("Are you asking about food, opening hours, or a booking?" if locale=="en" and intent=="UNKNOWN" else
                "What detail would help with that?" if locale=="en" else missing_detail_question(intent,message))
        status="UNKNOWN"
    links=[item for item in links if item["url"]!=CONTACT or handoff or staff_needed(intent,message,context)]
    repeated=bool(last and last["intent"]==intent and (last["answer"]==answer or last["answer"].endswith(" "+answer))
                  and same_need(intent,message,last["question"]))
    if repeated:
        answer=repeat_answer(intent,message,context,last["answer"])
        links=[]
    response_hash=stable_id(answer)
    recent_hashes=context.get("recent_response_hashes",[])
    if response_hash in recent_hashes and intent in ("MENU","DRINKS","OPENING_HOURS","RESERVATION"):
        count=context.get("clarification_count",0)
        if intent=="MENU": answer=("Magst du lieber etwas Herzhaftes?" if count<2 else "Soll ich dir die Karte noch einmal zeigen?")
        elif intent=="DRINKS": answer=("Suchst du etwas Alkoholfreies?" if count<2 else "Soll ich dir die Getränkekarte noch einmal zeigen?")
        elif intent=="OPENING_HOURS": answer="Geht's dir um die Küche oder um das Restaurant?"
        else: answer="Für welchen Tag soll's sein?"
        links=[]
        repeated=True
    # The model may acknowledge the guest, but the sourced answer remains intact.
    # This keeps dates, prices and availability out of generated text.
    usage=no_model_usage()
    if intent not in ("OFF_TOPIC", "UNKNOWN") and status!="UNKNOWN" and (intent=="SMALLTALK" or not answer.rstrip().endswith("?")) and not repeated:
        recent=[{"role":row["role"],"content":row["content"][:300]} for row in db.execute(
            "SELECT role,content FROM conversation_messages WHERE session_id=? ORDER BY id DESC LIMIT 6",(sid,)).fetchall()][::-1]
        generated=generate(message,context,[],status,
                           verified_answer=None if intent=="SMALLTALK" else answer,
                           recent_turns=recent)
        model_answer=generated["message"]
        usage=generated["usage"]
        if model_answer and not is_off_topic(model_answer) and not re.search(
            r"\d|https?://|€|geöffnet|reservier|buch\w*|garantier|verfügbar|kosten|preis|\b(ja|nein)\b",model_answer,re.I):
            if intent=="SMALLTALK": answer=model_answer
            elif len(model_answer)<=120 and len(model_answer.split())<=18 and len(re.findall(r"[.!?](?:\s|$)",answer))<=2:
                answer=model_answer.rstrip(" .!? ")+". "+answer
    confidence={"KNOWN":0.96,"PARTIAL":0.65,"UNKNOWN":0.0}[status]
    response_type=("conversation" if intent in ("SMALLTALK","OFF_TOPIC") else
                   "clarification" if answer.rstrip().endswith("?") else
                   "factual" if status=="KNOWN" else "partial")
    show_feedback=response_type=="factual" and intent not in ("SMALLTALK","OFF_TOPIC")
    action_names={CONTACT:"CONTACT",BOOKING:"RESERVE",GROUP_FORM:"GROUP_REQUEST"}
    actions=[]
    for item in links:
        action=action_names.get(item["url"])
        if not action:
            label=normalize(item["title"]+" "+item["url"])
            action=("VIEW_DRINKS" if "getränkekarte" in label or "getraenkekarte" in label else
                    "VIEW_MENU" if "speisekarte" in label else
                    "VIEW_MENU" if intent=="MENU" and item["url"].lower().endswith(".pdf") else
                    "VIEW_DRINKS" if intent=="DRINKS" and item["url"].lower().endswith(".pdf") else
                    "VIEW_EVENT" if intent in ("CURRENT_EVENT","CHILDREN") else
                    "GET_DIRECTIONS" if intent in ("PARKING","DIRECTIONS") else "VIEW_SOURCE")
        actions.append({"type":action,"label":item["title"],"url":item["url"]})
    if not response_sources:
        response_sources=[{"title":x["title"],"url":x["url"],"source_type":"indexed_document",
                           "crawl_timestamp":None,"content_date":None,"valid_from":None,"valid_until":None,
                           "priority":None} for x in sources[:3]]
    context.setdefault("created_at",now())
    context["updated_at"]=now()
    context["locale"]=locale
    context["conversation_turns"]=context.get("conversation_turns",0)+1
    context["last_user_intent"]=intent if intent not in ("SMALLTALK","OFF_TOPIC","UNKNOWN") else context.get("last_user_intent")
    context["last_topic"]=category if intent not in ("SMALLTALK","OFF_TOPIC","UNKNOWN") else context.get("last_topic")
    context["last_entities"]={k:v for k,v in route.entities.items() if k!="locale"}
    context["last_retrieved_sources"]=[x["url"] for x in response_sources if x.get("url")][:3]
    context["pending_clarification"]=intent if response_type=="clarification" and intent not in ("UNKNOWN","OFF_TOPIC") else None
    context["pending_action"]="RESERVE" if any(x["type"]=="RESERVE" for x in actions) else None
    context["conversation_summary"]={k:context.get(k) for k in ("date","party_size","last_referenced_item","last_topic","pending_clarification","pending_action") if context.get(k) is not None}
    context["recent_response_hashes"]=(recent_hashes+[stable_id(answer)])[-5:]
    context["clarification_count"]=context.get("clarification_count",0)+1 if response_type=="clarification" else 0
    if needs_lookup and not sources:
        context["recent_failed_retrievals"]=(context.get("recent_failed_retrievals",[])+[intent])[-5:]
    elif sources:
        context["recent_failed_retrievals"]=[]
    db.execute("INSERT OR REPLACE INTO sessions VALUES(?,?,?)",(sid,json.dumps(context),now()))
    db.execute("INSERT INTO conversation_messages(session_id,role,content,created_at) VALUES(?,?,?,?)",(sid,"user",message,now()))
    db.execute("INSERT INTO conversation_messages(session_id,role,content,created_at) VALUES(?,?,?,?)",(sid,"assistant",answer,now()))
    latency=int((time.monotonic()-start)*1000)
    cursor=db.execute("INSERT INTO interactions(session_id,intent,confidence,sources,answer,latency_ms,status,created_at) VALUES(?,?,?,?,?,?,?,?)",(sid,intent,confidence,json.dumps([x["url"] for x in sources[:3]]),answer,latency,status,now()))
    iid=cursor.lastrowid
    for stage,detail in (("route",route.trace()),
                         ("retrieval",{"gate":needs_lookup,"indexed_hits":len(sources),"tool":used_tool,"tool_error":tool_error,"trace_id":trace_id}),
                         ("response",{"type":response_type,"status":status,"actions":[x["type"] for x in actions],"handoff":handoff,"repeated":repeated})):
        db.execute("INSERT INTO decision_events(interaction_id,session_id,stage,detail,created_at) VALUES(?,?,?,?,?)",
                   (iid,sid,stage,json.dumps(detail,ensure_ascii=False),now()))
    record_usage(db,sid,iid,usage)
    totals=session_usage(db,sid)
    if status=="UNKNOWN":
        safe=redact_example(message)
        topic=re.sub(r"\s+"," ",safe.lower().strip())[:80]
        gid=stable_id(topic)
        old=db.execute("SELECT occurrences,example_questions FROM knowledge_gaps WHERE id=?",(gid,)).fetchone()
        examples=json.loads(old[1]) if old else []
        if safe not in examples: examples=(examples+[safe])[-5:]
        db.execute("INSERT OR REPLACE INTO knowledge_gaps VALUES(?,?,?,?,?,?)",(gid,topic,(old[0]+1 if old else 1),json.dumps(examples),"needs_admin_answer",now()))
    db.commit();db.close()
    return {"session_id":sid,"message":answer,"links":links,"confidence":confidence,"intent":intent,
            "intents":all_intents,"status":status,"response_type":response_type,"actions":actions,
            "show_feedback":show_feedback,"sources":response_sources,"handoff":handoff,
            "interaction_id":iid,"usage":usage,"session_usage":totals,"latency_ms":latency}
