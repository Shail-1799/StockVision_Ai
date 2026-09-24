import dash
import dash_bootstrap_components as dbc
from dash import html, callback, Output, Input, State
from flask import session, request

from services.browser_detect import detect_in_app_browser

BASE_NAV_LINKS = [
    ("Dashboard", "/"),
    ("Upload", "/upload"),
    ("Orders", "/orders"),
    ("Missing Products", "/missing-products"),
    ("All Records", "/data"),
    ("Review Queue", "/review"),
    ("Reports", "/reports"),
    ("Settings", "/settings"),
]
ADMIN_NAV_LINK = ("Insights", "/insights")


def make_navbar():
    return html.Div(
        [
            # Filled in by render_navbar() below whenever the request looks
            # like it's coming from an in-app browser (WhatsApp/Telegram/
            # etc link preview) - empty otherwise. Sits above the navbar so
            # it's the first thing visible on every page, not just Upload,
            # since someone might land on Dashboard first and only hit the
            # broken-upload problem later.
            html.Div(id="in-app-browser-banner"),
            dbc.Navbar(
                dbc.Container(
                    [
                        dbc.NavbarBrand(
                            [html.Span("📦 ", className="me-1"), "StockVision AI"],
                            href="/",
                            className="fw-bold fs-4",
                        ),
                        dbc.NavbarToggler(id="navbar-toggler", n_clicks=0),
                        dbc.Collapse(
                            dbc.Nav(id="navbar-links", navbar=True, className="ms-auto flex-wrap"),
                            id="navbar-collapse",
                            navbar=True,
                            is_open=False,
                        ),
                        html.Div(id="navbar-user-badge", className="ms-3 text-white small"),
                    ],
                    fluid=True,
                ),
                color="dark",
                dark=True,
                className="mb-4 shadow-sm",
            ),
        ]
    )


@callback(
    Output("navbar-collapse", "is_open"),
    Input("navbar-toggler", "n_clicks"),
    State("navbar-collapse", "is_open"),
    prevent_initial_call=True,
)
def toggle_navbar(n_clicks, is_open):
    return not is_open


# Identity now comes from the authenticated Flask session (server-side,
# tamper-proof) instead of a client-editable localStorage picker - every
# Dash callback runs inside a real Flask request, so session data is just
# read directly wherever it's needed (see pages/upload.py, pages/insights.py).
@callback(
    Output("navbar-links", "children"),
    Output("navbar-user-badge", "children"),
    Output("in-app-browser-banner", "children"),
    Input("navbar-toggler", "id"),  # fires once per page load, cheap trigger
)
def render_navbar(_):
    username = session.get("username", "")
    is_admin = bool(session.get("is_admin"))

    links = list(BASE_NAV_LINKS)
    if is_admin:
        links.append(ADMIN_NAV_LINK)
    nav = [dbc.NavLink(label, href=href, active="exact") for label, href in links]

    badge = html.Div(
        [
            html.Span(f"👤 {username}" + (" (admin)" if is_admin else ""), className="me-3"),
            html.A("Logout", href="/logout", className="text-white-50"),
        ]
    )

    banner = ""
    app_name = detect_in_app_browser(request.headers.get("User-Agent", ""))
    if app_name:
        banner = dbc.Alert(
            [
                html.Strong("⚠️ Photo uploads won't work here. "),
                f"You're viewing this inside {app_name}'s built-in browser, which has a known bug "
                "that blocks photo uploads after taking/selecting a picture. Tap the ⋮ or share icon "
                "above and choose \"Open in Chrome\" / \"Open in Safari\", then continue there.",
            ],
            color="danger",
            className="mb-0 rounded-0 text-center",
        )

    return nav, badge, banner
