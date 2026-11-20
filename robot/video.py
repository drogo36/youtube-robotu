"""Kurgu: arka plan + başlık bandı + altyazılar + seslendirme + müzik -> 1080x1920 Shorts videosu."""
import random
import subprocess

from . import config, visuals
from .log import log

FPS = 30


def _ff(args):
    cmd = [config.ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error"] + [str(a) for a in args]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError("ffmpeg hatası:\n" + res.stderr[-1500:])


def _background(clips, duration, work, seed):
    out = work / "arka_plan.mp4"
    if not clips:
        img = visuals.gradient_background(work / "arka_plan.jpg", seed)
        _ff(["-loop", "1", "-t", f"{duration:.2f}", "-i", img,
             "-vf", "crop=1080:1920:x='120+110*sin(t/4)':y='120+110*cos(t/5)',fps=30,format=yuv420p",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out])
        return out
    segs, t, i = [], 0.0, 0
    order = clips[:]
    while t < duration:
        path, clip_len = order[i % len(order)]
        seg_len = min(6.0, clip_len - 0.2, duration - t + 0.1)
        if seg_len < 1.0:
            seg_len = min(clip_len - 0.1, duration - t + 0.1)
        start = round(random.uniform(0, max(0.0, clip_len - seg_len - 0.2)), 2)
        seg = work / f"seg_{i:02d}.mp4"
        _ff(["-ss", start, "-t", f"{seg_len:.2f}", "-i", path, "-an",
             "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=1,format=yuv420p",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", seg])
        segs.append(seg)
        t += seg_len
        i += 1
        if i > 40:
            break
    lst = work / "liste.txt"
    lst.write_text("".join(f"file '{s.name}'\n" for s in segs), encoding="utf-8")
    _ff(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out])
    return out


def render(script_data, voice_path, voice_seconds, clips, work, out_path):
    duration = voice_seconds + 0.8
    bg = _background(clips, duration, work, script_data["title"])
    banner = visuals.banner_png(script_data["headline"].upper()[:40], work / "bant.png", config.CHANNEL_NAME)
    chunks = visuals.caption_chunks(script_data["script"], voice_seconds)

    inputs = ["-i", bg, "-i", voice_path]
    music_files = sorted(list(config.MUSIC.glob("*.mp3")) + list(config.MUSIC.glob("*.m4a")))
    has_music = bool(music_files)
    if has_music:
        inputs += ["-stream_loop", "-1", "-i", random.choice(music_files)]
    img_start = 3 if has_music else 2
    inputs += ["-i", banner]
    cap_paths = []
    for n, (text, _, _) in enumerate(chunks):
        p = visuals.caption_png(text, work / f"alt_{n:03d}.png")
        cap_paths.append(p)
        inputs += ["-i", p]

    f = [f"[0:v]drawbox=x=0:y=0:w=iw:h=ih:color=black@0.32:t=fill[v0]",
         f"[v0][{img_start}:v]overlay=0:0[v1]"]
    last = "v1"
    for n, (_, a, b) in enumerate(chunks):
        idx = img_start + 1 + n
        nxt = f"c{n}"
        f.append(f"[{last}][{idx}:v]overlay=0:1150:enable='between(t,{a},{b})'[{nxt}]")
        last = nxt
    if has_music:
        f.append(f"[1:a]volume=1.0[va];[2:a]volume={config.MUSIC_VOLUME},"
                 f"afade=t=out:st={max(duration - 1.5, 0):.2f}:d=1.5[ma];"
                 f"[va][ma]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]")
    else:
        f.append("[1:a]apad[aout]")

    (work / "filtre.txt").write_text(";\n".join(f), encoding="utf-8")  # hata ayıklama için kayıt
    _ff(inputs + ["-filter_complex", ";".join(f), "-map", f"[{last}]", "-map", "[aout]",
                  "-t", f"{duration:.2f}", "-r", FPS, "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                  "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
                  "-movflags", "+faststart", out_path])
    log.info(f"Video hazır: {out_path.name} ({duration:.1f} sn, {len(chunks)} altyazı)")
    return out_path
