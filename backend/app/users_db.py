"""
users.db — everything about *people*, in a separate SQLite file from the
catalog (zolpo.db). The split mirrors the products/product_meta philosophy:
the catalog is rebuildable from the gov feeds and cheap to reset; user data
is irreplaceable, needs its own backups, and must never be touched by a
reset ingest. The two databases are linked only by value (item_code,
universal store key "chain:store") in application code — no cross-file SQL.

Tables:
  users              – accounts. Passwordless: magic-link by email (password_hash
                       is reserved for a future opt-in password flow).
  consents           – append-only consent ledger (kind, granted, ts). The latest
                       row per kind is the current state; the history is what we
                       show a regulator / app-store review.
  sessions           – long-lived login sessions. Only a SHA-256 of the token is
                       stored — a leaked users.db does not leak valid cookies.
  magic_links        – one-time sign-in tokens (hashed), 15-minute expiry.
  subscriptions      – plan/status per user; billing itself lives at the provider
                       (Apple/Google/Stripe), we keep only their reference id.
  user_stores        – the user's selected stores (server-side sync of what the
                       frontend keeps in localStorage).
  lists / list_items – shopping lists (item_code = barcode, the catalog key).
  price_alerts       – "tell me when X drops" — evaluated against price_history.
  push_subscriptions – Web Push / APNs / FCM endpoints per user.
  events             – append-only behavioural log (search / view / compare …),
                       keyed by an anonymous device id so it accumulates *before*
                       signup and gets linked to the user at signup. This is the
                       raw material for aggregated demand analytics; user_id and
                       anon_id are deliberately droppable columns so aggregates
                       can be produced with no personal data in them.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager

from .config import USERS_DB_PATH

MAGIC_LINK_TTL_MIN = 15          # sign-in link lifetime
MAGIC_LINK_COOLDOWN_S = 60       # min seconds between links for one email
SESSION_TTL_DAYS = 90

# Behavioural event allowlist — anything else is dropped server-side so a
# misbehaving client can't turn the log into a junk drawer.
EVENT_TYPES = {
    "search", "view_product", "compare", "category_open", "promo_open",
    "promo_click", "map_store_open", "add_to_cart", "alert_set", "list_add",
}
EVENTS_MAX_BATCH = 25
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RE_STORE_KEY = re.compile(r"^\d{1,4}:[\w.-]{1,12}$")   # universal "chain:store"


class RateLimited(Exception):
    """A magic link for this email was issued less than the cooldown ago."""


@contextmanager
def get_users_db():
    """Yield a users.db connection (WAL: events land while the app reads)."""
    conn = sqlite3.connect(USERS_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_users_db() -> None:
    with get_users_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id        TEXT PRIMARY KEY,      -- uuid4
                email          TEXT UNIQUE NOT NULL,  -- normalized lower-case
                email_verified INTEGER DEFAULT 0,
                password_hash  TEXT,                  -- reserved; magic-link only for now
                display_name   TEXT,
                locale         TEXT DEFAULT 'he',
                created_at     TEXT NOT NULL,
                last_seen_at   TEXT
            );

            CREATE TABLE IF NOT EXISTS consents (
                user_id TEXT NOT NULL,
                kind    TEXT NOT NULL,     -- 'analytics' / 'marketing' / 'data_insights'
                granted INTEGER NOT NULL,
                ts      TEXT NOT NULL,
                PRIMARY KEY (user_id, kind, ts)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,   -- sha256(session token)
                user_id    TEXT NOT NULL,
                device     TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS magic_links (
                token_hash TEXT PRIMARY KEY,   -- sha256(one-time token)
                email      TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used       INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                sub_id       TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                plan         TEXT NOT NULL,      -- 'free' / 'plus'
                status       TEXT NOT NULL,      -- trial / active / canceled / expired
                provider     TEXT,               -- 'apple' / 'google' / 'stripe'
                provider_ref TEXT,               -- the provider's subscription id
                started_at   TEXT,
                renews_at    TEXT,
                canceled_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS user_stores (
                user_id   TEXT NOT NULL,
                store_key TEXT NOT NULL,          -- universal "chain:store"
                rank      INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, store_key)
            );

            CREATE TABLE IF NOT EXISTS lists (
                list_id    TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL,
                name       TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS list_items (
                list_id   TEXT NOT NULL,
                item_code TEXT NOT NULL,          -- barcode (catalog key)
                qty       REAL DEFAULT 1,
                added_at  TEXT NOT NULL,
                PRIMARY KEY (list_id, item_code)
            );

            CREATE TABLE IF NOT EXISTS price_alerts (
                alert_id      TEXT PRIMARY KEY,
                user_id       TEXT NOT NULL,
                item_code     TEXT NOT NULL,
                store_key     TEXT,               -- NULL = any of the user's stores
                target_price  REAL,               -- NULL = any drop
                active        INTEGER DEFAULT 1,
                created_at    TEXT NOT NULL,
                last_fired_at TEXT
            );

            CREATE TABLE IF NOT EXISTS push_subscriptions (
                user_id    TEXT NOT NULL,
                endpoint   TEXT NOT NULL,
                keys_json  TEXT,                  -- p256dh/auth for Web Push
                platform   TEXT,                  -- 'web' / 'ios' / 'android'
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, endpoint)
            );

            CREATE TABLE IF NOT EXISTS events (
                ts        TEXT NOT NULL,
                anon_id   TEXT NOT NULL,          -- device id, exists before signup
                user_id   TEXT,                   -- linked at signup (link_anon)
                type      TEXT NOT NULL,          -- one of EVENT_TYPES
                item_code TEXT,
                store_key TEXT,
                query     TEXT,                   -- search demand, verbatim
                props     TEXT                    -- small JSON blob (result count …)
            );
            CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(ts);
            CREATE INDEX IF NOT EXISTS idx_events_item ON events(item_code, ts);
            CREATE INDEX IF NOT EXISTS idx_events_anon ON events(anon_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            """
        )


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC).replace(tzinfo=None)


