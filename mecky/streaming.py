"""SSE framing after the complete response has passed validation."""
import json
import re


def events(response: dict):
    yield "event: meta\ndata: "+json.dumps({k:response[k] for k in response if k!="message"},ensure_ascii=False)+"\n\n"
    chunks=re.findall(r"\S+\s*",response["message"])
    for chunk in chunks:
        yield "event: delta\ndata: "+json.dumps({"text":chunk},ensure_ascii=False)+"\n\n"
    yield "event: done\ndata: {}\n\n"
