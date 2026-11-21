"""Ayarlar: proje klasöründeki .env dosyasından okunur."""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "veri"
WORK = DATA / "calisma"
OUTPUT = DATA / "videolar"
LOGS = DATA / "loglar"
MUSIC = ROOT / "muzik"
for _p in (DATA, WORK, OUTPUT, LOGS, MUSIC):
    _p.mkdir(parents=True, exist_ok=True)


def _load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_env()


def _get(key, default=""):
    return os.environ.get(key, default).strip()


def _int(key, default):
    try:
        return int(_get(key, str(default)))
    except ValueError:
        return default


ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
CLAUDE_MODEL = _get("CLAUDE_MODEL", "claude-sonnet-5-5")
GEMINI_API_KEY = _get("GEMINI_API_KEY")
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-flash-lite-latest")
PEXELS_API_KEY = _get("PEXELS_API_KEY")
PIXABAY_API_KEY = _get("PIXABAY_API_KEY")

LANGUAGE = _get("LANGUAGE", "en").lower()  # en / tr
CHANNEL_NAME = _get("CHANNEL_NAME", "")
WATCH_KEYWORDS = [k.strip() for k in _get(
    "WATCH_KEYWORDS",
    "GTA 6,Minecraft,Fortnite,Roblox,Call of Duty,Pokemon,Nintendo Switch 2,PlayStation 5,Xbox,"
    "Steam new game,EA Sports FC,Elden Ring,Marvel game,anime game,esports,free game,"
    "iPhone,Samsung Galaxy,ChatGPT,AI robot,NVIDIA,Tesla,SpaceX,viral video game,game trailer",
).split(",") if k.strip()]
KEYWORDS_PER_RUN = _int("KEYWORDS_PER_RUN", 9)  # her turda havuzdan rastgele bu kadar konu taranır
USE_GOOGLE_TRENDS = _get("USE_GOOGLE_TRENDS", "1") == "1"
TRENDS_GEO = _get("TRENDS_GEO", "US")

VIDEOS_PER_DAY = max(1, min(_int("VIDEOS_PER_DAY", 3), 6))  # YouTube API kotası günde ~6 yüklemeye izin verir
ACTIVE_START_HOUR = _int("ACTIVE_START_HOUR", 10)
ACTIVE_END_HOUR = _int("ACTIVE_END_HOUR", 23)
PRIVACY = _get("PRIVACY", "public")  # public / unlisted / private
TARGET_SECONDS = _int("TARGET_SECONDS", 32)
VOICE = _get("VOICE", "")
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")   # TikTok için videoları telefona yollar (isteğe bağlı)
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID")
AMAZON_TAG = _get("AMAZON_TAG")                   # Amazon ortaklık (affiliate) kodu; boşsa link eklenmez
AI_IMAGES = _get("AI_IMAGES", "1") == "1"  # Pollinations.ai ile yapay zekâ sahne görselleri (ücretsiz)
MUSIC_VOLUME = float(_get("MUSIC_VOLUME", "0.10") or 0.10)

CLIENT_SECRET_FILE = ROOT / "client_secret.json"
TOKEN_FILE = DATA / "youtube_token.json"
DB_FILE = DATA / "robot.db"

DEFAULT_VOICES = {
    "en": ("en-US-AndrewNeural", "Samantha"),   # (edge-tts sesi, Mac 'say' yedek sesi)
    "tr": ("tr-TR-AhmetNeural", "Yelda"),
}


def voices():
    edge, mac = DEFAULT_VOICES.get(LANGUAGE, DEFAULT_VOICES["en"])
    return (VOICE or edge), mac


def check(for_upload=True):
    """Eksik ayarları Türkçe olarak listeler."""
    problems = []
    if not (GEMINI_API_KEY or ANTHROPIC_API_KEY):
        problems.append("Yapay zekâ anahtarı yok: .env dosyasına GEMINI_API_KEY (ücretsiz) yaz")
    if not (PEXELS_API_KEY or PIXABAY_API_KEY):
        problems.append("Stok video anahtarı yok (PIXABAY_API_KEY) — videolar renkli arka planla üretilecek (zorunlu değil ama önerilir)")
    if for_upload and not CLIENT_SECRET_FILE.exists():
        problems.append("client_secret.json bulunamadı (Google Cloud'dan indirip proje klasörüne koy)")
    return problems


def ffmpeg_bin():
    """Önce sistemdeki ffmpeg, yoksa Python paketiyle gelen (imageio-ffmpeg)."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
