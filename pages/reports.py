from pathlib import Path

import dash
from dash import html, dcc, callback, Output, Input, State
import dash_bootstrap_components as dbc

from services.exporter import export_to_excel
from services.product_master_import import import_product_master
import config

dash.register_page(__name__, path="/reports", name="Reports")

layout = html.Div(
    [
        html.H3("Reports", className="mb-3"),
        dbc.Card(
            dbc.CardBody(
                [
                    html.H5("Export Purchase List"),
                    html.P(
                        "Generates an Excel workbook: Sheet 1 is the aggregated next-purchase-order "
                        "summary (rounded up to each product's MOQ where one is set), Sheet 2 is the "
                        "full detailed history.",
                        className="text-muted",
                    ),
                    dbc.Button("📥 Export to Excel", id="export-btn", color="primary"),
                    dcc.Download(id="download-export"),
                    html.Div(id="export-result", className="mt-3"),
                ]
            ),
            className="mb-4 shadow-sm",
        ),
        dbc.Card(
            dbc.CardBody(
                [
                    html.H5("Import Product Master (optional)"),
                    html.P(
                        "Upload a CSV/Excel with columns: Product Alias, Product Name, "
                        "Brand, Category, MRP, Current Stock, MOQ. Used to validate/auto-correct "
                        "OCR'd aliases and to round purchase orders up to a minimum order quantity.",
                        className="text-muted",
                    ),
                    dcc.Upload(
                        id="master-upload",
                        children=html.Div(["Drag & drop or ", html.A("click to browse")]),
                        style={
                            "width": "100%",
                            "height": "70px",
                            "lineHeight": "70px",
                            "borderWidth": "2px",
                            "borderStyle": "dashed",
                            "borderRadius": "8px",
                            "textAlign": "center",
                        },
                        accept=".csv,.xlsx,.xls",
                    ),
                    html.Div(id="master-import-result", className="mt-3"),
                ]
            ),
            className="shadow-sm",
        ),
    ]
)


@callback(
    Output("export-result", "children"),
    Output("download-export", "data"),
    Input("export-btn", "n_clicks"),
    prevent_initial_call=True,
)
def do_export(n_clicks):
    try:
        path = export_to_excel()
        return (
            dbc.Alert("✅ Export ready - downloading now.", color="success"),
            dcc.send_file(path),
        )
    except Exception as e:
        return dbc.Alert(f"❌ Export failed: {e}", color="danger"), dash.no_update


@callback(
    Output("master-import-result", "children"),
    Input("master-upload", "contents"),
    State("master-upload", "filename"),
    prevent_initial_call=True,
)
def do_import(contents, filename):
    import base64

    if not contents:
        return dash.no_update
    _, content_string = contents.split(",", 1)
    decoded = base64.b64decode(content_string)
    tmp_path = config.UPLOADS_DIR / f"master_{filename}"
    with open(tmp_path, "wb") as f:
        f.write(decoded)
    try:
        result = import_product_master(str(tmp_path))
        return dbc.Alert(
            f"✅ Product master updated: {result['inserted']} new, {result['updated']} updated.",
            color="success",
        )
    except Exception as e:
        return dbc.Alert(f"❌ Import failed: {e}", color="danger")
