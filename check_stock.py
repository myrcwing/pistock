#!/usr/bin/env python3
"""Pi stock checker for Pockle.
Reads RPilocator RSS feeds (approved retailers only), filters by price and
blocked sites, writes stock.json, and sends a phone alert (ntfy.sh) for NEW stock.
Standard library only. Run:  python check_stock.py   (add --dry to skip alerts)
"""
import json, re, sys, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

DRY = "--dry" in sys.argv
cfg = json.load(open("config.json"))
try:
    old = json.load(open("stock.json"))
    old_keys = {i["store"] + i["model"] for i in old.get("items", [])}
except Exception:
    old_keys = set()

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pockle-stock/1.0 (personal use)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()

items = []
for cat, m in cfg["models"].items():
    url = "https://rpilocator.com/feed/?" + urllib.parse.urlencode(
        {"country": cfg["country"], "cat": cat})
    raw = ""
    try:
        raw = get(url).decode("utf-8", "replace").strip()
        end = raw.find("</rss>")          # ignore anything after the feed ends
        if end >= 0:
            raw = raw[: end + 6]
        root = ET.fromstring(raw.encode("utf-8"))
    except Exception as e:
        print(f"[warn] {cat}: {e}")
        print("   feed starts with:", raw[:200].replace("\n", " "))
        continue
    print(f"[info] {cat}: {len(list(root.iter('item')))} feed items")
    for it in root.iter("item"):
        try:
            age = datetime.now(timezone.utc) - parsedate_to_datetime(it.findtext("pubDate") or "")
            if age.total_seconds() > cfg.get("max_age_hours", 12) * 3600:
                continue                  # old alert: probably sold out by now
        except Exception:
            pass
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or "")
        text = f"{title} {desc} {link}".lower()
        if any(w in text for w in cfg["blocked_words"]):
            continue
        if "out of stock" in text:
            continue
        pm = re.search(r"\$\s?(\d+(?:\.\d{2})?)", f"{title} {desc}")
        price = float(pm.group(1)) if pm else None
        if price is not None and price > m["max_price"]:
            continue  # above retail ceiling
        store = re.sub(r"^.*?:\s*", "", title).split(" has ")[0].split(" - ")[0][:18]
        items.append({"store": store, "model": m["label"], "price": price,
                      "url": link})

items.sort(key=lambda i: (i["price"] is None, i["price"] or 0))
items = items[: cfg["max_items"]]
out = {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
       "items": items}
json.dump(out, open("stock.json", "w"), indent=1)
print(json.dumps(out, indent=1))

new = [i for i in items if i["store"] + i["model"] not in old_keys]
if new and not DRY and not cfg["ntfy_topic"].startswith("CHANGE-ME"):
    for i in new:
        p = f"${i['price']:.2f}" if i["price"] else "price not listed"
        msg = f"{i['model']} in stock at {i['store']} ({p})"
        req = urllib.request.Request(
            "https://ntfy.sh/" + cfg["ntfy_topic"], data=msg.encode(),
            headers={"Title": "Pi in stock!", "Click": i["url"]})
        try:
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            print("[warn] alert failed:", e)
