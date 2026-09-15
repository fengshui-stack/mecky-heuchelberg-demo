import json
import statistics
import time
import uuid
from pathlib import Path
from mecky.engine import chat

cases=[json.loads(x) for x in Path("eval/questions.jsonl").read_text(encoding="utf-8").splitlines()]
results=[]
run_id=uuid.uuid4().hex[:10]
for i,case in enumerate(cases):
    start=time.monotonic()
    answer=chat(f"eval-{run_id}-{i}",case["question"])
    latency=(time.monotonic()-start)*1000
    expected=case["expected_relevant_url"]
    url_ok=not expected or any(expected in x["url"] for x in answer["links"])
    if answer["status"]=="UNKNOWN" and any("/kontakt/" in x["url"] or "/events/" in x["url"] for x in answer["links"]):
        url_ok=True
    prohibited=any(x in answer["message"].lower() for x in case["must_not_claim"])
    results.append({"question":case["question"],"intent":answer["intent"],"status":answer["status"],"url_ok":url_ok,"prohibited_claim":prohibited,"latency_ms":round(latency)})
known=sum(x["status"]=="KNOWN" for x in results)
unknown=sum(x["status"]=="UNKNOWN" for x in results)
report={"questions":len(results),"known":known,"partial":len(results)-known-unknown,"unknown":unknown,"link_correctness":round(sum(x["url_ok"] for x in results)/len(results),3),"prohibited_claim_rate":round(sum(x["prohibited_claim"] for x in results)/len(results),3),"median_latency_ms":round(statistics.median(x["latency_ms"] for x in results)),"p95_latency_ms":round(sorted(x["latency_ms"] for x in results)[int(.95*len(results))-1]),"limitations":"Automated checks cover links and prohibited phrases; human review is needed for factual correctness and naturalness.","failures":[x for x in results if not x["url_ok"] or x["prohibited_claim"]][:30]}
Path("eval/report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(report,ensure_ascii=False,indent=2))
