import os
import secrets
import sqlite3
import ipaddress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from flask import Flask, abort, g, redirect, render_template, request, url_for


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "urls.db"))
SHORT_CODE_LENGTH = 6
MAX_URL_LENGTH = 10_000
TEMPORARY_DURATION_OPTIONS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
TRACKING_QUERY_PREFIXES = (
    "utm_",
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_",
    "mkt_",
    "igshid",
    "vero_",
)
TRACKING_QUERY_KEYS = {
    "ref",
    "ref_src",
    "ref_url",
    "source",
    "si",
    "_hsenc",
    "_hsmi",
}

app = Flask(__name__)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE_PATH)
    try:
        columns = {
            row[1]: row for row in db.execute("PRAGMA table_info(urls)").fetchall()
        }
        if not columns:
            db.execute(
                """
                CREATE TABLE urls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    original_url TEXT NOT NULL,
                    is_temporary INTEGER NOT NULL DEFAULT 0,
                    expires_at TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        else:
            if "is_temporary" not in columns:
                db.execute(
                    "ALTER TABLE urls ADD COLUMN is_temporary INTEGER NOT NULL DEFAULT 0"
                )
            if "expires_at" not in columns:
                db.execute("ALTER TABLE urls ADD COLUMN expires_at TEXT")

            table_sql = db.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'urls'"
            ).fetchone()
            table_sql = table_sql[0] if table_sql else ""
            if "original_url TEXT NOT NULL UNIQUE" in table_sql:
                db.execute(
                    """
                    CREATE TABLE urls_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        code TEXT NOT NULL UNIQUE,
                        original_url TEXT NOT NULL,
                        is_temporary INTEGER NOT NULL DEFAULT 0,
                        expires_at TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                db.execute(
                    """
                    INSERT INTO urls_new (id, code, original_url, is_temporary, expires_at, created_at)
                    SELECT id, code, original_url, is_temporary, expires_at, created_at
                    FROM urls
                    """
                )
                db.execute("DROP TABLE urls")
                db.execute("ALTER TABLE urls_new RENAME TO urls")
        db.commit()
    finally:
        db.close()


def is_valid_url(value):
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def has_embedded_credentials(parsed):
    return parsed.username is not None or parsed.password is not None


def clean_query_string(query):
    cleaned_items = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in TRACKING_QUERY_KEYS:
            continue
        if any(lowered == prefix or lowered.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        cleaned_items.append((key, value))
    return urlencode(cleaned_items, doseq=True)


def is_public_hostname(hostname):
    if not hostname:
        return False

    lowered = hostname.lower()
    blocked_hostnames = {"localhost"}
    blocked_suffixes = {".localhost", ".local", ".internal", ".home", ".lan"}
    if lowered in blocked_hostnames or any(lowered.endswith(suffix) for suffix in blocked_suffixes):
        return False

    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return True

    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def normalize_url(value):
    parsed = urlparse(value.strip())
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()

    port = parsed.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None

    netloc = hostname
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth = f"{auth}:{parsed.password}"
        netloc = f"{auth}@{netloc}"
    if port is not None:
        netloc = f"{netloc}:{port}"

    path = parsed.path or "/"
    cleaned_query = clean_query_string(parsed.query)
    return urlunparse((scheme, netloc, path, parsed.params, cleaned_query, ""))


def generate_code(length=SHORT_CODE_LENGTH):
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def parse_expiry(value):
    if value not in TEMPORARY_DURATION_OPTIONS:
        return None
    expires_at = datetime.now(timezone.utc) + TEMPORARY_DURATION_OPTIONS[value]
    return expires_at.replace(microsecond=0).isoformat()


def is_expired(expires_at):
    if not expires_at:
        return False
    return datetime.now(timezone.utc) >= datetime.fromisoformat(expires_at)


def create_short_code(original_url, expires_at=None):
    db = get_db()
    is_temporary = int(expires_at is not None)
    while True:
        code = generate_code()
        try:
            db.execute(
                """
                INSERT INTO urls (code, original_url, is_temporary, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (code, original_url, is_temporary, expires_at),
            )
            db.commit()
            return code
        except sqlite3.IntegrityError:
            continue


def find_or_create_short_code(original_url):
    db = get_db()
    existing = db.execute(
        """
        SELECT code
        FROM urls
        WHERE original_url = ?
          AND is_temporary = 0
        """,
        (original_url,),
    ).fetchone()
    if existing is not None:
        return existing["code"]

    return create_short_code(original_url)


@app.get("/")
def index():
    return render_template("index.html", duration_options=TEMPORARY_DURATION_OPTIONS.keys())


@app.get("/privacy")
def privacy():
    return render_template("privacy.html")


@app.post("/shorten")
def shorten():
    target_url = request.form.get("url", "").strip()
    temporary_requested = request.form.get("temporary") == "on"
    duration = request.form.get("duration", "")
    if not target_url:
        return render_template(
            "index.html",
            error_message="Please enter a URL.",
            duration_options=TEMPORARY_DURATION_OPTIONS.keys(),
        )

    if len(target_url) > MAX_URL_LENGTH:
        return render_template(
            "index.html",
            error_message=f"URLs may be at most {MAX_URL_LENGTH} characters long.",
            duration_options=TEMPORARY_DURATION_OPTIONS.keys(),
            temporary_requested=temporary_requested,
            selected_duration=duration,
        )

    if not is_valid_url(target_url):
        return render_template(
            "index.html",
            error_message="Please enter a valid URL starting with http:// or https://.",
            duration_options=TEMPORARY_DURATION_OPTIONS.keys(),
            temporary_requested=temporary_requested,
            selected_duration=duration,
            submitted_url=target_url,
        )

    parsed = urlparse(target_url)
    if has_embedded_credentials(parsed):
        return render_template(
            "index.html",
            error_message="URLs with embedded credentials are not allowed.",
            duration_options=TEMPORARY_DURATION_OPTIONS.keys(),
            temporary_requested=temporary_requested,
            selected_duration=duration,
            submitted_url=target_url,
        )

    if not is_public_hostname(parsed.hostname):
        return render_template(
            "index.html",
            error_message="Private, local, and internal hosts are not allowed.",
            duration_options=TEMPORARY_DURATION_OPTIONS.keys(),
            temporary_requested=temporary_requested,
            selected_duration=duration,
            submitted_url=target_url,
        )

    normalized_url = normalize_url(target_url)
    expires_at = None
    if temporary_requested:
        expires_at = parse_expiry(duration)
        if expires_at is None:
            return render_template(
                "index.html",
                error_message="Please choose a valid expiration time for the temporary link.",
                duration_options=TEMPORARY_DURATION_OPTIONS.keys(),
                temporary_requested=temporary_requested,
                submitted_url=normalized_url,
            )
        code = create_short_code(normalized_url, expires_at=expires_at)
    else:
        code = find_or_create_short_code(normalized_url)
    short_url = request.host_url.rstrip("/") + url_for("follow_short_link", code=code)
    return render_template(
        "index.html",
        duration_options=TEMPORARY_DURATION_OPTIONS.keys(),
        temporary_requested=temporary_requested,
        selected_duration=duration,
        submitted_url=normalized_url,
        short_url=short_url,
        expires_at=expires_at,
    )


@app.get("/<code>")
def follow_short_link(code):
    record = get_db().execute(
        "SELECT id, original_url, expires_at FROM urls WHERE code = ?",
        (code,),
    ).fetchone()
    if record is None:
        abort(404)

    if is_expired(record["expires_at"]):
        db = get_db()
        db.execute("DELETE FROM urls WHERE id = ?", (record["id"],))
        db.commit()
        abort(404)

    return redirect(record["original_url"], code=302)


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


init_db()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("FLASK_RUN_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "").lower() == "true",
    )
