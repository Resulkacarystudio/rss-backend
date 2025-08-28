from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import feedparser
from bs4 import BeautifulSoup

app = Flask(__name__)
CORS(app)

# --- Şimdilik sadece Milliyet ---
RSS_SOURCES = {
    "milliyet": {
        "url": "https://www.milliyet.com.tr/rss/rssnew/anasayfa.xml",
        "logo": "https://upload.wikimedia.org/wikipedia/commons/0/0e/Milliyet_logo.svg",
        "color": "#ff1a1a"
    }
}

def fetch_rss(source="milliyet"):
    """Belirtilen kaynaktan tüm haberleri getir"""
    items = []
    info = RSS_SOURCES[source]
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

    return items

@app.route("/rss")
def get_rss():
    try:
        page = int(request.args.get("page", 1))
        per_page = 10

        # Tüm haberleri al
        all_items = fetch_rss()

        # Sadece istenen sayfanın 10 haberi
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
