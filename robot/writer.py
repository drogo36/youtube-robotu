"""Claude API ile konu seçimi ve özgün senaryo/başlık/açıklama yazımı."""
import json
import re
import time

import requests

from . import config, db
from .log import log

API_URL = "https://api.anthropic.com/v1/messages"
LANG_NAME = {"en": "English", "tr": "Turkish", "es": "Latin American Spanish", "pt": "Brazilian Portuguese",
             "id": "Indonesian", "hi": "Hindi"}


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def ask_claude(prompt, max_tokens=2500, system=None):
    """Yapay zekâya sorar: GEMINI_API_KEY varsa ücretsiz Gemini, yoksa Claude."""
    if config.GEMINI_API_KEY:
        return _ask_gemini(prompt, system)
    return _ask_anthropic(prompt, max_tokens, system)


def _ask_gemini(prompt, system=None):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.8}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    headers = {"x-goog-api-key": config.GEMINI_API_KEY, "content-type": "application/json"}
    models = list(dict.fromkeys([config.GEMINI_MODEL, "gemini-flash-lite-latest", "gemini-2.5-flash-lite",
                               "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash"]))
    last = None
    for attempt in range(10):   # Gemini ücretsiz katmanı yoğunken (503) daha uzun ve sabırlı dene
        model = models[attempt % len(models)]
        try:
            r = requests.post(GEMINI_URL.format(model=model), headers=headers, json=body, timeout=75)
            if r.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code == 404:
                raise RuntimeError(f"{model} modeli bulunamadı")
            if r.status_code != 200:
                raise SystemExit(f"Gemini API hatası {r.status_code}: {r.text[:400]}")
            cands = r.json().get("candidates") or []
            parts = (cands[0].get("content") or {}).get("parts", []) if cands else []
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            if not text.strip():
                raise RuntimeError("Gemini boş yanıt verdi")
            return text
        except (requests.RequestException, RuntimeError) as e:
            last = e
            wait = min(20 * (attempt + 1), 60)
            log.warning(f"Gemini ({model}) yanıt vermedi, {wait} sn sonra diğer modelle tekrar: {e}")
            time.sleep(wait)
    raise RuntimeError(f"Gemini API'ye ulaşılamadı: {last}")


