"""
Collect package data from YOUR OWN agent login on TravClan / SeatSeller.

Setup (once):
    pip install playwright
    playwright install chromium

Run:
    python fetch_packages.py --site TravClan --url <login page URL> --phone 9493936084
    python fetch_packages.py --site SeatSeller --url <login page URL> --phone 9493936084

What happens:
  1. A browser window opens and the script types your mobile number.
  2. When the site sends an OTP, the script asks YOU in this terminal. Type it in.
     (If auto-fill fails you can log in by hand in the browser window.)
  3. You open the package list page in that browser, then press Enter here.
  4. The script reads package data the page loaded (JSON first, then page text of
     each package link) and writes:
        packages.csv        -> paste into Admin > Packages > Import CSV on the website
        packages_full.json  -> everything, including itinerary and the package link

Your OTP/password is never saved. Check each portal's terms of use and keep
automated browsing light (this script waits between pages).
NOTE: written without access to the live portals, so field names/buttons are
matched by common patterns. If a field comes out empty, send me packages_full.json
or a screenshot and I will tune the matching.
"""
import argparse, csv, json, re, time
from playwright.sync_api import sync_playwright

INDIA = {"india", "goa", "kerala", "kashmir", "rajasthan", "manali", "shimla", "ladakh", "andaman",
         "sikkim", "darjeeling", "himachal", "uttarakhand", "mysore", "ooty", "munnar", "agra", "delhi"}
K_NAME = ("packagename", "package_name", "title", "name", "heading")
K_PRICE = ("startingprice", "starting_price", "price", "amount", "cost", "totalprice", "sellingprice")
K_NIGHTS = ("nights", "noofnights", "no_of_nights", "duration", "days", "noofdays")
K_DEST = ("destination", "destinations", "city", "location", "place", "country")
K_ITIN = ("itinerary", "itineraries", "dayplan", "day_plan", "plan", "schedule")
K_HIGH = ("highlights", "inclusions", "summary", "overview", "description", "shortdescription")
K_LINK = ("url", "link", "slug", "permalink", "href")


def norm(k):
    return re.sub(r"[^a-z_]", "", str(k).lower())


def pick(d, keys):
    low = {norm(k): v for k, v in d.items()}
    for k in keys:
        if k in low and low[k] not in (None, "", [], {}):
            return low[k]
    return None


def num(v):
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"[\d,]+(?:\.\d+)?", str(v or ""))
    return int(float(m.group(0).replace(",", ""))) if m else 0


def text(v, limit=400):
    if isinstance(v, list):
        v = "; ".join(text(x, 120) for x in v)
    elif isinstance(v, dict):
        v = "; ".join(text(x, 120) for x in v.values() if isinstance(x, (str, int, float)))
    v = re.sub(r"<[^>]+>", " ", str(v or ""))
    return re.sub(r"\s+", " ", v).strip()[:limit]


def itinerary(v):
    if not v:
        return ""
    if isinstance(v, list):
        out = []
        for i, d in enumerate(v, 1):
            if isinstance(d, dict):
                t = pick(d, ("title", "heading", "name", "day")) or ""
                desc = pick(d, ("description", "details", "text", "summary")) or ""
                out.append(f"Day {i}: {text(t, 80)} {text(desc, 250)}".strip())
            else:
                out.append(f"Day {i}: {text(d, 250)}")
        return " | ".join(out)
    return text(v, 3000)


def looks_like_package(d):
    if not isinstance(d, dict):
        return False
    return pick(d, K_NAME) is not None and pick(d, K_PRICE) is not None


def walk(o, found):
    if isinstance(o, dict):
        if looks_like_package(o):
            found.append(o)
        for v in o.values():
            walk(v, found)
    elif isinstance(o, list):
        for v in o:
            walk(v, found)


def to_row(d, source, base):
    dest = text(pick(d, K_DEST), 60)
    country = text(d.get("country") or d.get("countryName") or "", 40).lower()
    intl = (country and country != "india") or bool(d.get("isInternational") or d.get("international"))
    if not country and dest:
        intl = not any(w in dest.lower() for w in INDIA)
    link = text(pick(d, K_LINK), 300)
    if link and link.startswith("/"):
        link = base + link
    return {
        "name": text(pick(d, K_NAME), 100),
        "type": "international" if intl else "domestic",
        "destination": dest,
        "nights": num(pick(d, K_NIGHTS)),
        "price": num(pick(d, K_PRICE)),
        "source": source,
        "highlights": text(pick(d, K_HIGH), 200),
        "itinerary": itinerary(pick(d, K_ITIN)),
        "link": link,
    }


