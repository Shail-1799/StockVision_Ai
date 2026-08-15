import dash
from dash import html, dcc, callback, Output, Input
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import pandas as pd

from database.db import session_scope
from database.models import ImageRecord, OrderRecord, MissingProduct
from services.aggregator import update_missing_product_field

dash.register_page(__name__, path="/orders", name="Orders")

layout = html.Div(
    [
        html.H3("Orders", className="mb-3"),
        dcc.Interval(id="orders-refresh", interval=6000, n_intervals=0),
        html.Div(id="orders-grid-container"),
        html.Hr(),
        html.Div(id="order-detail"),
    ]
)


def _load_orders_df() -> pd.DataFrame:
    with session_scope() as s:
        rows = (
            s.query(OrderRecord, ImageRecord)
            .join(ImageRecord, OrderRecord.image_id == ImageRecord.id)
            .order_by(OrderRecord.created_at.desc())
            .all()
        )
        data = []
        for o, img in rows:
            row_count = (
                s.query(MissingProduct)
                .filter(MissingProduct.order_id == o.id)
                .count()
            )
            data.append(
                {
                    "order_id": o.id,
                    "image_id": img.id,
                    "filename": img.filename,
                    "retailer": o.retailer_name,
                    "status": img.processing_status,
                    "rows_found": row_count,
                    "uploaded": img.upload_date.strftime("%Y-%m-%d %H:%M") if img.upload_date else "",
                }
            )
        return pd.DataFrame(data)


@callback(Output("orders-grid-container", "children"), Input("orders-refresh", "n_intervals"))
def render_orders_grid(_):
    df = _load_orders_df()
    if df.empty:
        return dbc.Alert("No orders uploaded yet. Go to Upload to get started.", color="info")

    return dag.AgGrid(
        id="orders-grid",
        rowData=df.to_dict("records"),
        columnDefs=[
            {"field": "order_id", "headerName": "Order ID", "maxWidth": 110},
            {"field": "filename", "headerName": "File"},
            {"field": "retailer", "headerName": "Retailer"},
            {"field": "status", "headerName": "Status", "maxWidth": 120},
            {"field": "rows_found", "headerName": "X-Rows Found", "maxWidth": 140},
            {"field": "uploaded", "headerName": "Uploaded"},
        ],
        defaultColDef={"sortable": True, "filter": True, "resizable": True},
        dashGridOptions={"rowSelection": "single", "pagination": True, "paginationPageSize": 15},
        style={"height": "400px"},
    )


@callback(Output("order-detail", "children"), Input("orders-grid", "selectedRows"))
def show_order_detail(selected_rows):
    if not selected_rows:
        return ""
    order_id = selected_rows[0]["order_id"]
    with session_scope() as s:
        rows = s.query(MissingProduct).filter(MissingProduct.order_id == order_id).all()
        detail_df = pd.DataFrame(
            [
                {
                    "id": r.id,
                    "row_sr_no": r.row_sr_no,
                    "product_alias": r.product_alias,
                    "required_quantity": r.required_quantity,
                    "ocr_confidence": round(r.ocr_confidence, 2),
                    "cross_confidence": round(r.cross_confidence, 2),
                    "status": r.status,
                    "raw_row_text": r.raw_row_text,
                }
                for r in rows
            ]
        )

    if detail_df.empty:
        return dbc.Alert("No X-marked rows extracted for this order.", color="secondary")

    editable_defs = [
        {"field": "id", "headerName": "ID", "editable": False, "maxWidth": 80},
        {"field": "row_sr_no", "headerName": "Sr", "editable": True, "maxWidth": 90},
        {"field": "product_alias", "headerName": "Product Alias", "editable": True},
        {"field": "required_quantity", "headerName": "Qty", "editable": True, "maxWidth": 100},
        {"field": "ocr_confidence", "headerName": "OCR Conf", "editable": True, "maxWidth": 110},
        {"field": "cross_confidence", "headerName": "Cross Conf", "editable": True, "maxWidth": 110},
        {
            "field": "status",
            "headerName": "Status",
            "editable": True,
            "maxWidth": 130,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": ["accepted", "pending", "rejected"]},
        },
        {"field": "raw_row_text", "headerName": "Raw Row", "editable": True, "minWidth": 200},
    ]

    return html.Div(
        [
            html.H5(f"Detected rows for Order #{order_id} - click any cell to fix it"),
            dag.AgGrid(
                id="order-detail-grid",
                rowData=detail_df.to_dict("records"),
                columnDefs=editable_defs,
                defaultColDef={"sortable": True, "filter": True, "resizable": True},
                dashGridOptions={"stopEditingWhenCellsLoseFocus": True},
                style={"height": "300px"},
            ),
            html.Div(id="order-detail-save-toast", className="mt-1"),
        ]
    )


@callback(
    Output("order-detail-save-toast", "children"),
    Input("order-detail-grid", "cellValueChanged"),
    prevent_initial_call=True,
)
def on_order_detail_edit(changed):
    if not changed:
        return dash.no_update
    change = changed[0] if isinstance(changed, list) else changed
    row_id = change["data"]["id"]
    field = change["colId"]
    new_value = change["value"]
    ok = update_missing_product_field(row_id, field, new_value)
    if ok:
        return dbc.Alert("Saved.", color="success", duration=1500, className="py-1 px-2 mb-0")
    return dbc.Alert("Could not save.", color="warning", duration=2500, className="py-1 px-2 mb-0")