def _ask_anthropic(prompt, max_tokens=2500, system=None):
    headers = {"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    body = {"model": config.CLAUDE_MODEL, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]}
    if system:
        body["system"] = system
    last = None
    for attempt in range(4):
        try:
            r = requests.post(API_URL, headers=headers, json=body, timeout=120)
            if r.status_code in (429, 500, 502, 503, 529):
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code != 200:
                raise SystemExit(f"Claude API hatası {r.status_code}: {r.text[:400]}")
            data = r.json()
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        except (requests.RequestException, RuntimeError) as e:
            last = e
            wait = 10 * (attempt + 1)
            log.warning(f"Claude API geçici hata, {wait} sn sonra tekrar: {e}")
            time.sleep(wait)
    raise RuntimeError(f"Claude API'ye ulaşılamadı: {last}")


def _json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("Claude yanıtında JSON bulunamadı")
    return json.loads(m.group(0))


SYSTEM = ("You are the head writer of a fast, trustworthy gaming & tech news Shorts channel. "
          "You never invent facts. Rumors and leaks are always clearly labeled as unconfirmed. "
          "Every video must add original value: context, analysis, what it means for players.")


def choose_topic(candidates, trending, task=""):
    if not candidates:
        return None
    listing = "\n".join(f"{i}. [{c['source']}] {c['title']} ({c['published'][:16]})"
                        for i, c in enumerate(candidates[:60]))
    recent = "\n".join(f"- {t}" for t in db.recent_titles()) or "- (none)"
    from . import office
    brief = office.strategy_brief()
    if task:
        brief += (f"\nTHE CHANNEL OWNER GAVE THIS ASSIGNMENT (top priority, may be in Turkish): {task}\n"
                  "Pick the story that best fulfils it. Only return -1 if nothing at all is related.\n")
    from . import trends
    perf = office.performance_brief() + trends.market_brief()
    prompt = f"""{brief}
{perf}
Pick the ONE story that will get the most views as a YouTube Short right now for a gaming/tech audience.

Fresh headlines:
{listing}

Rising Google searches right now (boost stories that match these): {', '.join(trending) or 'n/a'}

Videos we already published this week (do NOT repeat the same story):
{recent}

Rising searches are tagged with their country code: a story that is rising in several big markets (US, India, Brazil,
Indonesia, Mexico, Philippines...) has the biggest worldwide view potential — prefer it.
Prefer: stories with GLOBAL appeal that people in many countries would stop scrolling for (huge franchises, viral moments, shocking numbers, surprising tech, free stuff, big release dates, trailers, leaks with big buzz).
VIEWS FIRST (learned from our real data): plain deal/price-drop videos get almost no views on Shorts (often under 30).
Our winners were curiosity stories: leaks, surprising crossovers, shocking records, controversies, "is this real?" moments.
Only pick a deal story if it is EXTRAORDINARY (a hugely popular product at a historic low that everyone talks about), and
never two deal videos in a row.
VARIETY RULE: our recent videos are listed above. Do NOT pick the same game/franchise/company as our last 3 videos unless it is truly massive breaking news. Rotate between games, consoles, phones, AI and tech so the channel never feels repetitive.
Avoid: duplicates of what we published, minor/boring news, anything not gaming/tech.

Reply ONLY with JSON: {{"index": <number>, "topic": "<short search phrase for this story>", "reason": "<one sentence>"}}
If nothing is good enough, reply {{"index": -1}}."""
    data = _json(ask_claude(prompt, 400, SYSTEM))
    idx = int(data.get("index", -1))
    if idx < 0 or idx >= len(candidates):
        return None
    chosen = dict(candidates[idx])
    chosen["topic"] = data.get("topic") or chosen["title"]
    log.info(f"Seçilen konu: {chosen['title']}  —  {data.get('reason', '')}")
    return chosen


FORMATS = [
    ("breaking", "BREAKING NEWS style: urgent, fast, the single biggest fact first."),
    ("3things", "'3 THINGS you need to know' style: number them clearly (Number one..., Number two..., Number three...)."),
    ("didyouknow", "'You won't believe this' style: lead with the most surprising fact, then reveal context step by step like a mini story."),
    ("versus", "VERSUS / comparison style: compare it to something famous people already know (older game, rival product, past record)."),
    ("hottake", "HOT TAKE / prediction style: state a bold but reasonable opinion early, back it with the facts, invite people to disagree."),
]


def _lang_rule(lang):
    """İngilizce dışındaki kardeş kanallar için: her şey o dilde, doğal ve yerel."""
    if config.LANGUAGE == "en":
        return ""
    return (f"LANGUAGE (critical): this channel's audience speaks {lang}. Write the script, title, description, headline, "
            f"tiktok_caption and the comment question natively in {lang}, the way a young local gaming creator talks "
            f"(not a translation). Translate the fixed phrases too: 'Respawn verdict:' and 'Follow for more.' become "
            f"natural {lang} equivalents. Use local hashtags of that country plus global ones. Tags: mix {lang} and English. "
            f"pexels_queries and image_prompts stay in ENGLISH. Skip any line about deal links.\n")


def write_video(story, related, task=""):
    import random
    from . import office
    pref = [f for f in FORMATS if f[0] in office.preferred_formats()]
    # Kanal Müdürünün seçtiği tarzlar %70 ağırlıkla, diğerleri denemeye devam (öğrenmek için)
    fmt_name, fmt_rule = random.choice(pref) if pref and random.random() < 0.7 else random.choice(FORMATS)
    if story.get("evergreen"):
        fmt_name, fmt_rule = next(f for f in FORMATS if f[0] == "didyouknow")
    log.info(f"Video tarzı: {fmt_name}")
    lang = LANG_NAME.get(config.LANGUAGE, "English")
    words = int(config.TARGET_SECONDS * (2.6 if config.LANGUAGE == "en" else 2.1))
    sources = "\n".join(f"- [{a['source']}] {a['title']}" for a in [story] + related)
    channel = config.CHANNEL_NAME or "our channel"
    prompt = f"""Write a YouTube Short in {lang} about this story.

Main headline: {story['title']}
Related headlines from other outlets (use them to cross-check facts):
{sources}

Video format for this one: {fmt_rule}
{("REFERENCE TEXT (Wikipedia). Pick the 3 most surprising, little-known facts from it that would make a gamer say 'wait, what?'. Every fact must be stated in this text; never add outside facts, numbers or dates:" + chr(10) + story["context"]) if story.get("context") else ""}
{office.strategy_brief()}
{("Channel owner's assignment for this video (follow it; it may be in Turkish, but write the video in " + lang + "): " + task) if task else ""}

{_lang_rule(lang)}
Rules (this is for the YouTube Shorts algorithm: maximize retention, rewatches and comments worldwide):
- Use ONLY facts present in these headlines{" and the reference text below" if story.get("context") else ""}. If something is a leak/rumor, say so clearly.
- Script about {words} words (~{config.TARGET_SECONDS} seconds spoken). Very short punchy sentences (max 10 words). No emojis, no hashtags, no stage directions.
- HOOK: the first 6 words must create instant curiosity or shock (a bold claim, a surprising number, or a question). Never start with "Hey guys", "Today", "In this video" or the channel name.
- Pacing: a new fact or twist every 1-2 sentences. Use concrete numbers and comparisons people can feel ("more than double", "in just 24 hours").
- ORIGINALITY (very important, YouTube demonetizes generic mass-produced videos): add real analysis a fan would not get from the headline alone: why it matters for players, what it compares to, what is likely next. Include exactly one line that starts with "Respawn verdict:" giving our honest, specific opinion. Never pad, never repeat the headline in other words.
- End with a short question that makes people comment, then a final sentence that loops naturally back to the hook (so the Short replays seamlessly). Do NOT add a long outro; at most "Follow for more." before the loop line.
- Title: max 55 characters before the hashtags, written for a global audience. Make it a CURIOSITY GAP: tease the surprising part without giving it away ("Minecraft Was Almost Called This", "Nobody Noticed This In GTA 5"), main game/brand name in the first 3 words, honest (no fake claims), 1 emoji max. Never a plain price headline. End the title with 2 relevant hashtags plus #shorts (e.g. " #gta6 #gaming #shorts").
- Description: 2 sentences summary in {lang}, then a line "Sources: " listing outlet names, then a line with 10-12 popular, relevant hashtags (mix of broad ones like #gaming #shorts #viral #fyp #gamer and specific ones for this story). Never more than 12 hashtags.
- Tags: 15 high-search-volume tags people actually type (broad + specific, include common misspellings/short forms like "gta vi").
- headline: 2-4 word ALL CAPS on-screen banner that teases the story (curiosity, not a summary).
- pexels_queries: 6 short ENGLISH stock-footage search terms with strong motion and visual energy (e.g. "neon city night drive", "gamer hands controller closeup", "crowd cheering stadium"). No brand names.
- If the story is about something people can buy, the line right before the loop line must be: "Deal link is on our channel page." (Shorts description links are not clickable, the channel page link is.)
- amazon_query: if the story is about something people can BUY (a console, game, phone, accessory, a deal or price drop), a short Amazon search phrase for it (e.g. "Nintendo Switch 2 console"); otherwise "".
- tiktok_caption: a punchy TikTok caption (max 150 characters) ending with 4-5 TikTok hashtags (e.g. #gaming #gamingnews #fyp).
- image_prompts: 5 vivid ENGLISH prompts for an AI image generator, one per key moment of the script, in story order. Each describes a dramatic, eye-catching scene (subject, setting, action, mood, camera angle). NEVER name real people, brands, game titles or existing characters; describe original generic scenes instead (e.g. "neon-lit Miami-style beach city at sunset, sports car drifting, aerial shot").

Reply ONLY with JSON:
{{"title": "...", "description": "...", "tags": ["..."], "headline": "...", "script": "...", "pexels_queries": ["..."], "image_prompts": ["..."], "amazon_query": "", "tiktok_caption": "..."}}"""
    data = _json(ask_claude(prompt, 2500, SYSTEM))
    for key in ("title", "description", "script", "headline"):
        if not str(data.get(key, "")).strip():
            raise ValueError(f"Claude senaryosunda '{key}' alanı boş")
    data["title"] = data["title"].strip()[:100]
    data["format"] = fmt_name
    data["tags"] = [str(t)[:60] for t in data.get("tags", [])][:15]
    data["pexels_queries"] = data.get("pexels_queries") or ["city night", "gaming"]
    data["image_prompts"] = [str(x) for x in (data.get("image_prompts") or [])][:6]
    return data


def localize(title, description):
    """Başlık + kısa açıklamayı büyük pazarların dillerine çevirir (YouTube her izleyiciye kendi dilinde gösterir)."""
    langs = config.LOCALIZE_LANGS
    if not langs:
        return {}
    short = description.split("Sources:")[0].strip()[:400]
    tags = " ".join(w for w in description.split() if w.startswith("#"))[:200]
    prompt = f"""Translate this YouTube video title and description for viewers in these languages: {", ".join(langs)}.
Keep it natural, catchy and native for gamers in each country (not word-for-word). Keep emojis and product/game names.
Title max 90 characters. Do not add facts.

Title: {title}
Description: {short}

Reply ONLY with JSON: {{"<lang code>": {{"title": "...", "description": "..."}}, ...}}"""
    try:
        data = _json(ask_claude(prompt, 4000, SYSTEM))
    except Exception as e:
        log.warning(f"Çeviriler alınamadı: {e}")
        return {}
    out = {}
    for lang in langs:
        v = data.get(lang) or {}
        t, d = str(v.get("title", "")).strip(), str(v.get("description", "")).strip()
        if t and d:
            out[lang] = {"title": t[:100], "description": (d + ("\n\n" + tags if tags else ""))[:4900]}
    log.info(f"Çeviriler hazır: {len(out)} dil")
    return out
