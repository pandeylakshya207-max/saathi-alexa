"""Saathi: an Alexa+ MCP server that looks after a parent who lives alone.

Parent side (voice): log medicines, daily check-ins, ask for help at home.
Family side: weekly briefing, approve or decline care requests, manage medicines.
Every tool returns a `say` field written to be spoken aloud as-is.
"""
from __future__ import annotations

import os
from typing import Literal

from mcp.server.mcpserver import MCPServer

import store

store.init_db()

INSTRUCTIONS = """Saathi is a voice-first care companion for an elderly parent who lives alone,
and a care co-ordinator for their family who live in other cities.
- Every tool returns a `say` field. Speak it as-is: it is already written for voice.
- Speak warmly and simply, in short sentences. Never diagnose. Saathi notices patterns
  and brings in family and doctors.
- If the parent mentions chest pain, breathlessness or a fall, call check_in immediately.
- Anything that books a service or costs money goes through request_care, which waits
  for a family member's approval. Never treat a request as booked until it is approved."""

mcp = MCPServer(
    "saathi",
    title="Saathi",
    description="Care companion for parents who live alone, and a care co-ordinator for their family.",
    instructions=INSTRUCTIONS,
    version="0.2.0",
)

Slot = Literal["morning", "afternoon", "night"]
Service = Literal["doctor_home_visit", "home_lab_test", "nurse_visit",
                  "medicine_refill", "grocery_delivery"]

SLOT_PHRASE = {"morning": "in the morning", "afternoon": "in the afternoon", "night": "at night"}

OPENERS = {
    "stable": "is doing well this week",
    "watch": "is mostly fine, but there are a couple of things to keep an eye on",
    "concern": "is showing a pattern this week that is worth acting on",
    "urgent": "needs attention right now",
}


def _by_time(doses: list[dict]) -> list[dict]:
    return sorted(doses, key=lambda d: store.SLOTS[d["slot"]])


def _dose_words(doses: list[dict]) -> str:
    return store.join_words(f"{d['medicine']} {SLOT_PHRASE[d['slot']]}" for d in doses)


def _next_dose_line() -> str:
    today = _by_time(store.doses_for_day(store.now().date()))
    left = [d for d in today if d["status"] in ("due", "upcoming")]
    if not left:
        return "That's all your medicines for today. Well done."
    return f"Next is {_dose_words(left[:1])}."


# ---------------- parent-facing tools ----------------

@mcp.tool()
def log_medicine(medicine: str, taken: bool = True) -> dict:
    """Record that the parent took, or skipped, a medicine.

    Use when they say things like "I took my BP tablet" or "I skipped the sugar
    medicine". `medicine` can be the name or how they describe it.
    """
    med = store.find_medicine(medicine)
    if med is None:
        names = store.join_words(m["name"] for m in store.list_medicines())
        return {"say": f"I couldn't match that to your medicines. You take {names}. "
                       f"Which one was it?", "matched": False}
    slot = store.closest_slot(med["slots"])
    store.log_dose(med["name"], slot, taken)
    if taken:
        say = f"Done. {med['name']} {SLOT_PHRASE[slot]} is marked as taken. {_next_dose_line()}"
    else:
        say = (f"Okay, I've noted that you skipped {med['name']} {SLOT_PHRASE[slot]}. "
               f"If something is stopping you from taking it, tell me and I'll let "
               f"{store.primary_contact()} know.")
    return {"say": say, "matched": True, "medicine": med["name"], "slot": slot, "taken": taken}


@mcp.tool()
def medicines_today() -> dict:
    """Tell the parent which medicines they have taken today and what is still due."""
    today = _by_time(store.doses_for_day(store.now().date()))
    taken = [d for d in today if d["status"] == "taken"]
    due = [d for d in today if d["status"] in ("due", "missed")]
    later = [d for d in today if d["status"] == "upcoming"]
    parts = [f"You've taken {store._n(len(taken), 'medicine')} today." if taken
             else "You haven't logged any medicines yet today."]
    if due:
        parts.append(f"Due now: {_dose_words(due)}.")
    if later:
        parts.append(f"Later today: {_dose_words(later)}.")
    if not due and not later:
        parts.append("Nothing else is due today.")
    return {"say": " ".join(parts), "doses": today}


