from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime

app = Flask(__name__)
CORS(app)

# --- RSS kaynakları + logo + renk ---
RSS_SOURCES = {
    "cnn": {
        "url": "https://www.cnnturk.com/feed/rss/all/news",
        "logo": "https://seeklogo.com/images/C/cnn-turk-logo-3E40B3A2ED-seeklogo.com.png",
        "color": "#cc0000"  # koyu kırmızı
    },
    "hurriyet": {
        "url": "https://www.hurriyet.com.tr/rss/anasayfa",
        "logo": "https://upload.wikimedia.org/wikipedia/commons/thumb/6/62/Hurriyet_logo.svg/2560px-Hurriyet_logo.svg.png",
        "color": "#e60000"
    },
    "milliyet": {
        "url": "https://www.milliyet.com.tr/rss/rssnew/anasayfa.xml",
        "logo": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0e/Milliyet_logo.svg/2560px-Milliyet_logo.svg.png",
        "color": "#ff1a1a"
    },
    "bbc": {
        "url": "https://feeds.bbci.co.uk/news/rss.xml",
        "logo": "https://upload.wikimedia.org/wikipedia/commons/b/bc/BBC_News_2022_%28Alt%29.svg",
        "color": "#bb1919"
    },
    "reuters": {
        "url": "https://feeds.reuters.com/reuters/topNews",
        "logo": "https://upload.wikimedia.org/wikipedia/commons/5/59/Reuters_Logo.svg",
        "color": "#ff9900"
    }
}

def get_og_image(url):
    """Haber sayfasından <meta property='og:image'> çek"""
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            return og_image["content"]
    except Exception as e:
        print("Resim alınamadı:", e)
    return None


def fetch_rss(limit=None):
    """Tüm kaynaklardan haberleri çek (limit varsa o kadar haber döner)"""
    items = []
    for source, info in RSS_SOURCES.items():
        try:
            resp = requests.get(info["url"], timeout=10)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)

            count = 0
            for entry in feed.entries:
                if limit and count >= limit:
                    break
                count += 1

                img_url = None

                if "enclosures" in entry and entry.enclosures:
                    img_url = entry.enclosures[0].get("href")

                if not img_url and "description" in entry:
                    soup = BeautifulSoup(entry.description, "html.parser")
                    img_tag = soup.find("img")
                    if img_tag and img_tag.get("src"):
                        img_url = img_tag["src"]

                if not img_url:
                    img_url = get_og_image(entry.link)

                items.append({
                    "source": source,
                    "source_logo": info["logo"],
                    "source_color": info["color"],
                    "title": entry.title,
                    "link": entry.link,
                    "pubDate": entry.get("published", ""),
                    "description": BeautifulSoup(entry.get("description", ""), "html.parser").get_text(),
                    "image": img_url
                })
        except Exception as e:
            print(f"{info['url']} okunamadı:", e)

    # Yayın tarihine göre sırala (yeni → eski)
    items.sort(key=lambda x: x["pubDate"], reverse=True)
    return items


@app.route("/rss")
def get_rss():
    try:
        page = int(request.args.get("page", 1))
        per_page = 10

        # sadece gerekli sayfa kadar haber çekelim
        need_count = page * per_page
        all_items = fetch_rss(limit=need_count)

        # slice işlemi
        start = (page - 1) * per_page
        end = start + per_page
        paginated = all_items[start:end]

        return jsonify({
            "page": page,
            "per_page": per_page,
            "total": len(all_items),
            "news": paginated
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
