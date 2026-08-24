import os
from datetime import timedelta

import dash
import dash_bootstrap_components as dbc
from dash import html, page_container
from flask import send_from_directory, abort, request, session, redirect, jsonify, Response

import config
from database.db import init_db
from services.aggregator import verify_login
from components.navbar import make_navbar

# Create local folders + tables on first run (safe to call repeatedly - it's
# idempotent, which matters on serverless where the module can be re-imported
# per invocation).
init_db()

app = dash.Dash(
    __name__,
    use_pages=True,
    external_stylesheets=[dbc.themes.FLATLY],
    suppress_callback_exceptions=True,
    title=config.APP_TITLE,
)
server = app.server  # Flask WSGI app - this is what Vercel/gunicorn serve

server.secret_key = config.SECRET_KEY
server.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(days=config.SESSION_LIFETIME_DAYS),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=config.SESSION_COOKIE_SECURE,
)

# Paths reachable with NO login at all. Deliberately tiny: everything else -
# every page, every Dash callback endpoint, every static asset, every photo
# under /media/ - requires a valid session. This is what "even if the link
# is public, nobody unauthenticated can use it" means in practice: nothing
# renders, not even the Dash JS shell, until you've logged in.
_PUBLIC_PATHS = {"/login"}

# Very small in-memory brute-force throttle: N failed logins for a username
# within a short window adds a delay before the next attempt is accepted.
# Deliberately not a persisted/distributed rate limiter (that's overkill for
# a ~10-person internal tool) - just enough friction that a script can't
# hammer the login form at full speed. Resets on deploy/restart, which is
# fine for this threat model.
import time as _time

_failed_logins = {}  # username -> (fail_count, last_attempt_ts)
_LOGIN_LOCKOUT_AFTER = 5
_LOGIN_LOCKOUT_SECONDS = 30


def _login_page(error: str = "") -> str:
    error_html = f'<div style="color:#e74c3c;margin-bottom:12px;">{error}</div>' if error else ""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{config.APP_TITLE} - Sign in</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
    </head>
    <body style="background:#f5f6f8;">
        <div style="max-width:380px;margin:80px auto;padding:32px;background:white;
                    border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
            <h3 style="margin-bottom:4px;">📦 {config.APP_TITLE}</h3>
            <p style="color:#888;margin-bottom:20px;">Sign in to continue</p>
            {error_html}
            <form method="POST" action="/login">
                <div class="mb-3">
                    <label class="form-label">Username</label>
                    <input type="text" name="username" class="form-control" required autofocus>
                </div>
                <div class="mb-3">
                    <label class="form-label">Password</label>
                    <input type="password" name="password" class="form-control" required>
                </div>
                <button type="submit" class="btn btn-dark w-100">Sign in</button>
            </form>
        </div>
    </body>
    </html>
    """


@server.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("username"):
            return redirect("/")
        return Response(_login_page(), mimetype="text/html")

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    fail_count, last_ts = _failed_logins.get(username, (0, 0))
    if fail_count >= _LOGIN_LOCKOUT_AFTER and (_time.time() - last_ts) < _LOGIN_LOCKOUT_SECONDS:
        wait = int(_LOGIN_LOCKOUT_SECONDS - (_time.time() - last_ts))
        return Response(_login_page(f"Too many attempts - try again in {wait}s."), mimetype="text/html")

    user = verify_login(username, password)
    if not user:
        _failed_logins[username] = (fail_count + 1, _time.time())
        return Response(_login_page("Incorrect username or password."), mimetype="text/html")

    _failed_logins.pop(username, None)
    session.permanent = True
    session["username"] = user["name"]
    session["is_admin"] = user["is_admin"]
    return redirect("/")


@server.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@server.before_request
def require_login():
    if request.path in _PUBLIC_PATHS:
        return None
    if session.get("username"):
        return None
    # Dash's own JS makes fetch() calls to these paths expecting JSON back -
    # an HTML redirect there just shows as a confusing console error, so
    # answer with a plain 401 instead; anywhere else (real navigation,
    # /media/ photos, everything) gets redirected to the login page.
    if request.path.startswith("/_dash-update-component") or request.path.startswith("/_dash-"):
        return jsonify({"error": "Not authenticated"}), 401
    return redirect("/login")


@server.route("/media/<path:filename>")
def serve_media(filename):
    """Serves uploaded/processed images for the side-by-side verify views
    (Orders detail, All Records selection). Only ever serves a bare filename
    (no path traversal) from the two known local directories. Reached only
    by an authenticated session - require_login() above gates this route
    like every other one."""
    filename = os.path.basename(filename)
    for base_dir in (config.PROCESSED_DIR, config.UPLOADS_DIR):
        candidate = base_dir / filename
        if candidate.exists():
            return send_from_directory(base_dir, filename)
    abort(404)


app.layout = html.Div([make_navbar(), page_container])

if __name__ == "__main__":
    app.run_server(debug=False, port=8050)