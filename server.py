# ================================================
# server.py - Haber API (RSS + Parse + Rewrite)
# ================================================

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import pytz
import os
import concurrent.futures
from openai import OpenAI

# =================================================
# OpenAI client
# =================================================
# Railway dashboard → Variables → OPENAI_API_KEY tanımlanmalı
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# =================================================
# Flask App & CORS
# =================================================
app = Flask(__name__)
# CORS ayarları → hem localhost hem resulkacar.com için izin ver
CORS(app, resources={r"/*": {"origins": ["http://localhost:5173", "https://resulkacar.com"]}})

# Türkiye saat dilimi
LOCAL_TZ = pytz.timezone("Europe/Istanbul")

# HTTP headers (RSS kaynakları için güvenli UA)
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HaberMerkezi/1.0; +https://resulkacar.com)",
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
}

# =================================================
# RSS Kategorileri
# =================================================
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
            "color": "#e60000"
        },
        "ntv": {
            "url": "https://www.ntv.com.tr/gundem.rss",
            "logo": "/logos/ntv.png",
            "color": "#006699"
        },
        "mynet": {
            "url": "https://www.mynet.com/haber/rss/anasayfa",
            "logo": "/logos/mynet.png",
            "color": "#ff6600"
        },
        "sabah": {
            "url": "https://www.sabah.com.tr/rss/anasayfa.xml",
            "logo": "/logos/sabah.png",
            "color": "#7c0f0f"
        },
        "trthaber": {
            "url": "https://www.trthaber.com/xml_mobile.php?tur=anasayfa",
            "logo": "/logos/trthaber.png",
            "color": "#006699"
        }
    },
    "breaking": {
        "milliyet": {
            "url": "https://www.milliyet.com.tr/rss/rssNew/SonDakikaRss.xml",
            "logo": "/logos/milliyet.png",
            "color": "#ff1a1a"
        },
        "hurriyet": {
            "url": "https://www.hurriyet.com.tr/rss/sondakika",
            "logo": "/logos/hurriyet.png",
            "color": "#e60000"
        },
        "ntv": {
            "url": "https://www.ntv.com.tr/son-dakika.rss",
            "logo": "/logos/ntv.png",
            "color": "#006699"
        },
        "mynet": {
            "url": "https://www.mynet.com/haber/rss/sondakika",
            "logo": "/logos/mynet.png",
            "color": "#ff6600"
        },
        "trthaber": {
            "url": "https://www.trthaber.com/sondakika.rss",
            "logo": "/logos/trthaber.png",
            "color": "#7DB6D3"
        }
    },
    "gundem": {
        "milliyet": {
            "url": "https://www.milliyet.com.tr/rss/rssnew/gundem.xml",
            "logo": "/logos/milliyet.png",
            "color": "#1a76ff"
        },
        "hurriyet": {
            "url": "https://www.hurriyet.com.tr/rss/gundem",
            "logo": "/logos/hurriyet.png",
            "color": "#e60000"
        },
        "ntv": {
            "url": "https://www.ntv.com.tr/gundem.rss",
            "logo": "/logos/ntv.png",
            "color": "#006699"
        },
        "sabah": {
            "url": "https://www.sabah.com.tr/rss/gundem.xml",
            "logo": "/logos/sabah.png",
            "color": "#cc0000"
        },
        "mynet": {
            "url": "https://www.mynet.com/haber/rss/guncel",
            "logo": "/logos/mynet.png",
            "color": "#ff6600"
        }
    },
    "siyaset": {
        "milliyet": {
            "url": "https://www.milliyet.com.tr/rss/rssnew/siyaset.xml",
            "logo": "/logos/milliyet.png",
            "color": "#1a76ff"
        },
        "hurriyet": {
            "url": "https://www.hurriyet.com.tr/rss/siyaset",
            "logo": "/logos/hurriyet.png",
            "color": "#e60000"
        },
        "sabah": {
            "url": "https://www.sabah.com.tr/rss/siyaset.xml",
            "logo": "/logos/sabah.png",
            "color": "#cc0000"
        }
    },
    "ekonomi": {
        "milliyet": {
            "url": "https://www.milliyet.com.tr/rss/rssnew/ekonomi.xml",
            "logo": "/logos/milliyet.png",
            "color": "#1a76ff"
        },
        "hurriyet": {
            "url": "https://www.hurriyet.com.tr/rss/ekonomi",
            "logo": "/logos/hurriyet.png",
            "color": "#e60000"
        },
        "ntv": {
            "url": "https://www.ntv.com.tr/ekonomi.rss",
            "logo": "/logos/ntv.png",
            "color": "#006699"
        },
        "sabah": {
            "url": "https://www.sabah.com.tr/rss/ekonomi.xml",
            "logo": "/logos/sabah.png",
            "color": "#cc0000"
        },
        "mynet": {
            "url": "https://www.mynet.com/haber/rss/ekonomi",
            "logo": "/logos/mynet.png",
            "color": "#ff6600"
        }
    },
    "spor": {
        "milliyet": {
            "url": "https://www.milliyet.com.tr/rss/rssnew/spor.xml",
            "logo": "/logos/milliyet.png",
            "color": "#1a76ff"
        },
        "ntv": {
            "url": "https://www.ntv.com.tr/spor.rss",
            "logo": "/logos/ntv.png",
            "color": "#006699"
        },
        "sabah": {
            "url": "https://www.sabah.com.tr/rss/spor.xml",
            "logo": "/logos/sabah.png",
            "color": "#cc0000"
        },
        "hurriyet": {
            "url": "https://www.hurriyet.com.tr/rss/spor",
            "logo": "/logos/hurriyet.png",
            "color": "#e60000"
        },
        "mynet": {
            "url": "https://www.mynet.com/haber/rss/spor",
            "logo": "/logos/mynet.png",
            "color": "#ff6600"
        }
    },
    "dunya": {
        "milliyet": {
            "url": "https://www.milliyet.com.tr/rss/rssnew/dunya.xml",
            "logo": "/logos/milliyet.png",
            "color": "#1a76ff"
        },
        "hurriyet": {
            "url": "https://www.hurriyet.com.tr/rss/dunya",
            "logo": "/logos/hurriyet.png",
            "color": "#e60000"
        },
        "ntv": {
            "url": "https://www.ntv.com.tr/dunya.rss",
            "logo": "/logos/ntv.png",
            "color": "#006699"
        },
        "sabah": {
            "url": "https://www.sabah.com.tr/rss/dunya.xml",
            "logo": "/logos/sabah.png",
            "color": "#cc0000"
        }
    },
    "magazin": {
        "mynet": {
            "url": "https://www.mynet.com/haber/rss/kategori/yasam/",
            "logo": "/logos/mynet.png",
            "color": "#ff6600"
        },
        "milliyet": {
            "url": "https://www.milliyet.com.tr/rss/rssnew/magazinrss.xml",
            "logo": "/logos/milliyet.png",
            "color": "#1a76ff"
        },
        "sabah": {
            "url": "https://www.sabah.com.tr/rss/magazin.xml",
            "logo": "/logos/sabah.png",
            "color": "#cc0000"
        },
        "ntv": {
            "url": "https://www.ntv.com.tr/n-life.rss",
            "logo": "/logos/ntv.png",
            "color": "#4e00cc"
        }
    },
    "saglik": {
        "mynet": {
            "url": "https://www.mynet.com/haber/rss/kategori/saglik/s",
            "logo": "/logos/mynet.png",
            "color": "#ff6600"
        },
        "sabah": {
            "url": "https://www.sabah.com.tr/rss/saglik.xml",
            "logo": "/logos/sabah.png",
            "color": "#cc0000"
        },
        "ntv": {
            "url": "https://www.ntv.com.tr/saglik.rss",
            "logo": "/logos/ntv.png",
            "color": "#0044cc"
        }
    },
    "teknoloji": {
        "mynet": {
            "url": "https://www.mynet.com/haber/rss/kategori/teknoloji/",
            "logo": "/logos/mynet.png",
            "color": "#ff6600"
        },
         "milliyet": {
            "url": "https://www.milliyet.com.tr/rss/rssnew/teknolojirss.xml",
            "logo": "/logos/milliyet.png",
            "color": "#892b40"
        },
         "sabah": {
            "url": "https://www.sabah.com.tr/rss/teknoloji.xml",
            "logo": "/logos/sabah.png",
            "color": "#0a34a7"
        },
           "ntv": {
            "url": "https://www.ntv.com.tr/teknoloji.rss",
            "logo": "/logos/ntv.png",
            "color": "#4365c2"
        }
    },
    "egitim": {
        "mynet": {
            "url": "https://www.mynet.com/haber/rss/kategori/teknoloji/",
            "logo": "/logos/mynet.png",
            "color": "#ff6600"
        },
        "ntv": {
            "url": "https://www.ntv.com.tr/egitim.rss",
            "logo": "/logos/ntv.png",
            "color": "#006eff"
        },
        "milliyet": {
            "url": "https://www.milliyet.com.tr/rss/rssnew/egitim.xml",
            "logo": "/logos/milliyet.png",
            "color": "#ff0008"
        }
    },
    "kultursanat": {
         "sabah": {
            "url": "https://www.sabah.com.tr/rss/kultur-sanat.xml",
            "logo": "/logos/sabah.png",
            "color": "#ff6f00"
        },
         "ntv": {
            "url": "https://www.ntv.com.tr/sanat.rss",
            "logo": "/logos/ntv.png",
            "color": "#0800ff"
        },
    }
}

