import argparse
import json
from .crawler import crawl
from .store import connect

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["crawl","refresh","reindex","import-rag","stats"])
    args = parser.parse_args()
    if args.command in ("crawl","refresh"):
        print(json.dumps(crawl(),ensure_ascii=False,indent=2))
    elif args.command == "import-rag":
        from .manual import import_rag
        print(f"Imported {import_rag()} manually curated sections")
    elif args.command == "reindex":
        from .crawler import extract_facts
        db=connect()
        db.execute("DELETE FROM structured_facts")
        for row in db.execute("SELECT * FROM documents").fetchall():
            extract_facts(db,dict(row))
        db.commit();db.close()
        print("Facts reindexed")
    else:
        db=connect()
        print(json.dumps({table:db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("documents","document_chunks","structured_facts","admin_knowledge","knowledge_gaps")},indent=2))
        db.close()

if __name__ == "__main__":
    main()
