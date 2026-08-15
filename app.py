import os

import dash
import dash_bootstrap_components as dbc
from dash import html, page_container

import config
from database.db import init_db
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

app.index_string = """<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5">
        <meta name="theme-color" content="#2c3e50">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
        <link rel="manifest" href="/assets/manifest.json">
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>"""

app.layout = html.Div(
    [
        make_navbar(),
        dbc.Container(page_container, fluid=True, className="pb-5"),
    ]
)

if config.USING_SQLITE_ON_SERVERLESS:
    import logging

    logging.getLogger(__name__).warning(
        "Running on a serverless host without a DATABASE_URL env var - falling "
        "back to a /tmp SQLite file. Data will NOT persist reliably between "
        "requests/deploys. Set DATABASE_URL to a Postgres connection string "
        "(e.g. Vercel Postgres / Neon) in your project's environment variables."
    )

if __name__ == "__main__":
    debug_mode = os.environ.get("DASH_DEBUG", "true").lower() == "true" and not config.IS_SERVERLESS
    app.run(debug=debug_mode, host="0.0.0.0", port=config.APP_PORT)
