import dash
from dash import html, dcc, callback, Output, Input
import dash_bootstrap_components as dbc
import plotly.express as px
import pandas as pd

from services.aggregator import (
    get_dashboard_stats,
    get_daily_trend,
    get_retailer_distribution,
    get_top_missing_products,
)

dash.register_page(__name__, path="/", name="Dashboard")


def stat_card(title, value, color="primary", icon="📦"):
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


layout = html.Div(
    [
        dcc.Interval(id="dashboard-refresh", interval=5000, n_intervals=0),
        html.H3("Dashboard", className="mb-3"),
        html.Div(id="stats-cards"),
        html.Hr(),
        dbc.Row(
            [
                dbc.Col(dcc.Graph(id="daily-trend-chart"), md=6),
                dbc.Col(dcc.Graph(id="retailer-distribution-chart"), md=6),
            ]
        ),
        dbc.Row([dbc.Col(dcc.Graph(id="top-missing-chart"), md=12)]),
    ]
)


@callback(Output("stats-cards", "children"), Input("dashboard-refresh", "n_intervals"))
def update_stats(_):
    s = get_dashboard_stats()
    cards = [
        stat_card("Images Uploaded", s["images_uploaded"], "primary", "🖼️"),
        stat_card("Orders Processed", s["orders_processed"], "success", "✅"),
        stat_card("Missing Products", s["missing_products"], "danger", "🚫"),
        stat_card("Total Missing Qty", s["total_missing_qty"], "warning", "🔢"),
        stat_card("OCR Accuracy", f"{s['ocr_accuracy_pct']}%", "info", "🎯"),
        stat_card("Pending Review", s["pending_review"], "secondary", "🕵️"),
    ]
    return dbc.Row([dbc.Col(c, md=2, className="mb-3") for c in cards])


@callback(Output("daily-trend-chart", "figure"), Input("dashboard-refresh", "n_intervals"))
def update_daily_trend(_):
    data = get_daily_trend()
    df = pd.DataFrame(data) if data else pd.DataFrame(columns=["day", "qty"])
    fig = px.line(df, x="day", y="qty", markers=True, title="Daily Missing Qty Trend")
    fig.update_layout(margin=dict(t=40, b=20))
    return fig


@callback(Output("retailer-distribution-chart", "figure"), Input("dashboard-refresh", "n_intervals"))
def update_retailer_dist(_):
    data = get_retailer_distribution()
    df = pd.DataFrame(data) if data else pd.DataFrame(columns=["retailer", "qty"])
    fig = px.pie(df, names="retailer", values="qty", title="Missing Qty by Retailer", hole=0.4)
    fig.update_layout(margin=dict(t=40, b=20))
    return fig


@callback(Output("top-missing-chart", "figure"), Input("dashboard-refresh", "n_intervals"))
def update_top_missing(_):
    data = get_top_missing_products(10)
    df = pd.DataFrame(data) if data else pd.DataFrame(columns=["product_alias", "total_required_quantity"])
    fig = px.bar(
        df,
        x="product_alias",
        y="total_required_quantity",
        text="total_required_quantity",
        title="Top 10 Missing Products",
    )
    fig.update_layout(margin=dict(t=40, b=20))
    return fig
