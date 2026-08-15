import dash_bootstrap_components as dbc
from dash import html, callback, Output, Input, State

NAV_LINKS = [
    ("Dashboard", "/"),
    ("Upload", "/upload"),
    ("Orders", "/orders"),
    ("Missing Products", "/missing-products"),
    ("All Records", "/data"),
    ("Review Queue", "/review"),
    ("Reports", "/reports"),
    ("Settings", "/settings"),
]


def make_navbar():
    return dbc.Navbar(
        dbc.Container(
            [
                dbc.NavbarBrand(
                    [html.Span("📦 ", className="me-1"), "StockVision AI"],
                    href="/",
                    className="fw-bold fs-4",
                ),
                dbc.NavbarToggler(id="navbar-toggler", n_clicks=0),
                dbc.Collapse(
                    dbc.Nav(
                        [dbc.NavLink(label, href=href, active="exact") for label, href in NAV_LINKS],
                        navbar=True,
                        className="ms-auto flex-wrap",
                    ),
                    id="navbar-collapse",
                    navbar=True,
                    is_open=False,
                ),
            ],
            fluid=True,
        ),
        color="dark",
        dark=True,
        className="mb-4 shadow-sm",
    )


@callback(
    Output("navbar-collapse", "is_open"),
    Input("navbar-toggler", "n_clicks"),
    State("navbar-collapse", "is_open"),
    prevent_initial_call=True,
)
def toggle_navbar(n_clicks, is_open):
    return not is_open
