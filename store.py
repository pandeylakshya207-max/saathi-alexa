"""Saathi care store and care-signal engine.

Everything Saathi knows lives in SQLite, so it remembers across Alexa+
sessions: medicines, dose history, daily check-ins, family members,
alerts, and care requests that wait for a family member's approval.

Run `python store.py --seed` to load the demo household.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
DB_PATH = Path(__file__).with_name("saathi.db")

# Dose slots and the hour each one is due.
SLOTS = {"morning": 8, "afternoon": 14, "night": 21}
GRACE_HOURS = 3  # a dose counts as missed this long after its slot

TABLES = ["profile", "family", "medicines", "dose_log", "checkins", "alerts", "care_requests"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS family (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, relation TEXT, city TEXT,
    is_primary INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS medicines (
    name TEXT PRIMARY KEY, purpose TEXT NOT NULL, slots TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dose_log (
    id INTEGER PRIMARY KEY, medicine TEXT NOT NULL, slot TEXT NOT NULL,
    day TEXT NOT NULL, taken INTEGER NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY, text TEXT NOT NULL, symptoms TEXT NOT NULL,
    mood TEXT NOT NULL, severity INTEGER NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY, level TEXT NOT NULL, message TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS care_requests (
    id TEXT PRIMARY KEY, service TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL,
    created_at TEXT NOT NULL, decided_by TEXT, decided_at TEXT, booking TEXT);
"""


def now() -> datetime:
    return datetime.now(IST)


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as c:
        c.executescript(SCHEMA)


# ---------- small helpers ----------

STOPWORDS = {"for", "the", "a", "my", "and", "of", "to", "tablet", "tablets", "pill",
             "pills", "medicine", "medicines", "goli", "wali", "dawai", "i", "took", "have"}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower())) - STOPWORDS


