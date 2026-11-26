#!/usr/bin/env python3
"""
YouTube Gündem Robotu
---------------------
Komutlar (Terminal'de proje klasöründeyken):
  python3 main.py kontrol   -> ayarlar ve gerekli programlar tamam mı?
  python3 main.py giris     -> YouTube hesabına bir kez giriş (tarayıcı açılır)
  python3 main.py dene      -> 1 video üretir, YÜKLEMEZ (veri/videolar klasörüne bakabilirsin)
  python3 main.py tek       -> 1 video üretir ve hemen yükler
  python3 main.py baslat    -> robotu sürekli çalıştırır (günde VIDEOS_PER_DAY video)
  python3 main.py durum     -> son videoların listesi
"""
import random
import os
import sys
import time
from datetime import datetime, timedelta

from robot import config, db
from robot.log import log


def cmd_kontrol():
    ok = True
    if config.ffmpeg_bin():
        print("✅ ffmpeg (video motoru) hazır")
    else:
        print("❌ ffmpeg bulunamadı  ->  kurulum.command dosyasını tekrar çalıştır")
        ok = False
    try:
        import edge_tts  # noqa: F401
        print("✅ edge-tts (seslendirme) kurulu")
    except ImportError:
        print("⚠️  edge-tts kurulu değil -> pip3 install -r requirements.txt  (yoksa Mac sesi kullanılır)")
    try:
        import PIL  # noqa: F401
        import requests  # noqa: F401
    except ImportError:
        print("❌ Python paketleri eksik  ->  pip3 install -r requirements.txt")
        ok = False
    for p in config.check(for_upload=True):
        print(("⚠️  " if "zorunlu değil" in p else "❌ ") + p)
        if "zorunlu değil" not in p:
            ok = False
    print(f"• Dil: {config.LANGUAGE} | Günde video: {config.VIDEOS_PER_DAY} | "
          f"Saatler: {config.ACTIVE_START_HOUR}:00-{config.ACTIVE_END_HOUR}:00 | Görünürlük: {config.PRIVACY}")
    print(f"• Takip edilen konular: {', '.join(config.WATCH_KEYWORDS)}")
    if config.TOKEN_FILE.exists():
        print("✅ YouTube girişi yapılmış")
    else:
        print("⚠️  YouTube girişi yok  ->  python3 main.py giris")
    print("\nHER ŞEY HAZIR ✅" if ok else "\nYukarıdaki ❌ maddeleri düzeltip tekrar çalıştır.")
    return ok


def _slots_for(day):
    """Gün içine eşit aralıklı, hafif rastgele yükleme saatleri."""
    rnd = random.Random(day.strftime("%Y%m%d"))
    start = day.replace(hour=config.ACTIVE_START_HOUR, minute=0, second=0, microsecond=0)
    span = max(1, config.ACTIVE_END_HOUR - config.ACTIVE_START_HOUR) * 60
    step = span / config.VIDEOS_PER_DAY
    return [start + timedelta(minutes=step * (k + 0.5) + rnd.randint(-20, 20))
            for k in range(config.VIDEOS_PER_DAY)]


def cmd_baslat():
    from robot import pipeline
    problems = [p for p in config.check(True) if "zorunlu değil" not in p]
    if problems:
        sys.exit("Eksik ayar var:\n- " + "\n- ".join(problems))
    log.info(f"🤖 Robot başladı. Günde {config.VIDEOS_PER_DAY} video. Durdurmak için Ctrl+C")
    retry_after = datetime.min
    last_run = datetime.min
    while True:
        now = datetime.now()
        done = db.uploads_today()
        slots = _slots_for(now)
        if done < len(slots) and now >= slots[done] and now >= retry_after \
                and now - last_run >= timedelta(minutes=60):
            last_run = now
            log.info(f"⏰ Sıradaki video zamanı geldi ({done + 1}/{len(slots)})")
            try:
                result = pipeline.make_one(upload=True)
                if result is None:
                    retry_after = now + timedelta(minutes=45)
            except SystemExit as e:
                log.error(str(e))
                if "kota" in str(e).lower():
                    retry_after = (now + timedelta(days=1)).replace(hour=config.ACTIVE_START_HOUR, minute=0)
                else:
                    retry_after = now + timedelta(hours=2)
            except Exception as e:
                log.exception(f"Hata oluştu, 30 dk sonra tekrar denenecek: {e}")
                retry_after = now + timedelta(minutes=30)
        time.sleep(60)


