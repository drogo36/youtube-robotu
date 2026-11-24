"""Haftalık uzun video (yatay 1920x1080, ~8-10 dk): haftanın en büyük oyun/teknoloji haberleri.
Uzun videolarda açıklamadaki linkler TIKLANABİLİR -> Amazon ortaklık linkleri burada gerçekten çalışır."""
import json
import random
import shutil
from datetime import datetime
from urllib.parse import quote_plus

from PIL import Image, ImageDraw, ImageFilter

from . import config, db, trends, visuals, voice, writer
from .log import log
from .video import _ff

W, H = 1920, 1080
PALETTE = [((255, 214, 0), (225, 25, 45)), ((0, 230, 255), (120, 30, 220)), ((255, 120, 0), (10, 90, 200)),
           ((120, 255, 80), (20, 120, 60)), ((255, 70, 160), (60, 20, 140))]


# ------------------------------------------------------------------ senaryo
def write_long(stories):
    listing = "\n".join(f"- [{s['source']}] {s['title']}" for s in stories[:40])
    words = int(config.LONG_MINUTES * 150)
    prompt = f"""Write a YouTube long-form video (about {config.LONG_MINUTES} minutes, ~{words} words of narration in English)
for a gaming & tech news channel: "This Week in Gaming & Tech".

Headlines from this week:
{listing}

Rules:
- Pick the 7 or 8 most interesting stories for a GLOBAL audience. Use ONLY facts in the headlines; label rumors/leaks clearly.
- Cold open (first chapter, ~40 words): tease the 3 biggest stories with a hook, no "hey guys", no channel intro.
- Each following chapter: one story, ~130-170 words: what happened, why it matters, comparison/context, and one honest
  opinion line starting with "Respawn verdict:". Short sentences, energetic, easy to follow.
- Last chapter (~60 words): quick recap + ask viewers to comment which story they care about most + subscribe.
- For chapters about something buyable (console, game, phone, accessory, deal) give amazon_query (short search phrase), else "".
- For each chapter give 3 ENGLISH stock-footage search terms (no brand names) with strong motion.
- title: max 70 characters, curiosity + main keyword first, honest. thumbnail_text: 2-4 BIG words.
- description: 3 sentence summary. tags: 15 search tags.

Reply ONLY with JSON:
{{"title": "...", "thumbnail_text": "...", "description": "...", "tags": ["..."],
 "chapters": [{{"heading": "...", "script": "...", "queries": ["...", "...", "..."], "amazon_query": ""}}]}}"""
    data = writer._json(writer.ask_claude(prompt, 6000, writer.SYSTEM))
    chapters = [c for c in data.get("chapters", []) if str(c.get("script", "")).strip()]
    if len(chapters) < 4:
        raise ValueError("Uzun video senaryosu çok kısa geldi")
    data["chapters"] = chapters
    return data


# ------------------------------------------------------------------ görseller
def _title_card(text, idx, path):
    acc, band = PALETTE[idx % len(PALETTE)]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = visuals.font(96)
    text = text.upper()
    lines = visuals._wrap(d, text, f, 1500)[:3]
    box_h = 70 + 115 * len(lines)
    y0 = (H - box_h) // 2
    d.rounded_rectangle([140, y0, W - 140, y0 + box_h], radius=36, fill=band + (235,))
    d.rectangle([140, y0, 170, y0 + box_h], fill=acc + (255,))
    y = y0 + 35
    for ln in lines:
        d.text(((W - d.textlength(ln, font=f)) / 2, y), ln, font=f, fill=(255, 255, 255),
               stroke_width=4, stroke_fill=(0, 0, 0))
        y += 115
    if idx > 0:
        nf = visuals.font(54)
        d.text((190, y0 - 80), f"#{idx}", font=nf, fill=acc, stroke_width=4, stroke_fill=(0, 0, 0))
    img.save(path)
    return path


