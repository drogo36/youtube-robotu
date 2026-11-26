"""YouTube resmi API (Data API v3) ile giriş ve video yükleme. Ek kütüphane gerektirmez."""
import base64
import hashlib
import http.server
import json
import subprocess
import os
import secrets
import socket
import threading
import time
import urllib.parse
import webbrowser

import requests

from . import config
from .log import log

SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


def _env(name):
    """Gizli anahtarı okur; kopyalarken karışan boşluk, satır sonu ve 'Secret:' ön ekini temizler."""
    v = os.environ.get(name, "").strip().strip('"').strip("'").strip()
    for prefix in ("secret:", "name:"):
        if v.lower().startswith(prefix):
            v = v[len(prefix):].strip()
    return v


def _client():
    # Bulut (GitHub Actions): bilgiler gizli ortam değişkenlerinden gelir
    if _env("YT_CLIENT_ID"):
        return {"client_id": _env("YT_CLIENT_ID"), "client_secret": _env("YT_CLIENT_SECRET"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"}
    if not config.CLIENT_SECRET_FILE.exists():
        raise SystemExit("client_secret.json bulunamadı. Kurulum rehberindeki 'YouTube API' adımını yap.")
    data = json.loads(config.CLIENT_SECRET_FILE.read_text(encoding="utf-8"))
    c = data.get("installed") or data.get("web")
    if not c:
        raise SystemExit("client_secret.json hatalı. Google Cloud'da 'Masaüstü uygulaması' türünde oluşturulmalı.")
    return c


# ------------------------------------------------------------------ giriş
def login():
    """Tarayıcıda Google hesabıyla bir kez giriş yapılır; jeton kaydedilir."""
    c = _client()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    redirect = f"http://127.0.0.1:{port}"
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q or "error" in q:
                result.update({k: v[0] for k, v in q.items()})
                ok = "code" in q and q.get("state", [""])[0] == state
                msg = ("Giris basarili! Bu pencereyi kapatip terminale donebilirsin." if ok
                       else "Giris basarisiz. Terminaldeki mesaja bak.")
            else:
                msg = "Bekleniyor..."
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<h2 style='font-family:sans-serif'>{msg}</h2>".encode())

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = c["auth_uri"] + "?" + urllib.parse.urlencode({
        "client_id": c["client_id"], "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPES, "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    (config.DATA / "giris_adresi.txt").write_text(url, encoding="utf-8")
    print("\nTarayıcı açılıyor. Açılmazsa şu adresi kopyalayıp tarayıcına yapıştır:\n" + url + "\n")
    webbrowser.open(url)
    for _ in range(600):
        if result:
            break
        time.sleep(0.5)
    server.shutdown()
    if "code" not in result or result.get("state") != state:
        raise SystemExit(f"Giriş tamamlanamadı: {result.get('error', 'zaman aşımı')}")
    r = requests.post(c["token_uri"], data={
        "code": result["code"], "client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier}, timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"Jeton alınamadı: {r.text[:300]}")
    tok = r.json()
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    config.TOKEN_FILE.write_text(json.dumps(tok, indent=2), encoding="utf-8")
    try:
        os.chmod(config.TOKEN_FILE, 0o600)
    except OSError:
        pass
    name = channel_name()
    print(f"✅ YouTube girişi tamam. Bağlanan kanal: {name}")
    return name


MAIN_CHANNEL_ID = "UC2gYCJRku-P0QIeNCdA4d-Q"     # İngilizce ana kanal (Respawn Report)
LINK_REDIRECT = "http://127.0.0.1:8765"         # kanal-bagla sayfasının kullandığı dönüş adresi
TOKEN_ENC = config.DATA / "token.enc"           # kardeş kanalın anahtarı, şifreli olarak depoda durur


def _crypt(data, decrypt=False):
    """Kardeş kanal anahtarını şifreler/çözer. Şifre, GitHub gizli anahtarı YT_CLIENT_SECRET'tir."""
    key = _env("YT_CLIENT_SECRET")
    if not key:
        raise SystemExit("YT_CLIENT_SECRET yok, kanal anahtarı çözülemez.")
    args = ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-a", "-A", "-pass", "env:TOKEN_KEY"]
    args += ["-d"] if decrypt else ["-salt"]
    return subprocess.run(args, input=data, capture_output=True, check=True,
                          env={**os.environ, "TOKEN_KEY": key}).stdout


def link_channel(url_or_code):
    """Telefondan/tarayıcıdan gelen Google onay kodunu kalıcı anahtara çevirir (kardeş kanallar için)."""
    from urllib.parse import urlparse, parse_qs
    txt = url_or_code.strip()
    q = parse_qs(urlparse(txt).query)
    code = (q.get("code", [""])[0] if "code=" in txt else txt).strip()
    verifier = q.get("verifier", [""])[0].strip()
    if not code:
        raise SystemExit("Adreste onay kodu bulunamadı. Adres çubuğundaki tam adresi kopyala.")
    c = _client()
    r = requests.post(c["token_uri"], data={"code": code, "client_id": c["client_id"],
                      "client_secret": c.get("client_secret", ""), "redirect_uri": LINK_REDIRECT,
                      "grant_type": "authorization_code", **({"code_verifier": verifier} if verifier else {})},
                      timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"Google kodu kabul etmedi (kod 10 dakikada bir eskir, tekrar dene): {' '.join(r.text.split())[:200]}")
    tok = r.json()
    if not tok.get("refresh_token"):
        raise SystemExit("Google kalıcı anahtar vermedi. Sayfadaki 'Robota bağla' düğmesinden baştan dene.")
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    config.TOKEN_FILE.write_text(json.dumps(tok), encoding="utf-8")
    ch = requests.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet", "mine": "true"},
                      headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=30).json().get("items", [])
    if not ch:
        config.TOKEN_FILE.unlink(missing_ok=True)
        raise SystemExit("Seçilen hesapta YouTube kanalı yok. Onay ekranında yeni kanalı seç.")
    if ch[0]["id"] == MAIN_CHANNEL_ID:
        config.TOKEN_FILE.unlink(missing_ok=True)
        raise SystemExit("Ana kanal (Respawn Report) seçildi. Onay ekranında YENİ dil kanalını seçmelisin.")
    TOKEN_ENC.write_bytes(_crypt(tok["refresh_token"].encode()))
    return ch[0]["snippet"]["title"], ch[0]["id"]


def _token():
    if config.CHANNEL_KEY and not config.TOKEN_FILE.exists():
        if not TOKEN_ENC.exists():
            raise SystemExit(f"'{config.CHANNEL_KEY}' kanalı henüz robota bağlanmadı (kanallar sayfasından bağla).")
        rt = _crypt(TOKEN_ENC.read_bytes(), decrypt=True).decode().strip()
        config.TOKEN_FILE.write_text(json.dumps({"refresh_token": rt, "expires_at": 0}), encoding="utf-8")
    if not config.CHANNEL_KEY and _env("YT_REFRESH_TOKEN") and not config.TOKEN_FILE.exists():
        config.TOKEN_FILE.write_text(json.dumps({"refresh_token": _env("YT_REFRESH_TOKEN"), "expires_at": 0}),
                                     encoding="utf-8")
    if not config.TOKEN_FILE.exists():
        raise SystemExit("YouTube girişi yapılmamış. Önce:  python3 main.py giris")
    tok = json.loads(config.TOKEN_FILE.read_text(encoding="utf-8"))
    if time.time() < tok.get("expires_at", 0):
        return tok["access_token"]
    c = _client()
    r = requests.post(c["token_uri"], data={
        "client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
        "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"}, timeout=30)
    if r.status_code != 200:
        raise SystemExit("YouTube oturumu düştü. Tekrar giriş yap:  python3 main.py giris\n" + r.text[:300])
    new = r.json()
    tok["access_token"] = new["access_token"]
    tok["expires_at"] = time.time() + new.get("expires_in", 3600) - 60
    config.TOKEN_FILE.write_text(json.dumps(tok, indent=2), encoding="utf-8")
    return tok["access_token"]


def channel_name():
    r = requests.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet", "mine": "true"},
                     headers={"Authorization": f"Bearer {_token()}"}, timeout=30)
    items = r.json().get("items", []) if r.status_code == 200 else []
    return items[0]["snippet"]["title"] if items else "(kanal bulunamadı — Google hesabında YouTube kanalı açılmış mı?)"


# ------------------------------------------------------------------ yükleme
def _safe_tags(tags, limit=480):
    """YouTube etiketlerin toplamını 500 karakterle sınırlar; aşarsa yükleme hata verir."""
    out, total = [], 0
    for t in tags:
        t = str(t).replace("<", "").replace(">", "").replace(",", " ").strip()
        cost = len(t) + (2 if " " in t else 0) + 1
        if not t or total + cost > limit:
            continue
        out.append(t)
        total += cost
    return out


def upload(video_path, title, description, tags, privacy=None, localizations=None):
    tags = _safe_tags(tags)
    privacy = privacy or config.PRIVACY
    meta = {
        "snippet": {"title": title[:100], "description": description[:4900], "tags": tags,
                    "categoryId": "20", "defaultLanguage": config.LANGUAGE,
                    "defaultAudioLanguage": config.LANGUAGE},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False, "embeddable": True},
    }
    if localizations:
        meta["localizations"] = localizations
    parts = "snippet,status,localizations" if localizations else "snippet,status"
    size = video_path.stat().st_size
    for attempt in range(5):
        try:
            init = requests.post(UPLOAD_URL, params={"uploadType": "resumable", "part": parts},
                                 headers={"Authorization": f"Bearer {_token()}",
                                          "Content-Type": "application/json; charset=UTF-8",
                                          "X-Upload-Content-Type": "video/mp4",
                                          "X-Upload-Content-Length": str(size)},
                                 data=json.dumps(meta), timeout=60)
            if init.status_code == 400 and "localizations" in meta:   # çeviri reddedilirse çevirisiz yükle
                log.warning(f"Çeviriler kabul edilmedi, çevirisiz yükleniyor: {init.text[:200]}")
                meta.pop("localizations")
                parts = "snippet,status"
                continue
            if init.status_code == 403 and "quota" in init.text.lower():
                raise SystemExit("YouTube günlük API kotası doldu. Yarın otomatik devam edecek.")
            if init.status_code != 200:
                raise RuntimeError(f"Yükleme başlatılamadı {init.status_code}: {init.text[:300]}")
            with open(video_path, "rb") as fh:
                up = requests.put(init.headers["Location"], data=fh, timeout=1800,
                                  headers={"Content-Type": "video/mp4", "Content-Length": str(size)})
            if up.status_code in (200, 201):
                vid = up.json()["id"]
                status = up.json().get("status", {}).get("privacyStatus", privacy)
                log.info(f"YouTube'a yüklendi: https://youtu.be/{vid}  (görünürlük: {status})")
                if privacy == "public" and status != "public":
                    log.warning("Video 'özel' kaldı: Google Cloud projen henüz YouTube denetiminden geçmemiş. "
                                "Rehberdeki 'Denetim başvurusu' adımına bak.")
                return vid
            raise RuntimeError(f"Yükleme hatası {up.status_code}: {up.text[:300]}")
        except (requests.RequestException, RuntimeError) as e:
            wait = 20 * (attempt + 1)
            log.warning(f"Yükleme denemesi {attempt + 1} başarısız: {e} — {wait} sn sonra tekrar")
            time.sleep(wait)
    raise RuntimeError("Video 5 denemede yüklenemedi")


def set_thumbnail(video_id, image_path):
    """Uzun videoya özel kapak resmi. Kanal telefonla doğrulanmamışsa YouTube reddeder; o zaman sessizce geçer."""
    if not video_id:
        return False
    try:
        with open(image_path, "rb") as fh:
            r = requests.post("https://www.googleapis.com/upload/youtube/v3/thumbnails/set",
                              params={"videoId": video_id, "uploadType": "media"},
                              headers={"Authorization": f"Bearer {_token()}", "Content-Type": "image/jpeg"},
                              data=fh.read(), timeout=120)
        if r.status_code == 200:
            log.info("Kapak resmi yüklendi")
            return True
        log.warning(f"Kapak resmi yüklenemedi ({r.status_code}): {r.text[:200]}")
    except Exception as e:
        log.warning(f"Kapak resmi hatası: {e}")
    return False
