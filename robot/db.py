"""Yerel kayıt: hangi haberler işlendi, hangi videolar yüklendi."""
import sqlite3
from datetime import datetime, timedelta

from . import config


def _conn():
    c = sqlite3.connect(config.DB_FILE)
    c.execute("""CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT, topic TEXT, source_url TEXT, title TEXT,
        file_path TEXT, youtube_id TEXT, status TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS seen (url TEXT PRIMARY KEY, seen_at TEXT)")
    return c


def mark_seen(urls):
    with _conn() as c:
        now = datetime.now().isoformat(timespec="seconds")
        c.executemany("INSERT OR IGNORE INTO seen VALUES (?, ?)", [(u, now) for u in urls])


def is_seen(url):
    with _conn() as c:
        return c.execute("SELECT 1 FROM seen WHERE url=?", (url,)).fetchone() is not None


def add_video(topic, source_url, title, file_path, youtube_id, status):
    with _conn() as c:
        c.execute("INSERT INTO videos (created_at, topic, source_url, title, file_path, youtube_id, status)"
                  " VALUES (?,?,?,?,?,?,?)",
                  (datetime.now().isoformat(timespec="seconds"), topic, source_url, title,
                   str(file_path), youtube_id, status))


def uploads_today():
    today = datetime.now().strftime("%Y-%m-%d")
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM videos WHERE status='yuklendi' AND topic!='haftalik' AND created_at LIKE ?",
                         (today + "%",)).fetchone()[0]


def hours_since_last_upload():
    with _conn() as c:
        row = c.execute("SELECT MAX(created_at) FROM videos WHERE status='yuklendi'").fetchone()
    if not row or not row[0]:
        return 999.0
    return (datetime.now() - datetime.fromisoformat(row[0])).total_seconds() / 3600


def recent_titles(days=7):
    since = (datetime.now() - timedelta(days=days)).isoformat()
    with _conn() as c:
        return [r[0] for r in c.execute("SELECT title FROM videos WHERE created_at>=? ORDER BY id DESC",
                                        (since,)).fetchall()]


def summary(limit=15):
    with _conn() as c:
        return c.execute("SELECT created_at, status, youtube_id, title FROM videos ORDER BY id DESC LIMIT ?",
                         (limit,)).fetchall()
