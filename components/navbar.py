import dash_bootstrap_components as dbc
from dash import html, dcc, callback, Output, Input, State, no_update

from services.aggregator import get_users, is_admin_user

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
            # Persists in this browser (localStorage) - no login, just "who
            # are you" so uploads/edits can be attributed. See AppUser.
            dcc.Store(id="current-user-store", storage_type="local"),
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
                        html.Div(
                            dbc.Select(
                                id="current-user-select",
                                placeholder="Who are you?",
                                size="sm",
                                style={"minWidth": "160px"},
                            ),
                            className="ms-3",
                        ),
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


@callback(
    Output("current-user-select", "options"),
    Output("current-user-select", "value"),
    Input("current-user-select", "id"),  # fires once on page load
    State("current-user-store", "data"),
)
def load_users(_, stored_user):
    users = get_users()
    options = [{"label": u["name"] + (" (admin)" if u["is_admin"] else ""), "value": u["name"]} for u in users]
    names = {u["name"] for u in users}
    value = stored_user if stored_user in names else (users[0]["name"] if users else None)
    return options, value


@callback(
    Output("current-user-store", "data"),
    Input("current-user-select", "value"),
    prevent_initial_call=True,
)
def save_current_user(value):
    return value


@callback(
    Output("navbar-links", "children"),
    Input("current-user-store", "data"),
)
def render_nav_links(current_user):
    links = list(BASE_NAV_LINKS)
    if is_admin_user(current_user):
        links.append(ADMIN_NAV_LINK)
    return [dbc.NavLink(label, href=href, active="exact") for label, href in links]