def _iso(dt: _dt.datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Auth: magic links + sessions
# --------------------------------------------------------------------------- #

def request_magic_link(email: str) -> dict:
    """
    Issue a one-time sign-in token for `email`. Returns {'email', 'token'} —
    the *caller* turns the token into a URL and mails it; only the SHA-256
    lands in the DB. Raises ValueError on a bad address, RateLimited when the
    previous link is younger than the cooldown.
    """
    email = (email or "").strip().lower()
    if len(email) > 254 or not _RE_EMAIL.match(email):
        raise ValueError("invalid email")
    now = _now()
    with get_users_db() as conn:
        recent = conn.execute(
            "SELECT MAX(created_at) AS ts FROM magic_links WHERE email = ?", (email,)
        ).fetchone()["ts"]
        if recent and _iso(now - _dt.timedelta(seconds=MAGIC_LINK_COOLDOWN_S)) < recent:
            raise RateLimited(email)
        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO magic_links (token_hash, email, created_at, expires_at) VALUES (?,?,?,?)",
            (_hash(token), email, _iso(now),
             _iso(now + _dt.timedelta(minutes=MAGIC_LINK_TTL_MIN))),
        )
        # Housekeeping: expired links are dead weight, drop them as we go.
        conn.execute("DELETE FROM magic_links WHERE expires_at < ?", (_iso(now),))
    return {"email": email, "token": token}


def redeem_magic_link(token: str, device: str = "web") -> dict | None:
    """
    One-time exchange: token → session. Creates the user on first sign-in.
    Returns {'user_id','email','session_token','new_user'} or None when the
    token is unknown, already used, or expired.
    """
    now = _now()
    with get_users_db() as conn:
        row = conn.execute(
            "SELECT email FROM magic_links WHERE token_hash = ? AND used = 0 AND expires_at >= ?",
            (_hash(token), _iso(now)),
        ).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE magic_links SET used = 1 WHERE token_hash = ?", (_hash(token),))

        user = conn.execute("SELECT user_id FROM users WHERE email = ?", (row["email"],)).fetchone()
        new_user = user is None
        if new_user:
            user_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO users (user_id, email, email_verified, created_at, last_seen_at) "
                "VALUES (?,?,1,?,?)",
                (user_id, row["email"], _iso(now), _iso(now)),
            )
        else:
            user_id = user["user_id"]
            conn.execute(
                "UPDATE users SET email_verified = 1, last_seen_at = ? WHERE user_id = ?",
                (_iso(now), user_id),
            )

        session_token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, device, created_at, expires_at) "
            "VALUES (?,?,?,?,?)",
            (_hash(session_token), user_id, device, _iso(now),
             _iso(now + _dt.timedelta(days=SESSION_TTL_DAYS))),
        )
    return {"user_id": user_id, "email": row["email"],
            "session_token": session_token, "new_user": new_user}


