from flask import Flask, jsonify
from flask_cors import CORS
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import pytz
import os
import concurrent.futures
import re

app = Flask(__name__)
CORS(app)

# Türkiye saat dilimi
LOCAL_TZ = pytz.timezone("Europe/Istanbul")

# --- Türk haber kaynakları --- #
RSS_SOURCES = {
    "milliyet": {
        "url": "https://www.milliyet.com.tr/rss/rssnew/anasayfa.xml",
        "logo": "/logos/milliyet.png",
        "color": "#1a76ff"
    },
    "hurriyet": {
        "url": "https://www.hurriyet.com.tr/rss/anasayfa",
        "logo": "/logos/hurriyet.png",
        "color": "#4100e6"
    },
    "sabah": {
        "url": "https://www.sabah.com.tr/rss/anasayfa.xml",
        "logo": "/logos/sabah.png",
        "color": "#d7881a"
    },
    "ntv": {
        "url": "https://www.ntv.com.tr/gundem.rss",
        "logo": "/logos/ntv.png",
        "color": "#006699"
    }
    
}


def parse_date(entry):
    """RSS/Atom tarihini güvenli şekilde İstanbul saatine çevir"""
    dt = None

    try:
        # Atom/RSS timestamp (struct_time formatı)
        if entry.get("published_parsed"):
            dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        elif entry.get("updated_parsed"):
            dt = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

        # Eğer string olarak varsa
        elif entry.get("published"):
            dt = parsedate_to_datetime(entry.published)
        elif entry.get("updated"):
            dt = parsedate_to_datetime(entry.updated)
    except Exception:
        dt = None

    # GUID içinde tarih
    if not dt:
        guid = entry.get("id") or entry.get("guid")
        if guid:
            match = re.search(r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})?", guid)
            if match:
                try:
                    year, month, day, hour, minute = match.groups(default="00")
                    dt = datetime(int(year), int(month), int(day),
                                  int(hour), int(minute), tzinfo=timezone.utc)
                except Exception:
                    pass

    # URL içinden tarih (saat/dakika → çekilme zamanı)
    if not dt:
        link = entry.get("link", "")
        match = re.search(r"(\d{4})[./-](\d{2})[./-](\d{2})", link)
        if match:
            try:
                year, month, day = match.groups()
                now = datetime.now(timezone.utc)
                dt = datetime(int(year), int(month), int(day),
                              now.hour, now.minute, tzinfo=timezone.utc)
            except Exception:
                pass

    # Hâlâ yoksa → çekilme zamanı
    if not dt:
        dt = datetime.now(timezone.utc)

    return dt.astimezone(LOCAL_TZ)


def fetch_single(source, info):
    """Tek bir kaynaktan haberleri getir"""
    items = []
    try:
        resp = requests.get(info["url"], timeout=10)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)

        for entry in feed.entries:
            # Görsel
            img_url = None
            if "enclosures" in entry and entry.enclosures:
                img_url = entry.enclosures[0].get("href")

            if not img_url and "description" in entry:
                soup = BeautifulSoup(entry.description, "html.parser")
                img_tag = soup.find("img")
                if img_tag and img_tag.get("src"):
                    img_url = img_tag["src"]

            pub_dt = parse_date(entry)

            items.append({
                "source": source,
                "source_logo": info["logo"],
                "source_color": info["color"],
                "title": entry.get("title", "Başlık Yok"),
                "link": entry.get("link", ""),
                "pubDate": entry.get("published", "") or entry.get("updated", ""),
                "published_at": pub_dt.isoformat(),  # ✅ İstanbul saati (+03:00)
                "published_at_ms": int(pub_dt.timestamp() * 1000),
                "description": BeautifulSoup(entry.get("description", ""), "html.parser").get_text() if "description" in entry else "",
                "image": img_url
            })
    except Exception as e:
        print(f"{info['url']} okunamadı:", e)

    return items


def fetch_rss():
    """Tüm kaynaklardan haberleri paralel çek"""
    items = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(fetch_single, source, info) for source, info in RSS_SOURCES.items()]
        for f in concurrent.futures.as_completed(futures):
            items.extend(f.result())

    # 🔥 İstanbul saatine göre sıralama (yeni → eski)
    items.sort(key=lambda x: x["published_at_ms"], reverse=True)
    return items


@app.route("/rss")
def get_rss():
    try:
        all_items = fetch_rss()
        return jsonify({
            "origin": os.environ.get("RAILWAY_STATIC_URL") or os.environ.get("RENDER", "local"),
            "total": len(all_items),
            "news": all_items
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
