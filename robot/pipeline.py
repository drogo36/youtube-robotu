"""Tek bir videonun baştan sona üretimi: trend -> senaryo -> ses -> görsel -> kurgu -> yükleme."""
import json
import re
import shutil
from datetime import datetime

from . import config, db, trends, video, visuals, voice, writer
from .log import log


def _slug(text):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:50] or "video"


def _cleanup_outputs(keep=30):
    vids = sorted(config.OUTPUT.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in vids[keep:]:
        old.unlink(missing_ok=True)
        old.with_suffix(".json").unlink(missing_ok=True)


def make_one(upload=True):
    candidates, trending = trends.collect()
    if not candidates:
        log.info("Yeni haber yok, bu tur atlanıyor")
        return None
    story = writer.choose_topic(candidates, trending)
    if not story:
        db.mark_seen([c["link"] for c in candidates])
        log.info("Claude yeterince iyi bir konu bulamadı, bu tur atlanıyor")
        return None
    related = [a for a in trends.articles_for_topic(story["topic"]) if a["link"] != story["link"]]
    data = writer.write_video(story, related)
    log.info(f"Başlık: {data['title']}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    work = config.WORK / stamp
    work.mkdir(parents=True, exist_ok=True)
    try:
        voice_path, secs = voice.synthesize(data["script"], work / "ses.mp3")
        clips = visuals.stock_clips(data["pexels_queries"], secs + 1, work)
        if config.AI_IMAGES and data.get("image_prompts"):
            images = visuals.ai_images(data["image_prompts"], work)
            mixed = []  # yapay zekâ görseli ve stok video sırayla: görsel, klip, görsel, klip...
            for k in range(max(len(images), len(clips))):
                if k < len(images):
                    mixed.append(images[k])
                if k < len(clips):
                    mixed.append(clips[k])
            clips = mixed
        out = config.OUTPUT / f"{stamp}_{_slug(data['title'])}.mp4"
        video.render(data, voice_path, secs, clips, work, out)
        out.with_suffix(".json").write_text(json.dumps({**data, "source": story}, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
        db.mark_seen([story["link"]] + [a["link"] for a in related])

        from urllib.parse import quote_plus
        q = str(data.get("amazon_query") or "").strip()
        if config.AMAZON_TAG and q:   # ürün/indirim haberlerinde ortaklık linki = YouTube şartlarını beklemeden gelir
            data["description"] = (f"🛒 Check the price: https://www.amazon.com/s?k={quote_plus(q)}&tag={config.AMAZON_TAG}\n"
                                   f"(As an Amazon Associate we earn from qualifying purchases.)\n\n" + data["description"])

        vid = None
        if upload:
            vid = youtube_upload(out, data)
        from . import telegram
        telegram.send_video(out, (data.get("tiktok_caption") or data["title"]).strip())
        db.add_video(story["topic"], story["link"], data["title"], out, vid, "yuklendi" if vid else "uretildi")
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)
        _cleanup_outputs()


def youtube_upload(path, data):
    from . import youtube
    desc = data["description"].strip()
    return youtube.upload(path, data["title"], desc, data["tags"])
