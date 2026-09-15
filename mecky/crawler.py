import hashlib
import io
import logging
import re
import xml.etree.ElementTree as ET
from urllib import robotparser
from collections import deque
from urllib.parse import urljoin, urlparse, urldefrag

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from .store import connect, now, stable_id, upsert_document, save_fact

log = logging.getLogger(__name__)
BASE = "https://heuchelberg.com/"
DOMAIN = "heuchelberg.com"
MAX_PAGES = 90
MAX_BYTES = 25_000_000
SKIP = ("/wp-admin/", "/feed/", "/tag/", "/author/", "/wp-json/", "/?", "/impressum", "/datenschutz")
ASSETS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".css", ".js", ".zip", ".mp4")
MAP = {
    "hochzeit":"weddings", "heirat":"weddings", "firmenevent":"corporate_events", "firmen-event":"corporate_events",
    "private-feier":"private_events", "event":"events", "mittagstisch":"menu", "speise":"menu",
    "getraenk":"drinks", "getränk":"drinks", "kinder":"children", "kontakt":"contact", "karte":"menu", "burger":"menu", "specials":"menu",
    "restaurant":"restaurant", "garten":"garden", "anfahrt":"directions", "reserv":"reservation",
    "fackel":"events", "wandern":"directions", "barista":"drinks"
}

def category(url, title=""):
    value = (url + " " + title).lower()
    if url == BASE: return "other"
    for term, cat in MAP.items():
        if term in value:
            return cat
    return "other"

def allowed(url):
    p = urlparse(url)
    if p.path.lower().endswith(".pdf") and any(f"/{y}/" in p.path for y in (2023,2024,2025)):
        return False
    return p.scheme == "https" and p.hostname in (DOMAIN, "www." + DOMAIN) and not any(s in p.path.lower() for s in SKIP) and not p.path.lower().endswith(ASSETS)

def normalize(url):
    url = urldefrag(url)[0]
    p = urlparse(url)
    return p._replace(query="", fragment="").geturl().rstrip("/") + ("/" if not p.path.lower().endswith(".pdf") else "")

def sitemap_urls(client):
    urls = []
    queue = [urljoin(BASE, "sitemap.xml")]
    seen = set()
    while queue and len(urls) < 200:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            r = client.get(url)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            locs = [x.text.strip() for x in root.iter() if x.tag.endswith("loc") and x.text]
            if root.tag.endswith("sitemapindex"):
                queue.extend(x for x in locs if any(y in x for y in ("page-sitemap", "post-sitemap", "event-sitemap")))
            else:
                urls.extend(x for x in locs if allowed(x))
        except Exception as exc:
            log.warning("Sitemap %s: %s", url, exc)
    return urls

def parse_html(content, url):
    soup = BeautifulSoup(content, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else url
    canonical = soup.find("link", rel="canonical")
    canonical_url = canonical.get("href", url) if canonical else url
    links = []
    for a in soup.find_all("a", href=True):
        target = normalize(urljoin(url, a["href"]))
        if allowed(target):
            links.append((target,a.get_text(" ",strip=True)[:120]))
    for tag in soup(["script", "style", "noscript", "svg", "form"]):
        tag.decompose()
    # Some operational information lives in the site's booking/opening overlay,
    # so include the visible body, including its panels.
    body = soup.body or soup
    lines = [re.sub(r"\s+", " ", x).strip() for x in body.stripped_strings]
    lines = [x for x in lines if x and len(x) > 2]
    dedup = []
    for x in lines:
        if not dedup or x != dedup[-1]:
            dedup.append(x)
    return title, canonical_url, "\n".join(dedup), links

def parse_pdf(content):
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages[:30])

def extract_facts(db, doc):
    text = doc["content"]
    url = doc["url"]
    did = doc["id"]
    if url == BASE:
        for subject, pattern in {
            "address": r"Auf dem Heuchelberg 1\s*\n74211 Leingarten-Heilbronn",
            "email": r"info@heuchelberg\.com",
            "phone": r"(?:0\s*71\s*31\s*[–-]\s*40\s*18\s*49)",
            "parking_rule": r"Bitte fahrt nicht direkt nach oben!.*?Bußgeld von 55€.*?Leingarten\.",
            "reservation": r"Reserviere online einen Tisch für 1-14 Gäste.*?28 Tage im Voraus möglich\.",
            "garden": r"Unser Garten hat zu unseren Öffnungszeiten bei jedem Wetter geöffnet\..*?selbst bedienen\."
        }.items():
            m = re.search(pattern, text, re.I | re.S)
            if m:
                cat = "contact" if subject in ("address","email","phone") else ("parking" if subject == "parking_rule" else subject)
                save_fact(db,cat,subject,re.sub(r"\s+"," ",m.group(0)),url,did)
        extract_opening_facts(db, text, url, did)
    if doc["category"] != "other":
        # Document text remains retrievable; do not turn a whole page into an
        # unconditional operational fact.
        save_fact(db,doc["category"],"official_page",doc["title"],url,did)