@mcp.tool()
def check_in(how_i_feel: str) -> dict:
    """Daily check-in: record how the parent says they feel, in their own words.

    Call this whenever they mention a symptom, their mood, a fall, chest pain or
    trouble breathing. Saathi looks for patterns across the whole week.
    """
    rec = store.record_checkin(how_i_feel)
    risk = store.assess()
    name, primary = store.parent_name(), store.primary_contact()

    if rec["severity"] >= 3:
        what = store.join_words(rec["symptoms"])
        store.add_alert("urgent", f'{name} reported {what}: "{how_i_feel}"')
        say = (f"I'm worried about that. If it feels serious, please call 112 right now. "
               f"I've sent an urgent alert to {store.family_names()}.")
        action = "urgent_alert_sent"
    elif rec["symptoms"] and risk["level"] == "concern":
        top = max(rec["symptoms"], key=lambda s: risk["symptom_counts"].get(s, 0))
        times = risk["symptom_counts"].get(top, 1)
        bp = any("blood pressure" in r for r in risk["reasons"])
        extra = ", and a few blood pressure tablets were missed" if bp else ""
        say = (f"I'm sorry you're not feeling well. This is the {store.ordinal(times)} time "
               f"this week you've mentioned {top}{extra}. Shall I ask {primary} to arrange "
               f"a doctor's visit at home?")
        store.add_alert("concern", f"{name}: {top} reported {times} times this week. "
                                   + " ".join(risk["reasons"]))
        action = "suggest_doctor_home_visit"
    elif rec["symptoms"]:
        say = (f"I'm sorry to hear that. I've noted it, and I'll let {primary} know "
               f"if it keeps happening. Please take some rest.")
        action = "noted"
    elif rec["mood"] == "low":
        store.add_alert("info", f'{name} sounded low today: "{how_i_feel}"')
        say = f"I'm right here with you. Would you like me to ask {primary} to call you this evening?"
        action = "suggest_family_call"
    else:
        say = "That's lovely to hear. I've noted it."
        action = "noted"
    return {"say": say, "symptoms": rec["symptoms"], "mood": rec["mood"],
            "risk_level": risk["level"], "next_action": action}


@mcp.tool()
def request_care(service: Service, reason: str) -> dict:
    """Ask for help at home: a doctor's visit, home lab test, nurse visit, medicine refill
    or grocery delivery.

    Nothing is booked or paid for until a family member approves it. Returns a request
    ID that can be checked later with care_request_status.
    """
    req = store.create_request(service, reason)
    store.add_alert("approval", f"{store.parent_name()} asked for {req['service_spoken']}: "
                                f"{reason}. Request {req['id']} needs approval.")
    say = (f"I've asked {store.primary_contact()} to approve {req['service_spoken']}. "
           f"I'll book it as soon as they say yes, and I'll tell you the time.")
    return {"say": say, "request_id": req["id"], "status": req["status"]}


@mcp.tool()
def care_request_status(request_id: str = "") -> dict:
    """Check on a care request. Leave request_id empty for the most recent one."""
    req = store.get_request(request_id) if request_id else store.latest_request()
    if not req:
        return {"say": "There aren't any care requests yet.", "found": False}
    service = req["service_spoken"]
    if req["status"] == "awaiting_family_approval":
        say = f"{service.capitalize()} is still waiting for {store.primary_contact()} to approve it."
    elif req["status"] == "booked":
        say = (f"Good news. {req['decided_by']} approved it, and {service} is booked for "
               f"{req['booking']['when_spoken']}.")
    else:
        say = f"{req['decided_by']} decided not to go ahead with {service} for now."
    return {"say": say, "found": True, "id": req["id"], "service": req["service"],
            "status": req["status"], "booking": req["booking"]}


# ---------------- family-facing tools ----------------

@mcp.tool()
def family_briefing() -> dict:
    """For a family member: how the parent is doing this week, why, and whether
    anything is waiting for their decision."""
    risk = store.assess()
    name = store.parent_name()
    pending = store.pending_requests()
    parts = [f"{name} {OPENERS[risk['level']]}."] + risk["reasons"][:3]
    if pending:
        p = pending[0]
        parts.append(f"{name} has asked for {p['service_spoken']}. "
                     f"Would you like me to approve it?")
    return {"say": " ".join(parts), "level": risk["level"], "reasons": risk["reasons"],
            "pending_requests": [{"id": p["id"], "service": p["service"], "reason": p["reason"]}
                                 for p in pending],
            "recent_alerts": store.recent_alerts()}


@mcp.tool()
def decide_care_request(approve: bool, family_member: str, request_id: str = "") -> dict:
    """For a family member: approve or decline a care request. Approving books it.
    Leave request_id empty to decide on the oldest pending request."""
    if not request_id:
        pending = store.pending_requests()
        if not pending:
            return {"say": "There's nothing waiting for approval right now.", "found": False}
        request_id = pending[0]["id"]
    before = store.get_request(request_id)
    if not before:
        return {"say": "I couldn't find that request.", "found": False}
    if before["status"] != "awaiting_family_approval":
        return {"say": f"That request was already {before['status']}.", "found": True,
                "status": before["status"]}
    req = store.decide_request(request_id, approve, family_member)
    name = store.parent_name()
    if req["status"] == "booked":
        say = (f"Done. {req['service_spoken'].capitalize()} is booked for "
               f"{req['booking']['when_spoken']}. I'll let {name} know.")
    else:
        say = f"Okay, I won't book it. It may help to give {name} a call and talk it through."
    return {"say": say, "found": True, "id": req["id"], "status": req["status"],
            "booking": req["booking"]}


@mcp.tool()
def add_medicine(name: str, purpose: str, slots: list[Slot]) -> dict:
    """For a family member: add or update a medicine, what it is for (for example
    "blood pressure bp"), and when it is taken."""
    med = store.add_medicine(name, purpose, list(slots))
    return {"say": f"Added {med['name']} for {purpose}, {store.join_words(SLOT_PHRASE[s] for s in slots)}.",
            "medicine": med}


if __name__ == "__main__":
    mcp.run(transport="streamable-http",
            host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "8000")))