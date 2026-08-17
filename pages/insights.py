import dash
from dash import html, dcc, callback, Output, Input
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import plotly.express as px
import pandas as pd

from services.aggregator import (
    get_retailer_reliability,
    get_user_activity,
    get_groq_usage_today,
    get_dashboard_stats,
    is_admin_user,
)
from components.charts import style_fig, empty_fig, COLORWAY

dash.register_page(__name__, path="/insights", name="Insights")

layout = html.Div(
    [
        dcc.Interval(id="insights-refresh", interval=10000, n_intervals=0),
        html.H3("Insights", className="mb-1"),
        html.P(
            "Deeper, team-wide analytics. This nav link is hidden for non-admins, but note this "
            "is name-based attribution with no login - it's a visibility convenience, not a real "
            "security boundary.",
            className="text-muted small",
        ),
        html.Div(id="insights-gate"),
    ]
)


def _admin_content():
    return html.Div(
        [
            html.Div(id="insights-usage-cards"),
            html.Hr(),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H5("Retailer Reliability", className="mb-2"),
                            html.P(
                                "How often each retailer couldn't fulfill an order - useful for "
                                "renegotiating or switching suppliers.",
                                className="text-muted small",
                            ),
                            html.Div(id="retailer-reliability-table"),
                        ],
                        md=7,
                    ),
                    dbc.Col(
                        [
                            html.H5("Team Activity", className="mb-2"),
                            html.P("Uploads and rough API usage per person.", className="text-muted small"),
                            html.Div(id="user-activity-table"),
                        ],
                        md=5,
                    ),
                ],
                className="mb-3",
            ),
            dcc.Graph(id="retailer-shortage-rate-chart", config={"displayModeBar": False}),
        ]
    )


@callback(Output("insights-gate", "children"), Input("current-user-store", "data"))
def gate_insights(current_user):
    if not is_admin_user(current_user):
        return dbc.Alert(
            "🔒 Insights is for admins only. Pick your name in the top-right - if you should have "
            "admin access, ask an admin to grant it on the Settings page.",
            color="warning",
        )
    return _admin_content()


@callback(Output("insights-usage-cards", "children"), Input("insights-refresh", "n_intervals"))
def update_usage_cards(_):
    usage = get_groq_usage_today()
    stats = get_dashboard_stats()

    def card(title, value, color, icon):
        return dbc.Card(
            dbc.CardBody(
                [
                    html.Div(icon, className="fs-2"),
                    html.H3(value, className="mb-0 mt-2"),
                    html.Div(title, className="text-muted small"),
                ]
            ),
            className=f"border-start border-{color} border-4 shadow-sm h-100",
        )

    cards = [
        card("Uploads Today", usage["uploads_today"], "primary", "📤"),
        card("API Tokens Used Today", f"{usage['tokens_today']:,}", "info", "🔢"),
        card("Failed Uploads (all time)", stats["failed_uploads"], "danger", "⚠️"),
    ]
    return dbc.Row([dbc.Col(c, md=4, className="mb-3") for c in cards])


@callback(Output("retailer-reliability-table", "children"), Input("insights-refresh", "n_intervals"))
def update_retailer_reliability(_):
    data = get_retailer_reliability()
    if not data:
        return dbc.Alert("No completed orders yet.", color="info")
    df = pd.DataFrame(data)
    return dag.AgGrid(
        rowData=df.to_dict("records"),
        columnDefs=[
            {"field": "retailer", "headerName": "Retailer", "minWidth": 160},
            {"field": "order_count", "headerName": "Orders", "maxWidth": 100},
            {"field": "shortage_rows", "headerName": "Shortage Rows", "maxWidth": 130},
            {"field": "shortage_qty", "headerName": "Shortage Qty", "maxWidth": 130},
            {"field": "shortage_rate_pct", "headerName": "Shortage Rate %", "maxWidth": 140},
            {"field": "last_order", "headerName": "Last Order"},
        ],
        columnSize="responsiveSizeToFit",
        defaultColDef={"sortable": True, "filter": True, "resizable": True},
        dashGridOptions={"pagination": True, "paginationPageSize": 10},
        style={"height": "340px"},
    )


@callback(Output("user-activity-table", "children"), Input("insights-refresh", "n_intervals"))
def update_user_activity(_):
    data = get_user_activity()
    if not data:
        return dbc.Alert("No attributed uploads yet - uploads made before a name was picked won't show here.", color="info")
    df = pd.DataFrame(data)
    return dag.AgGrid(
        rowData=df.to_dict("records"),
        columnDefs=[
            {"field": "uploaded_by", "headerName": "Person", "minWidth": 140},
            {"field": "uploads", "headerName": "Uploads", "maxWidth": 100},
            {"field": "tokens_used", "headerName": "Tokens Used", "maxWidth": 130},
            {"field": "last_upload", "headerName": "Last Upload"},
        ],
        columnSize="responsiveSizeToFit",
        defaultColDef={"sortable": True, "filter": True, "resizable": True},
        dashGridOptions={"pagination": True, "paginationPageSize": 10},
        style={"height": "340px"},
    )


@callback(Output("retailer-shortage-rate-chart", "figure"), Input("insights-refresh", "n_intervals"))
def update_shortage_rate_chart(_):
    data = get_retailer_reliability()
    if not data:
        return empty_fig("No completed orders yet")
    df = pd.DataFrame(data).sort_values("shortage_rate_pct", ascending=True)
    fig = px.bar(df, x="shortage_rate_pct", y="retailer", orientation="h", text="shortage_rate_pct")
    fig.update_traces(marker_color=COLORWAY[2], texttemplate="%{text:.0f}%", textposition="outside")
    fig.update_layout(xaxis_title="Shortage rate (% of orders with a missing item)", yaxis_title="")
    return style_fig(fig, title="Retailer Shortage Rate", height=380)
