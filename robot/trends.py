"""Trend radarı: Google News + Google Trends'ten taze, gündemde olan haberleri toplar."""
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from . import config, db
from .log import log

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Safari/605.1.15"}
NEWS_LANG = {"en": ("en-US", "US", "US:en"), "tr": ("tr", "TR", "TR:tr")}


def _rss(url):
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    return ET.fromstring(r.content)


def _parse_date(txt):
    try:
        d = parsedate_to_datetime(txt)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def google_news(query, max_age_hours=36):
    hl, gl, ceid = NEWS_LANG.get(config.LANGUAGE, NEWS_LANG["en"])
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{query} when:2d")
           + f"&hl={hl}&gl={gl}&ceid={ceid}")
    items = []
    try:
        root = _rss(url)
    except Exception as e:
        log.warning(f"Google News okunamadı ({query}): {e}")
        return items
    limit = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = _parse_date(it.findtext("pubDate") or "")
        source = (it.findtext("source") or "").strip()
        if not title or not link or (pub and pub < limit):
            continue
        items.append({"title": title, "link": link, "source": source,
                      "published": pub.isoformat() if pub else "", "keyword": query})
    return items


def _trends_geo(geo):
    try:
        root = _rss(f"https://trends.google.com/trending/rss?geo={geo}")
    except Exception as e:
        log.warning(f"Google Trends okunamadı ({geo}): {e}")
        return []
    return [(it.findtext("title") or "").strip() for it in root.iter("item") if it.findtext("title")]


def google_trends():
    """ABD + dönüşümlü 2 büyük pazarın yükselen aramaları (oyun/teknoloji dışı olanları yapay zekâ eler)."""
    import random
    others = [g for g in config.TRENDS_GEOS if g != config.TRENDS_GEO]
    geos = [config.TRENDS_GEO] + random.sample(others, min(2, len(others)))
    out = []
    for g in geos:
        out += [f"{t} ({g})" for t in _trends_geo(g)[:12]]
        time.sleep(2)
    return out[:36]


def collect():
    """Daha önce işlenmemiş haber adaylarını döndürür."""
    candidates, seen_links = [], set()
    import random
    pool = list(config.WATCH_KEYWORDS)
    first, rest = pool[:1], pool[1:]          # GTA 6 her turda bakılır, diğerleri dönüşümlü
    random.shuffle(rest)
    deals = list(config.DEAL_KEYWORDS)
    random.shuffle(deals)
    for kw in first + deals[:config.DEALS_PER_RUN] + rest[:max(config.KEYWORDS_PER_RUN - 1, 1)]:
        time.sleep(3)  # Google'ı yormamak için aramalar arasında bekle
        for item in google_news(kw)[:8]:
            if item["link"] in seen_links or db.is_seen(item["link"]):
                continue
            seen_links.add(item["link"])
            candidates.append(item)
    trending = google_trends() if config.USE_GOOGLE_TRENDS else []
    log.info(f"Trend radarı: {len(candidates)} yeni haber, {len(trending)} yükselen arama bulundu")
    return candidates, trending


def articles_for_topic(topic, limit=6):
    """Seçilen konu için ek haber başlıkları (doğrulama ve zengin içerik için)."""
    time.sleep(3)
    return google_news(topic, max_age_hours=72)[:limit]