# =================================================
# Yardımcı Fonksiyonlar
# =================================================
def parse_date(entry):
    """RSS/Atom tarihini güvenli şekilde İstanbul saatine çevir"""
    try:
        if entry.get("published_parsed"):
            dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        elif entry.get("updated_parsed"):
            dt = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
        elif entry.get("published"):
            dt = parsedate_to_datetime(entry.published)
        elif entry.get("updated"):
            dt = parsedate_to_datetime(entry.updated)
        else:
            dt = datetime.now(timezone.utc)
    except Exception:
        dt = datetime.now(timezone.utc)
    return dt.astimezone(LOCAL_TZ)


def extract_image_from_entry(entry):
    """RSS içinden görseli almaya çalışır (farklı alanları da kontrol eder)"""
    try:
        if "enclosures" in entry and entry.enclosures:
            href = entry.enclosures[0].get("href")
            if href:
                return href
        if "media_content" in entry and entry.media_content:
            return entry.media_content[0].get("url")
        if "media_thumbnail" in entry and entry.media_thumbnail:
            return entry.media_thumbnail[0].get("url")
        if "summary" in entry:
            soup = BeautifulSoup(entry.summary, "html.parser")
            img = soup.find("img")
            if img and img.get("src"):
                return img["src"]
    except Exception:
        return None
    return None


