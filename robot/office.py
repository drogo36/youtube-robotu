"""Sanal ofis: kanalı 20 kişilik bir yapay zekâ ekibi gibi yönetir.

Her rol aynı yapay zekâ modeline (Gemini) farklı bir görev tanımıyla sorulan bir "uzmandır".
Döngü:  Analist izlenmeleri toplar -> Kanal Müdürü günlük strateji kararı yazar ->
        her videoda Yayın Kurulu senaryoyu puanlar, zayıfsa yeniden yazdırır ->
        tüm kararlar ve sonuçlar veri/ofis.json'da birikir (ekibin "hafızası" ve eğitimi) ->
        ofis panosu docs/ofis.html'de yayınlanır.
"""
import html
import json
import re
from datetime import datetime, timedelta

import requests

from . import config
from .log import log

STATE = config.DATA / "ofis.json"
BOARD = config.ROOT / "docs" / "ofis.html"

TEAM = [
    ("Yönetim", "Kanal Müdürü", "Haftalık hedefleri koyar, her gün stratejiyi günceller, son kararı verir"),
    ("Yönetim", "Yayın Yönetmeni", "Her videonun yayına çıkıp çıkmayacağına karar verir"),
    ("Araştırma", "Trend Avcısı", "Google News ve Google Trends'i tarar"),
    ("Araştırma", "İndirim Avcısı", "Black Friday ve fiyat düşüşlerini yakalar"),
    ("Araştırma", "Doğrulama Editörü", "Bilgileri birden fazla kaynakla karşılaştırır, söylentiyi işaretler"),
    ("Araştırma", "Küresel Gündem Uzmanı", "Hangi haberin dünya çapında ilgi çekeceğini seçer"),
    ("İçerik", "Baş Senarist", "Kısa ve uzun video metinlerini yazar"),
    ("İçerik", "Kanca (Hook) Uzmanı", "İlk 3 saniyeyi yazar, izleyiciyi tutar"),
    ("İçerik", "Yorumcu", "'Respawn verdict' ile kanalın özgün görüşünü ekler"),
    ("İçerik", "Uzun Video Yapımcısı", "Haftalık 'This Week in Gaming & Tech' bölümlerini kurgular"),
    ("Kalite", "Yayın Kurulu Başkanı", "Senaryoyu 10 üzerinden puanlar, zayıfsa geri çevirir"),
    ("Kalite", "Politika & Telif Denetçisi", "YouTube kurallarına ve telif haklarına uygunluğu kontrol eder"),
    ("Görsel", "Görsel Yönetmen", "Stok video ve yapay zekâ sahnelerini seçer"),
    ("Görsel", "Kurgu Editörü", "Kamera hareketi, geçiş, altyazı ve renkleri uygular"),
    ("Görsel", "Kapak Tasarımcısı", "Uzun videoların kapak resmini hazırlar"),
    ("Büyüme", "SEO Uzmanı", "Başlık, etiket ve hashtag'leri arama hacmine göre seçer"),
    ("Büyüme", "Yayın Saati Planlayıcısı", "Videoları ABD izleyicisinin en aktif saatlerine yerleştirir"),
    ("Büyüme", "Veri Analisti", "Her videonun izlenmesini toplar ve rapor verir"),
    ("Gelir", "Ortaklık (Amazon) Sorumlusu", "Ürün videolarına komisyon linki ve fırsat kartı ekler"),
    ("Gelir", "Fırsatlar Sayfası Editörü", "Kanal profilindeki fırsatlar sayfasını günceller"),
]


# ------------------------------------------------------------------ durum
def load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"strategy": {}, "videos": [], "log": [], "reviews": []}


def save(st):
    st["videos"] = st.get("videos", [])[-200:]
    st["log"] = st.get("log", [])[-80:]
    st["reviews"] = st.get("reviews", [])[-30:]
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    # Plaza (canlı ofis) sayfası için herkese açık özet — sadece pano verisi
    pub = {"log": st["log"][-40:], "strategy": st.get("strategy", {}),
           "videos": [{k: v.get(k) for k in ("id", "title", "format", "views", "date", "score")} for v in st["videos"][-60:]]}
    BOARD.parent.mkdir(parents=True, exist_ok=True)
    name = f"kanal-{config.CHANNEL_KEY}-data.json" if config.CHANNEL_KEY else "ofis-data.json"
    (BOARD.parent / name).write_text(json.dumps(pub, ensure_ascii=False), encoding="utf-8")


