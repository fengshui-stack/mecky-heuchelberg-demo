import sqlite3
from pathlib import Path
from mecky.store import DB_PATH

SEED=Path("data/seed.db")
SEED.parent.mkdir(exist_ok=True)
source=sqlite3.connect(DB_PATH)
target=sqlite3.connect(SEED)
source.backup(target)
for table in ("sessions","conversation_messages","user_memory","interactions","feedback","knowledge_gaps","admin_knowledge","llm_usage"):
    target.execute(f"DELETE FROM {table}")
target.commit()
target.execute("VACUUM")
assert target.execute("SELECT count(*) FROM documents").fetchone()[0]>0
assert target.execute("SELECT count(*) FROM sessions").fetchone()[0]==0
print("Created public knowledge seed without conversation or admin data:",SEED,target.execute("SELECT count(*) FROM documents").fetchone()[0],"documents")
source.close();target.close()
