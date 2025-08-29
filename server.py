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

app = Flask(__name__)
CORS(app)

# Türkiye saat dilimi
LOCAL_TZ = pytz.timezone("Europe/Istanbul")

# --- Türk haber kaynakları --- #
RSS_SOURCES = {
    "milliyet": {
        "url": "https://www.milliyet.com.tr/rss/rssnew/anasayfa.xml",
        "logo": "/logos/milliyet.png",
        "color": "#ff1a1a"
    },
    "hurriyet": {
        "url": "https://www.hurriyet.com.tr/rss/anasayfa",
        "logo": "/logos/hurriyet.png",
        "color": "#e60000"
    },
    "sabah": {
        "url": "https://www.sabah.com.tr/rss/anasayfa.xml",
        "logo": "/logos/sabah.png",
        "color": "#d71a28"
    },
    "ntv": {
        "url": "https://www.ntv.com.tr/gundem.rss",
        "logo": "/logos/ntv.png",
        "color": "#006699"
    }
}


def parse_date(entry):
    """RSS tarihini güvenli şekilde İstanbul saatine çevir"""
    dt = None
    try:
        if hasattr(entry, "published") and entry.published:
            dt = parsedate_to_datetime(entry.published)
        elif hasattr(entry, "updated") and entry.updated:
            dt = parsedate_to_datetime(entry.updated)
    except Exception:
        dt = None

    if not dt:
        # Tarih yoksa şu anki zaman
        return datetime.now(LOCAL_TZ)

    # Eğer timezone yoksa UTC kabul et
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # Son olarak İstanbul’a çevir
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
