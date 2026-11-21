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


def _motion(i, seg_len):
    """Her sahneye farklı kamera hareketi: yakınlaş / uzaklaş / yana kay (Ken Burns)."""
    L = max(seg_len, 0.5)
    base = "fps=30,scale=1188:2112:force_original_aspect_ratio=increase,crop=1188:2112"
    kind = i % 3
    if kind == 0:    # yakınlaş
        zoom = f"scale=w='2*trunc(1188*(1+0.12*t/{L:.2f})/2)':h=-2:eval=frame,crop=1080:1920"
    elif kind == 1:  # uzaklaş
        zoom = f"scale=w='2*trunc(1188*(1.12-0.12*t/{L:.2f})/2)':h=-2:eval=frame,crop=1080:1920"
    else:            # yana kay
        zoom = f"crop=1080:1920:x='(iw-1080)*t/{L:.2f}':y='(ih-1920)/2'"
    return base + "," + zoom


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
        is_img = clip_len == "img"
        if is_img:
            clip_len = 99.0
        seg_len = min(random.uniform(2.4, 3.4), clip_len - 0.2, duration - t + 0.1)
        if seg_len < 1.0:
            seg_len = min(clip_len - 0.1, duration - t + 0.1)
        start = round(random.uniform(0, max(0.0, clip_len - seg_len - 0.2)), 2)
        seg = work / f"seg_{i:02d}.mp4"
        flash = "" if i == 0 else ",fade=t=in:st=0:d=0.18:color=white"
        src = (["-loop", "1", "-framerate", "30", "-t", f"{seg_len:.2f}", "-i", path] if is_img
               else ["-ss", start, "-t", f"{seg_len:.2f}", "-i", path])
        _ff(src + ["-an",
             "-vf", _motion(i, seg_len) + ",setsar=1,format=yuv420p" + flash,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", seg])
        segs.append(seg)
        t += seg_len
        i += 1
        if i > 60:
            break
    # Sahneleri concat filtresiyle birleştir (zaman damgaları kaymaz)
    args = []
    for sg in segs:
        args += ["-i", sg]
    graph = "".join(f"[{k}:v]" for k in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0,fps=30[v]"
    _ff(args + ["-filter_complex", graph, "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "19", out])
    return out


def render(script_data, voice_path, voice_seconds, clips, work, out_path):
    duration = voice_seconds + 0.8
    visuals.set_theme(script_data["title"])
    bar_hex = "0x%02X%02X%02X" % visuals.ACCENT
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
    overlays = []  # (girdi_sırası, başlangıç, bitiş)
    n_img = 0
    for c_idx, (text, timings) in enumerate(chunks):
        for w_idx, a, b in timings:
            p = visuals.caption_png(text, work / f"alt_{c_idx:03d}_{w_idx}.png", highlight=w_idx)
            inputs += ["-i", p]
            n_img += 1
            overlays.append((img_start + n_img, a, b))

    D = f"{duration:.2f}"
    f = [f"[0:v]setpts=N/(30*TB),drawbox=x=0:y=0:w=iw:h=ih:color=black@0.30:t=fill[v0]",
         f"color=c={bar_hex}:s=1080x16:r=30[bar]",
         f"[v0][bar]overlay=x='-1080+1080*t/{D}':y=1904:shortest=1[vb]",   # ilerleme çubuğu
         f"[vb][{img_start}:v]overlay=x=0:y='if(lt(t,0.35),-420+420*t/0.35,0)'[v1]"]   # kayan başlık bandı
    last = "v1"
    for n, (idx, a, b) in enumerate(overlays):
        nxt = f"c{n}"
        f.append(f"[{last}][{idx}:v]overlay=0:1120:enable='gte(t,{a})*lt(t,{b})'[{nxt}]")
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
    log.info(f"Video hazır: {out_path.name} ({duration:.1f} sn, {len(overlays)} karaoke kare)")
    return out_path
