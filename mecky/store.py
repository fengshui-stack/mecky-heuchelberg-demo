import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("MECKY_DB", "data/mecky.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,url TEXT UNIQUE,canonical_url TEXT,title TEXT,content TEXT,content_type TEXT,crawled_at TEXT,last_modified TEXT,content_hash TEXT,category TEXT,source_priority INTEGER);
CREATE TABLE IF NOT EXISTS document_chunks(id TEXT PRIMARY KEY,document_id TEXT,content TEXT,category TEXT);
CREATE TABLE IF NOT EXISTS source_links(id TEXT PRIMARY KEY,document_id TEXT,label TEXT,url TEXT,updated_at TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(content,category,content='document_chunks',content_rowid='rowid');
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON document_chunks BEGIN INSERT INTO chunks_fts(rowid,content,category) VALUES(new.rowid,new.content,new.category); END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON document_chunks BEGIN INSERT INTO chunks_fts(chunks_fts,rowid,content,category) VALUES('delete',old.rowid,old.content,old.category); END;
CREATE TABLE IF NOT EXISTS structured_facts(id TEXT PRIMARY KEY,category TEXT,subject TEXT,value TEXT,valid_from TEXT,valid_until TEXT,conditions TEXT,source_url TEXT,source_document_id TEXT,retrieved_at TEXT,confidence REAL,priority INTEGER);
CREATE TABLE IF NOT EXISTS manual_knowledge(id TEXT PRIMARY KEY,section TEXT,category TEXT,value TEXT,keywords TEXT,source_url TEXT,conflict_note TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS admin_knowledge(id TEXT PRIMARY KEY,category TEXT,subject TEXT,value TEXT,valid_from TEXT,valid_until TEXT,active INTEGER DEFAULT 1,created_at TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,context TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS conversation_messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS user_memory(id TEXT PRIMARY KEY,user_id TEXT,key TEXT,value TEXT,consent INTEGER,updated_at TEXT);
CREATE TABLE IF NOT EXISTS interactions(id INTEGER PRIMARY KEY,session_id TEXT,intent TEXT,confidence REAL,sources TEXT,answer TEXT,latency_ms INTEGER,status TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY,interaction_id INTEGER,rating INTEGER,comment TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS knowledge_gaps(id TEXT PRIMARY KEY,topic TEXT,occurrences INTEGER,example_questions TEXT,status TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS crawl_runs(id INTEGER PRIMARY KEY,started_at TEXT,finished_at TEXT,documents_seen INTEGER,documents_changed INTEGER,errors TEXT);
CREATE TABLE IF NOT EXISTS llm_usage(id INTEGER PRIMARY KEY,provider TEXT,model TEXT,tokens_input INTEGER,tokens_output INTEGER,estimated_cost REAL,created_at TEXT);
"""

def now():
    return datetime.now(timezone.utc).isoformat()

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db

def stable_id(*parts):
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:24]

def upsert_document(db, doc):
    old = db.execute("SELECT content_hash FROM documents WHERE url=?", (doc["url"],)).fetchone()
    if old and old[0] == doc["content_hash"]:
        return False
    db.execute("DELETE FROM document_chunks WHERE document_id=?", (doc["id"],))
    db.execute("DELETE FROM structured_facts WHERE source_document_id=?", (doc["id"],))
    db.execute("INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?)", tuple(doc[k] for k in ("id","url","canonical_url","title","content","content_type","crawled_at","last_modified","content_hash","category","source_priority")))
    paragraphs = [p.strip() for p in doc["content"].split("\n") if len(p.strip()) > 30]
    chunk = ""
    index = 0
    for p in paragraphs + ["" ]:
        if len(chunk) + len(p) > 1100 or not p:
            if chunk:
                db.execute("INSERT INTO document_chunks VALUES(?,?,?,?)", (stable_id(doc["id"],index),doc["id"],chunk,doc["category"]))
                index += 1
            chunk = ""
        chunk += ("\n" if chunk else "") + p
    return True

def save_fact(db, category, subject, value, url, doc_id, valid_from=None, valid_until=None, conditions=None, priority=3):
    fid = stable_id(category,subject,value,url,valid_from,valid_until)
    db.execute("INSERT OR REPLACE INTO structured_facts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (fid,category,subject,value,valid_from,valid_until,json.dumps(conditions or []),url,doc_id,now(),1.0,priority))
    return fid
