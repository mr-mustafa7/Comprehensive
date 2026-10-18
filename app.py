"""WSGI entry point detected by Vercel.

The assignment must live in this file. Vercel only auto-detects a top-level
``app`` binding here, and a bare import is ignored.
"""

from webapp.app import create_app

app = create_app()
