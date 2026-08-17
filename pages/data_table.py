import dash
from dash import html, dcc, callback, Output, Input, State, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import pandas as pd

from services.aggregator import (
    get_all_missing_products,
    get_missing_product_with_image,
    update_missing_product_field,
    delete_missing_products,
    add_manual_row,
)
from components.media import media_url

dash.register_page(__name__, path="/data", name="All Records")

COLUMN_DEFS = [
    {
        "field": "id",
        "headerName": "Row ID",
        "maxWidth": 100,
        "editable": False,
        "checkboxSelection": True,
    },
    {
        "field": "order_id",
        "headerName": "Order No.",
        "editable": True,
        "minWidth": 150,
        "maxWidth": 150,
    },
    {
        "field": "order_date",
        "headerName": "Order Date",
        "editable": True,
        "minWidth": 150,
        "maxWidth": 150,
    },
    {"field": "retailer", "headerName": "Retailer Name", "editable": True, "minWidth": 260},
    {"field": "row_sr_no", "headerName": "Sr No.", "editable": True, "minWidth": 100, "maxWidth": 100},
    {
        "field": "product_alias",
        "headerName": "Product Alias",
        "editable": True,
        "minWidth": 150,
    },
    {
        "field": "required_quantity",
        "headerName": "Qty",
        "editable": True,
        "minWidth": 100,
        "maxWidth": 100,
    },
    {"field": "uploaded_by", "headerName": "Uploaded By", "editable": False, "minWidth": 130},
    {
        "field": "created_at",
        "headerName": "Captured At",
        "editable": False,
        "minWidth": 150,
    },
]

layout = html.Div(
    [
        html.H3("All Records - Editable", className="mb-2"),
        html.P(
            "Every field here is editable, just like a spreadsheet - fix anything the AI "
            "got wrong. Use '+ Add Row' to type in a shortage manually. Select a row to "
            "verify it against the original photo below.",
            className="text-muted",
        ),
        dbc.ButtonGroup(
            [
                dbc.Button("➕ Add Row", id="data-add-row-btn", color="primary"),
                dbc.Button("🗑️ Delete Selected", id="data-delete-btn", color="danger", outline=True),
                dbc.Button("↩️ Undo Last Edit", id="data-undo-btn", color="secondary", outline=True),
            ],
            className="mb-3",
        ),
        html.Div(id="data-save-toast"),
        dcc.Store(id="data-refresh-trigger", data=0),
        dcc.Store(id="data-last-edit", data=None),  # {"id", "field", "old_value"}
        html.Div(id="data-grid-container"),
        html.Hr(),
        html.Div(id="data-verify-panel"),
    ]
)


def _load_df():
    data = get_all_missing_products()
    if not data:
        return pd.DataFrame(columns=[c["field"] for c in COLUMN_DEFS])
    return pd.DataFrame(data)


@callback(
    Output("data-grid-container", "children"),
    Input("data-refresh-trigger", "data"),
)
def render_grid(_):
    # Always render the grid (even empty) so component IDs stay stable for
    # the add/delete callback's State lookups - AG Grid shows its own
    # "no rows" placeholder when empty.
    df = _load_df()
    return dag.AgGrid(
        id="data-grid",
        rowData=df.sort_values(by="id", ascending=False).to_dict("records"),
        columnDefs=COLUMN_DEFS,
        defaultColDef={"sortable": True, "filter": True, "resizable": True},
        columnSize="responsiveSizeToFit",
        dashGridOptions={
            "rowSelection": "multiple",
            "pagination": False,
            "stopEditingWhenCellsLoseFocus": True,
        },
        style={"height": "600px"},
    )