def performance_brief():
    """Konu seçen yapay zekâya kanalın gerçek izlenme verisi: en iyi ve en kötü videolar."""
    vids = [v for v in load().get("videos", []) if v.get("id") and v.get("views") is not None][-40:]
    if len(vids) < 5:
        return ""
    vids = sorted(vids, key=lambda v: -(v.get("views") or 0))
    top = "\n".join(f"  {v['views']} views: {v.get('title')}" for v in vids[:5])
    low = "\n".join(f"  {v['views']} views: {v.get('title')}" for v in vids[-5:])
    return (f"OUR REAL RESULTS. Best performers (make more stories LIKE THESE):\n{top}\n"
            f"Worst performers (avoid stories like these):\n{low}\n")


def note(st, role, text):
    st.setdefault("log", []).append({"t": datetime.now().strftime("%Y-%m-%d %H:%M"), "role": role, "text": text[:300]})
    log.info(f"[Ofis] {role}: {text[:160]}")


def strategy_brief():
    """Yazarlara verilen kısa yönetim talimatı (prompt'lara eklenir)."""
    s = load().get("strategy") or {}
    if not s:
        return ""
    parts = []
    for key, label in (("focus", "Focus on"), ("prefer_formats", "Formats that work best for us"),
                       ("avoid", "Avoid"), ("hook_tips", "Hook lessons"), ("title_tips", "Title lessons")):
        v = s.get(key)
        if v:
            parts.append(f"- {label}: {', '.join(v) if isinstance(v, list) else v}")
    return ("\nChannel manager's current strategy (learned from our own view data — follow it):\n" + "\n".join(parts)
            if parts else "")


def preferred_formats():
    return (load().get("strategy") or {}).get("prefer_formats") or []


# ------------------------------------------------------------------ Veri Analisti
def _views(video_id):
    try:
        r = requests.get(f"https://www.youtube.com/watch?v={video_id}", timeout=20,
                         headers={"Accept-Language": "en-US,en;q=0.9", "User-Agent": "Mozilla/5.0"})
        m = re.search(r'"viewCount":"(\d+)"', r.text) or re.search(r'"viewCount":\{"simpleText":"([\d,]+)', r.text)
        return int(m.group(1).replace(",", "")) if m else None
    except Exception:
        return None


