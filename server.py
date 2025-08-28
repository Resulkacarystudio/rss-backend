from flask import Flask, jsonify
from flask_cors import CORS
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
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

def _safe_parse_dt(text: str):
    """
    Metin tarihini datetime'e çevirmeye çalışır (tz-aware).
    Başarısız olursa None döner.
    """
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
        return dt
    except Exception:
        return None

def parse_date(entry):
    """
    RSS tarih bilgisini tz-aware UTC datetime'e çevirir.
    CNN gibi tz-aware tarihleri direkt UTC'ye çevirir.
    Diğer tzinfo'suz tarihleri ise Istanbul kabul edip UTC'ye çevirir.
    """
    dt = None
    try:
        if hasattr(entry, "published") and entry.published:
            dt = parsedate_to_datetime(entry.published)
        elif hasattr(entry, "updated") and entry.updated:
            dt = parsedate_to_datetime(entry.updated)
    except Exception:
        dt = None

    if not dt:
        return datetime.now(timezone.utc) - timedelta(days=365*100)

    # CNN → tz-aware → direk UTC'ye çevir
    if dt.tzinfo:
        return dt.astimezone(timezone.utc)

    # Milliyet/Hürriyet gibi tzinfo yoksa → Istanbul say, UTC’ye çevir
    dt = LOCAL_TZ.localize(dt).astimezone(timezone.utc)
    return dt


def fetch_rss():
    """Tüm kaynaklardan haberleri getir ve tarihe göre (UTC) sırala"""
    items = []
    for source, info in RSS_SOURCES.items():
        try:
            resp = requests.get(info["url"], timeout=10)
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

                pub_dt_utc = parse_date(entry)  # tz-aware UTC datetime

                items.append({
                    "source": source,
                    "source_logo": info["logo"],
                    "source_color": info["color"],
                    "title": entry.get("title", "Başlık Yok"),
                    "link": entry.get("link", ""),
                    "pubDate": entry.get("published", "") or entry.get("updated", ""),
                    # ISO'yu her zaman Z (UTC) ile bitirecek şekilde yaz
                    "published_at": pub_dt_utc.isoformat().replace("+00:00", "Z"),
                    "description": BeautifulSoup(entry.get("description", ""), "html.parser").get_text() if "description" in entry else "",
                    "image": img_url,
                    # Sıralama için epoch (ms) ekleyelim (frontend ihtiyaç duyarsa hazır)
                    "published_at_ms": int(pub_dt_utc.timestamp() * 1000)
                })
        except Exception as e:
            print(f"{info['url']} okunamadı:", e)

    # 🔥 UTC datetime değerine göre sırala (en yeni → en eski)
    items.sort(key=lambda x: x["published_at_ms"], reverse=True)
    return items

@app.route("/rss")
def get_rss():
    try:
        all_items = fetch_rss()
        return jsonify({
            "total": len(all_items),
            "news": all_items
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Render gibi ortamlarda süreklilik için 0.0.0.0
    app.run(host="0.0.0.0", port=5000, debug=True)
