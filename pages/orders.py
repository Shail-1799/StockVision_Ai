import dash
from dash import html, dcc, callback, Output, Input, State
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import pandas as pd

from database.db import session_scope
from database.models import ImageRecord, OrderRecord, MissingProduct
from services.aggregator import update_missing_product_field, get_failed_images
from services.processor import retry_failed_image
from components.media import media_url

dash.register_page(__name__, path="/orders", name="Orders")

layout = html.Div(
    [
        html.H3("Orders", className="mb-3"),
        dcc.Interval(id="orders-refresh", interval=6000, n_intervals=0),
        html.Div(id="failed-uploads-panel", className="mb-3"),
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
                    "uploaded_by": img.uploaded_by or "",
                    "uploaded": img.upload_date.strftime("%Y-%m-%d %H:%M") if img.upload_date else "",
                }
            )
        return pd.DataFrame(data)


@callback(Output("failed-uploads-panel", "children"), Input("orders-refresh", "n_intervals"))
def render_failed_panel(_):
    failed = get_failed_images()
    if not failed:
        return ""
    rows = [
        html.Tr(
            [
                html.Td(f["filename"]),
                html.Td(f["retailer"]),
                html.Td(f["uploaded_by"] or "-"),
                html.Td(f["upload_date"]),
                html.Td(f["error_message"][:80] + ("…" if len(f["error_message"]) > 80 else ""), className="small text-muted"),
                html.Td(dbc.Button("Retry", id={"type": "retry-single", "index": f["id"]}, size="sm", color="warning", outline=True)),
            ]
        )
        for f in failed
    ]
    return dbc.Card(
        dbc.CardBody(
            [
                dbc.Row(
                    [
                        dbc.Col(html.H5(f"⚠️ {len(failed)} Failed Upload(s)", className="mb-0"), md=8),
                        dbc.Col(
                            dbc.Button("🔁 Retry All Failed", id="retry-all-failed-btn", color="warning", size="sm"),
                            md=4,
                            className="text-end",
                        ),
                    ],
                    className="mb-2",
                ),
                dbc.Table(
                    [html.Thead(html.Tr([html.Th(h) for h in ["File", "Retailer", "By", "Uploaded", "Error", ""]]))]
                    + [html.Tbody(rows)],
                    bordered=False,
                    hover=True,
                    size="sm",
                ),
                html.Div(id="retry-result", className="mt-1"),
            ]
        ),
        className="shadow-sm border-warning",
    )


@callback(
    Output("retry-result", "children"),
    Output("orders-refresh", "n_intervals", allow_duplicate=True),
    Input("retry-all-failed-btn", "n_clicks"),
    Input({"type": "retry-single", "index": dash.ALL}, "n_clicks"),
    State("orders-refresh", "n_intervals"),
    prevent_initial_call=True,
)
def handle_retry(all_clicks, single_clicks, current_n):
    triggered = dash.ctx.triggered_id
    if triggered == "retry-all-failed-btn":
        failed = get_failed_images()
        ok_count = 0
        for f in failed:
            result = retry_failed_image(f["id"])
            if not result.get("error"):
                ok_count += 1
        return (
            dbc.Alert(f"Retried {len(failed)} - {ok_count} succeeded, {len(failed) - ok_count} still failed.", color="info"),
            (current_n or 0) + 1,
        )
    if isinstance(triggered, dict) and triggered.get("type") == "retry-single":
        image_id = triggered["index"]
        result = retry_failed_image(image_id)
        if result.get("error"):
            return dbc.Alert(f"Still failing: {result['error']}", color="danger", duration=4000), (current_n or 0) + 1
        return dbc.Alert(f"✅ Recovered - {result['rows_found']} row(s) found.", color="success", duration=3000), (current_n or 0) + 1
    return dash.no_update, dash.no_update


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
            {"field": "uploaded_by", "headerName": "Uploaded By", "maxWidth": 140},
            {"field": "uploaded", "headerName": "Uploaded"},
        ],
        defaultColDef={
            "sortable": True,
            "filter": True,
            "floatingFilter": True,
            "resizable": True,
        },
        dashGridOptions={
            "rowSelection": "single",
            "pagination": True,
            "paginationPageSize": 15,
        },
        style={"height": "400px"},
    )


@callback(Output("order-detail", "children"), Input("orders-grid", "selectedRows"))
def show_order_detail(selected_rows):
    if not selected_rows:
        return ""
    order_id = selected_rows[0]["order_id"]
    image_id = selected_rows[0]["image_id"]
    with session_scope() as s:
        rows = s.query(MissingProduct).filter(MissingProduct.order_id == order_id).all()
        img = s.get(ImageRecord, image_id)
        img_url = media_url(img.display_path or img.filepath) if img else None
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

    grid = (
        dag.AgGrid(
            id="order-detail-grid",
            rowData=detail_df.to_dict("records"),
            columnDefs=editable_defs,
            defaultColDef={
                "sortable": True,
                "filter": True,
                "floatingFilter": True,
                "resizable": True,
            },
            dashGridOptions={"stopEditingWhenCellsLoseFocus": True},
            style={"height": "300px"},
        )
        if not detail_df.empty
        else dbc.Alert("No X-marked rows extracted for this order.", color="secondary")
    )

    return html.Div(
        [
            html.H5(f"Detected rows for Order #{order_id} - click any cell to fix it"),
            dbc.Row(
                [
                    dbc.Col(grid, md=7),
                    dbc.Col(
                        html.Img(src=img_url, style={"width": "100%", "borderRadius": "6px"})
                        if img_url
                        else dbc.Alert("No source photo for this order.", color="secondary"),
                        md=5,
                    ),
                ]
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
    ok, _old = update_missing_product_field(row_id, field, new_value)
    if ok:
        return dbc.Alert("Saved.", color="success", duration=1500, className="py-1 px-2 mb-0")
    return dbc.Alert("Could not save.", color="warning", duration=2500, className="py-1 px-2 mb-0")