def try_fill(page, sels, value):
    for s in sels:
        loc = page.locator(s).first
        try:
            if loc.count() and loc.is_visible():
                loc.fill(value)
                return True
        except Exception:
            pass
    return False


def click_btn(page, pattern):
    try:
        page.get_by_role("button", name=re.compile(pattern, re.I)).first.click(timeout=4000)
        return True
    except Exception:
        return False


def login(page, phone):
    ok = try_fill(page, ["input[type=tel]", "input[name*=mobile i]", "input[name*=phone i]",
                         "input[placeholder*=mobile i]", "input[placeholder*=phone i]", "input[type=text]"], phone)
    click_btn(page, r"send otp|get otp|request otp|continue|login|sign in|next")
    if not ok:
        print("Could not find the mobile field - please log in by hand in the browser window.")
        return
    otp = input("Enter the OTP you received (or press Enter if you will type it in the browser): ").strip()
    if otp:
        boxes = page.locator("input[maxlength='1']")
        if boxes.count() >= 4:
            for i, ch in enumerate(otp[: boxes.count()]):
                boxes.nth(i).fill(ch)
        else:
            try_fill(page, ["input[name*=otp i]", "input[placeholder*=otp i]", "input[autocomplete=one-time-code]",
                            "input[type=tel]", "input[type=text]"], otp)
        click_btn(page, r"verify|submit|login|sign in|continue")
    time.sleep(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True, choices=["TravClan", "SeatSeller"])
    ap.add_argument("--url", required=True, help="login page URL of the portal")
    ap.add_argument("--phone", required=True)
    ap.add_argument("--max", type=int, default=40, help="max package pages to open")
    a = ap.parse_args()
    base = re.match(r"https?://[^/]+", a.url).group(0)
    captured, rows = [], {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_context().new_page()

        def on_resp(r):
            try:
                if "json" in (r.headers.get("content-type") or ""):
                    captured.append(r.json())
            except Exception:
                pass

        page.on("response", on_resp)
        page.goto(a.url)
        login(page, a.phone)
        input("\nLog in is done? Now open your PACKAGE LIST page in the browser (scroll to load all), then press Enter here... ")
        time.sleep(2)

        # 1) package-like objects from JSON the portal itself loaded
        found = []
        for c in captured:
            walk(c, found)
        for d in found:
            r = to_row(d, a.site, base)
            if r["name"]:
                rows[(r["name"], r["price"])] = r

        # 2) fallback / enrich: open each package link and read the page text
        links = page.eval_on_selector_all(
            "a[href]", "els => [...new Set(els.map(e => e.href))]")
        links = [l for l in links if re.search(r"package|holiday|tour|itinerar", l, re.I)][: a.max]
        for l in links:
            try:
                page.goto(l, wait_until="domcontentloaded")
                time.sleep(1.5)
                body = page.inner_text("body")
                name = (page.locator("h1").first.inner_text() if page.locator("h1").count() else "").strip()
                price = num(re.search(r"₹\s?[\d,]+", body).group(0)) if re.search(r"₹\s?[\d,]+", body) else 0
                n = re.search(r"(\d+)\s*N(?:ights?)?", body)
                days = re.findall(r"(Day\s*\d+[^\n]*(?:\n[^\n]+){0,2})", body)
                if name:
                    key = (name, price)
                    r = rows.get(key) or {"name": name, "type": "domestic", "destination": "", "nights": 0,
                                          "price": price, "source": a.site, "highlights": "", "itinerary": "", "link": l}
                    r["link"] = r["link"] or l
                    r["nights"] = r["nights"] or (int(n.group(1)) if n else 0)
                    if not r["itinerary"] and days:
                        r["itinerary"] = " | ".join(re.sub(r"\s+", " ", x) for x in days)[:3000]
                    rows[key] = r
            except Exception as e:
                print("skip", l, e)
        browser.close()

    data = list(rows.values())
    with open("packages_full.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    clean = lambda s: str(s).replace(",", ";").replace("\n", " ")
    with open("packages.csv", "w", encoding="utf-8", newline="") as f:
        f.write("name,type,destination,nights,price,source,highlights\n")
        for r in data:
            f.write(",".join(clean(r[k]) for k in ("name", "type", "destination", "nights", "price", "source", "highlights")) + "\n")
    print(f"\nDone: {len(data)} packages -> packages.csv (website import) and packages_full.json (with itinerary and links)")
    print("Review the 'type' column (domestic/international) before importing.")


if __name__ == "__main__":
    main()
