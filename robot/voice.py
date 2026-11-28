"""Seslendirme: önce ücretsiz Microsoft Edge nöral sesleri (edge-tts), olmazsa Mac'in kendi 'say' sesi."""
import re
import shutil
import subprocess
import sys
import time

from . import config
from .log import log


def _duration(path):
    """Ses dosyasının süresi (saniye) — sadece ffmpeg ile, ffprobe gerektirmez."""
    out = subprocess.run([config.ffmpeg_bin(), "-hide_banner", "-i", str(path), "-f", "null", "-"],
                         capture_output=True, text=True)
    times = re.findall(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", out.stderr)
    if not times:
        m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", out.stderr)
        if not m:
            raise RuntimeError("Ses süresi okunamadı:\n" + out.stderr[-500:])
        times = [m.groups()]
    h, mnt, sec = times[-1]
    return int(h) * 3600 + int(mnt) * 60 + float(sec)


def _chunks(text, limit=220):
    """Metni cümle sınırlarından ~220 karakterlik parçalara böler (kısa istekler daha güvenilir)."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    parts, cur = [], ""
    for snt in sentences:
        if cur and len(cur) + len(snt) + 1 > limit:
            parts.append(cur)
            cur = snt
        else:
            cur = (cur + " " + snt).strip()
    if cur:
        parts.append(cur)
    return parts


def _edge_chunked(text, voice, out_mp3):
    import asyncio
    import edge_tts

    pieces = []
    for i, part in enumerate(_chunks(text)):
        piece = out_mp3.with_name(f"parca_{i:02d}.mp3")
        for attempt in range(1, 6):
            try:
                async def _run():
                    await asyncio.wait_for(edge_tts.Communicate(part, voice, rate="+12%").save(str(piece)), 120)
                asyncio.run(_run())
                if piece.exists() and piece.stat().st_size > 500:
                    break
                raise RuntimeError("boş ses")
            except Exception as e:
                piece.unlink(missing_ok=True)
                if attempt == 5:
                    raise RuntimeError(f"parça {i + 1} seslendirilemedi: {e}")
                time.sleep(4 * attempt)
        pieces.append(piece)
    lst = out_mp3.with_name("parcalar.txt")
    lst.write_text("".join(f"file '{p.name}'\n" for p in pieces), encoding="utf-8")
    subprocess.run([config.ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-ar", "44100", "-ac", "2", "-b:a", "192k", str(out_mp3)], check=True)
    log.info(f"Seslendirme tamam (Microsoft sesi, {len(pieces)} parça)")
    return out_mp3, _duration(out_mp3)


def synthesize(text, out_mp3):
    """Metni sese çevirir, (dosya_yolu, saniye) döndürür."""
    edge_voice, mac_voice = config.voices()
    txt_file = out_mp3.with_suffix(".txt")
    txt_file.write_text(text, encoding="utf-8")
    try:
        return _edge_chunked(text, edge_voice, out_mp3)
    except Exception as e:
        log.warning(f"edge-tts çalışmadı ({type(e).__name__}: {e}); Mac sesine geçiliyor")

    if shutil.which("say"):
        aiff = out_mp3.with_suffix(".aiff")
        subprocess.run(["say", "-v", mac_voice, "-r", "185", "-o", str(aiff), "-f", str(txt_file)], check=True)
        subprocess.run([config.ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(aiff), "-ar", "44100", "-ac", "2",
                        "-b:a", "192k", str(out_mp3)], check=True)
        return out_mp3, _duration(out_mp3)
    raise RuntimeError("Seslendirme yapılamadı: edge-tts kurulu değil ve 'say' komutu yok")
