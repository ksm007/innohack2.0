import sqlite3
from pathlib import Path


def get_connection(sqlite_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(sqlite_path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(sqlite_path: Path) -> None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(sqlite_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                payer TEXT NOT NULL,
                policy_name TEXT NOT NULL,
                version_label TEXT,
                document_pattern TEXT NOT NULL,
                likely_drug TEXT,
                version_group TEXT,
                last_refreshed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS extraction_runs (
                run_id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL,
                drug_name TEXT NOT NULL,
                question TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pageindex_runs (
                run_id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL,
                status TEXT NOT NULL,
                index_dir TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS extraction_cache (
                cache_key TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL,
                drug_name TEXT NOT NULL,
                question TEXT NOT NULL,
                snippet_signature TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS request_history (
                history_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                request_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(documents)")}
        if "version_group" not in columns:
            try:
                connection.execute("ALTER TABLE documents ADD COLUMN version_group TEXT")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        connection.execute(
            "CREATE INDEX IF NOT EXISTS extraction_cache_lookup_idx ON extraction_cache (doc_id, drug_name, question)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS request_history_kind_created_idx ON request_history (kind, created_at DESC)"
        )
