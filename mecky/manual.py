import re
from pathlib import Path
from .store import connect, now, stable_id

RAG=Path("heuchelberger-warte-rag.md")
CONFLICTS={
    "Reservierungsrichtlinien kurz":"Website nennt aktuell 28 Tage im Voraus; die Drei-Wochen-Angabe gilt nur als unverbindlicher Richtwert und wird nicht als feste Regel ausgegeben.",
    "Frühstück und Brunch":"Website bietet Berg-Brunch auf Vorbestellung an; nur kein reguläres Frühstück behaupten.",
    "Reservierungszeiten Richtwerte Mo bis Do":"Saisonale Öffnungszeiten widersprechen pauschalen Mo-Do-Zeiten; konkrete Verfügbarkeit nur im Buchungssystem.",
    "Reservierungszeiten Richtwerte August":"August-Angaben ohne Jahresbezug nicht als aktuelle Slots ausgeben.",
    "Reservierungszeiten Mittwoch Live Musik":"Live-Musik-Termin nicht aktuell bestätigt.",
    "Reservierungszeiten Freitag":"Richtwerte keine aktuelle Verfügbarkeit.",
    "Reservierungszeiten Samstag":"Richtwerte keine aktuelle Verfügbarkeit.",
    "Reservierungszeiten Sonntag":"Richtwerte keine aktuelle Verfügbarkeit.",
}

def category(title):
    t=title.lower()
    for term,cat in (("reserv","reservation"),("gruppe","groups"),("park","parking"),("anfahrt","directions"),("shuttle","directions"),("garten","garden"),("biergarten","garden"),("hund","dogs"),("zahlung","payment"),("gluten","menu"),("brunch","menu"),("frühstück","menu"),("küche","restaurant"),("bio","restaurant"),("rauch","services"),("übernacht","services"),("kinder","children"),("trau","private_events"),("beschwerde","contact"),("jobs","services"),("hochzeit","weddings"),("event","events")):
        if term in t:return cat
    return "other"

def import_rag():
    text=RAG.read_text(encoding="utf-8").replace("\\#","#").replace("\\*","*").replace("\\+","+").replace("\\!","!")
    parts=re.split(r"(?m)^##\s+",text)
    db=connect()
    count=0
    for part in parts[1:]:
        title,_,body=part.partition("\n")
        keyword=re.search(r"(?im)^Keywords:\s*(.+)$",body)
        value=re.sub(r"(?im)^Keywords:.*$","",body).strip()
        value=re.sub(r"\s+"," ",value).replace("**","")
        links=re.findall(r"https?://[^\s]+",value)
        url=links[0] if links else None
        value=re.sub(r"https?://[^\s]+","",value).strip()
        if not value: continue
        title=title.strip()
        db.execute("INSERT OR REPLACE INTO manual_knowledge VALUES(?,?,?,?,?,?,?,?)",(stable_id("manual",title),title,category(title),value,keyword.group(1).strip().lower() if keyword else "",url,CONFLICTS.get(title),now()))
        count+=1
    db.commit();db.close()
    return count

def find_manual(db,message,intent):
    q=message.lower()
    rows=db.execute("SELECT * FROM manual_knowledge").fetchall()
    scored=[]
    terms=set(re.findall(r"[\wäöüß]+",q))
    for row in rows:
        if row["conflict_note"]: continue
        keys={x.strip() for x in row["keywords"].split(",") if x.strip()}
        overlap=sum(2 if k in q and len(k)>4 else 1 for k in keys if k in terms or (len(k)>4 and k in q))
        if overlap:
            scored.append((overlap,row))
    scored.sort(key=lambda x:x[0],reverse=True)
    return scored[0][1] if scored and scored[0][0]>=2 else None
