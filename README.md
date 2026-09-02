# Tennis Tournament Desk

A local full-stack tournament front-desk application. The browser interface uses HTML, CSS and JavaScript; the API uses Python/FastAPI; tournament state is persisted in SQLite.

## Run locally

1. Open a terminal in this folder.
2. Create an environment: `python3 -m venv .venv`
3. Activate it: macOS/Linux `source .venv/bin/activate`; Windows PowerShell `.venv\\Scripts\\Activate.ps1`
4. Install packages: `pip install -r requirements.txt`
5. Start: `uvicorn app.main:app --reload`
6. Open: <http://127.0.0.1:8000>

The database file `tournament.db` is created automatically. Use **Load demo** for a quick test.

## Notes

- Each signup/team is stored as one object, including doubles teams.
- Availability blocks use exact date/time ranges.
- Scheduling uses 60-minute slots and respects blocked availability. Matches that cannot fit are left unscheduled for manual editing.
- Draws are single elimination, sized to the next power of two, with seed placement and byes given to the highest seeds first.