def session_user(session_token: str) -> dict | None:
    """The user behind a session cookie, or None. Touches last_seen_at."""
    if not session_token:
        return None
    now = _now()
    with get_users_db() as conn:
        row = conn.execute(
            """
            SELECT u.user_id, u.email, u.display_name, u.locale, u.created_at
            FROM sessions s JOIN users u ON u.user_id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at >= ?
            """,
            (_hash(session_token), _iso(now)),
        ).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE users SET last_seen_at = ? WHERE user_id = ?",
                     (_iso(now), row["user_id"]))
        return dict(row)


def delete_session(session_token: str) -> None:
    with get_users_db() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(session_token or ""),))


# --------------------------------------------------------------------------- #
# Consents / stores / events
# --------------------------------------------------------------------------- #

def record_consent(user_id: str, kind: str, granted: bool) -> None:
    with get_users_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO consents (user_id, kind, granted, ts) VALUES (?,?,?,?)",
            (user_id, kind, 1 if granted else 0, _iso(_now())),
        )


def get_consents(user_id: str) -> dict:
    """Current state: the newest row per kind."""
    with get_users_db() as conn:
        rows = conn.execute(
            """
            SELECT c.kind, c.granted FROM consents c
            JOIN (SELECT kind, MAX(ts) AS ts FROM consents WHERE user_id = ? GROUP BY kind) m
              ON m.kind = c.kind AND m.ts = c.ts
            WHERE c.user_id = ?
            """,
            (user_id, user_id),
        ).fetchall()
    return {r["kind"]: bool(r["granted"]) for r in rows}


def set_user_stores(user_id: str, store_keys: list[str]) -> list[str]:
    """Replace the user's store selection; malformed keys are dropped."""
    keys = [k for k in (store_keys or []) if isinstance(k, str) and _RE_STORE_KEY.match(k)][:24]
    with get_users_db() as conn:
        conn.execute("DELETE FROM user_stores WHERE user_id = ?", (user_id,))
        conn.executemany(
            "INSERT OR IGNORE INTO user_stores (user_id, store_key, rank) VALUES (?,?,?)",
            [(user_id, k, i) for i, k in enumerate(keys)],
        )
    return keys


def get_user_stores(user_id: str) -> list[str]:
    with get_users_db() as conn:
        rows = conn.execute(
            "SELECT store_key FROM user_stores WHERE user_id = ? ORDER BY rank", (user_id,)
        ).fetchall()
    return [r["store_key"] for r in rows]


def record_events(anon_id: str, user_id: str | None, events: list[dict]) -> int:
    """
    Append a batch of behavioural events. Server-side hygiene: allowlisted
    types only, hard field caps, server timestamps (client clocks lie), at
    most EVENTS_MAX_BATCH rows per call. Returns rows written.
    """
    anon_id = (anon_id or "").strip()[:64]
    if not anon_id or not isinstance(events, list):
        return 0
    ts = _iso(_now())
    rows = []
    for ev in events[:EVENTS_MAX_BATCH]:
        if not isinstance(ev, dict) or ev.get("type") not in EVENT_TYPES:
            continue
        props = ev.get("props")
        if isinstance(props, dict):
            props = json.dumps(props, ensure_ascii=False)[:500]
        else:
            props = None
        rows.append((ts, anon_id, user_id, ev["type"],
                     (str(ev["item_code"])[:20] if ev.get("item_code") else None),
                     (str(ev["store_key"])[:20] if ev.get("store_key") else None),
                     (str(ev["query"])[:200] if ev.get("query") else None),
                     props))
    if rows:
        with get_users_db() as conn:
            conn.executemany(
                "INSERT INTO events (ts, anon_id, user_id, type, item_code, store_key, query, props) "
                "VALUES (?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def link_anon(user_id: str, anon_id: str) -> int:
    """
    Attach a device's pre-signup events to the user who just signed in on it.
    Only unclaimed rows are touched, so one shared device can't steal another
    account's history. Returns rows linked.
    """
    anon_id = (anon_id or "").strip()[:64]
    if not anon_id:
        return 0
    with get_users_db() as conn:
        cur = conn.execute(
            "UPDATE events SET user_id = ? WHERE anon_id = ? AND user_id IS NULL",
            (user_id, anon_id),
        )
        return cur.rowcount
