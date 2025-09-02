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
from dateutil import tz

import os
import concurrent.futures
from openai import OpenAI
import pymysql
import os
import re
import dateparser
import json


# =================================================
# OpenAI client
# =================================================
# Railway dashboard → Variables → OPENAI_API_KEY tanımlanmalı
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
TR_SETTINGS = {
    "TIMEZONE": "Europe/Istanbul",
    "TO_TIMEZONE": "Europe/Istanbul",
    "RETURN_AS_TIMEZONE_AWARE": True,
    "PREFER_DATES_FROM": "past",
    "DATE_ORDER": "DMY",   # ✅ gün-ay-yıl
}


def parse_tr_date(txt):
    if not txt:
        return None
    s = str(txt).strip()

    # 1) ISO formatı (2025-09-02T15:44:59+03:00 gibi)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(LOCAL_TZ)
    except Exception:
        pass

    # 2) dd.MM.yyyy veya dd.MM.yyyy HH:mm:ss
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=LOCAL_TZ)
        except Exception:
            continue

    # 3) dd/MM/yyyy gibi varyantlar
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=LOCAL_TZ)
        except Exception:
            continue

    # 4) Son çare: dateparser (Türkçe + DMY)
    try:
        dt = dateparser.parse(
            s,
            languages=["tr"],
            settings={
                "TIMEZONE": "Europe/Istanbul",
                "TO_TIMEZONE": "Europe/Istanbul",
                "RETURN_AS_TIMEZONE_AWARE": True,
                "PREFER_DATES_FROM": "past",
                "DATE_ORDER": "DMY",
            },
        )
        return dt
    except Exception:
        return None



def _first_meta(soup, selectors):
    """Belirtilen meta etiketlerinden ilk bulduğunu döndürür"""
    for attr, val in selectors:
        el = soup.find("meta", {attr: val})
        if el and (el.get("content") or el.get("value")):
            return el.get("content") or el.get("value")
    return None

def _first_time(soup):
    t = soup.find("time", attrs={"datetime": True})
    if t:
        return t.get("datetime")
    t = soup.find(attrs={"itemprop": "datePublished"})
    if t and (t.get("datetime") or t.get("content") or t.text):
        return t.get("datetime") or t.get("content") or t.get_text(strip=True)
    return None

def _jsonld_dates(soup):
    """JSON-LD içinden datePublished / dateModified çek"""
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or script.text or "{}")
        except Exception:
            continue
        candidates = data if isinstance(data, list) else [data]
        for obj in candidates:
            t = obj.get("@type") or obj.get("type")
            if isinstance(t, list):
                is_article = any(typ in ("NewsArticle", "Article") for typ in t)
            else:
                is_article = t in ("NewsArticle", "Article")
            if is_article:
                pub = obj.get("datePublished")
                upd = obj.get("dateModified")
                if pub or upd:
                    return pub, upd
    return None, None

# ==============
# ===================================
# Flask App & CORS
# =================================================
app = Flask(__name__)
# CORS ayarları → hem localhost hem resulkacar.com için izin ver
CORS(app, resources={r"/*": {"origins": "*"}})
print("🔑 OPENAI_API_KEY:", os.environ.get("OPENAI_API_KEY"))

