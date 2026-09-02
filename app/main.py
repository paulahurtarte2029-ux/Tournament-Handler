from __future__ import annotations

import json
import math
import random
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "tournament.db"
STATIC = ROOT / "static"
app = FastAPI(title="Tennis Tournament Desk")


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")
    return c


def default_state():
    return {"tournament": None, "categories": [], "signups": [], "matches": []}


def load():
    with conn() as c:
        row = c.execute("SELECT data FROM state WHERE id=1").fetchone()
    return json.loads(row[0]) if row else default_state()


def save(data):
    with conn() as c:
        c.execute("INSERT INTO state(id,data) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (json.dumps(data),))
    return data


class State(BaseModel):
    tournament: dict[str, Any] | None = None
    categories: list[dict[str, Any]] = []
    signups: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []


def next_pow2(n):
    return 1 if n <= 1 else 2 ** math.ceil(math.log2(n))


def seed_order(size):
    order = [1, 2]
    while len(order) < size:
        target = len(order) * 2 + 1
        expanded = []
        for seed in order:
            expanded.extend([seed, target - seed])
        order = expanded
    return order


def blocked(signup, start, end):
    for b in signup.get("unavailable", []):
        try:
            if start < datetime.fromisoformat(b["end"]) and end > datetime.fromisoformat(b["start"]):
                return True
        except (KeyError, ValueError):
            continue
    return False


def generate(data):
    tournament = data.get("tournament")
    if not tournament:
        raise HTTPException(400, "Tournament setup is incomplete")
    all_matches = []
    rng = random.Random(tournament.get("drawSeed", 27))
    for category in data["categories"]:
        entrants = [s for s in data["signups"] if s["categoryId"] == category["id"]]
        if len(entrants) < 2:
            continue
        size = next_pow2(len(entrants))
        requested = min(int(category.get("seedCount", 0)), len(entrants))
        ranked = sorted([e for e in entrants if e.get("seed")], key=lambda e: e["seed"])
        seeded = ranked[:requested]
        unseeded = [e for e in entrants if e not in seeded]
        rng.shuffle(unseeded)
        positions = [None] * size
        order = seed_order(size)
        for entrant in seeded:
            seed = entrant["seed"]
            if 1 <= seed <= size:
                positions[order.index(seed)] = entrant["id"]
        byes = size - len(entrants)
        # Pair the first B seeds with byes; remaining entrants never occupy those opponent slots.
        reserved = set()
        for entrant in seeded[:byes]:
            pos = positions.index(entrant["id"])
            reserved.add(pos + 1 if pos % 2 == 0 else pos - 1)
        open_positions = [i for i, v in enumerate(positions) if v is None and i not in reserved]
        for pos, entrant in zip(open_positions, unseeded):
            positions[pos] = entrant["id"]
        rounds = int(math.log2(size))
        previous = []
        for r in range(1, rounds + 1):
            count = size // (2 ** r)
            current = []
            for i in range(count):
                mid = str(uuid.uuid4())
                if r == 1:
                    p1, p2 = positions[i * 2], positions[i * 2 + 1]
                else:
                    p1 = p2 = None
                m = {"id": mid, "categoryId": category["id"], "round": r, "index": i,
                     "player1Id": p1, "player2Id": p2, "source1": previous[i*2] if r > 1 else None,
                     "source2": previous[i*2+1] if r > 1 else None, "nextMatchId": None,
                     "status": "unscheduled", "date": None, "time": None, "court": None,
                     "score": "", "winnerId": None}
                all_matches.append(m); current.append(mid)
            if r > 1:
                for source in previous:
                    next(m for m in all_matches if m["id"] == source)["nextMatchId"] = current[previous.index(source)//2]
            previous = current
        # Auto-advance first-round byes.
        first = [m for m in all_matches if m["categoryId"] == category["id"] and m["round"] == 1]
        for m in first:
            players = [x for x in (m["player1Id"], m["player2Id"]) if x]
            if len(players) == 1:
                m["status"] = "bye"; m["winnerId"] = players[0]
                advance(all_matches, m)
    data["matches"] = all_matches
    schedule(data)
    return save(data)


def advance(matches, match):
    if not match.get("nextMatchId") or not match.get("winnerId"):
        return
    nxt = next((m for m in matches if m["id"] == match["nextMatchId"]), None)
    if not nxt: return
    if nxt.get("source1") == match["id"]: nxt["player1Id"] = match["winnerId"]
    if nxt.get("source2") == match["id"]: nxt["player2Id"] = match["winnerId"]


def schedule(data):
    t = data["tournament"]
    courts = t["courts"]
    signups = {s["id"]: s for s in data["signups"]}
    slots = []
    start_day = datetime.fromisoformat(t["startDate"])
    end_day = datetime.fromisoformat(t["endDate"])
    day = start_day
    while day.date() <= end_day.date():
        start = datetime.combine(day.date(), datetime.strptime(t["dailyStart"], "%H:%M").time())
        finish = datetime.combine(day.date(), datetime.strptime(t["dailyEnd"], "%H:%M").time())
        while start + timedelta(minutes=60) <= finish:
            for court in courts: slots.append((start, court))
            start += timedelta(minutes=60)
        day += timedelta(days=1)
    used = set()
    for m in sorted(data["matches"], key=lambda x: (x["round"], x["categoryId"])):
        if m["status"] == "bye" or not m["player1Id"] or not m["player2Id"]: continue
        for start, court in slots:
            key = (start.isoformat(), court)
            end = start + timedelta(minutes=60)
            if key in used or blocked(signups[m["player1Id"]], start, end) or blocked(signups[m["player2Id"]], start, end): continue
            m.update({"date": start.date().isoformat(), "time": start.strftime("%H:%M"), "court": court, "status": "scheduled"})
            used.add(key); break


@app.get("/api/state")
def get_state(): return load()


@app.put("/api/state")
def put_state(state: State): return save(state.model_dump())


@app.post("/api/generate")
def post_generate(state: State): return generate(state.model_dump())


@app.patch("/api/signups/{signup_id}/checkin")
def checkin(signup_id: str):
    data = load(); signup = next((s for s in data["signups"] if s["id"] == signup_id), None)
    if not signup: raise HTTPException(404, "Signup not found")
    signup["present"] = not signup.get("present", False)
    return save(data)


@app.patch("/api/matches/{match_id}")
def patch_match(match_id: str, changes: dict[str, Any]):
    data = load(); match = next((m for m in data["matches"] if m["id"] == match_id), None)
    if not match: raise HTTPException(404, "Match not found")
    allowed = {"status", "date", "time", "court", "score", "winnerId"}
    match.update({k: v for k, v in changes.items() if k in allowed})
    if match.get("status") == "completed":
        if not match.get("winnerId"): raise HTTPException(400, "Select a winner")
        advance(data["matches"], match)
    return save(data)


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index(): return FileResponse(STATIC / "index.html")

