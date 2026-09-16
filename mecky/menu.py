"""High-precision menu reading from the current, officially linked PDF."""
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from .store import stable_id

def normalize(value: str) -> str:
    """Normalize menu text locally; this is parsing, not conversation routing."""
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value)).strip()

HEADINGS = {"aus dem steinofen", "aus dem smoker", "desserts", "vegan lecker", "immer wieder ein erlebnis", "heuchelberg specials", "klassiker", "wasser aus deutschland", "unsere", "zum", "vorab", "dressings", "nur auf vorbestellung", "aus dem schwarzwald", "fruchtiges aus der region", "feines zum", "mitfunky farbwechsel", "hä llischem landschwein", "doofrepus doofrepus"}
PRICE = re.compile(r"(?<!\d)(\d{1,3})\s*,\s*(\d{2})(?:\s*€)?(?!\d)")


def document_year(url: str) -> int | None:
    years = [int(x) for x in re.findall(r"(?:/|[-_])((?:20)?2[0-9])(?:/|[-_.])", url)]
    years = [2000 + x if x < 100 else x for x in years]
    return max(years) if years else None


def current_document(db, category: str):
    """A card linked by the official homepage beats an unlinked PDF or old URL."""
    rows = db.execute("SELECT d.* FROM documents d WHERE d.content_type='pdf' AND d.category=?", (category,)).fetchall()
    if not rows:
        return None
    linked = {r[0] for r in db.execute("SELECT url FROM source_links WHERE upper(label) LIKE ?", ("%SPEISEKARTE%" if category == "menu" else "%GETRÄNKEKARTE%",))}
    return max(rows, key=lambda d: (document_year(d["url"]) or 0, d["url"] in linked,
                                    d["crawled_at"] or "", -len(d["url"])))


def is_fresh(doc, days=30):
    if not doc or not doc["crawled_at"]:
        return False
    try:
        return datetime.fromisoformat(doc["crawled_at"]) >= datetime.now(timezone.utc)-timedelta(days=days)
    except (TypeError, ValueError):
        return False


def source_metadata(doc):
    if not doc:
        return None
    year = document_year(doc["url"])
    printed = re.search(r"\b(?:AB|STAND)\s+(?:[A-ZÄÖÜa-zäöü]+\s+)?(20\d{2})\b", doc["content"][:600])
    content_date = str(int(printed.group(1))) if printed and (not year or int(printed.group(1))==year) else None
    return {"title": doc["title"], "url": doc["url"], "source_type": doc["content_type"],
            "crawl_timestamp": doc["crawled_at"], "content_date": content_date,
            "valid_from": None, "valid_until": None, "priority": doc["source_priority"]}


def candidate_name(line: str) -> str | None:
    line = re.sub(r"\s+", " ", line).strip(" Ɔ•-– ")
    if not 4 <= len(line) <= 72 or any(c.isdigit() for c in line) or "/" in line or "}" in line:
        return None
    letters = [c for c in line if c.isalpha()]
    if len(letters) < 4 or sum(c.isupper() for c in letters) / len(letters) < 0.8:
        return None
    if normalize(line) in HEADINGS or re.search(r"\b(finde uns|frag nach|zutaten|kleine portion|alkoholfrei|seite|unser tipp|weitere leckere|nur auf|immer wieder)\b", normalize(line)):
        return None
    return line


def upper_line(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return bool(letters) and len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) >= 0.8


def parse_items(text: str, category: str, url: str, document_id: str):
    """Parse only legible name/description/price groups; ambiguous PDF layouts get no price."""
    pages = text.split("\f")
    output = []
    section = None
    for page_number, page in enumerate(pages, 1):
        lines = [re.sub(r"\s+", " ", x).strip() for x in page.splitlines()]
        for index, line in enumerate(lines):
            name = candidate_name(line)
            if not name:
                continue
            if normalize(name) in ("desserts", "aus dem steinofen", "aus dem smoker", "klassiker"):
                section = name.title()
                continue
            following = []
            for next_line in lines[index + 1:index + 7]:
                if upper_line(next_line):
                    break
                if next_line:
                    following.append(next_line)
            if not following:
                continue
            description = " ".join(x for x in following if not PRICE.fullmatch(x.replace("€", "").strip()))[:220]
            # Prices are accepted only if exactly one value follows this name before
            # the next candidate; OCR can otherwise pair another item's price.
            prices = [m.group(1) + "," + m.group(2) for x in following for m in PRICE.finditer(x)]
            price = prices[0] + " €" if len(prices) == 1 and len(following) <= 4 else None
            label_text = normalize(name + " " + description)
            dietary = [x for x in ("vegan", "vegetarisch", "glutenfrei") if re.search(r"\b" + x + r"\w*\b", label_text)]
            allergens = re.search(r"[} {]\s*((?:[A-O0-9]\s*/\s*)+[A-O0-9])\b", description)
            output.append({"id": stable_id(document_id, page_number, index, name),
                           "document_id": document_id, "category": category, "section": section,
                           "item_name": name, "description": description or None,
                           "price": price, "dietary_labels": json.dumps(dietary),
                           "allergen_labels": json.dumps(re.findall(r"[A-O0-9]", allergens.group(1))) if allergens else "[]",
                           "page": page_number if len(pages) > 1 else None, "source_url": url,
                           "content_date": str(document_year(url)) if document_year(url) else None,
                           "confidence": 0.88 if price else 0.72})
    # Duplicate names caused by repeated PDF headers are not separate products.
    return list({normalize(x["item_name"]): x for x in output}.values())


def indexed_items(db, doc):
    rows = db.execute("SELECT * FROM menu_items WHERE document_id=?", (doc["id"],)).fetchall()
    if not rows:
        items = parse_items(doc["content"], doc["category"], doc["url"], doc["id"])
        for item in items:
            db.execute("INSERT OR REPLACE INTO menu_items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       tuple(item[key] for key in ("id", "document_id", "category", "section", "item_name", "description",
                                                   "price", "dietary_labels", "allergen_labels", "page", "source_url", "content_date", "confidence")))
        rows = db.execute("SELECT * FROM menu_items WHERE document_id=?", (doc["id"],)).fetchall()
    return [dict(row) for row in rows]


def matching_items(db, category: str, term: str):
    doc = current_document(db, category)
    if not doc:
        return None, []
    q = normalize(term)
    items = indexed_items(db, doc)
    matches = [x for x in items if q in normalize(x["item_name"])]
    matches.sort(key=lambda x: (not normalize(x["item_name"]).startswith(q), len(x["item_name"])))
    return doc, matches[:4]


def examples(db, category: str, count=3):
    doc = current_document(db, category)
    if not doc:
        return None, []
    items = [x for x in indexed_items(db, doc) if x["confidence"] >= 0.7 and len(x["item_name"].split()) <= 5]
    preferred = (("KÄSESPÄTZLE", "BERG-CURRYBOWL", "KAROTTEN-INGWER-SUPPE") if category == "menu"
                 else ("PALMBRÄU TURM-BIER", "APEROL SPRITZ", "BERGSCHORLEN"))
    selected = [next((item for item in items if normalize(item["item_name"]) == normalize(name)), None) for name in preferred]
    selected = [item for item in selected if item]
    if selected:
        return doc, selected[:count]
    # Spread unknown future cards across the PDF instead of repeating starters.
    if not items:
        return doc, []
    step = max(1, len(items) // count)
    chosen = [items[i] for i in range(0, len(items), step)][:count]
    return doc, chosen
