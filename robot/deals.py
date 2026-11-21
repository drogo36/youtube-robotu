"""Fırsatlar sayfası: Shorts açıklamasındaki linkler tıklanmadığı için, kanal profilindeki
tıklanabilir link bu sayfaya gider. Her ürün/indirim videosunda sayfa otomatik güncellenir."""
import html
import json
from datetime import datetime
from urllib.parse import quote_plus

from . import config

DEALS_FILE = config.DATA / "deals.json"
PAGE = config.ROOT / "docs" / "index.html"


def amazon_link(query):
    return f"https://www.amazon.com/s?k={quote_plus(query)}&tag={config.AMAZON_TAG}"


def _load():
    try:
        return json.loads(DEALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def add(query, title, youtube_id=None):
    if not (config.AMAZON_TAG and query):
        return
    deals = _load()
    deals.insert(0, {"query": query, "title": title.replace("#shorts", "").strip(),
                     "date": datetime.now().strftime("%Y-%m-%d"), "youtube_id": youtube_id})
    deals = deals[:60]
    DEALS_FILE.write_text(json.dumps(deals, ensure_ascii=False, indent=1), encoding="utf-8")
    render(deals)


def render(deals=None):
    deals = _load() if deals is None else deals
    cards = []
    for d in deals:
        vid = (f'<a class="vid" href="https://youtube.com/shorts/{html.escape(d["youtube_id"])}">▶ Watch the Short</a>'
               if d.get("youtube_id") else "")
        cards.append(f'''<article class="card">
  <div class="date">{html.escape(d["date"])}</div>
  <h2>{html.escape(d["title"])}</h2>
  <p class="q">{html.escape(d["query"])}</p>
  <a class="buy" href="{html.escape(amazon_link(d["query"]))}" rel="nofollow sponsored">Check today's price on Amazon →</a>
  {vid}
</article>''')
    body = "\n".join(cards) or '<p class="empty">New deals are added with every video. Check back soon!</p>'
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Respawn Report — Gaming & Tech Deals</title>
<meta name="description" content="Deals and price drops from the Respawn Report Shorts: consoles, games, phones and gear.">
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#0d0f14;color:#eef1f6}}
header{{padding:36px 20px 20px;text-align:center;background:linear-gradient(135deg,#e1192d,#7a1fd6)}}
header h1{{margin:0;font-size:28px;letter-spacing:.5px}}header p{{margin:8px 0 0;opacity:.9}}
main{{max-width:760px;margin:0 auto;padding:20px 16px 40px;display:grid;gap:14px}}
.card{{background:#171a22;border:1px solid #262b36;border-radius:16px;padding:18px}}
.date{{font-size:12px;color:#8a93a6}}h2{{font-size:18px;margin:6px 0 4px;line-height:1.35}}
.q{{margin:0 0 14px;color:#aab3c5;font-size:14px}}
.buy{{display:inline-block;background:#ffd400;color:#111;font-weight:700;text-decoration:none;padding:11px 16px;border-radius:10px}}
.vid{{display:inline-block;margin-left:10px;color:#9fb4ff;text-decoration:none;font-size:14px}}
.empty{{text-align:center;color:#8a93a6}}
footer{{max-width:760px;margin:0 auto;padding:0 16px 40px;font-size:12px;color:#8a93a6;text-align:center}}
footer a{{color:#9fb4ff}}
</style></head><body>
<header><h1>🎮 Respawn Report Deals</h1><p>Every deal from our Shorts, in one place. Updated automatically.</p></header>
<main>
{body}
</main>
<footer>As an Amazon Associate we earn from qualifying purchases. Prices and availability change; check Amazon for the current price.<br>
<a href="https://www.youtube.com/@RespawnReportNews">YouTube: @RespawnReportNews</a></footer>
</body></html>''', encoding="utf-8")
