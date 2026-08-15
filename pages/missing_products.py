import dash
from dash import html, dcc, callback, Output, Input
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import pandas as pd

from services.aggregator import get_aggregated_products, get_product_history

dash.register_page(__name__, path="/missing-products", name="Missing Products")

layout = html.Div(
    [
        html.H3("Missing Products (Aggregated)", className="mb-3"),
        dcc.Interval(id="mp-refresh", interval=6000, n_intervals=0),
        html.Div(id="mp-grid-container"),
        html.Hr(),
        html.Div(id="mp-history"),
    ]
)


@callback(Output("mp-grid-container", "children"), Input("mp-refresh", "n_intervals"))
def render_grid(_):
    data = get_aggregated_products()
    if not data:
        return dbc.Alert(
            "No accepted missing products yet. Upload sheets or clear the Review Queue.",
            color="info",
        )
    df = pd.DataFrame(data)
    df["last_seen"] = df["last_seen"].dt.strftime("%d %B %Y %H:%M:%S")
    return dag.AgGrid(
        id="mp-grid",
        rowData=df.to_dict("records"),
        columnDefs=[
            {"field": "product_alias", "headerName": "Product Alias","minWidth": 300,
                    "maxWidth": 300,},
            {"field": "total_required_quantity", "headerName": "Total Qty","minWidth": 150,
                    "maxWidth": 150,},
            {"field": "times_missing", "headerName": "Times Missing","minWidth": 150,
                    "maxWidth": 150,},
            {"field": "last_retailer", "headerName": "Last Retailer"},
            {"field": "last_seen", "headerName": "Last Seen"},
        ],
        columnSize="responsiveSizeToFit",
        defaultColDef={"sortable": True, "filter": True, "resizable": True},
        dashGridOptions={
            "rowSelection": "single",
            "pagination": True,
            "paginationPageSize": 20,
        },
        style={"height": "600px"},
    )


@callback(Output("mp-history", "children"), Input("mp-grid", "selectedRows"))
def show_history(selected_rows):
    if not selected_rows:
        return ""
    alias = selected_rows[0]["product_alias"]
    history = get_product_history(alias)
    df = pd.DataFrame(history)
    if df.empty:
        return ""
    df["date"] = df["date"].astype(str)
    return html.Div(
        [
            html.H5(f"History for {alias}"),
            dag.AgGrid(
                rowData=df.to_dict("records"),
                columnDefs=[{"field": c} for c in df.columns],
                defaultColDef={"sortable": True, "filter": True, "resizable": True},
                style={"height": "300px"},
            ),
        ]
    )