@callback(
    Output("data-save-toast", "children"),
    Output("data-last-edit", "data"),
    Input("data-grid", "cellValueChanged"),
    prevent_initial_call=True,
)
def on_cell_edit(changed):
    if not changed:
        return dash.no_update, dash.no_update
    change = changed[0] if isinstance(changed, list) else changed
    row_id = change["data"]["id"]
    field = change["colId"]
    new_value = change["value"]
    ok, old_value = update_missing_product_field(row_id, field, new_value)
    if ok:
        toast = dbc.Alert("Saved.", color="success", duration=1500, className="py-1 px-2 mb-2")
        return toast, {"id": row_id, "field": field, "old_value": old_value}
    return dbc.Alert("Could not save that value.", color="warning", duration=2500, className="py-1 px-2 mb-2"), dash.no_update


@callback(
    Output("data-refresh-trigger", "data"),
    Output("data-save-toast", "children", allow_duplicate=True),
    Input("data-add-row-btn", "n_clicks"),
    Input("data-delete-btn", "n_clicks"),
    Input("data-undo-btn", "n_clicks"),
    State("data-grid", "selectedRows"),
    State("data-refresh-trigger", "data"),
    State("data-last-edit", "data"),
    prevent_initial_call=True,
)
def on_add_delete_undo(add_clicks, delete_clicks, undo_clicks, selected_rows, current_trigger, last_edit):
    triggered = ctx.triggered_id
    toast = dash.no_update
    if triggered == "data-add-row-btn":
        add_manual_row()
    elif triggered == "data-delete-btn":
        if selected_rows:
            ids = [r["id"] for r in selected_rows]
            delete_missing_products(ids)
    elif triggered == "data-undo-btn":
        if last_edit:
            ok, _ = update_missing_product_field(last_edit["id"], last_edit["field"], last_edit["old_value"])
            toast = dbc.Alert(
                "Reverted." if ok else "Could not undo - that row may have been deleted.",
                color="success" if ok else "warning",
                duration=2000,
                className="py-1 px-2 mb-2",
            )
        else:
            toast = dbc.Alert("Nothing to undo yet.", color="secondary", duration=2000, className="py-1 px-2 mb-2")
    return (current_trigger or 0) + 1, toast


@callback(
    Output("data-verify-panel", "children"),
    Input("data-grid", "selectedRows"),
    prevent_initial_call=True,
)
def show_verify_panel(selected_rows):
    if not selected_rows:
        return ""
    row_id = selected_rows[0]["id"]
    detail = get_missing_product_with_image(row_id)
    if not detail:
        return ""

    with_image = None
    from database.db import session_scope
    from database.models import ImageRecord

    with session_scope() as s:
        img = s.get(ImageRecord, detail["image_id"])
        img_path = (img.display_path or img.filepath) if img else None

    url = media_url(img_path) if img_path else None

    return dbc.Card(
        dbc.CardBody(
            [
                html.H5(f"Verify: {detail['product_alias']}", className="mb-3"),
                dbc.Row(
                    [
                        dbc.Col(
                            html.Img(src=url, style={"width": "100%", "borderRadius": "6px"})
                            if url
                            else dbc.Alert("No source photo available for this row (manually entered).", color="secondary"),
                            md=7,
                        ),
                        dbc.Col(
                            [
                                html.Div([html.B("Retailer: "), detail["retailer"]]),
                                html.Div([html.B("Order Date: "), detail["order_date"] or "-"]),
                                html.Div([html.B("Sr No.: "), detail["row_sr_no"] or "-"]),
                                html.Div([html.B("Qty: "), str(detail["required_quantity"])]),
                                html.Div([html.B("Raw row text: "), detail["raw_row_text"] or "-"]),
                                html.Div([html.B("OCR confidence: "), f"{detail['ocr_confidence']:.2f}"]),
                                html.Div([html.B("Cross confidence: "), f"{detail['cross_confidence']:.2f}"]),
                                html.Div([html.B("Uploaded by: "), detail["uploaded_by"] or "-"]),
                            ],
                            md=5,
                            className="small",
                        ),
                    ]
                ),
            ]
        ),
        className="shadow-sm",
    )