def extract_opening_facts(db, text, url, did):
    # The homepage currently publishes a seasonal calendar for Sep 2026-Jan 2027.
    # Only records whose literal wording is found are accepted.
    blocks = {}
    for month, next_month in (("SEPTEMBER","OKTOBER"),("OKTOBER","NOVEMBER"),("NOVEMBER","DEZEMBER"),("DEZEMBER","JANUAR"),("JANUAR","Reservieren")):
        start = text.find("\n" + month + "\n", text.find("\nÖFFNUNGSZEITEN\n"))
        if start < 0:
            continue
        end = text.find("\n" + next_month + "\n", start + len(month) + 2)
        blocks[month] = text[start:end if end > start else start + 2200]
    for month, number, year in (("SEPTEMBER",9,2026),("OKTOBER",10,2026),("NOVEMBER",11,2026),("DEZEMBER",12,2026),("JANUAR",1,2027)):
        block = blocks.get(month, "")
        valid_from = f"{year}-{number:02d}-01"
        valid_until = f"{year}-{number:02d}-31"
        patterns = {
            "Sunday":r"(?:Sonn- & Feiertags|Sonntags) 11 bis 23 Uhr geöffnet",
            "Saturday":r"Samstags? 12 bis 23 Uhr geöffnet",
            "Wednesday":r"Mittwoch, Donnertag & Freitag 12 bis 22 Uhr geöffnet",
            "Thursday":r"Mittwoch, Donnertag & Freitag 12 bis 22 Uhr geöffnet",
            "Friday":r"Mittwoch, Donnertag & Freitag 12 bis 22 Uhr geöffnet"
        }
        for weekday, pattern in patterns.items():
            m = re.search(pattern,block,re.I)
            if m:
                save_fact(db,"opening_hours",f"{month}:{weekday}",m.group(0),url,did,valid_from,valid_until)
        if re.search(r"Mo & Di nur für Veranstaltungen.*Vorbestellung geöffnet",block,re.I):
            for weekday in ("Monday","Tuesday"):
                save_fact(db,"opening_hours",f"{month}:{weekday}","Mo & Di nur für Veranstaltungen & Events auf Vorbestellung geöffnet",url,did,valid_from,valid_until)
        elif re.search(r"Montag bis (?:Donnerstag|Samstag|Freitag).*?Geschlossen",block,re.I|re.S):
            for weekday in ("Monday","Tuesday","Wednesday","Thursday","Friday"):
                save_fact(db,"opening_hours",f"{month}:{weekday}","Für reguläre Gäste geschlossen; Feiern & Events auf Anfrage",url,did,valid_from,valid_until)
        kitchen = re.search(r"Unsere Küche hat an allen Öffnungstagen.*?geöffnet",block,re.I)
        if kitchen:
            save_fact(db,"kitchen_hours",month,kitchen.group(0),url,did,valid_from,valid_until,["schlechtes Wetter: eventuell vorzeitig geschlossen"])
    if "PONYREITEN FÜR KINDER SO 13.09./20.09./27.09. 13 bis 17 UHR" in blocks.get("SEPTEMBER", ""):
        for day in (13,20,27):
            date=f"2026-09-{day:02d}"
            save_fact(db,"events","pony:"+date,"Ponyreiten 13 bis 17 Uhr",url,did,date,date)
    if "PONYREITEN FÜR KINDER JEDEN SO 13 bis 17 UHR" in blocks.get("OKTOBER", ""):
        for day in (4,11,18,25):
            date=f"2026-10-{day:02d}"
            save_fact(db,"events","pony:"+date,"Ponyreiten 13 bis 17 Uhr",url,did,date,date)
    # Explicit exceptions take precedence over weekday rules.
    for day in ("2026-11-20","2026-11-21","2026-11-27","2026-11-28"):
        if day[-2:] + ".11." in blocks.get("NOVEMBER", ""):
            save_fact(db,"special_openings",day,"Für reguläre Gäste geschlossen; nur vorbestellte Feiern & Events",url,did,day,day,priority=3)
    for day in (7,14):
        if f"{day:02d}.11." in blocks.get("NOVEMBER", ""):
            date=f"2026-11-{day:02d}"
            save_fact(db,"special_openings",date,"12 bis 23 Uhr geöffnet",url,did,date,date,priority=3)
    for day in (6,13):
        if f"{day:02d}.11." in blocks.get("NOVEMBER", ""):
            date=f"2026-11-{day:02d}"
            save_fact(db,"special_openings",date,"Kaminabend ab 18 Uhr",url,did,date,date,priority=3)
    for day in range(23,27):
        if "23.12. bis 26.12. geschlossen" in blocks.get("DEZEMBER", ""):
            date=f"2026-12-{day:02d}"
            save_fact(db,"special_openings",date,"Geschlossen",url,did,date,date,priority=3)
    if "27.12. bis 30.12." in blocks.get("DEZEMBER", ""):
        for day in range(27,31):
            date=f"2026-12-{day:02d}"
            save_fact(db,"special_openings",date,"Ab 12 Uhr geöffnet; Sonn- und Feiertage gegebenenfalls ab 11 Uhr",url,did,date,date,priority=3)
    if "31.12. & 01.01. geschlossen" in blocks.get("DEZEMBER", ""):
        for date in ("2026-12-31","2027-01-01"):
            save_fact(db,"special_openings",date,"Geschlossen",url,did,date,date,priority=3)
    if "02.01. bis 10.01." in blocks.get("JANUAR", ""):
        for day in range(2,11):
            date=f"2027-01-{day:02d}"
            save_fact(db,"special_openings",date,"Ab 12 Uhr geöffnet; Sonn- und Feiertage ab 11 Uhr",url,did,date,date,priority=3)
    if "06.01. 11 bis 23 Uhr geöffnet" in blocks.get("JANUAR", ""):
        date="2027-01-06"
        db.execute("DELETE FROM structured_facts WHERE category='special_openings' AND subject=?",(date,))
        save_fact(db,"special_openings",date,"11 bis 23 Uhr geöffnet",url,did,date,date,priority=3)

