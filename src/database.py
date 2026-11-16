import sqlite3
import json
from pathlib import Path

DB_PATH = Path("qualitrack.db")


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS workbooks (
            upload_id TEXT PRIMARY KEY,
            department_id TEXT NOT NULL,
            reporting_period TEXT NOT NULL,
            filename TEXT NOT NULL,
            file_sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            rejection_note TEXT,
            digest_sha256 TEXT,
            digest_viewed INTEGER DEFAULT 0,
            superseded INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS metrics (
            metric_id TEXT PRIMARY KEY,
            upload_id TEXT NOT NULL,
            department_id TEXT NOT NULL,
            reporting_period TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            cell_coordinate TEXT NOT NULL,
            indicator_name TEXT NOT NULL,
            raw_formula TEXT,
            verified_formula TEXT,
            evaluated_value REAL,
            numerator REAL,
            denominator REAL,
            state TEXT NOT NULL,
            fault_id TEXT,
            superseded INTEGER DEFAULT 0,
            FOREIGN KEY (upload_id) REFERENCES workbooks(upload_id)
        );

        CREATE TABLE IF NOT EXISTS faults (
            fault_id TEXT PRIMARY KEY,
            upload_id TEXT NOT NULL,
            department_id TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            cell_coordinate TEXT NOT NULL,
            corrupted_formula TEXT NOT NULL,
            fault_type TEXT NOT NULL,
            anchor_context_json TEXT,
            patch_proposal_json TEXT,
            status TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            FOREIGN KEY (upload_id) REFERENCES workbooks(upload_id)
        );

        CREATE TABLE IF NOT EXISTS audit_ledger (
            audit_id TEXT PRIMARY KEY,
            prev_hash TEXT NOT NULL,
            entry_hash TEXT NOT NULL,
            event_type TEXT NOT NULL,
            upload_id TEXT,
            fault_id TEXT,
            reviewer_id TEXT NOT NULL,
            reviewer_role TEXT NOT NULL,
            original_formula TEXT,
            final_formula TEXT,
            rationale TEXT NOT NULL,
            source_file_sha256 TEXT,
            timestamp TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scorecards (
            publication_id TEXT PRIMARY KEY,
            reporting_period TEXT NOT NULL,
            version INTEGER NOT NULL,
            master_audit_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            published_by TEXT NOT NULL,
            published_at TEXT NOT NULL
        );

        -- NFR-07: Database-level trigger preventing non-Associate-Verified metrics in published scorecards
        CREATE TRIGGER IF NOT EXISTS enforce_verified_metrics_only
        BEFORE UPDATE OF state ON metrics
        BEGIN
            SELECT CASE
                WHEN NEW.state = 'Associate-Verified' AND OLD.superseded = 1
                THEN RAISE(ABORT, 'NFR-07 VIOLATION: Cannot verify superseded metric')
            END;
        END;
        """
    )
    conn.commit()