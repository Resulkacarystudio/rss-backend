from flask import Flask, jsonify
from flask_cors import CORS
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import pytz

from email.utils import parsedate_to_datetime
import pytz
app = Flask(__name__)
CORS(app)

# Türkiye saati
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
    "cnnturk": {
        "url": "https://www.cnnturk.com/feed/rss/all/news",
        "logo": "/logos/cnnturk.png",
        "color": "#cc0000"
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
    from email.utils import parsedate_to_datetime
    from datetime import datetime, timedelta
    import pytz

    LOCAL_TZ = pytz.timezone("Europe/Istanbul")
    dt = None
    try:
        if "published" in entry and entry.published:
            dt = parsedate_to_datetime(entry.published)
        elif "updated" in entry and entry.updated:
            dt = parsedate_to_datetime(entry.updated)
    except Exception:
        dt = None

    if not dt:
        return datetime.now(LOCAL_TZ) - timedelta(days=365*100)

    # Eğer dt zaten timezone içeriyorsa → sadece İstanbul’a çevir
    if dt.tzinfo:
        return dt.astimezone(LOCAL_TZ)

    # Eğer tzinfo yoksa → direkt İstanbul tz ekle
    return LOCAL_TZ.localize(dt)

def fetch_rss():
    """Tüm kaynaklardan haberleri getir ve tarihe göre sırala"""
    items = []
    for source, info in RSS_SOURCES.items():
        try:
            resp = requests.get(info["url"], timeout=5)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)

            for entry in feed.entries:
                # Görsel çıkar
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
                    "pubDate": entry.get("published", ""),
                    "published_at": pub_dt,  # datetime objesi
                    "description": BeautifulSoup(entry.get("description", ""), "html.parser").get_text() if "description" in entry else "",
                    "image": img_url
                })
        except Exception as e:
            print(f"{info['url']} okunamadı:", e)

    # 🔥 Tüm haberleri tarihe göre sırala (yeni → eski)
    items.sort(key=lambda x: x["published_at"], reverse=True)
    return items


@app.route("/rss")
def get_rss():
    try:
        all_items = fetch_rss()

        # JSON’a çevirirken datetime → string
        for item in all_items:
            if isinstance(item["published_at"], datetime):
                item["published_at"] = item["published_at"].isoformat()

        return jsonify({
            "total": len(all_items),
            "news": all_items
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
