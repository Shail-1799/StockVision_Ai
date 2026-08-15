import dash
from dash import html, dcc, callback, Output, Input, State, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import pandas as pd

from services.aggregator import (
    get_all_missing_products,
    update_missing_product_field,
    delete_missing_products,
    add_manual_row,
)

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
    {"field": "retailer", "headerName": "Retailer Name", "editable": True, "minWidth": 300,},
    {"field": "row_sr_no", "headerName": "Sr No.", "editable": True,  "minWidth": 100, "maxWidth": 100,},
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
    # {"field": "filename", "headerName": "Source File", "editable": False},
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
            "got wrong. Use '+ Add Row' to type in a shortage manually.",
            className="text-muted",
        ),
        dbc.ButtonGroup(
            [
                dbc.Button("➕ Add Row", id="data-add-row-btn", color="primary"),
                dbc.Button("🗑️ Delete Selected", id="data-delete-btn", color="danger", outline=True),
            ],
            className="mb-3",
        ),
        html.Div(id="data-save-toast"),
        dcc.Store(id="data-refresh-trigger", data=0),
        html.Div(id="data-grid-container"),
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
            # "paginationPageSize": 25,
            "stopEditingWhenCellsLoseFocus": True,
        },
        style={"height": "600px"},
    )


@callback(
    Output("data-save-toast", "children"),
    Input("data-grid", "cellValueChanged"),
    prevent_initial_call=True,
)
def on_cell_edit(changed):
    if not changed:
        return dash.no_update
    change = changed[0] if isinstance(changed, list) else changed
    row_id = change["data"]["id"]
    field = change["colId"]
    new_value = change["value"]
    ok = update_missing_product_field(row_id, field, new_value)
    if ok:
        return dbc.Alert("Saved.", color="success", duration=1500, className="py-1 px-2 mb-2")
    return dbc.Alert("Could not save that value.", color="warning", duration=2500, className="py-1 px-2 mb-2")


@callback(
    Output("data-refresh-trigger", "data"),
    Input("data-add-row-btn", "n_clicks"),
    Input("data-delete-btn", "n_clicks"),
    State("data-grid", "selectedRows"),
    State("data-refresh-trigger", "data"),
    prevent_initial_call=True,
)
def on_add_or_delete(add_clicks, delete_clicks, selected_rows, current_trigger):
    triggered = ctx.triggered_id
    if triggered == "data-add-row-btn":
        add_manual_row()
    elif triggered == "data-delete-btn":
        if selected_rows:
            ids = [r["id"] for r in selected_rows]
            delete_missing_products(ids)
    return (current_trigger or 0) + 1
