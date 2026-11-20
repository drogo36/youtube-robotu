"""Görseller: Pexels'ten telifsiz dikey videolar + ekrandaki yazılar (altyazı, başlık bandı)."""
import random
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config
from .log import log

W, H = 1080, 1920
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/ariblk.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def font(size):
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


# ---------------------------------------------------------------- Pexels
def _download(url, path):
    with requests.get(url, stream=True, timeout=60) as dl:
        dl.raise_for_status()
        with open(path, "wb") as fh:
            for chunk in dl.iter_content(1 << 20):
                fh.write(chunk)


def pixabay_clips(queries, need_seconds, folder):
    """Pixabay'den ücretsiz stok video indirir. Liste[(yol, süre)]."""
    clips, total, used = [], 0.0, set()
    for q in list(queries) + ["city night", "gaming", "car night"]:
        if total >= need_seconds:
            break
        try:
            r = requests.get("https://pixabay.com/api/videos/", timeout=20,
                             params={"key": config.PIXABAY_API_KEY, "q": q, "per_page": 10, "safesearch": "true"})
            r.raise_for_status()
            hits = r.json().get("hits", [])
        except Exception as e:
            log.warning(f"Pixabay araması başarısız ({q}): {e}")
            continue
        random.shuffle(hits)
        for h in hits[:2]:
            vids = h.get("videos", {})
            best = next((vids[k] for k in ("medium", "small", "large") if vids.get(k, {}).get("url")), None)
            if not best or h["id"] in used or h.get("duration", 0) < 4:
                continue
            path = folder / f"pixabay_{h['id']}.mp4"
            try:
                _download(best["url"], path)
            except Exception as e:
                log.warning(f"Pixabay videosu indirilemedi: {e}")
                continue
            used.add(h["id"])
            clips.append((path, float(h["duration"])))
            total += min(float(h["duration"]), 6.0)
            if total >= need_seconds:
                break
    log.info(f"Pixabay: {len(clips)} klip indirildi")
    return clips


def stock_clips(queries, need_seconds, folder):
    """Hangi anahtar varsa onunla stok video getirir; hiçbiri yoksa boş liste (renkli arka plan)."""
    if config.PIXABAY_API_KEY:
        return pixabay_clips(queries, need_seconds, folder)
    if config.PEXELS_API_KEY:
        return pexels_clips(queries, need_seconds, folder)
    return []


def pexels_clips(queries, need_seconds, folder):
    """Toplam süreyi dolduracak kadar dikey stok video indirir. Liste[(yol, süre)]."""
    if not config.PEXELS_API_KEY:
        return []
    headers = {"Authorization": config.PEXELS_API_KEY}
    clips, total, used_ids = [], 0.0, set()
    for q in list(queries) + ["city night aerial", "gaming neon", "car driving night"]:
        if total >= need_seconds:
            break
        try:
            r = requests.get("https://api.pexels.com/videos/search", headers=headers, timeout=20,
                             params={"query": q, "orientation": "portrait", "size": "medium", "per_page": 6})
            r.raise_for_status()
            videos = r.json().get("videos", [])
        except Exception as e:
            log.warning(f"Pexels araması başarısız ({q}): {e}")
            continue
        random.shuffle(videos)
        for v in videos[:2]:
            if v["id"] in used_ids or v.get("duration", 0) < 4:
                continue
            files = [f for f in v.get("video_files", [])
                     if f.get("height") and f.get("width") and f["height"] > f["width"] and f["height"] >= 1280
                     and f.get("file_type") == "video/mp4"]
            if not files:
                continue
            best = min(files, key=lambda f: abs(f["height"] - 1920))
            path = folder / f"pexels_{v['id']}.mp4"
            try:
                with requests.get(best["link"], stream=True, timeout=60) as dl:
                    dl.raise_for_status()
                    with open(path, "wb") as fh:
                        for chunk in dl.iter_content(1 << 20):
                            fh.write(chunk)
            except Exception as e:
                log.warning(f"Pexels videosu indirilemedi: {e}")
                continue
            used_ids.add(v["id"])
            clips.append((path, float(v["duration"])))
            total += min(float(v["duration"]), 7.0)
            if total >= need_seconds:
                break
    log.info(f"Pexels: {len(clips)} klip indirildi")
    return clips


