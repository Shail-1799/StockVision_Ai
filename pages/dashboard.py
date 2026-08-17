import dash
from dash import html, dcc, callback, Output, Input
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from services.aggregator import (
    get_dashboard_stats,
    get_daily_trend,
    get_retailer_distribution,
    get_top_missing_products,
    get_ocr_confidence_histogram,
    get_reorder_alerts,
)
from components.charts import style_fig, empty_fig, COLORWAY

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
        dcc.Interval(id="dashboard-refresh", interval=8000, n_intervals=0),
        html.H3("Dashboard", className="mb-3"),
        html.Div(id="stats-cards"),
        html.Hr(),
        dbc.Row(
            [
                dbc.Col(dcc.Graph(id="daily-trend-chart", config={"displayModeBar": False}), md=6),
                dbc.Col(dcc.Graph(id="retailer-distribution-chart", config={"displayModeBar": False}), md=6),
            ],
            className="mb-3",
        ),
        dbc.Row(
            [
                dbc.Col(dcc.Graph(id="top-missing-chart", config={"displayModeBar": False}), md=8),
                dbc.Col(dcc.Graph(id="ocr-confidence-chart", config={"displayModeBar": False}), md=4),
            ],
            className="mb-3",
        ),
        html.Hr(),
        html.H5("🔥 Recurring Shortages - Consider Restocking", className="mb-2"),
        html.P(
            "Products that have shown up as unavailable repeatedly, not just once - "
            "these are the ones worth a permanent stock-level fix rather than a one-off order.",
            className="text-muted small",
        ),
        html.Div(id="reorder-alerts-table"),
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
        stat_card("Failed Uploads", s["failed_uploads"], "danger", "⚠️"),
    ]
    return dbc.Row([dbc.Col(c, md=True, xs=6, className="mb-3") for c in cards])


@callback(Output("daily-trend-chart", "figure"), Input("dashboard-refresh", "n_intervals"))
def update_daily_trend(_):
    data = get_daily_trend()
    if not data:
        return empty_fig("No shortages recorded yet")
    df = pd.DataFrame(data)
    fig = px.area(df, x="day", y="qty", markers=True)
    fig.update_traces(line=dict(width=3, color=COLORWAY[0]), fillcolor="rgba(44,62,80,0.08)")
    return style_fig(fig, title="Daily Missing Qty Trend")


@callback(Output("retailer-distribution-chart", "figure"), Input("dashboard-refresh", "n_intervals"))
def update_retailer_dist(_):
    data = get_retailer_distribution()
    if not data:
        return empty_fig("No retailer data yet")
    df = pd.DataFrame(data).sort_values("qty", ascending=True)
    fig = px.bar(df, x="qty", y="retailer", orientation="h", text="qty")
    fig.update_traces(marker_color=COLORWAY[0], texttemplate="%{text:.0f}", textposition="outside")
    fig.update_layout(yaxis_title="", xaxis_title="Missing Qty")
    return style_fig(fig, title="Missing Qty by Retailer")


@callback(Output("top-missing-chart", "figure"), Input("dashboard-refresh", "n_intervals"))
def update_top_missing(_):
    data = get_top_missing_products(10)
    if not data:
        return empty_fig("No missing products yet")
    df = pd.DataFrame(data).sort_values("total_required_quantity", ascending=True)
    fig = px.bar(df, x="total_required_quantity", y="product_alias", orientation="h", text="total_required_quantity")
    fig.update_traces(marker_color=COLORWAY[1], texttemplate="%{text:.0f}", textposition="outside")
    fig.update_layout(yaxis_title="", xaxis_title="Total Qty")
    return style_fig(fig, title="Top 10 Missing Products", height=380)


@callback(Output("ocr-confidence-chart", "figure"), Input("dashboard-refresh", "n_intervals"))
def update_ocr_confidence(_):
    data = get_ocr_confidence_histogram()
    total = sum(d["count"] for d in data)
    if not total:
        return empty_fig("No extractions yet")
    df = pd.DataFrame(data)
    colors = ["#e74c3c", "#e74c3c", "#f39c12", "#18bc9c", "#18bc9c"]
    fig = go.Figure(go.Bar(x=df["bucket"], y=df["count"], marker_color=colors, text=df["count"], textposition="outside"))
    fig.update_layout(xaxis_title="OCR confidence", yaxis_title="Rows")
    return style_fig(fig, title="OCR Confidence Distribution", height=380)


@callback(Output("reorder-alerts-table", "children"), Input("dashboard-refresh", "n_intervals"))
def update_reorder_alerts(_):
    data = get_reorder_alerts()
    if not data:
        return dbc.Alert("No recurring shortages yet - nothing has been missing 3+ times.", color="success")
    df = pd.DataFrame(data)
    if "last_seen" in df.columns:
        df["last_seen"] = df["last_seen"].apply(lambda d: d.strftime("%d %B %Y") if hasattr(d, "strftime") else str(d))
    return dag.AgGrid(
        rowData=df.to_dict("records"),
        columnDefs=[
            {"field": "product_alias", "headerName": "Product Alias", "minWidth": 220},
            {
                "field": "total_required_quantity",
                "headerName": "Total Qty",
                "maxWidth": 130,
            },
            {"field": "times_missing", "headerName": "Times Missing", "maxWidth": 140},
            {"field": "last_retailer", "headerName": "Last Retailer"},
            {"field": "last_seen", "headerName": "Last Seen"},
        ],
        columnSize="responsiveSizeToFit",
        defaultColDef={
            "sortable": True,
            "filter": True,
            "floatingFilter": True,
            "resizable": True,
        },
        dashGridOptions={"pagination": True, "paginationPageSize": 10},
        style={"height": "320px"},
        className="ag-theme-alpine",
    )