def _n(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def join_words(items) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def ordinal(n: int) -> str:
    return {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}.get(n, f"{n}th")


# ---------- profile & family ----------

def get_profile() -> dict:
    with db() as c:
        return {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM profile")}


def set_profile(**values: str) -> None:
    with db() as c:
        c.executemany("INSERT OR REPLACE INTO profile(key, value) VALUES (?, ?)",
                      list(values.items()))


def parent_name() -> str:
    return get_profile().get("parent_name", "your parent")


def family_members() -> list[dict]:
    with db() as c:
        rows = c.execute("SELECT name, relation, city, is_primary FROM family "
                         "ORDER BY is_primary DESC, id").fetchall()
    return [dict(r) for r in rows]


def primary_contact() -> str:
    fam = family_members()
    return fam[0]["name"] if fam else "your family"


def family_names() -> str:
    names = [f["name"] for f in family_members()]
    return join_words(names) if names else "your family"


# ---------- medicines & doses ----------

def list_medicines() -> list[dict]:
    with db() as c:
        rows = c.execute("SELECT name, purpose, slots FROM medicines ORDER BY name").fetchall()
    return [{"name": r["name"], "purpose": r["purpose"], "slots": json.loads(r["slots"])}
            for r in rows]


def add_medicine(name: str, purpose: str, slots: list[str]) -> dict:
    if not slots or any(s not in SLOTS for s in slots):
        raise ValueError(f"slots must be chosen from {list(SLOTS)}")
    clean = name.strip().title()
    with db() as c:
        c.execute(
            "INSERT INTO medicines(name, purpose, slots) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET purpose = excluded.purpose, slots = excluded.slots",
            (clean, purpose.strip().lower(), json.dumps(slots)),
        )
    return {"name": clean, "purpose": purpose, "slots": slots}


def find_medicine(spoken: str) -> dict | None:
    """Match how a person describes a medicine ("my BP tablet") to a real one."""
    said = spoken.lower()
    meds = list_medicines()
    for m in meds:
        if m["name"].lower() in said:
            return m
    words = _words(spoken)
    for m in meds:
        if words & _words(m["purpose"]):
            return m
    return None


def closest_slot(slots: list[str], at: datetime | None = None) -> str:
    at = at or now()
    hour = at.hour + at.minute / 60
    return min(slots, key=lambda s: abs(SLOTS[s] - hour))


def log_dose(medicine: str, slot: str, taken: bool = True, at: datetime | None = None) -> None:
    at = at or now()
    with db() as c:
        c.execute("INSERT INTO dose_log(medicine, slot, day, taken, at) VALUES (?, ?, ?, ?, ?)",
                  (medicine, slot, at.date().isoformat(), int(taken), at.isoformat()))


def doses_for_day(day: date, at: datetime | None = None) -> list[dict]:
    """Status of every scheduled dose on a day: taken, skipped, missed, due or upcoming."""
    at = at or now()
    with db() as c:
        logs = c.execute("SELECT medicine, slot, taken FROM dose_log WHERE day = ? ORDER BY id",
                         (day.isoformat(),)).fetchall()
    latest = {(r["medicine"], r["slot"]): bool(r["taken"]) for r in logs}
    out = []
    for m in list_medicines():
        for slot in sorted(m["slots"], key=SLOTS.get):
            due_at = datetime(day.year, day.month, day.day, SLOTS[slot], tzinfo=IST)
            key = (m["name"], slot)
            if key in latest:
                status = "taken" if latest[key] else "skipped"
            elif at >= due_at + timedelta(hours=GRACE_HOURS):
                status = "missed"
            elif at >= due_at:
                status = "due"
            else:
                status = "upcoming"
            out.append({"medicine": m["name"], "purpose": m["purpose"],
                        "slot": slot, "status": status})
    return out


# ---------- check-ins ----------

SYMPTOMS = {
    "chest pain": (["chest pain", "chest is hurting", "chest hurts", "chest tight",
                    "seene mein dard"], 3),
    "breathlessness": (["breathless", "can't breathe", "cannot breathe", "short of breath",
                        "saans"], 3),
    "a fall": (["i fell", "fell down", "had a fall", "slipped", "gir gayi", "gir gaya"], 3),
    "dizziness": (["dizzy", "dizziness", "chakkar", "lightheaded", "light headed", "giddy"], 2),
    "headache": (["headache", "head is hurting", "sir dard"], 1),
    "weakness": (["weak", "tired", "exhausted", "kamzori", "thakan"], 1),
    "fever": (["fever", "bukhar", "temperature"], 1),
    "low appetite": (["not hungry", "no appetite", "didn't eat", "did not eat", "bhook nahi"], 1),
    "poor sleep": (["couldn't sleep", "could not sleep", "no sleep", "neend nahi"], 1),
}
LOW_MOOD = ["lonely", "alone", "sad", "akela", "akeli", "udaas", "miss my", "bored", "nobody"]


def detect(text: str) -> tuple[list[str], int, str]:
    t = text.lower()
    found = [name for name, (keys, _) in SYMPTOMS.items() if any(k in t for k in keys)]
    severity = max((SYMPTOMS[n][1] for n in found), default=0)
    mood = "low" if any(k in t for k in LOW_MOOD) else "ok"
    return found, severity, mood


def record_checkin(text: str, at: datetime | None = None) -> dict:
    at = at or now()
    symptoms, severity, mood = detect(text)
    with db() as c:
        c.execute("INSERT INTO checkins(text, symptoms, mood, severity, at) VALUES (?, ?, ?, ?, ?)",
                  (text, json.dumps(symptoms), mood, severity, at.isoformat()))
    return {"symptoms": symptoms, "severity": severity, "mood": mood}


def checkins_since(since: datetime) -> list[dict]:
    with db() as c:
        rows = c.execute("SELECT text, symptoms, mood, severity, at FROM checkins "
                         "WHERE at >= ? ORDER BY at", (since.isoformat(),)).fetchall()
    return [{**dict(r), "symptoms": json.loads(r["symptoms"])} for r in rows]


# ---------- alerts ----------

def add_alert(level: str, message: str) -> None:
    with db() as c:
        c.execute("INSERT INTO alerts(level, message, at) VALUES (?, ?, ?)",
                  (level, message, now().isoformat()))


def recent_alerts(limit: int = 5) -> list[dict]:
    with db() as c:
        rows = c.execute("SELECT level, message, at FROM alerts ORDER BY id DESC LIMIT ?",
                         (limit,)).fetchall()
    return [dict(r) for r in rows]


# ---------- care requests (wait for family approval) ----------

SERVICES = {
    "doctor_home_visit": "a doctor's home visit",
    "home_lab_test": "a home blood test",
    "nurse_visit": "a nurse visit",
    "medicine_refill": "a medicine refill delivery",
    "grocery_delivery": "a grocery delivery",
}


def _request_row(r) -> dict:
    d = dict(r)
    d["booking"] = json.loads(d["booking"]) if d["booking"] else None
    d["service_spoken"] = SERVICES.get(d["service"], d["service"])
    return d


def create_request(service: str, reason: str) -> dict:
    rid = uuid.uuid4().hex[:6].upper()
    with db() as c:
        c.execute("INSERT INTO care_requests(id, service, reason, status, created_at) "
                  "VALUES (?, ?, ?, 'awaiting_family_approval', ?)",
                  (rid, service, reason, now().isoformat()))
    return get_request(rid)


def get_request(rid: str) -> dict | None:
    with db() as c:
        r = c.execute("SELECT * FROM care_requests WHERE id = ?", (rid.strip().upper(),)).fetchone()
    return _request_row(r) if r else None


def latest_request() -> dict | None:
    with db() as c:
        r = c.execute("SELECT * FROM care_requests ORDER BY created_at DESC LIMIT 1").fetchone()
    return _request_row(r) if r else None


def pending_requests() -> list[dict]:
    with db() as c:
        rows = c.execute("SELECT * FROM care_requests WHERE status = 'awaiting_family_approval' "
                         "ORDER BY created_at").fetchall()
    return [_request_row(r) for r in rows]


def decide_request(rid: str, approve: bool, by: str) -> dict | None:
    req = get_request(rid)
    if not req or req["status"] != "awaiting_family_approval":
        return req
    booking = None
    if approve:
        slot = (now() + timedelta(days=1)).replace(hour=10, minute=30, second=0, microsecond=0)
        booking = {"provider": "Partner network (simulated for the demo)",
                   "when": slot.isoformat(), "when_spoken": "tomorrow at 10:30 in the morning"}
    with db() as c:
        c.execute("UPDATE care_requests SET status = ?, decided_by = ?, decided_at = ?, booking = ? "
                  "WHERE id = ?",
                  ("booked" if approve else "declined", by, now().isoformat(),
                   json.dumps(booking) if booking else None, req["id"]))
    return get_request(req["id"])


# ---------- care-signal engine ----------

def assess(days: int = 7) -> dict:
    """Look across the last week and decide how worried the family should be, and why."""
    t = now()
    since_day = date.fromisoformat(get_profile().get("since", t.date().isoformat()))

    missed = []
    for i in range(days):
        day = t.date() - timedelta(days=i)
        if day < since_day:
            break
        for d in doses_for_day(day, t):
            if d["status"] in ("missed", "skipped"):
                missed.append({**d, "day": day.isoformat()})

    checks = checkins_since(t - timedelta(days=days))
    counts = Counter(s for ch in checks for s in ch["symptoms"])
    low_mood = sum(1 for ch in checks if ch["mood"] == "low")
    day_ago = (t - timedelta(hours=24)).isoformat()
    urgent = [ch for ch in checks if ch["severity"] >= 3 and ch["at"] >= day_ago]

    score, reasons = 0, []
    if missed:
        score += min(len(missed), 4)
        by_med = Counter(m["medicine"] for m in missed)
        top, n = by_med.most_common(1)[0]
        if len(by_med) > 1:
            reasons.append(f"{_n(len(missed), 'missed dose')} this week, {n} of them {top}.")
        else:
            reasons.append(f"{_n(n, 'missed dose')} of {top} this week.")
    for sym, n in counts.most_common():
        if n >= 2:
            score += n
            reasons.append(f"{sym.capitalize()} reported {n} times this week.")
    bp_missed = [m for m in missed if {"bp", "blood", "pressure"} & _words(m["purpose"])]
    if bp_missed and counts.get("dizziness", 0) >= 2:
        score += 3
        reasons.append("The dizziness is showing up in the same week as missed blood pressure "
                       "doses. That is worth a doctor's look.")
    if low_mood >= 2:
        score += 1
        reasons.append(f"Sounded low or lonely {_n(low_mood, 'time')} this week.")

    suggested = None
    if urgent:
        level, suggested = "urgent", "call_now"
        worst = sorted({s for u in urgent for s in u["symptoms"] if SYMPTOMS[s][1] >= 3})
        reasons.insert(0, f"Reported {join_words(worst)} in the last 24 hours.")
    elif score >= 6:
        level, suggested = "concern", "doctor_home_visit"
    elif score >= 3:
        level, suggested = "watch", "check_in_call"
    else:
        level = "stable"

    return {"level": level, "score": score, "reasons": reasons, "suggested_action": suggested,
            "symptom_counts": dict(counts), "low_mood_count": low_mood,
            "missed_doses": missed, "window_days": days}


# ---------- demo household ----------

def seed_demo() -> None:
    """Load a realistic week for the demo: Kamla Devi, 72, living alone in Jaipur."""
    with db() as c:
        for table in TABLES:
            c.execute(f"DROP TABLE IF EXISTS {table}")
    init_db()
    t = now()
    start = t.date() - timedelta(days=6)
    set_profile(parent_name="Kamla", parent_full_name="Kamla Devi", city="Jaipur",
                since=start.isoformat())
    with db() as c:
        c.executemany("INSERT INTO family(name, relation, city, is_primary) VALUES (?, ?, ?, ?)",
                      [("Rohan", "son", "Bengaluru", 1), ("Priya", "daughter", "Pune", 0)])
    add_medicine("Metformin", "diabetes sugar", ["morning", "night"])
    add_medicine("Amlodipine", "blood pressure bp", ["night"])
    add_medicine("Calcium", "bones calcium", ["afternoon"])

    skipped = {(1, "Amlodipine", "night"), (3, "Amlodipine", "night"),
               (4, "Amlodipine", "night"), (3, "Metformin", "night")}
    for ago in range(6, -1, -1):
        day = t.date() - timedelta(days=ago)
        for m in list_medicines():
            for slot in m["slots"]:
                if (ago, m["name"], slot) in skipped:
                    continue
                at = datetime(day.year, day.month, day.day, SLOTS[slot], 10, tzinfo=IST)
                if at > t:
                    continue
                log_dose(m["name"], slot, True, at)

    notes = {5: "Feeling fine today, went for a short walk",
             4: "A bit dizzy this morning when I got up",
             2: "Felt chakkar again while standing up",
             1: "Feeling lonely today, nobody called"}
    for ago, text in notes.items():
        day = t.date() - timedelta(days=ago)
        record_checkin(text, datetime(day.year, day.month, day.day, 11, 0, tzinfo=IST))


if __name__ == "__main__":
    if "--seed" in sys.argv:
        seed_demo()
        print("Demo household loaded for", get_profile()["parent_full_name"])
        print(json.dumps(assess(), indent=2))
    else:
        init_db()
        print("Database ready at", DB_PATH)