def gradient_background(path, seed_text=""):
    """Pexels yoksa: koyu, hareketli kullanılacak büyük bir gradyan görsel."""
    rnd = random.Random(seed_text)
    palettes = [((12, 10, 40), (190, 20, 90)), ((5, 25, 45), (0, 160, 170)),
                ((25, 5, 45), (240, 120, 20)), ((10, 10, 10), (120, 40, 200))]
    c1, c2 = rnd.choice(palettes)
    bw, bh = W + 240, H + 240
    img = Image.new("RGB", (bw, bh))
    d = ImageDraw.Draw(img)
    for y in range(bh):
        t = y / bh
        d.line([(0, y), (bw, y)], fill=tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)))
    for _ in range(14):  # yumuşak ışık lekeleri
        x, y, r = rnd.randint(0, bw), rnd.randint(0, bh), rnd.randint(80, 260)
        blob = Image.new("L", (bw, bh), 0)
        ImageDraw.Draw(blob).ellipse([x - r, y - r, x + r, y + r], fill=rnd.randint(50, 110))
        glow = tuple(min(255, int(v * 1.25) + 30) for v in c2)
        img = Image.composite(Image.new("RGB", (bw, bh), glow), img,
                              blob.filter(ImageFilter.GaussianBlur(90)))
    img.save(path, quality=92)
    return path


# ---------------------------------------------------------------- yazılar
def _wrap(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=fnt) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def caption_png(text, path, size=88, highlight=None):
    """Altyazı görseli. highlight = o an söylenen kelimenin sırası (sarı + biraz büyük)."""
    img = Image.new("RGBA", (W, 560), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    words = text.upper().split()
    f, fb = font(size), font(int(size * 1.12))
    space = d.textlength(" ", font=f)
    lines, cur, cur_w = [], [], 0
    for i, w in enumerate(words):
        ww = d.textlength(w, font=fb if i == highlight else f)
        if cur and cur_w + space + ww > 960:
            lines.append(cur)
            cur, cur_w = [], 0
        cur.append((i, w, ww))
        cur_w += (space if len(cur) > 1 else 0) + ww
    if cur:
        lines.append(cur)
    line_h = int(size * 1.25)
    y = (560 - line_h * len(lines)) // 2
    for ln in lines:
        total = sum(ww for _, _, ww in ln) + space * (len(ln) - 1)
        x = (W - total) / 2
        for i, w, ww in ln:
            hot = i == highlight
            fnt = fb if hot else f
            dy = -int(size * 0.06) if hot else 0
            d.text((x, y + dy), w, font=fnt, fill=(255, 214, 0) if hot else (255, 255, 255),
                   stroke_width=9, stroke_fill=(0, 0, 0))
            x += ww + space
        y += line_h
    img.save(path)
    return path


def banner_png(headline, path, channel=""):
    img = Image.new("RGBA", (W, 420), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    size = 92
    f = font(size)
    while size > 50 and d.textlength(headline, font=f) > 900:
        size -= 4
        f = font(size)
    tw = d.textlength(headline, font=f)
    pad_x, box_h = 44, size + 60
    x0 = (W - tw) // 2 - pad_x
    y0 = 120
    d.rounded_rectangle([x0, y0, x0 + tw + pad_x * 2, y0 + box_h], radius=26, fill=(225, 25, 45, 245))
    d.text(((W - tw) // 2, y0 + (box_h - size) // 2 - 8), headline, font=f, fill=(255, 255, 255))
    if channel:
        cf = font(40)
        cw = d.textlength(channel, font=cf)
        d.text(((W - cw) // 2, y0 + box_h + 22), channel, font=cf, fill=(255, 255, 255, 230),
               stroke_width=3, stroke_fill=(0, 0, 0))
    img.save(path)
    return path


def caption_chunks(script, duration, max_words=3):
    """Senaryoyu 1-3 kelimelik parçalara böler; her kelimeye süre verir (karaoke için).
    Dönüş: [(parça_metni, [(kelime_sırası, başlangıç, bitiş), ...]), ...]"""
    words = script.replace("\n", " ").split()
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or w.endswith((".", "!", "?", ",", ":", ";")):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    weight = lambda w: len(w) + 2 + (4 if w.endswith((".", "!", "?")) else 0)
    total = sum(weight(w) for c in chunks for w in c)
    usable = max(duration - 0.2, 1)
    t, out = 0.05, []
    for c in chunks:
        timings = []
        for i, w in enumerate(c):
            dur = usable * weight(w) / total
            timings.append((i, round(t, 3), round(t + dur, 3)))
            t += dur
        out.append((" ".join(c), timings))
    return out