@app.after_request
def apply_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

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
    try:
        resp = requests.get(
            url,
            timeout=12,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
            },
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Başlık / açıklama / görsel
        title = soup.find("meta", property="og:title")
        title = title.get("content") if title else (soup.title.string if soup.title else "Başlık bulunamadı")
        description = soup.find("meta", property="og:description")
        description = description.get("content") if description else ""
        image = soup.find("meta", property="og:image")
        image = image.get("content") if image else None

        published_at = None
        updated_at = None

        # 0) JSON-LD
        pub_jsonld, upd_jsonld = _jsonld_dates(soup)
        if pub_jsonld and not published_at:
            published_at = pub_jsonld
        if upd_jsonld and not updated_at:
            updated_at = upd_jsonld

        # 1) Meta etiketleri
        if not published_at:
            published_at = _first_meta(
                soup,
                [
                    ("property", "article:published_time"),
                    ("name", "pubdate"),
                    ("name", "publishdate"),
                    ("name", "publish-date"),
                    ("itemprop", "datePublished"),
                ],
            ) or _first_time(soup)

        if not updated_at:
            updated_at = _first_meta(
                soup,
                [
                    ("property", "article:modified_time"),
                    ("name", "lastmod"),
                    ("itemprop", "dateModified"),
                ],
            )

        # 2) Metin içinden Türkçe etiketlerle (Sabah vb.)
        raw_text = soup.get_text(" ", strip=True)

        if not published_at:
            m = re.search(r"Giri(?:ş|s)\s*Tarihi[:\-\–]\s*([^\n\r|]+)", raw_text, flags=re.IGNORECASE)
            if m:
                published_at = m.group(1).strip()

        if not published_at:
            m = re.search(r"(Yayınlanma|Yayın Tarihi)[:\-\–]\s*([^\n\r|]+)", raw_text, flags=re.IGNORECASE)
            if m:
                published_at = m.group(2).strip()

        if not updated_at:
            m = re.search(r"(Son\s+Güncelleme|Güncellenme)[:\-\–]\s*([^\n\r|]+)", raw_text, flags=re.IGNORECASE)
            if m:
                updated_at = m.group(2).strip()

        # 3) Genel tarih kalıpları
        if not published_at:
            m = re.search(r"(\d{1,2}\s+[A-Za-zçğıöşüÇĞİÖŞÜ]+\s+\d{4}\s+\d{1,2}:\d{2})", raw_text)
            if m:
                published_at = m.group(1)

        if not published_at:
            m = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})\s*[-–]?\s*(\d{1,2}:\d{2})", raw_text)
            if m:
                published_at = f"{m.group(1)} {m.group(2)}"

        # 4) dateparser ile ISO formatına çevir
        dt_pub = parse_tr_date(published_at) if published_at else None
        dt_upd = parse_tr_date(updated_at) if updated_at else None

        if not dt_pub:
            dt_pub = datetime.now(LOCAL_TZ)

        return {
            "title": (title or "").strip(),
            "description": (description or "").strip(),
            "image": image,
            "publishedAt": dt_pub.isoformat(),
            "updatedAt": dt_upd.isoformat() if dt_upd else None,
            "fullText": "\n".join([p.get_text() for p in soup.find_all("p") if p.get_text()]).strip(),
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
    try:
        data = request.get_json()
        print("📩 Gelen data:", data)

        content = data.get("text", "")
        if not content:
            return jsonify({"error": "text parametresi gerekli"}), 400

        print("🚀 OpenAI çağrısı başlıyor...")
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Sen deneyimli bir haber editörüsün. "
                        "Haberi yeniden yazarken resmi bir haber dili kullan. "
                        "Olayları detaylandır, bağlam ekle, haberi uzat ve anlaşılır kıl. "
                        "Reklam, yönlendirme (örn: 'haber.com’u ziyaret edin'), kaynak ismi veya link kullanma. "
                        "Sadece haberin kendisine odaklan. "
                        "Son cümlede haberi özetleyici güçlü bir ifade ekle. "
                        "Ayrıca haberi sınıflandır: 'spor', 'siyaset', 'gündem', 'ekonomi', 'dünya', 'magazin', 'sağlık', 'teknoloji', 'eğitim', 'kültür-sanat' gibi."
                        "Sonucu JSON formatında döndür: {\"title\": ..., \"body\": ..., \"category\": ...}"
                    ),
                },
                {"role": "user", "content": content},
            ],
            response_format={ "type": "json_object" }  # ✅ direkt JSON dönecek
        )
        print("✅ OpenAI cevabı:", completion)

        rewritten_json = completion.choices[0].message.content
        import json
        try:
            parsed = json.loads(rewritten_json)
        except Exception:
            return jsonify({"error": "JSON parse edilemedi", "raw": rewritten_json}), 500

        return jsonify({
            "title_ai": parsed.get("title"),
            "rewritten": parsed.get("body"),
            "category": parsed.get("category")
        })

    except Exception as e:
        import traceback
        err_msg = f"{type(e).__name__}: {str(e)}"
        print("❌ REWRITE ERROR:", err_msg)
        print(traceback.format_exc())
        return jsonify({"error": err_msg}), 500





