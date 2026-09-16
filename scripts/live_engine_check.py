"""Run one end-to-end model/tool/validator turn against a temporary seeded DB."""
import json
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")
target = Path("/tmp/mecky-live-engine-check.db")
shutil.copyfile("data/seed.db", target)
os.environ["MECKY_DB"] = str(target)

from mecky import store
store.DB_PATH = target
from mecky.engine import chat

result = chat("live-contract", "Darf mein Hund mit?")
print(json.dumps({key: result[key] for key in (
    "message", "intents", "status", "response_type", "validator_result",
    "retry_count", "fallback_used", "usage", "latency_ms"
)}, ensure_ascii=False, indent=2))
