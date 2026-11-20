"""Claude API ile konu seçimi ve özgün senaryo/başlık/açıklama yazımı."""
import json
import re
import time

import requests

from . import config, db
from .log import log

API_URL = "https://api.anthropic.com/v1/messages"
LANG_NAME = {"en": "English", "tr": "Turkish"}


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
    models = list(dict.fromkeys([config.GEMINI_MODEL, "gemini-flash-lite-latest", "gemini-flash-latest"]))
    last = None
    for attempt in range(6):
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
            wait = 15 * (attempt + 1)
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


def choose_topic(candidates, trending):
    if not candidates:
        return None
    listing = "\n".join(f"{i}. [{c['source']}] {c['title']} ({c['published'][:16]})"
                        for i, c in enumerate(candidates[:60]))
    recent = "\n".join(f"- {t}" for t in db.recent_titles()) or "- (none)"
    prompt = f"""Pick the ONE story that will get the most views as a YouTube Short right now for a gaming/tech audience.

Fresh headlines:
{listing}

Rising Google searches right now (boost stories that match these): {', '.join(trending) or 'n/a'}

Videos we already published this week (do NOT repeat the same story):
{recent}

Prefer: big franchises (GTA 6 first), official announcements, release dates, trailers, leaks with big buzz, price news.
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


def write_video(story, related):
    lang = LANG_NAME.get(config.LANGUAGE, "English")
    words = int(config.TARGET_SECONDS * (2.6 if config.LANGUAGE == "en" else 2.1))
    sources = "\n".join(f"- [{a['source']}] {a['title']}" for a in [story] + related)
    channel = config.CHANNEL_NAME or "our channel"
    prompt = f"""Write a YouTube Short in {lang} about this story.

Main headline: {story['title']}
Related headlines from other outlets (use them to cross-check facts):
{sources}

Rules:
- Use ONLY facts present in these headlines. If something is a leak/rumor, say so clearly.
- Script about {words} words (~{config.TARGET_SECONDS} seconds spoken). Spoken style, short punchy sentences, no emojis, no hashtags, no stage directions.
- Structure: 1-sentence hook that creates curiosity -> the facts -> your own analysis ("what this means for players") -> a quick question to the viewer to drive comments -> "Follow {channel} for daily updates." (in {lang}).
- Title: max 70 characters, curiosity + main keyword at the start, no clickbait lies, 1 emoji max. Add " #shorts" at the end.
- Description: 2-3 sentences summary in {lang}, then a line "Sources: " listing outlet names, then 3-5 hashtags.
- Tags: 10-15 relevant search tags.
- headline: 2-5 word ALL CAPS on-screen banner text.
- pexels_queries: 5 short ENGLISH stock-footage search terms that visually fit (e.g. "neon city night", "gaming setup", "miami beach aerial"). No brand names.

Reply ONLY with JSON:
{{"title": "...", "description": "...", "tags": ["..."], "headline": "...", "script": "...", "pexels_queries": ["..."]}}"""
    data = _json(ask_claude(prompt, 2500, SYSTEM))
    for key in ("title", "description", "script", "headline"):
        if not str(data.get(key, "")).strip():
            raise ValueError(f"Claude senaryosunda '{key}' alanı boş")
    data["title"] = data["title"].strip()[:100]
    data["tags"] = [str(t)[:60] for t in data.get("tags", [])][:15]
    data["pexels_queries"] = data.get("pexels_queries") or ["city night", "gaming"]
    return data
