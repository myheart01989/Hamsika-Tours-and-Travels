"""Hamsika Tours & Travels - Flask + SQLite (SQL) web app.
Run:  pip install -r requirements.txt && python app.py   ->  http://localhost:5000
Admin: /admin  (username: admin). Password is stored only as a salted PBKDF2-SHA256 hash.
Optional env: SECRET_KEY, AMADEUS_ID, AMADEUS_SECRET (flight offers)."""
import os, json, sqlite3, urllib.request, urllib.parse
from flask import Flask, g, request, session, redirect, url_for, render_template_string, flash
from werkzeug.security import check_password_hash
from jinja2 import DictLoader

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
DB = os.path.join(os.path.dirname(__file__), "hamsika.db")
ADMIN_HASH = "pbkdf2:sha256:600000$zD83iqQy5tDIulBh$b11683e7d639a090fc4a599bc19948d0501a1a020cd6bad099f5107531435901"

PACKAGES = [
 ("Goa Beach Escape","domestic","Goa",4,18999,"Beach resort stay, sightseeing, airport transfers"),
 ("Kerala Backwaters","domestic","Kerala",5,24999,"Houseboat, Munnar tea hills, Alleppey"),
 ("Royal Rajasthan","domestic","Rajasthan",6,32999,"Jaipur, Jodhpur, Udaipur with heritage hotels"),
 ("Kashmir Paradise","domestic","Kashmir",5,29999,"Srinagar, Gulmarg, Pahalgam, shikara ride"),
 ("Dubai Delight","international","Dubai",5,54999,"Desert safari, Burj Khalifa, city tour, visa help"),
 ("Singapore & Malaysia","international","Singapore",6,69999,"Sentosa, Gardens by the Bay, Kuala Lumpur"),
 ("Bali Bliss","international","Bali",5,62999,"Villas, temples, beaches, Ubud tour"),
 ("Thailand Treat","international","Bangkok",5,44999,"Bangkok & Pattaya, island hop, city tours"),
]
SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT);
CREATE TABLE IF NOT EXISTS packages(id INTEGER PRIMARY KEY, name TEXT, type TEXT, destination TEXT, nights INT, price_inr INT, highlights TEXT);
CREATE TABLE IF NOT EXISTS enquiries(id INTEGER PRIMARY KEY, created TEXT DEFAULT CURRENT_TIMESTAMP, name TEXT, email TEXT, phone TEXT, package_id INT, travellers INT, travel_date TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS flight_requests(id INTEGER PRIMARY KEY, created TEXT DEFAULT CURRENT_TIMESTAMP, name TEXT, email TEXT, phone TEXT, origin TEXT, destination TEXT, depart TEXT, ret TEXT, passengers INT);
CREATE TABLE IF NOT EXISTS hotel_requests(id INTEGER PRIMARY KEY, created TEXT DEFAULT CURRENT_TIMESTAMP, name TEXT, email TEXT, phone TEXT, city TEXT, checkin TEXT, checkout TEXT, guests INT);
CREATE TABLE IF NOT EXISTS currency_requests(id INTEGER PRIMARY KEY, created TEXT DEFAULT CURRENT_TIMESTAMP, name TEXT, phone TEXT, from_cur TEXT, to_cur TEXT, amount REAL, rate REAL, result REAL);
"""
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db
@app.teardown_appcontext
def close(e):
    d = g.pop("db", None)
    if d: d.close()
def init():
    c = sqlite3.connect(DB); c.executescript(SCHEMA)
    c.execute("INSERT OR IGNORE INTO admin_users(username,password_hash) VALUES('admin',?)", (ADMIN_HASH,))
    if not c.execute("SELECT 1 FROM packages").fetchone():
        c.executemany("INSERT INTO packages(name,type,destination,nights,price_inr,highlights) VALUES(?,?,?,?,?,?)", PACKAGES)
    c.commit(); c.close()

def http_json(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {"User-Agent": "HamsikaTours/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r: return json.load(r)

# ---------- Open-source / open-API connectors ----------
def fx(frm, to, amt):               # Frankfurter (open source, ECB rates)
    d = http_json(f"https://api.frankfurter.dev/v1/latest?base={frm}&symbols={to}")
    rate = d["rates"][to]; return rate, round(rate * amt, 2)
def hotels_osm(city):               # Nominatim + Overpass (OpenStreetMap, open data)
    geo = http_json("https://nominatim.openstreetmap.org/search?format=json&limit=1&q=" + urllib.parse.quote(city))
    if not geo: return []
    lat, lon = geo[0]["lat"], geo[0]["lon"]
    q = f'[out:json][timeout:15];node["tourism"~"hotel|guest_house|hostel"]["name"](around:6000,{lat},{lon});out 15;'
    d = http_json("https://overpass-api.de/api/interpreter", data=urllib.parse.urlencode({"data": q}).encode())
    return [{"name": e["tags"]["name"], "type": e["tags"].get("tourism"), "stars": e["tags"].get("stars", "-"), "phone": e["tags"].get("phone", "")} for e in d["elements"]]
def flights_amadeus(o, d, dep, pax):  # Amadeus Self-Service API (free test tier); needs AMADEUS_ID/SECRET
    cid, sec = os.environ.get("AMADEUS_ID"), os.environ.get("AMADEUS_SECRET")
    if not cid: return None
    t = http_json("https://test.api.amadeus.com/v1/security/oauth2/token", urllib.parse.urlencode(
        {"grant_type": "client_credentials", "client_id": cid, "client_secret": sec}).encode())["access_token"]
    qs = urllib.parse.urlencode({"originLocationCode": o.upper(), "destinationLocationCode": d.upper(), "departureDate": dep, "adults": pax, "max": 8})
    r = http_json("https://test.api.amadeus.com/v2/shopping/flight-offers?" + qs, headers={"Authorization": "Bearer " + t})
    return [{"price": f'{x["price"]["total"]} {x["price"]["currency"]}', "airline": x["validatingAirlineCodes"][0],
             "stops": len(x["itineraries"][0]["segments"]) - 1} for x in r.get("data", [])]

# ---------- Templates ----------
BASE = """<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{{ title or 'Hamsika Tours & Travels' }}</title><style>
:root{--c:#0b6e8a;--d:#08475a;--a:#f59e0b;--bg:#f6f9fb;--t:#16252d}*{box-sizing:border-box}
body{margin:0;font-family:system-ui,Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--t)}
nav{background:var(--d);display:flex;flex-wrap:wrap;align-items:center;gap:6px 18px;padding:12px 5%}
nav b{color:#fff;font-size:1.2rem;margin-right:auto}nav a{color:#d6eef5;text-decoration:none}nav a:hover{color:var(--a)}
.hero{background:linear-gradient(135deg,var(--c),var(--d));color:#fff;padding:60px 5%;text-align:center}
.hero h1{margin:0 0 8px;font-size:clamp(1.8rem,5vw,3rem)}main{padding:30px 5%;max-width:1100px;margin:auto}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:18px}
.card{background:#fff;border-radius:12px;padding:18px;box-shadow:0 2px 10px #0001}.tag{background:var(--a);color:#000;border-radius:20px;padding:2px 10px;font-size:.75rem}
.price{font-size:1.3rem;color:var(--c);font-weight:700}input,select,textarea{width:100%;padding:10px;margin:4px 0 10px;border:1px solid #bcd;border-radius:8px;font:inherit}
button,.btn{background:var(--c);color:#fff;border:0;border-radius:8px;padding:10px 18px;cursor:pointer;text-decoration:none;display:inline-block}
.f{background:#fff;border-radius:12px;padding:20px;max-width:520px;box-shadow:0 2px 10px #0001}.ok{background:#d7f5e0;padding:10px;border-radius:8px;margin-bottom:12px}
table{border-collapse:collapse;width:100%;background:#fff;font-size:.85rem}th,td{padding:7px;border:1px solid #dde;text-align:left}.sc{overflow-x:auto;margin-bottom:24px}
footer{text-align:center;padding:24px;color:#567}</style></head><body>
<nav><b>✈ Hamsika Tours &amp; Travels</b><a href="/">Home</a><a href="/packages">Packages</a><a href="/flights">Flights</a><a href="/hotels">Hotels</a><a href="/currency">Currency Exchange</a><a href="/contact">Contact</a><a href="/admin">Admin</a></nav>
{% block body %}{% endblock %}<footer>© Hamsika Tours &amp; Travels · Domestic &amp; International Travel</footer></body></html>"""

HOME = """{% extends 'base' %}{% block body %}<div class=hero><h1>Explore India &amp; the World</h1>
<p>Domestic &amp; international packages · Flights · Hotels · Currency exchange</p><a class=btn style="background:var(--a);color:#000" href="/packages">View Packages</a></div>
<main><h2>Popular Packages</h2><div class=grid>{% for p in pk %}{% include 'card' %}{% endfor %}</div></main>{% endblock %}"""
CARD = """<div class=card><span class=tag>{{ p.type }}</span><h3>{{ p.name }}</h3><p>{{ p.destination }} · {{ p.nights }}N/{{ p.nights+1 }}D</p><p>{{ p.highlights }}</p>
<div class=price>₹{{ '{:,}'.format(p.price_inr) }} <small>/person</small></div><br><a class=btn href="/enquire/{{ p.id }}">Enquire / Book</a></div>"""
PKGS = """{% extends 'base' %}{% block body %}<main><h2>Domestic Packages</h2><div class=grid>{% for p in pk if p.type=='domestic' %}{% include 'card' %}{% endfor %}</div>
<h2>International Packages</h2><div class=grid>{% for p in pk if p.type=='international' %}{% include 'card' %}{% endfor %}</div></main>{% endblock %}"""
ENQ = """{% extends 'base' %}{% block body %}<main><div class=f><h2>Enquire: {{ p.name }}</h2>{% for m in get_flashed_messages() %}<div class=ok>{{ m }}</div>{% endfor %}
<form method=post>Name<input name=name required>Email<input type=email name=email required>Phone<input name=phone required>
Travellers<input type=number name=travellers value=2 min=1>Travel date<input type=date name=travel_date>Message<textarea name=message></textarea><button>Submit</button></form></div></main>{% endblock %}"""
FORM = """{% extends 'base' %}{% block body %}<main><div class=f><h2>{{ heading }}</h2>{% for m in get_flashed_messages() %}<div class=ok>{{ m }}</div>{% endfor %}
<form method=post>Name<input name=name required>Email<input type=email name=email>Phone<input name=phone required>{{ fields|safe }}<button>{{ btn }}</button></form></div>
{% if results %}<h3>Results</h3><div class=sc><table><tr>{% for k in results[0] %}<th>{{ k }}</th>{% endfor %}</tr>{% for r in results %}<tr>{% for v in r.values() %}<td>{{ v }}</td>{% endfor %}</tr>{% endfor %}</table></div>{% endif %}
{% if note %}<p>{{ note }}</p>{% endif %}</main>{% endblock %}"""
LOGIN = """{% extends 'base' %}{% block body %}<main><div class=f><h2>Admin Login</h2>{% for m in get_flashed_messages() %}<div class=ok>{{ m }}</div>{% endfor %}
<form method=post>Username<input name=u required>Password<input type=password name=p required><button>Login</button></form></div></main>{% endblock %}"""
ADMIN = """{% extends 'base' %}{% block body %}<main><h2>Admin Dashboard <a class=btn href="/admin/logout" style="float:right">Logout</a></h2>
{% for t, rows in data.items() %}<h3>{{ t }} ({{ rows|length }})</h3><div class=sc>{% if rows %}<table><tr>{% for k in rows[0].keys() %}<th>{{ k }}</th>{% endfor %}</tr>
{% for r in rows %}<tr>{% for v in r %}<td>{{ v }}</td>{% endfor %}</tr>{% endfor %}</table>{% else %}<p>No records yet.</p>{% endif %}</div>{% endfor %}</main>{% endblock %}"""
app.jinja_loader = DictLoader({"base": BASE, "home": HOME, "card": CARD, "pkgs": PKGS, "enq": ENQ, "form": FORM, "login": LOGIN, "admin": ADMIN})
R = render_template_string
def save(sql, vals): db().execute(sql, vals); db().commit()
def F(*k): return [request.form.get(x, "").strip() for x in k]

@app.route("/")
def home(): return R("{% include 'home' %}", pk=db().execute("SELECT * FROM packages LIMIT 6").fetchall())
@app.route("/packages")
def packages(): return R("{% include 'pkgs' %}", pk=db().execute("SELECT * FROM packages").fetchall())
@app.route("/enquire/<int:pid>", methods=["GET", "POST"])
def enquire(pid):
    p = db().execute("SELECT * FROM packages WHERE id=?", (pid,)).fetchone() or ("", 404)
    if request.method == "POST":
        save("INSERT INTO enquiries(name,email,phone,package_id,travellers,travel_date,message) VALUES(?,?,?,?,?,?,?)", [*F("name", "email", "phone"), pid, *F("travellers", "travel_date", "message")])
        flash("Thank you! Our team will contact you shortly."); return redirect(request.url)
    return R("{% include 'enq' %}", p=p)
@app.route("/flights", methods=["GET", "POST"])
def flights():
    res = note = None
    if request.method == "POST":
        n, e, ph, o, d, dep, ret, px = F("name", "email", "phone", "origin", "destination", "depart", "ret", "pax")
        save("INSERT INTO flight_requests(name,email,phone,origin,destination,depart,ret,passengers) VALUES(?,?,?,?,?,?,?,?)", [n, e, ph, o, d, dep, ret, px])
        try:
            res = flights_amadeus(o, d, dep, px or 1)
            note = None if res else "Request saved. Our agent will email fares (set AMADEUS_ID/AMADEUS_SECRET for live offers)."
        except Exception: note = "Request saved. Live fares unavailable right now; we will contact you."
    fields = '<input name=origin placeholder="From (IATA e.g. HYD)" required><input name=destination placeholder="To (e.g. DXB)" required>Depart<input type=date name=depart required>Return<input type=date name=ret>Passengers<input type=number name=pax value=1 min=1>'
    return R("{% include 'form' %}", heading="Flight Tickets (Domestic & International)", fields=fields, btn="Search & Request", results=res, note=note)
@app.route("/hotels", methods=["GET", "POST"])
def hotels():
    res = note = None
    if request.method == "POST":
        n, e, ph, city, ci, co, gs = F("name", "email", "phone", "city", "checkin", "checkout", "guests")
        save("INSERT INTO hotel_requests(name,email,phone,city,checkin,checkout,guests) VALUES(?,?,?,?,?,?,?)", [n, e, ph, city, ci, co, gs])
        try: res = hotels_osm(city) or None
        except Exception: pass
        note = "Request saved. Hotel list from OpenStreetMap; we will send rates & availability."
    fields = '<input name=city placeholder="City (domestic or international)" required>Check-in<input type=date name=checkin>Check-out<input type=date name=checkout>Guests<input type=number name=guests value=2 min=1>'
    return R("{% include 'form' %}", heading="Hotels & Accommodation", fields=fields, btn="Find Hotels", results=res, note=note)
@app.route("/currency", methods=["GET", "POST"])
def currency():
    note = None
    if request.method == "POST":
        n, ph, a, b, amt = F("name", "phone", "frm", "to", "amount")
        try:
            rate, out = fx(a.upper(), b.upper(), float(amt))
            save("INSERT INTO currency_requests(name,phone,from_cur,to_cur,amount,rate,result) VALUES(?,?,?,?,?,?,?)", [n, ph, a.upper(), b.upper(), float(amt), rate, out])
            note = f"{amt} {a.upper()} = {out} {b.upper()} (rate {rate}, indicative ECB rate). Visit/contact us to exchange."
        except Exception: note = "Invalid currency or rate service unavailable."
    fields = 'From<input name=frm value=INR maxlength=3>To<input name=to value=USD maxlength=3>Amount<input type=number step=any name=amount value=10000>'
    return R("{% include 'form' %}", heading="Currency Exchange", fields=fields, btn="Convert & Save", note=note)
@app.route("/contact")
def contact(): return R("{% extends 'base' %}{% block body %}<main><div class=f><h2>Contact Hamsika Tours &amp; Travels</h2><p>Use the Packages, Flights, Hotels or Currency pages: every request is saved and our team will reach out.</p></div></main>{% endblock %}")
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        u, p = F("u", "p")
        row = db().execute("SELECT password_hash FROM admin_users WHERE username=?", (u,)).fetchone()
        if row and check_password_hash(row[0], p): session["admin"] = True; return redirect("/admin")
        flash("Invalid credentials.")
    if not session.get("admin"): return R("{% include 'login' %}")
    t = {"Enquiries": "enquiries", "Flight requests": "flight_requests", "Hotel requests": "hotel_requests", "Currency requests": "currency_requests", "Packages": "packages"}
    return R("{% include 'admin' %}", data={k: db().execute(f"SELECT * FROM {v} ORDER BY id DESC").fetchall() for k, v in t.items()})
@app.route("/admin/logout")
def logout(): session.clear(); return redirect("/")

init()
if __name__ == "__main__": app.run(debug=False)