def fetch_single(source, info):
    """Tek kaynaktan haberleri getir"""
    items = []
    try:
        resp = requests.get(info["url"], timeout=12, headers=HTTP_HEADERS)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)

        for entry in feed.entries:
            img_url = extract_image_from_entry(entry)
            pub_dt = parse_date(entry)
            raw_desc_html = entry.get("description") or entry.get("summary", "")
            plain_desc = BeautifulSoup(raw_desc_html, "html.parser").get_text() if raw_desc_html else ""

            items.append(
                {
                    "source": source,
                    "source_logo": info.get("logo"),
                    "source_color": info.get("color"),
                    "title": entry.get("title", "Başlık Yok"),
                    "link": entry.get("link", ""),
                    "pubDate": entry.get("published", "") or entry.get("updated", ""),
                    "published_at": pub_dt.isoformat(),
                    "published_at_ms": int(pub_dt.timestamp() * 1000),
                    "description": plain_desc.strip(),
                    "image": img_url,
                }
            )
    except Exception as e:
        print(f"{info['url']} okunamadı:", e)
    return items


def dedupe_items(items):
    """Aynı link + başlık olan haberleri teke indir"""
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
    """Kategorideki tüm kaynaklardan haberleri getir"""
    items = []
    sources = RSS_CATEGORIES.get(category, RSS_CATEGORIES["all"])
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(fetch_single, source, info) for source, info in sources.items()]
        for f in concurrent.futures.as_completed(futures):
            items.extend(f.result())
    items = dedupe_items(items)
    items.sort(key=lambda x: x["published_at_ms"], reverse=True)
    return items


