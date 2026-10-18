"""Authenticated web application for clinician and patient medication workflows.

Run with: .venv/bin/python -m webapp.app
"""

import os
import secrets
import sys
from pathlib import Path

from flask import Flask, g, redirect, render_template, url_for

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from webapp import clinical, clinical_store  # noqa: E402
from webapp.security import init_security  # noqa: E402

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("COMPREHENSIVE_SECRET_KEY") or secrets.token_hex(32),
    USAGE_INFERENCE_PROVIDER=os.environ.get("COMPREHENSIVE_USAGE_MODEL", "rules").lower(),
    DOCUMENT_SUMMARY_PROVIDER=os.environ.get("COMPREHENSIVE_DOCUMENT_SUMMARY_MODEL", "claude").lower(),
)
init_security(app)
app.register_blueprint(clinical.bp)
clinical_store.seed_demo_data()


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


if __name__ == "__main__":
    app.run(debug=False, port=5050, threaded=True)
