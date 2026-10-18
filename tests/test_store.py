"""Persistence guarantees shared by the SQLite and PostgreSQL test runs."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from webapp import clinical_store, store


def test_transactions_persist_ids_and_bound_text_and_close(app):
    text = "A patient's 50% question?'; DROP TABLE users; --"
    with clinical_store._connect() as conn:
        organisation_id = conn.execute(
            "INSERT INTO organisations (name, created_at) VALUES (?, ?)",
            (text, clinical_store.now()),
        ).lastrowid
        assert isinstance(organisation_id, int)
    assert conn.closed

    with clinical_store._connect() as conn:
        row = conn.execute(
            "SELECT id, name, name AS duplicate, id AS duplicate FROM organisations WHERE id = ?",
            (organisation_id,),
        ).fetchone()
        assert row[0] == row["id"] == organisation_id
        assert row[1] == row["name"] == text
        assert row["duplicate"] == text
        assert row[3] == organisation_id
        assert dict(row)["name"] == text
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
    assert conn.closed


def test_failed_transaction_rolls_back_and_closes(app):
    with pytest.raises(RuntimeError, match="abort this write"):
        with clinical_store._connect() as conn:
            conn.execute(
                "INSERT INTO organisations (name, created_at) VALUES (?, ?)",
                ("Must roll back", clinical_store.now()),
            )
            raise RuntimeError("abort this write")
    assert conn.closed
    with clinical_store._connect() as check:
        assert check.execute(
            "SELECT COUNT(*) FROM organisations WHERE name = ?", ("Must roll back",)
        ).fetchone()[0] == 0


def test_email_uniqueness_is_case_insensitive_at_database_level(app):
    clinician = clinical_store.get_user_by_email("CLINICIAN@DEMO.TEST")
    with clinical_store._connect() as conn:
        if conn.dialect == "postgres":
            import psycopg

            integrity_error = psycopg.IntegrityError
        else:
            integrity_error = sqlite3.IntegrityError
    with pytest.raises(integrity_error):
        with clinical_store._connect() as conn:
            conn.execute(
                """INSERT INTO users
                   (email, password_hash, role, organisation_id, display_name, created_at)
                   VALUES (?, ?, 'clinician', ?, ?, ?)""",
                ("CLINICIAN@DEMO.TEST", "unused", clinician["organisation_id"], "Duplicate", clinical_store.now()),
            )
    assert conn.closed


def test_repeated_seed_preserves_existing_data_and_history(app):
    clinician = clinical_store.get_user_by_email("clinician@demo.test")
    with clinical_store._connect() as conn:
        conn.execute("UPDATE organisations SET name = ? WHERE id = ?", ("Edited by a user", clinician["organisation_id"]))
        before = {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()]
            for table in ("organisations", "users", "invitations", "document_versions", "audit_events")
        }

    assert clinical_store.seed_demo_data()["clinician_id"] == clinician["id"]
    with clinical_store._connect() as conn:
        after = {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()]
            for table in before
        }
    assert after == before


def test_sqlite_concurrent_initialization_seeds_once(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "concurrent.db")
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda _: clinical_store.seed_demo_data(), range(3)))
    assert len({result["clinician_id"] for result in results}) == 1
    with clinical_store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM organisations").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM audit_events WHERE action = 'workspace.seeded'").fetchone()[0] == 1
