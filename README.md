# Hamsika Tours & Travels

- `hamsika-tours.html` - website app (runs on Claude's hosted runtime: database and owner login come from there)
- `hamsika/` - Flask + SQLite version for your own server (`pip install -r requirements.txt && python app.py`)
- `fetch_packages.py` - collects packages from your own TravClan / SeatSeller agent login (Playwright; you enter the OTP)

Never commit passwords, OTPs, API keys, SECRET_KEY or the customer database.
