import re

import pytest

from webapp import clinical_store, store
from webapp.app import app as flask_app


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test-review.db")
    clinical_store.seed_demo_data()
    flask_app.config.update(
        TESTING=True,
        SECRET_KEY="test-only-secret",
        USAGE_INFERENCE_PROVIDER="rules",
        DOCUMENT_SUMMARY_PROVIDER="rules",
    )
    yield flask_app


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
