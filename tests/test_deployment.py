"""Deployment configuration and cross-instance persistence regressions."""

from pathlib import Path

import pytest

from scripts.build_vercel import build
from webapp import clinical_store, store
from webapp.app import create_app


@pytest.fixture()
def clean_env(monkeypatch):
    for name in (
        "VERCEL", "DATABASE_URL", "COMPREHENSIVE_SECRET_KEY", "COMPREHENSIVE_SEED_DEMO",
        "COMPREHENSIVE_USAGE_MODEL", "COMPREHENSIVE_DOCUMENT_SUMMARY_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_vercel_requires_persistent_secret_and_database(clean_env, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(RuntimeError, match="COMPREHENSIVE_SECRET_KEY"):
        create_app()
    monkeypatch.setenv("COMPREHENSIVE_SECRET_KEY", "test-value-" * 4)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp/demo.db")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        create_app()


def test_hosted_defaults_and_no_database_access_on_import(clean_env, monkeypatch):
    def unexpected_connection():
        raise AssertionError("Creating the Flask app must not open the database")

    monkeypatch.setattr(store, "_connect", unexpected_connection)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/demo")
    monkeypatch.setenv("COMPREHENSIVE_SECRET_KEY", "test-value-" * 4)
    hosted = create_app()
    assert hosted.config["SESSION_COOKIE_SECURE"] is True
    assert hosted.config["SESSION_COOKIE_HTTPONLY"] is True
    assert hosted.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert hosted.permanent_session_lifetime.total_seconds() == 8 * 3600
    assert hosted.config["SEED_DEMO"] is False
    assert hosted.config["USAGE_INFERENCE_PROVIDER"] == "rules"
    assert hosted.config["DOCUMENT_SUMMARY_PROVIDER"] == "structured"


@pytest.mark.parametrize("variable", ["COMPREHENSIVE_USAGE_MODEL", "COMPREHENSIVE_DOCUMENT_SUMMARY_MODEL"])
def test_hosted_app_rejects_local_claude_transport(clean_env, monkeypatch, variable):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/demo")
    monkeypatch.setenv("COMPREHENSIVE_SECRET_KEY", "test-value-" * 4)
    monkeypatch.setenv(variable, "claude")
    with pytest.raises(RuntimeError, match="Claude CLI"):
        create_app()


def test_schema_initializes_once_without_seed_when_disabled(clean_env, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "empty.db")
    monkeypatch.setenv("COMPREHENSIVE_SEED_DEMO", "0")
    calls = []
    original = clinical_store.init_db

    def initialize():
        calls.append(True)
        original()

    monkeypatch.setattr(clinical_store, "init_db", initialize)
    empty = create_app({"TESTING": True})
    assert not store.DB_PATH.exists()
    client = empty.test_client()
    assert client.get("/static/style.css").status_code == 200
    assert not store.DB_PATH.exists()
    assert client.get("/").status_code == 200
    assert client.get("/login").status_code == 200
    assert len(calls) == 1
    assert clinical_store.get_user_by_email("clinician@demo.test") is None


def test_database_initialization_retries_after_failure(clean_env, monkeypatch):
    monkeypatch.setenv("COMPREHENSIVE_SEED_DEMO", "0")
    attempts = []

    def initialize():
        attempts.append(True)
        if len(attempts) == 1:
            raise ConnectionError("temporary database outage")

    monkeypatch.setattr(clinical_store, "init_db", initialize)
    retry = create_app({"TESTING": True})
    client = retry.test_client()
    with pytest.raises(ConnectionError):
        client.get("/")
    assert not retry.extensions["database_initialized"]
    assert client.get("/").status_code == 200
    assert retry.extensions["database_initialized"]
    assert len(attempts) == 2


def test_vercel_entrypoint_is_the_root_flask_app():
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text()
    entry = (root / "app.py").read_text()
    assert "[project]" in pyproject
    assert "flask>=" in pyproject
    assert 'entrypoint = "app:app"' in pyproject
    assert "package = false" in pyproject
    assert "app = create_app()" in entry


def test_build_preserves_static_urls_without_database(tmp_path, clean_env):
    source = tmp_path / "webapp" / "static"
    source.mkdir(parents=True)
    (source / "style.css").write_text("body { color: black; }")
    build(tmp_path)
    assert (tmp_path / "public" / "static" / "style.css").read_text() == (source / "style.css").read_text()


def test_session_and_new_records_survive_another_app_instance(app, client, login):
    login(client, "clinician@demo.test", "DemoClinician!2026")
    clinician = clinical_store.get_user_by_email("clinician@demo.test")
    document_id, _ = clinical_store.create_document(
        clinician["id"], "Persistence check", "Synthetic", "Synthetic", "Once daily."
    )
    restarted = create_app(dict(app.config))
    restarted_client = restarted.test_client()
    cookie = client.get_cookie(app.config["SESSION_COOKIE_NAME"])
    restarted_client.set_cookie(app.config["SESSION_COOKIE_NAME"], cookie.value)
    response = restarted_client.get(f"/clinician/documents/{document_id}")
    assert response.status_code == 200
    assert b"Persistence check" in response.data