def cmd_durum():
    rows = db.summary()
    if not rows:
        print("Henüz video yok.")
    for created, status, vid, title in rows:
        link = f"https://youtube.com/shorts/{vid}" if vid else "-"
        print(f"{created}  {status:<9} {link:<45} {title}")
    print(f"\nBugün yüklenen: {db.uploads_today()}/{config.VIDEOS_PER_DAY}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "kontrol":
        cmd_kontrol()
    elif cmd == "giris":
        from robot import youtube
        youtube.login()
    elif cmd in ("dene", "tek"):
        from robot import pipeline
        if not (config.GEMINI_API_KEY or config.ANTHROPIC_API_KEY):
            sys.exit("Yapay zekâ anahtarı yok. .env dosyasına GEMINI_API_KEY yaz.")
        out = pipeline.make_one(upload=(cmd == "tek"))
        print(f"\n🎬 Video: {out}" if out else "\nBu tur video üretilmedi (loglara bak).")
    elif cmd == "uzun":
        # Haftalık uzun video (yatay, ~9 dk). Açıklamadaki Amazon linkleri tıklanabilir.
        from robot import longform
        out = longform.make_weekly(upload=True, task=os.environ.get("TASK", "").strip())
        print(f"\n🎬 Uzun video: {out}" if out else "\nUzun video üretilmedi (loglara bak).")
        if not out:
            sys.exit(1)
    elif cmd == "bulut":
        # GitHub Actions her tetiklendiğinde 1 video üretip yükler (günlük sınırı aşmadan)
        from robot import office, pipeline
        try:
            office.daily_review()   # Kanal Müdürü: günde bir kez izlenmeleri inceler, stratejiyi günceller
        except Exception as e:
            print(f"Ofis toplantısı atlandı: {e}")
        limit = 5 if os.environ.get("FORCE") == "1" else config.VIDEOS_PER_DAY  # elle çalıştırmada 2 ek video hakkı
        if db.uploads_today() >= limit:
            print("Bugünün video kotası dolu, atlanıyor.")
            return
        # Yedek zamanlayıcılar: son yüklemeden bu yana 3 saat geçmediyse bu tur atlanır (elle çalıştırma hariç)
        if os.environ.get("FORCE") != "1" and db.hours_since_last_upload() < 3:
            print("Son videodan bu yana 3 saat geçmedi, yedek tur atlanıyor.")
            return
        for attempt in range(2):
            try:
                if pipeline.make_one(upload=True, task=os.environ.get("TASK", "").strip()):
                    return
                print("Uygun yeni haber yok.")
                return
            except SystemExit:
                raise
            except Exception as e:
                log.exception(f"Bulut çalıştırması hata verdi (deneme {attempt + 1}/2): {e}")
        sys.exit(1)
    elif cmd == "bagla":
        # Kardeş dil kanalını robota bağlar (GitHub'daki "Kanal: es" kaydından gelir)
        from robot import youtube
        name, cid = youtube.link_channel(os.environ.get("KOD", ""))
        msg = f"✅ Bağlandı: {name} (https://www.youtube.com/channel/{cid}). Robot bu kanala kendi dilinde video yükleyecek."
        (config.DATA / "son_gorev.txt").write_text(msg, encoding="utf-8")
        print(msg)
    elif cmd == "kanal_ayar":
        # Kanallar sayfası için herkese açık ayar (OAuth istemci kimliği gizli değildir; her giriş adresinde görünür)
        import json
        from robot import youtube
        cid = youtube._client()["client_id"]
        root = config.ROOT / "veri" / "kanallar"
        linked = {k: (root / k / "token.enc").exists() for k in ("es", "pt", "id")}
        (config.ROOT / "docs" / "kanal-config.json").write_text(
            json.dumps({"client_id": cid, "linked": linked}), encoding="utf-8")
        print("Kanal ayarı yazıldı:", linked)
    elif cmd == "baslat":
        cmd_baslat()
    elif cmd == "durum":
        cmd_durum()
    else:
        print(__doc__)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nRobot durduruldu.")
