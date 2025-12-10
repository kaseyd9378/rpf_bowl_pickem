
# Bowl Pick'em (Pro) — Python/Flask

Scrapes the NCAA bowl schedule, converts kickoff times to **Pacific Time (PT)**, lets players make picks, and enforces CFP bracket dependencies with weighted scoring:
- First Round: **1** point per win
- Quarterfinals: **2** points
- Semifinals: **3** points
- National Championship: **4** points

Picks lock at kickoff (PT). CFP picks depend on earlier rounds.

## Quick start
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scrape.py  # Initialize DB, scrape NCAA, build CFP links
export SECRET_KEY='change-me'
flask --app app run --debug
```
Open http://127.0.0.1:5000

Default contest: **Bowl Pick'em 2025-26** (access: JOIN2025, admin: ADMIN2025)
