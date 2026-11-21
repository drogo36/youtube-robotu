"""Her bitmiş videoyu sahibinin Telegram'ına yollar (TikTok/Instagram'a telefondan tek dokunuşla paylaşmak için)."""
import requests

from . import config
from .log import log


def send_video(path, caption):
    token, chat = config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID
    if not (token and chat):
        return False
    try:
        with open(path, "rb") as fh:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendVideo", timeout=180,
                              data={"chat_id": chat, "caption": caption[:1000], "supports_streaming": "true"},
                              files={"video": (path.name, fh, "video/mp4")})
        if r.status_code != 200:
            log.warning(f"Telegram'a gönderilemedi: HTTP {r.status_code} {r.text[:200]}")
            return False
        log.info("Video Telegram'a gönderildi (TikTok için hazır)")
        return True
    except Exception as e:
        log.warning(f"Telegram hatası: {e}")
        return False
