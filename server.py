from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import pytz
import os
import concurrent.futures
import re

app = Flask(__name__)
CORS(app)

# Türkiye saat dilimi
LOCAL_TZ = pytz.timezone("Europe/Istanbul")

# --- RSS Kaynakları kategorilere göre --- #
RSS_CATEGORIES = {
    "all": {
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
        "ntv": {
            "url": "https://www.ntv.com.tr/gundem.rss",
            "logo": "/logos/ntv.png",
            "color": "#006699"
        }
    },
    "breaking": {
        "milliyet": {
            "url": "http://www.milliyet.com.tr/rss/rssNew/SonDakikaRss.xml",
            "logo": "/logos/milliyet.png",
            "color": "#1a76ff"
        },
        "trthaber": {
            "url": "http://www.trthaber.com/sondakika.rss",
            "logo": "/logos/trthaber.png",
            "color": "#006699"
        },
        "mynet": {
            "url": "http://www.mynet.com/haber/rss/sondakika",
            "logo": "/logos/mynet.png",
            "color": "#ff6600"
        },
        "ntv": {
            "url": "https://www.ntv.com.tr/gundem.rss",
            "logo": "/logos/ntv.png",
            "color": "#006699"
        }
    }
}


def parse_date(entry):
    """RSS/Atom tarihini güvenli şekilde İstanbul saatine çevir"""
    dt = None

    try:
        if entry.get("published_parsed"):
            dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        elif entry.get("updated_parsed"):
            dt = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
        elif entry.get("published"):
            dt = parsedate_to_datetime(entry.published)
        elif entry.get("updated"):
            dt = parsedate_to_datetime(entry.updated)
    except Exception:
        dt = None

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
            img_url = None

            # 1) enclosure varsa önce onu dene
            if "enclosures" in entry and entry.enclosures:
                img_url = entry.enclosures[0].get("href")

            # 2) media:content varsa (TRT, NTV gibi kaynaklar için)
            if not img_url and "media_content" in entry and entry.media_content:
                img_url = entry.media_content[0].get("url")

            # 3) description içindeki <img>
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
                "published_at": pub_dt.isoformat(),
                "published_at_ms": int(pub_dt.timestamp() * 1000),
                "description": BeautifulSoup(entry.get("description", ""), "html.parser").get_text() if "description" in entry else "",
                "image": img_url
            })
    except Exception as e:
        print(f"{info['url']} okunamadı:", e)

    return items



def fetch_rss(category="all"):
    """Kategoriye göre RSS çek"""
    items = []
    sources = RSS_CATEGORIES.get(category, RSS_CATEGORIES["all"])

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(fetch_single, source, info) for source, info in sources.items()]
        for f in concurrent.futures.as_completed(futures):
            items.extend(f.result())

    # Sıralama: en yeni → en eski
    items.sort(key=lambda x: x["published_at_ms"], reverse=True)

    # 🔥 Tarih filtresi: breaking = 2 gün, diğerleri = 7 gün
    now = datetime.now(LOCAL_TZ)
    if category == "breaking":
        cutoff = now - timedelta(days=2)
    else:
        cutoff = now - timedelta(days=7)

    items = [
        i for i in items
        if datetime.fromtimestamp(i["published_at_ms"]/1000, LOCAL_TZ) >= cutoff
    ]

    return items


@app.route("/rss")
def get_rss():
    try:
        category = request.args.get("category", "all")
        all_items = fetch_rss(category)
        return jsonify({
            "origin": os.environ.get("RAILWAY_STATIC_URL") or os.environ.get("RENDER", "local"),
            "category": category,
            "total": len(all_items),
            "news": all_items
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