def extract_meta_from_url(url):
    """Bir haber linkinden başlık, açıklama, görsel, tarih ve tam içerik çıkarır"""
    try:
        resp = requests.get(
            url,
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
            },
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title = soup.find("meta", property="og:title")
        title = title.get("content") if title else (soup.title.string if soup.title else "Başlık bulunamadı")

        description = soup.find("meta", property="og:description")
        description = description.get("content") if description else ""

        image = soup.find("meta", property="og:image")
        image = image.get("content") if image else None

        published_at = soup.find("meta", property="article:published_time")
        published_at = published_at.get("content") if published_at else None

        full_text = "\n".join([p.get_text() for p in soup.find_all("p") if p.get_text()])

        return {
            "title": title.strip() if title else "",
            "description": description.strip() if description else "",
            "image": image,
            "publishedAt": published_at,
            "fullText": full_text.strip(),
        }
    except Exception as e:
        return {"error": str(e)}

# =================================================
# API Endpoint'ler
# =================================================
@app.route("/rss")
def get_rss():
    """RSS endpoint → kategoriye göre haberleri döner"""
    try:
        category = request.args.get("category", "all")
        all_items = fetch_rss(category)
        return jsonify(
            {
                "origin": os.environ.get("RAILWAY_STATIC_URL", "local"),
                "category": category,
                "total": len(all_items),
                "news": all_items,
            }
        )
    except Exception as e:
        print("RSS error:", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/parse")
def parse_url():
    """Frontend'den gelen haber linkini alır ve detaylı verileri döner"""
    url = request.args.get("url")
    if not url:
        return jsonify({"error": "url parametresi gerekli"}), 400
    try:
        data = extract_meta_from_url(url)
        if not data or "error" in data:
            return jsonify({"error": data.get("error", "Bilinmeyen hata")}), 500
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": f"Parse başarısız: {str(e)}"}), 500


@app.route("/rewrite", methods=["POST"])
def rewrite():
    """Haberi OpenAI ile özgünleştir + başlık üret"""
    data = request.get_json()
    content = data.get("text", "")
    if not content:
        return jsonify({"error": "text parametresi gerekli"}), 400
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
               {
  "role": "system",
  "content": (
    "Sen deneyimli bir haber editörüsün. "
    "Haberi özgünleştirirken resmi bir haber dili kullan, "
    "gereksiz tekrarlar ve reklam amaçlı ifadeleri (örn: 'haber.com’u ziyaret edin') kesinlikle yazma. "
    "Kaynak adı veya yönlendirme linki ekleme. "
    "Olayın akışını net, tarafsız ve detaylı anlat. "
    "Metni daha uzun ve açıklayıcı yaz. "
    "Ayrıca haber için dikkat çekici ve anlamlı yeni bir başlık üret."
  )
}
,
                {"role": "user", "content": content},
            ],
        )
        rewritten = completion.choices[0].message.content

        # Başlık + içerik ayırma
        if "\n" in rewritten:
            parts = rewritten.split("\n", 1)
            title_ai = parts[0].strip()
            body_ai = parts[1].strip()
        else:
            title_ai = rewritten[:60] + "..."
            body_ai = rewritten

        return jsonify({"title_ai": title_ai, "rewritten": body_ai})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =================================================
# Main
# =================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
