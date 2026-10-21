"""Saathi Alexa+ simulator.

Simulates the Alexa+ experience on two devices: Kamla's Echo Show at home in
Jaipur, and her son Rohan's phone in Bengaluru.

Browser speech -> LLM agent (Groq, tool calling) -> real MCP tool calls to the
Saathi server over Streamable HTTP -> spoken reply in the browser.

Run:  python alexa_sim.py   then open http://127.0.0.1:8100 in Chrome.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx2
import uvicorn
from dotenv import load_dotenv
from mcp import Client
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

import store

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

MCP_URL = os.environ.get("SAATHI_MCP_URL", "http://127.0.0.1:8000/mcp")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_STEPS = 5

COMMON = """Speak like Alexa: warm, simple, short (one to three sentences), no lists,
no markdown, no emojis. Saathi tools return a `say` field written for voice:
base your reply on it closely. Never invent medical facts, bookings or times
that a tool did not return."""

PERSONAS = {
    "kamla": {
        "tools": {"log_medicine", "medicines_today", "check_in", "request_care",
                  "care_request_status"},
        "prompt": f"""You are Alexa+ on an Echo Show in the home of Kamla Devi, 72,
who lives alone in Jaipur. The Saathi add-on is enabled and helps her and her family.
- When she says she took or skipped a medicine, call log_medicine.
- When she asks what medicines are left or due, call medicines_today.
- When she mentions how she feels, any symptom, her mood, a fall, chest pain or
  breathing trouble, call check_in with her own words.
- If Saathi suggested a doctor's visit and she agrees, call request_care with
  service doctor_home_visit and a short reason.
- When she asks whether help or the doctor is coming, call care_request_status.
{COMMON}""",
    },
    "rohan": {
        "tools": {"family_briefing", "decide_care_request", "care_request_status",
                  "add_medicine", "request_care"},
        "prompt": f"""You are Alexa+ on the phone of Rohan, who lives in Bengaluru.
His mother Kamla ("Maa") lives alone in Jaipur and uses Saathi.
- When he asks how Maa is doing, call family_briefing.
- When he approves or declines a request, call decide_care_request with
  family_member "Rohan".
- To add or change one of her medicines, call add_medicine.
{COMMON}""",
    },
}


def tool_schema(tool) -> dict:
    return {"type": "function",
            "function": {"name": tool.name, "description": tool.description or "",
                         "parameters": tool.input_schema}}


def payload(result) -> str:
    return result.content[0].text if result.content else "{}"


async def chat(request: Request) -> JSONResponse:
    body = await request.json()
    persona = PERSONAS.get(body.get("persona"), PERSONAS["kamla"])
    text = (body.get("text") or "").strip()
    history = [m for m in (body.get("history") or [])[-8:]
               if m.get("role") in ("user", "assistant") and m.get("content")]
    if not text:
        return JSONResponse({"error": "Say something first."}, status_code=400)
    if not GROQ_KEY:
        return JSONResponse({"reply": "The simulator needs a GROQ_API_KEY in the .env file.",
                             "calls": []})

    messages = [{"role": "system", "content": persona["prompt"]}, *history,
                {"role": "user", "content": text}]
    calls, reply = [], ""
    async with Client(MCP_URL) as saathi, httpx2.AsyncClient(timeout=30) as http:
        listed = await saathi.list_tools()
        tools = [tool_schema(t) for t in listed.tools if t.name in persona["tools"]]
        for _ in range(MAX_STEPS):
            resp = await http.post(GROQ_URL,
                                   headers={"Authorization": f"Bearer {GROQ_KEY}"},
                                   json={"model": GROQ_MODEL, "messages": messages,
                                         "tools": tools, "tool_choice": "auto",
                                         "temperature": 0.3})
            if resp.status_code != 200:
                return JSONResponse({"reply": "Sorry, I couldn't reach my brain just now.",
                                     "calls": calls, "error": resp.text[:300]})
            msg = resp.json()["choices"][0]["message"]
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                reply = msg.get("content") or ""
                break
            messages.append({"role": "assistant", "content": msg.get("content") or "",
                             "tool_calls": tool_calls})
            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                start = time.perf_counter()
                try:
                    content = payload(await saathi.call_tool(name, args))
                except Exception as exc:  # surface tool errors to the model
                    content = json.dumps({"error": str(exc)})
                ms = round((time.perf_counter() - start) * 1000)
                calls.append({"tool": name, "args": args, "ms": ms})
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": content})
    return JSONResponse({"reply": reply, "calls": calls})


async def dashboard(request: Request) -> JSONResponse:
    async with Client(MCP_URL) as saathi:
        briefing = json.loads(payload(await saathi.call_tool("family_briefing", {})))
        meds = json.loads(payload(await saathi.call_tool("medicines_today", {})))
    return JSONResponse({"briefing": briefing, "medicines": meds,
                         "parent": store.get_profile().get("parent_full_name", "")})


async def reset(request: Request) -> JSONResponse:
    store.seed_demo()
    return JSONResponse({"ok": True})


async def index(request: Request) -> FileResponse:
    return FileResponse(HERE / "sim.html")


app = Starlette(routes=[
    Route("/", index),
    Route("/api/chat", chat, methods=["POST"]),
    Route("/api/dashboard", dashboard),
    Route("/api/reset", reset, methods=["POST"]),
])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8100)