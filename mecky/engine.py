import json
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .store import connect, now, stable_id
from .provider import generate
from .manual import find_manual

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
 ("MENU",r"speisekarte|essen|speisen|vegetar|vegan|gluten|gericht|menü|mittagstisch|burger"),
 ("DRINKS",r"getränk|trinken|\bbier\b|\bwein\b|kaffee|barista"),
 ("RESERVATION",r"reserv|buchen|tisch|spontan|platz frei|verfügbar"),
 ("RESTAURANT_VISIT",r"\bkommen\b|\bbesuchen\b|\bvorbeikommen\b|\bwir sind \d+\b|\bwir kommen\b"),
 ("WEDDING",r"hochzeit|heirat|trauung"),
 ("CORPORATE_EVENT",r"firma|betrieb|team|weihnachtsfeier|tagung"),
 ("PRIVATE_EVENT",r"geburtstag|private feier|taufe|konfirmation|feiern"),
 ("PARKING",r"park|auto|hochfahren|zufahrt"),
 ("PUBLIC_TRANSPORT",r"bahn|bus|s-bahn|öffentliche verkehr"),
 ("ACCESSIBILITY",r"rollstuhl|barriere|schlecht laufen|gehbehinder|kinderwagen"),
 ("DIRECTIONS",r"anfahrt|adresse|\bweg\b|wo.*(seid|liegt)|finden"),
 ("CHILDREN",r"kinder|pony|spielplatz"),
 ("GARDEN",r"garten|draußen|terrasse|außen"),
 ("CONTACT",r"kontakt|telefon|mail|erreich"),
 ("CURRENT_EVENT",r"event|veranstaltung|programm|was ist los"),
 ("SMALLTALK",r"^(hi|hey|hallo|guten tag|danke|super|hoffentlich|wie geht|servus)[!?.\s😅]*$")]
CAT = {"KITCHEN_HOURS":"kitchen_hours","OPENING_HOURS":"opening_hours","MENU":"menu","DRINKS":"drinks","RESERVATION":"reservation","RESTAURANT_VISIT":"restaurant","WEDDING":"weddings","CORPORATE_EVENT":"corporate_events","PRIVATE_EVENT":"private_events","PARKING":"parking","PUBLIC_TRANSPORT":"public_transport","ACCESSIBILITY":"accessibility","DIRECTIONS":"directions","CHILDREN":"children","GARDEN":"garden","CONTACT":"contact","CURRENT_EVENT":"events","DOGS":"dogs","PAYMENT":"payment","SMOKING":"services","OVERNIGHT":"services","BRUNCH":"menu","SHUTTLE":"directions","JOBS":"services"}
CONTACT = "https://heuchelberg.com/kontakt/"
BOOKING = "https://www.sevenrooms.com/explore/heuchelbergerwarte/reservations/create/search/"
GROUP_FORM = "https://8lnr26nliuj.typeform.com/to/sXrNgblN?typeform-source=heuchelberg.com"

def resolve_date(message, reference=None):
    today=(reference or datetime.now(TZ)).date()
    q=message.lower()
    if "übermorgen" in q: return today+timedelta(days=2)
    if "morgen" in q: return today+timedelta(days=1)
    if "heute" in q: return today
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
        try: return date(year,int(m[2]),int(m[1]))
        except ValueError: return None
    days={"montag":0,"dienstag":1,"mittwoch":2,"donnerstag":3,"freitag":4,"samstag":5,"sonntag":6}
    for name,weekday in days.items():
        if name in q:
            delta=(weekday-today.weekday())%7
            if delta == 0 or "nächst" in q: delta+=7
            return today+timedelta(days=delta)
    return None

def detect_intent(message, previous=None):
    q=message.lower().strip()
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
    if re.search(r"\b\d+\s*(leute[n]?|personen|gäste)\b|\bwir sind \d+\b",q): return "GROUP"
    return "UNKNOWN"