def _lower_caption(text, idx, path):
    acc, band = PALETTE[idx % len(PALETTE)]
    img = Image.new("RGBA", (W, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = visuals.font(62)
    tw = d.textlength(text, font=f)
    x0 = (W - tw) / 2 - 40
    d.rounded_rectangle([x0, 30, x0 + tw + 80, 170], radius=26, fill=(10, 10, 16, 200))
    d.rectangle([x0, 160, x0 + tw + 80, 170], fill=acc + (255,))
    d.text(((W - tw) / 2, 58), text, font=f, fill=(255, 255, 255))
    img.save(path)
    return path


def _brand(path):
    img = Image.new("RGBA", (520, 90), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, 520, 90], radius=20, fill=(225, 25, 45, 220))
    f = visuals.font(44)
    d.text((26, 18), "RESPAWN REPORT", font=f, fill=(255, 255, 255))
    img.save(path)
    return path


def _chunks(script, seconds, n_words=7):
    words = script.split()
    groups = [" ".join(words[i:i + n_words]) for i in range(0, len(words), n_words)]
    total = sum(len(g) for g in groups) or 1
    t, out = 0.0, []
    for g in groups:
        dur = seconds * len(g) / total
        out.append((g, round(t, 2), round(t + dur, 2)))
        t += dur
    return out


def _motion(i, L):
    base = "fps=30,scale=2112:1188:force_original_aspect_ratio=increase,crop=2112:1188"
    k = i % 3
    if k == 0:
        z = f"scale=w='2*trunc(2112*(1+0.10*t/{L:.2f})/2)':h=-2:eval=frame,crop=1920:1080"
    elif k == 1:
        z = f"scale=w='2*trunc(2112*(1.10-0.10*t/{L:.2f})/2)':h=-2:eval=frame,crop=1920:1080"
    else:
        z = f"crop=1920:1080:x='(iw-1920)*t/{L:.2f}':y='(ih-1080)/2'"
    return base + "," + z + ",eq=saturation=1.35:contrast=1.08"


def _background(clips, duration, work, tag):
    segs, t, i = [], 0.0, 0
    while t < duration and i < 80:
        path, clip_len = clips[i % len(clips)]
        if clip_len == "img":
            clip_len = 99.0
        L = max(1.0, min(random.uniform(3.0, 4.5), clip_len - 0.2, duration - t + 0.2))
        start = round(random.uniform(0, max(0.0, clip_len - L - 0.2)), 2)
        seg = work / f"{tag}_s{i:02d}.mp4"
        src = (["-loop", "1", "-framerate", "30", "-t", f"{L:.2f}", "-i", path] if str(path).endswith(".jpg")
               else ["-ss", start, "-t", f"{L:.2f}", "-i", path])
        flash = "" if i == 0 else ",fade=t=in:st=0:d=0.15:color=white"
        _ff(src + ["-an", "-vf", _motion(i, L) + ",setsar=1,format=yuv420p" + flash,
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", seg])
        segs.append(seg)
        t += L
        i += 1
    args = []
    for s in segs:
        args += ["-i", s]
    out = work / f"{tag}_bg.mp4"
    graph = "".join(f"[{k}:v]" for k in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0,fps=30[v]"
    _ff(args + ["-filter_complex", graph, "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", out])
    return out


def _render_chapter(idx, ch, work):
    tag = f"ch{idx:02d}"
    voice_path, secs = voice.synthesize(ch["script"], work / f"{tag}.mp3")
    duration = secs + 0.7
    clips = visuals.stock_clips(ch.get("queries") or ["gaming", "city night"], duration + 2, work)
    if not clips:
        clips = [(visuals.gradient_background(work / f"{tag}_grad.jpg", ch["heading"]), "img")]
    bg = _background(clips, duration, work, tag)
    inputs = ["-i", bg, "-i", voice_path, "-i", _brand(work / "brand.png"),
              "-i", _title_card(ch["heading"], idx, work / f"{tag}_title.png")]
    caps = _chunks(ch["script"], secs)
    for n, (text, a, b) in enumerate(caps):
        inputs += ["-i", _lower_caption(text, idx, work / f"{tag}_c{n:03d}.png")]
    f = ["[0:v]setpts=N/(30*TB),drawbox=x=0:y=0:w=iw:h=ih:color=black@0.12:t=fill[v0]",
         "[v0][2:v]overlay=x=40:y=36[v1]",
         "[v1][3:v]overlay=x='if(lt(t,0.4),-1920+1920*t/0.4,0)':y=0:enable='lt(t,2.6)'[v2]"]
    last = "v2"
    for n, (text, a, b) in enumerate(caps):
        if b < 2.6:
            continue
        a = max(a, 2.6)
        f.append(f"[{last}][{4 + n}:v]overlay=0:850:enable='gte(t,{a})*lt(t,{b})'[c{n}]")
        last = f"c{n}"
    f.append("[1:a]apad[aout]")
    out = work / f"{tag}.mp4"
    _ff(inputs + ["-filter_complex", ";".join(f), "-map", f"[{last}]", "-map", "[aout]", "-t", f"{duration:.2f}",
                  "-r", 30, "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", out])
    for p in work.glob(f"{tag}_s*.mp4"):
        p.unlink(missing_ok=True)
    for p in work.glob("pixabay_*.mp4"):
        p.unlink(missing_ok=True)
    return out, duration


def _thumbnail(text, frame_src, path):
    acc, band = random.choice(PALETTE)
    try:
        _ff(["-ss", "6", "-i", frame_src, "-frames:v", "1", path.with_suffix(".frame.jpg")])
        bg = Image.open(path.with_suffix(".frame.jpg")).convert("RGB").resize((1280, 720))
    except Exception:
        bg = Image.new("RGB", (1280, 720), band)
    from PIL import ImageEnhance
    bg = ImageEnhance.Color(bg).enhance(1.6)
    bg = ImageEnhance.Contrast(bg).enhance(1.2)
    d = ImageDraw.Draw(bg)
    f = visuals.font(130)
    lines = visuals._wrap(d, text.upper(), f, 1180)[:2]
    y = 720 - 40 - 150 * len(lines)
    for ln in lines:
        d.text((60, y), ln, font=f, fill=acc, stroke_width=10, stroke_fill=(0, 0, 0))
        y += 150
    d.rounded_rectangle([40, 36, 520, 120], radius=20, fill=(225, 25, 45))
    d.text((66, 50), "THIS WEEK", font=visuals.font(58), fill=(255, 255, 255))
    bg.save(path, quality=92)
    return path


def _ts(sec):
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}"


# ------------------------------------------------------------------ ana akış
def make_weekly(upload=True):
    stories = []
    for kw in list(config.WATCH_KEYWORDS)[:14] + list(config.DEAL_KEYWORDS)[:4]:
        stories += trends.google_news(kw, max_age_hours=24 * 7)
    seen, uniq = set(), []
    for s in stories:
        k = s["title"].lower()[:60]
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    random.shuffle(uniq)
    if len(uniq) < 6:
        log.info("Uzun video için yeterli haber yok")
        return None
    data = write_long(uniq)
    log.info(f"Uzun video: {data['title']} ({len(data['chapters'])} bölüm)")
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    work = config.WORK / f"uzun_{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        parts, t, chapters_desc, buy_lines = [], 0.0, [], []
        for i, ch in enumerate(data["chapters"]):
            out, dur = _render_chapter(i, ch, work)
            parts.append(out)
            chapters_desc.append(f"{_ts(t)} {ch['heading']}")
            q = str(ch.get("amazon_query") or "").strip()
            if q and config.AMAZON_TAG:
                buy_lines.append(f"🛒 {ch['heading']}: https://www.amazon.com/s?k={quote_plus(q)}&tag={config.AMAZON_TAG}")
            t += dur
            log.info(f"Bölüm {i + 1}/{len(data['chapters'])} hazır ({dur:.0f} sn)")
        lst = work / "liste.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        final = config.OUTPUT / f"{stamp}_haftalik.mp4"
        _ff(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", final])
        if chapters_desc and not chapters_desc[0].startswith("00:00"):
            chapters_desc[0] = "00:00 " + chapters_desc[0].split(" ", 1)[1]
        desc = data["description"].strip() + "\n\n"
        if buy_lines:
            desc += "Deals & prices mentioned in this video:\n" + "\n".join(buy_lines) + \
                    "\n(As an Amazon Associate we earn from qualifying purchases.)\n\n"
        desc += "All deals from our Shorts: https://drogo36.github.io/youtube-robotu/\n\nChapters:\n" + \
                "\n".join(chapters_desc) + "\n\n#gaming #gamingnews #tech #technews"
        thumb = _thumbnail(data.get("thumbnail_text") or data["title"], parts[min(1, len(parts) - 1)],
                           work / "kapak.jpg")
        vid = None
        if upload:
            from . import youtube
            vid = youtube.upload(final, data["title"][:100], desc, data.get("tags", []))
            youtube.set_thumbnail(vid, thumb)
        db.add_video("haftalik", "", data["title"], final, vid, "yuklendi" if vid else "uretildi")
        log.info(f"Haftalık uzun video tamam: {t / 60:.1f} dk")
        return final
    finally:
        shutil.rmtree(work, ignore_errors=True)
