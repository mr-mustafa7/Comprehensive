import re
import os
from uuid import uuid4
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest

from webapp import clinical_store, store
from webapp.app import create_app


BACKENDS = ["sqlite"] + (["postgres"] if os.environ.get("COMPREHENSIVE_TEST_DATABASE_URL") else [])


@pytest.fixture(params=BACKENDS)
def app(request, tmp_path, monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    schema = None
    test_url = os.environ.get("COMPREHENSIVE_TEST_DATABASE_URL")
    if request.param == "postgres":
        import psycopg
        from psycopg import sql
        schema = "test_" + uuid4().hex
        with psycopg.connect(test_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        parts = urlsplit(test_url)
        query = dict(parse_qsl(parts.query))
        query["options"] = f"-csearch_path={schema}"
        monkeypatch.setenv("DATABASE_URL", urlunsplit(parts._replace(query=urlencode(query))))
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test-review.db")
    try:
        clinical_store.seed_demo_data()
        flask_app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "USAGE_INFERENCE_PROVIDER": "rules",
            "DOCUMENT_SUMMARY_PROVIDER": "structured",
        })
        flask_app.extensions["database_initialized"] = True
        yield flask_app
    finally:
        if schema:
            with psycopg.connect(test_url, autocommit=True) as conn:
                conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture()
def client(app):
    return app.test_client()


def csrf_from(response):
    match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
    assert match, response.data[:500]
    return match.group(1).decode()


@pytest.fixture()
def login():
    def do_login(client, email, password):
        token = csrf_from(client.get("/login"))
        return client.post(
            "/login",
            data={"csrf_token": token, "email": email, "password": password},
            follow_redirects=False,
        )
    return do_login


@pytest.fixture()
def csrf(client):
    def get_token(path="/"):
        client.get(path)
        with client.session_transaction() as session:
            return session["csrf_token"]
    return get_token