def source_link(db, intent):
    if intent in ("MENU","DRINKS"):
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
    expansion={"OPENING_HOURS":["öffnungszeiten","geöffnet"],"MENU":["speisekarte","speisen"],"PARKING":["parkplatz","anfahrt"],"SHUTTLE":["hupfer","shuttle"],"WEDDING":["hochzeit","heiraten"],"CHILDREN":["kinderaktivitäten","ponyreiten"]}
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
    db=connect()
    context=session(db,sid)
    previous=context.get("intent")
    intent=detect_intent(message,previous)
    if intent=="UNKNOWN" and previous and len(message.split())<=4:
        intent=previous
    category=CAT.get(intent,"other")
    date=resolve_date(message)
    if date: context["date"]=date.isoformat()
    elif context.get("date") and intent in ("OPENING_HOURS","KITCHEN_HOURS","RESERVATION"):
        from datetime import date as date_type
        date=date_type.fromisoformat(context["date"])
    group=re.search(r"\b(\d{1,3})\s*(?:leute[n]?|personen|gäste)\b|\bwir sind\s+(\d{1,3})\b",message.lower())
    if group: context["party_size"]=int(group[1] or group[2])
    if intent!="UNKNOWN": context["intent"]=intent
    admin=current_admin(db,category,date)
    manual=find_manual(db,message,intent)
    sources=retrieve(db,message,intent)
    link=source_link(db,intent)
    links=[]
    status="UNKNOWN"
    answer=None
    if admin:
        answer=admin["value"]
        status="KNOWN"
    elif intent=="DOGS" and db.execute("SELECT 1 FROM manual_knowledge WHERE section='Hausregeln Hunde'").fetchone():
        answer="Ja, Hunde sind willkommen. Bitte nehmt sie an die Leine."
        status="KNOWN";links=[{"url":CONTACT,"title":"Bei Fragen: Kontakt"}]
    elif intent=="PAYMENT" and db.execute("SELECT 1 FROM manual_knowledge WHERE section='Zahlungsarten'").fetchone():
        answer="Ihr könnt bar oder mit EC-Karte zahlen. Bei Kreditkarten sind Visa und Mastercard möglich."
        status="KNOWN";links=[{"url":CONTACT,"title":"Kontakt"}]
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
        answer="Kindergeburtstage sind bei uns laut den Team-Informationen nicht möglich."
        status="KNOWN";links=[{"url":CONTACT,"title":"Kontakt"}]
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
                answer=f"Am {date.strftime('%d.%m.%Y')} gilt laut aktueller Website: {fact['value'].rstrip('.')}."
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
            answer="Dazu finde ich gerade keine eindeutige aktuelle Zeitangabe. Frag am besten kurz direkt beim Team nach."
            links=[{"url":CONTACT,"title":"Kontakt"}]
    elif intent=="RESERVATION":
        party=context.get("party_size")
        if re.search(r"kinderwagen.*tisch|tisch.*kinderwagen",message.lower()) and db.execute("SELECT 1 FROM manual_knowledge WHERE section='Tischwünsche und Kinderwagen'").fetchone():
            answer="Ein Kinderwagen direkt am Tisch ist nur begrenzt möglich. Gebt das bitte bei eurer Anfrage an, damit das Team einen passenden Platz prüfen kann."
            links=[{"url":BOOKING,"title":"Reservieren"}]
        elif party and party>14:
            answer=f"Für {party} Personen klärt ihr die Reservierung am besten direkt mit dem Team; die Online-Tischreservierung ist für 1 bis 14 Gäste vorgesehen."
            links=[{"url":GROUP_FORM,"title":"Gruppenanfrage"},{"url":CONTACT,"title":"Kontakt"}]
        elif re.search(r"wie weit|wie lange.*voraus|vorlauf",message.lower()):
            answer="Tischreservierungen im Bedienbereich sind laut aktueller Website 28 Tage im Voraus möglich. Freie Zeiten seht ihr direkt im Buchungssystem."
            links=[{"url":BOOKING,"title":"Tisch reservieren"}]
        else:
            answer=(f"Für {party} Personen könnt ihr online einen Tisch reservieren." if party else "Einen Tisch könnt ihr online für 1 bis 14 Gäste reservieren.") + " Freie Zeiten seht ihr direkt im Buchungssystem."
            links=[{"url":BOOKING,"title":"Tisch reservieren"}]
        status="KNOWN" if db.execute("SELECT 1 FROM structured_facts WHERE subject='reservation'").fetchone() else "PARTIAL"
    elif intent in ("RESTAURANT_VISIT","GROUP"):
        party=context.get("party_size")
        fact=hours_fact(db,"opening_hours",date) if date else None
        if fact:
            answer=f"Am {date.strftime('%d.%m.%Y')} gilt laut Website: {fact['value'].rstrip('.')}."
            status="KNOWN";links=[{"url":fact["source_url"],"title":"Öffnungszeiten"}]
            if party:
                answer+=f" Für {party} Personen könnt ihr euren Tisch vorab reservieren; freie Zeiten stehen im Buchungssystem."
                links.append({"url":BOOKING if party<=14 else GROUP_FORM,"title":"Reservieren" if party<=14 else "Gruppenanfrage"})
        elif party:
            answer=f"Für {party} Personen könnt ihr einen Besuch planen. Ob zu eurem Wunschtermin noch Platz ist, zeigt das Buchungssystem."
            status="PARTIAL";links=[{"url":BOOKING if party<=14 else CONTACT,"title":"Reservieren" if party<=14 else "Gruppenanfrage"}]
        else:
            answer="Ihr seid gern eingeladen. Für konkrete Öffnungszeiten oder freie Plätze prüf bitte den gewünschten Tag beziehungsweise das Buchungssystem."
            status="PARTIAL";links=[{"url":"https://heuchelberg.com/","title":"Öffnungszeiten"}]
    elif intent=="PARKING":
        if db.execute("SELECT 1 FROM structured_facts WHERE subject='parking_rule'").fetchone():
            answer="Bitte fahrt nicht direkt bis zur Warte hoch. Der Hauptparkplatz liegt unten am Fuß des Bergs; von dort sind es etwa 10 Minuten zu Fuß bergauf oder ihr nutzt den Heuchelberg-Hupfer."
            status="KNOWN";links=[{"url":"https://heuchelberg.com/","title":"Anfahrt und Parkplätze"}]
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
            answer="Ihr findet uns auf dem Heuchelberg 1, 74211 Leingarten-Heilbronn. Für die Anfahrt nutzt bitte einen der Parkplätze unten am Berg."
            status="KNOWN";links=[{"url":"https://heuchelberg.com/","title":"Anfahrt"}]
    elif intent=="CONTACT":
        if db.execute("SELECT 1 FROM structured_facts WHERE subject='email'").fetchone():
            answer="Das Team erreicht ihr per E-Mail an info@heuchelberg.com oder telefonisch unter 07131 401849."
            status="KNOWN";links=[{"url":CONTACT,"title":"Kontakt"}]
    elif intent=="MENU":
        if "gluten" in message.lower() and db.execute("SELECT 1 FROM manual_knowledge WHERE section='Glutenfrei'").fetchone():
            answer="Ja, laut den Team-Informationen gibt es glutenfreie Gerichte auf der Karte. Für Allergien oder besondere Anforderungen frag bitte sicherheitshalber direkt beim Team nach."
            status="PARTIAL";links=([link] if link else []) + [{"url":CONTACT,"title":"Kontakt"}]
        elif link:
            answer="Die aktuelle Karte kannst du direkt ansehen. Für einzelne Gerichte oder Allergene prüf bitte die Karte oder frag das Team, falls du eine sichere Auskunft brauchst."
            status="PARTIAL";links=[link]
    elif intent=="GARDEN":
        home=db.execute("SELECT content FROM documents WHERE url=?",("https://heuchelberg.com/",)).fetchone()
        if home and "Unser Garten hat zu unseren Öffnungszeiten bei jedem Wetter geöffnet" in home[0]:
            if "reserv" in message.lower() and "biergarten" in message.lower():
                answer="Im Biergarten findet ihr häufig auch ohne Reservierung ein Plätzchen. Für größere Gruppen fragt bitte vorher an, damit das Team die Möglichkeiten prüfen kann."
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
    elif intent=="DRINKS" and link and any(x in message.lower() for x in ("getränkekarte","karte","zeigen","zeig")):
        answer="Die Getränkekarte kannst du hier direkt ansehen."
        status="KNOWN";links=[link]
    elif intent=="CURRENT_EVENT" and date:
        answer=f"Für den {date.strftime('%d.%m.%Y')} kann ich gerade keinen konkreten Event bestätigen. Die aktuellen Termine findest du auf der Eventseite."
        status="UNKNOWN";links=[{"url":"https://heuchelberg.com/events/","title":"Events"}]
    elif intent in ("WEDDING","CORPORATE_EVENT","PRIVATE_EVENT","CURRENT_EVENT","CHILDREN","DRINKS"):
        if link or sources:
            names={"WEDDING":"Hochzeiten","CORPORATE_EVENT":"Firmenfeiern","PRIVATE_EVENT":"private Feiern","CURRENT_EVENT":"Veranstaltungen","CHILDREN":"Angebote für Kinder","DRINKS":"Getränke"}
            if intent in ("WEDDING","CORPORATE_EVENT","PRIVATE_EVENT") and not any(x in message.lower() for x in ("preis","kosten","kostet","teuer","frei","termin","kapazität","wie viele")):
                answer=f"Ja, {names[intent]} können bei uns stattfinden. Für eure Vorstellungen und einen passenden Termin hilft euch das Team gern weiter."
            else:
                answer=f"Zu {names[intent]} gibt es Informationen auf der offiziellen Seite. Einen konkreten Termin, Preis oder freie Plätze kann ich gerade nicht bestätigen; frag dafür bitte direkt beim Team nach."
            status="PARTIAL";links=[link] if link else [{"url":sources[0]["url"],"title":sources[0]["title"]}]
    elif manual and intent not in ("OPENING_HOURS","KITCHEN_HOURS","RESERVATION"):
        answer=manual["value"][:450]
        status="PARTIAL";links=[{"url":manual["source_url"],"title":"Mehr Informationen"}] if manual["source_url"] and manual["source_url"].startswith("https://") else [{"url":CONTACT,"title":"Kontakt"}]
    elif intent=="SMALLTALK":
        answer="Hallo! Schön, dass du da bist. Was möchtest du über die Heuchelberger Warte wissen?" if re.search(r"hi|hey|hallo|guten tag|servus",message.lower()) else "Gern! Wenn du noch etwas wissen möchtest, schreib einfach."
        status="KNOWN"
    if not answer:
        answer="Dazu finde ich gerade keine eindeutige Info auf der offiziellen Seite. Am besten fragst du kurz direkt beim Team nach."
        links=[{"url":CONTACT,"title":"Kontakt"}]
        status="UNKNOWN"
    # Only free-form smalltalk uses an optional model. Operational claims keep
    # their deterministic, source-grounded answer even when a model is set.
    if intent=="SMALLTALK":
        model_answer=generate(message,context,[],status)
        if model_answer and not re.search(r"\d|https?://|€|geöffnet|reservier",model_answer,re.I):
            answer=model_answer
    confidence={"KNOWN":0.96,"PARTIAL":0.65,"UNKNOWN":0.0}[status]
    db.execute("INSERT OR REPLACE INTO sessions VALUES(?,?,?)",(sid,json.dumps(context),now()))
    db.execute("INSERT INTO conversation_messages(session_id,role,content,created_at) VALUES(?,?,?,?)",(sid,"user",message,now()))
    db.execute("INSERT INTO conversation_messages(session_id,role,content,created_at) VALUES(?,?,?,?)",(sid,"assistant",answer,now()))
    latency=int((time.monotonic()-start)*1000)
    cursor=db.execute("INSERT INTO interactions(session_id,intent,confidence,sources,answer,latency_ms,status,created_at) VALUES(?,?,?,?,?,?,?,?)",(sid,intent,confidence,json.dumps([x["url"] for x in sources[:3]]),answer,latency,status,now()))
    iid=cursor.lastrowid
    if status=="UNKNOWN":
        safe=redact_example(message)
        topic=re.sub(r"\s+"," ",safe.lower().strip())[:80]
        gid=stable_id(topic)
        old=db.execute("SELECT occurrences,example_questions FROM knowledge_gaps WHERE id=?",(gid,)).fetchone()
        examples=json.loads(old[1]) if old else []
        if safe not in examples: examples=(examples+[safe])[-5:]
        db.execute("INSERT OR REPLACE INTO knowledge_gaps VALUES(?,?,?,?,?,?)",(gid,topic,(old[0]+1 if old else 1),json.dumps(examples),"needs_admin_answer",now()))
    db.commit();db.close()
    return {"session_id":sid,"message":answer,"links":links,"confidence":confidence,"intent":intent,"status":status,"interaction_id":iid}
