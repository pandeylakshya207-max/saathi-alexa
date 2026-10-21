"""Plays the Saathi demo story end to end against a running Saathi MCP server.

Usage: python demo.py [server_url]
"""
import asyncio
import json
import sys
import time

from mcp import Client

import store

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/mcp"

# (speaker, what they say, tool Alexa+ calls, arguments)
SCRIPT = [
    ("Kamla", "Alexa, what medicines do I have left today?", "medicines_today", {}),
    ("Kamla", "I took my BP tablet.", "log_medicine", {"medicine": "BP tablet"}),
    ("Kamla", "I'm feeling dizzy again today.", "check_in",
     {"how_i_feel": "I'm feeling dizzy again today"}),
    ("Kamla", "Yes, please ask Rohan.", "request_care",
     {"service": "doctor_home_visit",
      "reason": "Dizziness several times this week and missed blood pressure doses"}),
    ("Rohan, in Bengaluru", "Alexa, how is Maa doing?", "family_briefing", {}),
    ("Rohan, in Bengaluru", "Approve it.", "decide_care_request",
     {"approve": True, "family_member": "Rohan"}),
    ("Kamla", "Is the doctor coming?", "care_request_status", {}),
    ("Kamla", "I fell in the bathroom.", "check_in", {"how_i_feel": "I fell in the bathroom"}),
]


async def main() -> None:
    store.seed_demo()
    async with Client(URL) as client:
        tools = await client.list_tools()
        print(f"Connected to Saathi at {URL} ({len(tools.tools)} tools)\n")
        slowest = 0.0
        for speaker, said, tool, args in SCRIPT:
            print(f"{speaker}: {said}")
            start = time.perf_counter()
            result = await client.call_tool(tool, args)
            ms = (time.perf_counter() - start) * 1000
            slowest = max(slowest, ms)
            data = json.loads(result.content[0].text)
            print(f"   [Alexa+ calls {tool} - {ms:.0f} ms]")
            print(f"Alexa: {data['say']}\n")
        print(f"Slowest tool call: {slowest:.0f} ms (Alexa+ limit is 500 ms)")


asyncio.run(main())