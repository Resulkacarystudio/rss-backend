from flask import Flask, jsonify
from flask_cors import CORS
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime
from email.utils import parsedate_to_datetime

app = Flask(__name__)
CORS(app)

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
    """RSS tarih bilgisini datetime objesine çevir"""
    try:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            return datetime(*entry.published_parsed[:6])
        if hasattr(entry, "updated_parsed") and entry.updated_parsed:
            return datetime(*entry.updated_parsed[:6])
        if hasattr(entry, "published") and entry.published:
            return parsedate_to_datetime(entry.published)
        if hasattr(entry, "updated") and entry.updated:
            return parsedate_to_datetime(entry.updated)
    except Exception:
        pass
    return datetime.min


def fetch_rss():
    """Tüm kaynaklardan haberleri getir ve tarihe göre karıştır"""
    items = []
    for source, info in RSS_SOURCES.items():
        try:
            resp = requests.get(info["url"], timeout=5)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)

            for entry in feed.entries:
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
                    "title": entry.title,
                    "link": entry.link,
                    "pubDate": entry.get("published", ""),
                    "published_at": pub_dt,  # datetime objesi
                    "description": BeautifulSoup(entry.get("description", ""), "html.parser").get_text(),
                    "image": img_url
                })
        except Exception as e:
            print(f"{info['url']} okunamadı:", e)

    # 🔥 Tüm haberleri gerçek datetime’a göre sırala
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