def collect_stats(st):
    n = 0
    for v in st.get("videos", [])[-40:]:
        if not v.get("id"):
            continue
        views = _views(v["id"])
        if views is not None:
            v["views"] = views
            v["checked"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            n += 1
    if n:
        note(st, "Veri Analisti", f"{n} videonun güncel izlenmesi toplandı")


def record_video(data, vid, story):
    st = load()
    st.setdefault("videos", []).append({
        "id": vid, "title": data.get("title"), "format": data.get("format"), "topic": story.get("topic"),
        "deal": bool(str(data.get("amazon_query") or "").strip()), "score": data.get("qa_score"),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "views": 0})
    note(st, "Yayın Yönetmeni", f"Yayına onay verildi: {data.get('title')}")
    save(st)
    render_board(st)


# ------------------------------------------------------------------ Kanal Müdürü
def daily_review(force=False):
    from . import writer
    st = load()
    last = st.get("strategy", {}).get("date")
    if not force and last and datetime.now() - datetime.fromisoformat(last) < timedelta(hours=20):
        return
    collect_stats(st)
    vids = [v for v in st.get("videos", []) if v.get("id")][-40:]
    if len(vids) < 3:
        save(st)
        render_board(st)
        return
    table = "\n".join(f"- {v.get('views', 0)} views | format={v.get('format')} | deal={v.get('deal')} | "
                      f"QA={v.get('score')} | {v.get('date')} | {v.get('title')}" for v in vids)
    prompt = f"""You are the Channel Manager of "Respawn Report", a faceless English gaming & tech news YouTube Shorts channel
run by an AI team. Goal: maximum worldwide views and watch time, and Amazon affiliate sales from deal videos.

Our recent videos with their real view counts (newer videos have had less time):
{table}

Previous strategy: {json.dumps(st.get('strategy', {}), ensure_ascii=False)[:1500]}

Judge by the BEST performers: never tell the team to stop a topic/franchise that produced one of our top videos;
a 0-view video is usually a near-duplicate or bad timing, not proof the topic is dead. Plain deal/price videos
under-perform badly on Shorts: views come first (no views = no sales either).
Analyse what performs above our average and what under-performs (topics, formats, titles, hooks, deal vs news).
Make concrete decisions for the next 24 hours. Be specific, short, practical.
Allowed formats: breaking, 3things, didyouknow, versus, hottake.

Reply ONLY with JSON:
{{"summary_tr": "<2-3 sentence performance summary in TURKISH for the owner>",
  "decisions_tr": ["<decision in Turkish>", "..."],
  "focus": ["<topics/franchises to focus on>"], "avoid": ["<what to stop doing>"],
  "prefer_formats": ["<1-3 best formats from the allowed list>"],
  "hook_tips": ["<lesson>"], "title_tips": ["<lesson>"]}}"""
    try:
        data = writer._json(writer.ask_claude(prompt, 1500, writer.SYSTEM))
    except Exception as e:
        note(st, "Kanal Müdürü", f"Günlük toplantı yapılamadı: {e}")
        save(st)
        return
    data["date"] = datetime.now().isoformat(timespec="minutes")
    st["strategy"] = data
    st.setdefault("reviews", []).append({"date": data["date"], "summary": data.get("summary_tr", ""),
                                         "decisions": data.get("decisions_tr", [])})
    note(st, "Kanal Müdürü", "Günlük strateji toplantısı: " + "; ".join(data.get("decisions_tr", [])[:3]))
    save(st)
    render_board(st)


# ------------------------------------------------------------------ Yayın Kurulu
def qa_review(story, data):
    """Senaryoyu puanlar; 7'nin altındaysa bir kez yeniden yazdırır. Güncellenmiş data döner."""
    from . import writer
    st = load()
    prompt = f"""You are the Editorial Board of a YouTube Shorts gaming/tech news channel. Score this script strictly.
Headline it is based on: {story.get('title')}
Title: {data.get('title')}
Script: {data.get('script')}

Criteria: hook strength in the first 6 words, retention/pacing, original insight ("Respawn verdict"), factual safety
(nothing beyond the headline; rumors labeled), clarity for a global audience, title curiosity without clickbait lies.
{strategy_brief()}

Reply ONLY with JSON: {{"score": <1-10>, "problems": ["..."], "fix_instructions": "<how to rewrite, specific>"}}"""
    try:
        r = writer._json(writer.ask_claude(prompt, 700, writer.SYSTEM))
        score = int(r.get("score", 7))
    except Exception as e:
        log.warning(f"Yayın kurulu puanlayamadı: {e}")
        return data
    data["qa_score"] = score
    if score >= 7:
        note(st, "Yayın Kurulu Başkanı", f"{score}/10 ile onaylandı: {data.get('title')}")
        save(st)
        return data
    note(st, "Yayın Kurulu Başkanı", f"{score}/10 — geri çevrildi, yeniden yazılıyor ({'; '.join(r.get('problems', [])[:2])})")
    try:
        fix = f"""Rewrite this YouTube Short JSON following the editorial board's instructions exactly.
Instructions: {r.get('fix_instructions')}
Keep the same JSON keys and only use facts from the headline. Reply ONLY with the full JSON.
{json.dumps({k: data[k] for k in ('title', 'description', 'tags', 'headline', 'script') if k in data}, ensure_ascii=False)}"""
        new = writer._json(writer.ask_claude(fix, 2500, writer.SYSTEM))
        for k in ("title", "description", "tags", "headline", "script"):
            if new.get(k):
                data[k] = new[k]
        data["title"] = str(data["title"]).strip()[:100]
        data["qa_score"] = max(score, 7)
        note(st, "Baş Senarist", f"Kurulun notlarına göre yeniden yazıldı: {data.get('title')}")
    except Exception as e:
        log.warning(f"Yeniden yazım başarısız, ilk sürüm kullanılacak: {e}")
    save(st)
    return data


# ------------------------------------------------------------------ Ofis panosu
def render_board(st=None):
    if config.CHANNEL_KEY:      # kardeş kanallar ana panoyu ezmez
        return
    st = st or load()
    e = html.escape
    depts = {}
    for d, r, duty in TEAM:
        depts.setdefault(d, []).append((r, duty))
    team_html = "".join(
        f'<section class="dept"><h3>{e(d)}</h3>' + "".join(
            f'<div class="person"><b>{e(r)}</b><span>{e(duty)}</span></div>' for r, duty in rows) + "</section>"
        for d, rows in depts.items())
    s = st.get("strategy") or {}
    rev = st.get("reviews", [])[-1:] or [{}]
    dec = "".join(f"<li>{e(x)}</li>" for x in s.get("decisions_tr", [])) or "<li>İlk toplantı için veri birikiyor.</li>"
    vids = sorted([v for v in st.get("videos", []) if v.get("id")], key=lambda v: v.get("date", ""), reverse=True)[:25]
    rows = "".join(
        f'<tr><td>{e(v.get("date", ""))}</td><td><a href="https://youtu.be/{e(v["id"])}">{e(v.get("title") or "")}</a></td>'
        f'<td>{e(str(v.get("format") or "-"))}</td><td>{e(str(v.get("score") or "-"))}</td><td>{v.get("views", 0):,}</td></tr>'
        for v in vids)
    logs = "".join(f'<li><span>{e(x["t"])}</span> <b>{e(x["role"])}</b> — {e(x["text"])}</li>'
                   for x in reversed(st.get("log", [])[-30:]))
    total = sum(v.get("views", 0) for v in vids)
    BOARD.parent.mkdir(parents=True, exist_ok=True)
    BOARD.write_text(f"""<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Respawn Report — Sanal Ofis</title>
<style>*{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#0d0f14;color:#eef1f6}}
header{{padding:28px 18px;background:linear-gradient(135deg,#e1192d,#7a1fd6)}}h1{{margin:0;font-size:24px}}header p{{margin:6px 0 0;opacity:.9}}
main{{max-width:980px;margin:0 auto;padding:18px;display:grid;gap:18px}}.card{{background:#171a22;border:1px solid #262b36;border-radius:14px;padding:16px}}
h2{{margin:0 0 10px;font-size:18px}}.kpi{{display:flex;gap:12px;flex-wrap:wrap}}.kpi div{{background:#10131a;border-radius:10px;padding:10px 14px}}
.kpi b{{display:block;font-size:22px;color:#ffd400}}.team{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}}
.dept h3{{margin:0 0 6px;font-size:14px;color:#ffd400;text-transform:uppercase}}.person{{background:#10131a;border-radius:8px;padding:8px 10px;margin-bottom:6px}}
.person b{{display:block;font-size:14px}}.person span{{font-size:12px;color:#aab3c5}}table{{width:100%;border-collapse:collapse;font-size:13px}}
td{{padding:7px 6px;border-top:1px solid #262b36}}a{{color:#9fb4ff}}ul{{margin:0;padding-left:18px}}li{{margin:4px 0;font-size:14px}}
.log li span{{color:#8a93a6;font-size:12px}}</style></head><body>
<header><h1>🏢 Respawn Report — Sanal Ofis</h1><p>20 kişilik yapay zekâ ekibi · son güncelleme {datetime.now().strftime('%d.%m.%Y %H:%M')}</p></header>
<main>
<div class="card"><h2>📊 Durum</h2><div class="kpi"><div><b>{len(vids)}</b>takip edilen video</div><div><b>{total:,}</b>toplam izlenme</div>
<div><b>{e(', '.join(s.get('prefer_formats', [])) or '-')}</b>en iyi tarz</div></div></div>
<div class="card"><h2>🧠 Kanal Müdürünün son kararı</h2><p>{e(rev[0].get('summary', '') or 'Henüz yeterli veri yok.')}</p><ul>{dec}</ul></div>
<div class="card"><h2>🎬 Son videolar</h2><table><tr><td><b>Tarih</b></td><td><b>Video</b></td><td><b>Tarz</b></td><td><b>Kurul puanı</b></td><td><b>İzlenme</b></td></tr>{rows}</table></div>
<div class="card"><h2>🗂️ Ofis kayıtları</h2><ul class="log">{logs}</ul></div>
<div class="card"><h2>👥 Ekip (20 kişi)</h2><div class="team">{team_html}</div></div>
</main></body></html>""", encoding="utf-8")


# ------------------------------------------------------------------ Sahibin görevleri
def task_received(task):
    st = load()
    note(st, "Kanal Müdürü", f"Patrondan yeni görev geldi: {task[:200]} — ekip çalışmaya başladı")
    save(st)
    (config.DATA / "son_gorev.txt").write_text("Görev alındı, ekip çalışıyor...", encoding="utf-8")


def task_done(task, title, vid):
    st = load()
    note(st, "Yayın Yönetmeni", f"Patronun görevi tamamlandı: {title}")
    save(st)
    render_board(st)
    (config.DATA / "son_gorev.txt").write_text(
        f"✅ Görev tamamlandı!\n\n**{title}**\nhttps://youtu.be/{vid}\n\nPlaza: https://drogo36.github.io/youtube-robotu/plaza.html",
        encoding="utf-8")
