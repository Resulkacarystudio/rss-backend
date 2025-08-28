from flask import Flask, jsonify
from flask_cors import CORS
import requests
import feedparser
from bs4 import BeautifulSoup

app = Flask(__name__)
CORS(app)

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

@app.route("/rss")
def get_rss():
    try:
        rss_url = "https://www.cnnturk.com/feed/rss/all/news"
        resp = requests.get(rss_url)
        resp.raise_for_status()

        feed = feedparser.parse(resp.text)

        items = []
        for entry in feed.entries:
            img_url = None

            # önce RSS içinden dene
            if "enclosures" in entry and entry.enclosures:
                img_url = entry.enclosures[0].get("href")

            # yoksa description içindeki img
            if not img_url and "description" in entry:
                soup = BeautifulSoup(entry.description, "html.parser")
                img_tag = soup.find("img")
                if img_tag and img_tag.get("src"):
                    img_url = img_tag["src"]

            # hala yoksa haber sayfasını aç
            if not img_url:
                img_url = get_og_image(entry.link)

            items.append({
                "title": entry.title,
                "link": entry.link,
                "pubDate": entry.get("published", ""),
                "description": BeautifulSoup(entry.get("description", ""), "html.parser").get_text(),
                "image": img_url
            })

        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(port=5000, debug=True)
