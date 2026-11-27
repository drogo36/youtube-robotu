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
NEWS_LANG = {"en": ("en-US", "US", "US:en"), "tr": ("tr", "TR", "TR:tr"), "es": ("es-419", "MX", "MX:es-419"),
             "pt": ("pt-BR", "BR", "BR:pt-419"), "id": ("id", "ID", "ID:id"), "hi": ("hi", "IN", "IN:hi")}


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


_MARKET = None


def market():
    """YouTube'un en çok izlenen listeleri (tur başına bir kez çekilir)."""
    global _MARKET
    if _MARKET is None:
        try:
            from . import youtube
            regions = list(dict.fromkeys([config.TRENDS_GEO] + config.TRENDS_GEOS[:5]))
            _MARKET = youtube.most_popular(regions)
        except BaseException as e:
            log.warning(f"Piyasa radarı çalışmadı: {e}")
            _MARKET = []
    return _MARKET


def hot_names(names):
    """Verilen oyun/marka adlarından, şu an YouTube'da en çok izlenen videolarda geçenler (izlenmeye göre sıralı)."""
    score = {}
    for v in market():
        blob = (v["title"] + " " + " ".join(v["tags"])).lower()
        for n in names:
            short = n.split(" (")[0].split(":")[0].lower()
            if len(short) >= 4 and short in blob:
                score[n] = score.get(n, 0) + v["views"]
    return [n for n, _ in sorted(score.items(), key=lambda x: -x[1])]


def market_brief(limit=25):
    vids = market()[:limit]
    if not vids:
        return ""
    lines = "\n".join(f"  {v['views']:,} views [{v['region']}] {v['title']}" for v in vids)
    return ("WHAT THE MARKET IS WATCHING: the most viewed gaming/tech videos on YouTube right now. Stories about the same "
            "games, creators, events and topics have proven demand — strongly prefer them:\n" + lines + "\n")


def collect():
    """Daha önce işlenmemiş haber adaylarını döndürür."""
    candidates, seen_links = [], set()
    import random
    hot = hot_names(config.WATCH_KEYWORDS + [g.split(" (")[0] for g in config.EVERGREEN_GAMES])[:4]
    if hot:
        log.info(f"Piyasada en çok izlenenler: {', '.join(hot)}")
    pool = list(dict.fromkeys(hot + list(config.WATCH_KEYWORDS)))
    first, rest = pool[:max(1, len(hot))], pool[max(1, len(hot)):]   # piyasada en çok izlenenler her turda bakılır
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


def evergreen_story():
    """Dev oyunlar hakkında "bunu bilmiyordun" videosu için Wikipedia'dan doğrulanmış bilgi parçası."""
    import random
    from datetime import datetime
    games = list(config.EVERGREEN_GAMES)
    random.shuffle(games)
    hot = hot_names(games)[:6]          # YouTube'da şu an en çok izlenen oyunlar öne
    games = hot + [g for g in games if g not in hot]
    week = datetime.now().strftime("%G-%V")
    for game in games[:10]:
        key = f"wiki:{game}:{week}"
        if db.is_seen(key):
            continue
        try:
            r = requests.get("https://en.wikipedia.org/w/api.php", timeout=20, headers={
                "User-Agent": "RespawnReportBot/1.0 (https://github.com/drogo36/youtube-robotu; robot@users.noreply.github.com)"},
                params={
                "action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
                "titles": game, "format": "json"})
            pages = r.json().get("query", {}).get("pages", {})
            text = next(iter(pages.values()), {}).get("extract", "")
        except Exception as e:
            log.warning(f"Wikipedia okunamadı ({game}): {e}")
            continue
        text = "\n".join(l for l in text.splitlines() if l.strip() and not l.startswith("=="))
        if len(text) < 3000:
            continue
        start = random.randint(0, max(0, len(text) - 7000))   # her seferinde makalenin farklı bir bölümü
        name = game.split(" (")[0]
        return {"title": f"{name}: surprising facts most players never knew", "link": key, "source": "Wikipedia",
                "published": "", "keyword": name, "topic": name, "evergreen": True,
                "context": text[:1500] + "\n...\n" + text[start:start + 5500]}
    return None