def get_db_connection():
    return pymysql.connect(
        host=os.environ.get("DB_HOST"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASS"),
        database=os.environ.get("DB_NAME"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )
@app.route("/save", methods=["POST"])
def save_news():
    data = request.get_json()
    title = data.get("title")
    content = data.get("content")
    image = data.get("image")
    published_at_raw = data.get("published_at")
    category = data.get("category")

    if not title or not content:
        return jsonify({"error": "title ve content gerekli"}), 400

    # ✅ Tarihi normalize et
    dt = parse_tr_date(published_at_raw) if published_at_raw else datetime.now(LOCAL_TZ)
    if not dt:
        dt = datetime.now(LOCAL_TZ)
    published_at_db = dt.strftime("%Y-%m-%d %H:%M:%S")

    # ✅ Slug üret
    slug = slugify_title(title)

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                INSERT INTO haberList (title, slug, content, image, published_at, category, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """
            cursor.execute(sql, (title, slug, content, image, published_at_db, category))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Haber kaydedildi"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


    

@app.route("/news", methods=["GET"])
def get_saved_news():
    try:
        category = request.args.get("category", "all")
        limit = int(request.args.get("limit", 20))
        offset = int(request.args.get("offset", 0))

        conn = get_db_connection()
        with conn.cursor() as cursor:
            if category == "all":
                sql = """
                    SELECT id, title, content, image, category, published_at, created_at
                    FROM haberList
                    ORDER BY published_at DESC
                    LIMIT %s OFFSET %s
                """
                cursor.execute(sql, (limit, offset))
            else:
                sql = """
                    SELECT id, title, content, image, category, published_at, created_at
                    FROM haberList
                    WHERE category = %s
                    ORDER BY published_at DESC
                    LIMIT %s OFFSET %s
                """
                cursor.execute(sql, (category, limit, offset))

            rows = cursor.fetchall()

            # total
            if category == "all":
                cursor.execute("SELECT COUNT(*) as count FROM haberList")
            else:
                cursor.execute("SELECT COUNT(*) as count FROM haberList WHERE category = %s", (category,))
            total = cursor.fetchone()["count"]

        conn.close()

        

        # ✅ Her kaydın published_at'ını ISO'ya çevir
        normalized = []
        for r in rows:
            dt = r.get("published_at")
            iso_val = None

            if isinstance(dt, datetime):
                # Eğer naive ise TR varsay, sonra ISO üret
                if dt.tzinfo is None:
                    dt = LOCAL_TZ.localize(dt)
                iso_val = dt.astimezone(LOCAL_TZ).isoformat()
            elif isinstance(dt, str) and dt:
                parsed = parse_tr_date(dt)
                if parsed is None:
                    # son çare: YYYY-MM-DD HH:MM:SS gibi ise elle ISO'ya çevir
                    try:
                        parsed = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
                        parsed = LOCAL_TZ.localize(parsed)
                    except Exception:
                        parsed = None
                iso_val = parsed.astimezone(LOCAL_TZ).isoformat() if parsed else None

            r["published_at"] = iso_val
            normalized.append(r)

        return jsonify({"success": True, "news": normalized, "total": total})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
# === Haberleri slug (başlık) ile çek ===
def slugify_title(title: str) -> str:
    """Python tarafında slug üretir (React'teki slugify ile uyumlu)"""
    import unicodedata
    text = unicodedata.normalize("NFD", title)
    text = text.encode("ascii", "ignore").decode("utf-8")  # Türkçe harfleri sadeleştir
    text = text.lower()
    text = re.sub(r"ş", "s", text)
    text = re.sub(r"ı", "i", text)
    text = re.sub(r"ç", "c", text)
    text = re.sub(r"ü", "u", text)
    text = re.sub(r"ö", "o", text)
    text = re.sub(r"ğ", "g", text)
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")

@app.route("/news/slug/<slug>", methods=["GET"])
def get_news_by_slug(slug):
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                SELECT id, title, content, image, category, published_at, created_at
                FROM haberList
                ORDER BY published_at DESC
            """
            cursor.execute(sql)
            rows = cursor.fetchall()
        conn.close()

        # Python tarafında slug karşılaştırması yapıyoruz
        for row in rows:
            if slugify_title(row["title"]) == slug:
                dt = row.get("published_at")
                if isinstance(dt, datetime):
                    if dt.tzinfo is None:
                        dt = LOCAL_TZ.localize(dt)
                    row["published_at"] = dt.astimezone(LOCAL_TZ).isoformat()
                elif isinstance(dt, str):
                    parsed = parse_tr_date(dt)
                    if parsed:
                        row["published_at"] = parsed.astimezone(LOCAL_TZ).isoformat()

                return jsonify({"success": True, "news": row})

        return jsonify({"success": False, "error": "Haber bulunamadı"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def news_exists(title, link):
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT id FROM haberList WHERE title = %s OR content LIKE %s LIMIT 1"
            cursor.execute(sql, (title, f"%{link}%"))
            row = cursor.fetchone()
        conn.close()
        return row is not None
    except Exception as e:
        print("DB kontrol hatası:", e)
        return False


def rewrite_with_ai(text):
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Sen deneyimli bir haber editörüsün. "
                        "Haberi yeniden yazarken resmi bir haber dili kullan. "
                        "Kaynak veya link ekleme. "
                        "Sonucu JSON formatında döndür: "
                        "{\"title\": ..., \"body\": ..., \"category\": ...}"
                    ),
                },
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
        )
        raw = completion.choices[0].message.content
        return json.loads(raw)
    except Exception as e:
        print("AI rewrite hatası:", e)
        return None
def save_ai_news(title, content, image, published_at, category):
    try:
        dt = parse_tr_date(published_at) if published_at else datetime.now(LOCAL_TZ)
        if not dt:
            dt = datetime.now(LOCAL_TZ)
        published_at_db = dt.strftime("%Y-%m-%d %H:%M:%S")

        # ✅ Slug üret
        slug = slugify_title(title)

        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                INSERT INTO haberList (title, slug, content, image, category, published_at, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """
            cursor.execute(sql, (title, slug, content, image, category, published_at_db))
        conn.commit()
        conn.close()
        print(f"✅ Yeni haber kaydedildi: {title}")
    except Exception as e:
        print("Kaydetme hatası:", e)

def fetch_and_process(category="all"):
    print(f"🚀 {category} kategorisi için yeni haberler kontrol ediliyor...")
    items = fetch_rss(category)

    for item in items:
        title = item["title"]
        link = item["link"]
        if news_exists(title, link):
            continue  # zaten var

        # ham içerik
        raw_text = f"{title}\n\n{item.get('description') or ''}"

        # yapay zekâya gönder
        ai_result = rewrite_with_ai(raw_text)
        if not ai_result:
            continue

        save_ai_news(
            title=ai_result.get("title") or title,
            content=ai_result.get("body") or (item.get("description") or ""),
            image=item.get("image"),
            published_at=item.get("published_at"),
            category=ai_result.get("category") or category,
        )
@app.route("/cron")
def run_cron():
    category = request.args.get("category", "all")
    fetch_and_process(category)
    return jsonify({"status": "ok", "category": category})

# =================================================
# Main
# =================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
