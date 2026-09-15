import json

from .store import now


def record_usage(db, sid, interaction_id, usage):
    db.execute("INSERT INTO interaction_usage(interaction_id,session_id,usage,created_at) VALUES(?,?,?,?)",
               (interaction_id, sid, json.dumps(usage), now()))
    if usage["model_called"]:
        db.execute("INSERT INTO llm_usage(provider,model,tokens_input,tokens_output,estimated_cost,created_at) VALUES(?,?,?,?,?,?)",
                   (usage["provider"], usage["model"], usage["tokens_input"], usage["tokens_output"], usage["cost_usd"], now()))


def session_usage(db, sid):
    rows = [json.loads(row[0]) for row in db.execute("SELECT usage FROM interaction_usage WHERE session_id=?", (sid,))]
    unknown_costs = sum(row["cost_usd"] is None for row in rows)
    unknown_tokens = sum(not row["tokens_complete"] for row in rows)
    known_cost = sum(row["cost_usd"] or 0 for row in rows)
    calls = sum(row["model_called"] for row in rows)
    return {"answers": len(rows), "model_calls": calls, "currency": "USD",
            "tokens_input": sum(row["tokens_input"] or 0 for row in rows),
            "tokens_output": sum(row["tokens_output"] or 0 for row in rows),
            "tokens_total": sum(row["tokens_total"] or 0 for row in rows),
            "tokens_complete": unknown_tokens == 0, "unknown_token_requests": unknown_tokens,
            "cost_usd": None if unknown_costs else known_cost, "known_cost_usd": known_cost,
            "unknown_cost_requests": unknown_costs,
            "cost_status": "incomplete" if unknown_costs else "estimated" if any(row["cost_status"] == "estimated" for row in rows) else "reported" if calls else "not_used"}
