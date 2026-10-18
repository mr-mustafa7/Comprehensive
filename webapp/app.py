"""Authenticated web application for clinician and patient medication workflows.

Run with: .venv/bin/python -m webapp.app
"""

import os
import secrets
import sys
from threading import Lock
from pathlib import Path

from flask import Flask, g, redirect, render_template, url_for

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from webapp import clinical, clinical_store  # noqa: E402
from webapp.security import init_security  # noqa: E402

def create_app(test_config: dict | None = None) -> Flask:
    """Configure without database writes so build/import is safe on Vercel."""
    hosted = os.environ.get("VERCEL") == "1"
    secret = os.environ.get("COMPREHENSIVE_SECRET_KEY", "")
    if hosted:
        if len(secret) < 32:
            raise RuntimeError("Set COMPREHENSIVE_SECRET_KEY to a random value of at least 32 characters.")
        if not os.environ.get("DATABASE_URL", "").startswith(("postgres://", "postgresql://")):
            raise RuntimeError("Set DATABASE_URL to a persistent PostgreSQL database before deploying.")

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=secret or secrets.token_hex(32),
        USAGE_INFERENCE_PROVIDER=os.environ.get("COMPREHENSIVE_USAGE_MODEL", "rules").lower(),
        DOCUMENT_SUMMARY_PROVIDER=os.environ.get("COMPREHENSIVE_DOCUMENT_SUMMARY_MODEL", "structured").lower(),
        SEED_DEMO=os.environ.get("COMPREHENSIVE_SEED_DEMO", "0" if hosted else "1") == "1",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=hosted,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
        MAX_CONTENT_LENGTH=256 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    if app.config["USAGE_INFERENCE_PROVIDER"] not in {"rules", "claude"}:
        raise RuntimeError("COMPREHENSIVE_USAGE_MODEL must be rules or claude.")
    if app.config["DOCUMENT_SUMMARY_PROVIDER"] not in {"structured", "rules", "claude"}:
        raise RuntimeError("COMPREHENSIVE_DOCUMENT_SUMMARY_MODEL must be structured, rules, or claude.")
    if hosted and "claude" in (app.config["USAGE_INFERENCE_PROVIDER"], app.config["DOCUMENT_SUMMARY_PROVIDER"]):
        raise RuntimeError("The local Claude CLI is unavailable on Vercel. Use rules and structured providers.")

    initialization_lock = Lock()
    app.extensions["database_initialized"] = False

    @app.before_request
    def ensure_database():
        # The CDN serves these in Vercel; local Flask can serve them without a DB.
        from flask import request
        if request.endpoint == "static" or app.extensions["database_initialized"]:
            return None
        with initialization_lock:
            if not app.extensions["database_initialized"]:
                if app.config["SEED_DEMO"]:
                    clinical_store.seed_demo_data()
                else:
                    clinical_store.init_db()
                app.extensions["database_initialized"] = True
        return None

    init_security(app)
    app.register_blueprint(clinical.bp)

    @app.context_processor
    def user_context():
        return {"current_user": g.get("user")}

    @app.route("/")
    def home():
        if g.user is None:
            return render_template("login.html")
        if g.user["role"] == "clinician":
            return redirect(url_for("clinical.clinician_dashboard"))
        return redirect(url_for("clinical.patient_dashboard"))

    return app


if __name__ == "__main__":
    create_app().run(debug=False, port=5050, threaded=True)
