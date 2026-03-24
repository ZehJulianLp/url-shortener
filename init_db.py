import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "urls.db"


def main():
    connection = sqlite3.connect(DATABASE_PATH)
    try:
        columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(urls)").fetchall()
        }
        if not columns:
            connection.execute(
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
                connection.execute(
                    "ALTER TABLE urls ADD COLUMN is_temporary INTEGER NOT NULL DEFAULT 0"
                )
            if "expires_at" not in columns:
                connection.execute("ALTER TABLE urls ADD COLUMN expires_at TEXT")

            table_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'urls'"
            ).fetchone()
            table_sql = table_sql[0] if table_sql else ""
            if "original_url TEXT NOT NULL UNIQUE" in table_sql:
                connection.execute(
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
                connection.execute(
                    """
                    INSERT INTO urls_new (id, code, original_url, is_temporary, expires_at, created_at)
                    SELECT id, code, original_url, is_temporary, expires_at, created_at
                    FROM urls
                    """
                )
                connection.execute("DROP TABLE urls")
                connection.execute("ALTER TABLE urls_new RENAME TO urls")
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
