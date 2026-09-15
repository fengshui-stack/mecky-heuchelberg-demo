import shutil
from pathlib import Path
from .store import DB_PATH, connect

SEED=Path("data/seed.db")

def main():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    if not DB_PATH.exists() and SEED.exists():
        shutil.copyfile(SEED,DB_PATH)
    db=connect()
    docs=db.execute("SELECT count(*) FROM documents").fetchone()[0]
    db.close()
    print(f"Mecky knowledge ready: {docs} documents")

if __name__=="__main__": main()