def crawl():
    db = connect()
    started = now()
    seen_count = changed = 0
    errors = []
    with httpx.Client(timeout=22, follow_redirects=True, headers={"User-Agent":"MeckyKnowledgeCrawler/1.0 (+https://heuchelberg.com/)"}) as client:
        robots=robotparser.RobotFileParser()
        try:
            robots.parse(client.get(urljoin(BASE,"robots.txt")).text.splitlines())
        except Exception as exc:
            log.warning("robots.txt unavailable: %s",exc)
            robots.parse(["User-agent: *","Disallow: /wp-admin/"])
        queue = deque([BASE] + sitemap_urls(client))
        seen = set()
        while queue and seen_count < MAX_PAGES:
            url = normalize(queue.popleft())
            if url in seen or not allowed(url) or not robots.can_fetch("MeckyKnowledgeCrawler",url):
                continue
            seen.add(url)
            try:
                response = client.get(url)
                response.raise_for_status()
                if len(response.content) > MAX_BYTES:
                    raise ValueError("document exceeds byte limit")
                ct = response.headers.get("content-type", "").lower()
                is_pdf = url.lower().endswith(".pdf") or "application/pdf" in ct
                if not is_pdf and "text/html" not in ct:
                    continue
                if is_pdf:
                    title, canonical, content, links = url.rsplit("/",1)[-1],url,parse_pdf(response.content),[]
                else:
                    title, canonical, content, links = parse_html(response.text,url)
                if len(content) < 40:
                    continue
                doc = {"id":stable_id(url),"url":url,"canonical_url":canonical,"title":title,"content":content,
                       "content_type":"pdf" if is_pdf else "html","crawled_at":now(),"last_modified":response.headers.get("last-modified"),
                       "content_hash":hashlib.sha256(content.encode()).hexdigest(),"category":category(url,title),
                       "source_priority":4 if is_pdf else 3}
                if upsert_document(db,doc):
                    extract_facts(db,doc)
                    changed += 1
                seen_count += 1
                if not is_pdf:
                    db.execute("DELETE FROM source_links WHERE document_id=?",(doc["id"],))
                    for link,label in links:
                        if label and len(label)>2:
                            db.execute("INSERT OR REPLACE INTO source_links VALUES(?,?,?,?,?)",(stable_id(doc["id"],link,label),doc["id"],label,link,now()))
                for link,label in links:
                    if link.lower().endswith(".pdf") and link not in seen:
                        queue.appendleft(link)
                    elif len(seen) + len(queue) < MAX_PAGES * 2 and link not in seen:
                        queue.append(link)
                db.commit()
            except Exception as exc:
                errors.append(f"{url}: {str(exc)[:150]}")
                log.warning("Crawl %s: %s",url,exc)
    db.execute("INSERT INTO crawl_runs(started_at,finished_at,documents_seen,documents_changed,errors) VALUES(?,?,?,?,?)",(started,now(),seen_count,changed,str(errors[:20])))
    db.commit()
    db.close()
    return {"seen":seen_count,"changed":changed,"errors":errors[:20]}
