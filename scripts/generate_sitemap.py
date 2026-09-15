from pathlib import Path
from mecky.store import connect

db=connect()
rows=db.execute("SELECT title,url,category,content_type,crawled_at FROM documents ORDER BY category,url").fetchall()
out=["# Interne Sitemap", "", f"Live-Crawl: {len(rows)} offizielle Dokumente. Nur heuchelberg.com und direkt verlinkte offizielle PDFs wurden verarbeitet.", ""]
current=None
for row in rows:
    if row["category"]!=current:
        current=row["category"]
        out.extend([f"## {current}",""])
    title=row["title"].replace("[", "(").replace("]",")")
    out.append(f"- [{title}]({row['url']}) · {row['content_type']}")
out.append("")
path=Path("docs/site-map.md");path.parent.mkdir(exist_ok=True)
path.write_text("\n".join(out),encoding="utf-8")
print(path,len(rows))
db.close()
