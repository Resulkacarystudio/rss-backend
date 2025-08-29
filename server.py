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

# Basit ve güvenli bir User-Agent (bazı kaynaklar istiyor)
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HaberMerkezi/1.0; +https://example.com)",
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
}

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
            "url": "https://www.milliyet.com.tr/rss/rssNew/SonDakikaRss.xml",
            "logo": "/logos/milliyet.png",
            "color": "#1a76ff"
        },
        # TRT: HTTPS kullan
        "trthaber": {
            "url": "https://www.trthaber.com/sondakika.rss",
            "logo": "/logos/trthaber.png",
            "color": "#006699"
        },
        "mynet": {
            "url": "https://www.mynet.com/haber/rss/sondakika",
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

def extract_image_from_entry(entry):
    """
    Farklı RSS formatlarındaki görselleri agresif şekilde yakalar.
    Sıra: enclosure -> media:content -> media:thumbnail -> description img -> content:encoded img -> imageUrl (TRT)
    """
    # 1) enclosure
    if "enclosures" in entry and entry.enclosures:
        href = entry.enclosures[0].get("href")
        if href:
            return href

    # 2) media:content
    if "media_content" in entry and entry.media_content:
        url = entry.media_content[0].get("url")
        if url:
            return url

    # 3) media:thumbnail
    if "media_thumbnail" in entry and entry.media_thumbnail:
        url = entry.media_thumbnail[0].get("url")
        if url:
            return url

    # 4) description içindeki <img>
    desc_html = entry.get("description") or entry.get("summary", "")
    if desc_html:
        soup = BeautifulSoup(desc_html, "html.parser")
        img_tag = soup.find("img")
        if img_tag and img_tag.get("src"):
            return img_tag["src"]

    # 5) content:encoded / content içindeki <img>
    # feedparser 'content' alanını list olarak döndürebilir
    if hasattr(entry, "content") and entry.content:
        try:
            content_html = entry.content[0].get("value", "")
            if content_html:
                soup = BeautifulSoup(content_html, "html.parser")
                img_tag = soup.find("img")
                if img_tag and img_tag.get("src"):
                    return img_tag["src"]
        except Exception:
            pass

    # 6) TRT Haber özel alan: <imageUrl> ... feedparser bunu 'imageurl' olarak map'liyor
    # (Senin örneğinde bu alan var. Asıl çözüm bu!)
    if hasattr(entry, "imageurl"):
        return entry.imageurl

    # 7) linkler içinde image tipli enclosure olabilir
    if "links" in entry:
        for l in entry.links:
            if l.get("rel") == "enclosure" and "image" in (l.get("type") or "") and l.get("href"):
                return l.get("href")

    return None

def fetch_single(source, info):
    """Tek bir kaynaktan haberleri getir"""
    items = []
    try:
        resp = requests.get(info["url"], timeout=12, headers=HTTP_HEADERS)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)

        for entry in feed.entries:
            img_url = extract_image_from_entry(entry)
            pub_dt = parse_date(entry)

            # Açıklama düz metin
            raw_desc_html = entry.get("description") or entry.get("summary", "")
            plain_desc = ""
            if raw_desc_html:
                plain_desc = BeautifulSoup(raw_desc_html, "html.parser").get_text()

            items.append({
                "source": source,
                "source_logo": info["logo"],
                "source_color": info["color"],
                "title": entry.get("title", "Başlık Yok"),
                "link": entry.get("link", ""),
                "pubDate": entry.get("published", "") or entry.get("updated", ""),
                "published_at": pub_dt.isoformat(),
                "published_at_ms": int(pub_dt.timestamp() * 1000),
                "description": plain_desc.strip(),
                "image": img_url
            })
    except Exception as e:
        print(f"{info['url']} okunamadı:", e)

    return items

def dedupe_items(items):
    """Aynı link/title gelenleri ayıkla (bazı RSS'lerde tekrar gelebiliyor)"""
    seen = set()
    unique = []
    for it in items:
        key = (it.get("link") or "", it.get("title") or "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)
    return unique

def fetch_rss(category="all"):
    """Kategoriye göre RSS çek"""
    items = []
    sources = RSS_CATEGORIES.get(category, RSS_CATEGORIES["all"])

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(fetch_single, source, info) for source, info in sources.items()]
        for f in concurrent.futures.as_completed(futures):
            items.extend(f.result())

    # Tekrarları temizle
    items = dedupe_items(items)

    # Sıralama: en yeni → en eski
    items.sort(key=lambda x: x["published_at_ms"], reverse=True)

    # 🔥 Tarih filtresi: breaking = 2 gün, diğerleri = 7 gün
    now = datetime.now(LOCAL_TZ)
    cutoff = now - (timedelta(days=2) if category == "breaking" else timedelta(days=7))
    items = [i for i in items if datetime.fromtimestamp(i["published_at_ms"]/1000, LOCAL_TZ) >= cutoff]

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
