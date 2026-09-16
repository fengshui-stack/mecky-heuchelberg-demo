"""Run and persist the required behavior checks against the deployed API."""
import json
import os
from pathlib import Path

import httpx

ROOT=os.getenv("MECKY_LIVE_URL","https://mecky-heuchelberg-demo.onrender.com").rstrip("/")
cases=[
    ("t1","Hi",None),
    ("t1","Hi",None),
    ("t2","kann man bei euch hochfahrn?",{"get_directions","get_parking_info"}),
    ("t3","ich habe geschissen",None),
    ("t4","habt ihr bier?",{"get_drinks"}),
    ("t5","ich hab hunger",{"get_menu"}),
    ("t6","was kostet das schnitzel?",{"get_menu"}),
    ("t7","du fotze",None),
    ("t8","morgen offen?",{"get_opening_hours"}),
    ("t9","ich hab hunger",{"get_menu"}),
    ("t9","und trinken?",{"get_drinks"}),
]
rows=[]
with httpx.Client(timeout=90) as client:
    for session,message,expected in cases:
        response=client.post(ROOT+"/chat",json={"session_id":"gold-"+session,"message":message})
        response.raise_for_status();data=response.json()
        tools=set(data.get("intents",[]))
        checks={
            "model_called":bool(data.get("usage",{}).get("model_called")),
            "validator_passed":data.get("validator_result") in {"pass","retry_pass"},
            "no_old_fallback":"keine verlässliche info" not in data.get("message","").casefold(),
            "not_fallback":not data.get("fallback_used"),
            "expected_tool":expected is None or bool(tools & expected),
        }
        rows.append({"session":session,"message":message,"expected_tools":sorted(expected or []),
                     "checks":checks,"response":data})
report={"url":ROOT,"cases":len(rows),"passed":sum(all(x["checks"].values()) for x in rows),"rows":rows}
if rows[0]["response"]["message"]==rows[1]["response"]["message"]:
    rows[1]["checks"]["not_repeated"]=False
else: rows[1]["checks"]["not_repeated"]=True
report["passed"]=sum(all(x["checks"].values()) for x in rows)
Path("docs/live-goldstandard-10.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"url":ROOT,"cases":report["cases"],"passed":report["passed"],
                  "summary":[{"message":x["message"],"answer":x["response"]["message"],"tools":x["response"].get("intents"),"validator":x["response"].get("validator_result"),"checks":x["checks"]} for x in rows]},ensure_ascii=False,indent=2))
if report["passed"]!=len(rows):raise SystemExit("Live behavior gate failed")
