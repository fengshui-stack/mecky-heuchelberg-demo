"""One minimal, billable OpenAI request that validates the production contract."""
from dotenv import load_dotenv

load_dotenv(".env")

from mecky.provider import agent_request
from mecky.tools import tool_definitions

result = agent_request(
    [{"role": "user", "content": "Servus"}],
    "Du bist Mecky. Antworte kurz und freundlich.",
    tool_definitions(),
    None,
)
print({
    "error": result["error"],
    "payload": result["payload"],
    "tool_calls": len(result["tool_calls"]),
    "usage": result["usage"],
})
