"""
Entrypoint for Vercel's Python runtime, which expects a WSGI-callable
named `app` in this file. Our Dash app's underlying Flask server is
exposed as `server` in app.py - we just re-export it under the name
Vercel looks for.
"""
from app import server as app  # noqa: F401
