"""Ayarlar: proje klasöründeki .env dosyasından okunur."""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Kardeş kanallar (es / pt / id ...): her kanalın hafızası ayrı klasörde tutulur
CHANNEL_KEY = os.environ.get("CHANNEL_KEY", "").strip().lower()
DATA = ROOT / "veri" / "kanallar" / CHANNEL_KEY if CHANNEL_KEY else ROOT / "veri"
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
# Kardeş kanalların yerel popüler oyunları (ör. Endonezya: Mobile Legends) havuza eklenir
WATCH_KEYWORDS += [k.strip() for k in _get("EXTRA_KEYWORDS", "").split(",") if k.strip()]
DEAL_KEYWORDS = [k.strip() for k in _get(
    "DEAL_KEYWORDS",
    "Black Friday gaming deals,PS5 deal,Nintendo Switch 2 deal,Xbox deal,video game price drop,"
    "gaming headset deal,iPhone deal,Samsung Galaxy deal,gaming monitor deal,Steam Deck deal",
).split(",") if k.strip()]
DEALS_PER_RUN = _int("DEALS_PER_RUN", 1)  # her turda bakılacak indirim araması (Amazon linki = komisyon)
KEYWORDS_PER_RUN = _int("KEYWORDS_PER_RUN", 9)  # her turda havuzdan rastgele bu kadar konu taranır
USE_GOOGLE_TRENDS = _get("USE_GOOGLE_TRENDS", "1") == "1"
TRENDS_GEO = _get("TRENDS_GEO", "US")
# YouTube'un en büyük oyun izleyici pazarları: her turda bunlardan 2'sinin yükselen aramaları da taranır
TRENDS_GEOS = [g.strip() for g in _get("TRENDS_GEOS", "US,IN,BR,ID,MX,PH,GB,DE,JP,TR").split(",") if g.strip()]
# Başlık/açıklama çevirileri: bu ülkelerdeki izleyiciler videoyu kendi dilinde başlıkla görür
LOCALIZE_LANGS = [l.strip() for l in _get("LOCALIZE_LANGS", "es,pt,hi,id,fr,de,ar,ja,ko,tr,ru,it,tl,vi,th").split(",") if l.strip()]

VIDEOS_PER_DAY = max(1, min(_int("VIDEOS_PER_DAY", 3), 6))  # YouTube API kotası günde ~6 yüklemeye izin verir
ACTIVE_START_HOUR = _int("ACTIVE_START_HOUR", 10)
ACTIVE_END_HOUR = _int("ACTIVE_END_HOUR", 23)
PRIVACY = _get("PRIVACY", "public")  # public / unlisted / private
TARGET_SECONDS = _int("TARGET_SECONDS", 25)  # kısa Shorts sonuna kadar izlenir ve döngüye girer
VOICE = _get("VOICE", "")
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")   # TikTok için videoları telefona yollar (isteğe bağlı)
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID")
AMAZON_TAG = _get("AMAZON_TAG")                   # Amazon ortaklık (affiliate) kodu; boşsa link eklenmez
# Her zaman izlenen "bilinmeyen gerçekler" videoları (Wikipedia'dan doğrulanmış): turların bu oranı
EVERGREEN_SHARE = float(_get("EVERGREEN_SHARE", "0.4") or 0.4)
EVERGREEN_GAMES = [g.strip() for g in _get("EVERGREEN_GAMES",
    "Minecraft|Grand Theft Auto V|Fortnite|Roblox|Pokémon (video game series)|The Legend of Zelda: Breath of the Wild|"
    "Elden Ring|Call of Duty|Super Mario Bros.|Red Dead Redemption 2|The Witcher 3: Wild Hunt|Among Us|Tetris|"
    "Halo (franchise)|God of War (2018 video game)|Cyberpunk 2077|The Elder Scrolls V: Skyrim|Clash of Clans|"
    "PUBG: Battlegrounds|League of Legends|Valorant|Hollow Knight|Five Nights at Freddy's|Sonic the Hedgehog|"
    "Pac-Man|The Last of Us|Resident Evil 4|Dark Souls|Free Fire (video game)|Mobile Legends: Bang Bang|"
    "Genshin Impact|Grand Theft Auto: San Andreas|Super Smash Bros. Ultimate|Animal Crossing: New Horizons|"
    "Half-Life 2|Portal 2|Doom (1993 video game)|Counter-Strike 2|Terraria|Stardew Valley|Undertale|"
    "Metal Gear Solid|Street Fighter II|Mortal Kombat|PlayStation 2|Game Boy|Nintendo Switch|Xbox 360").split("|") if g.strip()]
LONG_MINUTES = _int("LONG_MINUTES", 9)   # haftalık uzun video hedef süresi (dakika)
AI_IMAGES = _get("AI_IMAGES", "1") == "1"  # Pollinations.ai ile yapay zekâ sahne görselleri (ücretsiz)
MUSIC_VOLUME = float(_get("MUSIC_VOLUME", "0.10") or 0.10)

CLIENT_SECRET_FILE = ROOT / "client_secret.json"
TOKEN_FILE = DATA / "youtube_token.json"
DB_FILE = DATA / "robot.db"

DEFAULT_VOICES = {
    "en": ("en-US-AndrewNeural", "Samantha"),   # (edge-tts sesi, Mac 'say' yedek sesi)
    "tr": ("tr-TR-AhmetNeural", "Yelda"),
    "es": ("es-MX-JorgeNeural", "Paulina"),
    "pt": ("pt-BR-AntonioNeural", "Luciana"),
    "id": ("id-ID-ArdiNeural", "Damayanti"),
    "hi": ("hi-IN-MadhurNeural", "Lekha"),
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
